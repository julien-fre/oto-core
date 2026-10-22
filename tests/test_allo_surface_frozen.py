"""La surface de `AlloClient` est un CONTRAT, pas un détail.

oto-backend épingle oto-core par tag et importe `oto.tools.allo` : renommer une méthode, changer un défaut ou déplacer
un symbole hors de `client.py` casse un consommateur au bump du pin, loin d'ici. Ce test fige les membres AVEC leurs
signatures, les noms importables, la correspondance entre les fonctions de la description et les méthodes du client,
et la taille des modules du paquet.

⚠️ Ce test échoue si tu ajoutes une méthode : c'est voulu — mets à jour la constante EN CONNAISSANCE DE CAUSE, jamais
par réflexe pour faire passer le vert.
"""
import inspect
import pathlib

import yaml

import oto.tools.allo as pkg
import oto.tools.allo.client as mod

ROOT = pathlib.Path(__file__).resolve().parent.parent
DESCRIPTION = ROOT / "connectors" / "allo" / "connector.yaml"

EXPECTED_MEMBERS = {
    '_request': "(self, method: 'str', path: 'str', *, params: 'Optional[Dict[str, Any]]' = None, body: 'Optional[Dict[str, Any]]' = None) -> 'Any'",
    '_send': "(self, method: 'str', path: 'str', *, params: 'Optional[Dict[str, Any]]' = None, body: 'Optional[Dict[str, Any]]' = None, stream: 'bool' = False) -> 'requests.Response'",
    'add_item_tags': "(self, item_id: 'str', tags: 'List[str]') -> 'Any'",
    'add_queue_numbers': "(self, numbers: 'List[Dict[str, Any]]', *, user_id: 'Optional[str]' = None, email: 'Optional[str]' = None) -> 'Any'",
    'create_company': "(self, name: 'str', **fields: 'Any') -> 'Any'",
    'create_conversation_note': "(self, contact_number: 'str', content: 'str', *, allo_number: 'Optional[str]' = None, sender_id: 'Optional[str]' = None) -> 'Any'",
    'create_person': "(self, numbers: 'List[str]', **fields: 'Any') -> 'Any'",
    'create_person_note': "(self, person_id: 'str', content: 'str') -> 'Any'",
    'create_tag': "(self, name: 'str', *, color: 'Optional[str]' = None) -> 'Any'",
    'get_call_recording': "(self, item_id: 'str') -> 'FileOut'",
    'get_company': "(self, company_id: 'str') -> 'Any'",
    'get_conversation_item': "(self, item_id: 'str', *, extend: 'Optional[str]' = None) -> 'Any'",
    'get_conversation_items': "(self, ids: 'List[str]') -> 'Any'",
    'get_deal': "(self, deal_id: 'str') -> 'Any'",
    'get_dialing_queue': "(self, *, user_id: 'Optional[str]' = None, email: 'Optional[str]' = None, page: 'Optional[int]' = None, size: 'Optional[int]' = None) -> 'Any'",
    'get_me': "(self) -> 'Any'",
    'get_outbound_metrics': "(self, date: 'Dict[str, str]', *, compare_date: 'Optional[Dict[str, str]]' = None, user_ids: 'Optional[List[str]]' = None, allo_numbers: 'Optional[List[str]]' = None, tags: 'Optional[List[str]]' = None, granularity: 'Optional[str]' = None, extend: 'Optional[str]' = None, stage: 'Optional[str]' = None, page: 'Optional[int]' = None, size: 'Optional[int]' = None) -> 'Any'",
    'get_person': "(self, person_id: 'str') -> 'Any'",
    'get_team_metrics': "(self, date: 'Dict[str, str]', *, compare_date: 'Optional[Dict[str, str]]' = None, user_ids: 'Optional[List[str]]' = None, allo_numbers: 'Optional[List[str]]' = None) -> 'Any'",
    'list_company_attributes': "(self, *, page: 'Optional[int]' = None, size: 'Optional[int]' = None) -> 'Any'",
    'list_conversation_notes': "(self, contact_number: 'str', allo_number: 'str', *, page: 'Optional[int]' = None, size: 'Optional[int]' = None) -> 'Any'",
    'list_conversations': "(self, allo_number: 'str', *, last_activity_since: 'Optional[str]' = None, unread: 'Optional[bool]' = None, page: 'Optional[int]' = None, size: 'Optional[int]' = None, extend: 'Optional[str]' = None) -> 'Any'",
    'list_numbers': "(self) -> 'Any'",
    'list_person_attributes': "(self, *, page: 'Optional[int]' = None, size: 'Optional[int]' = None) -> 'Any'",
    'list_person_notes': "(self, person_id: 'str', *, page: 'Optional[int]' = None, size: 'Optional[int]' = None) -> 'Any'",
    'list_tags': "(self) -> 'Any'",
    'list_users': "(self, *, role: 'Optional[str]' = None, status: 'Optional[str]' = None) -> 'Any'",
    'probe': "(self) -> 'Any'",
    'remove_item_tag': "(self, item_id: 'str', tag: 'str') -> 'Any'",
    'remove_queue_numbers': "(self, *, number: 'Optional[str]' = None, position: 'Optional[int]' = None, unassigned: 'Optional[bool]' = None, user_id: 'Optional[str]' = None, email: 'Optional[str]' = None) -> 'Any'",
    'reset_dialing_queue': "(self, *, name: 'Optional[str]' = None, user_id: 'Optional[str]' = None, email: 'Optional[str]' = None) -> 'Any'",
    'search_companies': "(self, *, filters: 'Optional[Dict[str, Any]]' = None, sort: 'Optional[str]' = None, page: 'Optional[int]' = None, size: 'Optional[int]' = None) -> 'Any'",
    'search_conversation_items': "(self, *, allo_number: 'Optional[str]' = None, contact_number: 'Optional[str]' = None, user_id: 'Optional[str]' = None, direction: 'Optional[str]' = None, type: 'Optional[str]' = None, result: 'Optional[str]' = None, tags: 'Optional[List[str]]' = None, unread: 'Optional[bool]' = None, unresponded: 'Optional[bool]' = None, search: 'Optional[str]' = None, date: 'Optional[Dict[str, str]]' = None, sort: 'Optional[str]' = None, extend: 'Optional[str]' = None, page: 'Optional[int]' = None, size: 'Optional[int]' = None) -> 'Any'",
    'search_deals': "(self, *, filters: 'Optional[Dict[str, Any]]' = None, search: 'Optional[str]' = None, sort: 'Optional[str]' = None, page: 'Optional[int]' = None, size: 'Optional[int]' = None) -> 'Any'",
    'search_people': "(self, *, filters: 'Optional[Dict[str, Any]]' = None, search: 'Optional[str]' = None, sort: 'Optional[str]' = None, page: 'Optional[int]' = None, size: 'Optional[int]' = None) -> 'Any'",
    'send_sms': "(self, to: 'str', message: 'str', *, from_number: 'Optional[str]' = None, sender_id: 'Optional[str]' = None) -> 'Any'",
    'update_call_summary': "(self, item_id: 'str', content: 'str', *, template_key: 'Optional[str]' = None) -> 'Any'",
    'update_company': "(self, company_id: 'str', **fields: 'Any') -> 'Any'",
    'update_conversation': "(self, contact_number: 'str', action: 'str', *, allo_number: 'Optional[str]' = None) -> 'Any'",
    'update_dialing_queue': "(self, *, name: 'Optional[str]' = None, voicemail_handling: 'Optional[str]' = None, do_not_disturb: 'Optional[str]' = None, user_id: 'Optional[str]' = None, email: 'Optional[str]' = None) -> 'Any'",
    'update_person': "(self, person_id: 'str', **fields: 'Any') -> 'Any'",
}

