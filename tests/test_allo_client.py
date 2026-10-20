"""Contract of the Allo client (`Authorization: Api-Key <key>`; conversations,
tags, notes, CRM, Power Dialer queue, analytics, SMS).

Mocks `requests.Session.request`: paths, query and body as in the vendor's API
reference, the auth header and never the key in the query, the timeout, phone
numbers percent-encoded in a path, local refusals.
"""
from __future__ import annotations

import pytest

from oto.tools.allo import client as al
from oto.tools.common.credentials import MissingCredential
from oto.tools.common.errors import UpstreamHTTPError


class _Resp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {"data": {}}
        self.content = b"x"
        self.text = str(self._body)

    def json(self):
        return self._body


@pytest.fixture()
def capture(monkeypatch):
    seen = {"responses": []}

    def fake_request(self, method, url, **kwargs):
        seen.update(method=method, url=url, kwargs=kwargs)
        if seen["responses"]:
            return seen["responses"].pop(0)
        return _Resp(200)

    monkeypatch.setattr(al.requests.Session, "request", fake_request)
    return seen


@pytest.fixture()
def cli():
    return al.AlloClient(api_key="ak_live_SECRET")


def test_key_required():
    with pytest.raises(MissingCredential):
        al.AlloClient(api_key=None)


def test_api_key_scheme_in_header_never_in_query(cli, capture):
    cli.list_users(role="ADMIN")
    assert cli.session.headers["Authorization"] == "Api-Key ak_live_SECRET"
    assert "SECRET" not in capture["url"]
    assert all("SECRET" not in str(v) for v in (capture["kwargs"].get("params") or {}).values())
    assert capture["kwargs"]["timeout"] == al._HTTP_TIMEOUT


@pytest.mark.parametrize("call,method,path", [
    (lambda c: c.probe(), "GET", "/v2/api/me"),
    (lambda c: c.list_numbers(), "GET", "/v2/api/numbers"),
    (lambda c: c.list_conversations("+33187000000"), "GET", "/v2/api/conversations"),
    (lambda c: c.search_conversation_items(), "POST", "/v2/api/conversations/items/search"),
    (lambda c: c.get_conversation_item("cll-1"), "GET", "/v2/api/conversations/items/cll-1"),
    (lambda c: c.get_conversation_items(["cll-1"]), "POST", "/v2/api/conversations/items/batch"),
    (lambda c: c.get_recording_link("cll-1"), "GET", "/v2/api/conversations/items/cll-1/recording"),
    (lambda c: c.update_call_summary("cll-1", "x"), "PATCH",
     "/v2/api/conversations/items/cll-1/summary"),
    (lambda c: c.update_conversation("+33612345678", "READ"), "PUT",
     "/v2/api/conversations/%2B33612345678/action"),
    (lambda c: c.list_tags(), "GET", "/v2/api/tags"),
    (lambda c: c.create_tag("Hot"), "POST", "/v2/api/tags"),
    (lambda c: c.add_item_tags("cll-1", ["hot"]), "POST", "/v2/api/conversations/items/cll-1/tags"),
    (lambda c: c.remove_item_tag("cll-1", "hot"), "DELETE",
     "/v2/api/conversations/items/cll-1/tags/hot"),
    (lambda c: c.list_conversation_notes("+33612345678", "+33187000000"), "GET",
     "/v2/api/conversations/%2B33612345678/notes"),
    (lambda c: c.create_conversation_note("+33612345678", "x"), "POST",
     "/v2/api/conversations/%2B33612345678/notes"),
    (lambda c: c.list_person_notes("per-1"), "GET", "/v2/api/crm/people/per-1/notes"),
    (lambda c: c.create_person_note("per-1", "x"), "POST", "/v2/api/crm/people/per-1/notes"),
    (lambda c: c.search_people(), "POST", "/v2/api/crm/people/search"),
    (lambda c: c.get_person("per-1"), "GET", "/v2/api/crm/people/per-1"),
    (lambda c: c.create_person(["+33612345678"]), "POST", "/v2/api/crm/people"),
    (lambda c: c.update_person("per-1", name="A"), "PUT", "/v2/api/crm/people/per-1"),
    (lambda c: c.search_companies(), "POST", "/v2/api/crm/companies/search"),
    (lambda c: c.get_company("com-1"), "GET", "/v2/api/crm/companies/com-1"),
    (lambda c: c.create_company("Acme"), "POST", "/v2/api/crm/companies"),
    (lambda c: c.update_company("com-1", industry="x"), "PUT", "/v2/api/crm/companies/com-1"),
    (lambda c: c.search_deals(), "POST", "/v2/api/crm/deals/search"),
    (lambda c: c.get_deal("dea-1"), "GET", "/v2/api/crm/deals/dea-1"),
    (lambda c: c.list_person_attributes(), "GET", "/v2/api/crm/attributes"),
    (lambda c: c.list_company_attributes(), "GET", "/v2/api/crm/companies/attributes"),
    (lambda c: c.get_dialing_queue(), "GET", "/v2/api/dialing-queues/current"),
    (lambda c: c.reset_dialing_queue(), "POST", "/v2/api/dialing-queues/current"),
    (lambda c: c.update_dialing_queue(name="Q"), "PATCH", "/v2/api/dialing-queues/current"),
    (lambda c: c.add_queue_numbers([{"number": "+33612345678"}]), "POST",
     "/v2/api/dialing-queues/current/numbers"),
    (lambda c: c.remove_queue_numbers(unassigned=True), "DELETE",
     "/v2/api/dialing-queues/current/numbers"),
    (lambda c: c.get_team_metrics({"from": "2026-10-01", "to": "2026-10-07"}), "POST",
     "/v2/api/analytics/overview"),
    (lambda c: c.get_outbound_metrics({"from": "2026-10-01", "to": "2026-10-07"}), "POST",
     "/v2/api/analytics/outbound"),
    (lambda c: c.send_sms("+14155551234", "hi", from_number="+14155550100"), "POST", "/v1/api/sms"),
])
def test_paths(cli, capture, call, method, path):
    call(cli)
    assert capture["method"] == method
    assert capture["url"] == al.BASE_URL + path


