"""Gardes par commit (`fabrique/commits.py`), dans les deux sens, sur un faux dépôt git.

Chaque commit est jugé contre son premier parent : un changement de code d'un connecteur sans montée de version échoue,
avec une dispense en trailer ou une montée il passe ; un commit de publication ne regarde aucun connecteur ; une
exception en attente ne s'ajoute jamais. Le verdict d'un commit ne dépend ni de son regroupement ni d'un rejeu.
"""
from __future__ import annotations

import pathlib
import re
import subprocess

import pytest

import fabrique.commits as commits
from fabrique.commits import commits_between, dispenses, judge_commit, semver_key

CLIENTS = """\
families:
  google: one sub-package per service
described_by:
  unipile: linkedin_unipile
  microsoft/files.py: microsoft
without_description:
  common: { category: not_a_service_client, reason: shared utilities }
  zoho: { category: before_the_rule, reason: not described yet }
"""
TRAILERS = "\n\nChangelog: fixed\nCo-Authored-By: t <t@example.com>"


def _description(name: str, version: str) -> str:
    return f"connector:\n  name: {name}\n  version: {version}\nfunctions: []\n"


class Repo:
    def __init__(self, root: pathlib.Path):
        self.root = root
        self.git("init", "-q", "-b", "main")

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.root), "-c", "user.name=t", "-c", "user.email=t@example.com",
             "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args],
            check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, message: str, files: dict[str, str | None] | None = None) -> str:
        for path, text in (files or {}).items():
            target = self.root / path
            if text is None:
                target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")


BASE_FILES = {
    "connectors/clients.yaml": CLIENTS,
    "connectors/connector.schema.json": "{}\n",
    "connectors/sellsy/connector.yaml": _description("sellsy", "1.0.0"),
    "connectors/linkedin_unipile/connector.yaml": _description("linkedin_unipile", "1.1.0"),
    "connectors/microsoft/connector.yaml": _description("microsoft", "3.1.0"),
    "oto/tools/sellsy/client.py": "x = 1\n",
    "oto/tools/unipile/client.py": "x = 1\n",
    "oto/tools/microsoft/files.py": "x = 1\n",
    "oto/tools/microsoft/mail.py": "x = 1\n",
    "oto/tools/common/errors.py": "x = 1\n",
    "oto/tools/zoho/client.py": "x = 1\n",
    "fabrique/typescript.py": "x = 1\n",
    "ts/src/sellsy.ts": "// generated\n",
    "ts/package.json": '{"version": "0.0.0"}\n',
    "tests/test_sellsy_client.py": "x = 1\n",
    "pyproject.toml": 'version = "1.182.0"\n',
    "uv.lock": "version 1.182.0\n",
}


@pytest.fixture
def repo(tmp_path) -> Repo:
    r = Repo(tmp_path)
    r.base = r.commit("base" + TRAILERS, BASE_FILES)
    return r


def _judge(repo: Repo, ref: str = "HEAD"):
    return judge_commit(ref, root=repo.root)


# --- Version : commit par commit ------------------------------------------------------


def test_client_change_without_version_fails_and_says_what_to_add(repo):
    repo.commit("fix(sellsy): retry" + TRAILERS, {"oto/tools/sellsy/client.py": "x = 2\n"})
    verdict = _judge(repo)
    assert not verdict.ok
    assert verdict.failures == [
        "sellsy: code changed (oto/tools/sellsy/client.py), version unchanged: connector.version 1.0.0 → 1.0.1, "
        "or the trailer 'Version-dispense: sellsy — <reason>'"]


def test_description_change_without_version_fails(repo):
    repo.commit("feat(sellsy): a field" + TRAILERS,
                {"connectors/sellsy/connector.yaml": _description("sellsy", "1.0.0") + "# more\n"})
    assert not _judge(repo).ok


def test_client_change_with_dispense_trailer_passes(repo):
    repo.commit("refactor(sellsy): rename a local" + TRAILERS + "\nVersion-dispense: sellsy — internal rename",
                {"oto/tools/sellsy/client.py": "x = 2\n"})
    verdict = _judge(repo)
    assert verdict.ok and verdict.notes == ["sellsy 1.0.0: dispensed, internal rename (oto/tools/sellsy/client.py)"]


