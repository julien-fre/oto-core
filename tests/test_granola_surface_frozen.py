"""La surface de `GranolaClient` est un CONTRAT, pas un détail.

Un consommateur épingle la lib par tag et importe `oto.tools.granola` : renommer une méthode, changer un défaut ou
déplacer un symbole casse un consommateur au bump du pin, loin d'ici. Ce test fige les membres AVEC leurs signatures,
les noms importables et la correspondance entre les fonctions de la description et les méthodes du client.

⚠️ Ce test échoue si tu ajoutes une méthode : c'est voulu — mets à jour la constante EN CONNAISSANCE DE CAUSE, jamais
par réflexe pour faire passer le vert.
"""
import inspect
import pathlib

import yaml

import oto.tools.granola as pkg
import oto.tools.granola.client as mod

ROOT = pathlib.Path(__file__).resolve().parent.parent
DESCRIPTION = ROOT / "connectors" / "granola" / "connector.yaml"

EXPECTED_MEMBERS = {
    '_delete': "(self, path: 'str') -> 'Any'",
    '_get': "(self, path: 'str', **params: 'Any') -> 'Any'",
    '_patch': "(self, path: 'str', body: 'Dict[str, Any]') -> 'Any'",
    '_post': "(self, path: 'str', body: 'Dict[str, Any]') -> 'Any'",
    '_request': "(self, method: 'str', path: 'str', *, params: 'Optional[Dict[str, Any]]' = None, json_body: 'Any' = None) -> 'Any'",
    'create_webhook_endpoint': "(self, url: 'str', scopes: 'List[str]', **body: 'Any') -> 'Any'",
    'delete_webhook_endpoint': "(self, webhook_endpoint_id: 'str') -> 'Any'",
    'get_note': "(self, note_id: 'str', **params: 'Any') -> 'Any'",
    'get_transcript': "(self, note_id: 'str', **params: 'Any') -> 'Any'",
    'list_folders': "(self, **params: 'Any') -> 'Any'",
    'list_notes': "(self, **params: 'Any') -> 'Any'",
    'list_webhook_endpoints': "(self) -> 'Any'",
    'update_webhook_endpoint': "(self, webhook_endpoint_id: 'str', **body: 'Any') -> 'Any'",
}


def _members():
    return {n: str(inspect.signature(getattr(mod.GranolaClient, n)))
            for n in dir(mod.GranolaClient)
            if not n.startswith("__") and callable(getattr(mod.GranolaClient, n))}


def _functions():
    return {f["name"]: f for f in yaml.safe_load(DESCRIPTION.read_text(encoding="utf-8"))["functions"]}


def test_membres_et_signatures_figes():
    assert _members() == EXPECTED_MEMBERS


def test_constructeur_fige():
    assert str(inspect.signature(mod.GranolaClient.__init__)) == "(self, api_key: 'Optional[str]' = None)"


def test_noms_importables():
    assert pkg.__all__ == ["GranolaClient"]
    assert pkg.GranolaClient is mod.GranolaClient
    assert mod.GranolaClient.BASE_URL == "https://public-api.granola.ai"
    assert mod.GranolaClient.__mro__ == (mod.GranolaClient, object)


def test_une_fonction_decrite_est_une_methode_du_meme_nom():
    assert set(_functions()) == {n for n in EXPECTED_MEMBERS if not n.startswith("_")}
