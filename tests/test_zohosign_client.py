"""Zoho Sign client: requests sent, files returned, refusals named — HTTP doubles only."""
import json

import pytest

from oto.tools.common.errors import UpstreamHTTPError
from oto.tools.zohosign import client as zs
from oto.tools.zohosign.client import ZohoSignClient, required_scope

API = "https://sign.zoho.test"
ACCOUNTS = "https://accounts.zoho.test"


class _Resp:
    def __init__(self, status=200, body=None, content=None, headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or ({"Content-Type": "application/json"} if body is not None
                                   else {})
        self.content = content if content is not None else (
            json.dumps(body).encode() if body is not None else b"")
        self.text = self.content.decode(errors="replace")
        self.request = None
        self.url = ""

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


@pytest.fixture
def calls(monkeypatch):
    seen, answers = [], []
    monkeypatch.setattr(zs, "get_access_token", lambda *a, **k: "tok")
    monkeypatch.setattr(zs, "invalidate", lambda key: seen.append(("invalidate",)))

    def fake(method, url, **kwargs):
        seen.append((method, url, kwargs))
        return answers.pop(0)

    monkeypatch.setattr(zs.requests, "request", fake)
    return seen, answers


def _client():
    return ZohoSignClient("id", "secret", "rt", api_domain=API, accounts_url=ACCOUNTS)


def test_addresses_have_no_default():
    with pytest.raises(ValueError):
        ZohoSignClient("id", "secret", "rt")


def test_list_sends_one_page_context_in_data(calls):
    seen, answers = calls
    answers.append(_Resp(body={"code": 0, "status": "success", "requests": [],
                               "page_context": {"has_more_rows": False}}))
    out = _client().list_requests(start_index=11, row_count=10,
                                  search_columns={"recipient_email": "a@example.test"})
    method, url, kw = seen[0]
    assert (method, url) == ("GET", f"{API}/api/v1/requests")
    assert json.loads(kw["params"]["data"]) == {"page_context": {
        "row_count": 10, "start_index": 11,
        "search_columns": {"recipient_email": "a@example.test"},
        "sort_column": "created_time", "sort_order": "DESC"}}
    assert kw["headers"]["Authorization"] == "Zoho-oauthtoken tok"
    assert kw["allow_redirects"] is False
    assert out["requests"] == []


def test_list_refuses_an_undocumented_filter_or_sort(calls):
    with pytest.raises(ValueError):
        _client().list_requests(search_columns={"request_status": "completed"})
    with pytest.raises(ValueError):
        _client().list_requests(sort_column="modified_time")


def test_template_page_size_is_zohos(calls):
    with pytest.raises(ValueError):
        _client().list_templates(row_count=30)


def test_create_from_template_posts_a_form_with_the_json_document(calls):
    seen, answers = calls
    answers.append(_Resp(body={"code": 0, "status": "success",
                               "requests": {"request_id": "9"}}))
    actions = [{"action_id": "1", "action_type": "SIGN", "recipient_name": "Ann",
                "recipient_email": "ann@example.test", "verify_recipient": False}]
    _client().create_from_template("42", actions, request_name="NDA",
                                   field_data={"field_text_data": {"Company": "Acme"}})
    method, url, kw = seen[0]
    assert (method, url) == ("POST", f"{API}/api/v1/templates/42/createdocument")
    assert kw["data"]["is_quicksend"] == "true"
    assert json.loads(kw["data"]["data"]) == {"templates": {
        "actions": actions, "notes": "", "request_name": "NDA",
        "field_data": {"field_text_data": {"Company": "Acme"}}}}


def test_draft_is_not_sent(calls):
    seen, answers = calls
    answers.append(_Resp(body={"code": 0, "status": "success", "requests": {}}))
    _client().create_from_template("42", [{"action_id": "1"}], quick_send=False)
    assert seen[0][2]["data"]["is_quicksend"] == "false"


@pytest.mark.parametrize("gesture, path", [("remind", "remind"), ("recall", "recall")])
def test_remind_and_recall_post_on_the_request(calls, gesture, path):
    seen, answers = calls
    answers.append(_Resp(body={"code": 0, "status": "success", "message": "ok"}))
    getattr(_client(), gesture)("7")
    assert seen[0][:2] == ("POST", f"{API}/api/v1/requests/7/{path}")


def test_pdf_comes_back_as_bytes_with_its_name(calls):
    seen, answers = calls
    answers.append(_Resp(content=b"%PDF-1.7", headers={
        "Content-Type": "application/pdf",
        "Content-Disposition": 'attachment; filename="NDA signed.pdf"'}))
    f = _client().download_pdf("7", with_coc=True)
    assert seen[0][2]["params"] == {"with_coc": "true"}
    assert f == {"filename": "NDA signed.pdf", "content_type": "application/pdf",
                 "content": b"%PDF-1.7"}


def test_several_documents_come_back_as_a_zip(calls):
    _, answers = calls
    answers.append(_Resp(content=b"PK\x03\x04", headers={"Content-Type": "application/zip"}))
    assert _client().download_pdf("7")["filename"] == "7.zip"


def test_certificate_without_a_name_gets_one(calls):
    _, answers = calls
    answers.append(_Resp(content=b"%PDF", headers={"Content-Type": "application/pdf"}))
    f = _client().download_completion_certificate("7")
    assert f["filename"] == "7-completion-certificate.pdf"


def test_a_json_body_on_a_file_endpoint_is_a_refusal(calls):
    _, answers = calls
    answers.append(_Resp(body={"code": 9001, "status": "failure",
                               "message": "Document not completed"}))
    with pytest.raises(UpstreamHTTPError):
        _client().download_completion_certificate("7")


def test_a_failure_status_under_200_is_raised(calls):
    _, answers = calls
    answers.append(_Resp(body={"code": 4003, "status": "failure", "message": "nope"}))
    with pytest.raises(UpstreamHTTPError) as e:
        _client().get_request("7")
    assert e.value.status_code == 400


def test_one_new_token_after_a_401(calls):
    seen, answers = calls
    answers.extend([_Resp(401, body={"code": 1, "status": "failure", "message": "x"}),
                    _Resp(body={"code": 0, "status": "success", "requests": {}})])
    _client().get_request("7")
    assert [c[0] for c in seen] == ["GET", "invalidate", "GET"]


def test_a_refused_call_names_the_scope_it_expects(calls):
    _, answers = calls
    answers.append(_Resp(403, body={"code": 9041, "status": "failure",
                                    "message": "Invalid OAuth scope"}))
    with pytest.raises(UpstreamHTTPError) as e:
        _client().recall("7")
    assert "ZohoSign.documents.UPDATE" in str(e.value)


def test_a_redirect_is_never_followed(calls):
    _, answers = calls
    answers.append(_Resp(302, headers={"Location": "https://elsewhere.test/"}))
    with pytest.raises(Exception) as e:
        _client().get_request("7")
    assert "302" in str(e.value) or "redirect" in str(e.value).lower()


@pytest.mark.parametrize("method, endpoint, scope", [
    ("GET", "requests", "ZohoSign.documents.READ"),
    ("GET", "requests/7", "ZohoSign.documents.READ"),
    ("GET", "requests/7/pdf", "ZohoSign.documents.READ"),
    ("GET", "requests/7/completioncertificate", "ZohoSign.documents.READ"),
    ("POST", "requests/7/remind", "ZohoSign.documents.UPDATE"),
    ("POST", "requests/7/recall", "ZohoSign.documents.UPDATE"),
    ("GET", "templates", "ZohoSign.templates.READ"),
    ("GET", "templates/4", "ZohoSign.templates.READ"),
    ("POST", "templates/4/createdocument", "ZohoSign.documents.CREATE"),
    ("DELETE", "requests/7", None),
])
def test_scope_by_call(method, endpoint, scope):
    assert required_scope(method, endpoint) == scope
