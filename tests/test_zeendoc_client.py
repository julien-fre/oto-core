"""Contrat du client Zeendoc (API REST v4 et pages de document, GED en lecture seule).

Mocke `requests.post` (login) et `requests.Session.request` (le reste) : mot de passe
dans le corps JSON du login, cookie de session sur chaque appel et cache process-wide
keyé par empreinte, nouvelle connexion unique quand la session est close (401 de l'API,
page de connexion d'une page de document), critères traduits avec un id par critère,
bornes (opérateurs, page de 50, ids), noms de champs ramenés en `custom_t2`, document
absent en 404 (texte `ERROR`, redirection `no_right`), fichier PDF vérifié, redirection
refusée — et le credential jamais lu de l'environnement.
"""
from __future__ import annotations

import pytest

from oto.tools.common.errors import UpstreamHTTPError
from oto.tools.http.client import RedirectRefused
from oto.tools.zeendoc import ZeendocAuthError, auth
from oto.tools.zeendoc import client as zc

ROOT = "https://armoires.zeendoc.com/cab_1"
JSON = {"Content-Type": "application/json"}

CONTEXT = {"collections": [
    {"collId": "coll_2", "label": "Fournisseurs",
     "index": [{"indexId": "custom_t2", "label": "Fournisseur"},
               {"indexId": "custom_f1", "label": "Montant HT"}]},
    {"label": "_SERVICE_RECHERCHE_MULTI_CLASSEUR_LABEL", "index": [{}]},
]}


class _Resp:
    def __init__(self, status_code=200, body=None, headers=None, content=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.content = content if content is not None else b"{}"
        self.text = self.content.decode("latin-1")
        self.headers = headers if headers is not None else dict(JSON)
        self.url = f"{ROOT}/x"
        self.closed = False

    def json(self):
        return self._body

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size]

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _login(cookie="abc123", duration="38880s"):
    return _Resp(200, {"cookie": f"ZeenDoc={cookie}", "cookieDuration": duration})


@pytest.fixture()
def capture(monkeypatch):
    auth._SESSIONS.clear()
    seen = {"calls": [], "responses": [], "logins": [], "login_responses": []}

    def fake_post(url, **kwargs):
        seen["logins"].append((url, kwargs))
        return seen["login_responses"].pop(0) if seen["login_responses"] else _login()

    def fake_request(self, method, url, **kwargs):
        seen.update(method=method, url=url, kwargs=kwargs)
        seen["calls"].append((method, url, kwargs))
        return seen["responses"].pop(0) if seen["responses"] else _Resp(200, {})

    monkeypatch.setattr(auth.requests, "post", fake_post)
    monkeypatch.setattr(zc.requests.Session, "request", fake_request)
    monkeypatch.setattr(zc.time, "sleep", lambda _s: None)
    yield seen
    auth._SESSIONS.clear()


@pytest.fixture()
def cli():
    return zc.ZeendocClient(login="user@example.com", password="pw-secret", url_client="cab_1")


# --- session -----------------------------------------------------------------

def test_login_sends_the_password_in_a_json_body_and_the_cookie_rides_every_call(capture, cli):
    cli.get_context()
    url, kwargs = capture["logins"][0]
    assert url == f"{ROOT}/api/v4/login"
    assert kwargs["json"] == {"login": "user@example.com", "password": "pw-secret"}
    assert "params" not in kwargs and kwargs["allow_redirects"] is False
    method, url, kwargs = capture["calls"][0]
    assert (method, url) == ("GET", f"{ROOT}/api/v4/context")
    assert kwargs["headers"]["Cookie"] == "ZeenDoc=abc123"
    assert kwargs["allow_redirects"] is False and kwargs["timeout"] == zc.HTTP_TIMEOUT


def test_session_is_shared_by_clients_of_the_same_credential(capture):
    for _ in range(2):
        zc.ZeendocClient("user@example.com", "pw-secret", "cab_1").get_context()
    assert len(capture["logins"]) == 1
    assert all("pw-secret" not in key for key in auth._SESSIONS)


def test_refused_login_is_a_401_that_never_echoes_the_password(capture, cli):
    capture["login_responses"].append(_Resp(401, {"message": "Authentication failed."}))
    with pytest.raises(ZeendocAuthError) as e:
        cli.get_context()
    assert e.value.status_code == 401 and "pw-secret" not in str(e.value)
    assert capture["calls"] == []


