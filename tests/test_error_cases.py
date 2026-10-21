"""Les cas communs de la table d'erreurs (`connectors/_cases/errors.yaml`), joués côté Python, une ligne par cas.

La lib ne lit la table d'erreurs d'aucune description : seul le moteur du paquet de l'hôte le fait. Les cas se jouent
donc ici contre une référence écrite dans le test, qui dit la sémantique du format (« Signal de refus du service ») ; le
paquet de l'hôte joue les mêmes cas, sortis par la fabrique dans `ts/src/error-cases.ts`, contre son moteur.
"""
from __future__ import annotations

import pathlib

import pytest
import yaml

from fabrique import error_cases
from fabrique.descriptions import DescriptionError

LOADED = error_cases.load()
ABSENT = object()


def _at(value, path: str):
    """La valeur au chemin pointé, un indice de liste en chiffres ; `ABSENT` quand le chemin ne mène à rien."""
    for key in path.split("."):
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list) and key.isdigit() and int(key) < len(value):
            value = value[int(key)]
        else:
            return ABSENT
    return value


def holds(condition: dict, answer: dict) -> bool:
    """La référence d'une condition sur le corps : `equals`, même type et valeur exacte ; `contains`, un texte qui contient
    l'un des textes, les deux en minuscules (`str.lower`, comme `toLowerCase`). Un corps qui n'est pas JSON n'a rien."""
    if "json" not in answer:
        return False
    value = _at(answer["json"], condition["path"])
    if "equals" in condition:
        return any(type(value) is type(expected) and value == expected for expected in condition["equals"])
    return isinstance(value, str) and any(text.lower() in value.lower() for text in condition["contains"])


def selected(errors: list[dict], answer: dict) -> dict | None:
    """La première entrée dont un statut couvre la réponse et dont la condition tient, quand elle en a une."""
    for entry in errors:
        statuses = entry["status"] if isinstance(entry["status"], list) else [entry["status"]]
        if answer["status"] in statuses and ("body" not in entry or holds(entry["body"], answer)):
            return {"code": entry["code"], "marks_account": entry.get("marks_account")}
    return None


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
