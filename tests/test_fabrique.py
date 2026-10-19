"""La fabrique : règles hors schéma, JSON Schema d'entrée recopié, ajouts du format, refus, sortie à jour.

La sortie TypeScript commitée (`ts/src/`) doit être celle que la fabrique produit des
descriptions : sinon `test_committed_output_is_current` échoue et dit de lancer
`python -m fabrique`.
"""
from __future__ import annotations

import copy
import pathlib
import re

import pytest
import yaml

from fabrique.build import generate, stale
from fabrique.descriptions import CONNECTORS, DescriptionError, check, served
from fabrique.typescript import NotGenerated, connector_module, function_source, js_block

SELLSY = CONNECTORS / "sellsy" / "connector.yaml"
NOTION = CONNECTORS / "notion" / "connector.yaml"
PENNYLANE = CONNECTORS / "pennylane" / "connector.yaml"


def _load(path: pathlib.Path) -> dict:
    return copy.deepcopy(yaml.safe_load(path.read_text(encoding="utf-8")))


# --- Sortie commitée -------------------------------------------------------------


def test_committed_output_is_current():
    assert stale(generate()) == [], "ts/src is out of date: run `python -m fabrique`"


def test_every_description_generates_a_module():
    result = generate()
    assert {m.connector for m in result.modules} == {p.parent.name for p in CONNECTORS.glob("*/connector.yaml")}
    assert all(m.generated for m in result.modules)


def test_every_function_is_generated():
    result = generate()
    assert [s.function for m in result.modules for s in m.skipped] == []


# --- Règle 1 : un argument, un seul endroit ---------------------------------------


def _get_estimate(d):
    return next(f for f in d["functions"] if f["name"] == "get_estimate")


@pytest.mark.parametrize("mutate, message", [
    (lambda d: _get_estimate(d)["call"].update(body={"id": "id"}), "goes to two places"),
    (lambda d: _get_estimate(d)["call"].update(path="/estimates/{estimate_id}"), "the path names 'estimate_id'"),
    (lambda d: _get_estimate(d)["call"]["query"].update(other="nope"), "names 'nope', which is not an input argument"),
    (lambda d: _get_estimate(d)["call"].pop("query"), "go nowhere in call"),
    (lambda d: _get_estimate(d)["input"].update(required=[]), "path argument 'id' must be required"),
    (lambda d: d["functions"][0]["pagination"].update(request_param="cursor"), "request_param 'cursor' is not an input argument"),
], ids=["two_places", "path_unknown", "query_unknown", "unplaced", "optional_path", "pagination_unknown"])
def test_argument_rule_refuses(mutate, message):
    description = _load(SELLSY)
    mutate(description)
    with pytest.raises(DescriptionError, match=message):
        check(description, SELLSY)


# --- Règle 2 : une référence de auth nomme un champ de credential -----------------


@pytest.mark.parametrize("path, reference", [(SELLSY, "client_secret"), (NOTION, "token")])
def test_auth_reference_must_name_a_credential_field(path, reference):
    description = _load(path)
    description["connector"]["auth"][reference] = "missing_field"
    with pytest.raises(DescriptionError, match=rf"auth\.{reference} names 'missing_field', which is not a credential field"):
        check(description, path)


def test_schema_violation_is_refused_before_the_rules():
    description = _load(SELLSY)
    del description["functions"][0]["class"]
    with pytest.raises(DescriptionError, match="does not match the description schema"):
        check(description, SELLSY)


def test_valid_descriptions_pass():
    for path in sorted(CONNECTORS.glob("*/connector.yaml")):
        check(_load(path), path)


# --- Génération : refus nommés, pagination -----------------------------------------


def test_input_schema_is_copied_as_is():
    """Aucune traduction : le schéma servi est celui de la description, ancres YAML résolues, quels que soient ses mots-clés."""
    function = next(f for f in _load(NOTION)["functions"] if f["name"] == "edit_page_markdown")
    source = function_source("notion", function)
    assert "  schema: " + js_block(function["input"], 1) + ",\n" in source
    assert '"oneOf": [' in source and '"not": {' in source


@pytest.mark.parametrize("mutate", [
    lambda i: i.update(additionalProperties=True),
    lambda i: i.pop("additionalProperties"),
    lambda i: i.update(type="array"),
], ids=["open", "no_additional_properties", "not_an_object"])
def test_root_not_strict_is_skipped_and_named(mutate):
    """La seule exigence que la fabrique vérifie encore elle-même, au cas où le schéma du format la laisserait passer."""
    description = check(_load(NOTION), NOTION)
    mutate(description.data["functions"][0]["input"])
    module = connector_module(description)
    reason = "input: the root must be a strict object (type: object, additionalProperties: false)"
    assert [(s.function, s.reason) for s in module.skipped] == [("notion.search_workspace", reason)]
    assert f"// - notion.search_workspace: {reason}" in module.source
    assert "export const searchWorkspace" not in module.source
    assert "export const getPage" in module.source


def test_pagination_adds_its_arguments_and_refuses_a_clash():
    function = _load(NOTION)["functions"][0]
    source = function_source("notion", function)
    assert '"all_pages": {"type": "boolean"' in source and '"maximum": 10' in source
    function["input"]["properties"]["all_pages"] = {"type": "boolean"}
    with pytest.raises(NotGenerated, match="pagination adds"):
        function_source("notion", function)