def test_login_without_cookie_is_an_upstream_error(capture, cli):
    capture["login_responses"].append(_Resp(200, {"message": "ok"}))
    with pytest.raises(UpstreamHTTPError) as e:
        cli.get_context()
    assert e.value.status_code == 502


def test_closed_session_logs_in_again_once(capture, cli):
    capture["login_responses"] += [_login("old"), _login("new")]
    capture["responses"] += [_Resp(401, {"message": "no session"}), _Resp(200, CONTEXT)]
    assert cli.get_context() == CONTEXT
    assert [c[2]["headers"]["Cookie"] for c in capture["calls"]] == ["ZeenDoc=old", "ZeenDoc=new"]


def test_login_page_from_a_document_page_logs_in_again(capture, cli):
    login_page = _Resp(200, headers={"Content-Type": "text/html"},
                       content=b'<html><body OnLoad="window.location = \'/cab_1/Ihm/../index.php\'">')
    capture["responses"] += [login_page, _Resp(200, headers={}, content=b"Invoice\r\nTotal")]
    assert cli.get_document_text("coll_2", 7) == "Invoice\nTotal"
    assert len(capture["logins"]) == 2


def test_session_closed_twice_is_a_401(capture, cli):
    capture["responses"] += [_Resp(401), _Resp(401)]
    with pytest.raises(UpstreamHTTPError) as e:
        cli.get_context()
    assert e.value.status_code == 401


@pytest.mark.parametrize("kwargs, name", [
    ({"password": "p", "url_client": "c"}, "ZEENDOC_LOGIN"),
    ({"login": "l", "url_client": "c"}, "ZEENDOC_PASSWORD"),
    ({"login": "l", "password": "p"}, "ZEENDOC_URL_CLIENT"),
])
def test_missing_credential_is_named_never_read_from_env(monkeypatch, kwargs, name):
    from oto.tools.common.credentials import MissingCredential
    for var in ("ZEENDOC_LOGIN", "ZEENDOC_PASSWORD", "ZEENDOC_URL_CLIENT"):
        monkeypatch.setenv(var, "from_env")
    with pytest.raises(MissingCredential) as e:
        zc.ZeendocClient(**kwargs)
    assert e.value.name == name


@pytest.mark.parametrize("bad", ["cab/../x", "a b", "x" * 65, "cab?x=1"])
def test_url_client_and_binder_cannot_reshape_the_url(capture, bad):
    with pytest.raises(ValueError):
        zc.ZeendocClient("l", "p", bad)
    with pytest.raises(ValueError):
        zc.ZeendocClient("l", "p", "cab_1").count_documents(bad)
    assert capture["calls"] == []


# --- recherche ----------------------------------------------------------------

def test_criteria_get_one_id_each_and_map_to_the_api(capture, cli):
    capture["responses"].append(_Resp(200, {"nbDocs": 3}))
    cli.count_documents("coll_2", [
        {"field": "custom_t2", "operator": "EQUALS", "value": "ACME"},
        {"field": "custom_d4", "operator": "BETWEEN", "start": "2026-01-01", "end": "2026-03-31"},
        {"field": "custom_t5", "operator": "NULL"},
    ], match="any")
    method, url, kwargs = capture["calls"][0]
    assert (method, url) == ("POST", f"{ROOT}/api/v4/binders/coll_2/documents/count")
    assert kwargs["json"] == {"queryOperator": "OR", "indexList": [
        {"id": 1, "label": "custom_t2", "operator": "EQUALS", "value": "ACME"},
        {"id": 2, "label": "custom_d4", "operator": "BETWEEN",
         "startValue": "2026-01-01", "endValue": "2026-03-31"},
        {"id": 3, "label": "custom_t5", "operator": "NULL"},
    ]}


