"""La surface de `DropcontactClient` est un CONTRAT, pas un détail.

Un consommateur épingle la lib par tag et importe `oto.tools.dropcontact.client` : renommer une méthode, changer un
défaut ou déplacer un symbole casse un consommateur au bump du pin, loin d'ici. Ce test fige les membres AVEC leurs
signatures, les noms importables et la correspondance entre les fonctions de la description et les méthodes du client.

⚠️ Ce test échoue si tu ajoutes une méthode : c'est voulu — mets à jour la constante EN CONNAISSANCE DE CAUSE, jamais
par réflexe pour faire passer le vert.
"""
import inspect
import pathlib

import yaml

import oto.tools.dropcontact.client as mod

ROOT = pathlib.Path(__file__).resolve().parent.parent
DESCRIPTION = ROOT / "connectors" / "dropcontact" / "connector.yaml"

EXPECTED_MEMBERS = {
    '_headers': "(self) -> 'dict'",
    'check_credits': "(self) -> 'dict'",
    'fetch': "(self, request_id: 'str', *, force_results: 'bool' = False) -> 'dict'",
    'submit': "(self, contacts: 'list[dict]', *, siren: 'bool' = False, language: 'str | None' = None, "
              "custom_callback_url: 'str | None' = None) -> 'dict'",
}


def _members():
    return {n: str(inspect.signature(getattr(mod.DropcontactClient, n)))
            for n in dir(mod.DropcontactClient)
            if not n.startswith("__") and callable(getattr(mod.DropcontactClient, n))}


def _functions():
    return {f["name"]: f for f in yaml.safe_load(DESCRIPTION.read_text(encoding="utf-8"))["functions"]}


def test_membres_et_signatures_figes():
    assert _members() == EXPECTED_MEMBERS


def test_constructeur_fige():
    assert str(inspect.signature(mod.DropcontactClient.__init__)) == "(self, api_key: 'str | None' = None)"


def test_noms_importables():
    assert mod.DropcontactClient.BASE_URL == "https://api.dropcontact.com/v1"
    assert mod.DropcontactClient.__mro__ == (mod.DropcontactClient, object)
    assert (mod.MAX_CONTACTS_PER_BATCH, mod.MAX_CONTACT_BYTES) == (250, 15_000)


def test_une_fonction_decrite_est_une_methode_du_meme_nom():
    assert set(_functions()) == {n for n in EXPECTED_MEMBERS if not n.startswith("_")}