def test_handwritten_function_is_not_generated():
    function = _load(NOTION)["functions"][0]
    del function["call"]
    function["handwritten"] = {"python": {"module": "m", "function": "f"}, "typescript": {"file": "f.ts", "export": "f"}}
    with pytest.raises(NotGenerated, match="handwritten"):
        function_source("notion", function)


# --- Ajouts du format : sortie ----------------------------------------------------


def _pennylane(name: str) -> dict:
    return next(f for f in _load(PENNYLANE)["functions"] if f["name"] == name)


def test_connector_carries_headers_rate_and_probe():
    notion = connector_module(check(_load(NOTION), NOTION)).source
    assert 'headers: {"Notion-Version": "2025-09-03"},' in notion
    pennylane = connector_module(check(_load(PENNYLANE), PENNYLANE)).source
    assert "rateLimit: { requests: 4, intervalMs: 1000 }," in pennylane
    assert 'probe: { function: "pennylane.get_company", nonEmpty: ["scopes"] },' in pennylane


def test_probe_carries_its_balance():
    """Une sonde à solde porte son chemin, son seuil et son unité ; une sonde sans solde ne change pas."""
    description = _load(PENNYLANE)
    _fn(description, "get_company").pop("cost")
    description["connector"]["probe"]["balance"] = {"path": "credits.remaining", "min": 1, "unit": "credits"}
    source = connector_module(check(description, PENNYLANE)).source
    assert ('probe: { function: "pennylane.get_company", nonEmpty: ["scopes"], '
            'balance: { path: "credits.remaining", min: 1, unit: "credits" } },') in source
    description["connector"]["probe"] = {"function": "get_company", "balance": {"path": "a.0.b", "min": 0.5, "unit": "EUR"}}
    source = connector_module(check(description, PENNYLANE)).source
    assert 'probe: { function: "pennylane.get_company", nonEmpty: [], balance: { path: "a.0.b", min: 0.5, unit: "EUR" } },' in source


def test_request_carries_constants_encoding_and_stop_flag():
    source = function_source("pennylane", _pennylane("list_customers"))
    assert 'encode: {"filter": "json"},' in source
    assert 'more: "has_more"' in source
    source = function_source("pennylane", _pennylane("create_customer_invoice"))
    assert 'constants: {"body": {"draft": true}},' in source


def test_checks_and_expectations_are_carried():
    source = function_source("pennylane", _pennylane("create_ledger_entry"))
    assert 'checks: [\n    { kind: "equal_sums", refusal: "entry_unbalanced", items: "ledger_entry_lines", fields: ["debit", "credit"] },' in source
    source = function_source("pennylane", _pennylane("get_quote_pdf_link"))
    assert 'expect: [\n    { kind: "non_empty", refusal: "pdf_missing", path: "public_file_url" },' in source


def test_delete_carries_its_body():
    source = function_source("pennylane", _pennylane("unletter_ledger_entry_lines"))
    assert 'method: "DELETE"' in source
    assert 'body: {"ledger_entry_lines": "ledger_entry_lines", "unbalanced_lettering_strategy": "unbalanced_lettering_strategy"},' in source


# --- Règles 3 à 5 : constantes, contrôles, sonde ------------------------------------


def _fn(d, name):
    return next(f for f in d["functions"] if f["name"] == name)


@pytest.mark.parametrize("path, mutate, message", [
    (PENNYLANE, lambda d: _fn(d, "create_customer_invoice")["call"]["constants"]["body"].update(label=True),
     "body 'label' is both a constant and an argument"),
    (NOTION, lambda d: d["connector"]["headers"].update(Authorization="x"),
     "header 'Authorization' is set twice"),
    (NOTION, lambda d: _fn(d, "get_page")["call"].update(constants={"headers": {"notion-version": "x"}}),
     "header 'notion-version' is set twice"),
    (PENNYLANE, lambda d: _fn(d, "get_product")["call"].update(encode={"product_id": "json"}),
     "encode names 'product_id', which is not placed in query, body or headers"),
    (PENNYLANE, lambda d: _fn(d, "create_ledger_entry")["checks"][0].update(refusal="nope"),
     "equal_sums names refusal 'nope', which the function does not declare"),
    (PENNYLANE, lambda d: _fn(d, "create_ledger_entry")["checks"][0].update(fields=["debit", "amount"]),
     "equal_sums needs 'ledger_entry_lines' to be a list argument whose items declare debit, amount"),
    (PENNYLANE, lambda d: _fn(d, "create_ledger_entry")["checks"][0].update(items="label"),
     "equal_sums needs 'label' to be a list argument"),
    (PENNYLANE, lambda d: _fn(d, "get_quote_pdf_link")["expect"][0].update(refusal="nope"),
     "non_empty names refusal 'nope'"),
    (PENNYLANE, lambda d: d["connector"]["probe"].update(function="nope"),
     "probe names 'nope', which is not a function of the connector"),
    (PENNYLANE, lambda d: d["connector"]["probe"].update(function="get_product"),
     "probe 'get_product' must be a read function with a call and no required argument"),
    (PENNYLANE, lambda d: d["connector"]["probe"].update(function="create_customer"),
     "probe 'create_customer' must be a read function"),
    (PENNYLANE, lambda d: d["connector"]["probe"].update(balance={"path": "credits.remaining", "min": 1, "unit": "credits"}),
     "probe 'get_company' reads a balance, so it must declare no cost"),
], ids=["constant_and_argument", "header_and_auth", "header_case", "encode_unplaced", "check_refusal",
        "check_fields", "check_not_a_list", "expect_refusal", "probe_unknown", "probe_required", "probe_write",
        "probe_balance_with_cost"])
