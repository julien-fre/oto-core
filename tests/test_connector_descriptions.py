"""Les fichiers de description de connecteur respectent leur schéma.

Chaque `connectors/<nom>/connector.yaml` est validé contre
`connectors/connector.schema.json` (JSON Schema 2020-12), et chaque exemple d'une
fonction contre le schéma d'entrée de cette fonction. Des variantes invalides du
fichier Sellsy prouvent que la validation refuse ce qu'elle doit refuser.
"""
from __future__ import annotations

import copy
import json
import pathlib

import pytest
import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

ROOT = pathlib.Path(__file__).resolve().parent.parent / "connectors"
SCHEMA = json.loads((ROOT / "connector.schema.json").read_text(encoding="utf-8"))
DESCRIPTIONS = sorted(ROOT.glob("*/connector.yaml"))


def _load(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _validate(description: dict) -> None:
    Draft202012Validator(SCHEMA).validate(description)
    for function in description["functions"]:
        validator = Draft202012Validator(function["input"])
        for example in function["examples"]:
            validator.validate(example["input"])


def test_schema_is_valid_json_schema():
    Draft202012Validator.check_schema(SCHEMA)


def test_sellsy_description_is_present():
    assert ROOT / "sellsy" / "connector.yaml" in DESCRIPTIONS


@pytest.mark.parametrize("path", DESCRIPTIONS, ids=lambda p: p.parent.name)
def test_description_is_valid(path):
    description = _load(path)
    _validate(description)
    assert description["connector"]["name"] == path.parent.name


def _sellsy() -> dict:
    return copy.deepcopy(_load(ROOT / "sellsy" / "connector.yaml"))


def _drop_class(d):
    del d["functions"][0]["class"]


def _unknown_key(d):
    d["connector"]["unknown"] = True


def _call_and_handwritten(d):
    d["functions"][0]["handwritten"] = {
        "python": {"module": "oto.tools.sellsy.client", "function": "list_estimates"},
        "typescript": {"file": "sellsy.ts", "export": "listEstimates"},
    }


def _neither_call_nor_handwritten(d):
    del d["functions"][1]["call"]


def _sensitive_without_confirm(d):
    d["functions"][0]["class"] = "sensitive"


def _input_not_strict(d):
    d["functions"][0]["input"]["additionalProperties"] = True


def _no_examples(d):
    d["functions"][0]["examples"] = []


def _example_outside_input(d):
    d["functions"][0]["examples"][0]["input"]["limit"] = 1000


def _example_unknown_argument(d):
    d["functions"][1]["examples"][0]["input"]["nope"] = 1


def _embed_not_documented(d):
    d["functions"][1]["examples"][0]["input"]["embed"] = ["owner"]


def _auth_missing_token_url(d):
    del d["connector"]["auth"]["token_url"]


def _credential_missing(d):
    del d["connector"]["credential"]


def _quota_without_platform(d):
    d["connector"]["quota"] = {"per_month": 1000}


def _bad_version(d):
    d["connector"]["version"] = "1.0"


def _bad_exposure(d):
    d["exposure"]["mode"] = "per_tool"


def _output_schema_not_strict(d):
    d["functions"][0]["output"]["schema"]["additionalProperties"] = True


def _output_schema_no_properties(d):
    del d["functions"][0]["output"]["schema"]["properties"]


def _rate_limit_without_window(d):
    d["connector"]["rate_limit"] = {"requests": 4}


def _constant_header_not_a_string(d):
    d["connector"]["headers"] = {"X-Api-Version": 2}


def _unknown_encoding(d):
    d["functions"][0]["call"]["encode"] = {"limit": "csv"}


def _unknown_check_kind(d):
    d["functions"][0]["checks"] = [{"kind": "positive", "refusal": "invalid_request", "items": "limit", "fields": ["a", "b"]}]


def _expectation_without_path(d):
    d["functions"][1]["expect"] = [{"kind": "non_empty", "refusal": "estimate_not_found"}]


def _probe_extra_key(d):
    d["connector"]["probe"] = {"function": "get_estimate", "covers": "quota"}


def _empty_stop_flag(d):
    d["functions"][0]["pagination"]["more"] = ""


def _client_auth_missing(d):
    del d["connector"]["auth"]["client_auth"]


def _token_url_and_token_urls(d):
    d["connector"]["auth"]["token_urls"] = {"setting": "region", "values": {"us": "https://a.example", "eu": "https://b.example"}}


def _base_url_and_base_urls(d):
    d["connector"]["base_urls"] = {"setting": "region", "values": {"us": "https://a.example", "eu": "https://b.example"}}


def _single_choice(d):
    d["connector"]["settings"] = [{"name": "region", "label": "Region", "type": "choice", "choices": ["us"]}]


def _text_without_pattern(d):
    d["connector"]["settings"] = [{"name": "domain", "label": "Domain", "type": "text"}]


def _text_pattern_not_anchored(d):
    d["connector"]["settings"] = [{"name": "domain", "label": "Domain", "type": "text", "pattern": "[a-z]+"}]


def _url_setting_with_choices(d):
    d["connector"]["settings"] = [{"name": "server", "label": "Server", "type": "url", "choices": ["a", "b"]}]


def _template_trailing_slash(d):
    d["connector"]["base_url"] = "https://{domain}.example.net/"


def _api_key_query_with_prefix(d):
    d["connector"]["auth"] = {"kind": "api_key", "in": "query", "name": "key", "prefix": "Key ", "key": "client_id"}


def _api_key_without_place(d):
    d["connector"]["auth"] = {"kind": "api_key", "name": "X-Key", "key": "client_id"}


def _oauth2_user(d, **changes):
    d["connector"]["auth"] = {
        "kind": "oauth2_user", "authorize_url": "https://login.example/authorize", "token_url": "https://login.example/token",
        "client_auth": "body", "refresh": "refresh_token", "rotates": False,
        "identity": {"function": "list_estimates", "path": "data"},
    } | changes
    del d["connector"]["credential"]


def _oauth2_user_with_token_credential(d):
    _oauth2_user(d)
    d["connector"]["credential"] = [{"name": "access_token", "label": "Access token", "secret": True}]


def _oauth2_user_with_client_id(d):
    _oauth2_user(d, client_id="client_id")


def _oauth2_user_without_identity(d):
    _oauth2_user(d)
    del d["connector"]["auth"]["identity"]


def _rotates_without_refresh_token(d):
    _oauth2_user(d, refresh="none")


def _exchange_without_its_grant(d):
    _oauth2_user(d, refresh="exchange")
    del d["connector"]["auth"]["rotates"]


def _authorize_param_set_by_the_host(d):
    _oauth2_user(d, authorize_params={"redirect_uri": "https://evil.example"})


def _unknown_pkce(d):
    _oauth2_user(d, pkce="plain")


def test_oauth2_user_mutation_base_is_valid():
    """Les variantes `oauth2_user` ci-dessous partent d'une description valide : chacune n'échoue que par sa faute."""
    description = _sellsy()
    _oauth2_user(description)
    _validate(description)


@pytest.mark.parametrize("mutate", [
    _drop_class, _unknown_key, _call_and_handwritten, _neither_call_nor_handwritten,
    _sensitive_without_confirm, _input_not_strict, _no_examples, _example_outside_input,
    _example_unknown_argument, _embed_not_documented, _auth_missing_token_url,
    _credential_missing, _quota_without_platform, _bad_version, _bad_exposure,
    _output_schema_not_strict, _output_schema_no_properties,
    _rate_limit_without_window, _constant_header_not_a_string, _unknown_encoding, _unknown_check_kind,
    _expectation_without_path, _probe_extra_key, _empty_stop_flag,
    _client_auth_missing, _token_url_and_token_urls, _base_url_and_base_urls, _single_choice, _text_without_pattern,
    _text_pattern_not_anchored, _url_setting_with_choices, _template_trailing_slash, _api_key_query_with_prefix,
    _api_key_without_place, _oauth2_user_with_token_credential, _oauth2_user_with_client_id,
    _oauth2_user_without_identity, _rotates_without_refresh_token, _exchange_without_its_grant,
    _authorize_param_set_by_the_host, _unknown_pkce,
], ids=lambda f: f.__name__.lstrip("_"))
def test_invalid_description_is_rejected(mutate):
    description = _sellsy()
    mutate(description)
    with pytest.raises(ValidationError):
        _validate(description)


# --- Niveaux d'accès (docs/conception/niveaux-d-acces.md) ----------------------------

READ = "Estimates.READ"
ALL = "Estimates.ALL"


def _with_levels(d):
    """Sellsy en consentement d'une personne, avec un niveau `read` et un niveau `full`."""
    _oauth2_user(d, access_levels={"read": {"scopes": [READ]}, "full": {"scopes": [ALL]}}, scope_implies={ALL: [READ]})
    for function in d["functions"]:
        function["scopes"] = [READ]


def test_access_levels_base_is_valid():
    """Les variantes ci-dessous partent d'une description à niveaux valide : chacune n'échoue que par sa faute."""
    description = _sellsy()
    _with_levels(description)
    _validate(description)


def test_scope_implies_is_optional():
    description = _sellsy()
    _with_levels(description)
    del description["connector"]["auth"]["scope_implies"]
    description["connector"]["auth"]["access_levels"]["full"]["scopes"] = [ALL, READ]
    _validate(description)


@pytest.mark.parametrize("path", [p for p in DESCRIPTIONS if "access_levels" not in _load(p)["connector"]["auth"]],
                         ids=lambda p: p.parent.name)
def test_connector_without_levels_declares_no_function_scopes(path):
    """Un connecteur sans niveaux ne change pas : ni `scope_implies`, ni `scopes` sur une fonction."""
    description = _load(path)
    assert "scope_implies" not in description["connector"]["auth"]
    assert all("scopes" not in function for function in description["functions"])


def _levels_and_scopes(d):
    _with_levels(d)
    d["connector"]["auth"]["scopes"] = [ALL]


def _levels_without_full(d):
    _with_levels(d)
    d["connector"]["auth"]["access_levels"] = {"read": {"scopes": [READ]}, "write": {"scopes": [ALL]}}


def _full_level_only(d):
    _with_levels(d)
    d["connector"]["auth"]["access_levels"] = {"full": {"scopes": [ALL]}}


def _level_without_scopes(d):
    _with_levels(d)
    d["connector"]["auth"]["access_levels"]["read"] = {}


def _level_with_empty_scopes(d):
    _with_levels(d)
    d["connector"]["auth"]["access_levels"]["read"]["scopes"] = []


def _level_unknown_key(d):
    _with_levels(d)
    d["connector"]["auth"]["access_levels"]["read"]["default"] = True


def _level_name_not_an_identifier(d):
    _with_levels(d)
    d["connector"]["auth"]["access_levels"]["Read only"] = {"scopes": [READ]}


def _scope_implies_without_levels(d):
    _oauth2_user(d, scopes=[ALL], scope_implies={ALL: [READ]})


def _scope_implies_empty(d):
    _with_levels(d)
    d["connector"]["auth"]["scope_implies"] = {ALL: []}


def _levels_outside_a_consent(d):
    d["connector"]["auth"]["access_levels"] = {"read": {"scopes": [READ]}, "full": {"scopes": [ALL]}}


def _function_scopes_without_levels(d):
    d["functions"][0]["scopes"] = [READ]


def _function_without_scopes_with_levels(d):
    _with_levels(d)
    del d["functions"][1]["scopes"]


def _function_with_empty_scopes(d):
    _with_levels(d)
    d["functions"][1]["scopes"] = []


@pytest.mark.parametrize("mutate", [
    _levels_and_scopes, _levels_without_full, _full_level_only, _level_without_scopes, _level_with_empty_scopes,
    _level_unknown_key, _level_name_not_an_identifier, _scope_implies_without_levels, _scope_implies_empty,
    _levels_outside_a_consent, _function_scopes_without_levels, _function_without_scopes_with_levels,
    _function_with_empty_scopes,
], ids=lambda f: f.__name__.lstrip("_"))
def test_invalid_access_levels_are_rejected(mutate):
    description = _sellsy()
    mutate(description)
    with pytest.raises(ValidationError):
        _validate(description)


# --- Identité lue à une adresse complète --------------------------------------------

USERINFO = "https://openid.example/userinfo"


def _with_url_identity(d):
    """Sellsy à niveaux, l'identité lue sur un service d'identité commun, dont chaque niveau demande les droits."""
    _with_levels(d)
    auth = d["connector"]["auth"]
    auth["identity"] = {"url": USERINFO, "path": "email", "scopes": ["openid", "email"]}
    for level in auth["access_levels"].values():
        level["scopes"] += ["openid", "email"]


def test_url_identity_base_is_valid():
    description = _sellsy()
    _with_url_identity(description)
    _validate(description)


def _url_identity_without_scopes(d):
    _with_url_identity(d)
    del d["connector"]["auth"]["identity"]["scopes"]


def _url_identity_with_empty_scopes(d):
    _with_url_identity(d)
    d["connector"]["auth"]["identity"]["scopes"] = []


def _url_identity_with_a_function(d):
    _with_url_identity(d)
    d["connector"]["auth"]["identity"]["function"] = "list_estimates"


def _url_identity_not_https(d):
    _with_url_identity(d)
    d["connector"]["auth"]["identity"]["url"] = "http://openid.example/userinfo"


def _url_identity_with_a_query(d):
    _with_url_identity(d)
    d["connector"]["auth"]["identity"]["url"] = USERINFO + "?fields=email"


def _url_identity_with_a_template(d):
    _with_url_identity(d)
    d["connector"]["auth"]["identity"]["url"] = "https://{domain}.example/userinfo"


def _url_identity_without_path(d):
    _with_url_identity(d)
    del d["connector"]["auth"]["identity"]["path"]


@pytest.mark.parametrize("mutate", [
    _url_identity_without_scopes, _url_identity_with_empty_scopes, _url_identity_with_a_function, _url_identity_not_https,
    _url_identity_with_a_query, _url_identity_with_a_template, _url_identity_without_path,
], ids=lambda f: f.__name__.lstrip("_"))
def test_invalid_url_identity_is_rejected(mutate):
    description = _sellsy()
    mutate(description)
    with pytest.raises(ValidationError):
        _validate(description)


# --- Compte de l'hôte et compte rattaché ---------------------------------------------

IDENTITY = {"name": "account_id", "label": "Hosted account", "pattern": "^[A-Za-z0-9_-]{1,64}$"}


def _hosted(d):
    """Sellsy, chaque champ du credential fourni par l'hôte, et un compte rattaché cité par l'adresse de base."""
    for field in d["connector"]["credential"]:
        field["holder"] = "host"
    d["connector"]["account_identity"] = dict(IDENTITY)
    d["connector"]["base_url"] += "/{account_id}"


def test_hosted_account_base_is_valid():
    """Les variantes ci-dessous partent d'une description valide : chacune n'échoue que par sa faute."""
    description = _sellsy()
    _hosted(description)
    _validate(description)


def test_holder_defaults_to_account():
    description = _sellsy()
    description["connector"]["credential"][0]["holder"] = "account"
    _validate(description)


def _holder_unknown(d):
    _hosted(d)
    d["connector"]["credential"][0]["holder"] = "organisation"


def _host_holder_in_a_consent(d):
    _oauth2_user(d)
    d["connector"]["credential"] = [{"name": "api_key", "label": "API key", "secret": True, "holder": "host"}]


def _identity_pattern_not_anchored(d):
    _hosted(d)
    d["connector"]["account_identity"]["pattern"] = "[A-Za-z0-9_-]+"


def _identity_name_not_an_identifier(d):
    _hosted(d)
    d["connector"]["account_identity"]["name"] = "Account-Id"


def _identity_without_pattern(d):
    _hosted(d)
    del d["connector"]["account_identity"]["pattern"]


def _identity_unknown_key(d):
    _hosted(d)
    d["connector"]["account_identity"]["default"] = "abc"


@pytest.mark.parametrize("mutate", [
    _holder_unknown, _host_holder_in_a_consent, _identity_pattern_not_anchored, _identity_name_not_an_identifier,
    _identity_without_pattern, _identity_unknown_key,
], ids=lambda f: f.__name__.lstrip("_"))
def test_invalid_hosted_account_is_rejected(mutate):
    description = _sellsy()
    mutate(description)
    with pytest.raises(ValidationError):
        _validate(description)


def test_act_is_a_boolean():
    description = _sellsy()
    description["functions"][0]["act"] = False
    _validate(description)
    description["functions"][0]["act"] = "no"
    with pytest.raises(ValidationError):
        _validate(description)


# --- Signal de refus du service ------------------------------------------------------


def _signal(d, **entry):
    """Une entrée de la table d'erreurs qui marque le compte, sous une condition sur le corps."""
    d["connector"]["errors"].insert(0, {"status": 400, "code": "key_refused", "message": "The key is refused.", "retryable": False,
                                        "body": {"path": "error.code", "equals": ["invalid_key", 190, True]},
                                        "marks_account": "credential_rejected", **entry})


def test_account_signal_base_is_valid():
    """Les variantes ci-dessous partent d'une description valide : chacune n'échoue que par sa faute."""
    description = _sellsy()
    _signal(description)
    description["functions"][0].setdefault("refusals", []).append(
        {"code": "credits_spent", "when": 402, "message": "Credits spent.", "marks_account": "quota_exhausted"})
    _validate(description)


@pytest.mark.parametrize("mutate", [
    lambda d: _signal(d, marks_account="revoked"),
    lambda d: _signal(d, body={"path": "error.code"}),
    lambda d: _signal(d, body={"path": "error.code", "equals": []}),
    lambda d: _signal(d, body={"path": "error.code", "equals": [{"code": 1}]}),
    lambda d: _signal(d, body={"path": "error.code", "equals": ["a"], "contains": "b"}),
    lambda d: _signal(d, body={"path": "", "equals": ["a"]}),
], ids=["unknown_mark", "body_without_equals", "equals_empty", "equals_not_a_scalar", "body_unknown_key", "empty_path"])
def test_invalid_account_signal_is_rejected(mutate):
    description = _sellsy()
    mutate(description)
    with pytest.raises(ValidationError):
        _validate(description)


# --- Sonde à solde ---------------------------------------------------------------------


def _balance(d, **balance):
    """Une sonde qui lit le solde d'un compte payant."""
    d["connector"]["probe"] = {"function": "list_estimates", "balance": {"path": "credits.remaining", "min": 1, "unit": "credits", **balance}}


def test_probe_balance_base_is_valid():
    """Les variantes ci-dessous partent d'une description valide : chacune n'échoue que par sa faute."""
    description = _sellsy()
    _balance(description)
    _validate(description)
    _balance(description, path="accounts.0.balance", min=0.5)
    _validate(description)
    _balance(description, min=0)
    _validate(description)


@pytest.mark.parametrize("mutate", [
    lambda d: _balance(d, path=""),
    lambda d: _balance(d, path=".credits"),
    lambda d: _balance(d, path="credits."),
    lambda d: _balance(d, path="credits..remaining"),
    lambda d: _balance(d, path="credits remaining"),
    lambda d: _balance(d, min="1"),
    lambda d: _balance(d, min=-1),
    lambda d: _balance(d, unit=""),
    lambda d: _balance(d, covers="quota"),
    lambda d: d["connector"].update(probe={"function": "list_estimates", "balance": {"path": "credits", "unit": "credits"}}),
    lambda d: d["connector"].update(probe={"function": "list_estimates", "balance": {"path": "credits", "min": 1}}),
], ids=["empty_path", "leading_dot", "trailing_dot", "empty_segment", "space_in_path", "min_not_a_number", "min_negative",
        "empty_unit", "unknown_key", "without_min", "without_unit"])
def test_invalid_probe_balance_is_rejected(mutate):
    description = _sellsy()
    mutate(description)
    with pytest.raises(ValidationError):
        _validate(description)


# --- Délai propre à une fonction -------------------------------------------------------


def test_function_timeout_base_is_valid():
    """Même type et mêmes bornes que le délai du connecteur ; l'égalité avec lui est une règle de la fabrique."""
    description = _sellsy()
    description["functions"][0]["timeout_s"] = 1
    _validate(description)
    description["functions"][0]["timeout_s"] = 300
    _validate(description)


@pytest.mark.parametrize("value", [0, -5, 1.5, "60", None, 301],
                         ids=["zero", "negative", "not_an_integer", "text", "null", "above_300"])
def test_invalid_function_timeout_is_rejected(value):
    description = _sellsy()
    description["functions"][0]["timeout_s"] = value
    with pytest.raises(ValidationError):
        _validate(description)


def test_connector_timeout_has_the_same_bounds():
    description = _sellsy()
    description["connector"]["timeout_s"] = 300
    _validate(description)
    description["connector"]["timeout_s"] = 301
    with pytest.raises(ValidationError):
        _validate(description)
