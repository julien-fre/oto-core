"""La surface de `PipecornClient` est un CONTRAT, pas un détail.

oto-backend épingle oto-core par tag et importe `oto.tools.pipecorn` : renommer une
méthode, changer un défaut ou déplacer un symbole hors de `client.py` casse un
consommateur au bump du pin, loin d'ici. Ce test fige les membres AVEC leurs
signatures, les noms importables depuis `oto.tools.pipecorn[.client]` et la taille des
modules du paquet. Pipecorn n'a pas de description (`connectors/clients.yaml` dit
pourquoi) : aucune correspondance à vérifier.

⚠️ Ce test échoue si tu ajoutes une méthode : c'est voulu — mets à jour la
constante EN CONNAISSANCE DE CAUSE, jamais par réflexe pour faire passer le vert.
"""
import inspect
import pathlib

import oto.tools.pipecorn as pkg
import oto.tools.pipecorn.client as mod

EXPECTED_MEMBERS = {
    '_body': "(self, enrichment_type, linkedin_url, firstname, lastname, domain, company_name, phone_type, phone_country_codes, custom) -> 'Dict[str, Any]'",
    '_call': "(self, method: 'str', url: 'str', *, json: 'Optional[dict]' = None, headers: 'Optional[dict]' = None, timeout=(10, 60)) -> 'Any'",
    '_kinds': "(enrichment_type: 'Any') -> 'List[str]'",
    'enrich_contact': "(self, enrichment_type: 'List[str]', *, linkedin_url: 'Optional[str]' = None, firstname: 'Optional[str]' = None, lastname: 'Optional[str]' = None, domain: 'Optional[str]' = None, company_name: 'Optional[str]' = None, phone_type: 'Optional[str]' = None, phone_country_codes: 'Optional[List[str]]' = None, custom: 'Optional[Dict[str, Any]]' = None, idempotency_key: 'Optional[str]' = None, timeout=(10, 60)) -> 'Dict[str, Any]'",
    'get_enrichment': "(self, enrichment_id: 'str') -> 'Dict[str, Any]'",
    'get_account_info': "(self) -> 'Dict[str, Any]'",
    'get_credits': "(self) -> 'Dict[str, Any]'",
    'probe': "(self) -> 'Any'",
    'submit_enrichment': "(self, enrichment_type: 'List[str]', *, linkedin_url: 'Optional[str]' = None, firstname: 'Optional[str]' = None, lastname: 'Optional[str]' = None, domain: 'Optional[str]' = None, company_name: 'Optional[str]' = None, phone_type: 'Optional[str]' = None, phone_country_codes: 'Optional[List[str]]' = None, custom: 'Optional[Dict[str, Any]]' = None, idempotency_key: 'Optional[str]' = None) -> 'Dict[str, Any]'",
}


def _members():
    return {n: str(inspect.signature(getattr(mod.PipecornClient, n)))
            for n in dir(mod.PipecornClient)
            if not n.startswith("__") and callable(getattr(mod.PipecornClient, n))}


def test_membres_et_signatures_figes():
    assert _members() == EXPECTED_MEMBERS


def test_constructeur_fige():
    assert str(inspect.signature(mod.PipecornClient.__init__)) == \
        "(self, api_key: 'Optional[str]' = None)"


def test_noms_importables():
    assert pkg.__all__ == ["PipecornClient", "credits_spent"]
    for name in ("PipecornClient", "credits_spent", "BASE_URL", "SYNC_URL", "HTTP_TIMEOUT",
                 "ENRICHMENT_TYPES", "PHONE_TYPES", "CREDITS", "MOBILE_TYPES"):
        assert hasattr(mod, name), name


def test_aucun_module_de_500_lignes_ou_plus():
    package = pathlib.Path(mod.__file__).parent
    for path in package.rglob("*.py"):
        assert len(path.read_text(encoding="utf-8").splitlines()) < 500, path
