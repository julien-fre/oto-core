"""Contrat du client Aircall (Public API, Basic `api_id:api_token`, lecture seule).

Mocke `requests.Session.request` : chemins et paramètres relevés dans la référence
éditeur, en-tête d'auth, bornes de pagination, conversion des dates en secondes
UNIX, refus locaux, et la re-tentative unique sur 429.
"""
from __future__ import annotations

import pytest

from oto.tools.aircall import client as ac
from oto.tools.common.credentials import MissingCredential
from oto.tools.common.errors import UpstreamHTTPError


class _Resp:
    def __init__(self, status_code: int = 200, body=None, headers=None):
        self.status_code = status_code
        self._body = body if body is not None else {"meta": {}, "calls": []}
        self.content = b"x"
        self.text = str(self._body)
        self.headers = headers or {}

    def json(self):
        return self._body


@pytest.fixture()
def capture(monkeypatch):
    seen = {"calls": [], "sleeps": [], "responses": []}

    def fake_request(self, method, url, **kwargs):
        seen.update(method=method, url=url, kwargs=kwargs)
        seen["calls"].append((method, url, kwargs.get("params")))
        if seen["responses"]:
            return seen["responses"].pop(0)
        return _Resp(200)

    monkeypatch.setattr(ac.requests.Session, "request", fake_request)
    monkeypatch.setattr(ac.time, "sleep", lambda s: seen["sleeps"].append(s))
    monkeypatch.setattr(ac.time, "time", lambda: 1_000_000.0)
    return seen


@pytest.fixture()
def cli():
    return ac.AircallClient(api_id="API_ID", api_token="API_TOKEN")


def _params(capture):
    return capture["kwargs"].get("params") or {}


# --- authentification ------------------------------------------------------

def test_les_deux_champs_sont_exiges():
    with pytest.raises(MissingCredential):
        ac.AircallClient(api_id="x", api_token=None)
    with pytest.raises(MissingCredential):
        ac.AircallClient(api_id=None, api_token="y")


def test_basic_auth_en_header_jamais_en_query(cli, capture):
    cli.list_calls(date_from=1)
    assert cli.session.headers["Authorization"] == (
        "Basic " + ac.basic_signature("API_ID", "API_TOKEN"))
    assert ac.basic_signature("API_ID", "API_TOKEN") == "QVBJX0lEOkFQSV9UT0tFTg=="
    assert "API_TOKEN" not in capture["url"]
    assert all("API_TOKEN" not in str(v) for v in _params(capture).values())


def test_timeout_borne(cli, capture):
    cli.probe()
    assert capture["kwargs"]["timeout"] == ac._HTTP_TIMEOUT


# --- chemins ---------------------------------------------------------------

@pytest.mark.parametrize("appel,chemin", [
    (lambda c: c.probe(), "/v1/ping"),
    (lambda c: c.get_company(), "/v1/company"),
    (lambda c: c.list_calls(), "/v1/calls"),
    (lambda c: c.search_calls(), "/v1/calls/search"),
    (lambda c: c.get_call(812), "/v1/calls/812"),
    (lambda c: c.get_transcription(812), "/v1/calls/812/transcription"),
    (lambda c: c.get_summary("812"), "/v1/calls/812/summary"),
    (lambda c: c.get_topics(812), "/v1/calls/812/topics"),
    (lambda c: c.get_sentiments(812), "/v1/calls/812/sentiments"),
    (lambda c: c.get_action_items(812), "/v1/calls/812/action_items"),
    (lambda c: c.list_users(), "/v2/users"),
    (lambda c: c.get_user(456), "/v2/users/456"),
    (lambda c: c.get_user("john.doe@example.com"), "/v2/users/john.doe@example.com"),
    (lambda c: c.list_teams(), "/v1/teams"),
    (lambda c: c.get_team(678), "/v1/teams/678"),
    (lambda c: c.list_numbers(), "/v1/numbers"),
    (lambda c: c.get_number(1234), "/v1/numbers/1234"),
    (lambda c: c.list_contacts(), "/v1/contacts"),
    (lambda c: c.search_contacts(email="a@b.c"), "/v1/contacts/search"),
    (lambda c: c.get_contact(710), "/v1/contacts/710"),
])
def test_chaque_methode_frappe_son_endpoint_en_get(cli, capture, appel, chemin):
    appel(cli)
    assert capture["method"] == "GET"
    assert capture["url"] == f"https://api.aircall.io{chemin}"


def test_un_id_non_numerique_est_refuse_avant_tout_appel(cli, capture):
    for bad in ("12/../users", "abc", "", None, True):
        with pytest.raises(ValueError):
            cli.get_call(bad)
    assert capture["calls"] == []


