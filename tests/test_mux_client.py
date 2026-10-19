"""Contract of the Mux Video client (Basic `token_id:token_secret`; assets and
direct uploads).

Mocks `requests.Session.request`: paths, query and body as in the vendor's API
reference, the Basic header and never a secret in the query, the timeout, the
new asset's settings, local refusals.
"""
from __future__ import annotations

import pytest

from oto.tools.common.credentials import MissingCredential
from oto.tools.common.errors import UpstreamHTTPError
from oto.tools.mux import client as mx


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

    monkeypatch.setattr(mx.requests.Session, "request", fake_request)
    return seen


@pytest.fixture()
def cli():
    return mx.MuxClient(token_id="TOKEN_ID", token_secret="TOKEN_SECRET")


def test_both_fields_required():
    with pytest.raises(MissingCredential):
        mx.MuxClient(token_id="x", token_secret=None)
    with pytest.raises(MissingCredential):
        mx.MuxClient(token_id=None, token_secret="y")


def test_basic_auth_in_header_never_in_query(cli, capture):
    cli.list_assets(limit=5)
    assert cli.session.headers["Authorization"] == "Basic " + mx.basic_signature("TOKEN_ID", "TOKEN_SECRET")
    assert mx.basic_signature("TOKEN_ID", "TOKEN_SECRET") == "VE9LRU5fSUQ6VE9LRU5fU0VDUkVU"
    assert "TOKEN_SECRET" not in capture["url"]
    assert all("TOKEN_SECRET" not in str(v) for v in (capture["kwargs"].get("params") or {}).values())
    assert capture["kwargs"]["timeout"] == mx._HTTP_TIMEOUT


@pytest.mark.parametrize("call,method,path", [
    (lambda c: c.probe(), "GET", "/video/v1/assets"),
    (lambda c: c.list_assets(), "GET", "/video/v1/assets"),
    (lambda c: c.get_asset("abc123"), "GET", "/video/v1/assets/abc123"),
    (lambda c: c.get_upload("up456"), "GET", "/video/v1/uploads/up456"),
    (lambda c: c.create_upload(), "POST", "/video/v1/uploads"),
    (lambda c: c.create_asset("https://files.example/film.mp4"), "POST", "/video/v1/assets"),
])
def test_paths(cli, capture, call, method, path):
    call(cli)
    assert capture["method"] == method
    assert capture["url"] == mx.BASE_URL + path


def test_list_assets_params(cli, capture):
    cli.list_assets(limit=10, cursor="cur", upload_id="up456")
    assert capture["kwargs"]["params"] == {"limit": 10, "cursor": "cur", "upload_id": "up456"}
    with pytest.raises(ValueError):
        cli.list_assets(limit=0)


def test_create_upload_body(cli, capture):
    cli.create_upload(cors_origin="*", video_quality="plus", max_resolution_tier="1440p",
                      passthrough="film-1", title="A film")
    assert capture["kwargs"]["json"] == {
        "new_asset_settings": {"playback_policy": ["public"], "video_quality": "plus",
                               "max_resolution_tier": "1440p", "passthrough": "film-1",
                               "meta": {"title": "A film"}},
        "cors_origin": "*",
    }


def test_create_upload_defaults_to_public_playback(cli, capture):
    cli.create_upload()
    assert capture["kwargs"]["json"] == {"new_asset_settings": {"playback_policy": ["public"]}}


def test_create_asset_body(cli, capture):
    cli.create_asset("https://files.example/film.mp4", playback_policy="signed", test=True)
    assert capture["kwargs"]["json"] == {"inputs": [{"url": "https://files.example/film.mp4"}],
                                         "playback_policy": ["signed"], "test": True}


@pytest.mark.parametrize("kwargs", [
    {"playback_policy": "private"},
    {"video_quality": "ultra"},
    {"max_resolution_tier": "4k"},
    {"passthrough": "x" * 256},
    {"timeout": 10},
])
def test_create_upload_refusals(cli, kwargs):
    with pytest.raises(ValueError):
        cli.create_upload(**kwargs)


@pytest.mark.parametrize("bad", ["http://files.example/a.mp4", "file:///etc/passwd", ""])
def test_create_asset_needs_https(cli, bad):
    with pytest.raises(ValueError):
        cli.create_asset(bad)


@pytest.mark.parametrize("bad", ["../uploads", "a/b", "", None])
def test_ids_cannot_leave_the_path(cli, bad):
    with pytest.raises(ValueError):
        cli.get_asset(bad)


def test_upstream_error_is_typed(cli, capture):
    capture["responses"].append(_Resp(401, body={"error": {"type": "unauthorized"}}))
    with pytest.raises(UpstreamHTTPError) as e:
        cli.get_asset("abc123")
    assert e.value.status_code == 401