def test_added_rules_refuse(path, mutate, message):
    description = _load(path)
    mutate(description)
    with pytest.raises(DescriptionError, match=re.escape(message)):
        check(description, path)


def test_probe_without_balance_may_cost():
    """Le coût n'est refusé qu'à la fonction d'une sonde qui lit un solde."""
    description = _load(PENNYLANE)
    assert _fn(description, "get_company")["cost"] == {"per": "request"}
    check(description, PENNYLANE)


# --- Comptes : réglages, adresses par réglage, clé en query, consentement ------------

TYPEFORM = CONNECTORS / "typeform" / "connector.yaml"
MICROSOFT = CONNECTORS / "microsoft" / "connector.yaml"


def _lucca_like(d):
    """Sellsy, l'adresse tirée d'un sous-domaine saisi par l'admin."""
    d["connector"]["settings"] = [{"name": "domain", "label": "Domain", "type": "text", "pattern": "^[a-z0-9-]+$"}]
    d["connector"]["base_url"] = "https://{domain}.example.net/api"


def _server_like(d):
    """Sellsy, l'adresse saisie en entier par l'admin, et le jeton demandé à cette adresse."""
    d["connector"]["settings"] = [{"name": "server", "label": "Server address", "type": "url"}]
    d["connector"]["base_url"] = "{server}/api"
    d["connector"]["auth"]["token_url"] = "{server}/connect/token"


def _consent(d, **changes):
    d["connector"]["auth"] = {
        "kind": "oauth2_user", "authorize_url": "https://login.example/authorize", "token_url": "https://login.example/token",
        "client_auth": "basic", "refresh": "refresh_token", "rotates": True,
        "identity": {"function": "list_estimates", "path": "data.0.owner"},
    } | changes
    del d["connector"]["credential"]


@pytest.mark.parametrize("mutate", [_lucca_like, _server_like], ids=["text_in_host", "url_at_head"])
def test_templates_over_settings_pass(mutate):
    description = _load(SELLSY)
    mutate(description)
    check(description, SELLSY)


def test_instance_url_from_the_token_passes_and_is_carried():
    description = _load(SELLSY)
    _consent(description, from_token=["instance_url"])
    description["connector"]["base_url"] = "{instance_url}/services/data/v62.0"
    source = connector_module(check(description, SELLSY)).source
    assert '"fromToken": ["instance_url"]' in source
    assert 'baseUrl: "{instance_url}/services/data/v62.0",' in source


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d["connector"].update(base_url="https://{domain}.example.net"),
     "base_url cites {domain}, which is not a declared setting (none declared)"),
    (lambda d: (_lucca_like(d), d["connector"].update(base_url="{domain}/api")),
     "base_url starts with {domain}, which is not a url setting"),
    (lambda d: (_server_like(d), d["connector"].update(base_url="https://api.example.net/{server}")),
     "base_url cites the url setting {server} elsewhere than at its head"),
    (lambda d: (_lucca_like(d), d["connector"]["auth"].update(token_url="https://{tenant}.example.net/token")),
     "auth.token_url cites {tenant}, which is not a declared setting (domain)"),
    (lambda d: (_lucca_like(d), d["connector"].update(base_url="https://api.example.net")),
     "setting(s) domain cited by no URL"),
    (lambda d: (_lucca_like(d), d["connector"]["settings"].append({"name": "client_id", "label": "x", "type": "url"})),
     "name(s) declared twice among credential, settings and from_token: client_id"),
    (lambda d: d["connector"].update(settings=[{"name": "region", "label": "Region", "type": "choice", "choices": ["us", "eu"], "default": "fr"}]),
     "setting 'region': default 'fr' is not one of its choices"),
    (lambda d: (_lucca_like(d), d["connector"].pop("base_url"), d["connector"].update(base_urls={"setting": "domain", "values": {"a": "https://a.example", "b": "https://b.example"}})),
     "base_urls.setting names 'domain', which is not a choice setting"),
    (lambda d: (d["connector"].update(settings=[{"name": "region", "label": "Region", "type": "choice", "choices": ["us", "eu"]}]),
                d["connector"].pop("base_url"),
                d["connector"].update(base_urls={"setting": "region", "values": {"us": "https://a.example", "fr": "https://b.example"}})),
     "base_urls.values must give a URL to each choice of 'region' (us, eu), and to nothing else"),
    (lambda d: (_consent(d, from_token=["instance_url"]), d["connector"]["auth"].update(token_url="{instance_url}/token")),
     "auth.token_url cites {instance_url}, which is not a declared setting (none declared)"),
    (lambda d: _consent(d, identity={"function": "get_estimate", "path": "id"}),
     "auth.identity 'get_estimate' must be a read function with a call and no required argument"),
    (lambda d: _consent(d, identity={"function": "nope", "path": "id"}),
     "auth.identity names 'nope', which is not a function of the connector"),
    (lambda d: (d["connector"].update(auth={"kind": "api_key", "in": "query", "name": "limit", "key": "client_id"})),
     "function list_estimates: query 'limit' is set twice (the authentication and the function)"),
], ids=["undeclared", "text_at_head", "url_not_at_head", "token_url_undeclared", "unused", "name_twice", "bad_default",
        "urls_on_text", "urls_not_each_choice", "token_from_token", "identity_required_argument", "identity_unknown",
        "query_key_clash"])
