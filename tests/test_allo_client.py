"""Contract of the Allo client (`Authorization: Api-Key <key>`; conversations,
tags, notes, CRM, Power Dialer queue, analytics, SMS).

Mocks `requests.Session.request`: paths, query and body as in the vendor's API
reference, the auth header and never the key in the query, the timeout, phone
numbers percent-encoded in a path, local refusals. The reads of a call lose their
recording addresses; the audio of a call comes as a file, over a fake transport
(the API call, then the download of the signed link). Phone numbers are made up
(+33 1 99 00, +1 415 555 01xx: ranges reserved for fiction).
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
    (lambda c: c.list_conversations("+33199000000"), "GET", "/v2/api/conversations"),
    (lambda c: c.search_conversation_items(), "POST", "/v2/api/conversations/items/search"),
    (lambda c: c.get_conversation_item("cll-1"), "GET", "/v2/api/conversations/items/cll-1"),
    (lambda c: c.get_conversation_items(["cll-1"]), "POST", "/v2/api/conversations/items/batch"),
    (lambda c: c.update_call_summary("cll-1", "x"), "PATCH",
     "/v2/api/conversations/items/cll-1/summary"),
    (lambda c: c.update_conversation("+33199000001", "READ"), "PUT",
     "/v2/api/conversations/%2B33199000001/action"),
    (lambda c: c.list_tags(), "GET", "/v2/api/tags"),
    (lambda c: c.create_tag("Hot"), "POST", "/v2/api/tags"),
    (lambda c: c.add_item_tags("cll-1", ["hot"]), "POST", "/v2/api/conversations/items/cll-1/tags"),
    (lambda c: c.remove_item_tag("cll-1", "hot"), "DELETE",
     "/v2/api/conversations/items/cll-1/tags/hot"),
    (lambda c: c.list_conversation_notes("+33199000001", "+33199000000"), "GET",
     "/v2/api/conversations/%2B33199000001/notes"),
    (lambda c: c.create_conversation_note("+33199000001", "x"), "POST",
     "/v2/api/conversations/%2B33199000001/notes"),
    (lambda c: c.list_person_notes("per-1"), "GET", "/v2/api/crm/people/per-1/notes"),
    (lambda c: c.create_person_note("per-1", "x"), "POST", "/v2/api/crm/people/per-1/notes"),
    (lambda c: c.search_people(), "POST", "/v2/api/crm/people/search"),
    (lambda c: c.get_person("per-1"), "GET", "/v2/api/crm/people/per-1"),
    (lambda c: c.create_person(["+33199000001"]), "POST", "/v2/api/crm/people"),
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
    (lambda c: c.add_queue_numbers([{"number": "+33199000001"}]), "POST",
     "/v2/api/dialing-queues/current/numbers"),
    (lambda c: c.remove_queue_numbers(unassigned=True), "DELETE",
     "/v2/api/dialing-queues/current/numbers"),
    (lambda c: c.get_team_metrics({"from": "2026-10-01", "to": "2026-10-07"}), "POST",
     "/v2/api/analytics/overview"),
    (lambda c: c.get_outbound_metrics({"from": "2026-10-01", "to": "2026-10-07"}), "POST",
     "/v2/api/analytics/outbound"),
    (lambda c: c.send_sms("+14155550123", "hi", from_number="+14155550100"), "POST", "/v1/api/sms"),
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
    cli.list_conversations("+33199000000", unread=True, size=50)
    assert capture["kwargs"]["params"] == {"allo_number": "+33199000000", "unread": "true",
                                           "size": 50}


def test_create_person_body(cli, capture):
    cli.create_person(["+33199000001"], name="Marie", custom_attributes={"tier": "A"})
    assert capture["kwargs"]["json"] == {"numbers": ["+33199000001"], "name": "Marie",
                                         "custom_attributes": {"tier": "A"}}


def test_sms_from_a_number_or_a_sender_id(cli, capture):
    cli.send_sms("+33199000001", "Bonjour", sender_id="MyCompany")
    assert capture["kwargs"]["json"] == {"sender_id": "MyCompany", "to": "+33199000001",
                                         "message": "Bonjour"}
    cli.send_sms("+14155550123", "Hi", from_number="+14155550100")
    assert capture["kwargs"]["json"] == {"from": "+14155550100", "to": "+14155550123",
                                         "message": "Hi"}


@pytest.mark.parametrize("kwargs", [{}, {"from_number": "+1", "sender_id": "X"}])
def test_sms_needs_exactly_one_sender(cli, capture, kwargs):
    capture["method"] = None
    with pytest.raises(ValueError):
        cli.send_sms("+33199000001", "x", **kwargs)
    assert capture["method"] is None


def test_remove_queue_numbers_filters(cli, capture):
    cli.remove_queue_numbers(number="+33199000001", position=2)
    assert capture["kwargs"]["params"] == {"number": "+33199000001", "position": 2}
    with pytest.raises(ValueError):
        cli.remove_queue_numbers()
    with pytest.raises(ValueError):
        cli.remove_queue_numbers(unassigned=True, number="+33199000001")


@pytest.mark.parametrize("call", [
    lambda c: c.update_conversation("+33199000001", "DELETE"),
    lambda c: c.search_people(sort="RANDOM"),
    lambda c: c.list_conversations("+33199000000", size=500),
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


# --- no recording address leaves the client (1.1.0) ------------------------------------------

_ADDRESSES = {
    "recording_url": "https://files.example.test/recordings/cll-1.mp3",
    "recording_download_url": "https://files.example.test/sign/recordings/cll-1.mp3?token=t-0",
    "recording_download_expires_at": "2026-01-01T00:00:00Z",
}


def _item(item_id="cll-1"):
    return {"id": item_id, "type": "CALL", "duration": 42, "recording_duration": 30, **_ADDRESSES}


_PAGINATION = {"page": 1, "size": 20, "total_count": 2, "total_pages": 1, "has_more": False}


@pytest.mark.parametrize("call", [
    lambda c: c.search_conversation_items(type="CALL"),
    lambda c: c.get_conversation_items(["cll-1", "cll-2"]),
])
def test_lists_of_items_lose_their_addresses_and_keep_pagination(cli, capture, call):
    capture["responses"].append(_Resp(200, {"data": [_item("cll-1"), _item("cll-2")], "pagination": _PAGINATION}))
    answer = call(cli)
    assert answer["pagination"] == _PAGINATION
    assert [i["id"] for i in answer["data"]] == ["cll-1", "cll-2"]
    for item in answer["data"]:
        assert not set(_ADDRESSES) & set(item)
        assert item["recording_duration"] == 30


def test_one_item_loses_its_addresses(cli, capture):
    capture["responses"].append(_Resp(200, {"data": _item("cll-1")}))
    assert cli.get_conversation_item("cll-1") == {
        "data": {"id": "cll-1", "type": "CALL", "duration": 42, "recording_duration": 30}}


def test_the_last_item_of_each_conversation_loses_its_addresses(cli, capture):
    conversations = [{"contact_number": "+33199000001", "last_item": _item("cll-1")},
                     {"contact_number": "+33199000002", "last_item": None}]
    capture["responses"].append(_Resp(200, {"data": conversations, "pagination": _PAGINATION}))
    answer = cli.list_conversations("+33199000000")
    assert answer["data"][0] == {"contact_number": "+33199000001",
                                 "last_item": {"id": "cll-1", "type": "CALL", "duration": 42,
                                               "recording_duration": 30}}
    assert answer["data"][1]["last_item"] is None
    assert answer["pagination"] == _PAGINATION


def test_the_signed_link_is_no_method_any_more(cli):
    assert not hasattr(cli, "get_recording_link")


# --- the audio of a call, rendered as a file ---------------------------------------------------

from requests.adapters import HTTPAdapter  # noqa: E402

import files_fake  # noqa: E402
from oto.connectors.files import FileOut, FileOutputError  # noqa: E402
from oto.tools.common import url_guard  # noqa: E402

_LINK = "https://files.example.test/sign/recordings/cll-812.mp3?token=t-0"
_AUDIO = {"status": 200, "headers": {"Content-Type": "audio/mpeg"}, "text": "ID3-audio"}


class _Sequence(HTTPAdapter):
    """Answers each request in order (the API call, then the download) and keeps each request."""

    def __init__(self, *answers):
        super().__init__()
        self.answers = list(answers)
        self.sent = []

    def send(self, request, **kwargs):
        self.sent.append(request)
        if not self.answers:
            raise AssertionError("nothing more should be sent")
        return self.build_response(request, files_fake.raw(self.answers.pop(0)))


def _json(status, value):
    return {"status": status, "headers": {"Content-Type": "application/json"}, "json": value}


@pytest.fixture()
def wire(cli, monkeypatch):
    monkeypatch.setattr(url_guard.socket, "getaddrinfo", files_fake.resolve_publicly)

    def mount(*answers):
        transport = _Sequence(*answers)
        cli.session.mount("https://", transport)
        cli.session.mount("http://", transport)
        return transport
    return mount


def test_the_recording_of_a_call_is_a_file(cli, wire):
    transport = wire(_json(200, {"data": {"url": _LINK, "expires_at": "2026-01-01T01:00:00Z"}}), _AUDIO)
    result = cli.get_call_recording("cll-812")
    assert result == FileOut(name="call-cll-812-recording.mp3", content=b"ID3-audio", mime="audio/mpeg")
    api, download = transport.sent
    assert api.method == "GET" and api.url == al.BASE_URL + "/v2/api/conversations/items/cll-812/recording"
    assert api.headers["Authorization"] == "Api-Key ak_live_SECRET"
    assert download.url == _LINK
    assert "Authorization" not in download.headers


@pytest.mark.parametrize("status, code", [(404, "RECORDING_NOT_FOUND"), (404, "CONVERSATION_ITEM_NOT_FOUND"),
                                          (403, "RECORDING_ACCESS_DENIED"), (403, "RECORDING_DOWNLOAD_RESTRICTED")])
def test_a_refused_call_downloads_nothing(cli, wire, status, code):
    transport = wire(_json(status, {"error": {"code": code}}))
    with pytest.raises(UpstreamHTTPError) as e:
        cli.get_call_recording("cll-812")
    assert e.value.status_code == status
    assert len(transport.sent) == 1


def test_an_answer_without_a_link_has_no_file(cli, wire):
    transport = wire(_json(200, {"data": {"url": None}}))
    with pytest.raises(FileOutputError) as e:
        cli.get_call_recording("cll-812")
    assert e.value.code == "file_missing"
    assert len(transport.sent) == 1


def test_a_link_in_http_is_refused_without_being_told(cli, wire):
    link = "http://files.example.test/sign/recordings/cll-812.mp3?token=t-0"
    transport = wire(_json(200, {"data": {"url": link}}))
    with pytest.raises(FileOutputError) as e:
        cli.get_call_recording("cll-812")
    assert e.value.code == "file_download_refused"
    assert link not in str(e.value) and "t-0" not in str(e.value)
    assert len(transport.sent) == 1


def test_a_redirect_of_the_link_is_not_followed(cli, wire):
    moved = {"status": 302, "headers": {"Location": "https://elsewhere.example.test/a.mp3"}, "text": ""}
    transport = wire(_json(200, {"data": {"url": _LINK}}), moved)
    with pytest.raises(FileOutputError) as e:
        cli.get_call_recording("cll-812")
    assert e.value.code == "file_download_refused"
    assert len(transport.sent) == 2


@pytest.mark.parametrize("bad", ["..", ".", "", None])
def test_an_id_that_leaves_the_path_is_refused_before_sending(cli, wire, bad):
    transport = wire()
    with pytest.raises(ValueError):
        cli.get_call_recording(bad)
    assert transport.sent == []
