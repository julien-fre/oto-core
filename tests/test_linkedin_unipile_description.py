"""La description `linkedin_unipile` 1.2.0 : la recherche, le fil d'actualité et les produits premium du client.

Le client `oto.tools.unipile` n'est pas tiré de la description (il prend l'identité du compte en paramètre) ; ces
gardes lisent le client lui-même pour les trois fichiers que 1.2.0 rattache (`_api/search.py`, `_api/premium.py`,
`feed.py`) : chaque méthode publique y est une fonction sous son nom, avec les arguments qu'elle nomme et la requête
qu'elle envoie, ou une méthode que le format ne sait pas dire, nommée dans l'en-tête de la description (`NOT_DESCRIBED`).
Écarts nommés, gardés ici : `resolve_facet` sans `limit` laisse Unipile choisir, là où le client envoie 100
(`CLIENT_DEFAULTS`) ; `skill_endorsement_id` est un texte de chiffres, comme Unipile le prend, là où la méthode prend un
entier qu'elle écrit en texte ; les `limit` sont bornés à 100, comme le dit la référence v2.
Rien ne revient à l'agent d'une adresse ouverte sans connexion : les photos d'un membre, d'une entreprise ou d'une école,
et le pixel de suivi d'une offre, sont retirés par la description et par le client.
"""
from __future__ import annotations

import copy
import inspect
import re
from unittest import mock

import jsonschema
import yaml

from fabrique.descriptions import CONNECTORS, check
from fabrique.typescript import connector_module
from oto.tools.unipile import client as unipile_client
from oto.tools.unipile import feed
from oto.tools.unipile._api import premium
from oto.tools.unipile._api.premium import _PremiumMixin
from oto.tools.unipile._api.search import _SearchMixin
from oto.tools.unipile.client import UnipileClient

LINKEDIN = CONNECTORS / "linkedin_unipile" / "connector.yaml"
ACCOUNT = "acc_0"

# Ce que le format ne sait pas dire, et pourquoi (en tête de la description).
NOT_DESCRIBED = {
    "search": "search: one method for three products",
    "member_action": "member_action: the route and the body depend on the pair",
    "get_feed": "get_feed and parse_feed (the home feed)",
}
CLASSES = {
    "read": {"resolve_facet", "list_contracts", "inmail_balance", "list_job_postings", "get_job_posting",
             "list_job_applicants", "get_job_applicant", "list_hiring_projects"},
    # Un réglage de la session premium du compte, envoyé à personne : du côté lecture, comme chez oto 1.
    "write": {"select_contract"},
    # Le membre voit la recommandation aussitôt, comme une invitation.
    "sensitive": {"endorse_profile"},
}
PAGINATED = {"list_job_postings", "list_job_applicants", "list_hiring_projects"}
PERSONAL = {"resolve_facet": {"keywords"}, "endorse_profile": {"profile_id"}, "get_job_applicant": {"applicant_id"}}
OPEN_ADDRESSES = {
    "get_job_posting": ["company.public_picture_url", "tracking_pixel_url"],
    "list_job_applicants": ["profile.public_picture_url", "profile.work_experience.company.picture_url",
                            "profile.educations.school.picture_url"],
    "get_job_applicant": ["profile.public_picture_url", "profile.work_experience.company.picture_url",
                          "profile.educations.school.picture_url"],
    "list_hiring_projects": ["owner.public_picture_url"],
}
# Ce que le client envoie quand l'agent ne dit rien, et que la description laisse au service.
CLIENT_DEFAULTS = {"resolve_facet": {"limit": 100}}
VALUES = {
    "facet_type": "SKILL", "keywords": "Microsoft Excel", "limit": 25, "contract_id": "123456789",
    "profile_id": "ACoAAB1x2y3", "skill_endorsement_id": "7", "cursor": "eyJsaW1pdCI6MjV9", "job_id": "4012345678",
    "applicant_id": "98765",
}


def _description() -> dict:
    return copy.deepcopy(yaml.safe_load(LINKEDIN.read_text(encoding="utf-8")))


def _functions() -> dict[str, dict]:
    return {f["name"]: f for f in _description()["functions"]}


def _mixin_methods(mixin) -> set[str]:
    return {n for n, v in vars(mixin).items() if inspect.isfunction(v) and not n.startswith("_")}


