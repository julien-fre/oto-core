"""Contrat du client Qonto (Business API v2, clé `login:secret-key`, banque en lecture seule).

Mocke `requests.Session.request` : en-tête d'auth envoyé tel quel, chemins sous
`/v2`, filtres en tableau à la Rails (`status[]=…` répété), booléens en `true`/`false`,
clés `filter[…]`, bornes (dates ISO 8601, mois `MM-YYYY`, page et per_page positifs),
énumérations, ids de chemin, re-tentatives sur 429 mais jamais sur 401, redirection
refusée — et la clé jamais lue de l'environnement. Chaque exemple de la description est
rejoué contre le client.
"""
from __future__ import annotations

import pathlib

import pytest
import yaml

from oto.tools.common.credentials import MissingCredential
from oto.tools.common.errors import UpstreamHTTPError
from oto.tools.http.client import RedirectRefused
from oto.tools.qonto import client as qc

DESCRIPTION = (pathlib.Path(__file__).resolve().parent.parent
               / "connectors" / "qonto" / "connector.yaml")

KEY = "acme-1234:sk_test"
BASE = "https://thirdparty.qonto.com/v2"
ACCOUNT = "0f9a3c1e-0000-4000-8000-00000000a001"


class _Resp:
    def __init__(self, status_code: int = 200, body=None, headers=None):
        self.status_code = status_code
        self._body = body if body is not None else {"meta": {}}
        self.content = b"x"
        self.text = str(self._body)
        self.headers = headers or {}

    def json(self):
        return self._body


@pytest.fixture()
def capture(monkeypatch):
    seen = {"calls": [], "responses": []}

    def fake_request(self, method, url, **kwargs):
        seen.update(method=method, url=url, kwargs=kwargs, headers=dict(self.headers))
        seen["calls"].append((method, url))
        if seen["responses"]:
            return seen["responses"].pop(0)
        return _Resp(200)

    monkeypatch.setattr(qc.requests.Session, "request", fake_request)
    monkeypatch.setattr(qc.time, "sleep", lambda _s: None)
    return seen


@pytest.fixture()
def cli():
    return qc.QontoClient(api_key=KEY)


# --- auth, sonde ------------------------------------------------------------

def test_key_goes_as_is_in_authorization_and_probe_reads_the_organization(capture, cli):
    cli.probe()
    assert capture["headers"]["Authorization"] == KEY
    assert capture["calls"] == [("GET", f"{BASE}/organization")]
    assert capture["kwargs"]["params"] is None
    assert capture["kwargs"]["allow_redirects"] is False
    assert capture["kwargs"]["timeout"] == qc.HTTP_TIMEOUT


def test_missing_key_is_named_never_read_from_env(monkeypatch):
    monkeypatch.setenv("QONTO_API_KEY", "env-1:sk_env")
    with pytest.raises(MissingCredential, match="QONTO_API_KEY"):
        qc.QontoClient()


@pytest.mark.parametrize("key", ["sk_only", ":sk", "acme-1:", "acme 1:sk", "acme-1:sk x"])
def test_key_must_be_login_colon_secret(key):
    with pytest.raises(ValueError, match="login:secret-key"):
        qc.QontoClient(api_key=key)


# --- query & chemins ----------------------------------------------------------

def test_transactions_arrays_go_bracketed_and_booleans_as_text(capture, cli):
    cli.list_transactions(ACCOUNT, status=["completed", "pending"], side="debit",
                          operation_type=["card"], settled_at_from="2026-10-01",
                          with_attachments=False, includes=["vat_details", "labels"],
                          sort_by="settled_at:asc", page=2, per_page=50)
    assert capture["calls"] == [("GET", f"{BASE}/transactions")]
    assert capture["kwargs"]["params"] == [
        ("bank_account_id", ACCOUNT),
        ("status[]", "completed"), ("status[]", "pending"),
        ("side", "debit"), ("operation_type[]", "card"),
        ("settled_at_from", "2026-10-01"), ("with_attachments", "false"),
        ("includes[]", "vat_details"), ("includes[]", "labels"),
        ("sort_by", "settled_at:asc"), ("page", 2), ("per_page", 50)]


def test_transactions_need_exactly_one_account(cli):
    with pytest.raises(ValueError, match="exactly one"):
        cli.list_transactions()
    with pytest.raises(ValueError, match="exactly one"):
        cli.list_transactions(ACCOUNT, iban="FR7616958000010000000000000")


def test_iban_spaces_are_dropped(capture, cli):
    cli.list_transactions(iban="FR76 1695 8000 0100 0000 0000 000")
    assert capture["kwargs"]["params"] == [("iban", "FR7616958000010000000000000")]


def test_invoice_filters_use_filter_keys(capture, cli):
    cli.list_client_invoices("unpaid", due_date_to="2026-10-31", exclude_imported=False)
    assert capture["calls"] == [("GET", f"{BASE}/client_invoices")]
    assert capture["kwargs"]["params"] == [
        ("filter[status]", "unpaid"), ("filter[due_date_to]", "2026-10-31"),
        ("exclude_imported", "false")]