# --- paramètres ------------------------------------------------------------

def test_bornes_de_dates_partent_en_secondes_unix(cli, capture):
    cli.list_calls(date_from="2026-09-01", date_to="2026-09-02T00:00:00+02:00",
                   order="desc", per_page=50, page=2)
    p = _params(capture)
    assert p["from"] == 1788220800          # 2026-09-01T00:00:00Z
    assert p["to"] == 1788300000            # 2026-09-01T22:00:00Z
    assert p["order"] == "desc" and p["per_page"] == 50 and p["page"] == 2


def test_un_none_ne_part_pas(cli, capture):
    cli.list_calls()
    assert capture["kwargs"]["params"] is None


def test_drapeaux_en_minuscules(cli, capture):
    cli.get_call(1, fetch_contact=True)
    assert _params(capture) == {"fetch_contact": "true"}
    cli.list_calls(fetch_contact=False)
    assert _params(capture) == {"fetch_contact": "false"}


def test_recherche_d_appels(cli, capture):
    cli.search_calls(direction="inbound", user_id=456, phone_number="+33100000000")
    p = _params(capture)
    assert p == {"direction": "inbound", "user_id": "456",
                 "phone_number": "+33100000000"}


def test_recherche_de_contacts(cli, capture):
    cli.search_contacts(phone_number="+33100000000", order_by="updated_at")
    assert _params(capture) == {"phone_number": "+33100000000",
                                "order_by": "updated_at"}


def test_mode_de_transcription(cli, capture):
    cli.get_transcription(5, mode="realtime")
    assert _params(capture) == {"mode": "realtime"}
    with pytest.raises(ValueError):
        cli.get_transcription(5, mode="live")


@pytest.mark.parametrize("kw", [
    {"per_page": 0}, {"per_page": 51}, {"per_page": True}, {"page": 0},
    {"order": "newest"},
])
def test_refus_locaux_de_pagination_et_d_ordre(cli, capture, kw):
    with pytest.raises(ValueError):
        cli.list_calls(**kw)
    assert capture["calls"] == []


def test_direction_hors_enumeration(cli, capture):
    with pytest.raises(ValueError, match="inbound"):
        cli.search_calls(direction="internal")


# --- dates -----------------------------------------------------------------

@pytest.mark.parametrize("valeur,attendu", [
    (1700000000, 1700000000),
    ("1700000000", 1700000000),
    ("2026-09-01", 1788220800),
    ("2026-09-01T00:00:00Z", 1788220800),
    ("2026-09-01T02:00:00+02:00", 1788220800),
    (None, None),
])
def test_unix_seconds(valeur, attendu):
    assert ac.unix_seconds(valeur, "x") == attendu


@pytest.mark.parametrize("valeur", [
    "2026-09-01T08:00:00",       # sans fuseau
    "hier",
    -1,
    1788220800000,               # millisecondes
    True,
])
def test_unix_seconds_refuse(valeur):
    with pytest.raises(ValueError):
        ac.unix_seconds(valeur, "x")


# --- erreurs et limite de débit ---------------------------------------------

def test_erreur_amont_typee(cli, capture):
    capture["responses"].append(_Resp(404, {"error": "Not Found"}))
    with pytest.raises(UpstreamHTTPError) as e:
        cli.get_summary(1)
    assert e.value.status_code == 404 and e.value.service == "aircall"


def test_429_retente_une_fois_quand_le_reset_est_proche(cli, capture):
    capture["responses"] += [
        _Resp(429, {"error": "Too Many Requests"},
              {"X-AircallApi-Reset": "1000005"}),
        _Resp(200, {"meta": {}, "calls": [{"id": 1}]}),
    ]
    assert cli.list_calls()["calls"] == [{"id": 1}]
    assert capture["sleeps"] == [5.0]
    assert len(capture["calls"]) == 2


def test_429_remonte_quand_le_reset_est_loin(cli, capture):
    capture["responses"].append(
        _Resp(429, {"error": "Too Many Requests"},
              {"X-AircallApi-Reset": "1000060"}))
    with pytest.raises(UpstreamHTTPError) as e:
        cli.list_calls()
    assert e.value.status_code == 429
    assert capture["sleeps"] == [] and len(capture["calls"]) == 1


def test_429_sans_en_tete_remonte(cli, capture):
    capture["responses"].append(_Resp(429, {"error": "Too Many Requests"}))
    with pytest.raises(UpstreamHTTPError):
        cli.list_calls()
    assert len(capture["calls"]) == 1


# --- aucune adresse d'enregistrement ne sort (1.1.0) -----------------------------------------

