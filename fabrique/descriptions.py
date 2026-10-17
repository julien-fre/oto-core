"""Lecture et contrôle des fichiers de description.

Un fichier est lu, validé contre `connectors/connector.schema.json` (chaque exemple
contre l'entrée de sa fonction), puis contre les règles que le schéma JSON ne sait
pas dire :

1. chaque argument d'entrée va à un seul endroit de `call` (chemin, query, corps ou
   en-tête), chaque `{param}` du chemin et chaque valeur de `query`, `body` et
   `headers` nomme un argument déclaré, un argument du chemin est requis, aucun
   argument n'est sans place, et le `request_param` d'une pagination est un
   argument ;
2. chaque référence de `auth` (`key`, `token`, `username`, `password`, `client_id`,
   `client_secret`) nomme un champ de `credential` ;
3. un nom côté API reçoit une seule valeur : une constante de `call.constants` ne
   reprend pas un nom de la même place, un en-tête constant (du connecteur ou de la
   fonction) ni celui de l'authentification ni un autre en-tête, à la casse près, et
   une clé passée en query (`auth.in: query`) n'est le nom d'aucun paramètre de
   query ; chaque clé de `call.encode` nomme un argument placé en query, en corps ou
   en en-tête ;
4. chaque contrôle (`checks`, `expect`) nomme un refus de sa fonction ; `equal_sums`
   porte sur un argument liste dont les éléments déclarent les deux champs ;
5. la sonde, et l'identité d'un `oauth2_user` lue par une fonction, nomment une
   fonction de lecture du connecteur, appelée par `call`, sans argument requis ;
   l'identité lue à une adresse complète exige des droits que le consentement
   demande (ses `scopes`, quand le connecteur n'a pas de niveaux ; à chaque niveau
   sinon, règle 7) ;
6. les réglages : un nom n'est déclaré qu'une fois parmi `credential`, `settings` et
   `from_token` ; le défaut d'une liste fermée en est une valeur ; un gabarit d'adresse
   (`base_url`, `token_url`, `authorize_url`) ne cite que des réglages déclarés (et,
   pour `base_url`, des valeurs de `from_token` et l'identité du compte, règle 8), une
   adresse libre en tête seulement, un autre réglage après `https://` seulement ; `base_urls` et `token_urls` portent
   sur une liste fermée et donnent une adresse à chacune de ses valeurs, et rien
   d'autre ; tout réglage déclaré est cité ;
7. les niveaux d'accès (`auth.access_levels`, voir docs/conception/niveaux-d-acces.md) :
   `scope_implies` est clos (un droit impliqué qui en implique d'autres les fait
   impliquer aussi par qui l'implique : lue en un pas ou par transitivité,
   l'implication dit la même chose) et chacune de ses clés est un droit d'un
   niveau ; `full` couvre chaque droit d'un niveau restreint et chaque droit exigé
   par une fonction (`full` ne filtre rien) ; l'identité du consentement et la
   sonde sont servies à chaque niveau ;
8. l'identité d'un compte rattaché (`account_identity`, l'identifiant du compte chez
   un tiers qui héberge les comptes de ses utilisateurs) : son nom n'est ni celui
   d'un champ de `credential`, ni d'un réglage, ni d'une valeur de `from_token` ;
   elle est citée par `base_url`, ou par chaque adresse de `base_urls`, après l'hôte
   seulement, et par aucune autre adresse ; aucun argument d'entrée, aucun nom côté
   API de `call` (paramètre du chemin, de query, de corps, en-tête), aucune constante
   ni aucun en-tête constant ne porte son nom : l'agent ne la fournit jamais ;
9. `act` suit la classe : jamais `false` sur une fonction `sensitive`, jamais `true`
   sur une fonction `read` ; absent, il vaut `false` pour `read`, `true` sinon.

Un fichier fautif lève `DescriptionError`, qui nomme le fichier, la fonction et la
règle : la fabrique ne génère alors rien.
"""
from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass

