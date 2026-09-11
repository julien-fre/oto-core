"""Le client HelloStock confronté au CONTRAT OpenAPI lui-même, pas à sa copie.

Le contrat vit dans le dépôt de la plateforme HelloStock, qui n'est pas public : ce
banc ne tourne donc que là où il est lisible, désigné par la variable
`HELLOSTOCK_ADMIN_OPENAPI` (chemin du fichier `admin.json`). Ailleurs il est SAUTÉ,
et le dit — un vert obtenu sans le contrat ne prouve rien sur lui.

Ce qu'il vérifie, en jouant chaque méthode du client contre un transport qui
enregistre au lieu d'envoyer :

- chaque (verbe, chemin) appelé existe dans le contrat ;
- les paramètres de query envoyés sont EXACTEMENT ceux que le contrat déclare pour
  cette route — un filtre ajouté côté plateforme apparaît ici comme un écart ;
- les champs de corps envoyés existent dans le schéma de requête ;
- les référentiels publiés par le client égalent les énumérations du contrat.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from oto.tools.hellostock import client as hs

_PATH = os.environ.get("HELLOSTOCK_ADMIN_OPENAPI")

pytestmark = pytest.mark.skipif(
    not _PATH or not Path(_PATH).is_file(),
    reason="contrat HelloStock non lisible ici (HELLOSTOCK_ADMIN_OPENAPI non posé)")


@pytest.fixture(scope="module")
def contract():
    return json.loads(Path(_PATH).read_text(encoding="utf-8"))


class _Resp:
    status_code = 200
    headers: dict = {}

    def json(self):
        return {"items": [], "nextCursor": None, "total": 0, "success": True}


@pytest.fixture()
def recorded(monkeypatch):
    seen = []

    def fake_request(self, method, url, params=None, json=None, **kw):
        seen.append((method, url, dict(params or {}), json))
        return _Resp()

    monkeypatch.setattr(hs.requests.Session, "request", fake_request)
    return seen


# Chaque méthode, avec TOUS ses paramètres renseignés.
_CALLS = [
    ("list_demandes", (), dict(status="declared", since="2026-01-01",
                               until="2026-02-01", departement="69", matiere="inox",
                               service="x", q="t", limit=1, cursor="1")),
    ("get_demande", (1,), {}),
    ("update_demande_status", (1, "closed"), {}),
    ("send_demande", (1, [2]), dict(message="m")),
    ("list_offres", (), dict(status="declared", since="2026-01-01", until="2026-02-01",
                             departement="69", matiere="inox", certificat="dispo",
                             q="t", limit=1, cursor="1")),
    ("get_offre", (1,), {}),
    ("update_offre", (1,), dict(status="closed", keywords=["304L"])),
    ("list_users", (), dict(q="t", sector="autre", service="x", is_admin=True,
                            has_offres=True, has_demandes=False, limit=1, cursor="1")),
    ("get_user", (1,), {}),
    ("list_positionnements", (), dict(demande_id=1, user_id=2, since="2026-01-01",
                                      limit=1, cursor="1")),
]


def _template(contract, url: str) -> str:
    path = url.split("://", 1)[1].split("/", 1)[1]
    path = "/" + path
    for tpl in contract["paths"]:
        if re.fullmatch(re.sub(r"\{[^}]+\}", r"[^/]+", tpl), path):
            return tpl
    raise AssertionError(f"chemin absent du contrat : {path}")


def _body_props(contract, op) -> set:
    schema = op["requestBody"]["content"]["application/json"]["schema"]
    if "$ref" in schema:
        schema = contract["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]]
    return set(schema.get("properties", {}))


def test_every_client_call_matches_a_contract_operation(contract, recorded):
    c = hs.HelloStockAdminClient(token="hs_x", base_url="https://h.test")
    for name, args, kwargs in _CALLS:
        getattr(c, name)(*args, **kwargs)
    ecarts = []
    for (method, url, params, body), (name, _, _) in zip(recorded, _CALLS):
        tpl = _template(contract, url)
        op = contract["paths"][tpl].get(method.lower())
        if op is None:
            ecarts.append(f"{name} : {method} {tpl} absent du contrat")
            continue
        declared = {p["name"] for p in op.get("parameters", []) if p["in"] == "query"}
        if set(params) != declared:
            ecarts.append(f"{name} : query envoyée {sorted(params)} ≠ contrat "
                          f"{sorted(declared)}")
        if body is not None and not set(body) <= _body_props(contract, op):
            ecarts.append(f"{name} : corps {sorted(body)} hors schéma")
    assert not ecarts, "\n".join(ecarts)


def test_every_contract_route_is_either_called_or_named_absent(contract, recorded):
    """Le contrat ne doit porter aucune opération que le client ignore sans le dire :
    les absences sont écrites dans l'en-tête du module, et nommées ici."""
    delibere = {("delete", "/api/admin/users/{id}"),
                ("put", "/api/admin/content/{slug}"),
                ("get", "/api/admin/positionnements/{id}/devis"),
                ("get", "/api/admin/openapi.json")}
    c = hs.HelloStockAdminClient(token="hs_x", base_url="https://h.test")
    for name, args, kwargs in _CALLS:
        getattr(c, name)(*args, **kwargs)
    called = {(m.lower(), _template(contract, u)) for m, u, _, _ in recorded}
    declared = {(m, p) for p, ops in contract["paths"].items() for m in ops
                if m in ("get", "post", "patch", "put", "delete")}
    assert declared - called == delibere


def _enum(contract, path, method, param):
    for p in contract["paths"][path][method]["parameters"]:
        if p["name"] == param:
            return tuple(p["schema"]["enum"])
    raise AssertionError(f"{param} absent de {method} {path}")


def test_the_published_referentials_equal_the_contract_enums(contract):
    assert hs.STATUSES == _enum(contract, "/api/admin/demandes", "get", "status")
    assert hs.STATUSES == _enum(contract, "/api/admin/offres", "get", "status")
    assert hs.MATIERES == _enum(contract, "/api/admin/demandes", "get", "matiere")
    assert hs.MATIERES == _enum(contract, "/api/admin/offres", "get", "matiere")
    assert hs.CERTIFICATS == _enum(contract, "/api/admin/offres", "get", "certificat")
    assert hs.SECTORS == _enum(contract, "/api/admin/users", "get", "sector")