_ADDRESSES = {
    "recording": "https://files.example.test/r/c-1.mp3?signature=sig-0",
    "recording_short_url": "https://short.example.test/r/c-1",
    "voicemail": "https://files.example.test/v/c-1.mp3?signature=sig-0",
    "voicemail_short_url": "https://short.example.test/v/c-1",
    "asset": "https://assets.example.test/recording/c-1",
}


def _call(call_id=1):
    return {"id": call_id, "direction": "inbound", "duration": 42, **_ADDRESSES}


@pytest.mark.parametrize("appel", [
    lambda c: c.list_calls(),
    lambda c: c.search_calls(direction="inbound"),
])
def test_les_listes_d_appels_perdent_leurs_adresses_et_gardent_meta(cli, capture, appel):
    meta = {"count": 2, "total": 2, "current_page": 1, "per_page": 20, "next_page_link": None}
    capture["responses"].append(_Resp(200, {"calls": [_call(1), _call(2)], "meta": meta}))
    answer = appel(cli)
    assert answer["meta"] == meta
    assert [c["id"] for c in answer["calls"]] == [1, 2]
    for call in answer["calls"]:
        assert not set(_ADDRESSES) & set(call)
        assert call["duration"] == 42


def test_un_appel_perd_ses_adresses(cli, capture):
    capture["responses"].append(_Resp(200, {"call": _call(812)}))
    answer = cli.get_call(812, fetch_contact=True)
    assert answer == {"call": {"id": 812, "direction": "inbound", "duration": 42}}
    assert _params(capture) == {"fetch_contact": "true"}


def test_les_adresses_courtes_ne_se_demandent_plus(cli, capture):
    for appel in (lambda: cli.list_calls(fetch_short_urls=True),
                  lambda: cli.search_calls(fetch_short_urls=True),
                  lambda: cli.get_call(1, fetch_short_urls=True)):
        with pytest.raises(TypeError):
            appel()
    assert capture["calls"] == []


# --- l'audio d'un appel, rendu en fichier ------------------------------------------------------

from requests.adapters import HTTPAdapter  # noqa: E402

import files_fake  # noqa: E402
from oto.connectors.files import FileOut, FileOutputError  # noqa: E402
from oto.tools.common import url_guard  # noqa: E402

_AUDIO = {"status": 200, "headers": {"Content-Type": "audio/mpeg"}, "text": "ID3-audio"}


class _Sequence(HTTPAdapter):
    """Rend chaque réponse dans l'ordre (l'appel à l'API, puis le téléchargement) et note chaque requête."""

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


@pytest.mark.parametrize("methode, champ", [
    ("get_call_recording", "recording"),
    ("get_call_voicemail", "voicemail"),
])
def test_l_audio_d_un_appel_est_un_fichier(cli, wire, methode, champ):
    transport = wire(_json(200, {"call": _call(812)}), _AUDIO)
    result = getattr(cli, methode)(812)
    assert result == FileOut(name=f"call-812-{champ}.mp3", content=b"ID3-audio", mime="audio/mpeg")
    api, download = transport.sent
    assert api.method == "GET" and api.url == "https://api.aircall.io/v1/calls/812"
    assert api.headers["Authorization"].startswith("Basic ")
    assert download.url == _ADDRESSES[champ]
    assert "Authorization" not in download.headers


def test_un_appel_inconnu_ne_telecharge_rien(cli, wire):
    transport = wire(_json(404, {"error": "Not Found"}))
    with pytest.raises(UpstreamHTTPError) as e:
        cli.get_call_recording(812)
    assert e.value.status_code == 404
    assert len(transport.sent) == 1


def test_un_appel_sans_messagerie_n_a_pas_de_fichier(cli, wire):
    call = {k: v for k, v in _call(812).items() if not k.startswith("voicemail")}
    transport = wire(_json(200, {"call": {**call, "voicemail": None}}))
    with pytest.raises(FileOutputError) as e:
        cli.get_call_voicemail(812)
    assert e.value.code == "file_missing"
    assert len(transport.sent) == 1


def test_une_adresse_en_http_est_refusee_sans_la_dire(cli, wire):
    address = "http://files.example.test/r/c-1.mp3?signature=sig-0"
    transport = wire(_json(200, {"call": {**_call(812), "recording": address}}))
    with pytest.raises(FileOutputError) as e:
        cli.get_call_recording(812)
    assert e.value.code == "file_download_refused"
    assert address not in str(e.value) and "sig-0" not in str(e.value)
    assert len(transport.sent) == 1


def test_un_id_d_appel_non_numerique_est_refuse_avant_tout_envoi(cli, wire):
    transport = wire()
    with pytest.raises(ValueError):
        cli.get_call_recording("12/../users")
    assert transport.sent == []
