"""Les cas communs de `output.strip` (`connectors/_cases/strip.yaml`), joués côté Python, une ligne par cas.

La lib n'applique la sortie d'aucune description (ni `items`, ni `strip`, ni `projection`) : seul le moteur du paquet de
l'hôte le fait. Les cas se jouent donc ici contre une référence écrite dans le test, qui dit la sémantique du format
(« Retirer de la sortie ») ; le paquet de l'hôte joue les mêmes cas, sortis par la fabrique dans
`ts/src/strip-cases.ts`, contre son moteur. Les sorties refusées le sont par la fabrique (règle 18), avec leur code et
le chemin qu'elles nomment.
"""
from __future__ import annotations

import copy
import re

import pytest
from jsonschema import Draft202012Validator

from fabrique import strip_cases
from fabrique.descriptions import DescriptionError, check_rules, schema

LOADED = strip_cases.load()


def _at(value, path: str):
    """La valeur au chemin pointé de `items`, un index de liste en nombre (la lecture du moteur)."""
    for key in path.split("."):
        if isinstance(value, list) and key.isdigit():
            value = value[int(key)] if int(key) < len(value) else None
        elif isinstance(value, dict):
            value = value.get(key)
        else:
            return None
    return value


def _strip(value, keys: list[str]):
    """Le chemin retiré : une liste se traverse, le reste du chemin valant pour chaque élément ; une valeur absente,
    nulle ou scalaire n'a rien à retirer. La valeur reçue n'est pas modifiée."""
    if isinstance(value, list):
        return [_strip(element, keys) for element in value]
    if not isinstance(value, dict) or keys[0] not in value:
        return value
    if len(keys) == 1:
        return {key: inner for key, inner in value.items() if key != keys[0]}
    return {**value, keys[0]: _strip(value[keys[0]], keys[1:])}


def _record(value, output: dict):
    for path in output.get("strip", []):
        value = _strip(value, path.split("."))
    projection = output.get("projection")
    if projection is not None and isinstance(value, dict):
        value = {key: inner for key, inner in value.items() if key in projection}
    return value


def shaped(answer, output: dict):
    """La référence : `strip`, puis `projection`, sur la réponse, ou sur chaque élément de la liste `items`."""
    if "items" in output:
        return [_record(element, output) for element in _at(answer, output["items"])]
    return _record(answer, output)


@pytest.mark.parametrize("case", LOADED.cases, ids=[case["name"] for case in LOADED.cases])
def test_strip_case(case):
    answer = copy.deepcopy(case["answer"])
    assert shaped(answer, case["function"]["output"]) == case["shaped"]
    assert answer == case["answer"]


@pytest.mark.parametrize("refused", LOADED.refused, ids=[refused["name"] for refused in LOADED.refused])
def test_refused_output_is_refused_by_the_fabrique(refused):
    description = strip_cases.carrying(LOADED, refused["output"])
    expected = f"function {strip_cases.CARRIER}: output.strip {refused['path']!r}: {refused['refusal']}"
    with pytest.raises(DescriptionError, match=re.escape(expected)):
        check_rules(description, "connectors/_cases/strip.yaml")


@pytest.mark.parametrize("refused", [r for r in LOADED.refused if r["refusal"] != "strip_path_overlaps"],
                         ids=lambda r: r["name"])
def test_malformed_or_twice_is_refused_by_the_schema_too(refused):
    description = strip_cases.carrying(LOADED, refused["output"])
    assert next(iter(Draft202012Validator(schema()).iter_errors(description)), None) is not None


def test_cases_cover_every_refusal():
    assert sorted({r["refusal"] for r in LOADED.refused}) == sorted(strip_cases.REFUSALS)


def test_refused_output_that_the_fabrique_accepts_is_refused_at_load(tmp_path):
    text = strip_cases.CASES.read_text(encoding="utf-8").replace("strip: [call..recording]", "strip: [call.recording]", 1)
    path = tmp_path / "strip.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(DescriptionError, match="refused output empty_segment is accepted by the fabrique"):
        strip_cases.load(path)


def test_refused_output_with_another_refusal_is_refused_at_load(tmp_path):
    text = strip_cases.CASES.read_text(encoding="utf-8").replace(
        "path: call..recording\n    refusal: strip_path_malformed", "path: call..recording\n    refusal: strip_path_twice", 1)
    path = tmp_path / "strip.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(DescriptionError, match="refused output empty_segment: the fabrique answers strip_path_malformed"):
        strip_cases.load(path)
