"""La surface de `SlackClient` est un CONTRAT, pas un détail.

Un consommateur épingle la lib par tag et importe `oto.tools.slack` : renommer une méthode, changer un défaut ou déplacer
un symbole casse un consommateur au bump du pin, loin d'ici. Ce test fige les membres AVEC leurs signatures, les noms
importables et la correspondance entre les fonctions de la description et les méthodes du client.

⚠️ Ce test échoue si tu ajoutes une méthode : c'est voulu — mets à jour la constante EN CONNAISSANCE DE CAUSE, jamais
par réflexe pour faire passer le vert.
"""
import inspect
import pathlib

import yaml

import oto.tools.slack as pkg
import oto.tools.slack.client as mod
import oto.tools.slack.text as text

ROOT = pathlib.Path(__file__).resolve().parent.parent
DESCRIPTION = ROOT / "connectors" / "slack" / "connector.yaml"

EXPECTED_MEMBERS = {
    '_file_source': '(self, file_id: str) -> tuple',
    '_prefer': '(self, want_user: bool) -> bool',
    '_request': '(self, method: str, endpoint: str, as_user: Optional[bool] = None, **kwargs) -> Dict[str, Any]',
    '_resolve_token': '(self, as_user: Optional[bool]) -> str',
    'add_reaction': '(self, channel: str, ts: str, name: str) -> Dict[str, Any]',
    'channel_info': '(self, channel: str, as_user: Optional[bool] = None) -> Dict[str, Any]',
    'create_usergroup': "(self, name: 'str', handle: 'Optional[str]' = None, description: 'Optional[str]' = None, channels: 'Optional[Iterable[str]]' = None, as_user: 'Optional[bool]' = None) -> 'Dict[str, Any]'",
    'delete_message': '(self, channel: str, ts: str, as_user: Optional[bool] = None) -> Dict[str, Any]',
    'disable_usergroup': "(self, usergroup: 'str', as_user: 'Optional[bool]' = None) -> 'Dict[str, Any]'",
    'download_file': '(self, file_id: str, dest: str) -> str',
    'enable_usergroup': "(self, usergroup: 'str', as_user: 'Optional[bool]' = None) -> 'Dict[str, Any]'",
    'fetch_file': '(self, file_id: str) -> Dict[str, Any]',
    'file_info': '(self, file_id: str) -> Dict[str, Any]',
    'find_user_by_email': '(self, email: str, as_user: Optional[bool] = None) -> Dict[str, Any]',
    'get_user_info': '(self, user_id: str, as_user: Optional[bool] = None) -> Dict[str, Any]',
    'history': '(self, channel: str, limit: int = 50, cursor: Optional[str] = None, oldest: Optional[str] = None, latest: Optional[str] = None, inclusive: bool = False, as_user: Optional[bool] = None) -> Dict[str, Any]',
    'join_channel': '(self, channel: str, as_user: Optional[bool] = None) -> Dict[str, Any]',
    'list_channels': "(self, types: str = 'public_channel', as_user: Optional[bool] = None) -> List[Dict[str, Any]]",
    'list_usergroups': "(self, include_users: 'bool' = False, include_disabled: 'bool' = False, include_count: 'bool' = False, as_user: 'Optional[bool]' = None) -> 'List[Dict[str, Any]]'",
    'open_dm': '(self, user: str, as_user: Optional[bool] = None) -> Dict[str, Any]',
    'post_ephemeral': '(self, channel: str, user: str, text: str = None, blocks: List[Dict] = None) -> Dict[str, Any]',
    'post_message': '(self, channel: str, text: str = None, blocks: List[Dict] = None, thread_ts: str = None, as_user: Optional[bool] = None) -> Dict[str, Any]',
    'replies': '(self, channel: str, thread_ts: str, limit: int = 50, cursor: Optional[str] = None, oldest: Optional[str] = None, latest: Optional[str] = None, inclusive: bool = False, as_user: Optional[bool] = None) -> Dict[str, Any]',
    'search_messages': '(self, query: str, count: int = 20) -> Dict[str, Any]',
    'set_usergroup_users': "(self, usergroup: 'str', users: 'Iterable[str]', as_user: 'Optional[bool]' = None) -> 'Dict[str, Any]'",
    'update_message': '(self, channel: str, ts: str, text: str = None, blocks: List[Dict] = None) -> Dict[str, Any]',
    'update_usergroup': "(self, usergroup: 'str', name: 'Optional[str]' = None, handle: 'Optional[str]' = None, description: 'Optional[str]' = None, channels: 'Optional[Iterable[str]]' = None, as_user: 'Optional[bool]' = None) -> 'Dict[str, Any]'",
    'usergroup_users': "(self, usergroup: 'str', include_disabled: 'bool' = False, as_user: 'Optional[bool]' = None) -> 'List[str]'",
}

#: Méthodes publiques que la description ne porte pas (motifs : `LEFT_OUT` de `tests/test_slack_description.py`).
OUTSIDE_DESCRIPTION = {
    "search_messages", "fetch_file", "download_file",
    "create_usergroup", "update_usergroup", "set_usergroup_users", "disable_usergroup", "enable_usergroup",
}


def _members():
    return {n: str(inspect.signature(getattr(mod.SlackClient, n)))
            for n in dir(mod.SlackClient)
            if not n.startswith("__") and callable(getattr(mod.SlackClient, n))}


def _functions():
    return {f["name"]: f for f in yaml.safe_load(DESCRIPTION.read_text(encoding="utf-8"))["functions"]}


def test_membres_et_signatures_figes():
    assert _members() == EXPECTED_MEMBERS


def test_noms_importables():
    assert pkg.__all__ == ["SlackClient", "verify_slack_signature"]
    assert mod.SlackClient.BASE_URL == "https://slack.com/api"
    for name in ("SlackError", "verify_slack_signature", "_SLACK_ERROR_STATUS", "_HTTP_TIMEOUT"):
        assert hasattr(mod, name), name
    assert text.MAX_TEXT_LEN == 4000
    for name in ("escape_false_emoji_shortcodes", "chunk_text"):
        assert callable(getattr(text, name)), name


def test_une_fonction_decrite_est_une_methode_du_meme_nom():
    public = {n for n in EXPECTED_MEMBERS if not n.startswith("_")}
    assert set(_functions()) == public - OUTSIDE_DESCRIPTION
