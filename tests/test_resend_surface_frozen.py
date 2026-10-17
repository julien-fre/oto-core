"""La surface de `ResendClient` est un CONTRAT, pas un détail.

oto-backend épingle oto-core par tag et importe `oto.tools.resend.client` : renommer
une méthode, changer un défaut ou déplacer un symbole hors de `client.py` casse un
consommateur au bump du pin, loin d'ici. Ce test fige les membres AVEC leurs
signatures (l'envoi historique `send`/`send_template` compris), les noms
importables depuis `oto.tools.resend[.client]`, et la taille des modules du paquet.

⚠️ Ce test échoue si tu ajoutes une méthode : c'est voulu — mets à jour la
constante EN CONNAISSANCE DE CAUSE, jamais par réflexe pour faire passer le vert.
"""
import inspect
import pathlib

import oto.tools.resend as pkg
import oto.tools.resend.client as mod

EXPECTED_MEMBERS = {
    '_delete': "(self, path: 'str') -> 'Any'",
    '_email': "(value: 'Any') -> 'str'",
    '_fields': "(first_name: 'Optional[str]', last_name: 'Optional[str]', unsubscribed: 'Optional[bool]', properties: 'Optional[Dict[str, Any]]') -> 'Dict[str, Any]'",
    '_get': "(self, path: 'str', params: 'Optional[Dict[str, Any]]' = None) -> 'Any'",
    '_ids': "(name: 'str', values: 'Optional[Sequence[str]]') -> 'List[str]'",
    '_need': "(value: 'Any', name: 'str') -> 'Any'",
    '_pace': "(self) -> 'None'",
    '_page': "(limit: 'Optional[int]', after: 'Optional[str]', before: 'Optional[str]') -> 'Dict[str, Any]'",
    '_patch': "(self, path: 'str', body: 'Dict[str, Any]') -> 'Any'",
    '_post': "(self, path: 'str', body: 'Optional[Dict[str, Any]]') -> 'Any'",
    '_request': "(self, method: 'str', path: 'str', *, params: 'Optional[Dict[str, Any]]' = None, json: 'Any' = None) -> 'Any'",
    '_retry_wait': "(resp: 'Any', attempt: 'int') -> 'Optional[float]'",
    '_seg': "(value: 'Any', name: 'str') -> 'str'",
    '_segment_ids_of': "(self, contact: 'str') -> 'List[str]'",
    'add_contact_to_segment': "(self, contact: 'str', segment_id: 'str') -> 'Any'",
    'create_contact': "(self, email: 'str', *, first_name: 'Optional[str]' = None, last_name: 'Optional[str]' = None, unsubscribed: 'Optional[bool]' = None, properties: 'Optional[Dict[str, Any]]' = None, segment_ids: 'Optional[Sequence[str]]' = None) -> 'Any'",
    'create_segment': "(self, name: 'str') -> 'Any'",
    'delete_contact': "(self, contact: 'str') -> 'Any'",
    'find_contact': "(self, contact: 'str') -> 'Optional[Dict[str, Any]]'",
    'get_contact': "(self, contact: 'str') -> 'Any'",
    'get_segment': "(self, segment_id: 'str') -> 'Any'",
    'get_topic': "(self, topic_id: 'str') -> 'Any'",
    'list_contact_segments': "(self, contact: 'str', *, limit: 'Optional[int]' = None, after: 'Optional[str]' = None, before: 'Optional[str]' = None) -> 'Any'",
    'list_contact_topics': "(self, contact: 'str', *, limit: 'Optional[int]' = None, after: 'Optional[str]' = None, before: 'Optional[str]' = None) -> 'Any'",
    'list_contacts': "(self, segment_id: 'Optional[str]' = None, *, limit: 'Optional[int]' = None, after: 'Optional[str]' = None, before: 'Optional[str]' = None) -> 'Any'",
    'list_segments': "(self, *, limit: 'Optional[int]' = None, after: 'Optional[str]' = None, before: 'Optional[str]' = None) -> 'Any'",
    'list_topics': "(self, *, limit: 'Optional[int]' = None, after: 'Optional[str]' = None, before: 'Optional[str]' = None) -> 'Any'",
    'remove_contact_from_segment': "(self, contact: 'str', segment_id: 'str') -> 'Any'",
    'send': "(self, to: 'str | List[str]', subject: 'str', text: 'str' = None, html: 'str' = None, reply_to: 'str' = None, from_email: 'str' = None) -> 'Dict[str, Any]'",
    'send_template': "(self, to: 'str | List[str]', subject: 'str', template_html: 'str', variables: 'Dict[str, str]' = None, reply_to: 'str' = None) -> 'Dict[str, Any]'",
    'update_contact': "(self, contact: 'str', *, first_name: 'Optional[str]' = None, last_name: 'Optional[str]' = None, unsubscribed: 'Optional[bool]' = None, properties: 'Optional[Dict[str, Any]]' = None) -> 'Any'",
    'upsert_contact': "(self, email: 'str', *, first_name: 'Optional[str]' = None, last_name: 'Optional[str]' = None, unsubscribed: 'Optional[bool]' = None, properties: 'Optional[Dict[str, Any]]' = None, segment_ids: 'Optional[Sequence[str]]' = None, dry_run: 'bool' = False) -> 'Dict[str, Any]'",
}


def _members():
    return {n: str(inspect.signature(getattr(mod.ResendClient, n)))
            for n in dir(mod.ResendClient)
            if not n.startswith("__") and callable(getattr(mod.ResendClient, n))}


def test_membres_et_signatures_figes():
    assert _members() == EXPECTED_MEMBERS


def test_noms_importables():
    assert pkg.__all__ == ["ResendClient", "send_email"]
    assert pkg.ResendClient is mod.ResendClient
    for name in ("ResendClient", "send_email", "BASE_URL", "HTTP_TIMEOUT",
                 "MAX_ATTEMPTS", "MAX_PAGE_SIZE", "MAX_WALK_PAGES", "MIN_INTERVAL_S",
                 "RATE_LIMIT_MAX_WAIT", "RETRY_STATUSES"):
        assert name in mod.__all__, name
        assert hasattr(mod, name), name


def test_aucun_module_de_500_lignes_ou_plus():
    package = pathlib.Path(mod.__file__).parent
    for path in package.rglob("*.py"):
        assert len(path.read_text(encoding="utf-8").splitlines()) < 500, path
