"""`UpstreamHTTPError` : statut, méthode, URL assainie et `Retry-After` d'une réponse amont.

Un appelant qui réserve avant l'appel (un moteur de crédits) doit distinguer un refus net
d'un envoi ambigu sans lire le texte du message. Ces tests figent :

- l'assainissement de l'URL (ni query, ni fragment, ni userinfo : une clé d'API y passe) ;
- la lecture du `Retry-After` en secondes ;
- `raise_for_upstream`, qui remplit méthode et URL depuis `resp.request` (`requests`) ;
- la compatibilité du constructeur (méthode, URL et `retry_after` optionnels) ;
- les clients convertis, joués par le vrai chemin `requests` jusqu'à l'adaptateur HTTP,
  remplacé par une réponse simulée : aucun réseau.
"""
from __future__ import annotations

import uuid

import pytest
import requests

from oto.tools.common.errors import (
    UpstreamHTTPError,
    raise_for_upstream,
    retry_after_seconds,
    sanitize_url,
)


def _secret() -> str:
    return "k" + uuid.uuid4().hex


# --- sanitize_url ----------------------------------------------------------------------

@pytest.mark.parametrize("url, attendu", [
    ("https://api.example.org/v1/items", "https://api.example.org/v1/items"),
    ("https://api.example.org/v1/items?key=SECRET&q=1", "https://api.example.org/v1/items"),
    ("https://api.example.org/v1/items#SECRET", "https://api.example.org/v1/items"),
    ("https://user:SECRET@api.example.org/v1", "https://api.example.org/v1"),
    ("https://SECRET@api.example.org:8443/v1?x=1#y", "https://api.example.org:8443/v1"),
    ("http://[::1]:8080/p?SECRET", "http://[::1]:8080/p"),
    ("https://api.example.org", "https://api.example.org"),
    (None, None),
    ("", None),
])
def test_sanitize_url(url, attendu):
    assert sanitize_url(url) == attendu


def test_sanitize_url_ne_garde_aucun_secret():
    cle = _secret()
    propre = sanitize_url(f"https://{cle}:{cle}@h.example.org/a?key={cle}#{cle}")
    assert cle not in propre


# --- retry_after_seconds ---------------------------------------------------------------

class _Headers:
    def __init__(self, headers=None):
        if headers is not None:
            self.headers = headers


