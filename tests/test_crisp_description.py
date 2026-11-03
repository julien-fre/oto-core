"""La description `crisp` 1.0.0 : la messagerie client de Crisp, en lecture seule, sans client Python.

Gardes : chaque fonction est une lecture (`class: read`, jamais `act`) servie par un `GET` ; le compte est le jeton
de site (identifiant et clé en Basic, en-tête `X-Crisp-Tier: website`) et l'identifiant du site est un réglage du
compte, cité par `base_url`, jamais un argument ; chaque fonction qui lit une conversation, un message ou un contact
dit à l'agent que le contenu peut porter des données personnelles ou de santé, et de ne pas chercher une personne par
son nom ou son téléphone sans nécessité ; un argument qui peut désigner une personne est `personal`.
"""
from __future__ import annotations

import copy

import yaml

from fabrique.descriptions import CONNECTORS, check
from fabrique.typescript import connector_module

CRISP = CONNECTORS / "crisp" / "connector.yaml"
PRIVACY = (
    "May contain personal or health data: read only what the task needs, and do not look a person up by name or "
    "phone number unless the task requires it."
)
HELPDESK_OR_WORKSPACE = {
    "get_website", "list_inboxes", "get_inbox", "get_helpdesk", "list_helpdesk_locales", "list_helpdesk_pages",
    "list_helpdesk_tree", "get_helpdesk_entry", "get_helpdesk_content", "get_helpdesk_metadata",
}


def _description() -> dict:
    return copy.deepcopy(yaml.safe_load(CRISP.read_text(encoding="utf-8")))


def _functions() -> list[dict]:
    return _description()["functions"]


def test_description_passes_the_fabrique():
    module = connector_module(check(_description(), CRISP))
    assert module.generated and module.skipped == []


def test_every_function_is_a_read_served_by_a_get():
    for function in _functions():
        assert function["class"] == "read", function["name"]
        assert function.get("act", False) is False, function["name"]
        assert function["call"]["method"] == "GET", function["name"]
        assert "body" not in function["call"] and "confirm" not in function, function["name"]


def test_the_account_is_a_website_token_and_the_website_id_a_setting():
    connector = _description()["connector"]
    assert connector["auth"] == {"kind": "basic", "username": "token_identifier", "password": "token_key"}
    assert connector["headers"] == {"X-Crisp-Tier": "website"}
    assert connector["base_url"] == "https://api.crisp.chat/v1/website/{website_id}"
    assert [s["name"] for s in connector["settings"]] == ["website_id"]
    for function in _functions():
        assert "website_id" not in function["input"]["properties"], function["name"]


def test_conversations_messages_and_contacts_carry_the_privacy_notice():
    readers = [f for f in _functions() if f["name"] not in HELPDESK_OR_WORKSPACE]
    assert {f["name"] for f in readers} == {
        "list_conversations", "search_conversations", "get_conversation", "get_conversation_meta",
        "list_conversation_messages", "list_people", "search_people", "get_person", "get_person_data",
        "list_person_conversations",
    }
    for function in readers:
        assert PRIVACY in " ".join(function["description"].split()), function["name"]


def test_an_argument_that_may_name_a_person_is_personal():
    by_name = {f["name"]: f["input"]["properties"] for f in _functions()}
    for name, argument in [("get_person", "people_id"), ("get_person_data", "people_id"),
                           ("list_person_conversations", "people_id"), ("search_people", "search_text"),
                           ("search_conversations", "search_query")]:
        assert by_name[name][argument].get("personal") is True, (name, argument)
