"""Les cas communs du fichier rendu : `connectors/_cases/file.yaml`, joués des deux côtés.

Le fichier porte un bloc `connector` synthétique et des cas ; chaque cas porte sa fonction en forme source (`call`,
`output.file`), ses arguments, la réponse simulée de l'API (statut, en-têtes, corps en texte ou en JSON) et, pour
`from: url`, celle du téléchargement ; il attend un fichier `{ name, mime, size }` ou l'un des six refus nommés. La
fabrique assemble ces fonctions en une description, contrôlée par le schéma et les règles de toute description (la
règle 17 comprise), puis la convertit comme une description :

- en Python, dans la forme de `oto/connectors/declared.py` (`python.declared`), que `tests/test_file_cases.py` donne à
  `oto.connectors.files`, avec un faux transport ;
- en TypeScript, `ts/src/file-cases.ts` : le module de ce connecteur (`connector_module`), les six refus et la liste des
  cas, que les tests du paquet de l'hôte jouent contre son moteur, avec un faux `fetch`. Des données de test : l'index ne
  le réexporte pas, le paquet `ts/` l'expose sous `./file-cases`.

`python -m fabrique --check` échoue quand le module TypeScript commité ne suit plus le fichier.
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass

import yaml
from jsonschema import Draft202012Validator

from . import python
from .cases import case_functions
from .descriptions import CONNECTORS, REPO, Description, DescriptionError, check_rules, check_schema
from .typescript import camel, connector_module, js, js_block

CASES = CONNECTORS / "_cases" / "file.yaml"
OUTPUT_NAME = "file-cases.ts"
# Les refus d'un fichier rendu, les mêmes des deux côtés.
REFUSALS = ("file_download_refused", "file_foreign_origin", "file_missing", "file_too_large", "file_type_refused",
            "file_unreadable")

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
                        "size": {"type": "integer", "minimum": 1}}}

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
                "required": ["name", "function", "args", "answer"],
                "properties": {
                    "name": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
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
    },
}


@dataclass(frozen=True)
class FileCases:
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


def _check_case(case: dict, where: str) -> None:
    """Un cas cohérent avec sa fonction : elle rend un fichier ; seule une adresse se télécharge ; la réponse d'un corps
    binaire est un texte, celle qui porte une adresse ou un encodage, un JSON."""
    at = f"{where}: case {case['name']}"
    file = (case["function"].get("output") or {}).get("file")
    if file is None:
        raise DescriptionError(f"{at}: a case function renders a file (output.file)")
    if "download" in case and file["from"] != "url":
        raise DescriptionError(f"{at}: only a function with from: url downloads")
    if file["from"] == "body" and "json" in case["answer"]:
        raise DescriptionError(f"{at}: a function with from: body answers bytes (text), not JSON")
    if file["from"] != "body" and "json" not in case["answer"]:
        raise DescriptionError(f"{at}: a function with from: {file['from']} answers JSON")


def load(path: pathlib.Path = CASES) -> FileCases:
    """Le fichier lu, sa forme contrôlée, ses fonctions contrôlées comme une description."""
    where = _relative(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    error = next(iter(sorted(Draft202012Validator(SCHEMA).iter_errors(data), key=lambda e: list(e.absolute_path))), None)
    if error is not None:
        at = "/".join(str(p) for p in error.absolute_path) or "(root)"
        raise DescriptionError(f"{where}: does not match the file cases form at {at}: {error.message}")
    names = [case["name"] for case in data["cases"]]
    twice = sorted({n for n in names if names.count(n) > 1})
    if twice:
        raise DescriptionError(f"{where}: case name(s) declared twice: {', '.join(twice)}")
    description = {"connector": data["connector"], "functions": case_functions(data["cases"], where)}
    check_schema(description, where)
    check_rules(description, where)
    for case in data["cases"]:
        _check_case(case, where)
    return FileCases(description=Description(path=path, data=description), cases=data["cases"])


def python_declared(file_cases: FileCases) -> dict[str, dict[str, dict]]:
    """La table de `oto/connectors/declared.py` pour le connecteur des cas, par la même conversion."""
    return python.declared([file_cases.description])


CASE_TYPE = '''
/** The refusals of a rendered file, the same on both sides. */
export const fileRefusals = {refusals} as const

export type FileRefusal = (typeof fileRefusals)[number]

/** A simulated answer: status, headers, and a body in text (bytes, UTF-8) or in JSON. */
export type FileCaseAnswer = {{
  readonly status: number
  readonly headers: {{ readonly [name: string]: string }}
  readonly text?: string
  readonly json?: unknown
}}

/**
 * A common case of a rendered file (connectors/_cases/file.yaml): a call of a function of `connector`, the answer of the
 * API and, for `from: "url"`, that of the download; it gives a file or one named refusal.
 */
export type FileCase = {{
  readonly name: string
  readonly function: (typeof connector.functions)[number]
  readonly args: {{ readonly [argument: string]: unknown }}
  readonly answer: FileCaseAnswer
  readonly download?: FileCaseAnswer
  readonly file?: {{ readonly name: string; readonly mime: string; readonly size: number }}
  readonly refusal?: FileRefusal
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


def typescript_source(file_cases: FileCases) -> str:
    """`ts/src/file-cases.ts` : le module du connecteur des cas, puis les refus, le type d'un cas et la liste des cas."""
    source = _relative(file_cases.description.path)
    module = connector_module(file_cases.description, source=source)
    if module.skipped:
        raise DescriptionError(f"{source}: function(s) not generated: {', '.join(s.function for s in module.skipped)}")
    rows = ",\n".join(_case_source(case) for case in file_cases.cases)
    return (module.source + CASE_TYPE.format(refusals=js(list(REFUSALS)))
            + "\n/** The common cases of a rendered file, in the order of the file. */\n"
            + "export const fileCases: readonly FileCase[] = [\n" + rows + ",\n]\n")
