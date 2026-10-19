"""Lecture et contrôle des fichiers de description.

Un fichier est lu, validé contre `connectors/connector.schema.json` (chaque exemple
contre l'entrée de sa fonction), puis contre les règles que le schéma JSON ne sait
pas dire :

1. chaque argument d'entrée va à un seul endroit de `call` (chemin, query, corps,
   en-tête ou partie fichier), chaque `{param}` du chemin et chaque valeur de `query`,
   `body`, `headers` et `files` nomme un argument déclaré, un argument du chemin est requis, aucun
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
   fonction de lecture du connecteur, appelée par `call`, sans argument requis ; la
   fonction d'une sonde qui lit un solde (`balance`) ne déclare pas de coût (`cost`) :
   on ne paie pas pour savoir si l'on peut payer ; l'identité lue à une adresse complète exige des droits que le consentement
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
   sur une fonction `read` ; absent, il vaut `false` pour `read`, `true` sinon ;
10. le signal de refus du service (une entrée de `errors` ou un refus qui porte
   `marks_account`, une condition sur le corps `body`) : un refus qui porte l'un ou
   l'autre a un statut pour `when`, jamais une condition en texte ; un statut 2xx
   exige une condition sur le corps (sinon chaque succès serait un refus) ; un 403
   sans condition sur le corps ne marque jamais `credential_rejected` (un droit
   manquant n'est pas une clé refusée), ni un 429 sans condition `quota_exhausted`
   (un débit dépassé n'est pas un crédit épuisé) ; une entrée qui marque le compte
   n'est pas rejouable ; dans une même table, une entrée à condition ne vient pas
   après une entrée sans condition qui partage un de ses statuts (elle ne serait
   jamais lue) ;
11. le délai propre à une fonction (`timeout_s`) remplace celui du connecteur pour
   chacun de ses appels, plus court ou plus long ; il n'est jamais égal au délai du
   connecteur (déclaré, ou 30 s par défaut) : il ne dirait rien ;
12. le coût (`cost`) : `items` et `times` (`per: item`) nomment deux arguments
   distincts de l'entrée, des listes (`type: array`) requises d'au moins un élément
   (`minItems` d'un ou plus), de sorte que le pire cas se calcule toujours, jamais
   nul ni deviné ; une fonction paginée ne coûte ni à l'élément ni à la quantité
   relue (`settle`) : chaque page est une requête, et une quantité lue dans une seule
   réponse ne dirait pas celle de l'appel ;
13. le travail asynchrone (`async`) : `collect` nomme une autre fonction de lecture du
   connecteur, appelée par `call`, qui n'est pas elle-même asynchrone ; `job_id.to`
   en est le seul argument requis (la relève se fait sans rien d'autre que
   l'identifiant du travail) ; quand le coût se règle (`settle`), la quantité se lit
   dans les réponses de la relève : elle n'est pas paginée et ne déclare pas de
   `settle` à elle ; le délai de relève (`within_s`, exigé par le schéma dans ce cas,
   sauf `no_deadline` quand la référence de l'éditeur dit qu'un travail n'a pas
   d'échéance) est plus long que le délai de la soumission, quand il est déclaré ;
14. les fichiers (`call.files`, une partie d'un corps multipart par argument qui
   porte l'identifiant d'un fichier en transit de l'appelant) : la méthode envoie un
   corps (`POST`, `PUT`, `PATCH`) ; la fonction n'est pas paginée ; chaque argument
   fichier est un texte (`type: string`), jamais encodé ; un nom de partie fichier
   n'est ni un nom de `body` ni une constante de corps (une partie, une valeur) ;
15. la donnée personnelle (`personal`) : dans l'entrée, sur une propriété seulement,
   jamais à la racine, et toujours `true` ; jamais dans le schéma de la sortie, où elle
   ne voudrait rien dire. L'hôte ne journalise pas sa valeur ;
16. le poids d'une valeur (`cost.weights`, à la place de `times`) : `field` nomme un
   champ de chaque élément de `items`, requis dans l'élément, une liste d'au moins un
   élément aux valeurs uniques, dont les valeurs admises (`enum`) sont exactement les
   clés de la table de poids : une valeur sans poids est refusée par le schéma
   d'entrée, avant l'appel, jamais comptée pour rien, et un poids ne vaut que pour une
   valeur admise.

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
# Le délai d'un appel quand le connecteur n'en déclare pas (le `default` du schéma).
DEFAULT_TIMEOUT_S = 30
AUTH_REFERENCES = ("key", "token", "username", "password", "client_id", "client_secret")
PLACES = ("query", "body", "headers", "files")
# Les méthodes qui envoient un corps multipart.
FILE_METHODS = ("POST", "PUT", "PATCH")
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
        if argument not in placed or placed[argument] == "the path" or placed[argument].startswith("files "):
            raise DescriptionError(
                f"{where}: function {name}: encode names {argument!r}, which is not placed in query, body or headers"
                " (a file is never encoded)"
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


def check_timeout(connector: dict, function: dict, where: str) -> None:
    """Règle 11 : le délai d'une fonction n'est pas celui du connecteur."""
    own = function.get("timeout_s")
    if own is not None and own == connector.get("timeout_s", DEFAULT_TIMEOUT_S):
        raise DescriptionError(
            f"{where}: function {function['name']}: timeout_s {own} is the connector's timeout: declare none"
        )


def _check_cost_list(function: dict, key: str, where: str) -> None:
    """Un argument que le coût compte : une liste requise, d'au moins un élément."""
    argument = function["cost"][key]
    schema = function["input"]["properties"].get(argument)
    if schema is None:
        raise DescriptionError(f"{where}: function {function['name']}: cost.{key} names {argument!r}, which is not an input argument")
    listed = schema.get("type") == "array" and isinstance(schema.get("minItems"), int) and schema["minItems"] >= 1
    if not listed or argument not in function["input"].get("required", []):
        raise DescriptionError(
            f"{where}: function {function['name']}: cost.{key} {argument!r} must be a required list argument "
            "(type: array, minItems 1 or more), so that the worst case is never zero nor guessed"
        )


