"""Contrat du client Apify (v2, Bearer, store/actors/runs/datasets).

Mocke `requests.Session.request` : vérifie surtout deux pièges — la forme d'URL de
l'identifiant d'actor (`user/name` → `user~name`) et le passage des garde-fous de
coût en QUERY (pas dans le corps, qui est l'input de l'actor).
"""
from __future__ import annotations

import pytest

from oto.tools.apify import client as ap
from oto.tools.common.errors import UpstreamHTTPError


class _Resp:
    def __init__(self, status_code: int, body):
        self.status_code = status_code
        self._body = body
        self.content = b"x"
        self.text = str(body)
        self.headers = {}

    def json(self):
        return self._body


@pytest.fixture()
def capture(monkeypatch):
    seen = {}

    def fake_request(self, method, url, **kwargs):
        seen.update(method=method, url=url, kwargs=kwargs)
        return _Resp(200, {"data": {"id": "run-1"}})

    monkeypatch.setattr(ap.requests.Session, "request", fake_request)
    return seen


def _client():
    return ap.ApifyClient(api_key="apify_api_test")


def test_auth_header_is_bearer():
    assert _client().session.headers["Authorization"] == "Bearer apify_api_test"


def test_store_search_params(capture):
    _client().store_search(search="google maps", limit=5)

    assert capture["method"] == "GET"
    assert capture["url"] == "https://api.apify.com/v2/store"
    assert capture["kwargs"]["params"] == {"search": "google maps", "limit": 5}


def test_actor_slug_is_converted_to_tilde(capture):
    """Le Store affiche `apify/x`, l'API attend `apify~x` — sinon 404."""
    _client().actor("apify/website-content-crawler")

    assert capture["url"].endswith("/actors/apify~website-content-crawler")


def test_run_sync_sends_input_as_body_and_guards_as_query(capture):
    _client().run_sync_dataset_items(
        "apify/google-maps-scraper",
        run_input={"searchStringsArray": ["boulangerie Marseille"]},
        max_items=20, fields=["title", "url"],
    )

    assert capture["method"] == "POST"
    assert capture["url"].endswith(
        "/actors/apify~google-maps-scraper/run-sync-get-dataset-items")
    assert capture["kwargs"]["json"] == {"searchStringsArray": ["boulangerie Marseille"]}
    assert capture["kwargs"]["params"] == {"maxItems": 20, "fields": "title,url"}


def test_run_sync_input_defaults_to_empty_object(capture):
    """Un POST sans corps ferait échouer l'actor : `{}` est le neutre attendu."""
    _client().run_sync_dataset_items("apify/x")

    assert capture["kwargs"]["json"] == {}


def test_run_and_status(capture):
    _client().run("apify/x", run_input={"a": 1}, timeout_secs=120, memory_mbytes=2048)
    assert capture["url"].endswith("/actors/apify~x/runs")
    assert capture["kwargs"]["params"] == {"timeout": 120, "memory": 2048}

    _client().run_status("run-1", wait_for_finish=10)
    assert capture["method"] == "GET"
    assert capture["url"].endswith("/actor-runs/run-1")
    assert capture["kwargs"]["params"] == {"waitForFinish": 10}


def test_abort_run(capture):
    _client().abort_run("run-1", gracefully=True)

    assert capture["method"] == "POST"
    assert capture["url"].endswith("/actor-runs/run-1/abort")
    assert capture["kwargs"]["params"] == {"gracefully": "true"}


def test_dataset_items_projection(capture):
    _client().dataset_items("ds-1", limit=100, fields=["title"], omit=["html"], clean=True)

    assert capture["url"].endswith("/datasets/ds-1/items")
    assert capture["kwargs"]["params"] == {
        "limit": 100, "fields": "title", "omit": "html", "clean": "true"}


def test_http_error_is_typed(monkeypatch):
    monkeypatch.setattr(ap.requests.Session, "request",
                        lambda self, *a, **k: _Resp(404, {"error": {"type": "record-not-found"}}))

    with pytest.raises(UpstreamHTTPError) as e:
        _client().run_status("nope")
    assert e.value.status_code == 404


# --- reprises : 429 (et 502/503/504 en lecture), jamais un départ ambigu ---------

@pytest.fixture()
def file_de_reponses(monkeypatch):
    """`Session.request` rend, dans l'ordre, les réponses de `reponses` (posées par le
    test) ; `envois` compte les envois, `attentes` les pauses demandées."""
    etat = {"reponses": [], "envois": [], "attentes": []}

    def fake_request(self, method, url, **kwargs):
        etat["envois"].append((method, url))
        return etat["reponses"].pop(0)

    monkeypatch.setattr(ap.requests.Session, "request", fake_request)
    monkeypatch.setattr(ap, "_sleep", etat["attentes"].append)
    return etat


