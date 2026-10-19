"""Garde : tout client de la lib a sa description, sauf exception nommée et motivée (`connectors/clients.yaml`).

Le dépôt lui-même doit passer ; un faux dépôt prouve que la garde refuse un client nouveau sans description et une
entrée qui ne dit plus vrai, et qu'elle accepte un client inscrit avec sa raison.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from fabrique.clients import ClientsError, check, list_clients, load, parse

CLIENTS = """\
families:
  google: one sub-package per service
described_by:
  unipile: linkedin_unipile
  google/gmail: gmail
without_description:
  wordpress: { category: not_describable, reason: "the REST root is found at call time" }
"""


def test_every_client_of_the_lib_has_its_description_or_its_reason():
    check(load())


def test_every_exception_gives_a_category_and_a_reason():
    assert all(entry.category and entry.reason for entry in load().without_description.values())


def _repo(tmp_path: pathlib.Path, clients: str = CLIENTS) -> pathlib.Path:
    """Un faux dépôt : quatre clients, dont un module et une famille, et trois descriptions."""
    for path in ("oto/tools/sellsy/__init__.py", "oto/tools/unipile/client.py", "oto/tools/wordpress/client.py",
                 "oto/tools/markdown_lint.py", "oto/tools/google/__init__.py", "oto/tools/google/gmail/lib/gmail.py",
                 "connectors/sellsy/connector.yaml", "connectors/linkedin_unipile/connector.yaml",
                 "connectors/gmail/connector.yaml"):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("", encoding="utf-8")
    (tmp_path / "connectors/clients.yaml").write_text(clients, encoding="utf-8")
    return tmp_path


def _with(clients: str, line: str, section: str = "without_description:") -> str:
    return clients.replace(section + "\n", section + "\n" + line + "\n")


def test_fake_repo_passes_once_every_client_is_named(tmp_path):
    root = _repo(tmp_path, _with(CLIENTS, '  markdown_lint.py: { category: not_a_service_client, reason: "a local check" }'))
    clients = load(root)
    assert list_clients(clients, root) == ["google/gmail", "markdown_lint.py", "sellsy", "unipile", "wordpress"]
    check(clients, root)


def test_new_client_without_description_is_refused(tmp_path):
    root = _repo(tmp_path, _with(CLIENTS, '  markdown_lint.py: { category: not_a_service_client, reason: "a local check" }'))
    (root / "oto/tools/threecx").mkdir()
    (root / "oto/tools/threecx/client.py").write_text("", encoding="utf-8")
    with pytest.raises(ClientsError, match=re.escape("client(s) without a description: threecx.")):
        check(load(root), root)


def test_new_client_listed_with_its_reason_passes(tmp_path):
    clients = _with(CLIENTS, '  markdown_lint.py: { category: not_a_service_client, reason: "a local check" }')
    root = _repo(tmp_path, _with(clients, '  threecx: { category: not_describable, reason: "a signed token on each request" }'))
    (root / "oto/tools/threecx").mkdir()
    (root / "oto/tools/threecx/client.py").write_text("", encoding="utf-8")
    check(load(root), root)


def test_new_client_of_a_family_is_a_client(tmp_path):
    root = _repo(tmp_path, _with(CLIENTS, '  markdown_lint.py: { category: not_a_service_client, reason: "a local check" }'))
    (root / "oto/tools/google/bigquery").mkdir()
    with pytest.raises(ClientsError, match=re.escape("client(s) without a description: google/bigquery.")):
        check(load(root), root)


@pytest.mark.parametrize("clients, message", [
    (_with(_with(CLIENTS, '  markdown_lint.py: { category: not_a_service_client, reason: x }'), '  zoho: { category: before_the_rule, reason: x }'),
     "without_description names 'zoho', which is no client of oto/tools"),
    (_with(_with(CLIENTS, '  markdown_lint.py: { category: not_a_service_client, reason: x }'), '  sellsy: { category: before_the_rule, reason: x }'),
     "'sellsy' now has its description: drop it from without_description"),
    (_with(_with(CLIENTS, '  markdown_lint.py: { category: not_a_service_client, reason: x }'), "  zoho: sellsy", "described_by:"),
     "described_by names 'zoho', which is no client of oto/tools nor part of one"),
    (_with(_with(CLIENTS, '  markdown_lint.py: { category: not_a_service_client, reason: x }'), "  wordpress: wp", "described_by:"),
     "described_by maps 'wordpress' to 'wp', which has no description"),
    (_with(_with(CLIENTS, '  markdown_lint.py: { category: not_a_service_client, reason: x }'), "  microsoft: a family", "families:"),
     "family 'microsoft' is no package of oto/tools"),
], ids=["unknown_exception", "stale_exception", "unknown_client", "unknown_connector", "unknown_family"])
def test_entry_that_no_longer_says_true_is_refused(tmp_path, clients, message):
    root = _repo(tmp_path, clients)
    with pytest.raises(ClientsError, match=re.escape(message)):
        check(load(root), root)


@pytest.mark.parametrize("text", [
    "families: {}\ndescribed_by: {}\n",
    "families: {}\ndescribed_by: {}\nwithout_description:\n  wordpress: { category: not_describable, reason: '' }\n",
    "families: {}\ndescribed_by: {}\nwithout_description:\n  wordpress: { category: not_describable }\n",
    "families: {}\ndescribed_by: {}\nwithout_description:\n  wordpress: 'a reason without category'\n",
    "families: {}\ndescribed_by: {}\nwithout_description:\n  wordpress: { category: later, reason: x }\n",
], ids=["missing_section", "empty_reason", "no_reason", "no_category", "unknown_category"])
def test_malformed_file_is_refused(text):
    with pytest.raises(ClientsError):
        parse(text)


# --- Une partie d'un client ----------------------------------------------------------


def _narrowed_repo(tmp_path: pathlib.Path, described_by: str) -> pathlib.Path:
    clients = _with(_with(CLIENTS, '  markdown_lint.py: { category: not_a_service_client, reason: x }'), described_by,
                    "described_by:")
    root = _repo(tmp_path, clients)
    for path in ("oto/tools/microsoft/files.py", "oto/tools/microsoft/mail.py", "connectors/microsoft/connector.yaml"):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text("", encoding="utf-8")
    return root


def test_part_of_a_client_is_its_connector_code_and_the_rest_is_not(tmp_path):
    root = _narrowed_repo(tmp_path, "  microsoft/files.py: microsoft")
    clients = load(root)
    check(clients, root)
    connectors = {"sellsy", "linkedin_unipile", "gmail", "microsoft"}
    assert clients.connectors_touched(
        ["oto/tools/microsoft/files.py", "oto/tools/microsoft/mail.py", "oto/tools/microsoft/__init__.py",
         "oto/tools/sellsy/__init__.py", "oto/tools/unipile/client.py", "oto/tools/google/gmail/lib/gmail.py"],
        connectors) == {"microsoft": ["oto/tools/microsoft/files.py"], "sellsy": ["oto/tools/sellsy/__init__.py"],
                        "linkedin_unipile": ["oto/tools/unipile/client.py"],
                        "gmail": ["oto/tools/google/gmail/lib/gmail.py"]}


@pytest.mark.parametrize("described_by, message", [
    ("  microsoft/nope.py: microsoft", "described_by names 'microsoft/nope.py', which is no client of oto/tools nor part of one"),
    ("  microsoft/files.py: microsoft\n  microsoft: microsoft", "'microsoft' has a description of its own name"),
], ids=["unknown_part", "whole_and_part"])
def test_part_that_does_not_exist_is_refused(tmp_path, described_by, message):
    root = _narrowed_repo(tmp_path, described_by)
    with pytest.raises(ClientsError, match=re.escape(message)):
        check(load(root), root)
