"""Contrat du client Resend côté contacts, segments et sujets (REST, `Bearer`).

Mocke `requests.Session.request`. Ce que ce fichier verrouille :

1. la clé ne part qu'en en-tête `Authorization`, jamais dans l'URL ; une
   redirection est refusée, jamais suivie ;
2. chaque méthode appelle le bon verbe et le bon chemin ; un email dans le chemin
   garde son `@` et voit ses autres caractères réservés encodés ;
3. un champ omis n'est jamais envoyé (il n'écrase rien chez Resend) ;
4. une lecture est retentée (429 court, 5xx), une écriture JAMAIS ;
5. `upsert_contact` : lit d'abord par email, crée (segments dans le même appel) ou
   ne corrige que ce qui diffère, n'ajoute que les segments manquants — et ne
   réabonne jamais un contact désabonné ;
6. les refus locaux partent avant tout appel.
"""
from __future__ import annotations

import pytest

from oto.tools.common.errors import UpstreamHTTPError
from oto.tools.http.client import RedirectRefused
from oto.tools.resend import client as rc

BASE = "https://api.resend.com"


class _Resp:
    def __init__(self, status_code: int = 200, body=None, headers=None):
        self.status_code = status_code
        self._body = body if body is not None else {"object": "list", "has_more": False,
                                                    "data": []}
        self.content = b"x"
        self.text = str(self._body)
        self.headers = headers or {}

    def json(self):
        return self._body


def _404():
    return _Resp(404, {"name": "not_found", "statusCode": 404,
                       "message": "Contact not found"})


@pytest.fixture()
def capture(monkeypatch):
    seen = {"calls": [], "replies": [], "sleeps": []}

    def fake_request(self, method, url, **kwargs):
        seen.update(method=method, url=url, kwargs=kwargs, headers=dict(self.headers))
        seen["calls"].append((method, url[len(BASE):], kwargs.get("params"),
                              kwargs.get("json")))
        if seen["replies"]:
            return seen["replies"].pop(0)
        return _Resp(200)

    monkeypatch.setattr(rc.requests.Session, "request", fake_request)
    monkeypatch.setattr(rc.time, "sleep", seen["sleeps"].append)
    return seen


@pytest.fixture()
def cli():
    return rc.ResendClient(api_key="re_secret")


def _verbs(capture):
    return [(m, p) for m, p, _q, _b in capture["calls"]]


# --- authentification, transport ------------------------------------------

def test_cle_en_entete_bearer_jamais_dans_l_url(cli, capture):
    cli.list_contacts(limit=10)
    assert capture["headers"]["Authorization"] == "Bearer re_secret"
    assert "re_secret" not in capture["url"]
    assert "re_secret" not in str(capture["kwargs"]["params"])


def test_cle_absente_refusee_a_la_construction():
    from oto.tools.common.credentials import MissingCredential
    with pytest.raises(MissingCredential):
        rc.ResendClient(api_key=None)


def test_une_redirection_est_refusee_jamais_suivie(cli, capture):
    capture["replies"].append(_Resp(302, headers={"Location": "https://ailleurs.test/x"}))
    with pytest.raises(RedirectRefused):
        cli.list_segments()
    assert capture["kwargs"]["allow_redirects"] is False
    assert len(capture["calls"]) == 1


def test_le_rythme_est_tenu_entre_deux_appels(cli, capture, monkeypatch):
    monkeypatch.setattr(rc.time, "monotonic", lambda: 100.0)
    cli.list_segments()
    cli.list_topics()
    assert capture["sleeps"] == [pytest.approx(rc.MIN_INTERVAL_S)]


# --- lectures ----------------------------------------------------------------

def test_list_contacts_filtre_par_segment_et_pagine(cli, capture):
    cli.list_contacts("seg-1", limit=100, after="c-9")
    assert capture["calls"] == [("GET", "/contacts",
                                 {"limit": 100, "after": "c-9", "segment_id": "seg-1"},
                                 None)]


def test_list_contacts_sans_parametre_n_envoie_rien(cli, capture):
    cli.list_contacts()
    assert capture["calls"][0][2] is None


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 101}, {"limit": True},
                                    {"limit": "10"}, {"after": "a", "before": "b"}])
def test_pagination_invalide_refusee_avant_tout_appel(cli, capture, kwargs):
    with pytest.raises(ValueError):
        cli.list_contacts(**kwargs)
    assert capture["calls"] == []


def test_un_email_dans_le_chemin_garde_son_arobase(cli, capture):
    cli.get_contact("  first+tag@example.com ")
    cli.get_contact("weird/name@example.com")
    assert _verbs(capture) == [("GET", "/contacts/first%2Btag@example.com"),
                               ("GET", "/contacts/weird%2Fname@example.com")]


def test_segments_et_sujets_d_un_contact(cli, capture):
    cli.list_contact_segments("c-1", limit=100)
    cli.list_contact_topics("c-1")
    assert capture["calls"] == [("GET", "/contacts/c-1/segments", {"limit": 100}, None),
                                ("GET", "/contacts/c-1/topics", None, None)]