def test_account_rules_refuse(mutate, message):
    description = _load(SELLSY)
    mutate(description)
    with pytest.raises(DescriptionError, match=re.escape(message)):
        check(description, SELLSY)


def test_oauth2_user_without_credential_is_refused_by_the_schema():
    description = _load(SELLSY)
    _consent(description)
    description["connector"]["credential"] = [{"name": "refresh_token", "label": "Refresh token", "secret": True}]
    with pytest.raises(DescriptionError, match="does not match the description schema at connector"):
        check(description, SELLSY)


def test_connector_carries_settings_urls_and_consent():
    typeform = connector_module(check(_load(TYPEFORM), TYPEFORM)).source
    assert '"setting": "region", "values": {"us": "https://api.typeform.com"' in typeform
    assert '"choices": ["us", "eu", "eu2"]' in typeform and '"default": "us"' in typeform
    microsoft = connector_module(check(_load(MICROSOFT), MICROSOFT)).source
    for fragment in ('"kind": "oauth2_user"', '"clientAuth": "body"', '"refresh": "refresh_token"', '"rotates": true',
                     '"identity": {"function": "microsoft.get_me", "path": "userPrincipalName"}', "credential: [],"):
        assert fragment in microsoft
    sellsy = connector_module(check(_load(SELLSY), SELLSY)).source
    assert '"clientAuth": "body"' in sellsy and '"tokenRequest": "json"' in sellsy


# --- Règle 7 : niveaux d'accès (docs/conception/niveaux-d-acces.md) -----------------

GMAIL = CONNECTORS / "gmail" / "connector.yaml"
OUTPUT = CONNECTORS.parent / "ts" / "src"
READ = "Estimates.READ"
ALL = "Estimates.ALL"
SETTINGS = "Settings.READ"


def _levels(d, **changes):
    """Sellsy en consentement à deux niveaux : `full` accorde `Estimates.ALL`, qui implique `Estimates.READ`."""
    _consent(d, access_levels={"read": {"scopes": [READ, SETTINGS]}, "full": {"scopes": [ALL, SETTINGS]}},
             scope_implies={ALL: [READ]}, **changes)
    for function in d["functions"]:
        function["scopes"] = [READ]


def test_access_levels_pass_and_are_carried():
    description = _load(SELLSY)
    _levels(description)
    _fn(description, "get_estimate")["scopes"] = [READ, SETTINGS]
    module = connector_module(check(description, SELLSY))
    assert '"accessLevels": {' in module.source and '"read": {"scopes": ["Estimates.READ", "Settings.READ"]}' in module.source
    assert '"scopeImplies": {"Estimates.ALL": ["Estimates.READ"]}' in module.source
    assert '  class: "read",\n  act: false,\n  scopes: ["Estimates.READ", "Settings.READ"],\n  description: ' in module.source
    assert '"scopes":' not in module.source.split("auth: {")[1].split("accessLevels")[0]


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d["connector"]["auth"]["scope_implies"].update({"Records.ALL": [READ]}),
     "auth.scope_implies: 'Records.ALL' is the scope of no access level"),
    (lambda d: (d["connector"]["auth"]["access_levels"]["full"]["scopes"].append("Everything"),
                d["connector"]["auth"]["scope_implies"].update({"Everything": [ALL]})),
     "auth.scope_implies: 'Everything' implies a scope that implies Estimates.READ, which 'Everything' must then list too"),
    (lambda d: d["connector"]["auth"]["access_levels"]["read"]["scopes"].append("Users.READ"),
     "access level 'read' asks for Users.READ, which level 'full' does not cover"),
    (lambda d: _fn(d, "get_estimate").update(scopes=[READ, "Users.READ"]),
     "function get_estimate: scope(s) Users.READ not covered by level 'full'"),
    (lambda d: (d["connector"]["auth"]["access_levels"]["read"].update(scopes=[SETTINGS]),),
     "auth.identity 'list_estimates' is not served at access level 'read'"),
    (lambda d: (d["connector"].update(probe={"function": "list_estimates"}),
                d["connector"]["auth"].update(identity={"function": "list_estimates", "path": "data"}),
                d["connector"]["auth"]["access_levels"].update(support={"scopes": [SETTINGS]})),
     "auth.identity 'list_estimates' is not served at access level 'support'"),
], ids=["implies_unused", "implies_not_closed", "level_beyond_full", "function_beyond_full", "identity_not_served",
        "identity_not_served_at_every_level"])
def test_access_level_rule_refuses(mutate, message):
    description = _load(SELLSY)
    _levels(description)
    mutate(description)
    with pytest.raises(DescriptionError, match=re.escape(message)):
        check(description, SELLSY)


