"""Les cas communs du fichier rendu : `connectors/_cases/file.yaml`, joués des deux côtés.

Le fichier porte un bloc `connector` synthétique, des cas et des fonctions refusées ; chaque cas porte sa fonction en
forme source (`call`, `output.file`), ses arguments, la réponse simulée de l'API (statut, en-têtes, corps en texte ou en
JSON) et, pour `from: url`, celle du téléchargement ; il attend un fichier `{ name, mime, size }` (et `text`, ses octets
en UTF-8, exigé pour `from: json`) ou l'un des six refus nommés. Une fonction refusée est valide contre le schéma des
descriptions et refusée par la règle 17 avec l'un de ses cinq codes, jamais par une autre règle. La fabrique assemble
les fonctions des cas en une description, contrôlée par le schéma et les règles de toute description (la règle 17
comprise), vérifie chaque fonction refusée, puis convertit la description comme une description :

- en Python, dans la forme de `oto/connectors/declared.py` (`python.declared`), que `tests/test_file_cases.py` donne à
  `oto.connectors.files`, avec un faux transport ;
- en TypeScript, `ts/src/file-cases.ts` : le module de ce connecteur (`connector_module`), les six refus, les cinq codes
  de la déclaration, les fonctions refusées (une définition chacune, hors du connecteur), la liste des cas et celle des
  fonctions refusées, que les tests du paquet de l'hôte jouent contre son moteur, avec un faux `fetch`, et contre le
  contrôle de sa déclaration. Des données de test : l'index ne le réexporte pas, le paquet `ts/` l'expose sous
  `./file-cases`.

`python -m fabrique --check` échoue quand le module TypeScript commité ne suit plus le fichier.
"""
from __future__ import annotations

import copy
import pathlib
from dataclasses import dataclass

import yaml
from jsonschema import Draft202012Validator

from . import python
from .cases import case_functions
from .descriptions import (CONNECTORS, FILE_DECLARATION_REFUSALS, REPO, Description, DescriptionError, check_rules,
                           check_schema, output_file_refusal)
from .typescript import NotGenerated, camel, connector_module, function_definition, js, js_block

CASES = CONNECTORS / "_cases" / "file.yaml"
OUTPUT_NAME = "file-cases.ts"
# Les refus d'un fichier rendu, les mêmes des deux côtés.
REFUSALS = ("file_download_refused", "file_foreign_origin", "file_missing", "file_too_large", "file_type_refused",
            "file_unreadable")
# Les refus à code de la déclaration (règle 17), les mêmes des deux côtés, dans l'ordre où ils se jugent.
DECLARATION_REFUSALS = FILE_DECLARATION_REFUSALS
_NAME = {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"}

_HEADERS = {"type": "object", "additionalProperties": {"type": "string"}}
_ANSWER = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "headers"],
    "properties": {"status": {"type": "integer", "minimum": 100, "maximum": 599}, "headers": _HEADERS,
                   "text": {"type": "string"}, "json": {}},
    "not": {"required": ["text", "json"]},
}
_FILE = {"type": "object", "additionalProperties": False, "required": ["name", "mime", "size"],
         "properties": {"name": {"type": "string", "minLength": 1}, "mime": {"type": "string", "minLength": 1},
                        "size": {"type": "integer", "minimum": 1}, "text": {"type": "string", "minLength": 1}}}

# La forme d'un fichier de cas ; `connector` et chaque fonction se valident ensuite comme une description.
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["connector", "cases", "refused"],
    "properties": {
        "connector": {"type": "object"},
        "cases": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "function", "args", "answer"],
                "properties": {
                    "name": _NAME,
                    "function": {"type": "object"},
                    "args": {"type": "object"},
                    "answer": _ANSWER,
                    "download": _ANSWER,
                    "file": _FILE,
                    "refusal": {"enum": list(REFUSALS)},
                },
                "oneOf": [{"required": ["file"]}, {"required": ["refusal"]}],
            },
        },
        "refused": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "function", "refusal"],
                "properties": {"name": _NAME, "function": {"type": "object"},
                               "refusal": {"enum": list(DECLARATION_REFUSALS)}},
            },
        },
    },
}


@dataclass(frozen=True)
class FileCases:
    description: Description
    cases: list[dict]
    refused: list[dict]

    @property
    def connector(self) -> str:
        return self.description.name