def _check_cost_weights(function: dict, where: str) -> None:
    """Règle 16, le poids d'une valeur : le champ qui porte les valeurs est, dans chaque élément de `items`, une liste requise
    d'au moins un élément, aux valeurs uniques, dont les valeurs admises sont exactement les clés de la table."""
    cost = function["cost"]
    field = cost["weights"]["field"]
    element = function["input"]["properties"][cost["items"]].get("items")
    prefix = f"{where}: function {function['name']}: cost.weights.field {field!r}"
    if not isinstance(element, dict) or not isinstance(element.get("properties"), dict) or field not in element["properties"]:
        raise DescriptionError(f"{prefix} must be a property of each element of {cost['items']!r} (an object schema)")
    schema = element["properties"][field]
    listed = (schema.get("type") == "array" and isinstance(schema.get("minItems"), int) and schema["minItems"] >= 1
              and schema.get("uniqueItems") is True)
    if not listed or field not in element.get("required", []):
        raise DescriptionError(
            f"{prefix} must be a required list of each element (type: array, minItems 1 or more, uniqueItems: true), "
            "so that each element counts at least one weight, each value once"
        )
    allowed = schema.get("items", {}).get("enum") if isinstance(schema.get("items"), dict) else None
    table = set(cost["weights"]["values"])
    if not isinstance(allowed, list) or not all(isinstance(v, str) for v in allowed) or set(allowed) != table:
        raise DescriptionError(
            f"{prefix}: its allowed values (items.enum, texts) must be exactly the keys of cost.weights.values "
            f"({', '.join(sorted(table))}), so that a value without a weight is refused before the call"
        )


def check_cost(function: dict, where: str) -> None:
    """Règle 12 : le coût à l'élément compte des listes requises et non vides, distinctes ; ni l'élément ni la quantité
    relue sur une fonction paginée. Les valeurs pesées dans chaque élément sont la règle 16."""
    cost = function.get("cost")
    if cost is None:
        return
    name = function["name"]
    if cost["per"] == "item":
        _check_cost_list(function, "items", where)
        if "weights" in cost:
            _check_cost_weights(function, where)
        if "times" in cost:
            if cost["times"] == cost["items"]:
                raise DescriptionError(f"{where}: function {name}: cost.times names the items argument {cost['items']!r} again")
            _check_cost_list(function, "times", where)
    if "pagination" in function and (cost["per"] == "item" or "settle" in cost):
        raise DescriptionError(
            f"{where}: function {name}: a paginated function costs per request or per page, without settle: "
            "each page is a request, and one response does not tell the quantity of the call"
        )


