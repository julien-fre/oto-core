"""Les cas communs de l'authentification (`connectors/_cases/auth.yaml`), joués côté Python, une ligne par cas.

La lib ne signe la requête d'aucune description : seul le moteur du paquet de l'hôte le fait. Les cas se jouent donc ici
contre une référence écrite dans le test, qui dit la sémantique du format (« Le compte ») ; le paquet de l'hôte joue les
mêmes cas, sortis par la fabrique dans `ts/src/auth-cases.ts`, contre son moteur.
"""
from __future__ import annotations

import base64
import pathlib

import pytest
import yaml

from fabrique import auth_cases
from fabrique.descriptions import DescriptionError

LOADED = auth_cases.load()


def signed(auth: dict, values: dict) -> tuple[dict, dict]:
    """La référence : les en-têtes (noms en minuscules) et la query qu'ajoute l'authentification."""
    kind = auth["kind"]
    if kind == "basic":
        username = values[auth["username"]] if "username" in auth else ""
        token = base64.b64encode(f"{username}:{values[auth['password']]}".encode("utf-8")).decode("ascii")
        return {"authorization": f"Basic {token}"}, {}
    if kind == "bearer":
        return {"authorization": f"Bearer {values[auth['token']]}"}, {}
    if auth["in"] == "query":
        return {}, {auth["name"]: values[auth["key"]]}
    return {auth["name"].lower(): auth.get("prefix", "") + values[auth["key"]]}, {}


@pytest.mark.parametrize("case", LOADED.cases, ids=[case["name"] for case in LOADED.cases])
def test_auth_case(case):
    assert signed(case["auth"], case["values"]) == (case["headers"], case["query"])


def test_the_cases_cover_basic_without_username():
    kinds = {(case["auth"]["kind"], "username" in case["auth"]) for case in LOADED.cases}
    assert {("basic", True), ("basic", False), ("bearer", False), ("api_key", False)} <= kinds
    assert {case["auth"].get("in") for case in LOADED.cases if case["auth"]["kind"] == "api_key"} == {"header", "query"}


def _write(tmp_path: pathlib.Path, mutate) -> pathlib.Path:
    data = yaml.safe_load(auth_cases.CASES.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "auth.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def _case(data, name):
    return next(case for case in data["cases"] if case["name"] == name)


@pytest.mark.parametrize("mutate, message", [
    (lambda d: _case(d, "basic_without_username")["auth"].update(username="api_id"),
     "auth.username names 'api_id', which is not a credential field"),
    (lambda d: _case(d, "basic_with_username")["auth"].pop("password"), "does not match the description schema"),
    (lambda d: _case(d, "bearer")["values"].update(other="x"), "values give exactly one value to each credential field"),
    (lambda d: _case(d, "bearer")["headers"].update({"Authorization": "x"}), "does not match the auth cases form"),
    (lambda d: _case(d, "bearer").update(auth={"kind": "none"}), "does not match the auth cases form"),
], ids=["username_not_a_field", "basic_without_password", "value_without_field", "header_name_not_lowercase", "kind_not_signed"])
def test_a_case_is_checked_like_a_description(tmp_path, mutate, message):
    with pytest.raises(DescriptionError, match=message):
        auth_cases.load(_write(tmp_path, mutate))
