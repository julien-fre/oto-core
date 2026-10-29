"""La surface de `QontoClient` est un CONTRAT, pas un détail.

oto-backend épingle oto-core par tag et importe `oto.tools.qonto` : renommer une
méthode, changer un défaut ou déplacer un symbole hors de `client.py` casse un
consommateur au bump du pin, loin d'ici. Ce test fige les membres AVEC leurs
signatures, les noms importables depuis `oto.tools.qonto[.client]`, la
correspondance entre les fonctions de la description et les méthodes du client,
et la taille des modules du paquet.

⚠️ Ce test échoue si tu ajoutes une méthode : c'est voulu — mets à jour la
constante EN CONNAISSANCE DE CAUSE, jamais par réflexe pour faire passer le vert.
"""
import inspect
import pathlib

import yaml

import oto.tools.qonto as pkg
import oto.tools.qonto.client as mod

ROOT = pathlib.Path(__file__).resolve().parent.parent
DESCRIPTION = ROOT / "connectors" / "qonto" / "connector.yaml"

EXPECTED_MEMBERS = {
    '_choice': "(name: 'str', value: 'Optional[str]', allowed: 'tuple') -> 'Optional[str]'",
    '_choices': "(name: 'str', values: 'Optional[List[str]]', allowed: 'Optional[tuple]' = None) -> 'Optional[List[str]]'",
    '_flag': "(value: 'Optional[bool]') -> 'Optional[str]'",
    '_get': "(self, path: 'str', params: 'Optional[Dict[str, Any]]' = None) -> 'Any'",
    '_page': "(self, page: 'Optional[int]', per_page: 'Optional[int]', most: 'int' = 100) -> 'Dict[str, Any]'",
    '_path_id': "(name: 'str', value: 'Any') -> 'str'",
    '_period': "(name: 'str', value: 'Optional[str]') -> 'Optional[str]'",
    '_positive': "(name: 'str', value: 'Optional[int]') -> 'Optional[int]'",
    '_sort': "(name: 'str', value: 'Optional[str]', pattern: 're.Pattern' = re.compile('^[a-z_]+:(?:asc|desc)$')) -> 'Optional[str]'",
    '_when': "(name: 'str', value: 'Optional[str]') -> 'Optional[str]'",
    'get_attachment': "(self, attachment_id: 'str') -> 'Any'",
    'get_client': "(self, client_id: 'str') -> 'Any'",
    'get_client_invoice': "(self, client_invoice_id: 'str') -> 'Any'",
    'get_organization': "(self, include_external_accounts: 'Optional[bool]' = None) -> 'Any'",
    'get_statement': "(self, statement_id: 'str') -> 'Any'",
    'get_supplier_invoice': "(self, supplier_invoice_id: 'str') -> 'Any'",
    'get_transaction': "(self, transaction_id: 'str', includes: 'Optional[List[str]]' = None) -> 'Any'",
    'list_client_invoices': "(self, status: 'Optional[str]' = None, *, created_at_from: 'Optional[str]' = None, created_at_to: 'Optional[str]' = None, updated_at_from: 'Optional[str]' = None, updated_at_to: 'Optional[str]' = None, due_date_from: 'Optional[str]' = None, due_date_to: 'Optional[str]' = None, exclude_imported: 'Optional[bool]' = None, sort_by: 'Optional[str]' = None, page: 'Optional[int]' = None, per_page: 'Optional[int]' = None) -> 'Any'",
    'list_clients': "(self, *, name: 'Optional[str]' = None, email: 'Optional[str]' = None, vat_number: 'Optional[str]' = None, tax_identification_number: 'Optional[str]' = None, updated_at_from: 'Optional[str]' = None, updated_at_to: 'Optional[str]' = None, sort_by: 'Optional[str]' = None, page: 'Optional[int]' = None, per_page: 'Optional[int]' = None) -> 'Any'",
    'list_credit_notes': "(self, *, created_at_from: 'Optional[str]' = None, created_at_to: 'Optional[str]' = None, sort_by: 'Optional[str]' = None, page: 'Optional[int]' = None, per_page: 'Optional[int]' = None) -> 'Any'",
    'list_labels': "(self, page: 'Optional[int]' = None, per_page: 'Optional[int]' = None) -> 'Any'",
    'list_memberships': "(self, page: 'Optional[int]' = None, per_page: 'Optional[int]' = None) -> 'Any'",
    'list_quotes': "(self, status: 'Optional[str]' = None, *, created_at_from: 'Optional[str]' = None, created_at_to: 'Optional[str]' = None, sort_by: 'Optional[str]' = None, page: 'Optional[int]' = None, per_page: 'Optional[int]' = None) -> 'Any'",
    'list_requests': "(self, status: 'Optional[List[str]]' = None, *, request_type: 'Optional[List[str]]' = None, created_at_from: 'Optional[str]' = None, processed_at_from: 'Optional[str]' = None, sort_by: 'Optional[str]' = None, page: 'Optional[int]' = None, per_page: 'Optional[int]' = None) -> 'Any'",
    'list_sepa_beneficiaries': "(self, status: 'Optional[List[str]]' = None, *, iban: 'Optional[List[str]]' = None, trusted: 'Optional[bool]' = None, sort_by: 'Optional[str]' = None, page: 'Optional[int]' = None, per_page: 'Optional[int]' = None) -> 'Any'",
    'list_sepa_transfers': "(self, status: 'Optional[List[str]]' = None, *, beneficiary_ids: 'Optional[List[str]]' = None, updated_at_from: 'Optional[str]' = None, updated_at_to: 'Optional[str]' = None, scheduled_date_from: 'Optional[str]' = None, scheduled_date_to: 'Optional[str]' = None, sort_by: 'Optional[str]' = None, page: 'Optional[int]' = None, per_page: 'Optional[int]' = None) -> 'Any'",
    'list_statements': "(self, bank_account_ids: 'Optional[List[str]]' = None, ibans: 'Optional[List[str]]' = None, *, period_from: 'Optional[str]' = None, period_to: 'Optional[str]' = None, sort_by: 'Optional[str]' = None, page: 'Optional[int]' = None, per_page: 'Optional[int]' = None) -> 'Any'",
    'list_supplier_invoices': "(self, status: 'Optional[str]' = None, *, created_at_from: 'Optional[str]' = None, created_at_to: 'Optional[str]' = None, updated_at_from: 'Optional[str]' = None, updated_at_to: 'Optional[str]' = None, query: 'Optional[str]' = None, page: 'Optional[int]' = None, per_page: 'Optional[int]' = None) -> 'Any'",
    'list_transaction_attachments': "(self, transaction_id: 'str', page: 'Optional[int]' = None, per_page: 'Optional[int]' = None) -> 'Any'",
    'list_transactions': "(self, bank_account_id: 'Optional[str]' = None, iban: 'Optional[str]' = None, *, status: 'Optional[List[str]]' = None, side: 'Optional[str]' = None, operation_type: 'Optional[List[str]]' = None, settled_at_from: 'Optional[str]' = None, settled_at_to: 'Optional[str]' = None, emitted_at_from: 'Optional[str]' = None, emitted_at_to: 'Optional[str]' = None, updated_at_from: 'Optional[str]' = None, updated_at_to: 'Optional[str]' = None, with_attachments: 'Optional[bool]' = None, includes: 'Optional[List[str]]' = None, sort_by: 'Optional[str]' = None, page: 'Optional[int]' = None, per_page: 'Optional[int]' = None) -> 'Any'",
    'probe': "(self) -> 'Any'",
}