def check_async(data: dict, function: dict, where: str) -> None:
    """Règle 13 : la relève d'un travail asynchrone est une autre lecture du connecteur, appelable avec l'identifiant du
    travail seul ; une quantité réglée se lit dans ses réponses, dans le délai de relève."""
    declared = function.get("async")
    if declared is None:
        return
    name = function["name"]
    collect = next((f for f in data["functions"] if f["name"] == declared["collect"]), None)
    if collect is None or collect is function:
        raise DescriptionError(f"{where}: function {name}: async.collect names {declared['collect']!r}, which is not another function of the connector")
    if collect["class"] != "read" or "call" not in collect or "async" in collect:
        raise DescriptionError(
            f"{where}: function {name}: async.collect {collect['name']!r} must be a read function with a call, not asynchronous itself"
        )
    to = declared["job_id"]["to"]
    if collect["input"].get("required", []) != [to] or to not in collect["input"]["properties"]:
        raise DescriptionError(
            f"{where}: function {name}: async.job_id.to {to!r} must be the only required argument of {collect['name']!r}"
        )
    timeout = function.get("timeout_s", data["connector"].get("timeout_s", DEFAULT_TIMEOUT_S))
    if "within_s" in declared and declared["within_s"] <= timeout:
        raise DescriptionError(
            f"{where}: function {name}: async.within_s {declared['within_s']} must exceed the timeout of the submission ({timeout} s)"
        )
    if "settle" in function.get("cost", {}) and ("pagination" in collect or "settle" in collect.get("cost", {})):
        raise DescriptionError(
            f"{where}: function {name}: its quantity is read in the responses of {collect['name']!r}, "
            "which must be neither paginated nor settled on its own"
        )


def check_files(function: dict, where: str) -> None:
    """Règle 14 : les parties fichier d'un corps multipart, dans une requête qui envoie un corps, une fois, sans
    pagination ; l'argument d'une partie porte l'identifiant d'un fichier en transit, un texte."""
    call = function.get("call") or {}
    files = call.get("files")
    if not files:
        return
    name = function["name"]
    if call["method"] not in FILE_METHODS:
        raise DescriptionError(f"{where}: function {name}: call.files needs a method that sends a body ({', '.join(FILE_METHODS)})")
    if "pagination" in function:
        raise DescriptionError(f"{where}: function {name}: a function that sends files is not paginated: a file is sent once")
    texts = set(call.get("body") or {}) | set((call.get("constants") or {}).get("body") or {})
    for part, argument in files.items():
        if part in texts:
            raise DescriptionError(f"{where}: function {name}: multipart part {part!r} is both a file and a body value")
        if function["input"]["properties"][argument].get("type") != "string":
            raise DescriptionError(
                f"{where}: function {name}: file argument {argument!r} must be type: string, the id of a transit file"
            )


# Les mots d'un JSON Schema dont la valeur est un schéma, une liste de schémas, ou des schémas par nom : la donnée
# personnelle se cherche là seulement, jamais dans `examples`, `default`, `const` ni `enum`, et le nom d'une propriété
# (une propriété qui s'appellerait `personal`) n'est jamais lu comme un mot.
SCHEMA_KEYWORDS = ("items", "additionalProperties", "not", "if", "then", "else", "contains", "propertyNames",
                   "unevaluatedItems", "unevaluatedProperties")
SCHEMA_LISTS = ("allOf", "anyOf", "oneOf", "prefixItems")
SCHEMA_MAPS = ("properties", "patternProperties", "$defs", "dependentSchemas")


def _personal_marks(schema: object, at: str) -> list[tuple[str, object]]:
    """Chaque `personal` d'un schéma, avec sa place (`input.properties.email`)."""
    if not isinstance(schema, dict):
        return []
    found = [(at, schema["personal"])] if "personal" in schema else []
    for key in SCHEMA_KEYWORDS:
        found += _personal_marks(schema.get(key), f"{at}.{key}")
    for key in SCHEMA_LISTS:
        for index, child in enumerate(schema.get(key) or []):
            found += _personal_marks(child, f"{at}.{key}[{index}]")
    for key in SCHEMA_MAPS:
        for name, child in (schema.get(key) or {}).items():
            found += _personal_marks(child, f"{at}.{key}.{name}")
    return found