import yaml
from jsonschema import Draft202012Validator

REPO = pathlib.Path(__file__).resolve().parent.parent
CONNECTORS = REPO / "connectors"
SCHEMA_PATH = CONNECTORS / "connector.schema.json"

PATH_PARAM = re.compile(r"\{([^{}]*)\}")
AUTH_REFERENCES = ("key", "token", "username", "password", "client_id", "client_secret")
PLACES = ("query", "body", "headers")
# Ce qui précède l'identité d'un compte dans une adresse : le schéma et l'hôte (ou une adresse libre en tête), puis `/`.
AFTER_HOST = re.compile(r"^(https://[^/{}]+|\{[a-z][a-z0-9_]*\})/")


class DescriptionError(ValueError):
    """Une description refusée : le message dit le fichier, la fonction et la règle."""


@dataclass(frozen=True)
class Description:
    path: pathlib.Path
    data: dict

    @property
    def name(self) -> str:
        return self.data["connector"]["name"]


def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _relative(path: pathlib.Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def check_schema(data: dict, where: str) -> None:
    """Le schéma du format, puis chaque exemple contre l'entrée de sa fonction."""
    errors = sorted(Draft202012Validator(schema()).iter_errors(data), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        at = "/".join(str(p) for p in first.absolute_path) or "(root)"
        raise DescriptionError(f"{where}: does not match the description schema at {at}: {first.message}")
    for function in data["functions"]:
        validator = Draft202012Validator(function["input"])
        for example in function["examples"]:
            error = next(iter(validator.iter_errors(example["input"])), None)
            if error is not None:
                raise DescriptionError(
                    f"{where}: function {function['name']}: example {example['title']!r} "
                    f"does not match its input: {error.message}"
                )


def check_arguments(function: dict, where: str) -> None:
    """Règle 1 : un argument va à un seul endroit, et tout endroit nomme un argument."""
    call = function.get("call")
    if call is None:
        return
    name = function["name"]
    declared = set(function["input"]["properties"])
    required = set(function["input"].get("required", []))
    placed: dict[str, str] = {}

    def place(argument: str, at: str) -> None:
        if argument not in declared:
            raise DescriptionError(f"{where}: function {name}: {at} names {argument!r}, which is not an input argument")
        if argument in placed:
            raise DescriptionError(
                f"{where}: function {name}: argument {argument!r} goes to two places ({placed[argument]} and {at})"
            )
        placed[argument] = at

    for argument in PATH_PARAM.findall(call["path"]):
        place(argument, "the path")
        if argument not in required:
            raise DescriptionError(f"{where}: function {name}: path argument {argument!r} must be required")
    for kind in PLACES:
        for api_name, argument in (call.get(kind) or {}).items():
            place(argument, f"{kind} {api_name!r}")
    pagination = function.get("pagination")
    unplaced = declared - set(placed)
    if unplaced:
        raise DescriptionError(
            f"{where}: function {name}: argument(s) {', '.join(sorted(unplaced))} go nowhere in call"
        )
    if pagination and pagination["request_param"] not in declared:
        raise DescriptionError(
            f"{where}: function {name}: pagination request_param {pagination['request_param']!r} is not an input argument"
        )
    for argument in call.get("encode") or {}:
        if argument not in placed or placed[argument] == "the path":
            raise DescriptionError(
                f"{where}: function {name}: encode names {argument!r}, which is not placed in query, body or headers"
            )


def check_auth(connector: dict, where: str) -> None:
    """Règle 2 : une référence de `auth` désigne un champ de `credential` existant."""
    auth = connector["auth"]
    fields = {field["name"] for field in connector.get("credential", [])}
    for reference in AUTH_REFERENCES:
        if reference in auth and auth[reference] not in fields:
            raise DescriptionError(
                f"{where}: auth.{reference} names {auth[reference]!r}, which is not a credential field "
                f"({', '.join(sorted(fields)) or 'none declared'})"
            )


def _auth_header(auth: dict) -> str | None:
    if auth["kind"] == "api_key":
        return auth["name"] if auth["in"] == "header" else None
    if auth["kind"] in ("bearer", "basic", "oauth2_client_credentials", "oauth2_user"):
        return "Authorization"
    return None


def _auth_query(auth: dict) -> str | None:
    return auth["name"] if auth["kind"] == "api_key" and auth["in"] == "query" else None


def check_constants(connector: dict, function: dict, where: str) -> None:
    """Règle 3 : un nom côté API, une seule valeur."""
    call = function.get("call")
    if call is None:
        return
    name = function["name"]
    constants = call.get("constants") or {}
    for kind in ("query", "body"):
        for api_name in constants.get(kind) or {}:
            if api_name in (call.get(kind) or {}):
                raise DescriptionError(
                    f"{where}: function {name}: {kind} {api_name!r} is both a constant and an argument"
                )
    auth_query = _auth_query(connector["auth"])
    if auth_query and (auth_query in (call.get("query") or {}) or auth_query in (constants.get("query") or {})):
        raise DescriptionError(
            f"{where}: function {name}: query {auth_query!r} is set twice (the authentication and the function)"
        )
    seen: dict[str, str] = {}
    auth_header = _auth_header(connector["auth"])
    if auth_header:
        seen[auth_header.lower()] = "the authentication"
    sources = [
        ("the connector headers", connector.get("headers") or {}),
        ("the function constant headers", constants.get("headers") or {}),
        ("the function headers", call.get("headers") or {}),
    ]
    for source, headers in sources:
        for header in headers:
            if header.lower() in seen:
                raise DescriptionError(
                    f"{where}: function {name}: header {header!r} is set twice ({seen[header.lower()]} and {source})"
                )
            seen[header.lower()] = source


def act(function: dict) -> bool:
    """Ce qui engage ou détruit : `act` déclaré, sinon déduit de la classe (`read` → false, `write` et `sensitive` → true)."""
    return function.get("act", function["class"] != "read")


def check_act(function: dict, where: str) -> None:
    """Règle 9 : `act` ne contredit pas la classe."""
    declared = function.get("act")
    if declared is False and function["class"] == "sensitive":
        raise DescriptionError(f"{where}: function {function['name']}: a sensitive function cannot declare act: false")
    if declared is True and function["class"] == "read":
        raise DescriptionError(f"{where}: function {function['name']}: a read function cannot declare act: true")


def check_checks(function: dict, where: str) -> None:
    """Règle 4 : un contrôle nomme un refus de sa fonction, et `equal_sums` une liste qui a ses deux champs."""
    name = function["name"]
    refusals = {refusal["code"] for refusal in function.get("refusals", [])}
    for check in function.get("checks", []) + function.get("expect", []):
        if check["refusal"] not in refusals:
            raise DescriptionError(
                f"{where}: function {name}: {check['kind']} names refusal {check['refusal']!r}, which the function does not declare"
            )
        if check["kind"] == "equal_sums":
            argument = function["input"]["properties"].get(check["items"])
            item = (argument or {}).get("items") if (argument or {}).get("type") == "array" else None
            missing = [f for f in check["fields"] if f not in ((item or {}).get("properties") or {})]
            if item is None or missing:
                raise DescriptionError(
                    f"{where}: function {name}: equal_sums needs {check['items']!r} to be a list argument whose items "
                    f"declare {', '.join(check['fields'])}"
                )


def _plain_read(data: dict, role: str, name: str, where: str) -> None:
    function = next((f for f in data["functions"] if f["name"] == name), None)
    if function is None:
        raise DescriptionError(f"{where}: {role} names {name!r}, which is not a function of the connector")
    if function["class"] != "read" or "call" not in function or function["input"].get("required"):
        raise DescriptionError(
            f"{where}: {role} {name!r} must be a read function with a call and no required argument"
        )


def check_probe(data: dict, where: str) -> None:
    """Règle 5 : la sonde et l'identité d'un consentement sont des lectures par `call`, appelables sans argument."""
    probe = data["connector"].get("probe")
    if probe is not None:
        _plain_read(data, "probe", probe["function"], where)
    auth = data["connector"]["auth"]
    identity = auth.get("identity")
    if identity is not None and "function" in identity:
        _plain_read(data, "auth.identity", identity["function"], where)
    if identity is not None and "url" in identity and "access_levels" not in auth:
        beyond = sorted(set(identity["scopes"]) - set(auth.get("scopes", [])))
        if beyond:
            raise DescriptionError(f"{where}: auth.identity needs {', '.join(beyond)}, which auth.scopes does not ask for")


def _check_template(
    template: str, at: str, settings: dict[str, dict], from_token: set[str], where: str, identity: str | None = None,
) -> set[str]:
    """Un gabarit d'adresse : chaque `{nom}` est un réglage déclaré (ou une valeur du jeton, ou l'identité du compte
    quand `identity` la nomme), à sa place."""
    cited = PATH_PARAM.findall(template)
    for position, name in enumerate(cited):
        head = position == 0 and template.startswith("{")
        if name in from_token:
            continue
        if name == identity:
            _check_identity_place(template, at, name, where)
            continue
        setting = settings.get(name)
        if setting is None:
            known = sorted(settings) + sorted(from_token)
            raise DescriptionError(
                f"{where}: {at} cites {{{name}}}, which is not a declared setting ({', '.join(known) or 'none declared'})"
            )
        if head and setting["type"] != "url":
            raise DescriptionError(f"{where}: {at} starts with {{{name}}}, which is not a url setting")
        if not head and setting["type"] == "url":
            raise DescriptionError(f"{where}: {at} cites the url setting {{{name}}} elsewhere than at its head")
    return set(cited)


def _check_identity_place(url: str, at: str, identity: str, where: str) -> None:
    if not AFTER_HOST.match(url[: url.index("{" + identity + "}")]):
        raise DescriptionError(f"{where}: {at} cites the account identity {{{identity}}} elsewhere than after the host")


def _check_urls_by_setting(urls: dict, at: str, settings: dict[str, dict], where: str, identity: str | None = None) -> set[str]:
    for url in urls["values"].values():
        for name in PATH_PARAM.findall(url):
            if name != identity:
                raise DescriptionError(f"{where}: {at}.values cites {{{name}}}, which is not the account identity")
            _check_identity_place(url, f"{at}.values", name, where)
    setting = settings.get(urls["setting"])
    if setting is None or setting["type"] != "choice":
        raise DescriptionError(f"{where}: {at}.setting names {urls['setting']!r}, which is not a choice setting")
    if set(urls["values"]) != set(setting["choices"]):
        raise DescriptionError(
            f"{where}: {at}.values must give a URL to each choice of {urls['setting']!r} "
            f"({', '.join(setting['choices'])}), and to nothing else"
        )
    return {urls["setting"]}


def check_settings(connector: dict, where: str) -> None:
    """Règle 6 : réglages déclarés une fois, cités à leur place, tous cités."""
    auth = connector["auth"]
    settings = {s["name"]: s for s in connector.get("settings", [])}
    from_token = set(auth.get("from_token", []))
    names = [f["name"] for f in connector.get("credential", [])] + [s["name"] for s in connector.get("settings", [])]
    names += list(from_token)
    twice = sorted({n for n in names if names.count(n) > 1})
    if twice:
        raise DescriptionError(f"{where}: name(s) declared twice among credential, settings and from_token: {', '.join(twice)}")
    for setting in settings.values():
        if "default" in setting and setting["default"] not in setting["choices"]:
            raise DescriptionError(f"{where}: setting {setting['name']!r}: default {setting['default']!r} is not one of its choices")
    identity = (connector.get("account_identity") or {}).get("name")
    cited: set[str] = set()
    if "base_url" in connector:
        cited |= _check_template(connector["base_url"], "base_url", settings, from_token, where, identity)
    if "base_urls" in connector:
        cited |= _check_urls_by_setting(connector["base_urls"], "base_urls", settings, where, identity)
    for key in ("token_url", "authorize_url"):
        if key in auth:
            cited |= _check_template(auth[key], f"auth.{key}", settings, set(), where)
    if "token_urls" in auth:
        cited |= _check_urls_by_setting(auth["token_urls"], "auth.token_urls", settings, where)
    unused = sorted(set(settings) - cited)
    if unused:
        raise DescriptionError(f"{where}: setting(s) {', '.join(unused)} cited by no URL")


def check_account_identity(data: dict, where: str) -> None:
    """Règle 8 : l'identité d'un compte rattaché a un nom à elle, n'est citée que par l'adresse de base, après l'hôte, et
    jamais fournie par l'agent. La place dans le gabarit se vérifie avec les réglages (règle 6)."""
    connector = data["connector"]
    declared = connector.get("account_identity")
    if declared is None:
        return
    identity = declared["name"]
    for kind, names in (
        ("a credential field", [f["name"] for f in connector.get("credential", [])]),
        ("a setting", [s["name"] for s in connector.get("settings", [])]),
        ("a value of auth.from_token", connector["auth"].get("from_token", [])),
    ):
        if identity in names:
            raise DescriptionError(f"{where}: account_identity {identity!r} is also the name of {kind}")
    if "base_url" in connector:
        urls = [("base_url", connector["base_url"])]
    else:
        urls = [(f"base_urls.values.{k}", v) for k, v in (connector.get("base_urls") or {}).get("values", {}).items()]
    if not urls:
        raise DescriptionError(f"{where}: account_identity {identity!r} needs a base_url that cites it")
    for at, url in urls:
        if "{" + identity + "}" not in url:
            raise DescriptionError(f"{where}: {at} does not cite the account identity {{{identity}}}")
    auth = connector["auth"]
    others = [(f"auth.{key}", auth[key]) for key in ("token_url", "authorize_url") if key in auth]
    others += [(f"auth.token_urls.values.{k}", v) for k, v in (auth.get("token_urls") or {}).get("values", {}).items()]
    for at, url in others:
        if identity in PATH_PARAM.findall(url):
            raise DescriptionError(f"{where}: {at} cites the account identity {{{identity}}}, which only the base URL cites")
    if identity.lower() in {header.lower() for header in connector.get("headers") or {}}:
        raise DescriptionError(f"{where}: the connector header {identity!r} bears the name of the account identity")
    for function in data["functions"]:
        name = function["name"]
        if identity in function["input"]["properties"]:
            raise DescriptionError(
                f"{where}: function {name}: input argument {identity!r} bears the name of the account identity, "
                "which only the base URL cites"
            )
        call = function.get("call")
        if call is None:
            continue
        if identity in PATH_PARAM.findall(call["path"]):
            raise DescriptionError(f"{where}: function {name}: the path cites the account identity {{{identity}}}")
        for kind in PLACES:
            mapping = call.get(kind) or {}
            api_names = {n.lower() for n in mapping} if kind == "headers" else set(mapping)
            if identity in api_names or identity in mapping.values():
                raise DescriptionError(
                    f"{where}: function {name}: {kind} parameter {identity!r} bears the name of the account identity"
                )
        for kind, constants in (call.get("constants") or {}).items():
            if identity in ({n.lower() for n in constants} if kind == "headers" else set(constants)):
                raise DescriptionError(
                    f"{where}: function {name}: constant {kind} {identity!r} bears the name of the account identity"
                )


def covered(scopes: list[str], implies: dict[str, list[str]]) -> set[str]:
    """Les droits que couvrent ceux d'un niveau : eux-mêmes et ce qu'ils impliquent (`scope_implies`, clos)."""
    return set(scopes).union(*(implies.get(scope, []) for scope in scopes))


def served(function: dict, scopes: list[str], implies: dict[str, list[str]]) -> bool:
    """Une fonction (ou une identité lue à une adresse) est servie à un niveau quand chacun des droits qu'elle exige
    est couvert par ceux du niveau."""
    return set(function["scopes"]) <= covered(scopes, implies)


def check_access_levels(data: dict, where: str) -> None:
    """Règle 7 : implication close et utile, `full` couvre tout, identité et sonde servies à chaque niveau."""
    auth = data["connector"]["auth"]
    levels = auth.get("access_levels")
    if levels is None:
        return
    implies = auth.get("scope_implies", {})
    granted = {scope for level in levels.values() for scope in level["scopes"]}
    for scope, implied in implies.items():
        if scope not in granted:
            raise DescriptionError(f"{where}: auth.scope_implies: {scope!r} is the scope of no access level")
        missing = sorted({deeper for scope2 in implied for deeper in implies.get(scope2, [])} - set(implied) - {scope})
        if missing:
            raise DescriptionError(
                f"{where}: auth.scope_implies: {scope!r} implies a scope that implies {', '.join(missing)}, "
                f"which {scope!r} must then list too"
            )
    full = covered(levels["full"]["scopes"], implies)
    for name, level in levels.items():
        beyond = sorted(set(level["scopes"]) - full)
        if beyond:
            raise DescriptionError(
                f"{where}: access level {name!r} asks for {', '.join(beyond)}, which level 'full' does not cover"
            )
    for function in data["functions"]:
        beyond = sorted(set(function["scopes"]) - full)
        if beyond:
            raise DescriptionError(
                f"{where}: function {function['name']}: scope(s) {', '.join(beyond)} not covered by level 'full'"
            )
    identity = auth["identity"]
    roles = []
    if "function" in identity:
        roles.append(("auth.identity", identity["function"], next(f for f in data["functions"] if f["name"] == identity["function"])))
    else:
        roles.append(("auth.identity", identity["url"], identity))
    if "probe" in data["connector"]:
        name = data["connector"]["probe"]["function"]
        roles.append(("probe", name, next(f for f in data["functions"] if f["name"] == name)))
    for role, name, required in roles:
        for level_name, level in levels.items():
            if not served(required, level["scopes"], implies):
                raise DescriptionError(
                    f"{where}: {role} {name!r} is not served at access level {level_name!r}: "
                    f"its scopes ({', '.join(required['scopes'])}) are not all covered"
                )


def check(data: dict, path: pathlib.Path) -> Description:
    where = _relative(path)
    if not isinstance(data, dict):
        raise DescriptionError(f"{where}: not a mapping")
    check_schema(data, where)
    if data["connector"]["name"] != path.parent.name:
        raise DescriptionError(f"{where}: connector.name {data['connector']['name']!r} is not the folder name")
    check_auth(data["connector"], where)
    check_account_identity(data, where)
    check_settings(data["connector"], where)
    for function in data["functions"]:
        check_arguments(function, where)
        check_constants(data["connector"], function, where)
        check_checks(function, where)
        check_act(function, where)
    names = [function["name"] for function in data["functions"]]
    twice = sorted({n for n in names if names.count(n) > 1})
    if twice:
        raise DescriptionError(f"{where}: function name(s) declared twice: {', '.join(twice)}")
    check_probe(data, where)
    check_access_levels(data, where)
    return Description(path=path, data=data)


def load(path: pathlib.Path) -> Description:
    return check(yaml.safe_load(path.read_text(encoding="utf-8")), path)


def load_all(root: pathlib.Path = CONNECTORS) -> list[Description]:
    return [load(path) for path in sorted(root.glob("*/connector.yaml"))]
