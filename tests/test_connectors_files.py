"""Un fichier rendu côté Python : `oto.connectors.files` au-delà des cas communs.

Les cas communs (`tests/test_file_cases.py`) disent ce que rendent les deux côtés ; ici, ce que seul le transport de la
lib peut montrer : l'authentification posée ou non sur le téléchargement, une borne tenue sans lire, une adresse interne
refusée par la garde, le délai de bout en bout, l'adresse absente de toute erreur, et la forme de `FileOut`.
"""
from __future__ import annotations

import socket

import pytest
import requests

import files_fake
from oto.connectors import files
from oto.connectors.files import MAX_BYTES, FileOut, FileOutputError, file_output
from oto.tools.common import url_guard

BASE_URL = "https://api.example.test/v1"
DECLARED = {
    "demo": {
        "get_recording": {"file": {"from": "body", "types": {"mp3": ["audio/mpeg"]},
                                   "name": {"header": "Content-Disposition", "template": "recording-{id}.mp3"},
                                   "max_bytes": 16}, "timeout_s": 30},
        "get_call_recording": {"file": {"from": "url", "path": "recording", "auth": "none", "types": {"mp3": ["audio/mpeg"]},
                                        "name": {"template": "call-{id}.mp3"}, "max_bytes": 16}, "timeout_s": 30},
        "get_export": {"file": {"from": "url", "path": "url", "auth": "account", "types": {"csv": ["text/csv"]},
                                "name": {"template": "export-{id}.csv"}, "max_bytes": 16}, "timeout_s": 30},
        "get_attachment": {"file": {"from": "base64", "path": "data", "types": {"pdf": ["application/pdf"]},
                                    "name": {"path": "filename", "template": "attachment-{id}.pdf"}, "max_bytes": 16},
                           "timeout_s": 30},
        "list_calls": {"cost": {"per": "request"}},
    }
}
SIGNED = "https://files.example.test/r/1.mp3?signature=s3cr3t-signature"
AUDIO = {"status": 200, "headers": {"Content-Type": "audio/mpeg"}, "text": "ID3-call"}


@pytest.fixture(autouse=True)
def _declared_and_resolver(monkeypatch):
    monkeypatch.setattr(files, "DECLARED", DECLARED)
    monkeypatch.setattr(url_guard.socket, "getaddrinfo", files_fake.resolve_publicly)


def _json(value) -> dict:
    return {"status": 200, "headers": {"Content-Type": "application/json"}, "json": value}


def _call(function, answer, download=None, session_auth=None, args=None):
    transport = files_fake.FakeTransport(download)
    session = files_fake.session(transport)
    if session_auth is not None:
        session.auth = session_auth
    result = file_output("demo", function, answer=files_fake.answer(answer), args=args or {"id": "x-1"}, session=session,
                         base_url=BASE_URL)
    return result, transport


# --- L'authentification d'un téléchargement -------------------------------------------------------------------------


def test_a_signed_address_is_downloaded_without_any_authentication_of_the_client():
    result, transport = _call("get_call_recording", _json({"recording": SIGNED}), AUDIO, session_auth=("user", "password"))
    request, kwargs = transport.requests[0]
    assert "Authorization" not in request.headers
    assert "Cookie" not in request.headers
    assert kwargs["timeout"] <= 30
    assert result == FileOut(name="call-x-1.mp3", content=b"ID3-call", mime="audio/mpeg")


def test_the_account_authentication_goes_to_the_api_origin_only():
    result, transport = _call("get_export", _json({"url": "https://api.example.test/exports/1"}),
                              {"status": 200, "headers": {"Content-Type": "text/csv"}, "text": "a,b\n"})
    assert transport.requests[0][0].headers["Authorization"] == files_fake.TOKEN
    assert result.name == "export-x-1.csv" and result.mime == "text/csv"
    with pytest.raises(FileOutputError) as raised:
        _call("get_export", _json({"url": "https://api.example.test.evil.test/exports/1"}))
    assert raised.value.code == "file_foreign_origin"


@pytest.mark.parametrize("function, address", [("get_call_recording", SIGNED), ("get_export", "https://api.example.test/exports/1")],
                         ids=["none", "account"])
def test_a_redirect_is_never_followed(function, address):
    transport = files_fake.FakeTransport({"status": 302, "headers": {"Location": "https://storage.example.test/r/1"}, "text": ""})
    field = "recording" if function == "get_call_recording" else "url"
    with pytest.raises(FileOutputError) as raised:
        file_output("demo", function, answer=files_fake.answer(_json({field: address})), args={"id": "x-1"},
                    session=files_fake.session(transport), base_url=BASE_URL)
    assert raised.value.code == "file_download_refused"
    assert len(transport.requests) == 1