def _r429(retry_after=None):
    r = _Resp(429, {"error": {"type": "rate-limit-exceeded"}})
    if retry_after is not None:
        r.headers = {"Retry-After": str(retry_after)}
    return r


@pytest.mark.parametrize("appel", [
    lambda c: c.run_status("run-1"),
    lambda c: c.dataset_items("ds-1"),
    lambda c: c.actor("apify/x"),
    lambda c: c.store_search("maps"),
    lambda c: c.actors(),
    lambda c: c.abort_run("run-1"),
    lambda c: c.run("apify/x"),
    lambda c: c.run_sync_dataset_items("apify/x"),
])
def test_a_429_is_retried_then_succeeds(file_de_reponses, appel):
    """Un 429 est refusé AVANT tout traitement : le rejouer est sûr, départ compris."""
    file_de_reponses["reponses"] = [_r429(), _r429(), _Resp(200, {"data": {"id": "run-1"}})]
    assert appel(_client()) == {"data": {"id": "run-1"}}
    assert len(file_de_reponses["envois"]) == 3
    assert len(file_de_reponses["attentes"]) == 2


def test_the_backoff_doubles_from_half_a_second(file_de_reponses):
    """Le backoff documenté par Apify : entre le délai et son double, le délai doublant
    depuis 500 ms."""
    file_de_reponses["reponses"] = [_r429(), _r429(), _r429(), _Resp(200, {})]
    _client().run_status("run-1")
    a, b, c = file_de_reponses["attentes"]
    assert 0.5 <= a <= 1.0 and 1.0 <= b <= 2.0 and 2.0 <= c <= 4.0


def test_a_short_retry_after_is_followed(file_de_reponses):
    file_de_reponses["reponses"] = [_r429(retry_after=3), _Resp(200, {})]
    _client().dataset_items("ds-1")
    assert file_de_reponses["attentes"] == [3.0]


def test_a_long_retry_after_is_not_slept_away(file_de_reponses):
    """Une attente qu'on ne peut pas tenir revient à l'appelant, nommée — jamais dormie."""
    file_de_reponses["reponses"] = [_r429(retry_after=120)]
    with pytest.raises(UpstreamHTTPError) as e:
        _client().run_status("run-1")
    assert e.value.status_code == 429 and e.value.retry_after == 120.0
    assert file_de_reponses["attentes"] == [] and len(file_de_reponses["envois"]) == 1


def test_it_gives_up_after_max_retries(file_de_reponses):
    file_de_reponses["reponses"] = [_r429() for _ in range(ap.MAX_RETRIES + 1)]
    with pytest.raises(UpstreamHTTPError) as e:
        _client().run_status("run-1")
    assert e.value.status_code == 429
    assert len(file_de_reponses["envois"]) == ap.MAX_RETRIES + 1 == 4
    assert len(file_de_reponses["attentes"]) == ap.MAX_RETRIES


@pytest.mark.parametrize("status", [502, 503, 504])
def test_a_gateway_error_is_retried_on_a_read(file_de_reponses, status):
    file_de_reponses["reponses"] = [_Resp(status, "bad gateway"), _Resp(200, [{"a": 1}])]
    assert _client().dataset_items("ds-1") == [{"a": 1}]
    assert len(file_de_reponses["envois"]) == 2


@pytest.mark.parametrize("depart", [
    lambda c: c.run("apify/x"),
    lambda c: c.run_sync_dataset_items("apify/x"),
])
@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_a_start_is_never_replayed_on_an_ambiguous_error(file_de_reponses, depart, status):
    """Un 5xx sur un départ ne dit pas si le run est parti, et Apify n'offre aucune clé
    d'idempotence : le rejouer pourrait lancer — et facturer — un second run."""
    file_de_reponses["reponses"] = [_Resp(status, "upstream error")]
    with pytest.raises(UpstreamHTTPError) as e:
        depart(_client())
    assert e.value.status_code == status
    assert len(file_de_reponses["envois"]) == 1 and file_de_reponses["attentes"] == []


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 408, 500])
def test_a_final_refusal_is_never_retried(file_de_reponses, status):
    file_de_reponses["reponses"] = [_Resp(status, {"error": {"type": "x"}})]
    with pytest.raises(UpstreamHTTPError):
        _client().run_status("run-1")
    assert len(file_de_reponses["envois"]) == 1
