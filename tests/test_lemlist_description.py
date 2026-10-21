"""La description `lemlist` 1.0.0 : celle du client existant (`oto.tools.lemlist`), sans rien y changer.

Une fonction par méthode du client qui envoie une seule requête à `api.lemlist.com/api`, sous son nom, avec ses noms
d'arguments et les clés que le client envoie à lemlist (chemin, query, corps, parties d'un multipart). Restent hors du
fichier, au client écrit à la main : les corps qui sont un argument entier, le corps en tableau nu, les query à clés
libres (les variables d'un lead), les compositions et aides locales, les routes choisies selon un argument, la relève
d'enrichissement (un 404 y est une réponse), les exports CSV et la connexion d'une boîte par ses mots de passe. Les
gardes ci-dessous lisent le client lui-même : un endpoint, un argument ou une clé qu'il ajoute sans la description fait
échouer le test ; une écriture servie du côté lecture aussi.
"""
from __future__ import annotations

import base64
import copy
import inspect
import json
import re
from unittest import mock

import jsonschema
import yaml

from fabrique import python
from fabrique.descriptions import CONNECTORS, check
from fabrique.typescript import connector_module
from oto.connectors.declared import DECLARED
from oto.tools.lemlist import client as lemlist_client
from oto.tools.lemlist.client import LemlistClient

LEMLIST = CONNECTORS / "lemlist" / "connector.yaml"