def test_the_default_port_is_the_same_origin():
    _, transport = _call("get_export", _json({"url": "https://api.example.test:443/exports/1"}),
                         {"status": 200, "headers": {}, "text": "a,b\n"})
    assert transport.requests[0][0].headers["Authorization"] == files_fake.TOKEN


# --- Les bornes ---------------------------------------------------------------------------------------------------


def test_a_content_length_beyond_the_bound_refuses_before_reading():
    response = files_fake.answer({"status": 200, "headers": {"Content-Type": "audio/mpeg", "Content-Length": "17"},
                                  "text": "ID3-0123456789abc"})
    with pytest.raises(FileOutputError) as raised:
        file_output("demo", "get_recording", answer=response, args={"id": "x-1"}, session=requests.Session(), base_url=BASE_URL)
    assert raised.value.code == "file_too_large"
    assert response.raw._fp.read_bytes == 0


def test_a_body_beyond_the_bound_stops_at_the_first_byte_too_many():
    response = files_fake.answer({"status": 200, "headers": {"Content-Type": "audio/mpeg"}, "text": "x" * 100_000})
    with pytest.raises(FileOutputError) as raised:
        file_output("demo", "get_recording", answer=response, args={"id": "x-1"}, session=requests.Session(), base_url=BASE_URL)
    assert raised.value.code == "file_too_large"
    assert response.raw._fp.read_bytes < 100_000


def test_a_name_is_reduced_to_255_characters_without_control_characters_and_keeps_its_extension():
    long = "a" * 300 + "\x00\x1f\x7f.pdf"
    result, _ = _call("get_attachment", _json({"data": "JVBERi0xLjQ=", "filename": long}))
    assert len(result.name) == 255 and result.name.endswith(".pdf") and set(result.name[:-4]) == {"a"}


def test_file_out_holds_at_most_50_mb_of_bytes():
    assert MAX_BYTES == 52_428_800
    FileOut(name="a.mp3", content=b"x", mime="audio/mpeg")
    with pytest.raises(ValueError):
        FileOut(name="a.mp3", content=b"x" * (MAX_BYTES + 1), mime="audio/mpeg")
    with pytest.raises(TypeError):
        FileOut(name="a.mp3", content="text", mime="audio/mpeg")


# --- La garde de l'adresse ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("address", ["https://127.0.0.1/r/1.mp3", "https://[::1]/r/1.mp3", "https://169.254.169.254/latest"])
def test_an_internal_address_is_refused_without_download(address):
    with pytest.raises(FileOutputError) as raised:
        _call("get_call_recording", _json({"recording": address}))
    assert raised.value.code == "file_download_refused"


def test_a_host_that_resolves_to_an_internal_address_is_refused_without_download(monkeypatch):
    monkeypatch.setattr(url_guard.socket, "getaddrinfo",
                        lambda host, port, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.7", port))])
    with pytest.raises(FileOutputError) as raised:
        _call("get_call_recording", _json({"recording": SIGNED}))
    assert raised.value.code == "file_download_refused"
    assert "files.example.test" not in str(raised.value) and "s3cr3t" not in str(raised.value)


def test_a_transport_failure_says_no_address():
    class Unreachable(files_fake.FakeTransport):
        def send(self, request, **kwargs):
            raise requests.ConnectionError(f"cannot reach {request.url}")

    session = files_fake.session(Unreachable())
    with pytest.raises(FileOutputError) as raised:
        file_output("demo", "get_call_recording", answer=files_fake.answer(_json({"recording": SIGNED})), args={"id": "x-1"},
                    session=session, base_url=BASE_URL)
    assert raised.value.code == "file_download_refused"
    assert "s3cr3t" not in str(raised.value) and raised.value.__context__ is None


# --- Le délai -----------------------------------------------------------------------------------------------------


class _Clock:
    """Une horloge qui avance de `step` secondes à chaque lecture."""

    def __init__(self, step: float):
        self.now, self.step = 0.0, step

    def monotonic(self) -> float:
        self.now += self.step
        return self.now


def test_the_timeout_of_the_function_holds_end_to_end(monkeypatch):
    monkeypatch.setattr(files, "time", _Clock(step=20.0))
    with pytest.raises(requests.Timeout) as raised:
        _call("get_call_recording", _json({"recording": SIGNED}), AUDIO)
    assert "30 s" in str(raised.value)
    assert "s3cr3t" not in str(raised.value) and raised.value.__context__ is None


# --- Ce que file_output exige ---------------------------------------------------------------------------------------


def test_a_function_without_a_file_is_a_mistake_of_the_caller():
    with pytest.raises(LookupError):
        _call("list_calls", _json({}))
    with pytest.raises(LookupError):
        _call("nope", _json({}))


def test_a_failed_answer_is_a_mistake_of_the_caller():
    with pytest.raises(ValueError, match="successful answer"):
        _call("get_recording", {"status": 404, "headers": {}, "text": "Not found"})
