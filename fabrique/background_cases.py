"""Les cas communs de la fonction longue : `connectors/_cases/background.yaml`, joués par le paquet de l'hôte.

Le fichier porte un bloc `connector` synthétique, des fonctions acceptées et des fonctions refusées. Une fonction acceptée
porte `background: true`, son propre `timeout_s`, et ce qu'une fonction peut déclarer avec lui (classe, `act`, `confirm`,
coût réglé, fichier rendu, fichier envoyé). Une fonction refusée, valide contre le schéma des descriptions, est refusée
par la règle 21 avec son code, jamais par une autre règle ; `beside` porte les fonctions du connecteur dont elle a besoin
(la relève d'un travail asynchrone, la soumission dont elle est la relève). Sans `background`, les mêmes fonctions sont
acceptées : c'est bien la règle 21 qui refuse.

La fabrique assemble les fonctions acceptées en une description, contrôlée par le schéma et les règles de toute
description, vérifie chaque fonction refusée, puis convertit la description comme une description :

- en TypeScript, `ts/src/background-cases.ts` : le module de ce connecteur (`connector_module`), les quatre refus de la
  règle 21, les fonctions refusées et leurs voisines (une définition chacune, hors du connecteur), la liste des fonctions
  acceptées et celle des fonctions refusées, que les tests du paquet de l'hôte jouent contre `registerConnectors`. Des
  données de test : l'index ne le réexporte pas, le paquet `ts/` l'expose sous `./background-cases` ;
- en Python, rien : le client Python ignore `background` et appelle en synchrone. `tests/test_background_cases.py` joue
  les cas contre la fabrique.

`python -m fabrique --check` échoue quand le module TypeScript commité ne suit plus le fichier.
"""
from __future__ import annotations

import copy
import pathlib
from dataclasses import dataclass

import yaml
from jsonschema import Draft202012Validator

from .descriptions import (BACKGROUND_REFUSALS, CONNECTORS, REPO, Description, DescriptionError, background_refusal,
                           check_rules, check_schema)
from .typescript import NotGenerated, camel, connector_module, function_definition, js

CASES = CONNECTORS / "_cases" / "background.yaml"
OUTPUT_NAME = "background-cases.ts"
REFUSALS = BACKGROUND_REFUSALS

_NAME = {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"}

# La forme d'un fichier de cas ; `connector` et chaque fonction se valident ensuite comme une description.
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["connector", "accepted", "refused"],
    "properties": {
        "connector": {"type": "object"},
        "accepted": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "function"],
                "properties": {"name": _NAME, "function": {"type": "object"}},
            },
        },
        "refused": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "function", "beside", "refusal"],
                "properties": {
                    "name": _NAME,
                    "function": {"type": "object"},
                    "beside": {"type": "array", "items": {"type": "object"}},
                    "refusal": {"enum": list(REFUSALS)},
                },
            },
        },
    },
}


@dataclass(frozen=True)
class BackgroundCases:
    description: Description
    accepted: list[dict]
    refused: list[dict]

    @property
    def connector(self) -> str:
        return self.description.name