def test_client_change_with_version_raised_passes(repo):
    repo.commit("fix(sellsy): retry" + TRAILERS, {
        "oto/tools/sellsy/client.py": "x = 2\n", "connectors/sellsy/connector.yaml": _description("sellsy", "1.0.1")})
    assert _judge(repo).ok


def test_each_commit_is_judged_alone_whatever_the_push(repo):
    """Une montée dans un commit ne couvre pas le changement du commit suivant, poussés ensemble ou non."""
    raised = repo.commit("feat(sellsy): bump" + TRAILERS, {"connectors/sellsy/connector.yaml": _description("sellsy", "1.1.0")})
    changed = repo.commit("fix(sellsy): retry" + TRAILERS, {"oto/tools/sellsy/client.py": "x = 2\n"})
    shas, note = commits_between(repo.base, changed, root=repo.root)
    assert shas == [raised, changed] and note is None
    together = [judge_commit(sha, root=repo.root).ok for sha in shas]
    alone = [judge_commit(raised, root=repo.root).ok, judge_commit(changed, root=repo.root).ok]
    assert together == alone == [True, False]


def test_a_dispense_covers_only_the_commit_that_carries_it(repo):
    repo.commit("chore: note" + TRAILERS + "\nVersion-dispense: sellsy — nothing")
    repo.commit("fix(sellsy): retry" + TRAILERS, {"oto/tools/sellsy/client.py": "x = 2\n"})
    assert not _judge(repo).ok


def test_replayed_patch_gets_the_same_verdict(repo):
    """Même patch, autre SHA (rejeu sur une autre base) : même verdict."""
    first = repo.commit("fix(sellsy): retry" + TRAILERS, {"oto/tools/sellsy/client.py": "x = 2\n"})
    repo.git("checkout", "-q", "-b", "other", repo.base)
    repo.commit("docs: unrelated" + TRAILERS, {"README.md": "hi\n"})
    repo.git("cherry-pick", first)
    replayed = repo.git("rev-parse", "HEAD")
    assert replayed != first
    assert judge_commit(first, root=repo.root).failures == judge_commit(replayed, root=repo.root).failures != []


def test_client_part_outside_the_description_is_no_connector_code(repo):
    """Le courrier d'un paquet dont la description ne couvre que les fichiers ne vise pas cette description."""
    repo.commit("feat(microsoft): inline images in a draft" + TRAILERS, {"oto/tools/microsoft/mail.py": "x = 2\n"})
    assert _judge(repo).ok and _judge(repo).notes == []
    repo.commit("fix(microsoft): files paging" + TRAILERS, {"oto/tools/microsoft/files.py": "x = 2\n"})
    assert not _judge(repo).ok


def test_client_described_under_another_name_counts_for_its_connector(repo):
    repo.commit("fix(unipile): retry" + TRAILERS, {"oto/tools/unipile/client.py": "x = 2\n"})
    assert [f.split(":")[0] for f in _judge(repo).failures] == ["linkedin_unipile"]


def test_lowered_version_fails_even_with_a_dispense(repo):
    repo.commit("fix(sellsy): oops" + TRAILERS + "\nVersion-dispense: sellsy — mistake",
                {"connectors/sellsy/connector.yaml": _description("sellsy", "0.9.0")})
    assert _judge(repo).failures == [
        "sellsy 1.0.0 -> 0.9.0: version lowered, never dispensed (connectors/sellsy/connector.yaml)"]


def test_new_connector_needs_no_raise(repo):
    repo.commit("feat(typeform): description and client" + TRAILERS, {
        "connectors/typeform/connector.yaml": _description("typeform", "1.0.0"), "oto/tools/typeform/client.py": "x\n"})
    assert _judge(repo).ok


def test_merge_commit_is_judged_on_its_own_changes(repo):
    repo.git("checkout", "-q", "-b", "feature", repo.base)
    repo.commit("fix(sellsy): retry" + TRAILERS + "\nVersion-dispense: sellsy — comment only",
                {"oto/tools/sellsy/client.py": "x = 2\n"})
    repo.git("checkout", "-q", "main")
    repo.commit("docs: readme" + TRAILERS, {"README.md": "hi\n"})
    repo.git("merge", "-q", "--no-ff", "-m", "Merge feature" + TRAILERS, "feature")
    verdict = _judge(repo)
    assert verdict.ok and verdict.notes == ["merge commit: judged on its own changes only"]