@pytest.mark.parametrize("headers, attendu", [
    ({"Retry-After": "30"}, 30.0),
    ({"Retry-After": "1.5"}, 1.5),
    ({"Retry-After": "-4"}, 0.0),
    ({"Retry-After": "inf"}, None),
    ({"Retry-After": "nan"}, None),
    ({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, None),
    ({"Retry-After": ""}, None),
    ({}, None),
    (None, None),
])
def test_retry_after_seconds(headers, attendu):
    assert retry_after_seconds(_Headers(headers)) == attendu


# --- constructeur ----------------------------------------------------------------------

def test_le_constructeur_d_avant_reste_valable():
    e = UpstreamHTTPError(404, "absent", service="folk")
    assert (e.status_code, e.body, e.service) == (404, "absent", "folk")
    assert e.method is None and e.url is None and e.retry_after is None
    assert str(e) == "folk HTTP 404: absent"
    assert e.is_client_error and not e.is_server_error
    assert str(UpstreamHTTPError(500)) == "HTTP 500: None"


def test_le_constructeur_assainit_l_url_et_normalise_la_methode():
    cle = _secret()
    e = UpstreamHTTPError(400, "x", method="post", url=f"https://h.example.org/p?key={cle}",
                          retry_after=3.0)
    assert e.method == "POST"
    assert e.url == "https://h.example.org/p"
    assert e.retry_after == 3.0
    assert cle not in str(e)


def test_un_rejet_de_debit_wordpress_garde_son_retry_after():
    from oto.tools.wordpress.client import WordPressRateLimited
    e = WordPressRateLimited(42.0)
    assert e.retry_after == 42.0 and e.status_code == 429


# --- raise_for_upstream ----------------------------------------------------------------

def _reponse(status: int, body: bytes = b'{"message": "refused"}', headers=None,
             method: str = "GET", url: str = "https://api.example.org/v1/x") -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    resp._content = body
    resp.headers.update(headers or {})
    resp.request = requests.Request(method, url).prepare()
    resp.url = resp.request.url
    return resp


def test_raise_for_upstream_ne_leve_rien_sous_400():
    raise_for_upstream(_reponse(200), service="s")
    raise_for_upstream(_reponse(302), service="s")


def test_raise_for_upstream_lit_la_requete_de_requests():
    cle = _secret()
    resp = _reponse(403, method="DELETE", url=f"https://api.example.org/v1/x?api_key={cle}")
    with pytest.raises(UpstreamHTTPError) as exc:
        raise_for_upstream(resp, service="s")
    e = exc.value
    assert e.status_code == 403 and e.body == {"message": "refused"}
    assert e.method == "DELETE"
    assert e.url == "https://api.example.org/v1/x"
    assert e.retry_after is None
    assert cle not in str(e)


def test_raise_for_upstream_lit_le_retry_after_d_un_429_seulement():
    with pytest.raises(UpstreamHTTPError) as exc:
        raise_for_upstream(_reponse(429, headers={"Retry-After": "20"}), service="s")
    assert exc.value.retry_after == 20.0
    with pytest.raises(UpstreamHTTPError) as exc:
        raise_for_upstream(_reponse(503, headers={"Retry-After": "20"}), service="s")
    assert exc.value.retry_after is None


def test_raise_for_upstream_sans_requete_connue():
    class _Nue:
        status_code = 500
        text = "boom"

        def json(self):
            raise ValueError

    with pytest.raises(UpstreamHTTPError) as exc:
        raise_for_upstream(_Nue(), service="s")
    assert exc.value.body == "boom"
    assert exc.value.method is None and exc.value.url is None


# --- clients convertis -----------------------------------------------------------------
# Chaque client levait une `Exception` ou une `RuntimeError` dont le statut ne se lisait
# que dans le texte. Joué par `requests` jusqu'à l'adaptateur, remplacé ici.

def _client_cases():
    from oto.tools.anthropic import AnthropicAdminClient
    from oto.tools.attio.client import AttioClient
    from oto.tools.ashby import AshbyClient
    from oto.tools.gemini import GeminiClient
    from oto.tools.greenhouse import GreenhouseClient
    from oto.tools.groq import GroqClient
    from oto.tools.lighton import LightOnClient
    from oto.tools.mistral import MistralClient
    from oto.tools.n8n import N8nClient
    from oto.tools.recruitee import RecruiteeClient
    from oto.tools.serper import SerperClient
    from oto.tools.topograph import TopographClient

    msg = [{"role": "user", "content": "x"}]
    return [
        ("anthropic", "GET", lambda k: AnthropicAdminClient(api_key=k).get_usage()),
        ("ashby", "POST", lambda k: AshbyClient(api_key=k).call("candidate.info", {})),
        ("attio", "GET", lambda k: AttioClient(api_key=k)._request(
            "GET", "objects/companies", params={"limit": 1})),
        ("gemini", "POST", lambda k: GeminiClient(api_key=k).chat(msg)),
        ("greenhouse", "GET", lambda k: GreenhouseClient(api_key=k).get_candidate(1)),
        ("groq", "POST", lambda k: GroqClient(api_key=k).chat(msg)),
        ("lighton", "GET", lambda k: LightOnClient(api_key=k).list_workspaces()),
        ("Mistral", "POST", lambda k: MistralClient(api_key=k).chat(msg)),
        ("n8n", "GET", lambda k: N8nClient(api_key=k, base_url="https://n8n.example.org")
         .get_workflow("1")),
        ("recruitee", "GET", lambda k: RecruiteeClient(api_token=k, company_id="c1")
         .get_candidate(1)),
        ("serper", "POST", lambda k: SerperClient(api_key=k).search("x")),
        ("topograph", "GET", lambda k: TopographClient(api_key=k).search("x")),
    ]


def _adaptateur(monkeypatch, status: int, headers=None):
    """Remplace l'envoi HTTP de `requests` : rend `status` avec la requête préparée."""
    envois = []

    def send(self, request, **kwargs):
        envois.append(request)
        resp = requests.Response()
        resp.status_code = status
        resp._content = b'{"message": "refused", "detail": "refused", "error": "refused"}'
        resp.headers["Content-Type"] = "application/json"
        resp.headers.update(headers or {})
        resp.request = request
        resp.url = request.url
        return resp

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    return envois


@pytest.mark.parametrize("service, methode, appel", _client_cases(),
                         ids=[c[0] for c in _client_cases()])
def test_un_client_converti_leve_une_erreur_typee(monkeypatch, service, methode, appel):
    envois = _adaptateur(monkeypatch, 403)
    cle = _secret()
    with pytest.raises(UpstreamHTTPError) as exc:
        appel(cle)
    e = exc.value
    assert len(envois) == 1
    assert e.status_code == 403 and e.is_client_error
    assert e.service == service
    assert e.method == methode
    assert e.url == sanitize_url(envois[0].url)
    assert "?" not in e.url and cle not in e.url
    assert "refused" in str(e.body)


def test_attio_un_429_sort_type_avec_son_retry_after(monkeypatch):
    from oto.tools.attio.client import AttioClient

    envois = _adaptateur(monkeypatch, 429, {"Retry-After": "7"})
    with pytest.raises(UpstreamHTTPError) as exc:
        AttioClient(api_key=_secret())._request("POST", "objects/companies/records", json={})
    e = exc.value
    assert len(envois) == 1
    assert e.status_code == 429 and e.retry_after == 7.0
    assert (e.service, e.method) == ("attio", "POST")
    assert e.url == "https://api.attio.com/v2/objects/companies/records"


def test_attio_un_corps_non_json_reste_du_texte_borne(monkeypatch):
    from oto.tools.attio.client import AttioClient

    def send(self, request, **kwargs):
        resp = requests.Response()
        resp.status_code = 503
        resp._content = b"<html>" + b"x" * 5000
        resp.request = request
        return resp

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    with pytest.raises(UpstreamHTTPError) as exc:
        AttioClient(api_key=_secret())._request("GET", "self")
    assert exc.value.status_code == 503 and exc.value.is_server_error
    assert isinstance(exc.value.body, str) and len(exc.value.body) == 2000


def test_topograph_rejoue_un_429_puis_sort_avec_son_retry_after(monkeypatch):
    from oto.tools.topograph import TopographClient
    from oto.tools.topograph import client as topograph_client

    attentes = []
    monkeypatch.setattr(topograph_client.time, "sleep", attentes.append)
    envois = _adaptateur(monkeypatch, 429, {"Retry-After": "2"})
    with pytest.raises(UpstreamHTTPError) as exc:
        TopographClient(api_key=_secret()).search("x")
    assert len(envois) == 3
    assert attentes == [2, 2]
    assert exc.value.status_code == 429 and exc.value.retry_after == 2.0
