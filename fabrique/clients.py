"""Les clients Python de la lib et leurs descriptions (`connectors/clients.yaml`).

Un client est une entrée directe de `oto/tools/` (un paquet ou un module, hors `__init__.py`), ou un sous-paquet d'une
famille que le fichier déclare (`google` : un paquet par service). Le code qu'une description couvre :

- par défaut, tout le client du même nom que le connecteur ;
- `described_by` rattache un client entier à un connecteur d'un autre nom (`unipile: linkedin_unipile`), ou seulement
  des fichiers et sous-dossiers d'un client (`microsoft/files.py: microsoft`) : dès qu'un client a une telle entrée,
  seuls les chemins nommés sont le code d'un connecteur, le reste du client (le courrier d'un paquet dont la description
  ne couvre que les fichiers) ne l'est pas.

Un client sans description figure dans `without_description`, avec sa catégorie et sa raison. Trois catégories de
principe admettent une entrée nouvelle ; les deux catégories en attente ne font que décroître : un client nouveau entre
au format (garde par commit, `fabrique/commits.py`).

Ce module ne lit que YAML et des chemins : la garde par commit le charge sans `jsonschema`.
"""
from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
TOOLS = pathlib.PurePosixPath("oto/tools")
CLIENTS_FILE = pathlib.PurePosixPath("connectors/clients.yaml")
CONNECTOR = re.compile(r"^connectors/([a-z][a-z0-9_]*)/")
NOT_A_CLIENT = {"__init__.py", "__pycache__"}
# Catégories d'un client sans description. De principe : une entrée nouvelle y est admise, avec son motif.
PRINCIPLE = {
    "not_a_service_client": "pas le client d'un service",
    "not_describable": "le format ne sait pas le dire",
    "oto_service": "client d'un service d'oto",
}
# En attente : la liste ne fait que décroître, un client nouveau entre au format.
PENDING = {
    "before_the_rule": "antérieur à la règle du 05/10, pas encore décrit",
    "not_described_yet": "pas encore décrit",
}


class ClientsError(ValueError):
    """`connectors/clients.yaml` contredit les clients ou les descriptions du dépôt : le message dit l'entrée."""


@dataclass(frozen=True)
class Undescribed:
    category: str
    reason: str


@dataclass(frozen=True)
class Clients:
    families: dict[str, str]
    described_by: dict[str, str]
    without_description: dict[str, Undescribed]

    def client_of(self, path: str) -> str | None:
        """Le client auquel appartient un chemin du dépôt, ou `None` hors de `oto/tools/` et pour `__init__.py`."""
        parts = pathlib.PurePosixPath(path).parts
        if parts[:2] != TOOLS.parts or len(parts) < 3 or parts[2] in NOT_A_CLIENT:
            return None
        if parts[2] in self.families:
            if len(parts) < 4 or parts[3] in NOT_A_CLIENT:
                return None
            return f"{parts[2]}/{parts[3]}"
        return parts[2]

    def _narrowed(self, client: str) -> bool:
        """Le client a des entrées de `described_by` sur une partie de lui seulement."""
        return any(key.startswith(client + "/") for key in self.described_by)

    def connector_of_path(self, path: str, connectors: set[str]) -> str | None:
        """Le connecteur dont un chemin de `oto/tools/` est le code, ou `None`."""
        client = self.client_of(path)
        if client is None:
            return None
        inside = path.removeprefix(f"{TOOLS}/")
        keys = [key for key in self.described_by if inside == key or inside.startswith(key + "/")]
        if keys:
            return self.described_by[max(keys, key=len)]
        if self._narrowed(client):
            return None
        return self.connector_of(client, connectors)

    def connector_of(self, client: str, connectors: set[str]) -> str | None:
        """Le connecteur dont la description couvre ce client, en tout ou en partie."""
        if client in self.described_by:
            return self.described_by[client]
        narrowed = sorted({c for key, c in self.described_by.items() if key.startswith(client + "/")})
        if narrowed:
            return narrowed[0]
        name = client.removesuffix(".py")
        return name if name in connectors else None

    def connectors_touched(self, paths: list[str], connectors: set[str]) -> dict[str, list[str]]:
        """Pour chaque connecteur dont le code change, les chemins qui le touchent : sa description
        (`connectors/<nom>/`) et son client, ou la partie de son client que nomme `described_by`. Le reste (la lib
        commune, la fabrique, la sortie générée, les tests, la version de la lib) n'est le code d'aucun connecteur."""
        touched: dict[str, list[str]] = {}
        for path in paths:
            match = CONNECTOR.match(path)
            name = match.group(1) if match else self.connector_of_path(path, connectors)
            if name is not None:
                touched.setdefault(name, []).append(path)
        return touched

    def pending(self) -> set[str]:
        return {name for name, entry in self.without_description.items() if entry.category in PENDING}


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def parse(text: str) -> Clients:
    data = yaml.safe_load(text)
    if not isinstance(data, dict) or set(data) != {"families", "described_by", "without_description"}:
        raise ClientsError(f"{CLIENTS_FILE}: expects exactly families, described_by and without_description")
    for key in ("families", "described_by"):
        if not isinstance(data[key], dict) or not all(isinstance(k, str) and _text(v) for k, v in data[key].items()):
            raise ClientsError(f"{CLIENTS_FILE}: {key} maps each name to a non-empty text")
    exceptions = {}
    categories = {**PRINCIPLE, **PENDING}
    if not isinstance(data["without_description"], dict):
        raise ClientsError(f"{CLIENTS_FILE}: without_description maps each client to its category and reason")
    for name, entry in data["without_description"].items():
        if not isinstance(entry, dict) or set(entry) != {"category", "reason"} or not _text(entry["reason"]):
            raise ClientsError(f"{CLIENTS_FILE}: without_description {name!r}: expects a category and a non-empty reason")
        if entry["category"] not in categories:
            raise ClientsError(
                f"{CLIENTS_FILE}: without_description {name!r}: category {entry['category']!r} is none of "
                f"{', '.join(categories)}"
            )
        exceptions[name] = Undescribed(entry["category"], entry["reason"].strip())
    return Clients(families=data["families"], described_by=data["described_by"], without_description=exceptions)