_BODY_IS_THE_ARGUMENT = "the body is an argument itself (a dict sent as is)"
# Les méthodes publiques du client qui ne sont pas une requête unitaire que le format sait dire, et pourquoi.
LEFT_OUT = {
    **{name: _BODY_IS_THE_ARGUMENT for name in (
        "update_campaign", "add_step", "update_step", "update_ab_variant", "update_schedule", "update_lead",
        "update_draft", "update_lemwarm_settings", "update_deliverability_alert", "upsert_contact", "upsert_company",
        "create_lead")},
    "update_task": "the body is the data argument, with the task id added to it",
    "update_watch_list": "the body is the data argument, with the watch list id added to it",
    "add_lead": "the body is the lead argument, its email taken out into the path",
    "bulk_enrich": "the body is a bare array of items",
    "add_lead_variables": "query parameters with free keys, the variables",
    "update_lead_variables": "query parameters with free keys, the variables",
    "delete_lead_variables": "query parameters with free keys, the variable names",
    "list_all_campaigns": "a composition: pages walked, and a truncated flag",
    "get_campaign_tree": "a composition: the campaign and its sequences, rebuilt as a tree",
    "save_campaign_tree": "a composition, written to a local file",
    "load_campaign_tree": "local: reads a file",
    "sync_campaign": "a composition, written to a local file",
    "find_step": "local: walks a tree",
    "get_first_email": "local: walks a tree",
    "get_emails": "local: walks a tree",
    "print_tree": "local: prints a tree",
    "get_sequence_steps": "a composition: the sequences, then one picked locally",
    "get_all_leads": "a composition: the CSV export, parsed",
    "get_campaign_stats": "a composition: one page of activities, counted locally",
    "sync_activities": "a composition: pages walked and filtered locally",
    "status": "a composition: one page of campaigns, counted, and errors caught",
    "unsubscribe_lead": "delete_lead without action, the same request",
    "mark_lead_interested": "the route depends on whether campaign_id is given",
    "mark_lead_not_interested": "the route depends on whether campaign_id is given",
    "get_enrichment": "a 404 is an answer (enrichmentStatus not-found), not an error",
    "export_leads": "a CSV export",
    "export_unsubscribes": "a CSV export",
    "export_unsubscribed_variables": "a CSV export",
    "export_unsubscribed_contacts": "a CSV export",
    "export_contact_list": "a CSV export",
    "connect_email_account": "the SMTP and IMAP passwords of a mailbox would be arguments, which the host journals",
}
# Les arguments d'une méthode que sa fonction ne prend pas, et pourquoi.
ARGUMENTS_LEFT_OUT = {
    "list_campaigns": {"sort_order": "the client adds sortBy=createdAt with it, a constant only when given"},
    "list_schedules": {"sort_order": "the client adds sortBy=createdAt with it, a constant only when given"},
    "create_campaign": {"auto_review": "turns adding a lead into a send; oto 1 serves it apart",
                        "auto_review_conditions": "goes with auto_review"},
    "enrich": {"webhook_url": "lemlist posts the result to an address chosen by the caller"},
    "enrich_lead": {"webhook_url": "lemlist posts the result to an address chosen by the caller"},
    "get_contact_messages": {"mark_as_read": "it writes on a read"},
    "export_campaign_leads": {"format": "the constant json: the CSV form is an export"},
    "upload_lead_audio": {"filename": "the host names the part after the transit file"},
}
# Ce que le client envoie quand l'appel ne le donne pas, sans que lemlist l'exige : pas un défaut déclaré, l'hôte
# n'envoyant rien pour un argument absent.
CLIENT_FILLS = {"get_activities": {"limit": 100, "offset": 0}}
# Ce que le client pose et que lemlist exige : exigé par le schéma, l'agent le donne.
REQUIRED_WHERE_THE_CLIENT_FILLS = {
    "create_schedule": {"timezone", "start", "end", "weekdays"},
    "create_watch_list": {"filters", "segment_type", "signal_processing_type", "activate"},
    "list_tasks": {"filters"},
    "delete_ab_variant": {"variant"},
    "attach_inbox_labels": {"append"},
    "export_campaign_leads": {"state"},
}
# Ce que l'appel du client doit donner pour envoyer les constantes de la description.
CLIENT_GIVEN = {"export_campaign_leads": {"format": "json"}}
# Les drapeaux qui ne partent que vrais, comme le client les envoie (`const: true`).
ONLY_TRUE = {
    "enrich": {"find_email", "verify_email", "linkedin_enrichment", "find_phone"},
    "enrich_lead": {"find_email", "verify_email", "linkedin_enrichment", "find_phone"},
    "delete_company": {"force"},
}
# Les booléens en query, que le client écrit true ou false (`_query`), comme l'hôte.
QUERY_BOOLEANS = {
    "list_contacts": "not_in_any_campaign", "get_activities": "is_first", "add_webhook": "is_first",
}
# Ce que fait chaque fonction : une écriture mal classée est un défaut grave.
CLASSES = {
    "read": {
        "list_campaigns", "get_campaign", "get_campaign_statutes", "get_sequences", "get_ab_variant",
        "list_schedules", "get_schedule", "get_campaign_schedules", "get_lead", "get_lead_by_email",
        "get_campaign_leads", "get_activities", "get_campaign_stats_v2", "get_batch_campaign_stats",
        "get_campaign_reports", "list_unsubscribes", "get_unsubscribe", "list_unsubscribed_variables",
        "get_unsubscribed_variable", "get_contact_subscription", "list_contacts", "get_contact",
        "list_contact_lists", "list_companies", "get_company_notes", "list_inboxes", "get_contact_messages",
        "list_inbox_labels", "get_inbox_label", "list_drafts", "get_draft", "list_tasks", "list_watch_lists",
        "get_watch_list_filters", "get_watch_list_filter_values", "get_watch_list_library", "get_watch_list_history",
        "get_signals", "start_campaign_export", "get_campaign_export_status", "export_campaign_leads",
        "search_people_database", "search_companies_database", "get_database_filters", "list_personas", "get_team",
        "get_team_credits", "get_team_senders", "get_user", "get_user_channels", "get_team_crm_users",
        "get_crm_filters", "list_fields", "get_lemwarm_settings", "list_deliverability_alerts",
        "get_deliverability_alert", "list_webhooks",
    },
    "write": {
        "create_campaign", "pause_campaign", "duplicate_campaign", "create_schedule", "associate_schedule",
        "pause_lead", "upload_lead_audio", "enrich", "enrich_lead", "create_contact_list", "manage_contact_list",
        "create_company_note", "create_inbox_label", "attach_inbox_labels", "remove_inbox_labels", "create_draft",
        "create_task", "ignore_tasks", "create_persona", "test_email_account", "start_lemwarm", "pause_lemwarm",
        "create_deliverability_alert",
    },
    "sensitive": {
        # Envoie, ou lance ce qui envoie, à une vraie personne.
        "start_campaign", "launch_lead", "resume_lead", "send_inbox_email", "send_linkedin_message",
        "send_whatsapp_message", "select_ab_winner", "create_ab_variant", "import_leads_from_crm",
        "create_watch_list", "push_external_signals",
        # Désinscrit ou réinscrit.
        "add_unsubscribe", "delete_unsubscribe", "unsubscribe_variable", "resubscribe_variable",
        "bulk_unsubscribe_variables", "unsubscribe_contact", "resubscribe_contact",
        # Supprime.
        "delete_step", "delete_ab_variant", "delete_schedule", "delete_lead", "delete_activity_recording_transcript",
        "delete_contact", "delete_company", "delete_draft", "delete_watch_list", "delete_persona",
        "disconnect_email_account", "delete_deliverability_alert", "delete_webhook",
        # Des données partent vers une adresse que donne l'appel.
        "add_webhook", "set_campaign_export_email",
    },
}
# Les lectures servies en POST (des statistiques, des recherches dans la base partagée).
POST_READS = {"get_batch_campaign_stats", "search_people_database", "search_companies_database"}
REQUEST = {"per": "request"}
WRITING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# Une valeur par argument, pour un appel qui les donne tous.
VALUES = {
    "campaign_id": "cam_example1", "limit": 20, "offset": 40, "page": 2, "status": "running",
    "created_by": "usr_example1", "name": "Q4 outreach", "timezone": "Europe/Paris", "sequence_id": "seq_example1",
    "step_id": "stp_example1", "variant": "A", "schedule_id": "skd_example1", "start": "09:00", "end": "18:00",
    "weekdays": [1, 2, 3], "seconds_to_wait": 600, "public": True, "email": "marie@example.test", "action": "remove",
    "lead_id": "lea_example1", "version": "v2", "state": "all", "crm": "hubspot", "user_id": "usr_example1",
    "filter_id": "42", "filter_type": "list", "deduplicate": True, "audio": "00000000-0000-4000-8000-000000000000",
    "linkedin_url": "https://www.example.test/in/marie", "first_name": "Marie", "last_name": "Martin",
    "company_name": "Example", "company_domain": "example.test", "find_email": True, "verify_email": True,
    "linkedin_enrichment": True, "find_phone": True, "type": "emailsReplied", "is_first": True,
    "min_date": "2026-10-01", "max_date": "2026-10-31", "start_date": "2026-10-01T00:00:00Z",
    "end_date": "2026-10-31T00:00:00Z", "activity_id": "act_example1", "send_user": "usr_example1|me@example.test",
    "ab_selected": "B", "channels": ["email", "linkedin"], "campaign_ids": ["cam_example1", "cam_example2"],
    "value": "example.test", "values": ["marie@example.test", "example.test"], "contact_id": "ctc_example1",
    "ids_or_emails": ["ctc_example1", "paul@example.test"], "search": "martin", "list_id": "lst_example1",
    "not_in_any_campaign": True, "company_id": "cpy_example1", "company_linkedin_url": "https://www.example.test/c/x",
    "company_salesnav_url": "https://www.example.test/s/x", "field_rejection_reason": "invalid",
    "id_or_email": "marie@example.test", "contact_ids": ["ctc_example1", "ctc_example2"],
    "ids_or_domains": ["example.test", "example.net"], "fields": ["name", "domain"], "sort_by": "createdAt",
    "sort_order": "desc", "crm_sync_status": "synced", "force": True, "note": "Met at the trade show.",
    "skip": 10, "label_id": "lbl_example1", "label_name": "Hot", "label_ids": ["lbl_example1"], "append": False,
    "draft_owner": "usr_example1", "draft_id": "drf_example1", "channel": "email", "content": "<p>Hello</p>",
    "subject": "Next week", "cc": ["cc@example.test"], "attachments": [{"name": "a.pdf"}],
    "reply_to_activity_id": "act_example2", "source_metadata": {"origin": "agent"}, "send_user_id": "usr_example1",
    "send_user_email": "me@example.test", "send_user_mailbox_id": "mbx_example1", "message": "Thanks!",
    "send_user_whatsapp_account_id": "wa_example1", "filters": [{"filterId": "location", "in": ["Paris"]}],
    "task_type": "phone", "assigned_to": "usr_example1", "due_date": "2026-10-22T09:00:00Z",
    "record_id": "ctc_example1", "title": "Call back", "priority": "0", "images": ["https://img.example.test/a.png"],
    "videos": ["https://img.example.test/a.mp4"], "ids": ["tsk_example1"], "emoji": "x",
    "segment_type": "all", "signal_processing_type": "push_to_campaign", "signal_opportunity_template": {"k": "v"},
    "persona_id": "pdp_example1", "activate": False, "watch_list_id": "wl_example1", "query": "Paris",
    "received_at_from": "2026-10-01", "received_at_to": "2026-10-31",
    "contact": {"linkedinUrl": "https://www.example.test/in/marie"},
    "company": {"domain": "example.test", "name": "Example"}, "custom_fields": {"source": "fair"},
    "export_id": "exp_example1", "size": 25, "excludes": ["ctc_example1"], "mode": "leads",
    "entity": "contact", "source": "custom", "email_account_id": "mbx_example1", "user_mailbox_id": "mbx_example1",
    "alert_id": "alr_example1", "widget": "outreach", "metric": "spamRate", "severity": "critical",
    "scope": "global", "threshold": 5, "comparison_operator": "above", "period_days": 3, "period_mode": "rolling",
    "scope_entities": ["mbx_example1"], "channel_config": {"email": {"enabled": False}}, "recheck_delay_hours": 6,
    "target_url": "https://hooks.example.test/lemlist", "secret": "signing-text", "zap_id": "z1",
    "hook_id": "hok_example1",
}
# Un argument du même nom qui n'a pas le même vocabulaire d'une fonction à l'autre.
VALUES_OF = {
    "create_watch_list": {"type": "companyIsHiring"},
    "get_crm_filters": {"type": "contact"},
    "get_watch_list_filters": {"type": "companyIsHiring"},
    "get_team_senders": {"state": "running"},
}


