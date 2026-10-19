"""Contrat du client FullEnrich (surface async submit/fetch, signal #252).

Mocke `requests.post`/`requests.get` : on vérifie le payload bulk émis et le
parse du retour — AUCUN polling in-process (le polling appartient à l'appelant).
"""
from __future__ import annotations

import pytest

from oto.tools.common.errors import UpstreamHTTPError
from oto.tools.fullenrich import client as fe


class _Resp:
    def __init__(self, status_code: int, body: dict, headers: dict | None = None):
        self.status_code = status_code
        self._body = body
        self.text = str(body)
        self.headers = headers or {}

    def json(self):
        return self._body


def test_submit_bulk_payload(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, json=json, timeout=timeout)
        return _Resp(200, {"enrichment_id": "abc123"})

    monkeypatch.setattr(fe.requests, "post", fake_post)
    c = fe.FullenrichClient(api_key="k")
    eid = c.submit([
        {"first_name": "Mathias", "last_name": "Mimouna",
         "linkedin_slug": "mathias-mimouna-240b1212b", "company_name": "Acme"},
        {"first_name": "Carole", "last_name": "Rosenberger", "domain": "acme.fr"},
    ])

    assert eid == "abc123"
    assert captured["url"].endswith("/contact/enrich/bulk")
    assert captured["timeout"] == 30
    data = captured["json"]["data"]
    assert len(data) == 2
    assert data[0]["linkedin_url"] == "https://www.linkedin.com/in/mathias-mimouna-240b1212b/"
    assert data[0]["custom"] == {"slug": "mathias-mimouna-240b1212b"}
    assert data[0]["company_name"] == "Acme"
    assert data[0]["enrich_fields"] == fe.DEFAULT_ENRICH_FIELDS
    assert "linkedin_url" not in data[1]
    assert data[1]["domain"] == "acme.fr"


def test_submit_guards():
    c = fe.FullenrichClient(api_key="k")
    with pytest.raises(ValueError, match="no contact"):
        c.submit([])
    with pytest.raises(ValueError, match="cap"):
        c.submit([{"first_name": "A", "last_name": "B"}] * (fe.MAX_CONTACTS_PER_JOB + 1))
    with pytest.raises(ValueError, match="first_name and last_name"):
        c.submit([{"first_name": "A"}])
    with pytest.raises(ValueError, match="linkedin_slug OR domain"):
        c.submit([{"first_name": "A", "last_name": "B"}])


def test_fetch_in_progress(monkeypatch):
    monkeypatch.setattr(fe.requests, "get",
                        lambda url, headers=None, timeout=None: _Resp(200, {"status": "IN_PROGRESS"}))
    out = FullenrichClientFixture().fetch("abc123")
    assert out == {"status": "IN_PROGRESS", "profiles": None, "cost_credits": None}


def test_fetch_in_progress_reports_the_cost_the_upstream_already_declares(monkeypatch):
    monkeypatch.setattr(fe.requests, "get",
                        lambda url, headers=None, timeout=None: _Resp(
                            200, {"status": "IN_PROGRESS", "cost": {"credits": 0}}))
    out = FullenrichClientFixture().fetch("abc123")
    assert out == {"status": "IN_PROGRESS", "profiles": None, "cost_credits": 0}


def test_fetch_finished_reports_the_credits_fullenrich_deducted(monkeypatch):
    """`cost_credits` est le `cost.credits` de l'amont, tel quel — jamais recalculé
    depuis les valeurs trouvées (le barème est celui de FullEnrich)."""
    body = {"status": "FINISHED", "cost": {"credits": 14},
            "data": [{"custom": {"slug": "a-b"},
                      "contact_info": {"phones": [{"number": "+33600000000"}],
                                       "work_emails": [{"email": "a@b.fr"}]}}]}
    monkeypatch.setattr(fe.requests, "get",
                        lambda url, headers=None, timeout=None: _Resp(200, body))
    out = FullenrichClientFixture().fetch("abc123")
    assert out["status"] == "FINISHED"
    assert out["cost_credits"] == 14
    assert len(out["profiles"]) == 1


@pytest.mark.parametrize("cost", [
    None, {}, {"credits": None}, {"credits": "14"}, {"credits": 1.5},
    {"credits": -1}, {"credits": True}, 14, "14",
])
def test_fetch_a_malformed_or_missing_cost_is_none_never_a_guess(monkeypatch, cost):
    body = {"status": "FINISHED", "data": []}
    if cost is not None:
        body["cost"] = cost
    monkeypatch.setattr(fe.requests, "get",
                        lambda url, headers=None, timeout=None: _Resp(200, body))
    out = FullenrichClientFixture().fetch("abc123")
    assert out["status"] == "FINISHED"
    assert out["cost_credits"] is None


