"""Garde : le job `publish-npm` de `.github/workflows/publish.yml` publie l'archive construite, désignée comme un fichier.

npm lit un argument `dossier/archive.tgz` comme le raccourci GitHub `utilisateur/dépôt` et tente `git ls-remote` : la
v1.190.0 n'est pas partie sur npm pour cette raison. Un chemin qui commence par `./` est toujours un fichier.
Le geste de publication : `docs/release.md`.
"""
from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent


def _publish_npm() -> dict:
    return yaml.safe_load((REPO / ".github/workflows/publish.yml").read_text())["jobs"]["publish-npm"]


def test_publish_npm_publishes_a_local_file():
    runs = [step["run"] for step in _publish_npm()["steps"] if "npm publish" in step.get("run", "")]
    assert len(runs) == 1, runs
    assert re.search(r'npm publish "\./npm/[^"]+\.tgz"', runs[0]), f"publish-npm: npm publish \"./npm/<archive>.tgz\", got: {runs[0]}"
