"""Les cas communs du corps emboîté (`connectors/_cases/nested_body.yaml`), joués côté Python, une ligne par cas.

La lib n'envoie la requête d'aucune description : seul le moteur du paquet de l'hôte le fait. Les cas se jouent donc
ici contre une référence écrite dans le test, qui dit la sémantique du format (« Le corps emboîté ») ; le paquet de
l'hôte joue les mêmes cas, sortis par la fabrique dans `ts/src/nested-body-cases.ts`, contre son moteur. Les entrées
rejetées le sont par le schéma d'entrée, avant tout envoi ; les fonctions refusées le sont par la fabrique (règle 22),
avec leur code.
"""
from __future__ import annotations

import copy
import re

import pytest
from jsonschema import Draft202012Validator

from fabrique import nested_body_cases
from fabrique.descriptions import NESTED_BODY_REFUSALS, DescriptionError, body_entries, body_table_refusal, check_rules
from test_body_cases import request as flat_request

LOADED = nested_body_cases.load()
FUNCTIONS = {function["name"]: function for function in LOADED.description.data["functions"]}
WHERE = "connectors/_cases/nested_body.yaml"


def body(function: dict, given: dict) -> dict:
    """La référence : la constante du corps, copiée, puis chaque argument donné posé à son chemin, les objets parents
    créés au besoin ; un argument absent ne crée rien, un `null` part `null`. Une clé est une clé : un point n'y est
    qu'un caractère."""
    call = function["call"]
    sent = copy.deepcopy((call.get("constants") or {}).get("body") or {})
    for path, argument in body_entries(call["body"]):
        if argument not in given:
            continue
        parent = sent
        for key in path[:-1]:
            parent = parent.setdefault(key, {})
        parent[path[-1]] = given[argument]
    return sent


@pytest.mark.parametrize("case", LOADED.cases, ids=[case["name"] for case in LOADED.cases])
def test_nested_body_case(case):
    function = case["function"]
    given = copy.deepcopy(case["input"])
    assert Draft202012Validator(function["input"]).is_valid(given)
    # Chemin, query et en-têtes par la référence du corps entier, qui ne lit le corps qu'à sa clé `call.body` ; le corps
    # par la référence de la règle 22.
    others = {**function, "call": {**function["call"], "body": "body"}}
    expected = {**flat_request(others, {**given, "body": None}), "body": body(function, given)}
    assert expected == case["request"]
    assert given == case["input"]


@pytest.mark.parametrize("rejected", LOADED.rejected, ids=[rejected["name"] for rejected in LOADED.rejected])
def test_rejected_input_is_refused_by_the_schema(rejected):
    assert not Draft202012Validator(FUNCTIONS[rejected["function"]]["input"]).is_valid(rejected["input"])


@pytest.mark.parametrize("refused", LOADED.refused, ids=[refused["name"] for refused in LOADED.refused])
def test_refused_function_is_refused_by_rule_22(refused):
    function = refused["function"]
    code, path, _reason = body_table_refusal(function)
    assert code == refused["refusal"]
    expected = f"function {function['name']}: call.body {path!r}: {code}: "
    with pytest.raises(DescriptionError, match=re.escape(expected)):
        check_rules(nested_body_cases.alone(LOADED, function), WHERE)


def test_every_refusal_has_a_refused_function():
    assert {refused["refusal"] for refused in LOADED.refused} == set(NESTED_BODY_REFUSALS)


def test_a_constant_and_a_table_meet_through_objects_only():
    """Les chemins des refus : la première rencontre autrement que par deux objets, au premier niveau comme au-dessous."""
    paths = {refused["name"]: body_table_refusal(refused["function"])[1] for refused in LOADED.refused}
    assert paths == {
        "empty_nested_table": "data",
        "deep_empty_nested_table": "data.meta",
        "argument_on_a_constant": "data.format",
        "flat_argument_on_a_constant": "draft",
        "argument_over_a_constant_object": "data",
        "table_under_a_constant_value": "data",
        "nested_in_multipart": "meta.title",
    }


def test_a_flat_table_beside_a_file_part_is_not_judged_by_rule_22():
    function = copy.deepcopy(next(r["function"] for r in LOADED.refused if r["name"] == "nested_in_multipart"))
    function["call"]["body"] = {"title": "title"}
    assert body_table_refusal(function) is None
    check_rules(nested_body_cases.alone(LOADED, function), WHERE)


def test_a_whole_body_is_not_judged_by_rule_22():
    function = copy.deepcopy(FUNCTIONS["create_record"])
    function["call"]["body"] = "values"
    assert body_table_refusal(function) is None


def test_typescript_carries_the_nested_table_as_is():
    source = nested_body_cases.typescript_source(LOADED)
    assert '    body: {"data": {"values": "values", "owner_id": "owner_id"}},\n' in source
    assert '    constants: {"body": {"data": {"format": "plain"}}},\n' in source
    assert "export const nestedBodyRefusedFunctions: readonly NestedBodyRefusedFunction[]" in source
