"""Les cas communs du coût : `connectors/_cases/cost.yaml`, joués des deux côtés.

Le fichier porte un bloc `connector` synthétique et des cas ; chaque cas porte sa fonction en forme source (`function`,
et `collect` pour un travail asynchrone), ses arguments, ses réponses et ce qu'en rendent les fonctions pures du coût.
La fabrique assemble ces fonctions en une description, contrôlée par le schéma et les règles de toute description, puis
la convertit comme une description :

- en Python, dans la forme de `oto/connectors/declared.py` (`python.declared`), que `tests/test_cost_cases.py` donne à
  `oto.connectors.cost` ;
- en TypeScript, `ts/src/cost-cases.ts` : le module de ce connecteur (`connector_module`) et la liste des cas, que les
  tests du paquet de l'hôte jouent contre `costOf`, `settledQuantity` et `collectionOf`. Des données de test : l'index
  ne le réexporte pas, le paquet `ts/` l'expose sous `./cost-cases`.

`python -m fabrique --check` échoue quand le module TypeScript commité ne suit plus le fichier.
"""
from __future__ import annotations

import copy
import pathlib
from dataclasses import dataclass
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from . import python
from .descriptions import CONNECTORS, REPO, Description, DescriptionError, check_rules, check_schema
from .typescript import camel, collection_fields, connector_module, js, js_block

CASES = CONNECTORS / "_cases" / "cost.yaml"
OUTPUT_NAME = "cost-cases.ts"
ERROR = "error"

_QUANTITY = {"type": "object", "additionalProperties": False, "required": ["quantity", "unit"],
             "properties": {"quantity": {"type": "number"}, "unit": {"type": "string", "minLength": 1}}}
_SETTLED = {"type": "object", "additionalProperties": False, "required": ["quantity", "unit", "from", "exceeded"],
            "properties": {"quantity": {"type": "number"}, "unit": {"type": "string", "minLength": 1},
                           "from": {"enum": ["response", "requests", "worst_case", "unreadable"]},
                           "exceeded": {"type": "boolean"}}}
_COLLECTION = {"type": "object", "additionalProperties": False, "required": ["function", "args"],
               "properties": {"function": {"type": "string"}, "args": {"type": "object", "minProperties": 1, "maxProperties": 1},
                              "within_s": {"type": "integer"}, "no_deadline": {"const": True}},
               "not": {"required": ["within_s", "no_deadline"]}}


def _or_error(schema: dict) -> dict:
    return {"oneOf": [schema, {"type": "null"}, {"const": ERROR}]}


# La forme d'un fichier de cas ; `connector` et chaque fonction se valident ensuite comme une description.
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["connector", "cases"],
    "properties": {
        "connector": {"type": "object"},
        "cases": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "function", "args", "answers", "worst_case", "settled", "collection"],
                "properties": {
                    "name": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
                    "function": {"type": "object"},
                    "collect": {"type": "object"},
                    "args": {"type": "object"},
                    "answers": {"type": "array"},
                    "submission": {},
                    "worst_case": _or_error(_QUANTITY),
                    "settled": _or_error(_SETTLED),
                    "collection": _or_error(_COLLECTION),
                },
            },
        },
    },
}


@dataclass(frozen=True)
class CostCases:
    description: Description
    cases: list[dict]

    @property
    def connector(self) -> str:
        return self.description.name


