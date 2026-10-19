"""Gardes par commit : la version d'un connecteur monte avec son code ; les exceptions en attente ne font que décroître.

`python -m fabrique.commits <avant> <après>` juge chaque commit de `avant..après`, un par un, contre son premier parent :
le verdict d'un commit ne dépend ni de son regroupement dans un push ou une PR, ni d'un rejeu (même patch, autre SHA).
Une base inconnue (premier push, `0000…`, commit absent de l'historique) ne juge que le commit de tête contre son
parent, et le dit ; un commit antérieur à `connectors/clients.yaml` (une PR ouverte avant la garde) est jugé avec
celui de la tête, et le dit aussi. La CI la lance sur une PR (de sa base à sa tête) et sur un push de `main` (d'avant
à après le push), avec l'historique entier (`fetch-depth: 0`) ; jamais sur un tag ni sur un dispatch.

**Version.** Le code d'un connecteur est sa description (tout fichier de `connectors/<nom>/`) et son client, ou la
partie de son client que rattache `connectors/clients.yaml` ; la lib commune, la fabrique, la sortie générée, les tests
et la version de la lib (`pyproject.toml`, `uv.lock`, le paquet npm) n'en sont pas. Quand un commit change le code d'un
connecteur qui existe avant et après lui, `connector.version` monte (semver), ou le commit porte, dans son bloc de
trailers (avec `Changelog:`), une dispense de la forme exacte :

    Version-dispense: <connecteur> — <raison>

La dispense ne vaut que pour le commit qui la porte. `Version-dispense: * — <raison>` dispense tous les connecteurs du
commit, seulement s'il touche `connectors/connector.schema.json` ou `fabrique/` (une passe sur tout le format). Une
version qui descend n'est jamais dispensée ; une dispense mal formée, hors du bloc de trailers, ou globale sans passe
sur le format fait échouer le commit.

**Exceptions en attente.** Un commit n'ajoute aucune entrée aux catégories en attente de `without_description`
(`fabrique/clients.py`) : un client nouveau entre au format, ou dans une catégorie de principe avec son motif.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass, field

import yaml

from .clients import CLIENTS_FILE, PRINCIPLE, Clients, parse

REPO = pathlib.Path(__file__).resolve().parent.parent
TRAILER = "Version-dispense"
DISPENSE_FORM = re.compile(r"^(\*|[a-z][a-z0-9_]*) — (\S.*)$")
RAW_DISPENSE = re.compile(rf"^{TRAILER}:.*$", re.MULTILINE)
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")
DESCRIPTION = re.compile(r"^connectors/([a-z][a-z0-9_]*)/connector\.yaml$")
FORMAT_PASS = ("connectors/connector.schema.json", "fabrique/")
UNKNOWN = re.compile(r"^0+$")


class GuardError(ValueError):
    """La garde ne peut pas juger : commit introuvable, version illisible."""


@dataclass
class CommitVerdict:
    sha: str
    subject: str
    notes: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def git(*args: str, root: pathlib.Path = REPO, stdin: str | None = None) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, input=stdin)
    if result.returncode != 0:
        raise GuardError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def _commit(ref: str, root: pathlib.Path) -> str | None:
    """Le SHA d'un commit de l'historique, ou `None` s'il est inconnu (`0000…`, ou absent)."""
    if UNKNOWN.match(ref):
        return None
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                            capture_output=True, text=True)
    if result.returncode != 0 and result.stderr.strip():
        raise GuardError(f"git rev-parse {ref}: {result.stderr.strip()}")
    return result.stdout.strip() if result.returncode == 0 else None


def semver_key(version: str) -> tuple:
    """Une clé d'ordre semver : une préversion précède sa version, ses identifiants numériques précèdent les autres."""
    match = SEMVER.match(version)
    if match is None:
        raise GuardError(f"version {version!r} is not semver")
    major, minor, patch, pre = match.groups()
    release = (int(major), int(minor), int(patch))
    if pre is None:
        return release + (1, ())
    return release + (0, tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split(".")))


def next_patch(version: str) -> str:
    match = SEMVER.match(version)
    if match is None:
        raise GuardError(f"version {version!r} is not semver")
    major, minor, patch, _ = match.groups()
    return f"{major}.{minor}.{int(patch) + 1}"


def dispenses(message: str, root: pathlib.Path = REPO) -> tuple[dict[str, str], list[str]]:
    """Les dispenses du bloc de trailers d'un message (connecteur ou `*` → raison), et ses fautes de forme."""
    trailers = git("interpret-trailers", "--parse", root=root, stdin=message).splitlines()
    found, faults = {}, []
    read = 0
    for line in trailers:
        key, _, value = line.partition(": ")
        if key != TRAILER:
            continue
        read += 1
        form = DISPENSE_FORM.match(value.strip())
        if form is None:
            faults.append(f"malformed trailer '{line}': expected '{TRAILER}: <connector> — <reason>'")
        else:
            found[form.group(1)] = form.group(2).strip()
    if len(RAW_DISPENSE.findall(message)) > read:
        faults.append(f"a '{TRAILER}:' line is outside the trailer block (the last paragraph, with Changelog:): "
                      f"git does not read it as a trailer")
    return found, faults


def _clients_at(commit: str, root: pathlib.Path) -> Clients | None:
    if not git("ls-tree", commit, "--", str(CLIENTS_FILE), root=root).strip():
        return None
    return parse(git("show", f"{commit}:{CLIENTS_FILE}", root=root))


