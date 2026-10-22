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
from fabrique.descriptions import (BODY_REFUSALS, DescriptionError, _personal_marks, body_argument_refusal,
                                   check_personal, check_rules, free_keys, strict_object)

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


# --- Les clés libres en texte, à la racine de l'argument du corps entier (décidé par Alexis le 2026-10-22) ----------

def _contact() -> dict:
    return copy.deepcopy(FUNCTIONS["upsert_contact"]["input"]["properties"]["contact"])


def _account() -> dict:
    return copy.deepcopy(FUNCTIONS["update_account"]["input"]["properties"]["account"])


def test_free_keys_make_a_strict_object():
    assert free_keys({"type": "string", "personal": True})
    assert free_keys({"type": ["string", "number", "boolean"], "personal": True})
    assert strict_object(_contact())
    assert strict_object(_account())
    assert body_argument_refusal(FUNCTIONS["upsert_contact"]) is None
    assert body_argument_refusal(FUNCTIONS["update_account"]) is None


# Ce que les cas communs ne peuvent pas porter, le schéma des descriptions les refusant avant la règle 20 (un nombre),
# ou ce que `==` confondrait (`personal: 1`, `type: ["string"]`) : jugé ici, sur la règle seule.
@pytest.mark.parametrize("additional", [
    True, None, 0, 1, "string", [], {}, {"type": "string"}, {"personal": True}, {"type": "string", "personal": 1},
    {"type": "string", "personal": "true"}, {"type": ["string"], "personal": True}, {"type": "integer", "personal": True},
    {"type": "string", "personal": True, "maxLength": 100}, {"type": "string", "personal": True, "description": "A field."},
    {"type": ["string", "number", "boolean"], "personal": 1}, {"type": ("string", "number", "boolean"), "personal": True},
    {"type": ["string", "number", "boolean", "boolean"], "personal": True},
    {"type": ["string", "integer", "boolean"], "personal": True}, {"type": ["string", "number", "boolean"]},
], ids=["true", "absent", "zero", "one", "a_text", "a_list", "empty_schema", "not_personal", "untyped", "personal_one",
        "personal_text", "type_list", "integer", "max_length", "description", "simple_personal_one", "simple_tuple",
        "simple_twice", "simple_integer", "simple_not_personal"])
def test_any_other_free_keys_are_not_strict(additional):
    assert not free_keys(additional)
    for argument in (_contact(), _account()):
        if additional is None:
            del argument["additionalProperties"]
        else:
            argument["additionalProperties"] = additional
        assert not strict_object(argument)


def test_free_text_keys_hold_at_the_root_of_the_argument_only():
    """Ailleurs dans l'objet, une table garde sa forme libre, comme avant (`variables` de `create_lead`) ; la règle ne
    juge que la racine de l'argument, et un objet imbriqué n'y gagne ni n'y perd rien."""
    contact = _contact()
    contact["properties"]["address"] = {"type": "object", "additionalProperties": {"type": "integer"}}
    assert strict_object(contact)
    nested_only = _contact()
    nested_only["additionalProperties"] = False
    nested_only["properties"]["fields"] = {"type": "object", "additionalProperties": {"type": "string", "personal": True}}
    assert strict_object(nested_only)


def test_free_text_keys_are_marked_personal_by_rule_15():
    """La marque des clés libres est une marque de la règle 15, à sa place dans l'entrée : acceptée, et trouvée là."""
    function = FUNCTIONS["upsert_contact"]
    check_personal(function, "connectors/_cases/body.yaml")
    marks = dict(_personal_marks(function["input"], "input"))
    assert marks == {"input.properties.contact.additionalProperties": True,
                     "input.properties.contact.properties.email": True}


def test_free_simple_keys_are_marked_personal_by_rule_15():
    """Les clés libres à valeur simple de même, quel que soit le type de la valeur."""
    function = FUNCTIONS["update_account"]
    check_personal(function, "connectors/_cases/body.yaml")
    assert dict(_personal_marks(function["input"], "input")) == {"input.properties.account.additionalProperties": True}


def test_free_text_keys_go_out_as_they_are_in_typescript():
    source = body_cases.typescript_source(LOADED)
    assert '        "additionalProperties": {"type": "string", "personal": true},\n' in source
    assert '        "additionalProperties": {"type": ["string", "number", "boolean"], "personal": true},\n' in source