def _description() -> dict:
    return copy.deepcopy(yaml.safe_load(LEMLIST.read_text(encoding="utf-8")))


def _functions() -> dict[str, dict]:
    return {f["name"]: f for f in _description()["functions"]}


def _public_methods() -> set[str]:
    return {n for n, _ in inspect.getmembers(LemlistClient, inspect.isfunction) if not n.startswith("_")}


def _client_endpoints() -> dict[str, tuple[str, str]]:
    """Chaque méthode publique qui appelle `_request` une seule fois, sa méthode HTTP et son chemin, tel qu'écrit."""
    endpoints = {}
    for name in _public_methods():
        source = inspect.getsource(getattr(LemlistClient, name))
        found = re.findall(r'self\._request\(\s*"([A-Z]+)",\s*f?"([^"]+)"', source)
        if len(found) == 1:
            endpoints[name] = (found[0][0], "/" + found[0][1])
    return endpoints


class _Answer:
    status_code = 200
    ok = True
    headers: dict = {}
    content = b"{}"
    text = "{}"

    def json(self):
        return {}


def _sent_by_the_client(name: str, arguments: dict) -> dict:
    """Ce que la méthode du client envoie, sans réseau : méthode, adresse, query, corps JSON, parties, en-têtes."""
    sent = []

    def request(method, url, **kwargs):
        sent.append({"method": method, "url": url, "params": kwargs.get("params") or {}, "json": kwargs.get("json"),
                     "files": kwargs.get("files"), "headers": kwargs.get("headers") or {}})
        return _Answer()

    with mock.patch.object(lemlist_client.requests, "request", request), \
            mock.patch.object(lemlist_client.time, "sleep", lambda _s: None):
        getattr(LemlistClient(api_key="k"), name)(**arguments)
    assert len(sent) == 1, name
    return sent[0]


