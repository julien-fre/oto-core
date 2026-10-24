"""La description `attio` 1.0.0 : celle du client existant (`oto.tools.attio`).

Le client range ses méthodes par ressource (`client.notes.list`, `client.attributes.options`…) : chaque fonction est
une méthode, nommée de son verbe et de sa ressource (`FUNCTIONS`), avec les arguments que la méthode nomme ; les clés
envoyées à Attio (chemin, query, corps) sont les siennes. Les fiches de tous les objets partagent une ressource
(`AttioResource`, bâtie pour un objet) : l'objet est l'argument `object`. Écarts nommés, gardés ici :
- les méthodes laissées au client (`LEFT_OUT`) : les écritures dont le client emballe le corps dans `{"data": {...}}`
  autour de ses arguments (le format ne place pas un argument sous une autre clé), et `threads.list`, dont le client
  envoie des noms de paramètres qu'Attio ne lit pas ;
- l'argument `query` de `records.search`, que le client récrit en filtre sur le nom (`ARGUMENTS_LEFT_OUT`) ;
- les valeurs que le client pose quand l'appel ne les donne pas (`CLIENT_FILLS`), défauts non déclarés ;
- ce que le schéma refuse et que le client laisse passer (`NARROWER`), et ce que le client refuse lui-même
  (`CLIENT_REFUSES`).
Rien ne revient à l'agent d'une adresse ouverte sans connexion : l'adresse vidéo d'un enregistrement d'appel et celle
de l'avatar d'un membre sont retirées par la description et par le client.
Les gardes ci-dessous lisent le client lui-même : une méthode, un argument ou une clé qu'il ajoute sans la description
fait échouer le test ; une écriture servie du côté lecture aussi.
"""
from __future__ import annotations

import copy
import inspect
import json
import re
from unittest import mock

import jsonschema
import pytest
import yaml

from fabrique import python
from fabrique.descriptions import CONNECTORS, check
from fabrique.typescript import connector_module
from oto.connectors.declared import DECLARED
from oto.tools.attio import client as attio_client
from oto.tools.attio.client import AttioClient, AttioResource

ATTIO = CONNECTORS / "attio" / "connector.yaml"

# La ressource (attribut du client, `records` pour `AttioResource`) et la méthode de chaque fonction.
FUNCTIONS = {
    "list_records": ("records", "list"), "get_record": ("records", "get"),
    "search_records": ("records", "search"), "delete_record": ("records", "delete"),
    "list_notes": ("notes", "list"), "get_note": ("notes", "get"), "delete_note": ("notes", "delete"),
    "list_tasks": ("tasks", "list"), "get_task": ("tasks", "get"), "delete_task": ("tasks", "delete"),
    "list_lists": ("lists", "list"), "get_list": ("lists", "get"), "list_list_views": ("lists", "views"),
    "query_entries": ("entries", "query"), "get_entry": ("entries", "get"), "delete_entry": ("entries", "delete"),
    "list_workspace_members": ("workspace_members", "list"), "get_workspace_member": ("workspace_members", "get"),
    "get_comment": ("comments", "get"), "delete_comment": ("comments", "delete"),
    "get_thread": ("threads", "get"),
    "list_meetings": ("meetings", "list"), "get_meeting": ("meetings", "get"),
    "list_call_recordings": ("call_recordings", "list"), "get_call_recording": ("call_recordings", "get"),
    "get_call_recording_transcript": ("call_recordings", "transcript"),
    "list_objects": ("objects", "list"), "get_object": ("objects", "get"), "list_object_views": ("objects", "views"),
    "list_attributes": ("attributes", "list"), "get_attribute": ("attributes", "get"),
    "list_attribute_options": ("attributes", "options"), "list_attribute_statuses": ("attributes", "statuses"),
    "create_attribute": ("attributes", "create"),
}
_ENVELOPE = "the client wraps the body in {'data': {...}} around its arguments; the format places no argument under another key"
# Les méthodes laissées au client, et pourquoi.
LEFT_OUT = {
    "create_record": (("records", "create"), _ENVELOPE),
    "update_record": (("records", "update"), _ENVELOPE + "; its method (PATCH or PUT) is picked by an argument"),
    "merge_records": (("records", "merge"), _ENVELOPE),
    "create_note": (("notes", "create"), _ENVELOPE + ", with format markdown added"),
    "create_task": (("tasks", "create"), _ENVELOPE + ", with values added and a second request (the default assignee)"),
    "update_task": (("tasks", "update"), _ENVELOPE + ", with the deadline completed to midnight, the assignee wrapped"),
    "create_list": (("lists", "create"), _ENVELOPE + ", with a slug made from the name and access defaults"),
    "update_list": (("lists", "update"), _ENVELOPE),
    "create_entry": (("entries", "create"), _ENVELOPE + ", with entry_values {} by default"),
    "update_entry": (("entries", "update"), _ENVELOPE + "; its method (PATCH or PUT) is picked by an argument"),
    "create_comment": (("comments", "create"), _ENVELOPE + ", with format and author wrapped, an anchor among three"),
    "create_attribute_option": (("attributes", "create_option"), _ENVELOPE),
    "create_attribute_status": (("attributes", "create_status"), _ENVELOPE),
    "list_threads": (("threads", "list"), "the client sends parent_object, parent_record_id and list_id where Attio "
                                          "reads object, record_id and list: swallowed, then an unfiltered thread list "
                                          "is refused"),
}
RESOURCES = {"records": AttioResource, **{
    attr: type(getattr(AttioClient(api_key="k"), attr)) for attr in (
        "notes", "tasks", "lists", "entries", "workspace_members", "comments", "threads", "meetings",
        "call_recordings", "objects", "attributes")}}