def test_probe_must_be_served_at_every_level():
    description = _load(SELLSY)
    _levels(description)
    description["connector"]["probe"] = {"function": "list_estimates"}
    _fn(description, "list_estimates")["scopes"] = [READ]
    check(description, SELLSY)
    description["connector"]["auth"]["identity"] = {"function": "list_estimates", "path": "data"}
    _fn(description, "list_estimates")["scopes"] = [ALL]
    with pytest.raises(DescriptionError, match=re.escape("auth.identity 'list_estimates' is not served at access level 'read'")):
        check(description, SELLSY)


def test_closed_implication_passes():
    """Un droit impliqué qui en implique d'autres : la clé qui l'implique les liste aussi, et la lecture en un pas suffit."""
    description = _load(SELLSY)
    _levels(description)
    auth = description["connector"]["auth"]
    auth["access_levels"]["full"]["scopes"] = ["Everything", SETTINGS]
    auth["access_levels"]["read"]["scopes"] = [ALL, SETTINGS]
    auth["scope_implies"] = {"Everything": [ALL, READ], ALL: [READ]}
    check(description, SELLSY)


def test_gmail_levels_serve_reads_at_read_and_everything_at_full():
    """Ce que l'hôte filtre : au niveau `read`, les lectures seules ; à `full`, tout, comme sans niveaux."""
    description = check(_load(GMAIL), GMAIL)
    auth = description.data["connector"]["auth"]
    levels, implies = auth["access_levels"], auth["scope_implies"]
    functions = description.data["functions"]
    at_read = {f["name"] for f in functions if served(f, levels["read"]["scopes"], implies)}
    assert at_read == {f["name"] for f in functions if f["class"] == "read"}
    assert all(served(f, levels["full"]["scopes"], implies) for f in functions)


@pytest.mark.parametrize("path", [p for p in sorted(CONNECTORS.glob("*/connector.yaml"))
                                  if "access_levels" not in yaml.safe_load(p.read_text(encoding="utf-8"))["connector"]["auth"]],
                         ids=lambda p: p.parent.name)
def test_connector_without_levels_is_unchanged(path):
    """Un connecteur sans niveaux sort à l'octet près comme avant : son module est celui qui est commité, sans `accessLevels`
    ni `scopes` de fonction."""
    module = connector_module(check(_load(path), path))
    assert "accessLevels" not in module.source and "scopeImplies" not in module.source
    assert "\n  scopes: " not in module.source
    assert module.source == (OUTPUT / f"{module.connector}.ts").read_text(encoding="utf-8")


# --- Identité lue à une adresse complète (règles 5 et 7) ----------------------------

SHEETS = CONNECTORS / "google_sheets" / "connector.yaml"
USERINFO = "https://openid.example/userinfo"
OPENID = ["openid", "email"]


def _url_identity(d, levels=True):
    if levels:
        _levels(d)
        for level in d["connector"]["auth"]["access_levels"].values():
            level["scopes"] += OPENID
    else:
        _consent(d, scopes=[READ, *OPENID])
    d["connector"]["auth"]["identity"] = {"url": USERINFO, "path": "email", "scopes": list(OPENID)}


@pytest.mark.parametrize("levels", [True, False], ids=["with_levels", "without_levels"])
def test_url_identity_passes_and_is_carried_as_is(levels):
    description = _load(SELLSY)
    _url_identity(description, levels)
    source = connector_module(check(description, SELLSY)).source
    assert '"identity": {"url": "https://openid.example/userinfo", "path": "email", "scopes": ["openid", "email"]}' in source


@pytest.mark.parametrize("levels, mutate, message", [
    (True, lambda d: d["connector"]["auth"]["access_levels"]["read"]["scopes"].remove("email"),
     "auth.identity 'https://openid.example/userinfo' is not served at access level 'read': its scopes (openid, email) are not all covered"),
    (True, lambda d: d["connector"]["auth"]["identity"].update(scopes=["openid", "profile"]),
     "auth.identity 'https://openid.example/userinfo' is not served at access level 'read'"),
    (False, lambda d: d["connector"]["auth"].update(scopes=[READ, "openid"]),
     "auth.identity needs email, which auth.scopes does not ask for"),
    (False, lambda d: d["connector"]["auth"].pop("scopes"),
     "auth.identity needs email, openid, which auth.scopes does not ask for"),
], ids=["level_without_identity_scope", "identity_scope_in_no_level", "scopes_without_identity_scope", "no_scopes"])
def test_url_identity_rules_refuse(levels, mutate, message):
    description = _load(SELLSY)
    _url_identity(description, levels)
    mutate(description)
    with pytest.raises(DescriptionError, match=re.escape(message)):
        check(description, SELLSY)


def test_sheets_identity_is_read_at_an_address_and_levels_split_reads():
    description = check(_load(SHEETS), SHEETS)
    auth = description.data["connector"]["auth"]
    assert auth["identity"] == {"url": "https://openidconnect.googleapis.com/v1/userinfo", "path": "email", "scopes": OPENID}
    levels, implies = auth["access_levels"], auth["scope_implies"]
    functions = description.data["functions"]
    assert {f["name"] for f in functions if served(f, levels["read"]["scopes"], implies)} == {
        f["name"] for f in functions if f["class"] == "read"}
    assert all(served(f, levels["full"]["scopes"], implies) for f in functions)


