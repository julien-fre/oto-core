"""La surface de `LinearClient` est un CONTRAT, pas un détail.

Un consommateur épingle la lib par tag et importe `oto.tools.linear` : renommer une méthode, changer un défaut ou
déplacer un symbole casse un consommateur au bump du pin, loin d'ici. Ce test fige les membres AVEC leurs signatures,
les noms importables et la correspondance entre les fonctions de la description et les méthodes du client : chaque
méthode publique est décrite ou laissée au client, nommée avec sa raison (`LEFT_TO_THE_CLIENT`).

⚠️ Ce test échoue si tu ajoutes une méthode : c'est voulu — mets à jour la constante EN CONNAISSANCE DE CAUSE, jamais
par réflexe pour faire passer le vert.
"""
import inspect
import pathlib

import yaml

import oto.tools.linear as pkg
import oto.tools.linear.client as mod

ROOT = pathlib.Path(__file__).resolve().parent.parent
DESCRIPTION = ROOT / "connectors" / "linear" / "connector.yaml"

EXPECTED_MEMBERS = {
    '_execute': "(self, query: 'str', variables: 'Optional[Dict[str, Any]]' = None) -> 'Any'",
    'archive_issue': "(self, issue_id: 'str') -> 'Any'",
    'create_comment': "(self, issue_id: 'str', body: 'str', *, parent_id: 'Optional[str]' = None, fields: 'Optional[str]' = None) -> 'Any'",
    'create_issue': "(self, title: 'str', team_id: 'str', *, description: 'Optional[str]' = None, assignee_id: 'Optional[str]' = None, state_id: 'Optional[str]' = None, priority: 'Optional[int]' = None, label_ids: 'Optional[List[str]]' = None, project_id: 'Optional[str]' = None, cycle_id: 'Optional[str]' = None, parent_id: 'Optional[str]' = None, due_date: 'Optional[str]' = None, estimate: 'Optional[int]' = None, fields: 'Optional[str]' = None) -> 'Any'",
    'create_label': "(self, name: 'str', *, team_id: 'Optional[str]' = None, color: 'Optional[str]' = None, description: 'Optional[str]' = None, fields: 'Optional[str]' = None) -> 'Any'",
    'create_project': "(self, name: 'str', team_ids: 'List[str]', *, description: 'Optional[str]' = None, status_id: 'Optional[str]' = None, lead_id: 'Optional[str]' = None, target_date: 'Optional[str]' = None, fields: 'Optional[str]' = None) -> 'Any'",
    'create_webhook': "(self, url: 'str', *, team_id: 'Optional[str]' = None, resource_types: 'Optional[List[str]]' = None, secret: 'Optional[str]' = None, enabled: 'Optional[bool]' = None, all_public_teams: 'bool' = False, fields: 'Optional[str]' = None) -> 'Any'",
    'delete_comment': "(self, comment_id: 'str') -> 'Any'",
    'delete_issue': "(self, issue_id: 'str') -> 'Any'",
    'delete_label': "(self, label_id: 'str') -> 'Any'",
    'delete_project': "(self, project_id: 'str') -> 'Any'",
    'delete_webhook': "(self, webhook_id: 'str') -> 'Any'",
    'get_comment': "(self, comment_id: 'str', *, fields: 'Optional[str]' = None) -> 'Any'",
    'get_cycle': "(self, cycle_id: 'str', *, fields: 'Optional[str]' = None) -> 'Any'",
    'get_issue': "(self, issue_id: 'str', *, fields: 'Optional[str]' = None) -> 'Any'",
    'get_label': "(self, label_id: 'str', *, fields: 'Optional[str]' = None) -> 'Any'",
    'get_project': "(self, project_id: 'str', *, fields: 'Optional[str]' = None) -> 'Any'",
    'get_team': "(self, team_id: 'str', *, fields: 'Optional[str]' = None) -> 'Any'",
    'get_user': "(self, user_id: 'str', *, fields: 'Optional[str]' = None) -> 'Any'",
    'get_viewer': "(self, *, fields: 'Optional[str]' = None) -> 'Any'",
    'list_comments': "(self, issue_id: 'str', *, first: 'Optional[int]' = None, after: 'Optional[str]' = None, fields: 'Optional[str]' = None) -> 'Any'",
    'list_cycles': "(self, *, team_id: 'Optional[str]' = None, first: 'int' = 50, after: 'Optional[str]' = None, fields: 'Optional[str]' = None) -> 'Any'",
    'list_issues': "(self, *, team_id: 'Optional[str]' = None, project_id: 'Optional[str]' = None, cycle_id: 'Optional[str]' = None, assignee_id: 'Optional[str]' = None, state_id: 'Optional[str]' = None, updated_after: 'Optional[str]' = None, updated_before: 'Optional[str]' = None, created_after: 'Optional[str]' = None, created_before: 'Optional[str]' = None, order_by: 'Optional[str]' = None, first: 'int' = 50, after: 'Optional[str]' = None, fields: 'Optional[str]' = None) -> 'Any'",
    'list_labels': "(self, *, team_id: 'Optional[str]' = None, first: 'int' = 50, after: 'Optional[str]' = None, fields: 'Optional[str]' = None) -> 'Any'",
    'list_projects': "(self, *, team_id: 'Optional[str]' = None, first: 'int' = 50, after: 'Optional[str]' = None, fields: 'Optional[str]' = None) -> 'Any'",
    'list_teams': "(self, *, first: 'Optional[int]' = None, after: 'Optional[str]' = None, fields: 'Optional[str]' = None) -> 'Any'",
    'list_users': "(self, *, first: 'Optional[int]' = None, after: 'Optional[str]' = None, fields: 'Optional[str]' = None) -> 'Any'",
    'list_webhooks': "(self, *, team_id: 'Optional[str]' = None, first: 'int' = 50, after: 'Optional[str]' = None, fields: 'Optional[str]' = None) -> 'Any'",
    'list_workflow_states': "(self, team_id: 'str', *, first: 'Optional[int]' = None, after: 'Optional[str]' = None, fields: 'Optional[str]' = None) -> 'Any'",
    'search_issues': "(self, query_text: 'str', *, team_id: 'Optional[str]' = None, first: 'int' = 50, after: 'Optional[str]' = None, fields: 'Optional[str]' = None) -> 'Any'",
    'update_comment': "(self, comment_id: 'str', body: 'str', *, fields: 'Optional[str]' = None) -> 'Any'",
    'update_issue': "(self, issue_id: 'str', *, title: 'Optional[str]' = None, description: 'Optional[str]' = None, assignee_id: 'Optional[str]' = None, state_id: 'Optional[str]' = None, priority: 'Optional[int]' = None, label_ids: 'Optional[List[str]]' = None, project_id: 'Optional[str]' = None, cycle_id: 'Optional[str]' = None, due_date: 'Optional[str]' = None, estimate: 'Optional[int]' = None, fields: 'Optional[str]' = None) -> 'Any'",
    'update_project': "(self, project_id: 'str', *, name: 'Optional[str]' = None, description: 'Optional[str]' = None, status_id: 'Optional[str]' = None, lead_id: 'Optional[str]' = None, target_date: 'Optional[str]' = None, fields: 'Optional[str]' = None) -> 'Any'",
    'update_webhook': "(self, webhook_id: 'str', *, url: 'Optional[str]' = None, resource_types: 'Optional[List[str]]' = None, enabled: 'Optional[bool]' = None, fields: 'Optional[str]' = None) -> 'Any'",
}

