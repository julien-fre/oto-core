"""Garde : un seul numéro de version pour le dépôt. Le paquet npm `ts/` porte celle de la lib (`pyproject.toml`).

Un tag `vX.Y.Z` publie les deux (`.github/workflows/publish.yml`) ; un paquet resté en arrière ferait échouer sa
publication après celle de la lib, et le tag resterait à moitié publié. Rejouée sur le tag par `publish.yml`, la garde
bloque aussi la publication PyPI. Le geste de publication : `docs/release.md`.
"""
from __future__ import annotations

import json
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent


def _lib_version() -> str:
    # Lue comme `tag-release.yml` la lit : `tomllib` n'existe qu'à partir de Python 3.11, la lib en accepte 3.10.
    return re.search(r'^version = "(.+)"$', (REPO / "pyproject.toml").read_text(), re.MULTILINE).group(1)


def test_npm_package_carries_the_lib_version():
    package = json.loads((REPO / "ts/package.json").read_text())
    assert package["version"] == _lib_version(), "ts/package.json: run `npm version --no-git-tag-version <version>` in ts/"


def test_npm_lockfile_carries_the_lib_version():
    lock = json.loads((REPO / "ts/package-lock.json").read_text())
    assert (lock["version"], lock["packages"][""]["version"]) == (_lib_version(), _lib_version()), \
        "ts/package-lock.json: run `npm version --no-git-tag-version <version>` in ts/"


def test_npm_package_publishes_the_repository_license():
    # npm ne publie que le dossier du paquet : `ts/LICENSE` est une copie, qui ne doit pas dériver.
    assert (REPO / "ts/LICENSE").read_text() == (REPO / "LICENSE").read_text()