def _covered() -> set[str]:
    """Les méthodes publiques des trois fichiers rattachés, `get_feed` compris (il vit dans `_api/content.py` mais
    lit le fil par `feed.py`)."""
    return _mixin_methods(_SearchMixin) | _mixin_methods(_PremiumMixin) | {"get_feed"}


def _named_parameters(method: str) -> set[str]:
    return {p for p in inspect.signature(getattr(UnipileClient, method)).parameters if p != "self"}


class _Answer:
    status_code = 200
    headers: dict = {}

    def __init__(self, body=None):
        self._body = {} if body is None else body
        self.text = "{}"

    def json(self):
        return copy.deepcopy(self._body)


def _for_the_client(name: str, arguments: dict) -> dict:
    """Les arguments de la description tels que la méthode les prend : l'id de compétence en entier."""
    if name == "endorse_profile" and "skill_endorsement_id" in arguments:
        return dict(arguments, skill_endorsement_id=int(arguments["skill_endorsement_id"]))
    return arguments


def _sent_by_the_client(name: str, arguments: dict, answer=None) -> tuple[dict, object]:
    sent = []

    def request(self, method, url, **kwargs):
        sent.append({"method": method, "url": url, "params": dict(kwargs.get("params") or {}),
                     "json": kwargs.get("json"), "headers": dict(self.headers)})
        return _Answer(answer)

    with mock.patch.object(unipile_client.requests.Session, "request", request):
        returned = getattr(UnipileClient(api_key="k", account_id=ACCOUNT), name)(**_for_the_client(name, arguments))
    assert len(sent) == 1, name
    return sent[0], returned


def _described(function: dict, arguments: dict) -> tuple:
    call = function["call"]
    path = call["path"].format(**{a: arguments[a] for a in re.findall(r"{(\w+)}", call["path"])})
    query = {api: arguments[a] for api, a in call.get("query", {}).items() if a in arguments}
    query |= {k: v for k, v in CLIENT_DEFAULTS.get(function["name"], {}).items() if k not in query}
    body = {api: arguments[a] for api, a in call["body"].items() if a in arguments} if "body" in call else None
    base = _description()["connector"]["base_url"].format(account_id=ACCOUNT)
    return call["method"], base + path, query, body


def _client_view(sent: dict) -> tuple:
    return sent["method"], sent["url"], sent["params"], sent["json"]


def _shaped(answer, paths: list[str], items: str | None = None):
    answer = copy.deepcopy(answer)
    target = answer[items] if items else answer
    for path in paths:
        premium._drop(target, path.split("."))
    return answer


def test_the_description_is_version_1_2_0_and_passes_the_fabrique():
    description = _description()
    assert description["connector"]["version"] == "1.2.0"
    check(description, LINKEDIN)


def test_each_method_of_the_three_files_is_a_function_under_its_name_or_named_as_not_described():
    functions = set(_functions())
    covered = _covered()
    assert covered - functions == set(NOT_DESCRIBED)
    header = LINKEDIN.read_text(encoding="utf-8").split("\nconnector:")[0]
    for name, says in NOT_DESCRIBED.items():
        assert says in header, name
    assert set().union(*CLASSES.values()) == covered - set(NOT_DESCRIBED)
    assert "parse_feed" in header and callable(feed.parse_feed)


def test_each_function_takes_the_arguments_its_client_method_names():
    functions = _functions()
    for name in set().union(*CLASSES.values()):
        function = functions[name]
        assert set(function["input"]["properties"]) == _named_parameters(name), name
        required = {p for p, v in inspect.signature(getattr(UnipileClient, name)).parameters.items()
                    if p != "self" and v.default is inspect.Parameter.empty}
        assert set(function["input"].get("required", [])) == required, name


def test_each_argument_goes_where_the_client_sends_it():
    functions = _functions()
    for name in set().union(*CLASSES.values()):
        function = functions[name]
        every = {a: VALUES[a] for a in function["input"]["properties"]}
        jsonschema.validate(every, function["input"])
        sent, _ = _sent_by_the_client(name, every)
        assert _client_view(sent) == _described(function, every), name
        assert sent["headers"]["X-API-KEY"] == "k"
        fewest = {a: VALUES[a] for a in function["input"].get("required", [])}
        sent, _ = _sent_by_the_client(name, fewest)
        method, url, query, body = _described(function, fewest)
        # Une table de corps sans argument : l'hôte envoie un objet vide, comme le client.
        assert _client_view(sent) == (method, url, query, {} if body == {} else body), name