# Les fiches de tous les objets : l'objet de la ressource est un argument de la fonction.
ARGUMENTS_ADDED = {name: {"object"} for name, (resource, _) in FUNCTIONS.items() if resource == "records"}
# Les arguments d'une méthode que sa fonction ne prend pas, et pourquoi.
ARGUMENTS_LEFT_OUT = {"search_records": {"query": "the client rewrites it into {'name': {'$contains': query}}"}}
# Exigés par la description, facultatifs au client : sans `query`, une recherche sans filtre est list_records.
REQUIRED_HERE = {"search_records": {"filters"}}
# Ce que le client pose quand l'appel ne le donne pas : défauts du client, non déclarés (l'hôte n'envoie rien).
CLIENT_FILLS = {
    "list_records": {"limit": 50, "offset": 0},
    "search_records": {"limit": 50},
    "query_entries": {"limit": 50, "offset": 0},
}
POST_READS = {"list_records", "search_records", "query_entries"}
CLASSES = {
    "read": {n for n in FUNCTIONS if n.split("_")[0] in ("list", "get", "search", "query")},
    "write": {"create_attribute"},
    "sensitive": {"delete_record", "delete_note", "delete_task", "delete_entry", "delete_comment"},
}
ADDRESSES = {
    "list_workspace_members": ("data.avatar_url", "list"), "get_workspace_member": ("data.avatar_url", "one"),
    "list_call_recordings": ("data.video_url", "list"), "get_call_recording": ("data.video_url", "one"),
}
PERSONAL = {"search_records": ["filters"], "query_entries": ["filter"]}
UUID = "0f1e2d3c-4b5a-4968-8776-655443322110"
VALUES = {
    "object": "companies", "record_id": UUID, "limit": 20, "offset": 40,
    "sort": [{"attribute": "created_at", "direction": "desc"}], "sorts": [{"attribute": "name", "direction": "asc"}],
    "filters": {"email_addresses": "ada@acme.example"}, "filter": {"stage": "Won"},
    "parent_object": "people", "parent_record_id": UUID, "note_id": UUID, "task_id": UUID, "completed": False,
    "list_id_or_slug": "sales_pipeline", "entry_id": UUID, "workspace_member_id": UUID, "comment_id": UUID,
    "thread_id": UUID, "meeting_id": UUID, "call_recording_id": UUID, "cursor": "Y3Vyc29y", "ends_from":
    "2026-10-19T00:00:00Z", "starts_before": "2026-10-26T00:00:00Z", "object_id_or_slug": "people",
    "target": "objects", "identifier": "companies", "attribute": "stage",
    "definition": {"title": "Source", "description": None, "api_slug": "source", "type": "text",
                   "is_required": False, "is_unique": False, "is_multiselect": False, "config": {}},
}
VALUES_OF = {"list_tasks": {"sort": "created_at:desc", "limit": 100}, "list_meetings": {"sort": "start_desc"}}
# Plus étroit que le client, qui laisse passer : motifs d'identifiant, listes fermées, bornes, paires.
NARROWER = {
    "get_record": [{"object": "companies/x", "record_id": UUID}, {"object": "companies", "record_id": "r1"}],
    "list_records": [{"object": "companies", "sort": [{"attribute": "name", "direction": "up"}]},
                     {"object": "companies", "limit": 0}],
    "search_records": [{"object": "people"}, {"object": "people", "filters": {}}],
    "list_notes": [{"parent_object": "people"}, {"parent_record_id": UUID}],
    "get_attribute": [{"target": "activities", "identifier": "calls", "attribute": "title"}],
    "create_attribute": [{"target": "objects", "identifier": "companies", "definition": {"title": "Source"}},
                         {"target": "objects", "identifier": "companies",
                          "definition": dict(VALUES["definition"], type="formula")}],
    "query_entries": [{"list_id_or_slug": "sales_pipeline", "offset": -1}],
}
# Ce que le client refuse lui-même (ValueError avant tout envoi), et que le schéma refuse aussi.
CLIENT_REFUSES = {
    "list_notes": [{"limit": 51}, {"limit": 0}],
    "list_tasks": [{"limit": 1001}, {"sort": "due_at:asc"}],
    "list_meetings": [{"limit": 201}, {"sort": "start"}],
}