def test_microsoft_levels_serve_every_function_at_read():
    """Les treize fonctions de `microsoft` sont des lectures : le niveau `read` les sert toutes, avec les droits *.Read.All."""
    description = check(_load(MICROSOFT), MICROSOFT)
    auth = description.data["connector"]["auth"]
    assert "scopes" not in auth
    read = auth["access_levels"]["read"]["scopes"]
    assert not any("ReadWrite" in scope for scope in read)
    assert all(served(f, read, auth["scope_implies"]) for f in description.data["functions"])


# --- Règle 8 : compte de l'hôte et compte rattaché -----------------------------------

LINKEDIN = CONNECTORS / "linkedin_unipile" / "connector.yaml"
ACCOUNT_ID = "{account_id}"


def test_hosted_account_passes_and_is_carried():
    """Tous les champs du credential fournis par l'hôte : la description reste valide ; la sortie dit `holder` de chaque
    champ et l'identité du compte."""
    description = _load(LINKEDIN)
    assert all(field["holder"] == "host" for field in description["connector"]["credential"])
    source = connector_module(check(description, LINKEDIN)).source
    assert 'credential: [{"name": "api_key", "label": "Unipile API key", "secret": true, "holder": "host"}],' in source
    assert 'accountIdentity: {"name": "account_id", "label": "LinkedIn account", "pattern": "^[A-Za-z0-9_-]{1,64}$"},' in source
    assert 'baseUrl: "https://api.unipile.com/v2/{account_id}",' in source
    assert '"account_id"' not in source.split("export const connector")[0]


def test_holder_defaults_to_account_in_the_output():
    sellsy = connector_module(check(_load(SELLSY), SELLSY)).source
    assert '"secret": true, "holder": "account"}' in sellsy
    assert "accountIdentity" not in sellsy


@pytest.mark.parametrize("mutate", [
    lambda d: d["connector"].update(base_url="https://api.example.net/v2/{account_id}/linkedin"),
    lambda d: (d["connector"].update(settings=[{"name": "server", "label": "Server", "type": "url"}]),
               d["connector"].update(base_url="{server}/v2/{account_id}")),
    lambda d: (d["connector"].pop("base_url"),
               d["connector"].update(settings=[{"name": "region", "label": "Region", "type": "choice", "choices": ["us", "eu"]}]),
               d["connector"].update(base_urls={"setting": "region", "values": {
                   "us": "https://us.example.net/v2/{account_id}", "eu": "https://eu.example.net/v2/{account_id}"}})),
], ids=["in_the_path", "after_a_url_setting", "in_each_base_urls"])
def test_account_identity_after_the_host_passes(mutate):
    description = _load(LINKEDIN)
    mutate(description)
    check(description, LINKEDIN)


def _get_profile(d):
    return _fn(d, "get_profile")


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d["connector"].update(base_url="https://api.unipile.com/v2"),
     "base_url does not cite the account identity {account_id}"),
    (lambda d: (d["connector"].pop("base_url"),
                d["connector"].update(settings=[{"name": "region", "label": "Region", "type": "choice", "choices": ["us", "eu"]}]),
                d["connector"].update(base_urls={"setting": "region", "values": {
                    "us": "https://us.example.net/v2/{account_id}", "eu": "https://eu.example.net/v2"}})),
     "base_urls.values.eu does not cite the account identity {account_id}"),
    (lambda d: (_get_profile(d)["input"]["properties"].update(account_id={"type": "string"}),
                _get_profile(d)["call"]["query"].update(account_id="account_id")),
     "function get_profile: input argument 'account_id' bears the name of the account identity"),
    (lambda d: _get_profile(d)["call"].update(path="/users/{identifier}/{account_id}"),
     "function get_profile: the path cites the account identity {account_id}"),
    (lambda d: _get_profile(d)["call"].update(query={"account_id": "with_sections"}),
     "function get_profile: query parameter 'account_id' bears the name of the account identity"),
    (lambda d: _fn(d, "send_message")["call"].update(body={"account_id": "text"}),
     "function send_message: body parameter 'account_id' bears the name of the account identity"),
    (lambda d: _get_profile(d)["call"].update(headers={"Account_Id": "with_sections"}),
     "function get_profile: headers parameter 'account_id' bears the name of the account identity"),
    (lambda d: _get_profile(d)["call"].update(constants={"query": {"account_id": "x"}}),
     "function get_profile: constant query 'account_id' bears the name of the account identity"),
    (lambda d: d["connector"].update(settings=[{"name": "account_id", "label": "Account", "type": "text", "pattern": "^[a-z]+$"}]),
     "account_identity 'account_id' is also the name of a setting"),
    (lambda d: d["connector"]["credential"].append({"name": "account_id", "label": "Account", "secret": False}),
     "account_identity 'account_id' is also the name of a credential field"),
    (lambda d: d["connector"].update(base_url="{account_id}/v2"),
     "base_url cites the account identity {account_id} elsewhere than after the host"),
    (lambda d: d["connector"].update(base_url="https://{account_id}.unipile.com/v2"),
     "base_url cites the account identity {account_id} elsewhere than after the host"),
    (lambda d: (d["connector"].pop("base_url"),
                d["connector"].update(settings=[{"name": "region", "label": "Region", "type": "choice", "choices": ["us", "eu"]}]),
                d["connector"].update(base_urls={"setting": "region", "values": {
                    "us": "https://us.example.net/v2/{account_id}", "eu": "https://eu.example.net/{region}/{account_id}"}})),
     "base_urls.values cites {region}, which is not the account identity"),
    (lambda d: (d["connector"].update(auth={"kind": "oauth2_client_credentials", "token_url": "https://login.example/{account_id}/token",
                                            "token_request": "form", "client_auth": "body", "client_id": "api_key",
                                            "client_secret": "api_key"})),
     "auth.token_url cites the account identity {account_id}, which only the base URL cites"),
], ids=["not_cited", "not_cited_in_each_base_urls", "input_argument", "path_parameter", "query_parameter",
        "body_parameter", "header_parameter", "constant", "setting_name", "credential_name", "at_the_head", "in_the_host",
        "base_urls_cites_a_setting", "token_url"])
