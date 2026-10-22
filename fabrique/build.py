"""Génère la sortie TypeScript et la sortie Python de données, les écrit, ou vérifie que la sortie commitée est à jour."""
from __future__ import annotations

import pathlib
from dataclasses import dataclass

from . import auth_cases, body_cases, cases, error_cases, file_cases, python, strip_cases
from .descriptions import CONNECTORS, REPO, load_all
from .typescript import GENERATED_MARK, Module, connector_module, index_source

OUTPUT = REPO / "ts" / "src"


@dataclass
class Result:
    modules: list[Module]
    files: dict[str, str]
    python: str


def generate(root: pathlib.Path = CONNECTORS) -> Result:
    """Toutes les descriptions et les cas communs (coût, fichier rendu, retrait de la sortie, authentification, table
    d'erreurs, corps entier), contrôlés d'abord : un seul fautif, et rien
    n'est généré."""
    descriptions = load_all(root)
    modules = [connector_module(description) for description in descriptions]
    files = {f"{m.connector}.ts": m.source for m in modules}
    files["index.ts"] = index_source(modules)
    files[cases.OUTPUT_NAME] = cases.typescript_source(cases.load(root / cases.CASES.relative_to(CONNECTORS)))
    files[file_cases.OUTPUT_NAME] = file_cases.typescript_source(
        file_cases.load(root / file_cases.CASES.relative_to(CONNECTORS)))
    files[strip_cases.OUTPUT_NAME] = strip_cases.typescript_source(
        strip_cases.load(root / strip_cases.CASES.relative_to(CONNECTORS)))
    files[auth_cases.OUTPUT_NAME] = auth_cases.typescript_source(auth_cases.load(root / auth_cases.CASES.relative_to(CONNECTORS)))
    files[error_cases.OUTPUT_NAME] = error_cases.typescript_source(
        error_cases.load(root / error_cases.CASES.relative_to(CONNECTORS)))
    files[body_cases.OUTPUT_NAME] = body_cases.typescript_source(
        body_cases.load(root / body_cases.CASES.relative_to(CONNECTORS)))
    return Result(modules=modules, files=files, python=python.python_source(descriptions))


def _generated_on_disk(output: pathlib.Path) -> set[str]:
    return {
        path.name for path in output.glob("*.ts")
        if path.read_text(encoding="utf-8").startswith(GENERATED_MARK)
    }


def write(result: Result, output: pathlib.Path = OUTPUT, python_output: pathlib.Path = python.OUTPUT) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for stale in _generated_on_disk(output) - set(result.files):
        (output / stale).unlink()
    for name, source in result.files.items():
        (output / name).write_text(source, encoding="utf-8")
    python_output.parent.mkdir(parents=True, exist_ok=True)
    python_output.write_text(result.python, encoding="utf-8")


def stale(result: Result, output: pathlib.Path = OUTPUT, python_output: pathlib.Path = python.OUTPUT) -> list[str]:
    """Les fichiers dont la version commitée n'est pas celle que la fabrique produit : ceux de `ts/src/` par leur nom,
    le module Python de données par son chemin dans le dépôt."""
    differ = []
    for name, source in sorted(result.files.items()):
        path = output / name
        if not path.exists() or path.read_text(encoding="utf-8") != source:
            differ.append(name)
    differ += sorted(_generated_on_disk(output) - set(result.files))
    if not python_output.exists() or python_output.read_text(encoding="utf-8") != result.python:
        differ.append(python.RELATIVE)
    return differ