#: Méthode publique que la description ne porte pas, et pourquoi : `probe`, la sonde d'oto 1, qui appelle `get_me`
#: (la description la déclare par `probe: { function: get_me }`).
OUTSIDE_DESCRIPTION = {"probe"}


def _members():
    return {n: str(inspect.signature(getattr(mod.AlloClient, n)))
            for n in dir(mod.AlloClient)
            if not n.startswith("__") and callable(getattr(mod.AlloClient, n))}


def _functions():
    return {f["name"]: f for f in yaml.safe_load(DESCRIPTION.read_text(encoding="utf-8"))["functions"]}


def test_membres_et_signatures_figes():
    assert _members() == EXPECTED_MEMBERS


def test_noms_importables():
    assert pkg.__all__ == ["AlloClient"]
    for name in ("AlloClient", "BASE_URL", "SORTS", "CONVERSATION_ACTIONS", "MAX_SIZE",
                 "RECORDING_ADDRESS_FIELDS"):
        assert hasattr(mod, name), name


def test_une_fonction_decrite_est_une_methode_du_meme_nom():
    public = {n for n in EXPECTED_MEMBERS if not n.startswith("_")}
    assert set(_functions()) == public - OUTSIDE_DESCRIPTION


def test_les_arguments_decrits_sont_ceux_de_la_methode():
    """Chaque argument nommé de la méthode est décrit ; sans `**fields`, la description n'en a pas d'autre. Une
    méthode à `**fields` (création et mise à jour d'une personne ou d'une entreprise) prend le reste de la
    description par mot-clé."""
    for name, fn in _functions().items():
        parameters = inspect.signature(getattr(mod.AlloClient, name)).parameters
        named = {n for n, p in parameters.items()
                 if n != "self" and p.kind is not inspect.Parameter.VAR_KEYWORD}
        described = set(fn["input"]["properties"])
        if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
            assert named <= described, name
        else:
            assert described == named, name


def test_les_enumerations_decrites_sont_celles_du_client():
    fns = _functions()
    for name in ("search_people", "search_companies", "search_deals"):
        assert tuple(fns[name]["input"]["properties"]["sort"]["enum"]) == mod.SORTS, name
    assert tuple(fns["update_conversation"]["input"]["properties"]["action"]["enum"]) == mod.CONVERSATION_ACTIONS
    for name, fn in fns.items():
        size = fn["input"]["properties"].get("size")
        if size:
            assert size["maximum"] == mod.MAX_SIZE, name


def test_aucun_module_de_500_lignes_ou_plus():
    package = pathlib.Path(mod.__file__).parent
    for path in package.rglob("*.py"):
        assert len(path.read_text(encoding="utf-8").splitlines()) < 500, path