@pytest.mark.parametrize("call, path", [
    (lambda c: c.get_transaction("t-1"), "/transactions/t-1"),
    (lambda c: c.list_transaction_attachments("t-1"), "/transactions/t-1/attachments"),
    (lambda c: c.get_attachment("a-1"), "/attachments/a-1"),
    (lambda c: c.get_statement("s-1"), "/statements/s-1"),
    (lambda c: c.get_supplier_invoice("i-1"), "/supplier_invoices/i-1"),
    (lambda c: c.get_client_invoice("i-2"), "/client_invoices/i-2"),
    (lambda c: c.get_client("c-1"), "/clients/c-1"),
    (lambda c: c.list_memberships(), "/memberships"),
    (lambda c: c.list_labels(), "/labels"),
    (lambda c: c.list_sepa_transfers(), "/sepa/transfers"),
    (lambda c: c.list_sepa_beneficiaries(), "/sepa/beneficiaries"),
    (lambda c: c.list_requests(), "/requests"),
    (lambda c: c.list_credit_notes(), "/credit_notes"),
    (lambda c: c.list_quotes(), "/quotes"),
    (lambda c: c.list_clients(), "/clients"),
    (lambda c: c.list_supplier_invoices(), "/supplier_invoices"),
    (lambda c: c.list_statements(), "/statements"),
])
def test_paths(capture, cli, call, path):
    call(cli)
    assert capture["calls"] == [("GET", f"{BASE}{path}")]


# --- validation -------------------------------------------------------------

@pytest.mark.parametrize("bad", ["01/10/2026", "2026-13-01", "yesterday", 20261001])
def test_bad_dates_are_refused(cli, bad):
    with pytest.raises(ValueError, match="ISO 8601"):
        cli.list_supplier_invoices(created_at_from=bad)


def test_statement_period_is_month_year(cli):
    with pytest.raises(ValueError, match="MM-YYYY"):
        cli.list_statements(period_from="2026-10")


def test_statement_accounts_and_ibans_are_exclusive(cli):
    with pytest.raises(ValueError, match="together"):
        cli.list_statements(["a"], ["FR7616958000010000000000000"])


@pytest.mark.parametrize("bad", [0, -1, True, "2"])
def test_page_and_per_page_must_be_positive_integers(cli, bad):
    with pytest.raises(ValueError, match="page"):
        cli.list_labels(page=bad)
    with pytest.raises(ValueError, match="per_page"):
        cli.list_quotes(per_page=bad)


def test_unknown_enums_and_bare_strings_are_refused(cli):
    with pytest.raises(ValueError, match="status"):
        cli.list_transactions(ACCOUNT, status=["settled"])
    with pytest.raises(ValueError, match="non-empty list"):
        cli.list_transactions(ACCOUNT, status="completed")
    with pytest.raises(ValueError, match="status"):
        cli.list_client_invoices("open")
    with pytest.raises(ValueError, match="sort_by"):
        cli.list_transactions(ACCOUNT, sort_by="amount:desc")


def test_client_name_needs_two_characters(cli):
    with pytest.raises(ValueError, match="2 characters"):
        cli.list_clients(name="K")


@pytest.mark.parametrize("bad", ["../organization", "a?b=1", "a b", ""])
def test_ids_cannot_reshape_the_url(cli, bad):
    with pytest.raises(ValueError, match="transaction_id"):
        cli.get_transaction(bad)


# --- transport --------------------------------------------------------------

def test_401_is_raised_at_once_never_retried(capture, cli):
    capture["responses"] = [_Resp(401, body={"errors": [{"code": "unauthorized"}]})]
    with pytest.raises(UpstreamHTTPError) as exc:
        cli.get_organization()
    assert exc.value.status_code == 401
    assert exc.value.service == "qonto"
    assert len(capture["calls"]) == 1


def test_429_is_retried_then_succeeds(capture, cli):
    capture["responses"] = [_Resp(429), _Resp(200, body={"labels": []})]
    assert cli.list_labels() == {"labels": []}
    assert len(capture["calls"]) == 2


def test_retries_are_bounded(capture, cli):
    capture["responses"] = [_Resp(503)] * qc.MAX_ATTEMPTS
    with pytest.raises(UpstreamHTTPError):
        cli.list_labels()
    assert len(capture["calls"]) == qc.MAX_ATTEMPTS


def test_redirect_is_refused(capture, cli):
    capture["responses"] = [_Resp(302, headers={"Location": "https://elsewhere.example"})]
    with pytest.raises(RedirectRefused):
        cli.get_organization()


# --- la description, rejouée ----------------------------------------------------

def _examples():
    doc = yaml.safe_load(DESCRIPTION.read_text(encoding="utf-8"))
    for fn in doc["functions"]:
        for ex in fn["examples"]:
            yield pytest.param(fn, ex["input"], id=f'{fn["name"]}:{ex["title"]}')


def _encoded(api: str, value):
    """The query pairs of one argument as the description says them: an array
    bracketed and repeated (`query_arrays: brackets`), a boolean as text."""
    if isinstance(value, list):
        return [(f"{api}[]", v) for v in value]
    if isinstance(value, bool):
        return [(api, "true" if value else "false")]
    return [(api, value)]


@pytest.mark.parametrize("fn, args", list(_examples()))
def test_every_example_replays_as_described(capture, cli, fn, args):
    getattr(cli, fn["name"])(**args)
    call = fn["call"]
    path = call["path"].format(**args)
    assert capture["calls"] == [(call["method"], f"{BASE}{path}")]
    expected = [pair for api, arg in (call.get("query") or {}).items() if arg in args
                for pair in _encoded(api, args[arg])]
    assert sorted(capture["kwargs"]["params"] or []) == sorted(expected)