# --- La dispense, un vrai trailer -------------------------------------------------------


def test_dispense_outside_the_trailer_block_is_refused(repo):
    repo.commit("fix(sellsy): retry\n\nVersion-dispense: sellsy — in the body" + TRAILERS,
                {"oto/tools/sellsy/client.py": "x = 2\n"})
    failures = _judge(repo).failures
    assert any("outside the trailer block" in f for f in failures) and any(f.startswith("sellsy: code changed") for f in failures)


@pytest.mark.parametrize("line", [
    "Version-dispense: sellsy",
    "Version-dispense: sellsy - a hyphen, not the dash",
    "Version-dispense: Sellsy — capital",
    "Version-dispense: sellsy —",
], ids=["no_reason", "hyphen", "capital", "empty_reason"])
def test_malformed_dispense_is_refused(line):
    found, faults = dispenses("fix: x" + TRAILERS + "\n" + line + "\n")
    assert found == {} and len(faults) == 1
    assert "expected 'Version-dispense: <connector> — <reason>'" in faults[0]


@pytest.mark.parametrize("touched", ["fabrique/typescript.py", "connectors/connector.schema.json"])
def test_global_dispense_passes_with_a_pass_over_the_format(repo, touched):
    repo.commit("feat(format): a field everywhere" + TRAILERS + "\nVersion-dispense: * — format-wide pass", {
        touched: "y\n", "connectors/sellsy/connector.yaml": _description("sellsy", "1.0.0") + "# x\n",
        "oto/tools/unipile/client.py": "x = 2\n"})
    verdict = _judge(repo)
    assert verdict.ok and len(verdict.notes) == 2


def test_global_dispense_without_a_pass_over_the_format_is_refused(repo):
    repo.commit("fix: two clients" + TRAILERS + "\nVersion-dispense: * — lazy", {
        "oto/tools/sellsy/client.py": "x = 2\n", "oto/tools/unipile/client.py": "x = 2\n"})
    failures = _judge(repo).failures
    assert failures[0].startswith("'Version-dispense: * — …' is refused: this commit touches neither")
    assert len(failures) == 3


# --- Commits de version, code commun ----------------------------------------------------


def test_release_commit_touching_only_the_lib_version_passes(repo):
    repo.commit("chore(release): v1.183.0" + TRAILERS, {
        "pyproject.toml": 'version = "1.183.0"\n', "uv.lock": "version 1.183.0\n", "ts/package.json": '{"version": "0.1.0"}\n'})
    verdict = _judge(repo)
    assert verdict.ok and verdict.notes == []


def test_shared_code_generated_output_and_tests_are_no_connector_code(repo):
    repo.commit("refactor: shared errors, fabrique, output and tests" + TRAILERS, {
        "oto/tools/common/errors.py": "x = 2\n", "fabrique/typescript.py": "x = 2\n",
        "ts/src/sellsy.ts": "// generated again\n", "tests/test_sellsy_client.py": "x = 2\n"})
    assert _judge(repo).ok


# --- Exceptions en attente : ne font que décroître --------------------------------------


@pytest.mark.parametrize("category", ["before_the_rule", "not_described_yet"])
def test_new_pending_exception_is_refused(repo, category):
    repo.commit("feat(luma): client" + TRAILERS, {
        "oto/tools/luma/client.py": "x\n",
        "connectors/clients.yaml": CLIENTS + f"  luma: {{ category: {category}, reason: not described yet }}\n"})
    assert _judge(repo).failures == [
        f"connectors/clients.yaml: 'luma' enters the pending category {category}, which only shrinks: describe the "
        "client, or name it in a principle category (not_a_service_client, not_describable, oto_service) with its reason"]


def test_moving_an_entry_into_a_pending_category_is_refused(repo):
    repo.commit("chore: reclassify" + TRAILERS, {"connectors/clients.yaml": CLIENTS.replace(
        "common: { category: not_a_service_client", "common: { category: not_described_yet")})
    assert not _judge(repo).ok


