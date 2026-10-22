"""La surface de `FolkClient` est un CONTRAT, pas un détail.

Un consommateur épingle la lib par tag et importe `oto.tools.folk` : renommer une méthode, changer un défaut ou déplacer
un symbole casse un consommateur au bump du pin, loin d'ici. Ce test fige les membres AVEC leurs signatures, les noms
importables et la correspondance entre les fonctions de la description et les méthodes du client.

⚠️ Ce test échoue si tu ajoutes une méthode : c'est voulu — mets à jour la constante EN CONNAISSANCE DE CAUSE, jamais
par réflexe pour faire passer le vert.
"""
import inspect
import pathlib

import yaml

import oto.tools.folk as pkg
import oto.tools.folk.client as mod
import oto.tools.folk.pacing as pacing

ROOT = pathlib.Path(__file__).resolve().parent.parent
DESCRIPTION = ROOT / "connectors" / "folk" / "connector.yaml"

EXPECTED_MEMBERS = {
    '_batch': '(self, endpoint: str, records: List[Dict]) -> List[Dict]',
    '_paginate': '(self, endpoint: str, params: Dict = None, limit: Optional[int] = 100, max_items: Optional[int] = None) -> List[Dict]',
    '_request': '(self, method: str, endpoint: str, extra_headers: Optional[Dict[str, str]] = None, **kwargs) -> Any',
    'add_group_member': '(self, group_id: str, user_id: str, role: str) -> Dict',
    'company_body': '(name: str = None, emails: List[str] = None, industry: str = None, **kwargs) -> Dict',
    'create_companies_batch': '(self, records: List[Dict]) -> List[Dict]',
    'create_company': '(self, name: str, emails: List[str] = None, industry: str = None, **kwargs) -> Dict',
    'create_deal': "(self, group_id: str, name: str, object_type: str = 'deals', people_ids: List[str] = None, company_ids: List[str] = None, custom_fields: Dict = None) -> Dict",
    'create_deals_batch': "(self, group_id: str, records: List[Dict], object_type: str = 'deals') -> List[Dict]",
    'create_group': '(self, name: str, visibility: str) -> Dict',
    'create_group_custom_field': '(self, group_id: str, entity_type: str, **field) -> Dict',
    'create_interaction': '(self, entity_id: str, type: str, title: str, content: str = None, date_time: str = None) -> Dict',
    'create_note': "(self, entity_id: str, content: str, visibility: str = 'public') -> Dict",
    'create_people_batch': '(self, records: List[Dict]) -> List[Dict]',
    'create_person': '(self, first_name: str, last_name: str = None, emails: List[str] = None, phones: List[str] = None, job_title: str = None, company_name: str = None, company_id: str = None, group_ids: List[str] = None, urls: List[str] = None, description: str = None, **kwargs) -> Dict',
    'create_reminder': "(self, entity_id: str, name: str, recurrence_rule: str, visibility: str = 'public') -> Dict",
    'create_task': '(self, entity_id: str, title: str, due_at: str, due_time: str = None, description: str = None, recurrence_frequency: str = None, assigned_users: List[Any] = None, is_public: bool = None) -> Dict',
    'create_webhook': '(self, name: str, target_url: str, subscribed_events: List[Dict]) -> Dict',
    'deal_body': '(name: str = None, people_ids: List[str] = None, company_ids: List[str] = None, custom_fields: Dict = None) -> Dict',
    'delete_company': '(self, company_id: str) -> Dict',
    'delete_deal': "(self, group_id: str, deal_id: str, object_type: str = 'deals') -> Dict",
    'delete_interaction': '(self, interaction_id: str, entity_id: str) -> Dict',
    'delete_note': '(self, note_id: str) -> Dict',
    'delete_person': '(self, person_id: str) -> Dict',
    'delete_reminder': '(self, reminder_id: str) -> Dict',
    'delete_task': '(self, task_id: str) -> Dict',
    'delete_webhook': '(self, webhook_id: str) -> Dict',
    'get_company': '(self, company_id: str) -> Dict',
    'get_current_user': '(self) -> Dict',
    'get_deal': "(self, group_id: str, deal_id: str, object_type: str = 'deals') -> Dict",
    'get_group_custom_field': '(self, group_id: str, entity_type: str, custom_field_name: str) -> Dict',
    'get_group_custom_fields': "(self, group_id: str, entity_type: str = 'person') -> List[Dict]",
    'get_interaction': '(self, interaction_id: str, entity_id: str) -> Dict',
    'get_person': '(self, person_id: str) -> Dict',
    'get_reminder': '(self, reminder_id: str) -> Dict',
    'get_task': '(self, task_id: str) -> Dict',
    'get_user': '(self, user_id: str) -> Dict',
    'get_webhook': '(self, webhook_id: str) -> Dict',
    'list_companies': '(self, **filters) -> List[Dict]',
    'list_deals': "(self, group_id: str, object_type: str = 'deals', **filters) -> List[Dict]",
    'list_group_members': '(self, group_id: str) -> List[Dict]',
    'list_groups': '(self) -> List[Dict]',
    'list_notes': '(self, entity_id: str = None) -> List[Dict]',
    'list_past_interactions': '(self, entity_id: str, max_items: Optional[int] = None) -> List[Dict]',
    'list_people': '(self, **filters) -> List[Dict]',
    'list_reminders': '(self, entity_id: str = None) -> List[Dict]',
    'list_tasks': '(self, filters: Dict[str, Any] = None, only_assigned_to_me: Optional[bool] = None, combinator: Optional[str] = None) -> List[Dict]',
    'list_upcoming_interactions': '(self, entity_id: str, max_items: Optional[int] = None) -> List[Dict]',
    'list_users': '(self) -> List[Dict]',
    'list_webhooks': '(self) -> List[Dict]',
    'mark_task_done': '(self, task_id: str, completed_at: str = None) -> Dict',
    'mark_task_todo': '(self, task_id: str) -> Dict',
    'person_body': '(first_name: str = None, last_name: str = None, emails: List[str] = None, phones: List[str] = None, job_title: str = None, company_name: str = None, company_id: str = None, group_ids: List[str] = None, urls: List[str] = None, description: str = None, **kwargs) -> Dict',
    'remove_group_member': '(self, group_id: str, user_id: str) -> Dict',
    'update_companies_batch': '(self, records: List[Dict]) -> List[Dict]',
    'update_company': '(self, company_id: str, **fields) -> Dict',
    'update_deal': "(self, group_id: str, deal_id: str, object_type: str = 'deals', **fields) -> Dict",
    'update_deals_batch': "(self, group_id: str, records: List[Dict], object_type: str = 'deals') -> List[Dict]",
    'update_group': '(self, group_id: str, **fields) -> Dict',
    'update_group_custom_field': '(self, group_id: str, entity_type: str, custom_field_name: str, **fields) -> Dict',
    'update_group_member': '(self, group_id: str, user_id: str, role: str) -> Dict',
    'update_interaction': '(self, interaction_id: str, entity_id: str, **fields) -> Dict',
    'update_note': '(self, note_id: str, **fields) -> Dict',
    'update_people_batch': '(self, records: List[Dict]) -> List[Dict]',
    'update_person': '(self, person_id: str, **fields) -> Dict',
    'update_reminder': '(self, reminder_id: str, **fields) -> Dict',
    'update_task': '(self, task_id: str, **fields) -> Dict',
    'update_webhook': '(self, webhook_id: str, **fields) -> Dict',
}