@pytest.mark.parametrize("criterion", [
    {"field": "custom_t2", "operator": "BEGIN WITH", "value": "A"},
    {"field": "custom_t2", "operator": "EQUALS"},
    {"field": "custom_t2", "operator": "BETWEEN", "value": "A"},
    {"field": "custom_t2", "operator": "NULL", "value": "A"},
    {"field": "custom t2", "operator": "EQUALS", "value": "A"},
    {"field": "custom_t2", "operator": "EQUALS", "value": True},
    {"field": "custom_t2", "operator": "EQUALS", "value": "A", "label": "x"},
])
def test_bad_criterion_is_refused_before_any_call(capture, cli, criterion):
    with pytest.raises(ValueError):
        cli.count_documents("coll_2", [criterion])
    assert capture["calls"] == []


def test_search_reads_every_field_of_the_binder_when_no_columns(capture, cli):
    capture["responses"] += [_Resp(200, CONTEXT), _Resp(200, {"nbDocs": 1, "document": [
        {"resId": 9, "properties": [], "indexes": {"customT2": ["ACME"], "typeId": [2]},
         "displayableIndexes": []}]})]
    found = cli.search_documents("coll_2", order_by="custom_f1", order="asc", offset=50)
    body = capture["calls"][1][2]["json"]
    assert body["wantedColumns"] == ";".join(list(zc.PROPERTIES) + ["custom_t2", "custom_f1"])
    assert (body["from"], body["nbResults"], body["orderCol"], body["order"]) == (50, 50, "custom_f1", "ASC")
    doc = found["document"][0]
    assert doc["indexes"] == {"custom_t2": ["ACME"], "type_id": [2]}
    assert doc["properties"] == {} and doc["displayableIndexes"] == {}


def test_search_past_the_end_has_an_empty_document_list(capture, cli):
    capture["responses"].append(_Resp(200, {"nbDocs": 3}))
    assert cli.search_documents("coll_2", columns=["custom_t2"])["document"] == []


def test_unknown_binder_is_refused_after_reading_the_context(capture, cli):
    capture["responses"].append(_Resp(200, CONTEXT))
    with pytest.raises(UpstreamHTTPError) as e:
        cli.search_documents("coll_9")
    assert e.value.status_code == 403


@pytest.mark.parametrize("kwargs", [{"limit": 51}, {"limit": 0}, {"offset": -1},
                                    {"order_by": "custom_f1", "order": "up"},
                                    {"match": "some"}, {"columns": []}])
def test_search_bounds_are_refused(capture, cli, kwargs):
    with pytest.raises(ValueError):
        cli.search_documents("coll_2", **kwargs)
    assert capture["calls"] == []


def test_non_json_answer_is_an_upstream_error(capture, cli):
    capture["responses"].append(_Resp(200, headers={"Content-Type": "text/html"},
                                      content=b"OPERATOR NOT KNOWN"))
    with pytest.raises(UpstreamHTTPError) as e:
        cli.count_documents("coll_2")
    assert "OPERATOR NOT KNOWN" in str(e.value)


# --- un document ----------------------------------------------------------------

def test_get_document_is_a_search_on_res_id(capture, cli):
    capture["responses"].append(_Resp(200, {"nbDocs": 1, "document": [{"resId": 9}]}))
    assert cli.get_document("coll_2", "9", columns=["custom_t2"])["resId"] == 9
    body = capture["calls"][0][2]["json"]
    assert body["indexList"] == [{"id": 1, "label": "Res_Id", "operator": "EQUALS", "value": "9"}]
    assert body["nbResults"] == 1


def test_get_document_not_found_is_a_404(capture, cli):
    capture["responses"].append(_Resp(200, {"nbDocs": 0}))
    with pytest.raises(UpstreamHTTPError) as e:
        cli.get_document("coll_2", 9, columns=["custom_t2"])
    assert e.value.status_code == 404


@pytest.mark.parametrize("bad", [0, -1, "x", True, 1.5])
def test_res_id_must_be_a_positive_integer(capture, cli, bad):
    with pytest.raises(ValueError):
        cli.get_document_text("coll_2", bad)


def test_text_page_and_its_decoding(capture, cli):
    capture["responses"].append(_Resp(200, headers={}, content="Siège\r\n".encode("cp1252")))
    assert cli.get_document_text("coll_2", 7) == "Siège\n"
    method, url, kwargs = capture["calls"][0]
    assert url == f"{ROOT}/Ihm/View/Get_Texte_Document.php"
    assert kwargs["params"] == {"Coll_Id": "coll_2", "Res_Id": 7, "Format": "Raw"}
    assert "pw-secret" not in str(kwargs) and kwargs["headers"]["Cookie"] == "ZeenDoc=abc123"


