"""La description `allo` 1.1.0 : aucune adresse d'enregistrement ne sort vers l'agent.

Les lectures d'un appel (`list_conversations` sous `last_item`, `search_conversation_items`, `get_conversation_item`,
`get_conversation_items`) retirent par `output.strip` `recording_url`, `recording_download_url` (signée, 48 heures) et
son échéance ; l'audio se rend en fichier par `get_call_recording` (`output.file`, lien signé de 60 minutes téléchargé
sans authentification), qui remplace `get_recording_link`. Même règle que `aircall` 1.1.0
(docs/conception/format-de-description.md, « Retirer de la sortie », « Fichiers »).
"""
from __future__ import annotations

import copy

import jsonschema
import yaml

from fabrique import python
from fabrique.descriptions import CONNECTORS, check
from fabrique.typescript import connector_module, function_source
from oto.connectors.declared import DECLARED
from test_strip_cases import shaped

ALLO = CONNECTORS / "allo" / "connector.yaml"
ADDRESS_FIELDS = ["recording_url", "recording_download_url", "recording_download_expires_at"]
CALL_READS = {"list_conversations": "data.last_item", "search_conversation_items": "data",
              "get_conversation_item": "data", "get_conversation_items": "data"}
FILE = {"from": "url", "path": "data.url", "auth": "none", "types": {"mp3": ["audio/mpeg", "audio/mp3"]},
        "name": {"template": "call-{item_id}-recording.mp3"}, "max_bytes": 52_428_800}


def _description() -> dict:
    return copy.deepcopy(yaml.safe_load(ALLO.read_text(encoding="utf-8")))


def _fn(description: dict, name: str) -> dict:
    return next(f for f in description["functions"] if f["name"] == name)


def _addresses(value) -> list[str]:
    if isinstance(value, dict):
        return [a for v in value.values() for a in _addresses(v)]
    if isinstance(value, list):
        return [a for v in value for a in _addresses(v)]
    return [value] if isinstance(value, str) and "://" in value else []


def test_the_description_is_version_1_1_0_and_passes_the_fabrique():
    description = _description()
    assert description["connector"]["version"] == "1.1.0"
    check(description, ALLO)


def test_the_signed_link_is_no_function_any_more():
    names = {f["name"] for f in _description()["functions"]}
    assert "get_recording_link" not in names and "get_call_recording" in names


def test_each_call_read_strips_every_address_field_and_keeps_the_whole_answer():
    description = _description()
    for name, prefix in CALL_READS.items():
        output = _fn(description, name)["output"]
        assert "items" not in output, f"{name}: the whole answer is kept (pagination included)"
        assert output["strip"] == [f"{prefix}.{field}" for field in ADDRESS_FIELDS], name
        assert "recording url" not in _fn(description, name)["description"], name


def test_no_address_reaches_the_agent_from_the_sample_and_pagination_stays():
    description = _description()
    for name in CALL_READS:
        output = _fn(description, name)["output"]
        sample = output["sample"]
        assert _addresses(sample), f"{name}: the sample carries the addresses it proves stripped"
        assert _addresses(shaped(sample, output)) == [], name
    for name in ("list_conversations", "search_conversation_items"):
        output = _fn(description, name)["output"]
        assert "pagination" in shaped(output["sample"], output), name


def test_the_recording_is_a_file_from_the_signed_link():
    function = _fn(_description(), "get_call_recording")
    assert function["class"] == "read"
    assert function["input"]["required"] == ["item_id"]
    assert function["call"] == {"method": "GET", "path": "/v2/api/conversations/items/{item_id}/recording"}
    assert function["timeout_s"] == 120
    assert function["output"] == {"file": FILE}
    assert [(r["code"], r["when"], (r.get("body") or {}).get("equals")) for r in function["refusals"]] == [
        ("recording_not_found", 404, ["RECORDING_NOT_FOUND"]),
        ("call_not_found", 404, None),
        ("recording_access_denied", 403, ["RECORDING_ACCESS_DENIED"]),
        ("recording_download_restricted", 403, ["RECORDING_DOWNLOAD_RESTRICTED"]),
    ]


def test_send_sms_takes_exactly_one_sender_and_costs_a_request():
    function = _fn(_description(), "send_sms")
    schema = function["input"]
    valid = {"to": "+33199000001", "message": "Bonjour"}
    jsonschema.validate(valid | {"sender_id": "MyCompany"}, schema)
    jsonschema.validate(valid | {"from_number": "+33199000000"}, schema)
    for wrong in (valid, valid | {"sender_id": "MyCompany", "from_number": "+33199000000"},
                  valid | {"sender_id": "MyCompany", "message": "x" * 1001}):
        try:
            jsonschema.validate(wrong, schema)
        except jsonschema.ValidationError:
            continue
        raise AssertionError(f"accepted: {sorted(wrong)}")
    assert function["cost"] == {"per": "request"}


def test_no_error_message_names_a_function():
    description = _description()
    names = {f["name"] for f in description["functions"]}
    for error in description["connector"]["errors"]:
        assert not any(name in error["message"] for name in names), error["code"]


def test_the_typescript_output_carries_the_paths_and_the_file():
    checked = check(_description(), ALLO)
    module = connector_module(checked)
    assert "example.test" not in module.source and "sample" not in module.source
    functions = {f["name"]: f for f in checked.data["functions"]}
    for name, prefix in CALL_READS.items():
        strip = ", ".join(f'"{prefix}.{field}"' for field in ADDRESS_FIELDS)
        assert f"output: {{ strip: [{strip}] }}" in function_source("allo", functions[name])
    source = function_source("allo", functions["get_call_recording"])
    assert ('  output: { file: { from: "url", path: "data.url", auth: "none", '
            'types: {"mp3": ["audio/mpeg", "audio/mp3"]}, name: { template: "call-{item_id}-recording.mp3" }, '
            'maxBytes: 52428800 } },\n') in source
    assert "timeoutMs: 120000" in source


def test_the_python_table_declares_the_file_with_its_timeout():
    table = python.declared([check(_description(), ALLO)])["allo"]
    assert table["get_call_recording"] == {"file": FILE, "timeout_s": 120}
    assert table["send_sms"] == {"cost": {"per": "request"}}
    assert DECLARED["allo"] == table, "oto/connectors/declared.py is out of date: run `python -m fabrique`"
