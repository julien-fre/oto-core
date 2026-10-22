"""Les cas communs du corps entier (`connectors/_cases/body.yaml`), joués côté Python, une ligne par cas.

La lib n'envoie la requête d'aucune description : seul le moteur du paquet de l'hôte le fait. Les cas se jouent donc
ici contre une référence écrite dans le test, qui dit la sémantique du format (« Le corps entier ») ; le paquet de
l'hôte joue les mêmes cas, sortis par la fabrique dans `ts/src/body-cases.ts`, contre son moteur. Les entrées rejetées
le sont par le schéma d'entrée, avant tout envoi ; les fonctions refusées le sont par la fabrique (règle 20), avec leur
code.
"""
from __future__ import annotations

import copy
import json
import re
from urllib.parse import quote

import pytest
from jsonschema import Draft202012Validator

from fabrique import body_cases
from fabrique.descriptions import BODY_REFUSALS, DescriptionError, body_argument_refusal, check_rules

LOADED = body_cases.load()
FUNCTIONS = {function["name"]: function for function in LOADED.description.data["functions"]}


def _text(value) -> str:
    """Une valeur dans un chemin, une query ou un en-tête : texte tel quel, nombre et booléen écrits, le reste en JSON."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, separators=(",", ":"))


def request(function: dict, given: dict) -> dict:
    """La référence : le chemin aux `{param}` encodés (comme `encodeURIComponent`), la query et les en-têtes des seuls
    arguments donnés, et pour corps l'argument nommé par `call.body`, tel quel."""
    call = function["call"]
    path = re.sub(r"\{([^{}]+)\}", lambda m: quote(_text(given[m.group(1)]), safe="!*'()"), call["path"])
    query = [[name, _text(given[argument])] for name, argument in (call.get("query") or {}).items() if argument in given]
    headers = {name.lower(): _text(given[argument]) for name, argument in (call.get("headers") or {}).items()
               if argument in given}
    return {"path": path, "query": query, "headers": headers, "body": given[call["body"]]}


@pytest.mark.parametrize("case", LOADED.cases, ids=[case["name"] for case in LOADED.cases])
def test_body_case(case):
    given = copy.deepcopy(case["input"])
    assert Draft202012Validator(case["function"]["input"]).is_valid(given)
    assert request(case["function"], given) == case["request"]
    assert given == case["input"]


@pytest.mark.parametrize("rejected", LOADED.rejected, ids=[rejected["name"] for rejected in LOADED.rejected])
def test_rejected_input_is_refused_by_the_schema(rejected):
    assert not Draft202012Validator(FUNCTIONS[rejected["function"]]["input"]).is_valid(rejected["input"])


@pytest.mark.parametrize("refused", LOADED.refused, ids=[refused["name"] for refused in LOADED.refused])
def test_refused_function_is_refused_by_rule_20(refused):
    function = refused["function"]
    expected = f"function {function['name']}: call.body {function['call']['body']!r}: {refused['refusal']}: "
    with pytest.raises(DescriptionError, match=re.escape(expected)):
        check_rules(body_cases.alone(LOADED, function), "connectors/_cases/body.yaml")
    assert body_argument_refusal(function)[0] == refused["refusal"]


def test_every_refusal_has_a_refused_function():
    assert {refused["refusal"] for refused in LOADED.refused} == set(BODY_REFUSALS)


def test_a_table_body_is_not_judged_by_rule_20():
    function = copy.deepcopy(FUNCTIONS["create_lead"])
    function["call"]["body"] = {"lead": "lead"}
    assert body_argument_refusal(function) is None
    check_rules(body_cases.alone(LOADED, function), "connectors/_cases/body.yaml")


def test_typescript_carries_the_argument_name_as_the_body():
    source = body_cases.typescript_source(LOADED)
    assert '    body: "lead",\n' in source
    assert 'export const refusedFreeBag = defineFunction({' in source
    assert "export const bodyRefusedFunctions: readonly BodyRefusedFunction[]" in source