class _Answer:
    status_code = 200
    ok = True
    headers: dict = {}
    text = "{}"

    def __init__(self, body=None):
        self._body = {} if body is None else body
        self.content = json.dumps(self._body).encode()

    def json(self):
        return copy.deepcopy(self._body)


def _description() -> dict:
    return copy.deepcopy(yaml.safe_load(ATTIO.read_text(encoding="utf-8")))


def _functions() -> dict[str, dict]:
    return {f["name"]: f for f in _description()["functions"]}


def _public_methods() -> set[tuple[str, str]]:
    return {(attr, n) for attr, cls in RESOURCES.items()
            for n, _ in inspect.getmembers(cls, inspect.isfunction) if not n.startswith("_")}


def _parameters(name: str) -> dict[str, inspect.Parameter]:
    resource, method = FUNCTIONS[name]
    return {p: v for p, v in inspect.signature(getattr(RESOURCES[resource], method)).parameters.items()
            if p != "self" and v.kind is not inspect.Parameter.VAR_KEYWORD}


def _call_the_client(name: str, arguments: dict, answer=None) -> tuple[dict, object]:
    """Ce que le client envoie pour un appel de la fonction, sans réseau, et ce qu'il rend."""
    sent = []

    def request(method, url, **kwargs):
        sent.append({"method": method, "url": url, "params": dict(kwargs.get("params") or {}),
                     "json": kwargs.get("json"), "headers": dict(kwargs.get("headers") or {}),
                     "timeout": kwargs.get("timeout")})
        return _Answer(answer)

    resource, method = FUNCTIONS[name]
    given = dict(arguments)
    client = AttioClient(api_key="attio-k")
    target = AttioResource(client, given.pop("object")) if resource == "records" else getattr(client, resource)
    with mock.patch.object(attio_client.requests, "request", request):
        returned = getattr(target, method)(**given)
    assert len(sent) == 1, name
    return sent[0], returned


def _in_query(value):
    """Une valeur en query comme l'écrit l'hôte : booléen en minuscules, nombre en texte."""
    return str(value).lower() if isinstance(value, bool) else str(value)


def _described(name: str, function: dict, arguments: dict) -> tuple:
    """La requête que dit la description, plus ce que le client pose quand l'appel ne le donne pas."""
    call = function["call"]
    given = {**CLIENT_FILLS.get(name, {}), **arguments}
    path = call["path"].format(**{a: given[a] for a in re.findall(r"{(\w+)}", call["path"])})
    query = {api: _in_query(given[a]) for api, a in call.get("query", {}).items() if a in given}
    body = {api: given[a] for api, a in call["body"].items() if a in given} if "body" in call else None
    return call["method"], AttioClient.BASE_URL + path, query, body


def _client_view(sent: dict) -> tuple:
    return sent["method"], sent["url"], {k: _in_query(v) for k, v in sent["params"].items()}, sent["json"]


def _every_argument(name: str, function: dict) -> dict:
    values = {**VALUES, **VALUES_OF.get(name, {})}
    return {a: values[a] for a in function["input"]["properties"]}


def _required(name: str, function: dict) -> dict:
    values = {**VALUES, **VALUES_OF.get(name, {})}
    return {a: values[a] for a in function["input"].get("required", [])}


def _valid(function: dict, arguments: dict) -> bool:
    return jsonschema.Draft202012Validator(function["input"]).is_valid(arguments)