def test_fetch_finished_parses_profiles(monkeypatch):
    body = {
        "status": "FINISHED",
        "data": [
            {
                "custom": {"slug": "mathias-mimouna-240b1212b"},
                "profile": {"first_name": "Mathias", "last_name": "Mimouna",
                            "location": {"city": "Paris", "country": "France"}},
                "contact_info": {"phones": [{"number": "+33600000000"}],
                                 "work_emails": [{"email": "m@acme.fr"}]},
            },
            {"custom": {"slug": "carole-rosenberger-82a8ba27a"}, "contact_info": {}},
        ],
    }
    monkeypatch.setattr(fe.requests, "get",
                        lambda url, headers=None, timeout=None: _Resp(200, body))
    out = FullenrichClientFixture().fetch("abc123")
    assert out["status"] == "FINISHED"
    p0, p1 = out["profiles"]
    assert p0.found and p0.phones == ["+33600000000"] and p0.linkedin_slug == "mathias-mimouna-240b1212b"
    assert p0.location == "Paris, France"
    assert not p1.found and p1.linkedin_slug == "carole-rosenberger-82a8ba27a"


def test_fetch_credits_insufficient(monkeypatch):
    monkeypatch.setattr(fe.requests, "get",
                        lambda url, headers=None, timeout=None: _Resp(200, {"status": "CREDITS_INSUFFICIENT"}))
    with pytest.raises(RuntimeError, match="insufficient credits"):
        FullenrichClientFixture().fetch("abc123")


def FullenrichClientFixture() -> fe.FullenrichClient:
    return fe.FullenrichClient(api_key="k")


# --- Réponses d'erreur HTTP documentées du GET (signaux #990, #1027-#1029) ------------
# L'API répond `400 {"code": "error.enrichment.in_progress", …}` quand un job n'est pas
# prêt (doc v2 de `GET /contact/enrich/bulk/{id}`). Levée en RuntimeError générique,
# cette réponse NORMALE devenait « Erreur interne du serveur » côté agent, à chaque
# relevé, jusqu'à la fin du job — qu'il ne voyait donc jamais.

def _get(status_code, body):
    return lambda url, headers=None, timeout=None: _Resp(status_code, body)


def test_fetch_400_in_progress_est_un_job_en_cours_pas_une_erreur(monkeypatch):
    monkeypatch.setattr(fe.requests, "get", _get(400, {
        "code": "error.enrichment.in_progress",
        "message": "Enrichment not ready, try again in 30 seconds"}))
    out = FullenrichClientFixture().fetch("abc123")
    assert out == {"status": "IN_PROGRESS", "profiles": None, "cost_credits": None}


def test_fetch_404_not_found_est_un_statut_nomme(monkeypatch):
    monkeypatch.setattr(fe.requests, "get", _get(404, {
        "code": "error.enrichment.not_found", "message": "Enrichment ID not found"}))
    out = FullenrichClientFixture().fetch("abc123")
    assert out == {"status": fe.STATUS_NOT_FOUND, "profiles": None, "cost_credits": None}


def test_fetch_429_rate_limit_est_un_statut_nomme(monkeypatch):
    monkeypatch.setattr(fe.requests, "get", _get(429, {
        "code": "error.rate.limit", "message": "Too many requests. Try again in 1m"}))
    out = FullenrichClientFixture().fetch("abc123")
    assert out == {"status": "RATE_LIMIT", "profiles": None, "cost_credits": None}


def test_fetch_402_credits_insuffisants_comme_le_statut(monkeypatch):
    monkeypatch.setattr(fe.requests, "get", _get(402, {"status": "CREDITS_INSUFFICIENT"}))
    with pytest.raises(UpstreamHTTPError, match="insufficient credits") as exc:
        FullenrichClientFixture().fetch("abc123")
    assert exc.value.status_code == 402
    assert exc.value.body == fe._CREDITS_INSUFFISANTS


def test_fetch_un_autre_400_reste_une_erreur(monkeypatch):
    monkeypatch.setattr(fe.requests, "get", _get(400, {"code": "error.other", "message": "x"}))
    with pytest.raises(UpstreamHTTPError, match="fullenrich HTTP 400") as exc:
        FullenrichClientFixture().fetch("abc123")
    assert exc.value.body == {"code": "error.other", "message": "x"}


def test_fetch_un_corps_non_json_ne_masque_pas_le_code(monkeypatch):
    class _Brut(_Resp):
        def json(self):
            raise ValueError("pas du json")
    monkeypatch.setattr(fe.requests, "get",
                        lambda url, headers=None, timeout=None: _Brut(500, {}))
    with pytest.raises(UpstreamHTTPError, match="fullenrich HTTP 500"):
        FullenrichClientFixture().fetch("abc123")