# Le texte de la requête dépend des arguments donnés : Linear refuse une variable déclarée inutilisée, le client ne
# déclare une variable et sa clause de filtre que pour un filtre donné ; `list_webhooks` change d'opération avec
# `team_id` (`team(id){webhooks}`, réponse remise en forme par le client).
LEFT_TO_THE_CLIENT = {"list_issues", "search_issues", "list_projects", "list_cycles", "list_labels", "list_webhooks"}


def _members():
    return {n: str(inspect.signature(getattr(mod.LinearClient, n)))
            for n in dir(mod.LinearClient)
            if not n.startswith("__") and callable(getattr(mod.LinearClient, n))}


def _functions():
    return {f["name"]: f for f in yaml.safe_load(DESCRIPTION.read_text(encoding="utf-8"))["functions"]}


def test_membres_et_signatures_figes():
    assert _members() == EXPECTED_MEMBERS


def test_constructeur_fige():
    assert str(inspect.signature(mod.LinearClient.__init__)) == "(self, api_key: 'Optional[str]' = None)"


def test_noms_importables():
    assert pkg.__all__ == ["LinearClient", "LinearError", "LinearGraphQLError", "LinearRateLimited"]
    assert pkg.LinearClient is mod.LinearClient
    assert mod.LinearClient.ENDPOINT == "https://api.linear.app/graphql"
    assert mod.LinearClient.__mro__ == (mod.LinearClient, object)
    assert issubclass(mod.LinearRateLimited, mod.LinearGraphQLError)
    assert issubclass(mod.LinearGraphQLError, mod.LinearError)


def test_chaque_methode_publique_est_decrite_ou_laissee_au_client_nommee():
    public = {n for n in EXPECTED_MEMBERS if not n.startswith("_")}
    assert len(_functions()) == 27
    assert set(_functions()) | LEFT_TO_THE_CLIENT == public
    assert not set(_functions()) & LEFT_TO_THE_CLIENT
    header = DESCRIPTION.read_text(encoding="utf-8")
    for name in LEFT_TO_THE_CLIENT:
        assert name in header, name