def _in_query(value):
    """Une valeur en query comme l'écrit l'hôte : liste jointe par des virgules (`query_arrays: comma`), booléen en
    minuscules, nombre en texte."""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, list):
        return ",".join(str(v) for v in value)
    return str(value)


def _described(name: str, function: dict, arguments: dict) -> tuple:
    """La requête que dit la description : méthode, adresse, query, corps JSON, noms des parties fichier. Un argument
    encodé en JSON est comparé par sa valeur, l'espacement de la sérialisation étant libre."""
    call = function["call"]
    given = {**CLIENT_FILLS.get(name, {}), **arguments}
    path = call["path"].format(**{a: given[a] for a in re.findall(r"{(\w+)}", call["path"])})
    encoded = set(call.get("encode", {}))
    query = {k: str(v) for k, v in call.get("constants", {}).get("query", {}).items()}
    for api, argument in call.get("query", {}).items():
        if argument in given:
            query[api] = given[argument] if argument in encoded else _in_query(given[argument])
    body = None
    if "body" in call or "body" in call.get("constants", {}):
        body = {**call.get("constants", {}).get("body", {}),
                **{api: given[a] for api, a in call.get("body", {}).items() if a in given}}
    files = sorted(call.get("files", {}))
    return call["method"], LemlistClient.BASE_URL + path, query, body, files


