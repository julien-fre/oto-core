"""Contrat du client jefacture.com (Banqup région France, Bearer, lecture seule).

Mocke `requests.Session.request` : en-tête d'auth, hôte de la région France,
chemins par espace, query de l'API (filtres entre crochets, pages à partir de
0), bornes (UUID, dates, tailles de page), énumérations, re-tentatives sur 429,
redirection refusée — et le jeton jamais lu de l'environnement. Chaque exemple
de la description est rejoué contre le client, constantes comprises.
"""
from __future__ import annotations

import pathlib

import pytest
import yaml

from oto.tools.jefacture import client as jf
from oto.tools.common.errors import UpstreamHTTPError
from oto.tools.http.client import RedirectRefused

DESCRIPTION = (pathlib.Path(__file__).resolve().parent.parent
               / "connectors" / "jefacture" / "connector.yaml")

BASE = "https://api.btx.fr.banqup.com"
SPACE = "4b0a3c5e-0d1f-4c2a-9f6e-1a2b3c4d5e6f"
DOC = "1d0159ca-ab19-49d5-9e13-9d34afb03849"


class _Resp:
    def __init__(self, status_code: int = 200, body=None, headers=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
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

    monkeypatch.setattr(jf.requests.Session, "request", fake_request)
    monkeypatch.setattr(jf.time, "sleep", lambda _s: None)
    return seen


@pytest.fixture()
def cli():
    return jf.JefactureClient(access_token="at_test")


# --- auth, identité -----------------------------------------------------------

def test_bearer_and_identity(capture, cli):
    cli.get_me()
    assert capture["headers"]["Authorization"] == "Bearer at_test"
    assert capture["calls"] == [("GET", f"{BASE}/workspace/user/business/v1/users/me")]
    assert capture["kwargs"]["params"] is None
    assert capture["kwargs"]["allow_redirects"] is False
    assert capture["kwargs"]["timeout"] == jf.HTTP_TIMEOUT


def test_missing_token_is_named_never_read_from_env(monkeypatch):
    """The library never reads secrets: an absent token is a named refusal."""
    from oto.tools.common.credentials import MissingCredential
    monkeypatch.setenv("JEFACTURE_ACCESS_TOKEN", "at_env")
    with pytest.raises(MissingCredential) as exc:
        jf.JefactureClient()
    assert "JEFACTURE_ACCESS_TOKEN" in str(exc.value)


# --- query ------------------------------------------------------------------------

def test_list_documents_maps_filters_to_the_api(capture, cli):
    cli.list_documents(SPACE, folder="PURCHASES", category="INVOICE",
                       status_query="pay=UNPAID", issued_from="2026-09-01",
                       issued_to="2026-09-30", due_to="2026-10-31",
                       updated_since="2026-10-01T00:00:00Z", document_number="F-12",
                       counterpart="Dupont", sort_by="dueDate.asc", page=0, page_size=200)
    assert capture["calls"] == [
        ("GET", f"{BASE}/documents/core/transaction/v2/spaces/{SPACE}/documents")]
    assert capture["kwargs"]["params"] == {
        "include": "connections,balanceOffsets", "folder": "PURCHASES",
        "category": "INVOICE", "status[ql]": "pay=UNPAID",
        "issueDate[gte]": "2026-09-01", "issueDate[lte]": "2026-09-30",
        "dueDate[lte]": "2026-10-31", "updatedAt[gte]": "2026-10-01T00:00:00Z",
        "documentNumber[icont]": "F-12", "connectionName[icont]": "Dupont",
        "sortBy": "dueDate.asc", "page": 0, "pageSize": 200}


def test_list_spaces_sorts_by_name_and_pages_from_zero(capture, cli):
    cli.list_spaces(page=0)
    assert capture["calls"] == [("GET", f"{BASE}/workspace/space/v2/spaces")]
    assert capture["kwargs"]["params"] == {"sortBy": "name.asc", "page": 0}


def test_reconciliation_and_movements_use_size(capture, cli):
    cli.list_reconciliations(SPACE, matching_status="UNMATCHED", page=2, page_size=50)
    assert capture["kwargs"]["params"] == {"matchingStatus": "UNMATCHED", "page": 2, "size": 50}
    acc = "2f1e0d9c-8b7a-4c6d-9e5f-4a3b2c1d0e9f"
    cli.list_account_movements(SPACE, acc, booking_type="BOOKED", page_size=100)
    assert capture["url"] == (
        f"{BASE}/payments/paymentaccounts/v1/spaces/{SPACE}/paymentAccounts/{acc}/movements")
    assert capture["kwargs"]["params"] == {"bookingType": "BOOKED", "size": 100}


# --- bornes ---------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["", "abc", "../spaces", f"{SPACE}/x", None, 12])
def test_ids_cannot_reshape_the_url(cli, bad):
    with pytest.raises(ValueError, match="UUID"):
        cli.get_document(SPACE, bad)
    with pytest.raises(ValueError, match="space_id"):
        cli.list_payment_accounts(bad)


@pytest.mark.parametrize("kwargs, match", [
    ({"issued_from": "2026-13-01"}, "issued_from"),
    ({"due_to": "01/10/2026"}, "due_to"),
    ({"updated_since": "hier"}, "updated_since"),
    ({"folder": "sales"}, "folder"),
    ({"category": "BILL"}, "category"),
    ({"sort_by": "random"}, "sort_by"),
    ({"status_query": "  "}, "status_query"),
    ({"page": -1}, "page"),
    ({"page": True}, "page"),
    ({"page_size": 0}, "page_size"),
    ({"page_size": 201}, "page_size"),
])
def test_bad_arguments_are_refused(cli, kwargs, match):
    with pytest.raises(ValueError, match=match):
        cli.list_documents(SPACE, **kwargs)


def test_movements_window_is_ordered_and_bounded(cli):
    acc = "2f1e0d9c-8b7a-4c6d-9e5f-4a3b2c1d0e9f"
    with pytest.raises(ValueError, match="date_to"):
        cli.list_account_movements(SPACE, acc, date_from="2026-10-31", date_to="2026-10-01")
    with pytest.raises(ValueError, match="page_size"):
        cli.list_account_movements(SPACE, acc, page_size=101)


# --- erreurs, re-tentatives, redirection -------------------------------------------

def test_upstream_error_is_raised_with_service(capture, cli):
    capture["responses"] = [_Resp(403, {"status": 403, "title": "Forbidden"})]
    with pytest.raises(UpstreamHTTPError) as exc:
        cli.list_spaces()
    assert exc.value.status_code == 403
    assert exc.value.service == "jefacture"


def test_429_is_retried_then_succeeds(capture, cli):
    capture["responses"] = [_Resp(429), _Resp(200, {"spaces": []})]
    assert cli.list_spaces() == {"spaces": []}
    assert len(capture["calls"]) == 2


def test_retries_are_bounded(capture, cli):
    capture["responses"] = [_Resp(503)] * 5
    with pytest.raises(UpstreamHTTPError):
        cli.list_spaces()
    assert len(capture["calls"]) == jf.MAX_ATTEMPTS


def test_redirect_is_refused(capture, cli):
    capture["responses"] = [_Resp(302, headers={"Location": "https://elsewhere.example.test/"})]
    with pytest.raises(RedirectRefused):
        cli.get_me()
    assert len(capture["calls"]) == 1


# --- la description, rejouée ----------------------------------------------------

def _examples():
    doc = yaml.safe_load(DESCRIPTION.read_text(encoding="utf-8"))
    for fn in doc["functions"]:
        for ex in fn["examples"]:
            yield pytest.param(fn, ex["input"], id=f'{fn["name"]}:{ex["title"]}')


@pytest.mark.parametrize("fn, args", list(_examples()))
def test_every_example_replays_as_described(capture, cli, fn, args):
    getattr(cli, fn["name"])(**args)
    call = fn["call"]
    path = call["path"].format(**args)
    assert capture["calls"] == [(call["method"], f"{BASE}{path}")]
    expected = {api: args[arg] for api, arg in (call.get("query") or {}).items()
                if arg in args}
    expected.update((call.get("constants") or {}).get("query") or {})
    assert (capture["kwargs"]["params"] or {}) == expected


def test_base_url_is_the_described_one():
    doc = yaml.safe_load(DESCRIPTION.read_text(encoding="utf-8"))
    assert doc["connector"]["base_url"] == jf.BASE_URL == BASE