def _shaped(answer, paths: list[str]):
    """La réponse taillée comme l'hôte la taille (`output.strip`), chaque chemin à travers les listes."""
    answer = copy.deepcopy(answer)

    def strip(node, keys):
        if isinstance(node, list):
            for item in node:
                strip(item, keys)
        elif isinstance(node, dict):
            if len(keys) == 1:
                node.pop(keys[0], None)
            elif keys[0] in node:
                strip(node[keys[0]], keys[1:])

    for path in paths:
        strip(answer, path.split("."))
    return answer


def test_the_description_is_version_1_0_0_and_passes_the_fabrique():
    description = _description()
    assert description["connector"]["version"] == "1.0.0"
    check(description, ATTIO)


def test_each_client_method_is_one_function_or_left_out_by_name():
    assert set(_functions()) == set(FUNCTIONS)
    described = set(FUNCTIONS.values())
    assert len(described) == len(FUNCTIONS)
    left_out = {method for method, _ in LEFT_OUT.values()}
    assert len(left_out) == len(LEFT_OUT) and not described & left_out
    assert described | left_out == _public_methods()


def test_the_connector_says_what_the_client_does():
    """Jeton en Bearer ; délai de lecture de 60 s, celui du client ; le rythme des écritures d'Attio (25 par seconde),
    que toute fonction admet ; sonde par la liste des objets ; ni clé de la plateforme ni en-tête constant."""
    connector = _description()["connector"]
    assert connector["base_url"] == AttioClient.BASE_URL
    assert connector["auth"] == {"kind": "bearer", "token": "api_key"}
    assert connector["credential"] == [{"name": "api_key", "label": "Access token", "secret": True}]
    sent, _ = _call_the_client("list_objects", {})
    assert sent["headers"]["Authorization"] == "Bearer attio-k"
    assert sent["timeout"] == (10, connector["timeout_s"]) == attio_client._HTTP_TIMEOUT
    assert connector["rate_limit"] == {"requests": 25, "seconds": 1}
    assert connector["modes"] == ["byo_user", "byo_org"]
    assert connector["probe"] == {"function": "list_objects", "non_empty": ["data"]}
    assert "headers" not in connector and "query_arrays" not in connector


def test_each_function_takes_the_arguments_its_client_method_names():
    for name, function in _functions().items():
        parameters = _parameters(name)
        left_out = set(ARGUMENTS_LEFT_OUT.get(name, {}))
        properties = set(function["input"]["properties"])
        assert properties == (set(parameters) - left_out) | ARGUMENTS_ADDED.get(name, set()), name
        without_default = {p for p, v in parameters.items() if v.default is inspect.Parameter.empty}
        assert set(function["input"].get("required", [])) == (
            without_default | ARGUMENTS_ADDED.get(name, set()) | REQUIRED_HERE.get(name, set())), name
    assert set(ARGUMENTS_LEFT_OUT) <= set(FUNCTIONS) and set(REQUIRED_HERE) <= set(FUNCTIONS)


def test_each_argument_goes_where_the_client_sends_it():
    for name, function in _functions().items():
        for arguments in (_every_argument(name, function), _required(name, function)):
            jsonschema.validate(arguments, function["input"])
            sent, _ = _call_the_client(name, arguments)
            assert _client_view(sent) == _described(name, function, arguments), (name, arguments)


def test_each_example_sends_what_the_client_sends_for_it():
    for name, function in _functions().items():
        for example in function["examples"]:
            jsonschema.validate(example["input"], function["input"])
            sent, _ = _call_the_client(name, example["input"])
            assert _client_view(sent) == _described(name, function, example["input"]), (name, example["title"])


def test_what_the_client_fills_is_never_a_declared_default_nor_required():
    functions = _functions()
    for name, fills in CLIENT_FILLS.items():
        properties = functions[name]["input"]["properties"]
        assert all("default" not in properties[a] for a in fills), name
        assert not set(fills) & set(functions[name]["input"].get("required", [])), name
        assert {a: _parameters(name)[a].default for a in fills} == fills, name


def test_where_the_schema_is_narrower_than_the_client_it_is_named():
    functions = _functions()
    for name, cases in NARROWER.items():
        for case in cases:
            assert not _valid(functions[name], case), (name, case)
            _call_the_client(name, case)


def test_what_the_client_refuses_the_schema_refuses():
    functions = _functions()
    for name, cases in CLIENT_REFUSES.items():
        for case in cases:
            assert not _valid(functions[name], case), (name, case)
            with pytest.raises(ValueError):
                _call_the_client(name, case)