def _relative(path: pathlib.Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def alone(background_cases: BackgroundCases, functions: list[dict]) -> dict:
    """Une description qui ne porte que `functions`, sous le connecteur des cas."""
    return {"connector": copy.deepcopy(background_cases.description.data["connector"]),
            "functions": copy.deepcopy(functions)}


def refused_functions(refused: dict) -> list[dict]:
    """Les fonctions d'une description refusée : la fonction longue, puis ses voisines."""
    return [refused["function"], *refused["beside"]]


def _foreground(function: dict) -> dict:
    """La même fonction, sans `background`."""
    return {key: value for key, value in function.items() if key != "background"}


def _check_accepted(accepted: dict, where: str) -> None:
    function = accepted["function"]
    if function.get("background") is not True:
        raise DescriptionError(f"{where}: accepted function {accepted['name']}: declares background: true")


def _check_refused(loaded: BackgroundCases, refused: dict, where: str) -> None:
    """Une fonction refusée l'est par la règle 21, avec son code ; jamais par le schéma ni par une autre règle : sans
    `background`, la même description est acceptée."""
    at = f"{where}: refused function {refused['name']}"
    function = refused["function"]
    if function.get("background") is not True:
        raise DescriptionError(f"{at}: declares background: true")
    if any("background" in beside for beside in refused["beside"]):
        raise DescriptionError(f"{at}: only the refused function declares background")
    description = alone(loaded, refused_functions(refused))
    try:
        check_schema(description, where)
    except DescriptionError as error:
        raise DescriptionError(f"{at} must match the description schema: {error}") from None
    try:
        check_rules(alone(loaded, [_foreground(function), *refused["beside"]]), where)
    except DescriptionError as error:
        raise DescriptionError(f"{at} is refused without background, by another rule than 21: {error}") from None
    expected = background_refusal(function, description["functions"])
    try:
        check_rules(description, where)
    except DescriptionError as error:
        if expected is None:
            raise DescriptionError(f"{at} is refused by another rule than 21: {error}") from None
    else:
        raise DescriptionError(f"{at} is accepted by the fabrique")
    if expected[0] != refused["refusal"]:
        raise DescriptionError(f"{at}: the fabrique answers {expected[0]}, the file says {refused['refusal']}")


def load(path: pathlib.Path = CASES) -> BackgroundCases:
    """Le fichier lu, sa forme contrôlée, ses fonctions acceptées contrôlées comme une description, ses fonctions
    refusées vérifiées."""
    where = _relative(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    error = next(iter(sorted(Draft202012Validator(SCHEMA).iter_errors(data), key=lambda e: list(e.absolute_path))), None)
    if error is not None:
        at = "/".join(str(p) for p in error.absolute_path) or "(root)"
        raise DescriptionError(f"{where}: does not match the background cases form at {at}: {error.message}")
    names = [entry["name"] for entry in data["accepted"] + data["refused"]]
    twice = sorted({n for n in names if names.count(n) > 1})
    if twice:
        raise DescriptionError(f"{where}: case name(s) declared twice: {', '.join(twice)}")
    for accepted in data["accepted"]:
        _check_accepted(accepted, where)
    description = {"connector": data["connector"], "functions": [copy.deepcopy(a["function"]) for a in data["accepted"]]}
    check_schema(description, where)
    check_rules(description, where)
    loaded = BackgroundCases(description=Description(path=path, data=description), accepted=data["accepted"],
                             refused=data["refused"])
    for refused in data["refused"]:
        _check_refused(loaded, refused, where)
    missing = sorted(set(REFUSALS) - {refused["refusal"] for refused in data["refused"]})
    if missing:
        raise DescriptionError(f"{where}: no refused function for {', '.join(missing)}")
    return loaded


CASE_TYPE = '''
/** The refusals of a long function (rule 21 of the fabrique), the same on both sides, in the order they are judged. */
export const backgroundRefusals = {refusals} as const

export type BackgroundRefusal = (typeof backgroundRefusals)[number]

/** A long function of `connector` (connectors/_cases/background.yaml) that the host declares. */
export type BackgroundAcceptedFunction = {{
  readonly name: string
  readonly function: (typeof connector.functions)[number]
}}

/**
 * A long function that rule 21 refuses, declared with the functions it needs beside it (`beside`: the collect of an
 * asynchronous job, the submission whose collect it is), all under the case connector, and the refusal. Never in
 * `connector.functions`. Without `background`, the same functions are accepted.
 */
export type BackgroundRefusedFunction = {{
  readonly name: string
  readonly function: ConnectorFunction
  readonly beside: readonly ConnectorFunction[]
  readonly refusal: BackgroundRefusal
}}
'''


def _entries(entries: list[tuple[str, str]]) -> str:
    return "  {\n" + "\n".join(f"    {key}: {value}," for key, value in entries) + "\n  }"


def _refused_identifier(refused: dict) -> str:
    return camel(f"refused_{refused['name']}")


def _beside_identifier(refused: dict, function: dict) -> str:
    return camel(f"refused_{refused['name']}_beside_{function['name']}")


def _accepted_source(accepted: dict) -> str:
    return _entries([("name", js(accepted["name"])), ("function", camel(accepted["function"]["name"]))])


def _refused_source(refused: dict) -> str:
    beside = "[" + ", ".join(_beside_identifier(refused, f) for f in refused["beside"]) + "]"
    return _entries([("name", js(refused["name"])), ("function", _refused_identifier(refused)), ("beside", beside),
                     ("refusal", js(refused["refusal"]))])


def _definition(connector: str, function: dict, at: str) -> str:
    try:
        return function_definition(connector, function)
    except NotGenerated as error:
        raise DescriptionError(f"{at}: not generated: {error}") from None


def typescript_source(background_cases: BackgroundCases) -> str:
    """`ts/src/background-cases.ts` : le module du connecteur des cas, les refus, les types, les fonctions refusées et
    leurs voisines, puis les fonctions acceptées et les fonctions refusées en listes."""
    source = _relative(background_cases.description.path)
    module = connector_module(background_cases.description, source=source)
    if module.skipped:
        raise DescriptionError(f"{source}: function(s) not generated: {', '.join(s.function for s in module.skipped)}")
    head = module.source.replace('import { defineConnector, defineFunction } from "./types"',
                                 'import { defineConnector, defineFunction, type ConnectorFunction } from "./types"', 1)
    if head == module.source:
        raise DescriptionError(f"{source}: the generated module no longer imports from ./types as expected")
    connector = background_cases.connector
    definitions = []
    for refused in background_cases.refused:
        at = f"{source}: refused function {refused['name']}"
        definitions.append(f"export const {_refused_identifier(refused)} = "
                           f"{_definition(connector, refused['function'], at)}\n")
        for beside in refused["beside"]:
            definitions.append(f"export const {_beside_identifier(refused, beside)} = "
                               f"{_definition(connector, beside, at)}\n")
    accepted = ",\n".join(_accepted_source(entry) for entry in background_cases.accepted)
    refused = ",\n".join(_refused_source(entry) for entry in background_cases.refused)
    return (head + CASE_TYPE.format(refusals=js(list(REFUSALS)))
            + "\n// The functions rule 21 refuses, and those they need beside them, under the case connector, never in"
            + " connector.functions.\n"
            + "\n".join(definitions)
            + "\n/** The long functions the host declares, in the order of the file. */\n"
            + "export const backgroundAcceptedFunctions: readonly BackgroundAcceptedFunction[] = [\n" + accepted + ",\n]\n"
            + "\n/** The long functions rule 21 refuses, in the order of the file. */\n"
            + "export const backgroundRefusedFunctions: readonly BackgroundRefusedFunction[] = [\n" + refused + ",\n]\n")
