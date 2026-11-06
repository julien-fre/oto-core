"""Les cas communs de la table d'erreurs (`connectors/_cases/errors.yaml`), joués côté Python, une ligne par cas.

Ils se jouent contre `oto.connectors.serve.refusal`, la lecture de la table que sert un hôte Python (le lecteur générique
d'oto 1), à la sémantique du format (`docs/conception/signal-de-refus.md`) ; le paquet de l'hôte d'oto 2 joue les mêmes
cas, sortis par la fabrique dans `ts/src/error-cases.ts`, contre son moteur.
"""
from __future__ import annotations

import pathlib

import pytest
import yaml

from fabrique import error_cases
from fabrique.descriptions import DescriptionError
from oto.connectors import serve

LOADED = error_cases.load()


def selected(errors: list[dict], answer: dict) -> dict | None:
    """L'entrée que retient `serve.refusal` pour la réponse simulée (corps JSON, ou texte), en code et marque."""
    description = {"connector": {"errors": errors}, "functions": []}
    body = answer["json"] if "json" in answer else answer["text"]
    entry = serve.refusal(description, {"name": "carrier"}, answer["status"], body)
    return None if entry is None else {"code": entry["code"], "marks_account": entry["marks_account"]}


@pytest.mark.parametrize("case", LOADED.cases, ids=[case["name"] for case in LOADED.cases])
def test_error_case(case):
    assert selected(LOADED.errors, case["answer"]) == case["entry"]


def test_the_cases_cover_both_operators():
    conditions = [entry["body"] for entry in LOADED.errors if "body" in entry]
    assert any("equals" in c for c in conditions) and any("contains" in c for c in conditions)
    answers = [case["answer"] for case in LOADED.cases]
    assert any("text" in a for a in answers) and any(not isinstance(a.get("json"), dict) for a in answers)
    assert any(case["entry"] is None for case in LOADED.cases)


def _write(tmp_path: pathlib.Path, mutate) -> pathlib.Path:
    data = yaml.safe_load(error_cases.CASES.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "errors.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def _case(data, name):
    return next(case for case in data["cases"] if case["name"] == name)


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d["connector"]["errors"].insert(0, {"status": 422, "code": "invalid_request", "retryable": False, "message": "x"}),
     "its body condition comes after an entry without one for status 422"),
    (lambda d: d["connector"]["errors"][4]["body"].update(contains=[""]), "does not match the description schema"),
    (lambda d: d["connector"]["errors"][4]["body"].update(equals=["insufficient credits"]), "does not match the description schema"),
    (lambda d: _case(d, "contains_whole_text").update(entry={"code": "credits_exhausted", "marks_account": None}),
     "is no entry of the table"),
    (lambda d: _case(d, "contains_whole_text")["answer"].update(text="x"), "does not match the error cases form"),
], ids=["rule_10_shadowed", "contains_empty_text", "equals_and_contains", "entry_not_in_the_table", "json_and_text"])
def test_a_case_is_checked_like_a_description(tmp_path, mutate, message):
    with pytest.raises(DescriptionError, match=message):
        error_cases.load(_write(tmp_path, mutate))