def _relative(path: pathlib.Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def _functions(cases: list[dict], where: str) -> list[dict]:
    """Les fonctions que portent les cas, chacune une fois : un même nom est toujours la même fonction."""
    functions: dict[str, dict] = {}
    for case in cases:
        for key in ("function", "collect"):
            function = case.get(key)
            if function is None:
                continue
            name = function.get("name")
            if name in functions and functions[name] != function:
                raise DescriptionError(f"{where}: case {case['name']}: function {name!r} differs from another of that name")
            functions.setdefault(name, function)
    return [copy.deepcopy(f) for f in functions.values()]


def _check_case(case: dict, where: str) -> None:
    """Un cas cohérent avec sa fonction : sa relève est celle qu'elle déclare, une soumission pour un travail asynchrone."""
    function = case["function"]
    job = function.get("async")
    at = f"{where}: case {case['name']}"
    if job is None:
        if "collect" in case or "submission" in case or case["collection"] is not None:
            raise DescriptionError(f"{at}: a function that is not asynchronous has no collect, submission nor collection")
        return
    if case.get("collect", {}).get("name") != job["collect"] or "submission" not in case:
        raise DescriptionError(f"{at}: an asynchronous function carries its collect function ({job['collect']}) and a submission")
    expected = case["collection"]
    if isinstance(expected, dict) and expected["function"] != job["collect"]:
        raise DescriptionError(f"{at}: collection.function names {expected['function']!r}, not the collect function")
    if (case["worst_case"] is None) != ("cost" not in function):
        raise DescriptionError(f"{at}: worst_case is null exactly when the function declares no cost")


def load(path: pathlib.Path = CASES) -> CostCases:
    """Le fichier lu, sa forme contrôlée, ses fonctions contrôlées comme une description."""
    where = _relative(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    error = next(iter(sorted(Draft202012Validator(SCHEMA).iter_errors(data), key=lambda e: list(e.absolute_path))), None)
    if error is not None:
        at = "/".join(str(p) for p in error.absolute_path) or "(root)"
        raise DescriptionError(f"{where}: does not match the cost cases form at {at}: {error.message}")
    names = [case["name"] for case in data["cases"]]
    twice = sorted({n for n in names if names.count(n) > 1})
    if twice:
        raise DescriptionError(f"{where}: case name(s) declared twice: {', '.join(twice)}")
    description = {"connector": data["connector"], "functions": _functions(data["cases"], where)}
    check_schema(description, where)
    check_rules(description, where)
    for case in data["cases"]:
        _check_case(case, where)
    return CostCases(description=Description(path=path, data=description), cases=data["cases"])


# --- Python ------------------------------------------------------------------------------------------------------


def python_declared(cost_cases: CostCases) -> dict[str, dict[str, dict]]:
    """La table de `oto/connectors/declared.py` pour le connecteur des cas, par la même conversion."""
    return python.declared([cost_cases.description])


def python_collection(connector: str, expected: Any) -> Any:
    """La relève attendue dans les noms de `oto.connectors.cost.collection_of`."""
    if not isinstance(expected, dict):
        return expected
    return {"function": f"{connector}.{expected['function']}", "args": expected["args"],
            "within_s": expected.get("within_s"), "no_deadline": expected.get("no_deadline") is True}


# --- TypeScript --------------------------------------------------------------------------------------------------

CASE_TYPE = '''
/** What a pure cost function returns for the case: a value, `null` (no cost, not asynchronous), or `"error"` (it refuses). */
export type CostCaseOutcome<T> = T | null | "error"

/** A common cost case (connectors/_cases/cost.yaml): a call of a function of `connector`, and what each pure function returns. */
export type CostCase = {
  readonly name: string
  readonly function: (typeof connector.functions)[number]
  readonly args: { readonly [argument: string]: unknown }
  readonly answers: readonly unknown[]
  readonly submission?: unknown
  readonly worstCase: CostCaseOutcome<{ readonly quantity: number; readonly unit: string }>
  readonly settled: CostCaseOutcome<{
    readonly quantity: number
    readonly unit: string
    readonly from: "response" | "requests" | "worst_case" | "unreadable"
    readonly exceeded: boolean
  }>
  readonly collection: CostCaseOutcome<{
    readonly function: string
    readonly args: { readonly [argument: string]: string | number }
    readonly withinMs: number | null
    readonly noDeadline: boolean
  }>
}
'''


def typescript_collection(connector: str, expected: Any) -> Any:
    """La relève attendue dans les noms de la sortie, par la conversion de `async` (`collection_fields`)."""
    if not isinstance(expected, dict):
        return expected
    fields = collection_fields(connector, {"collect": expected["function"], **{k: expected[k] for k in ("within_s", "no_deadline") if k in expected}})
    return {"function": fields["collect"], "args": expected["args"], "withinMs": fields.get("withinMs"),
            "noDeadline": fields.get("noDeadline", False)}


def _case_source(connector: str, case: dict) -> str:
    entries = [
        ("name", js(case["name"])),
        ("function", camel(case["function"]["name"])),
        ("args", js_block(case["args"], 2)),
        ("answers", js_block(case["answers"], 2)),
    ]
    if "submission" in case:
        entries.append(("submission", js_block(case["submission"], 2)))
    entries += [
        ("worstCase", js(case["worst_case"])),
        ("settled", js(case["settled"])),
        ("collection", js(typescript_collection(connector, case["collection"]))),
    ]
    return "  {\n" + "\n".join(f"    {key}: {value}," for key, value in entries) + "\n  }"


def typescript_source(cost_cases: CostCases) -> str:
    """`ts/src/cost-cases.ts` : le module du connecteur des cas, puis le type d'un cas et la liste des cas."""
    source = _relative(cost_cases.description.path)
    module = connector_module(cost_cases.description, source=source)
    if module.skipped:
        raise DescriptionError(f"{source}: function(s) not generated: {', '.join(s.function for s in module.skipped)}")
    rows = ",\n".join(_case_source(cost_cases.connector, case) for case in cost_cases.cases)
    return (module.source + CASE_TYPE + "\n/** The common cost cases, in the order of the file. */\n"
            + "export const costCases: readonly CostCase[] = [\n" + rows + ",\n]\n")