def _relative(path: pathlib.Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def _check_case(case: dict, where: str) -> None:
    """Un cas cohérent avec sa fonction : elle rend un fichier ; seule une adresse se télécharge ; la réponse d'un corps
    binaire est un texte, celle qui porte une adresse ou un encodage, un JSON, celle d'un fichier JSON l'un ou l'autre
    (un texte dit les octets exacts : nombres, espaces, clés en double) ; le fichier d'un JSON dit ses octets."""
    at = f"{where}: case {case['name']}"
    file = (case["function"].get("output") or {}).get("file")
    if file is None:
        raise DescriptionError(f"{at}: a case function renders a file (output.file)")
    if "download" in case and file["from"] != "url":
        raise DescriptionError(f"{at}: only a function with from: url downloads")
    if file["from"] == "body" and "json" in case["answer"]:
        raise DescriptionError(f"{at}: a function with from: body answers bytes (text), not JSON")
    if file["from"] not in ("body", "json") and "json" not in case["answer"]:
        raise DescriptionError(f"{at}: a function with from: {file['from']} answers JSON")
    given = case.get("file")
    if given is not None and file["from"] == "json" and "text" not in given:
        raise DescriptionError(f"{at}: the file of a function with from: json says its bytes (file.text)")
    if given is not None and "text" in given and len(given["text"].encode("utf-8")) != given["size"]:
        raise DescriptionError(f"{at}: file.size is not the size of file.text in UTF-8")


def alone(file_cases: FileCases, function: dict) -> dict:
    """Une description qui ne porte que `function`, sous le connecteur des cas."""
    return {"connector": copy.deepcopy(file_cases.description.data["connector"]), "functions": [copy.deepcopy(function)]}


def _check_refused(loaded: FileCases, refused: dict, where: str) -> None:
    """Une fonction refusée l'est par la règle 17, avec son code ; jamais par le schéma ni par une autre règle."""
    at = f"{where}: refused function {refused['name']}"
    description = alone(loaded, refused["function"])
    try:
        check_schema(description, where)
    except DescriptionError as error:
        raise DescriptionError(f"{at} must match the description schema: {error}") from None
    expected = output_file_refusal(refused["function"])
    try:
        check_rules(description, where)
    except DescriptionError as error:
        if expected is None or f"output.file: {expected[0]}: " not in str(error):
            raise DescriptionError(f"{at} is refused by another rule than the coded ones of 17: {error}") from None
    else:
        raise DescriptionError(f"{at} is accepted by the fabrique")
    if expected[0] != refused["refusal"]:
        raise DescriptionError(f"{at}: the fabrique answers {expected[0]}, the file says {refused['refusal']}")


def load(path: pathlib.Path = CASES) -> FileCases:
    """Le fichier lu, sa forme contrôlée, ses fonctions contrôlées comme une description."""
    where = _relative(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    error = next(iter(sorted(Draft202012Validator(SCHEMA).iter_errors(data), key=lambda e: list(e.absolute_path))), None)
    if error is not None:
        at = "/".join(str(p) for p in error.absolute_path) or "(root)"
        raise DescriptionError(f"{where}: does not match the file cases form at {at}: {error.message}")
    names = [entry["name"] for entry in data["cases"] + data["refused"]]
    twice = sorted({n for n in names if names.count(n) > 1})
    if twice:
        raise DescriptionError(f"{where}: case name(s) declared twice: {', '.join(twice)}")
    description = {"connector": data["connector"], "functions": case_functions(data["cases"], where)}
    check_schema(description, where)
    check_rules(description, where)
    for case in data["cases"]:
        _check_case(case, where)
    loaded = FileCases(description=Description(path=path, data=description), cases=data["cases"], refused=data["refused"])
    for refused in data["refused"]:
        _check_refused(loaded, refused, where)
    missing = sorted(set(DECLARATION_REFUSALS) - {refused["refusal"] for refused in data["refused"]})
    if missing:
        raise DescriptionError(f"{where}: no refused function for {', '.join(missing)}")
    return loaded


def python_declared(file_cases: FileCases) -> dict[str, dict[str, dict]]:
    """La table de `oto/connectors/declared.py` pour le connecteur des cas, par la même conversion."""
    return python.declared([file_cases.description])


CASE_TYPE = '''
/** The refusals of a rendered file, the same on both sides. */
export const fileRefusals = {refusals} as const

export type FileRefusal = (typeof fileRefusals)[number]

/** The refusals of a declaration (rule 17 of the fabrique) that carry a code, the same on both sides, in the order they are judged. */
export const fileDeclarationRefusals = {declaration_refusals} as const

export type FileDeclarationRefusal = (typeof fileDeclarationRefusals)[number]

/** A simulated answer: status, headers, and a body in text (bytes, UTF-8) or in JSON. */
export type FileCaseAnswer = {{
  readonly status: number
  readonly headers: {{ readonly [name: string]: string }}
  readonly text?: string
  readonly json?: unknown
}}

/**
 * A common case of a rendered file (connectors/_cases/file.yaml): a call of a function of `connector`, the answer of the
 * API and, for `from: "url"`, that of the download; it gives a file or one named refusal. A file says its bytes as
 * UTF-8 text (`text`) for `from: "json"`.
 */
export type FileCase = {{
  readonly name: string
  readonly function: (typeof connector.functions)[number]
  readonly args: {{ readonly [argument: string]: unknown }}
  readonly answer: FileCaseAnswer
  readonly download?: FileCaseAnswer
  readonly file?: {{ readonly name: string; readonly mime: string; readonly size: number; readonly text?: string }}
  readonly refusal?: FileRefusal
}}

/** A function of the case connector that rule 17 refuses, and the refusal. Never in `connector.functions`. */
export type FileRefusedFunction = {{
  readonly name: string
  readonly function: ConnectorFunction
  readonly refusal: FileDeclarationRefusal
}}
'''


def _case_source(case: dict) -> str:
    entries = [
        ("name", js(case["name"])),
        ("function", camel(case["function"]["name"])),
        ("args", js_block(case["args"], 2)),
        ("answer", js_block(case["answer"], 2)),
    ]
    if "download" in case:
        entries.append(("download", js_block(case["download"], 2)))
    if "file" in case:
        entries.append(("file", js(case["file"])))
    else:
        entries.append(("refusal", js(case["refusal"])))
    return "  {\n" + "\n".join(f"    {key}: {value}," for key, value in entries) + "\n  }"


def _refused_identifier(refused: dict) -> str:
    return camel(f"refused_{refused['name']}")


def _refused_source(refused: dict) -> str:
    entries = [("name", js(refused["name"])), ("function", _refused_identifier(refused)), ("refusal", js(refused["refusal"]))]
    return "  {\n" + "\n".join(f"    {key}: {value}," for key, value in entries) + "\n  }"


def typescript_source(file_cases: FileCases) -> str:
    """`ts/src/file-cases.ts` : le module du connecteur des cas, puis les refus, les types, les fonctions refusées, la
    liste des cas et celle des fonctions refusées."""
    source = _relative(file_cases.description.path)
    module = connector_module(file_cases.description, source=source)
    if module.skipped:
        raise DescriptionError(f"{source}: function(s) not generated: {', '.join(s.function for s in module.skipped)}")
    head = module.source.replace('import { defineConnector, defineFunction } from "./types"',
                                 'import { defineConnector, defineFunction, type ConnectorFunction } from "./types"', 1)
    if head == module.source:
        raise DescriptionError(f"{source}: the generated module no longer imports from ./types as expected")
    refused_definitions = []
    for refused in file_cases.refused:
        try:
            definition = function_definition(file_cases.connector, refused["function"])
        except NotGenerated as error:
            raise DescriptionError(f"{source}: refused function {refused['name']}: not generated: {error}") from None
        refused_definitions.append(f"export const {_refused_identifier(refused)} = {definition}\n")
    rows = ",\n".join(_case_source(case) for case in file_cases.cases)
    refused = ",\n".join(_refused_source(entry) for entry in file_cases.refused)
    return (head + CASE_TYPE.format(refusals=js(list(REFUSALS)), declaration_refusals=js(list(DECLARATION_REFUSALS)))
            + "\n// The functions rule 17 refuses, each alone under the case connector, never in connector.functions.\n"
            + "\n".join(refused_definitions)
            + "\n/** The common cases of a rendered file, in the order of the file. */\n"
            + "export const fileCases: readonly FileCase[] = [\n" + rows + ",\n]\n"
            + "\n/** The functions rule 17 refuses with a code, in the order of the file. */\n"
            + "export const fileRefusedFunctions: readonly FileRefusedFunction[] = [\n" + refused + ",\n]\n")
