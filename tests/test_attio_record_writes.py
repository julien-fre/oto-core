"""Écritures de fiches Attio : ce qui part VRAIMENT sur le fil.

Deux signaux du 11/09/2026, migration du CRM d'une org vers Attio :
- **#887** — `update` sur une multisélection (ex. `domains`) ne faisait qu'AJOUTER :
  PATCH ajoute les valeurs passées, et une liste vide n'y change rien, sans erreur.
  Une valeur unique (domaine, adresse) coincée sur une fiche à fusionner ne se
  libérait par aucun appel. Attio : « Use the PUT endpoint to overwrite or remove
  multiselect attribute values ».
- **#886** — aucune fusion de deux fiches, alors qu'Attio expose
  `POST /v2/objects/{object}/records/merge`.

On juge sur le fil (verbe, chemin, corps), jamais à la lecture du code.
"""
from __future__ import annotations

import pytest

from oto.tools.attio import client as ac


@pytest.fixture()
def wire(monkeypatch):
    """Capture (method, endpoint, kwargs) du dernier appel HTTP."""
    seen = {}

    def fake_request(self, method, endpoint, **kwargs):
        seen.update(method=method, endpoint=endpoint, **kwargs)
        return {"data": {}}

    monkeypatch.setattr(ac.AttioClient, "_request", fake_request)
    return seen


def _client():
    return ac.AttioClient(api_key="attio-test-key")


def test_update_par_defaut_patche_et_ajoute(wire):
    _client().companies.update("r1", domains=[{"domain": "acme.com"}])
    assert wire["method"] == "PATCH"
    assert wire["endpoint"] == "objects/companies/records/r1"
    assert wire["json"] == {"data": {"values": {"domains": [{"domain": "acme.com"}]}}}


def test_update_qui_ecrase_part_en_put_et_peut_vider(wire):
    """PUT remplace la multisélection ; `[]` la vide — le geste qui manquait. Le
    drapeau ne part PAS dans les valeurs : ce n'est pas un attribut de la fiche."""
    _client().companies.update("r1", overwrite_multiselect=True, domains=[])
    assert wire["method"] == "PUT"
    assert wire["endpoint"] == "objects/companies/records/r1"
    assert wire["json"] == {"data": {"values": {"domains": []}}}


def test_merge_designe_le_primaire_et_le_secondaire(wire):
    _client().people.merge("prim", "sec")
    assert wire["method"] == "POST"
    assert wire["endpoint"] == "objects/people/records/merge"
    assert wire["json"] == {"data": {"primary_record_id": "prim",
                                     "secondary_record_id": "sec"}}
