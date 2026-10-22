"""La surface d'`OrigamiClient` est un CONTRAT, pas un détail.

Un consommateur épingle la lib par tag et importe `oto.tools.origami` : renommer une méthode, changer un défaut ou
déplacer un symbole casse un consommateur au bump du pin, loin d'ici. Ce test fige les membres AVEC leurs signatures,
les noms importables et la correspondance entre les fonctions de la description et les méthodes du client.

⚠️ Ce test échoue si tu ajoutes une méthode : c'est voulu — mets à jour la constante EN CONNAISSANCE DE CAUSE, jamais
par réflexe pour faire passer le vert.
"""
import inspect
import pathlib

import yaml

import oto.tools.origami as pkg
import oto.tools.origami.client as mod

ROOT = pathlib.Path(__file__).resolve().parent.parent
DESCRIPTION = ROOT / "connectors" / "origami" / "connector.yaml"

EXPECTED_MEMBERS = {
    '_request': "(self, method: 'str', path: 'str', *, params: 'Optional[Dict[str, Any]]' = None, json: 'Any' = None) -> 'Any'",
    'campaign_people': "(self, campaign_id: 'str', cursor: 'Optional[str]' = None, limit: 'Optional[int]' = None, status: 'Optional[str]' = None, search: 'Optional[str]' = None) -> 'Dict[str, Any]'",
    'campaign_stats': "(self, campaign_id: 'str') -> 'Dict[str, Any]'",
    'create_campaign': "(self, table_id: 'str', instructions: 'str', settings: 'Optional[Dict[str, Any]]' = None) -> 'Dict[str, Any]'",
    'create_workspace': "(self, name: 'str') -> 'Dict[str, Any]'",
    'delete_campaign': "(self, campaign_id: 'str', confirm: 'bool' = False, dry_run: 'bool' = False) -> 'Dict[str, Any]'",
    'get_campaign': "(self, campaign_id: 'str') -> 'Dict[str, Any]'",
    'get_run': "(self, agent_id: 'str', run_id: 'str', include: 'Optional[str]' = None) -> 'Dict[str, Any]'",
    'get_sequence': "(self, sequence_id: 'str') -> 'Dict[str, Any]'",
    'get_table': "(self, table_id: 'str', include: 'Optional[str]' = None) -> 'Dict[str, Any]'",
    'launch_campaign': "(self, campaign_id: 'str', dry_run: 'bool' = False) -> 'Dict[str, Any]'",
    'list_campaigns': "(self, table_id: 'str') -> 'Dict[str, Any]'",
    'list_columns': "(self, table_id: 'str') -> 'Dict[str, Any]'",
    'list_rows': "(self, table_id: 'str', cursor: 'Optional[str]' = None, cells: 'Optional[str]' = 'flat', limit: 'Optional[int]' = None, filters: 'Optional[List[Dict[str, Any]]]' = None, sort: 'Optional[Dict[str, Any]]' = None) -> 'Dict[str, Any]'",
    'list_sequences': "(self, workspace_id: 'str', cursor: 'Optional[str]' = None, limit: 'Optional[int]' = None, status: 'Optional[str]' = None, channel: 'Optional[str]' = None, recipient: 'Optional[str]' = None) -> 'Dict[str, Any]'",
    'list_tables': "(self, workspace_id: 'Optional[str]' = None, cursor: 'Optional[str]' = None, limit: 'Optional[int]' = None) -> 'Dict[str, Any]'",
    'list_workspaces': "(self, cursor: 'Optional[str]' = None, limit: 'Optional[int]' = None, search: 'Optional[str]' = None) -> 'Dict[str, Any]'",
    'pause_campaign': "(self, campaign_id: 'str', dry_run: 'bool' = False) -> 'Dict[str, Any]'",
    'resume_campaign': "(self, campaign_id: 'str', dry_run: 'bool' = False) -> 'Dict[str, Any]'",
    'upload_documents': "(self, workspace_id: 'str', files: 'List[Dict[str, Any]]') -> 'Dict[str, Any]'",
    'upsert_rows': "(self, table_id: 'str', rows: 'List[Dict[str, Any]]', match_columns: 'List[str]', enrich: 'bool' = False, reenrich_updated: 'Optional[bool]' = None, batch_id: 'Optional[str]' = None) -> 'Dict[str, Any]'",
}

#: Méthodes publiques que la description ne porte pas (motifs : `LEFT_OUT` de `tests/test_origami_description.py`).
OUTSIDE_DESCRIPTION = {"upload_documents"}


def _members():
    return {n: str(inspect.signature(getattr(mod.OrigamiClient, n)))
            for n in dir(mod.OrigamiClient)
            if not n.startswith("__") and callable(getattr(mod.OrigamiClient, n))}


def _functions():
    return {f["name"]: f for f in yaml.safe_load(DESCRIPTION.read_text(encoding="utf-8"))["functions"]}


def test_membres_et_signatures_figes():
    assert _members() == EXPECTED_MEMBERS


def test_constructeur_fige():
    assert str(inspect.signature(mod.OrigamiClient.__init__)) == (
        "(self, api_key: 'Optional[str]' = None, project_id: 'Optional[str]' = None)")


def test_noms_importables():
    assert pkg.__all__ == ["OrigamiClient"]
    assert pkg.OrigamiClient is mod.OrigamiClient
    assert mod.OrigamiClient.BASE_URL == "https://origami.chat/api/v2"
    assert mod._HTTP_TIMEOUT == (10, 120)


def test_une_fonction_decrite_est_une_methode_du_meme_nom():
    public = {n for n in EXPECTED_MEMBERS if not n.startswith("_")}
    assert set(_functions()) == public - OUTSIDE_DESCRIPTION