def test_reads_writes_and_deletes_are_classified_and_each_delete_is_confirmed():
    functions = _functions()
    assert {c: {n for n, f in functions.items() if f["class"] == c} for c in CLASSES} == CLASSES
    assert set().union(*CLASSES.values()) == set(FUNCTIONS)
    for name, function in functions.items():
        method = function["call"]["method"]
        if function["class"] == "read":
            assert method == ("POST" if name in POST_READS else "GET"), name
        assert (method == "DELETE") == (function["class"] == "sensitive"), name
        assert ("confirm" in function) == (function["class"] == "sensitive"), name
        assert "act" not in function, name
        if "confirm" in function:
            for argument in function["input"]["required"]:
                assert "{" + argument + "}" in function["confirm"]["summary"], name


def test_only_the_meetings_page_by_cursor_and_each_call_costs_one_request():
    for name, function in _functions().items():
        assert function["cost"] == {"per": "request"}, name
        if name != "list_meetings":
            assert "pagination" not in function, name
    meetings = _functions()["list_meetings"]
    assert meetings["pagination"] == {"kind": "cursor", "request_param": "cursor",
                                      "next": "pagination.next_cursor", "max_pages": 10}
    assert meetings["output"] == {"items": "data"}


def test_the_filters_are_personal_and_nothing_else():
    """Un filtre de fiche porte un courriel, un nom ou un numéro : donnée personnelle ; aucun autre argument."""
    for name, function in _functions().items():
        properties = function["input"]["properties"]
        assert sorted(a for a, s in properties.items() if s.get("personal") is True) == PERSONAL.get(name, []), name
        others = {a: s for a, s in properties.items() if a not in PERSONAL.get(name, [])}
        assert '"personal"' not in json.dumps(others), name


def test_no_address_that_opens_content_reaches_the_agent_description_and_client():
    """L'adresse vidéo d'un enregistrement (signée, une heure) et celle de l'avatar d'un membre ouvrent leur contenu
    sans connexion : la description les retire (`output.strip`), le client de même ; le reste demeure."""
    functions = _functions()
    stripped = {n for n, f in functions.items() if "strip" in f.get("output", {})}
    assert stripped == set(ADDRESSES)
    for name, (path, shape) in ADDRESSES.items():
        function = functions[name]
        assert function["output"]["strip"] == [path], name
        assert "never given" in function["description"], name
        key = path.split(".")[1]
        one = {"id": {"workspace_id": "w-0"}, "status": "completed", key: "https://files.example.test/x"}
        answer = {"data": [one, dict(one)] if shape == "list" else one}
        shaped = _shaped(answer, function["output"]["strip"])
        assert "files.example.test" not in str(shaped) and "w-0" in str(shaped), name
        _, returned = _call_the_client(name, _required(name, function), answer)
        assert returned == shaped, name
        sample = function["output"]["sample"]
        assert key in str(sample) and key not in str(_shaped(sample, function["output"]["strip"])), name


def test_the_401_marks_the_account_and_429_and_5xx_are_retried_as_oto_1_says():
    """Le client ne nomme aucun refus (`UpstreamHTTPError` sur tout statut hors 2xx). Le 401 dit un jeton invalide :
    il marque `credential_rejected` ; le 403 dit un droit ou une offre, pas une clé. Le 429 et les 5xx se rejouent."""
    errors = _description()["connector"]["errors"]
    assert [(e["status"], e["code"], e["marks_account"]) for e in errors if "marks_account" in e] == [
        (401, "key_refused", "credential_rejected")]
    assert not [e for e in errors if "body" in e]
    assert {e["code"] for e in errors if e["retryable"]} == {"rate_limited", "upstream_unavailable"}
    assert next(e for e in errors if e["code"] == "upstream_unavailable")["status"] == [500, 502, 503, 504]
    assert not [f for f in _functions().values() if "refusals" in f]
    transport = inspect.getsource(AttioClient._request)
    assert "UpstreamHTTPError.from_response" in transport


def test_what_stays_in_the_client_is_named_in_the_description():
    """Chaque méthode laissée au client, et l'argument `query`, sont nommés dans l'en-tête du fichier."""
    header = ATTIO.read_text(encoding="utf-8").split("\nconnector:")[0]
    for name in LEFT_OUT:
        assert name in header, name
        assert name not in _functions(), name
    assert "query argument of search_records" in header


def test_the_typescript_output_and_the_python_table():
    checked = check(_description(), ATTIO)
    module = connector_module(checked)
    for name in _functions():
        assert f'name: "attio.{name}",' in module.source, name
    assert not module.skipped
    table = python.declared([checked])["attio"]
    assert set(table) == set(_functions())
    assert DECLARED.get("attio") == table, "oto/connectors/declared.py is out of date: run `python -m fabrique`"