def test_account_identity_rule_refuses(mutate, message):
    description = _load(LINKEDIN)
    mutate(description)
    with pytest.raises(DescriptionError, match=re.escape(message)):
        check(description, LINKEDIN)


def test_base_urls_cite_nothing_without_an_account_identity():
    description = _load(SELLSY)
    description["connector"].pop("base_url")
    description["connector"]["settings"] = [{"name": "region", "label": "Region", "type": "choice", "choices": ["us", "eu"]}]
    description["connector"]["base_urls"] = {"setting": "region", "values": {
        "us": "https://us.example.net/{account_id}", "eu": "https://eu.example.net"}}
    with pytest.raises(DescriptionError, match=re.escape("base_urls.values cites {account_id}, which is not the account identity")):
        check(description, SELLSY)


# --- Règle 9 : `act`, ce qui engage ou détruit ---------------------------------------


@pytest.mark.parametrize("klass, declared, resolved", [
    ("read", None, False), ("write", None, True), ("sensitive", None, True),
    ("read", False, False), ("write", False, False), ("write", True, True), ("sensitive", True, True),
], ids=lambda v: str(v))
def test_act_resolves_from_the_class(klass, declared, resolved):
    function = _load(SELLSY)["functions"][1]
    function["class"] = klass
    if klass == "sensitive":
        function["confirm"] = {"summary": "Do it to {id}."}
    if declared is not None:
        function["act"] = declared
    assert f"  class: {klass!r},\n  act: {str(resolved).lower()},\n".replace("'", '"') in function_source("sellsy", function)


@pytest.mark.parametrize("klass, declared, message", [
    ("sensitive", False, "function get_estimate: a sensitive function cannot declare act: false"),
    ("read", True, "function get_estimate: a read function cannot declare act: true"),
], ids=["sensitive_not_act", "read_act"])
def test_act_rule_refuses(klass, declared, message):
    description = _load(SELLSY)
    function = _get_estimate(description)
    function["class"] = klass
    function["act"] = declared
    if klass == "sensitive":
        function["confirm"] = {"summary": "Do it to {id}."}
    with pytest.raises(DescriptionError, match=re.escape(message)):
        check(description, SELLSY)


def test_linkedin_sends_act_and_reads_do_not():
    module = connector_module(check(_load(LINKEDIN), LINKEDIN)).source
    for name in ("sendInvitation", "sendMessage"):
        assert f'export const {name} = defineFunction({{\n  name: ' in module
    assert module.count("  act: true,\n") == 2 and module.count("  act: false,\n") == 8


# --- Règle 10 : le signal de refus du service ----------------------------------------

META_ADS = CONNECTORS / "meta_ads" / "connector.yaml"
GRAPHQL_REFUSAL = {"path": "errors.0.extensions.code", "equals": ["UNAUTHENTICATED"]}


def _error(d, status):
    return next(e for e in d["connector"]["errors"] if e["status"] == status)


@pytest.mark.parametrize("mutate", [
    lambda d: _error(d, 402).update(marks_account="quota_exhausted"),
    lambda d: d["connector"]["errors"].insert(0, {"status": 200, "body": GRAPHQL_REFUSAL, "code": "key_refused",
                                                  "message": "The key is refused.", "retryable": False,
                                                  "marks_account": "credential_rejected"}),
    lambda d: d["connector"]["errors"].insert(0, {"status": [400, 403], "body": {"path": "error", "equals": ["invalid_key"]},
                                                  "code": "key_refused", "message": "The key is refused.", "retryable": False,
                                                  "marks_account": "credential_rejected"}),
    lambda d: _get_estimate(d)["refusals"].append({"code": "credits_spent", "when": 429, "message": "Credits spent.",
                                                   "body": {"path": "reason", "equals": ["monthly_quota"]},
                                                   "marks_account": "quota_exhausted"}),
], ids=["status_402", "graphql_under_200", "body_under_400_and_403", "refusal_body_under_429"])
def test_account_signal_passes_and_is_carried(mutate):
    description = _load(SELLSY)
    mutate(description)
    source = connector_module(check(description, SELLSY)).source
    assert "marksAccount: " in source