def test_find_contact_rend_none_sur_404_et_releve_le_reste(cli, capture):
    capture["replies"] += [_404(), _Resp(401, {"name": "restricted_api_key"})]
    assert cli.find_contact("a@example.com") is None
    with pytest.raises(UpstreamHTTPError) as e:
        cli.find_contact("a@example.com")
    assert e.value.status_code == 401


def test_segments_et_sujets(cli, capture):
    cli.list_segments(limit=20)
    cli.get_segment("seg-1")
    cli.list_topics(limit=5, after="t-1")
    cli.get_topic("t-2")
    assert capture["calls"] == [
        ("GET", "/segments", {"limit": 20}, None),
        ("GET", "/segments/seg-1", None, None),
        ("GET", "/topics", {"limit": 5, "after": "t-1"}, None),
        ("GET", "/topics/t-2", None, None),
    ]


# --- écritures ---------------------------------------------------------------

def test_create_contact_envoie_les_segments_dans_le_meme_appel(cli, capture):
    cli.create_contact("a@example.com", first_name="Ada", segment_ids=["s1", "s1", "s2"])
    assert capture["calls"] == [("POST", "/contacts", None, {
        "email": "a@example.com", "first_name": "Ada",
        "segments": [{"id": "s1"}, {"id": "s2"}]})]


def test_create_contact_refuse_un_email_invalide(cli, capture):
    with pytest.raises(ValueError, match="email"):
        cli.create_contact("pas-un-email")
    assert capture["calls"] == []


def test_update_contact_n_envoie_que_les_champs_donnes(cli, capture):
    cli.update_contact("a@example.com", unsubscribed=True,
                       properties={"plan": "pro", "seats": 3, "old": None})
    assert capture["calls"] == [("PATCH", "/contacts/a@example.com", None, {
        "unsubscribed": True, "properties": {"plan": "pro", "seats": 3, "old": None}})]


@pytest.mark.parametrize("kwargs", [{}, {"properties": {}}, {"unsubscribed": "yes"},
                                    {"properties": {"k": {"nested": 1}}},
                                    {"first_name": 3}])
def test_update_contact_refuse_avant_tout_appel(cli, capture, kwargs):
    with pytest.raises(ValueError):
        cli.update_contact("c-1", **kwargs)
    assert capture["calls"] == []


def test_suppression_et_appartenance_a_un_segment(cli, capture):
    cli.delete_contact("c-1")
    cli.add_contact_to_segment("a@example.com", "seg-1")
    cli.remove_contact_from_segment("c-1", "seg-1")
    cli.create_segment("  Product updates ")
    assert capture["calls"] == [
        ("DELETE", "/contacts/c-1", None, None),
        ("POST", "/contacts/a@example.com/segments/seg-1", None, None),
        ("DELETE", "/contacts/c-1/segments/seg-1", None, None),
        ("POST", "/segments", None, {"name": "Product updates"}),
    ]


# --- re-tentatives -------------------------------------------------------------

def test_une_lecture_est_retentee_sur_429_court(cli, capture):
    capture["replies"] += [_Resp(429, {"name": "rate_limit_exceeded"},
                                 headers={"retry-after": "1"}), _Resp(200)]
    cli.list_segments()
    assert len(capture["calls"]) == 2
    assert 1.0 in capture["sleeps"]


def test_une_lecture_n_attend_pas_un_429_long(cli, capture):
    capture["replies"] += [_Resp(429, {"name": "rate_limit_exceeded"},
                                 headers={"retry-after": "60"})]
    with pytest.raises(UpstreamHTTPError):
        cli.list_segments()
    assert len(capture["calls"]) == 1


def test_une_lecture_est_retentee_sur_5xx(cli, capture):
    capture["replies"] += [_Resp(503, {"name": "service_unavailable"}), _Resp(200)]
    cli.get_segment("seg-1")
    assert len(capture["calls"]) == 2


@pytest.mark.parametrize("status", [429, 500, 503])
def test_une_ecriture_n_est_jamais_rejouee(cli, capture, status):
    capture["replies"] += [_Resp(status, {"name": "x"}, headers={"retry-after": "1"})]
    with pytest.raises(UpstreamHTTPError):
        cli.create_contact("a@example.com")
    assert len(capture["calls"]) == 1


# --- upsert --------------------------------------------------------------------

def _contact(**kw):
    base = {"object": "contact", "id": "c-1", "email": "a@example.com",
            "first_name": "Ada", "last_name": None, "unsubscribed": False,
            "properties": {"plan": {"value": "free", "type": "string"}}}
    base.update(kw)
    return base


def _segments(*ids, has_more=False):
    return {"object": "list", "has_more": has_more,
            "data": [{"id": i, "name": i} for i in ids]}