def test_new_principle_exception_and_a_removed_pending_one_pass(repo):
    repo.commit("feat: two clients" + TRAILERS, {
        "oto/tools/pdf/render.py": "x\n", "oto/tools/zoho/client.py": None,
        "connectors/clients.yaml": CLIENTS.replace("  zoho: { category: before_the_rule, reason: not described yet }\n",
                                                   "  pdf: { category: not_a_service_client, reason: local rendering }\n")})
    assert _judge(repo).ok


def test_the_commit_that_introduces_the_list_compares_nothing(tmp_path):
    repo = Repo(tmp_path)
    files = {k: v for k, v in BASE_FILES.items() if k != "connectors/clients.yaml"}
    repo.commit("base" + TRAILERS, files)
    repo.commit("ci: guards" + TRAILERS, {"connectors/clients.yaml": CLIENTS})
    verdict = _judge(repo)
    assert verdict.ok and verdict.notes == ["connectors/clients.yaml introduced by this commit: no pending list to compare"]


# --- La commande ------------------------------------------------------------------------


def test_command_judges_each_new_commit(repo, monkeypatch, capsys):
    monkeypatch.setattr(commits, "REPO", repo.root)
    repo.commit("feat(sellsy): bump" + TRAILERS, {"connectors/sellsy/connector.yaml": _description("sellsy", "1.0.1")})
    assert commits.main([repo.base, "HEAD"]) == 0
    repo.commit("fix(sellsy): retry" + TRAILERS, {"oto/tools/sellsy/client.py": "x = 2\n"})
    assert commits.main([repo.base, "HEAD"]) == 1
    out = capsys.readouterr().out
    assert re.search(r"ok   [0-9a-f]{12} feat\(sellsy\): bump", out) and re.search(r"FAIL [0-9a-f]{12} fix\(sellsy\): retry", out)


@pytest.mark.parametrize("before", ["0" * 40, "1" * 40], ids=["zeros", "absent"])
def test_unknown_base_judges_only_the_head_commit_and_says_so(repo, monkeypatch, capsys, before):
    monkeypatch.setattr(commits, "REPO", repo.root)
    repo.commit("fix(sellsy): retry" + TRAILERS, {"oto/tools/sellsy/client.py": "x = 2\n"})
    repo.commit("docs: readme" + TRAILERS, {"README.md": "hi\n"})
    assert commits.main([before, "HEAD"]) == 0
    assert "only the head commit is judged" in capsys.readouterr().out
    repo.commit("fix(sellsy): again" + TRAILERS, {"oto/tools/sellsy/client.py": "x = 3\n"})
    assert commits.main([before, "HEAD"]) == 1


def test_commit_older_than_the_list_is_judged_with_the_list_of_the_head(tmp_path, monkeypatch, capsys):
    """Une PR ouverte avant la garde : ses commits n'ont pas `connectors/clients.yaml`, la tête jugée le prête."""
    repo = Repo(tmp_path)
    monkeypatch.setattr(commits, "REPO", repo.root)
    base = repo.commit("base" + TRAILERS, {k: v for k, v in BASE_FILES.items() if k != "connectors/clients.yaml"})
    repo.commit("fix(sellsy): retry" + TRAILERS, {"oto/tools/sellsy/client.py": "x = 2\n"})
    repo.commit("ci: guards" + TRAILERS, {"connectors/clients.yaml": CLIENTS})
    assert commits.main([base, "HEAD"]) == 1
    out = capsys.readouterr().out
    assert "connectors/clients.yaml absent from this commit: judged with the one of" in out
    assert "FAIL sellsy: code changed" in out
    with pytest.raises(commits.GuardError, match="connectors/clients.yaml is missing"):
        judge_commit("HEAD~1", root=repo.root)


def test_root_commit_compares_nothing(tmp_path):
    repo = Repo(tmp_path)
    repo.commit("base" + TRAILERS, BASE_FILES)
    assert judge_commit("HEAD", root=repo.root).notes == ["root commit: nothing to compare"]


@pytest.mark.parametrize("lower, higher", [
    ("1.0.0", "1.0.1"), ("1.9.0", "1.10.0"), ("1.0.0-rc.1", "1.0.0"), ("1.0.0-alpha", "1.0.0-alpha.1"),
    ("1.0.0-2", "1.0.0-10"), ("1.0.0-beta", "1.0.0-rc"), ("1.0.0-9", "1.0.0-alpha"),
])
def test_semver_order(lower, higher):
    assert semver_key(lower) < semver_key(higher)