def test_meta_ads_marks_on_graph_codes_under_a_400_before_the_plain_400():
    errors = _load(META_ADS)["connector"]["errors"]
    assert errors[0] == {"status": 400, "body": {"path": "error.code", "equals": [190, 102]}, "code": "authorization_expired",
                         "retryable": False, "marks_account": "credential_rejected",
                         "message": errors[0]["message"]}
    assert errors[1]["status"] == 400 and "body" not in errors[1] and "marks_account" not in errors[1]
    source = connector_module(check(_load(META_ADS), META_ADS)).source
    assert 'body: {"path": "error.code", "equals": [190, 102]}, marksAccount: "credential_rejected" }' in source


def test_nothing_marks_by_default():
    sellsy = connector_module(check(_load(SELLSY), SELLSY)).source
    assert "marksAccount" not in sellsy and 'body: {"path"' not in sellsy


@pytest.mark.parametrize("mutate, message", [
    (lambda d: _error(d, [401, 403]).update(marks_account="credential_rejected"),
     "errors 'access_rejected': a 403 without a body condition cannot mark credential_rejected"),
    (lambda d: _error(d, 429).update(marks_account="quota_exhausted"),
     "errors 'rate_limited': a 429 without a body condition cannot mark quota_exhausted"),
    (lambda d: _error(d, 402).update(marks_account="quota_exhausted", retryable=True),
     "errors 'plan_quota_reached': an entry that marks the account is not retryable"),
    (lambda d: d["connector"]["errors"].insert(0, {"status": 200, "code": "key_refused", "message": "Refused.", "retryable": False}),
     "errors 'key_refused': a 2xx status needs a body condition"),
    (lambda d: d["connector"]["errors"].append({"status": 400, "body": {"path": "error", "equals": ["invalid_key"]},
                                                "code": "key_refused", "message": "Refused.", "retryable": False,
                                                "marks_account": "credential_rejected"}),
     "errors 'key_refused': its body condition comes after an entry without one for status 400, so it is never read"),
    (lambda d: _get_estimate(d)["refusals"].append({"code": "key_refused", "when": "the error code is invalid_key",
                                                    "message": "Refused.", "marks_account": "credential_rejected"}),
     "function get_estimate: refusal 'key_refused': a refusal with body or marks_account needs an HTTP status in when"),
    (lambda d: _get_estimate(d)["refusals"].append({"code": "key_refused", "when": "the error code is invalid_key",
                                                    "message": "Refused.", "body": {"path": "error", "equals": ["invalid_key"]}}),
     "function get_estimate: refusal 'key_refused': a refusal with body or marks_account needs an HTTP status in when"),
    (lambda d: _get_estimate(d)["refusals"].append({"code": "forbidden", "when": 403, "message": "Refused.",
                                                    "marks_account": "credential_rejected"}),
     "function get_estimate: refusal 'forbidden': a 403 without a body condition cannot mark credential_rejected"),
    (lambda d: _get_estimate(d)["refusals"].append({"code": "empty", "when": 204, "message": "Nothing."}),
     "function get_estimate: refusal 'empty': a 2xx status needs a body condition"),
], ids=["403_alone", "429_alone", "retryable", "2xx_without_body", "shadowed", "mark_on_text_when", "body_on_text_when",
        "refusal_403_alone", "refusal_2xx_without_body"])
def test_account_signal_rule_refuses(mutate, message):
    description = _load(SELLSY)
    mutate(description)
    with pytest.raises(DescriptionError, match=re.escape(message)):
        check(description, SELLSY)


# --- Règle 11 : le délai propre à une fonction ---------------------------------------


@pytest.mark.parametrize("own, connector", [(300, None), (10, None), (60, 120), (300, 120)],
                         ids=["longer_than_default", "shorter_than_default", "shorter", "longer"])
def test_function_timeout_passes_and_is_carried(own, connector):
    description = _load(SELLSY)
    if connector is None:
        description["connector"].pop("timeout_s", None)
    else:
        description["connector"]["timeout_s"] = connector
    _get_estimate(description)["timeout_s"] = own
    source = connector_module(check(description, SELLSY)).source
    assert f"  timeoutMs: {own * 1000},\n" in source
    assert f"  timeoutMs: {(connector or 30) * 1000},\n" in source


def test_function_without_timeout_carries_none():
    source = function_source("sellsy", _get_estimate(_load(SELLSY)))
    assert "timeoutMs" not in source


@pytest.mark.parametrize("connector", [None, 120], ids=["default", "declared"])
def test_function_timeout_equal_to_the_connector_is_refused(connector):
    description = _load(SELLSY)
    if connector is None:
        description["connector"].pop("timeout_s", None)
    else:
        description["connector"]["timeout_s"] = connector
    _get_estimate(description)["timeout_s"] = connector or 30
    with pytest.raises(DescriptionError, match=re.escape(
            f"function get_estimate: timeout_s {connector or 30} is the connector's timeout: declare none")):
        check(description, SELLSY)


def test_linkedin_company_page_has_its_own_timeout():
    module = connector_module(check(_load(LINKEDIN), LINKEDIN)).source
    company = module.split("export const getCompany = ")[1].split("export const ")[0]
    assert "  timeoutMs: 60000,\n" in company
    assert module.count("  timeoutMs: ") == 2 and "  timeoutMs: 120000,\n" in module