def check_personal(function: dict, where: str) -> None:
    """Règle 15 : `personal` marque une propriété de l'entrée, toujours `true` ; ni la racine ni la sortie."""
    name = function["name"]
    for at, value in _personal_marks(function["input"], "input"):
        if at == "input":
            raise DescriptionError(f"{where}: function {name}: personal marks a property of input, not input itself")
        if value is not True:
            raise DescriptionError(f"{where}: function {name}: {at}: personal must be true (declare it only where it applies)")
    schema = (function.get("output") or {}).get("schema")
    for at, _ in _personal_marks(schema, "output.schema"):
        raise DescriptionError(f"{where}: function {name}: {at}: personal marks an input argument, not an output field")


def _statuses(entry: dict) -> list[int]:
    status = entry["status"] if "status" in entry else entry["when"]
    return status if isinstance(status, list) else [status]


def _check_signal_table(entries: list[dict], at: str, where: str) -> None:
    """Règle 10, sur une table (`errors` du connecteur, ou les refus d'une fonction)."""
    plain: set[int] = set()
    for entry in entries:
        label = f"{at} {entry['code']!r}"
        if "status" not in entry and not isinstance(entry["when"], int):
            if "body" in entry or "marks_account" in entry:
                raise DescriptionError(
                    f"{where}: {label}: a refusal with body or marks_account needs an HTTP status in when, not a text condition"
                )
            continue
        statuses = _statuses(entry)
        body = "body" in entry
        mark = entry.get("marks_account")
        if not body and any(200 <= status < 300 for status in statuses):
            raise DescriptionError(f"{where}: {label}: a 2xx status needs a body condition, or every success would be refused")
        if mark == "credential_rejected" and not body and 403 in statuses:
            raise DescriptionError(
                f"{where}: {label}: a 403 without a body condition cannot mark credential_rejected (a missing right is not a refused key)"
            )
        if mark == "quota_exhausted" and not body and 429 in statuses:
            raise DescriptionError(
                f"{where}: {label}: a 429 without a body condition cannot mark quota_exhausted (a rate limit is not spent credits)"
            )
        if mark is not None and entry.get("retryable") is True:
            raise DescriptionError(f"{where}: {label}: an entry that marks the account is not retryable")
        shadowed = sorted(plain.intersection(statuses))
        if body and shadowed:
            raise DescriptionError(
                f"{where}: {label}: its body condition comes after an entry without one for status "
                f"{', '.join(map(str, shadowed))}, so it is never read"
            )
        if not body:
            plain.update(statuses)


def check_signals(data: dict, where: str) -> None:
    """Règle 10 : le signal de refus du service, dans la table du connecteur et dans les refus de chaque fonction."""
    _check_signal_table(data["connector"]["errors"], "errors", where)
    for function in data["functions"]:
        _check_signal_table(function.get("refusals", []), f"function {function['name']}: refusal", where)


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
    """Règle 5 : la sonde et l'identité d'un consentement sont des lectures par `call`, appelables sans argument ; la
    fonction d'une sonde qui lit un solde ne coûte rien."""
    probe = data["connector"].get("probe")
    if probe is not None:
        _plain_read(data, "probe", probe["function"], where)
        function = next(f for f in data["functions"] if f["name"] == probe["function"])
        if "balance" in probe and "cost" in function:
            raise DescriptionError(
                f"{where}: probe {probe['function']!r} reads a balance, so it must declare no cost: one never pays to learn whether one can pay"
            )
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
    check_rules(data, where)
    return Description(path=path, data=data)


def check_rules(data: dict, where: str) -> None:
    """Les règles hors schéma, sur une description déjà validée par le schéma (`check`, et les cas du coût)."""
    check_auth(data["connector"], where)
    check_account_identity(data, where)
    check_settings(data["connector"], where)
    for function in data["functions"]:
        check_arguments(function, where)
        check_constants(data["connector"], function, where)
        check_checks(function, where)
        check_act(function, where)
        check_timeout(data["connector"], function, where)
        check_cost(function, where)
        check_async(data, function, where)
        check_files(function, where)
        check_personal(function, where)
    names = [function["name"] for function in data["functions"]]
    twice = sorted({n for n in names if names.count(n) > 1})
    if twice:
        raise DescriptionError(f"{where}: function name(s) declared twice: {', '.join(twice)}")
    check_probe(data, where)
    check_access_levels(data, where)
    check_signals(data, where)


def load(path: pathlib.Path) -> Description:
    return check(yaml.safe_load(path.read_text(encoding="utf-8")), path)


def load_all(root: pathlib.Path = CONNECTORS) -> list[Description]:
    return [load(path) for path in sorted(root.glob("*/connector.yaml"))]
