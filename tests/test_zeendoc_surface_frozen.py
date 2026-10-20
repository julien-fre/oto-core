"""La surface de `ZeendocClient` est un CONTRAT, pas un détail.

oto-backend épingle oto-core par tag et importe `oto.tools.zeendoc` : renommer une
méthode, changer un défaut ou déplacer un symbole hors de `client.py` casse un
consommateur au bump du pin, loin d'ici. Ce test fige les membres AVEC leurs
signatures, les noms importables depuis `oto.tools.zeendoc[.client]` et la taille
des modules du paquet. Zeendoc n'a pas de description (`connectors/clients.yaml`) :
rien à confronter à un `connector.yaml`.

⚠️ Ce test échoue si tu ajoutes une méthode : c'est voulu — mets à jour la
constante EN CONNAISSANCE DE CAUSE, jamais par réflexe pour faire passer le vert.
"""
import inspect
import pathlib

import oto.tools.zeendoc as pkg
import oto.tools.zeendoc.client as mod

EXPECTED_MEMBERS = {
    '_all_columns': "(self, binder: 'str') -> 'List[str]'",
    '_attempt': "(self, method: 'str', path: 'str', cookie: 'str', *, params: 'Optional[Dict[str, Any]]', json: 'Any', stream: 'bool') -> 'requests.Response'",
    '_choice': "(name: 'str', value: 'Any', allowed: 'Sequence[str]') -> 'str'",
    '_columns_of': "(self, binder: 'str', columns: 'Optional[List[str]]') -> 'str'",
    '_documents': "(found: 'Dict[str, Any]') -> 'Dict[str, Any]'",
    '_field': "(name: 'str', value: 'Any') -> 'str'",
    '_json': "(self, method: 'str', path: 'str', *, params: 'Optional[Dict[str, Any]]' = None, json: 'Any' = None) -> 'Any'",
    '_keyed_by_field': "(values: 'Any') -> 'Dict[str, Any]'",
    '_no_right': "(path: 'str', resp: 'requests.Response') -> 'bool'",
    '_query': "(criteria: 'Optional[List[Dict[str, Any]]]', match: 'str') -> 'Dict[str, Any]'",
    '_res_id': "(value: 'Any') -> 'int'",
    '_send': "(self, method: 'str', path: 'str', *, params: 'Optional[Dict[str, Any]]' = None, json: 'Any' = None, stream: 'bool' = False) -> 'requests.Response'",
    '_session_over': "(path: 'str', resp: 'requests.Response') -> 'bool'",
    '_slug': "(name: 'str', value: 'Any') -> 'str'",
    '_value': "(name: 'str', value: 'Any') -> 'str'",
    'count_documents': "(self, binder: 'str', criteria: 'Optional[List[Dict[str, Any]]]' = None, *, match: 'str' = 'all') -> 'Any'",
    'download_document': "(self, binder: 'str', res_id: 'int', version: 'str' = 'pdf') -> 'Dict[str, Any]'",
    'get_context': "(self) -> 'Any'",
    'get_document': "(self, binder: 'str', res_id: 'int', columns: 'Optional[List[str]]' = None) -> 'Any'",
    'get_document_text': "(self, binder: 'str', res_id: 'int') -> 'str'",
    'list_field_choices': "(self, binder: 'str', field: 'str') -> 'Any'",
    'probe': "(self) -> 'Any'",
    'search_documents': "(self, binder: 'str', criteria: 'Optional[List[Dict[str, Any]]]' = None, *, match: 'str' = 'all', order_by: 'Optional[str]' = None, order: 'str' = 'desc', offset: 'int' = 0, limit: 'int' = 50, columns: 'Optional[List[str]]' = None) -> 'Any'",
    'suggest_field_values': "(self, binder: 'str', field: 'str', term: 'str') -> 'Any'",
}


def _members():
    return {n: str(inspect.signature(getattr(mod.ZeendocClient, n)))
            for n in dir(mod.ZeendocClient)
            if not n.startswith("__") and callable(getattr(mod.ZeendocClient, n))}


def test_membres_et_signatures_figes():
    assert _members() == EXPECTED_MEMBERS


def test_noms_importables():
    assert pkg.__all__ == ["ZeendocClient", "ZeendocAuthError"]
    for name in ("ZeendocClient", "BASE_URL", "OPERATORS", "FILE_VERSIONS", "PAGE_MAX",
                 "PROPERTIES", "RETRY_STATUSES", "MAX_ATTEMPTS", "HTTP_TIMEOUT"):
        assert hasattr(mod, name), name


def test_aucun_module_de_500_lignes_ou_plus():
    package = pathlib.Path(mod.__file__).parent
    for path in package.rglob("*.py"):
        assert len(path.read_text(encoding="utf-8").splitlines()) < 500, path