def _client_view(function: dict, sent: dict) -> tuple:
    encoded_keys = {api for api, a in function["call"].get("query", {}).items()
                    if a in function["call"].get("encode", {})}
    query = {k: (json.loads(v) if k in encoded_keys else _in_query(v)) for k, v in sent["params"].items()}
    return sent["method"], sent["url"], query, sent["json"], sorted(sent["files"] or {})


def _values(name: str, function: dict) -> dict:
    values = {**VALUES, **VALUES_OF.get(name, {})}
    return {argument: values[argument] for argument in function["input"]["properties"]}


def test_the_description_is_version_1_0_0_and_passes_the_fabrique():
    description = _description()
    assert description["connector"]["version"] == "1.0.0"
    check(description, LEMLIST)


def test_each_single_request_method_of_the_client_is_a_function_of_the_same_name_method_and_path():
    functions = _functions()
    endpoints = _client_endpoints()
    assert {n: (f["call"]["method"], f["call"]["path"]) for n, f in functions.items()} == {
        n: endpoints[n] for n in functions}
    assert set(endpoints) - set(functions) <= set(LEFT_OUT)


def test_what_the_description_leaves_out_is_named_with_its_reason():
    assert _public_methods() - set(_functions()) == set(LEFT_OUT)
    assert not set(LEFT_OUT) & set(_functions())


def test_the_connector_says_what_the_client_does():
    """Clé seule en mot de passe d'une authentification Basic, identifiant vide : `Basic base64(":" + clé)`."""
    connector = _description()["connector"]
    assert connector["base_url"] == LemlistClient.BASE_URL
    assert connector["auth"] == {"kind": "basic", "password": "api_key"}
    assert connector["credential"] == [{"name": "api_key", "label": "API key", "secret": True}]
    headers = _sent_by_the_client("get_team", {})["headers"]
    assert headers["Authorization"] == "Basic " + base64.b64encode(b":k").decode()
    assert connector["timeout_s"] == lemlist_client._HTTP_TIMEOUT[1], "the client waits 60 s for an answer"
    assert connector["query_arrays"] == "comma"
    assert connector["rate_limit"] == {"requests": 20, "seconds": 2}, "lemlist's published rate, per key"
    assert "platform" not in connector["modes"], "campaigns, leads and the inbox act on the team behind the key"
    assert connector["probe"] == {"function": "list_campaigns"}
    assert "self.list_campaigns(" in inspect.getsource(LemlistClient.status), "the client probes by list_campaigns"


def test_each_function_takes_the_arguments_of_its_client_method():
    for name, function in _functions().items():
        parameters = set(inspect.signature(getattr(LemlistClient, name)).parameters) - {"self"}
        properties = set(function["input"]["properties"])
        assert properties <= parameters, name
        assert parameters - properties == set(ARGUMENTS_LEFT_OUT.get(name, {})), name
    assert set(ARGUMENTS_LEFT_OUT) <= set(_functions())


def test_each_argument_goes_where_the_client_sends_it():
    for name, function in _functions().items():
        arguments = _values(name, function)
        jsonschema.validate(arguments, function["input"])
        sent = _sent_by_the_client(name, {**arguments, **CLIENT_GIVEN.get(name, {})})
        assert _client_view(function, sent) == _described(name, function, arguments), name


def test_each_example_sends_what_the_client_sends_for_it():
    for name, function in _functions().items():
        for example in function["examples"]:
            jsonschema.validate(example["input"], function["input"])
            sent = _sent_by_the_client(name, {**example["input"], **CLIENT_GIVEN.get(name, {})})
            assert _client_view(function, sent) == _described(name, function, example["input"]), (name, example["title"])