def _version(commit: str, name: str, root: pathlib.Path) -> str:
    text = git("show", f"{commit}:connectors/{name}/connector.yaml", root=root)
    version = (yaml.safe_load(text) or {}).get("connector", {}).get("version")
    if not isinstance(version, str):
        raise GuardError(f"{commit[:12]}: connectors/{name}/connector.yaml has no connector.version")
    return version


def _connectors(commit: str, root: pathlib.Path) -> set[str]:
    names = git("ls-tree", "-r", "--name-only", commit, "--", "connectors", root=root).splitlines()
    return {match.group(1) for match in map(DESCRIPTION.match, names) if match}


def judge_commit(ref: str, root: pathlib.Path = REPO, clients: Clients | None = None,
                 tip: str | None = None) -> CommitVerdict:
    """Un commit contre son premier parent. `clients` : celui du commit par défaut ; un commit antérieur à
    `connectors/clients.yaml` (une PR ouverte avant la garde) prend celui de `tip`, la tête jugée, et le dit. Un commit
    de fusion n'est jugé que sur ce qu'il change lui-même (la résolution d'un conflit) : les commits fusionnés le sont un
    par un."""
    sha = _commit(ref, root)
    if sha is None:
        raise GuardError(f"commit {ref!r} not found: the guard needs the whole history (fetch-depth: 0)")
    parents = git("rev-list", "--parents", "-n", "1", sha, root=root).split()[1:]
    message = git("log", "-1", "--format=%B", sha, root=root)
    verdict = CommitVerdict(sha, message.splitlines()[0] if message else "")
    if not parents:
        verdict.notes.append("root commit: nothing to compare")
        return verdict
    parent = parents[0]
    if len(parents) == 1:
        paths = git("diff-tree", "-r", "--no-renames", "--no-commit-id", "--name-only", parent, sha, root=root).splitlines()
    else:
        paths = git("diff-tree", "-r", "--cc", "--no-commit-id", "--name-only", sha, root=root).splitlines()
        verdict.notes.append("merge commit: judged on its own changes only")
    own = _clients_at(sha, root) if clients is None else clients
    if own is None and tip is not None:
        own = _clients_at(tip, root)
        verdict.notes.append(f"{CLIENTS_FILE} absent from this commit: judged with the one of {tip[:12]}")
    if own is None:
        raise GuardError(f"{sha[:12]}: {CLIENTS_FILE} is missing")
    granted, faults = dispenses(message, root)
    verdict.failures += faults
    if "*" in granted and not any(p == FORMAT_PASS[0] or p.startswith(FORMAT_PASS[1]) for p in paths):
        verdict.failures.append(
            f"'{TRAILER}: * — …' is refused: this commit touches neither {FORMAT_PASS[0]} nor {FORMAT_PASS[1]}; "
            f"name each connector instead"
        )
        granted.pop("*")
    before, after = _connectors(parent, root), _connectors(sha, root)
    for name, touching in sorted(own.connectors_touched(paths, before | after).items()):
        if name not in before or name not in after:
            continue
        old, new = _version(parent, name, root), _version(sha, name, root)
        where = ", ".join(touching)
        if semver_key(new) > semver_key(old):
            verdict.notes.append(f"{name} {old} -> {new}: version raised ({where})")
        elif semver_key(new) < semver_key(old):
            verdict.failures.append(f"{name} {old} -> {new}: version lowered, never dispensed ({where})")
        elif name in granted or "*" in granted:
            verdict.notes.append(f"{name} {old}: dispensed, {granted.get(name, granted.get('*'))} ({where})")
        else:
            verdict.failures.append(
                f"{name}: code changed ({where}), version unchanged: connector.version {old} → {next_patch(old)}, "
                f"or the trailer '{TRAILER}: {name} — <reason>'"
            )
    previous = _clients_at(parent, root)
    if previous is None:
        verdict.notes.append(f"{CLIENTS_FILE} introduced by this commit: no pending list to compare")
    else:
        for name in sorted(own.pending() - previous.pending()):
            entry = own.without_description[name]
            verdict.failures.append(
                f"{CLIENTS_FILE}: {name!r} enters the pending category {entry.category}, which only shrinks: describe "
                f"the client, or name it in a principle category ({', '.join(PRINCIPLE)}) with its reason"
            )
    return verdict


def commits_between(before: str, after: str, root: pathlib.Path = REPO) -> tuple[list[str], str | None]:
    """Les commits à juger, du plus ancien au plus récent, et une note quand la base est inconnue."""
    head = _commit(after, root)
    if head is None:
        raise GuardError(f"commit {after!r} not found: the guard needs the whole history (fetch-depth: 0)")
    base = _commit(before, root)
    if base is None:
        return [head], f"base {before!r} unknown (first push, or out of the history): only the head commit is judged"
    return git("rev-list", "--reverse", "--topo-order", f"{base}..{head}", root=root).split(), None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m fabrique.commits", description=__doc__.split("\n\n")[0])
    parser.add_argument("before")
    parser.add_argument("after", nargs="?", default="HEAD")
    args = parser.parse_args(argv)
    try:
        shas, note = commits_between(args.before, args.after, root=REPO)
        if note:
            print(f"commit guard: {note}")
        if not shas:
            print("commit guard: no new commit")
        verdicts = [judge_commit(sha, root=REPO, tip=shas[-1]) for sha in shas]
    except GuardError as error:
        print(f"commit guard: {error}", file=sys.stderr)
        return 1
    for v in verdicts:
        print(f"{'ok  ' if v.ok else 'FAIL'} {v.sha[:12]} {v.subject}")
        for line in v.notes:
            print(f"     {line}")
        for line in v.failures:
            print(f"     FAIL {line}")
    return 0 if all(v.ok for v in verdicts) else 1


if __name__ == "__main__":
    sys.exit(main())
