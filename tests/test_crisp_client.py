"""Contrat du client Crisp (REST API V1, jeton de site en Basic, lecture seule) contre sa description.

Mocke `requests.Session.request`. Chaque exemple de chaque fonction de `connectors/crisp/connector.yaml` est joué par la
méthode du même nom, avec les mêmes arguments : la requête envoyée (verbe, adresse, query) est celle que la description
dit. S'y ajoutent l'authentification (en-têtes seulement, jamais dans l'adresse), les refus locaux avant tout appel, le
chemin d'arbre de la base de connaissances (ses `/` gardés, chaque segment encodé) et la traduction d'un refus de l'API.
"""
from __future__ import annotations

import copy
import inspect
import re

import pytest
import yaml

from fabrique.descriptions import CONNECTORS
from oto.tools.common.credentials import MissingCredential
from oto.tools.common.errors import UpstreamHTTPError
from oto.tools.crisp import client as cc

CRISP = CONNECTORS / "crisp" / "connector.yaml"
WEBSITE_ID = "8c842203-7ed8-4e29-a608-7cf78a7d2fcc"


class _Resp:
    def __init__(self, status_code: int = 200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {"error": False, "reason": "resolved", "data": {}}
        self.content = b"x"
        self.text = str(self._body)
        self.headers = {}

    def json(self):
        return self._body


@pytest.fixture()
def sent(monkeypatch):
    seen = {"calls": [], "responses": []}

    def fake_request(self, method, url, **kwargs):
        seen["calls"].append({"method": method, "url": url, "params": kwargs.get("params") or {},
                              "timeout": kwargs.get("timeout"), "headers": dict(self.headers)})
        return seen["responses"].pop(0) if seen["responses"] else _Resp()

    monkeypatch.setattr(cc.requests.Session, "request", fake_request)
    return seen


@pytest.fixture()
def cli():
    return cc.CrispClient(token_identifier="TOKEN_ID", token_key="TOKEN_KEY", website_id=WEBSITE_ID)


def _description() -> dict:
    return copy.deepcopy(yaml.safe_load(CRISP.read_text(encoding="utf-8")))


def _cases():
    for function in _description()["functions"]:
        for example in function["examples"]:
            yield pytest.param(function, example["input"], id=f"{function['name']}: {example['title']}")


# --- la description, fonction par fonction ---------------------------------------


def test_one_method_per_function_and_nothing_else():
    names = {f["name"] for f in _description()["functions"]}
    public = {n for n in vars(cc.CrispClient) if not n.startswith("_") and callable(getattr(cc.CrispClient, n))}
    assert public == names


@pytest.mark.parametrize("function, given", list(_cases()))
def test_each_example_sends_the_request_the_description_says(cli, sent, function, given):
    call = function["call"]
    getattr(cli, function["name"])(**given)
    [request] = sent["calls"]
    base = _description()["connector"]["base_url"].format(website_id=WEBSITE_ID)
    path = call["path"].format(**{a: given[a] for a in re.findall(r"{(\w+)}", call["path"])})
    assert request["method"] == call["method"] == "GET"
    assert request["url"] == base + path
    assert request["params"] == {api: given[a] for api, a in call.get("query", {}).items() if a in given}


def test_every_method_argument_is_an_argument_of_its_function():
    for function in _description()["functions"]:
        method = getattr(cc.CrispClient, function["name"])
        arguments = set(inspect.signature(method).parameters) - {"self"}
        assert arguments == set(function["input"]["properties"]), function["name"]


# --- authentification -------------------------------------------------------------


@pytest.mark.parametrize("missing", ["token_identifier", "token_key", "website_id"])
def test_the_three_fields_are_required(missing):
    fields = {"token_identifier": "i", "token_key": "k", "website_id": WEBSITE_ID, missing: None}
    with pytest.raises(MissingCredential):
        cc.CrispClient(**fields)


@pytest.mark.parametrize("website_id", ["../other", "a/b", "id?x=1"])
def test_a_website_id_that_is_not_an_id_is_refused(website_id):
    with pytest.raises(ValueError, match="website_id"):
        cc.CrispClient(token_identifier="i", token_key="k", website_id=website_id)


def test_basic_auth_and_tier_in_headers_never_in_the_address(cli, sent):
    cli.list_conversations(1, filter_unread=True)
    [request] = sent["calls"]
    assert request["headers"]["Authorization"] == "Basic " + cc.basic_signature("TOKEN_ID", "TOKEN_KEY")
    assert cc.basic_signature("TOKEN_ID", "TOKEN_KEY") == "VE9LRU5fSUQ6VE9LRU5fS0VZ"
    assert request["headers"]["X-Crisp-Tier"] == "website"
    assert "TOKEN" not in request["url"] and all("TOKEN" not in str(v) for v in request["params"].values())
    assert request["timeout"] == cc._HTTP_TIMEOUT


# --- arguments --------------------------------------------------------------------


def test_a_none_is_not_sent_and_a_boolean_flag_is_sent_as_0_or_1(cli, sent):
    cli.list_conversations()
    cli.list_conversations(2, filter_unread=True, filter_unassigned=False, per_page=50)
    assert sent["calls"][0]["params"] == {}
    assert sent["calls"][0]["url"].endswith("/conversations/1")
    assert sent["calls"][1]["params"] == {"filter_unread": 1, "filter_unassigned": 0, "per_page": 50}


def test_a_tree_path_keeps_its_slashes_and_encodes_each_segment(cli, sent):
    cli.get_helpdesk_content("fr", "articles", "/premiers pas/installer?x/")
    assert sent["calls"][0]["url"].endswith("/helpdesk/tree/content/fr/articles/premiers%20pas/installer%3Fx")


def test_an_id_is_one_encoded_segment_an_email_stays_readable(cli, sent):
    cli.get_person("jane.doe+x@example.test")
    cli.get_conversation("session_a/b")
    assert sent["calls"][0]["url"].endswith("/people/profile/jane.doe%2Bx@example.test")
    assert sent["calls"][1]["url"].endswith("/conversation/session_a%2Fb")


@pytest.mark.parametrize("call, name", [
    (lambda c: c.list_inboxes(0), "page_number"),
    (lambda c: c.list_conversations(1, per_page=10), "per_page"),
    (lambda c: c.list_conversations(1, filter_unread=2), "filter_unread"),
    (lambda c: c.list_conversations(1, filter_date_start="2026-03-01T00:00:00"), "filter_date_start"),
    (lambda c: c.list_people(1, filter_date_end="yesterday"), "filter_date_end"),
    (lambda c: c.list_people(1, sort_order="up"), "sort_order"),
    (lambda c: c.search_conversations(1, "vip", search_type="person"), "search_type"),
    (lambda c: c.search_conversations(1, ""), "search_query"),
    (lambda c: c.search_people(1, None), "search_text"),
    (lambda c: c.get_conversation(".."), "session_id"),
    (lambda c: c.get_person(""), "people_id"),
    (lambda c: c.list_conversation_messages("session_1", timestamp_before=-1), "timestamp_before"),
    (lambda c: c.get_helpdesk_entry("en", "articles", "guides/../secret"), "tree_path"),
    (lambda c: c.get_helpdesk_entry("en", "articles", "//"), "tree_path"),
    (lambda c: c.list_helpdesk_pages("en", "posts"), "content_type"),
    (lambda c: c.list_helpdesk_tree("..", "articles"), "locale"),
    (lambda c: c.list_helpdesk_tree("en", "articles", search_filter_status="all"), "search_filter_status"),
])
def test_a_bad_argument_is_refused_before_any_call(cli, sent, call, name):
    with pytest.raises(ValueError, match=name):
        call(cli)
    assert sent["calls"] == []


def test_a_date_time_with_its_offset_is_sent_as_given(cli, sent):
    cli.list_conversations(1, filter_date_start="2026-03-01T17:00:00.000Z",
                           filter_date_end="2026-03-02T00:00:00+02:00", order_date_updated=1)
    assert sent["calls"][0]["params"] == {"filter_date_start": "2026-03-01T17:00:00.000Z",
                                          "filter_date_end": "2026-03-02T00:00:00+02:00",
                                          "order_date_updated": 1}


# --- réponses ---------------------------------------------------------------------


def test_the_answer_is_returned_unchanged(cli, sent):
    body = {"error": False, "reason": "listed", "data": [{"session_id": "session_1"}]}
    sent["responses"].append(_Resp(200, body))
    assert cli.list_conversations() == body


@pytest.mark.parametrize("status", [401, 402, 404, 420, 429, 503])
def test_a_refusal_raises_upstream_http_error_once(cli, sent, status):
    sent["responses"].append(_Resp(status, {"error": True, "reason": "x", "data": {}}))
    with pytest.raises(UpstreamHTTPError) as caught:
        cli.get_website()
    assert caught.value.status_code == status and caught.value.service == "crisp"
    assert len(sent["calls"]) == 1