# --- Erreur typée : statut, méthode, URL, Retry-After -----------------------------------
# Un appelant qui a réservé des crédits avant l'appel doit distinguer, sans lire le texte
# du message, un refus net (rien n'a été envoyé, ou 4xx autre que 408/429) d'un envoi
# ambigu. Le client lève `UpstreamHTTPError` sur toute réponse non 2xx, et `ValueError`
# avant tout envoi.

_CONTACT = {"first_name": "Ada", "last_name": "Lovelace", "domain": "example.org"}


def _poster(monkeypatch, status_code, body, response_headers=None):
    monkeypatch.setattr(fe.requests, "post", lambda url, headers=None, json=None, timeout=None:
                        _Resp(status_code, body, response_headers))


def test_submit_4xx_est_un_refus_type(monkeypatch):
    _poster(monkeypatch, 400, {"code": "error.enrichment.domain.empty", "message": "domain"})
    with pytest.raises(UpstreamHTTPError) as exc:
        FullenrichClientFixture().submit([_CONTACT])
    e = exc.value
    assert e.status_code == 400
    assert e.is_client_error and not e.is_server_error
    assert e.service == "fullenrich"
    assert e.method == "POST"
    assert e.url == f"{fe.FullenrichClient.BASE_URL}/contact/enrich/bulk"
    assert "?" not in e.url
    assert e.body == {"code": "error.enrichment.domain.empty", "message": "domain"}
    assert e.retry_after is None


def test_submit_402_garde_le_message_credits_avec_son_statut(monkeypatch):
    _poster(monkeypatch, 402, {"message": "payment required"})
    with pytest.raises(UpstreamHTTPError, match="insufficient credits") as exc:
        FullenrichClientFixture().submit([_CONTACT])
    assert exc.value.status_code == 402 and exc.value.method == "POST"


def test_fetch_5xx_est_une_erreur_serveur_typee(monkeypatch):
    monkeypatch.setattr(fe.requests, "get", _get(503, {"message": "unavailable"}))
    with pytest.raises(UpstreamHTTPError) as exc:
        FullenrichClientFixture().fetch("abc123")
    e = exc.value
    assert e.status_code == 503
    assert e.is_server_error and not e.is_client_error
    assert e.method == "GET"
    assert e.url == f"{fe.FullenrichClient.BASE_URL}/contact/enrich/bulk/abc123"


def test_submit_5xx_est_une_erreur_serveur_typee(monkeypatch):
    _poster(monkeypatch, 502, {"message": "bad gateway"})
    with pytest.raises(UpstreamHTTPError) as exc:
        FullenrichClientFixture().submit([_CONTACT])
    assert exc.value.status_code == 502 and exc.value.is_server_error
    assert exc.value.method == "POST"


def test_fetch_429_rate_limit_garde_son_statut_nomme_malgre_retry_after(monkeypatch):
    """Le comportement actuel est gardé : le 429 documenté du relevé reste le statut
    `RATE_LIMIT` (l'appelant repasse), il ne devient pas une erreur."""
    monkeypatch.setattr(fe.requests, "get", lambda url, headers=None, timeout=None: _Resp(
        429, {"code": "error.rate.limit", "message": "Too many requests"}, {"Retry-After": "30"}))
    out = FullenrichClientFixture().fetch("abc123")
    assert out == {"status": "RATE_LIMIT", "profiles": None, "cost_credits": None}


def test_submit_429_sort_avec_son_retry_after(monkeypatch):
    _poster(monkeypatch, 429, {"code": "error.rate.limit", "message": "Too many requests"},
            {"Retry-After": "30"})
    with pytest.raises(UpstreamHTTPError) as exc:
        FullenrichClientFixture().submit([_CONTACT])
    e = exc.value
    assert e.status_code == 429 and e.method == "POST"
    assert e.retry_after == 30.0


def test_fetch_un_autre_429_sort_avec_son_retry_after(monkeypatch):
    monkeypatch.setattr(fe.requests, "get", lambda url, headers=None, timeout=None: _Resp(
        429, {"code": "error.other"}, {"Retry-After": "12"}))
    with pytest.raises(UpstreamHTTPError) as exc:
        FullenrichClientFixture().fetch("abc123")
    assert exc.value.retry_after == 12.0 and exc.value.method == "GET"


def test_un_refus_avant_envoi_reste_une_valueerror_sans_appel_http(monkeypatch):
    def interdit(*a, **k):
        raise AssertionError("aucun appel HTTP attendu")
    monkeypatch.setattr(fe.requests, "post", interdit)
    with pytest.raises(ValueError) as exc:
        FullenrichClientFixture().submit([{"first_name": "Ada", "last_name": "Lovelace"}])
    assert not isinstance(exc.value, UpstreamHTTPError)