def test_none_never_sent(cli, capture):
    cli.search_conversation_items(type="CALL", search="pricing",
                                  date={"from": "2026-10-01", "to": "2026-10-20"})
    assert capture["kwargs"]["json"] == {"type": "CALL", "search": "pricing",
                                         "date": {"from": "2026-10-01", "to": "2026-10-20"}}
    cli.list_conversations("+33187000000", unread=True, size=50)
    assert capture["kwargs"]["params"] == {"allo_number": "+33187000000", "unread": "true",
                                           "size": 50}


def test_create_person_body(cli, capture):
    cli.create_person(["+33612345678"], name="Marie", custom_attributes={"tier": "A"})
    assert capture["kwargs"]["json"] == {"numbers": ["+33612345678"], "name": "Marie",
                                         "custom_attributes": {"tier": "A"}}


def test_sms_from_a_number_or_a_sender_id(cli, capture):
    cli.send_sms("+33612345678", "Bonjour", sender_id="MyCompany")
    assert capture["kwargs"]["json"] == {"sender_id": "MyCompany", "to": "+33612345678",
                                         "message": "Bonjour"}
    cli.send_sms("+14155551234", "Hi", from_number="+14155550100")
    assert capture["kwargs"]["json"] == {"from": "+14155550100", "to": "+14155551234",
                                         "message": "Hi"}


@pytest.mark.parametrize("kwargs", [{}, {"from_number": "+1", "sender_id": "X"}])
def test_sms_needs_exactly_one_sender(cli, capture, kwargs):
    capture["method"] = None
    with pytest.raises(ValueError):
        cli.send_sms("+33612345678", "x", **kwargs)
    assert capture["method"] is None


def test_remove_queue_numbers_filters(cli, capture):
    cli.remove_queue_numbers(number="+33612345678", position=2)
    assert capture["kwargs"]["params"] == {"number": "+33612345678", "position": 2}
    with pytest.raises(ValueError):
        cli.remove_queue_numbers()
    with pytest.raises(ValueError):
        cli.remove_queue_numbers(unassigned=True, number="+33612345678")


@pytest.mark.parametrize("call", [
    lambda c: c.update_conversation("+33612345678", "DELETE"),
    lambda c: c.search_people(sort="RANDOM"),
    lambda c: c.list_conversations("+33187000000", size=500),
    lambda c: c.get_outbound_metrics({"from": "a", "to": "b"}, extend="items"),
    lambda c: c.get_outbound_metrics({"from": "a", "to": "b"}, extend="calls", stage="DIAL"),
    lambda c: c.get_conversation_items([]),
    lambda c: c.add_item_tags("cll-1", []),
    lambda c: c.create_person([]),
    lambda c: c.add_queue_numbers([]),
])
def test_local_refusals(cli, call):
    with pytest.raises(ValueError):
        call(cli)


@pytest.mark.parametrize("bad", ["..", ".", "", None])
def test_ids_cannot_leave_the_path(cli, bad):
    with pytest.raises(ValueError):
        cli.get_person(bad)


def test_slash_in_an_id_stays_in_its_segment(cli, capture):
    cli.get_person("../tags")
    assert capture["url"] == al.BASE_URL + "/v2/api/crm/people/..%2Ftags"


def test_upstream_error_is_typed(cli, capture):
    capture["responses"].append(_Resp(403, body={"error": {"code": "INSUFFICIENT_SCOPE"}}))
    with pytest.raises(UpstreamHTTPError) as e:
        cli.get_person("per-1")
    assert e.value.status_code == 403