def test_each_example_sends_what_the_client_sends_for_it():
    functions = _functions()
    for name in set().union(*CLASSES.values()):
        function = functions[name]
        for example in function["examples"]:
            jsonschema.validate(example["input"], function["input"])
            sent, _ = _sent_by_the_client(name, example["input"])
            assert _client_view(sent) == _described(function, example["input"]), (name, example["title"])


def test_where_the_schema_is_narrower_than_the_client_it_is_named():
    functions = _functions()
    for name, case in [("resolve_facet", {"facet_type": "skill", "keywords": "Excel"}),
                       ("resolve_facet", {"facet_type": "SKILL", "keywords": "Excel", "limit": 101}),
                       ("list_job_postings", {"limit": 101}),
                       ("endorse_profile", {"profile_id": "ACoAAB1x2y3", "skill_endorsement_id": "seven"})]:
        assert not jsonschema.Draft202012Validator(functions[name]["input"]).is_valid(case), (name, case)


def test_classes_side_and_confirmation():
    functions = _functions()
    named = set().union(*CLASSES.values())
    assert {c: {n for n in named if functions[n]["class"] == c} for c in CLASSES} == CLASSES
    assert functions["select_contract"]["act"] is False
    for name in named - {"select_contract"}:
        assert "act" not in functions[name], name
    for name in named:
        assert ("confirm" in functions[name]) == (functions[name]["class"] == "sensitive"), name
    summary = functions["endorse_profile"]["confirm"]["summary"]
    assert "{profile_id}" in summary and "{skill_endorsement_id}" in summary


def test_the_lists_page_by_cursor_as_the_client_does():
    functions = _functions()
    for name in set().union(*CLASSES.values()):
        function = functions[name]
        if name not in PAGINATED:
            assert "pagination" not in function, name
            continue
        assert function["pagination"] == {"kind": "cursor", "request_param": "cursor", "next": "next_cursor",
                                          "max_pages": 10}, name
        assert function["output"]["items"] == "data", name


def test_what_names_a_person_is_personal():
    functions = _functions()
    for name in set().union(*CLASSES.values()):
        properties = functions[name]["input"]["properties"]
        assert {p for p, s in properties.items() if s.get("personal")} == PERSONAL.get(name, set()), name


def test_open_addresses_are_stripped_description_and_client():
    """Les photos et le pixel de suivi s'ouvrent sans connexion : retirés par la description (`output.strip`) et par
    le client, mêmes chemins ; l'adresse d'un profil, derrière la connexion LinkedIn, reste."""
    functions = _functions()
    stripped = {n for n in set().union(*CLASSES.values()) if "strip" in functions[n].get("output", {})}
    assert stripped == set(OPEN_ADDRESSES)
    for name, paths in OPEN_ADDRESSES.items():
        function = functions[name]
        assert function["output"]["strip"] == paths, name
        assert tuple(paths) == premium.OPEN_ADDRESS_FIELDS[name], name
        items = function["output"].get("items")
        sample = function["output"]["sample"]
        assert "media.example.test" in str(sample), name
        shaped = _shaped(sample, paths, items)
        assert "media.example.test" not in str(shaped), name
        assert "profile_url" in str(shaped) or name == "get_job_posting" and "c-0" in str(shaped), name
        arguments = {a: VALUES[a] for a in function["input"].get("required", [])}
        _, returned = _sent_by_the_client(name, arguments, sample)
        assert "media.example.test" not in str(returned), name
        for key in (k for k in shaped if k in returned):
            assert returned[key] == shaped[key], (name, key)


def test_the_errors_are_the_connector_table():
    """Ni erreur, ni rythme, ni quota nouveaux : la table commune vaut ; les refus ajoutés disent un 404."""
    functions = _functions()
    for name in set().union(*CLASSES.values()):
        for refusal in functions[name].get("refusals", []):
            assert refusal["when"] == 404, name
    assert "rate_limit" not in _description()["connector"] and "quota" not in _description()["connector"]


def test_the_typescript_output():
    module = connector_module(check(_description(), LINKEDIN))
    for name in set().union(*CLASSES.values()):
        assert f'name: "linkedin_unipile.{name}",' in module.source, name
    assert not module.skipped