#: Méthodes publiques que la description ne porte pas (motifs : `LEFT_OUT` de `tests/test_folk_description.py`).
OUTSIDE_DESCRIPTION = {"person_body", "company_body", "deal_body"}


def _members():
    return {n: str(inspect.signature(getattr(mod.FolkClient, n)))
            for n in dir(mod.FolkClient)
            if not n.startswith("__") and callable(getattr(mod.FolkClient, n))}


def _functions():
    return {f["name"]: f for f in yaml.safe_load(DESCRIPTION.read_text(encoding="utf-8"))["functions"]}


def test_membres_et_signatures_figes():
    assert _members() == EXPECTED_MEMBERS


def test_noms_importables():
    assert pkg.__all__ == ["FolkClient"]
    assert mod.FolkClient.BASE_URL == "https://api.folk.app/v1"
    assert mod.FolkClient.BATCH_MAX_RECORDS == 100
    for name in ("filter_params", "task_filter_params", "RELATION_FIELDS", "WEBHOOK_EVENT_TYPES"):
        assert hasattr(mod, name), name
    for name in ("DEFAULT_MIN_INTERVAL_S", "SHARED_PACER", "FolkPacer", "key_fingerprint"):
        assert hasattr(pacing, name), name


def test_une_fonction_decrite_est_une_methode_du_meme_nom():
    public = {n for n in EXPECTED_MEMBERS if not n.startswith("_")}
    assert set(_functions()) == public - OUTSIDE_DESCRIPTION

