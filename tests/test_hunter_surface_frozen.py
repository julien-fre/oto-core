"""La surface de `HunterClient` est un CONTRAT, pas un détail.

Un consommateur épingle la lib par tag et importe `oto.tools.hunter` : renommer une méthode, changer un défaut ou
déplacer un symbole casse un consommateur au bump du pin, loin d'ici. Ce test fige les membres AVEC leurs signatures,
les noms importables et la correspondance entre les fonctions de la description et les méthodes du client.

⚠️ Ce test échoue si tu ajoutes une méthode : c'est voulu — mets à jour la constante EN CONNAISSANCE DE CAUSE, jamais
par réflexe pour faire passer le vert.
"""
import inspect
import pathlib

import yaml

import oto.tools.hunter as pkg
import oto.tools.hunter.client as mod

ROOT = pathlib.Path(__file__).resolve().parent.parent
DESCRIPTION = ROOT / "connectors" / "hunter" / "connector.yaml"

EXPECTED_MEMBERS = {
    '_request': "(self, endpoint: str, params: Dict = None) -> Dict[str, Any]",
    '_upstream_message': "(response: requests.models.Response) -> str",
    'account_info': "(self) -> Dict[str, Any]",
    'domain_search': "(self, domain: str, limit: int = 10) -> Dict[str, Any]",
    'email_finder': "(self, domain: str, first_name: str = None, last_name: str = None, full_name: str = None) -> Dict[str, Any]",
    'email_verifier': "(self, email: str) -> Dict[str, Any]",
}


def _members():
    return {n: str(inspect.signature(getattr(mod.HunterClient, n)))
            for n in dir(mod.HunterClient)
            if not n.startswith("__") and callable(getattr(mod.HunterClient, n))}


def _functions():
    return {f["name"]: f for f in yaml.safe_load(DESCRIPTION.read_text(encoding="utf-8"))["functions"]}


def test_membres_et_signatures_figes():
    assert _members() == EXPECTED_MEMBERS


def test_constructeur_fige():
    assert str(inspect.signature(mod.HunterClient.__init__)) == "(self, api_key: str = None)"


def test_noms_importables():
    assert pkg.__all__ == ["HunterClient"]
    assert pkg.HunterClient is mod.HunterClient
    assert mod.HunterClient.BASE_URL == "https://api.hunter.io/v2"
    assert mod.HunterClient.__mro__ == (mod.HunterClient, object)
    assert issubclass(mod.HunterError, RuntimeError)


def test_une_fonction_decrite_est_une_methode_du_meme_nom():
    assert set(_functions()) == {n for n in EXPECTED_MEMBERS if not n.startswith("_")}