def load(root: pathlib.Path = REPO) -> Clients:
    return parse((root / CLIENTS_FILE).read_text(encoding="utf-8"))


def connector_names(root: pathlib.Path = REPO) -> set[str]:
    return {path.parent.name for path in (root / "connectors").glob("*/connector.yaml")}


def list_clients(clients: Clients, root: pathlib.Path = REPO) -> list[str]:
    """Tous les clients de la lib, une famille dépliée en ses sous-paquets."""
    found = []
    for entry in sorted((root / TOOLS).iterdir()):
        if entry.name in NOT_A_CLIENT:
            continue
        if entry.name in clients.families:
            found += [f"{entry.name}/{sub.name}" for sub in sorted(entry.iterdir())
                      if sub.is_dir() and sub.name not in NOT_A_CLIENT]
        else:
            found.append(entry.name)
    return found


def check(clients: Clients, root: pathlib.Path = REPO) -> None:
    """Chaque client a sa description ou une exception motivée ; le fichier ne nomme rien qui n'existe pas, et aucune
    exception ne survit à la description de son client."""
    connectors = connector_names(root)
    present = list_clients(clients, root)
    for family in clients.families:
        if not (root / TOOLS / family).is_dir():
            raise ClientsError(f"{CLIENTS_FILE}: family {family!r} is no package of {TOOLS}")
    for key, connector in clients.described_by.items():
        client = clients.client_of(f"{TOOLS}/{key}")
        if client is None or client not in present or not (root / TOOLS / key).exists():
            raise ClientsError(f"{CLIENTS_FILE}: described_by names {key!r}, which is no client of {TOOLS} nor part of one")
        if connector not in connectors:
            raise ClientsError(f"{CLIENTS_FILE}: described_by maps {key!r} to {connector!r}, which has no description")
        if key == client and key in connectors:
            raise ClientsError(f"{CLIENTS_FILE}: {key!r} has a description of its own name: drop it from described_by")
        if key == client and clients._narrowed(client):
            raise ClientsError(f"{CLIENTS_FILE}: described_by names {key!r} whole and in part: keep one")
    for client in clients.without_description:
        if client not in present:
            raise ClientsError(f"{CLIENTS_FILE}: without_description names {client!r}, which is no client of {TOOLS}")
        if clients.connector_of(client, connectors) is not None:
            raise ClientsError(f"{CLIENTS_FILE}: {client!r} now has its description: drop it from without_description")
    missing = [c for c in present if clients.connector_of(c, connectors) is None and c not in clients.without_description]
    if missing:
        raise ClientsError(
            f"client(s) without a description: {', '.join(missing)}. Describe each in connectors/<name>/connector.yaml, "
            f"or name it in {CLIENTS_FILE} (without_description) in a principle category "
            f"({', '.join(PRINCIPLE)}) with its reason: a new client never enters a pending category"
        )