#: Méthode publique que la description ne porte pas, et pourquoi.
#: `probe` est une commodité de vérification de clé, pas une fonction exposée.
OUTSIDE_DESCRIPTION = {"probe"}


def _members():
    return {n: str(inspect.signature(getattr(mod.QontoClient, n)))
            for n in dir(mod.QontoClient)
            if not n.startswith("__") and callable(getattr(mod.QontoClient, n))}


def test_membres_et_signatures_figes():
    assert _members() == EXPECTED_MEMBERS


def test_noms_importables():
    assert pkg.__all__ == ["QontoClient"]
    for name in ("QontoClient", "BASE_URL", "RETRY_STATUSES", "MAX_ATTEMPTS", "HTTP_TIMEOUT",
                 "TRANSACTION_STATUSES", "TRANSACTION_INCLUDES", "SUPPLIER_INVOICE_STATUSES",
                 "CLIENT_INVOICE_STATUSES"):
        assert hasattr(mod, name), name


def test_une_fonction_decrite_est_une_methode_du_meme_nom():
    described = {f["name"] for f in yaml.safe_load(
        DESCRIPTION.read_text(encoding="utf-8"))["functions"]}
    public = {n for n in EXPECTED_MEMBERS if not n.startswith("_")}
    assert described == public - OUTSIDE_DESCRIPTION


def test_les_arguments_decrits_sont_ceux_de_la_methode():
    for fn in yaml.safe_load(DESCRIPTION.read_text(encoding="utf-8"))["functions"]:
        params = set(inspect.signature(getattr(mod.QontoClient, fn["name"])).parameters)
        assert set(fn["input"].get("properties", {})) == params - {"self"}, fn["name"]


def test_aucun_module_de_500_lignes_ou_plus():
    package = pathlib.Path(mod.__file__).parent
    for path in package.rglob("*.py"):
        assert len(path.read_text(encoding="utf-8").splitlines()) < 500, path