def test_what_the_client_fills_and_lemlist_requires_is_required_and_never_a_declared_default():
    functions = _functions()
    for name, arguments in REQUIRED_WHERE_THE_CLIENT_FILLS.items():
        signature = inspect.signature(getattr(LemlistClient, name)).parameters
        assert all(signature[a].default is not inspect.Parameter.empty for a in arguments), name
        assert arguments <= set(functions[name]["input"]["required"]), name
        assert all("default" not in functions[name]["input"]["properties"][a] for a in arguments), name
    for name, fills in CLIENT_FILLS.items():
        signature = inspect.signature(getattr(LemlistClient, name)).parameters
        assert {a: signature[a].default for a in fills} == fills, name
        assert all("default" not in functions[name]["input"]["properties"][a] for a in fills), name


def test_the_flags_the_client_sends_only_when_true_are_const_true():
    functions = _functions()
    for name, flags in ONLY_TRUE.items():
        properties = functions[name]["input"]["properties"]
        assert {f: properties[f].get("const") for f in flags} == {f: True for f in flags}, name
        required = {a: VALUES[a] for a in functions[name]["input"].get("required", [])}
        others = {f: False for f in flags}
        if name in ("enrich", "enrich_lead"):
            others["find_email"] = True
        sent = _sent_by_the_client(name, {**required, **others})
        assert {k for k, v in sent["params"].items() if v != "true"} <= {"webhookUrl"}, name


def test_the_query_booleans_go_true_or_false_as_the_host_writes_them():
    """Vrai ou faux, le client écrit le booléen en query comme l'hôte : `true` ou `false`, jamais `True`."""
    functions = _functions()
    for name, argument in QUERY_BOOLEANS.items():
        assert functions[name]["input"]["properties"][argument]["type"] == "boolean", name
        required = {a: VALUES[a] for a in functions[name]["input"].get("required", [])}
        api = next(k for k, v in functions[name]["call"]["query"].items() if v == argument)
        for value, written in ((True, "true"), (False, "false")):
            sent = _sent_by_the_client(name, {**required, argument: value})
            assert sent["params"][api] == written == _in_query(value), (name, value)


def test_reads_and_writes_are_classified_and_every_write_is_served_on_the_act_side():
    functions = _functions()
    assert {c: {n for n, f in functions.items() if f["class"] == c} for c in CLASSES} == CLASSES
    for name, function in functions.items():
        method = function["call"]["method"]
        acts = method in WRITING_METHODS and name not in POST_READS
        assert acts == (function["class"] != "read"), name
        assert ("confirm" in function) == (function["class"] == "sensitive"), name
        # Retirer des libellés d'une conversation se refait d'un appel : une écriture, pas une suppression.
        if (method == "DELETE" and name != "remove_inbox_labels") or name.startswith(
                ("send_", "delete_", "unsubscribe", "resubscribe")):
            assert function["class"] == "sensitive", name
        assert function.get("act", function["class"] != "read") == (name != "create_draft" and acts), name


def test_each_call_costs_one_request_and_nothing_is_paginated():
    for name, function in _functions().items():
        assert function["cost"] == REQUEST, name
        assert "pagination" not in function, name


def test_only_the_401_marks_the_account_as_a_refused_key():
    """Le client lève la même erreur pour tout statut au-delà de 400 : il ne nomme aucun refus. Marquer le 401 n'est
    donc pas plus large que lui, et un 401 de lemlist veut dire « clé refusée » : seule cette ligne marque le compte,
    en `credential_rejected` ; aucune ne lit le corps. Un 5xx n'est pas rejouable."""
    errors = _description()["connector"]["errors"]
    marking = [e for e in errors if "marks_account" in e]
    assert marking == [{"status": 401, "code": "key_refused", "retryable": False,
                        "marks_account": "credential_rejected", "message": marking[0]["message"]}]
    assert not [e for e in errors if "body" in e]
    assert not [r for f in _functions().values() for r in f.get("refusals", [])]
    assert "status_code ==" not in inspect.getsource(LemlistClient)
    assert {e["code"] for e in errors if e["retryable"]} == {"rate_limited"}


def test_the_typescript_output_and_the_python_table():
    checked = check(_description(), LEMLIST)
    module = connector_module(checked)
    for name in _functions():
        assert f'name: "lemlist.{name}",' in module.source, name
    for name in LEFT_OUT:
        assert f'"lemlist.{name}"' not in module.source, name
    table = python.declared([checked])["lemlist"]
    assert set(table) == set(_functions())
    assert DECLARED.get("lemlist") == table, "oto/connectors/declared.py is out of date: run `python -m fabrique`"