def test_upsert_cree_un_contact_absent_avec_ses_segments(cli, capture):
    capture["replies"] += [_404(), _Resp(200, {"object": "contact", "id": "c-new"})]
    out = cli.upsert_contact("a@example.com", first_name="Ada", segment_ids=["s1"])
    assert capture["calls"] == [
        ("GET", "/contacts/a@example.com", None, None),
        ("POST", "/contacts", None, {"email": "a@example.com", "first_name": "Ada",
                                     "segments": [{"id": "s1"}]}),
    ]
    assert out == {"email": "a@example.com", "id": "c-new", "action": "created",
                   "unsubscribed": False, "fields": {"first_name": "Ada"},
                   "segments_added": ["s1"]}


def test_upsert_ne_corrige_que_ce_qui_differe(cli, capture):
    capture["replies"] += [_Resp(200, _contact()), _Resp(200, _segments("s1")),
                           _Resp(200, {"object": "contact", "id": "c-1"}),
                           _Resp(200, {"id": "s2"})]
    out = cli.upsert_contact("a@example.com", first_name="Ada", last_name="Lovelace",
                             properties={"plan": "pro"}, segment_ids=["s1", "s2"])
    assert _verbs(capture) == [
        ("GET", "/contacts/a@example.com"),
        ("GET", "/contacts/c-1/segments"),
        ("PATCH", "/contacts/c-1"),
        ("POST", "/contacts/c-1/segments/s2"),
    ]
    assert capture["calls"][2][3] == {"last_name": "Lovelace",
                                      "properties": {"plan": "pro"}}
    assert out["action"] == "updated"
    assert out["changes"] == {
        "last_name": {"from": None, "to": "Lovelace"},
        "properties": {"from": {"plan": "free"}, "to": {"plan": "pro"}}}
    assert out["segments_added"] == ["s2"]
    assert out["already_in_segments"] == ["s1"]


def test_upsert_deja_a_jour_n_ecrit_rien(cli, capture):
    capture["replies"] += [_Resp(200, _contact()), _Resp(200, _segments("s1"))]
    out = cli.upsert_contact("a@example.com", first_name="Ada",
                             properties={"plan": "free"}, segment_ids=["s1"])
    assert [m for m, _p in _verbs(capture)] == ["GET", "GET"]
    assert out["action"] == "unchanged"


def test_upsert_sans_segment_ne_lit_pas_les_appartenances(cli, capture):
    capture["replies"] += [_Resp(200, _contact())]
    out = cli.upsert_contact("a@example.com", first_name="Ada")
    assert _verbs(capture) == [("GET", "/contacts/a@example.com")]
    assert out["action"] == "unchanged"


def test_upsert_lit_toutes_les_pages_d_appartenance(cli, capture):
    capture["replies"] += [_Resp(200, _contact()),
                           _Resp(200, _segments("s1", has_more=True)),
                           _Resp(200, _segments("s2"))]
    out = cli.upsert_contact("a@example.com", segment_ids=["s2"])
    assert capture["calls"][2][2] == {"limit": 100, "after": "s1"}
    assert out["action"] == "unchanged" and out["already_in_segments"] == ["s2"]


def test_upsert_ne_reabonne_jamais(cli, capture):
    capture["replies"] += [_Resp(200, _contact(unsubscribed=True))]
    out = cli.upsert_contact("a@example.com", unsubscribed=False)
    assert [m for m, _p in _verbs(capture)] == ["GET"]
    assert out["kept_unsubscribed"] is True
    assert out["unsubscribed"] is True
    assert out["action"] == "unchanged"


def test_upsert_peut_desabonner(cli, capture):
    capture["replies"] += [_Resp(200, _contact()), _Resp(200, {"id": "c-1"})]
    out = cli.upsert_contact("a@example.com", unsubscribed=True)
    assert capture["calls"][1][3] == {"unsubscribed": True}
    assert out["unsubscribed"] is True and out["action"] == "updated"


def test_upsert_dry_run_lit_et_n_ecrit_rien(cli, capture):
    capture["replies"] += [_Resp(200, _contact()), _Resp(200, _segments())]
    out = cli.upsert_contact("a@example.com", last_name="Lovelace",
                             segment_ids=["s9"], dry_run=True)
    assert [m for m, _p in _verbs(capture)] == ["GET", "GET"]
    assert out["dry_run"] is True and out["action"] == "would_update"
    assert out["segments_to_add"] == ["s9"]

    capture["calls"].clear()
    capture["replies"] += [_404()]
    out = cli.upsert_contact("b@example.com", segment_ids=["s9"], dry_run=True)
    assert [m for m, _p in _verbs(capture)] == ["GET"]
    assert out["action"] == "would_create" and out["segments_to_add"] == ["s9"]


def test_upsert_remonte_un_refus_de_cle(cli, capture):
    capture["replies"] += [_Resp(401, {"name": "restricted_api_key", "statusCode": 401,
                                       "message": "This API key is restricted to only "
                                                  "send emails"})]
    with pytest.raises(UpstreamHTTPError) as e:
        cli.upsert_contact("a@example.com")
    assert e.value.body["name"] == "restricted_api_key"
    assert len(capture["calls"]) == 1