def test_text_of_an_unknown_document_is_a_404(capture, cli):
    capture["responses"].append(_Resp(200, headers={"Content-Type": "text/html"}, content=b"ERROR"))
    with pytest.raises(UpstreamHTTPError) as e:
        cli.get_document_text("coll_2", 7)
    assert e.value.status_code == 404


def test_download_pdf(capture, cli):
    capture["responses"].append(_Resp(200, headers={
        "Content-Disposition": 'attachment; filename="F 0001.Zeendoc.pdf"'}, content=b"%PDF-1.4 x"))
    f = cli.download_document("coll_2", 7)
    assert f == {"filename": "F 0001.Zeendoc.pdf", "content_type": "application/pdf",
                 "content": b"%PDF-1.4 x"}
    params = capture["calls"][0][2]["params"]
    assert (params["Id"], params["Version"], params["Action"]) == (7, "PDF", "DOWNLOAD")
    assert capture["calls"][0][2]["stream"] is True


def test_download_original_guesses_its_type_from_its_name(capture, cli):
    capture["responses"].append(_Resp(200, headers={
        "Content-Disposition": 'attachment; filename="scan.jpg"'}, content=b"\xff\xd8"))
    assert cli.download_document("coll_2", 7, "original")["content_type"] == "image/jpeg"


def test_download_of_a_document_without_right_is_a_404_not_a_followed_redirect(capture, cli):
    capture["responses"].append(_Resp(302, headers={
        "Location": "/cab_1/Ihm/index.php?Coll_Id=coll_2&Module=Account&page=no_right"}))
    with pytest.raises(UpstreamHTTPError) as e:
        cli.download_document("coll_2", 7)
    assert e.value.status_code == 404 and len(capture["calls"]) == 1


def test_download_that_is_not_a_pdf_is_an_upstream_error(capture, cli):
    capture["responses"].append(_Resp(200, headers={}, content=b"<html>form</html>"))
    with pytest.raises(UpstreamHTTPError) as e:
        cli.download_document("coll_2", 7)
    assert e.value.status_code == 502


def test_download_is_capped(capture, cli, monkeypatch):
    monkeypatch.setattr(zc, "MAX_FILE_BYTES", 4)
    capture["responses"].append(_Resp(200, headers={}, content=b"%PDF-1.4"))
    with pytest.raises(UpstreamHTTPError) as e:
        cli.download_document("coll_2", 7)
    assert e.value.status_code == 413


def test_unknown_version_is_refused(capture, cli):
    with pytest.raises(ValueError):
        cli.download_document("coll_2", 7, "signed")


# --- champs, transport -------------------------------------------------------

def test_field_endpoints(capture, cli):
    cli.list_field_choices("coll_2", "custom_n30")
    cli.suggest_field_values("coll_2", "custom_t2", "pig")
    assert [c[1] for c in capture["calls"]] == [
        f"{ROOT}/api/v4/binders/coll_2/fields/custom_n30/item-list",
        f"{ROOT}/api/v4/binders/coll_2/fields/custom_t2/autocomplete-search"]
    assert capture["calls"][1][2]["params"] == {"term": "pig"}


def test_503_is_retried_then_succeeds(capture, cli):
    capture["responses"] += [_Resp(503), _Resp(200, CONTEXT)]
    assert cli.probe() == CONTEXT


def test_500_is_not_retried(capture, cli):
    capture["responses"].append(_Resp(500, {"message": "unexpected_error_during_search"}))
    with pytest.raises(UpstreamHTTPError):
        cli.count_documents("coll_2")
    assert len(capture["calls"]) == 1


def test_retries_are_bounded(capture, cli):
    capture["responses"] += [_Resp(429)] * zc.MAX_ATTEMPTS
    with pytest.raises(UpstreamHTTPError) as e:
        cli.get_context()
    assert e.value.status_code == 429 and len(capture["calls"]) == zc.MAX_ATTEMPTS


def test_redirect_is_refused(capture, cli):
    capture["responses"].append(_Resp(302, headers={"Location": "https://evil.example/x"}))
    with pytest.raises(RedirectRefused):
        cli.get_context()
    assert len(capture["calls"]) == 1
