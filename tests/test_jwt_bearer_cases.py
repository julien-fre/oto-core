"""Les cas communs du compte de service (`connectors/_cases/jwt_bearer.yaml`), joués côté Python, une ligne par cas.

La lib ne signe la requête d'aucune description : seul le moteur du paquet de l'hôte le fait. Les cas se jouent donc ici
contre une référence écrite dans le test (`cryptography`), qui dit la sémantique du format (`docs/conception/compte.md`),
recoupée par la bibliothèque de Google (`google.auth`, extra `google`) : même signature, et un jeton qu'elle vérifie. Le
paquet de l'hôte joue les mêmes cas, sortis par la fabrique dans `ts/src/jwt-bearer-cases.ts`, contre son moteur.
"""
from __future__ import annotations

import base64
import datetime
import json
import pathlib
import re
import urllib.parse

import pytest
import yaml
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from fabrique import jwt_bearer_cases
from fabrique.build import generate
from fabrique.descriptions import DescriptionError

LOADED = jwt_bearer_cases.load()
LIFETIME_S = 3600
PEM_HEAD = f"-----BEGIN {jwt_bearer_cases.PEM_LABEL}-----\n"


class Refused(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def read_key(auth: dict, text: str) -> tuple[dict, rsa.RSAPrivateKey]:
    """La référence : la clé lue, ou son refus, jugé dans cet ordre."""
    try:
        key = json.loads(text)
    except ValueError:
        raise Refused("service_account_key_not_json") from None
    if not isinstance(key, dict):
        raise Refused("service_account_key_not_json")
    if any(not isinstance(key.get(field), str) or not key[field] for field in ("client_email", "private_key")):
        raise Refused("service_account_key_incomplete")
    if "token_uri" in key and key["token_uri"] != auth["token_url"]:
        raise Refused("service_account_key_foreign_token_uri")
    if not key["private_key"].startswith(PEM_HEAD):
        raise Refused("service_account_key_unreadable")
    try:
        private = serialization.load_pem_private_key(key["private_key"].encode("ascii"), password=None)
    except (ValueError, TypeError):
        raise Refused("service_account_key_unreadable") from None
    if not isinstance(private, rsa.RSAPrivateKey):
        raise Refused("service_account_key_unreadable")
    return key, private


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _segment(value: dict) -> str:
    return _b64url(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def assertion(auth: dict, key: dict, private: rsa.RSAPrivateKey, now: int) -> tuple[dict, dict, str, str]:
    """La référence : en-tête, revendications, entrée signée et signature RS256 (PKCS#1 v1.5, SHA-256, déterministe)."""
    header = {"alg": "RS256", "typ": "JWT"}
    if key.get("private_key_id"):
        header["kid"] = key["private_key_id"]
    claims = {"iss": key["client_email"], "scope": " ".join(auth["scopes"]), "aud": auth["token_url"],
              "iat": now, "exp": now + LIFETIME_S}
    signing_input = f"{_segment(header)}.{_segment(claims)}"
    signature = _b64url(private.sign(signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256()))
    return header, claims, signing_input, signature


def token_body(jwt: str) -> str:
    """La référence : le corps en formulaire de la requête de jeton, `grant_type` puis `assertion`."""
    return urllib.parse.urlencode([("grant_type", jwt_bearer_cases.GRANT_TYPE), ("assertion", jwt)])


def outcome(answer: dict, now: int) -> dict:
    """La référence : une redirection n'est jamais suivie ; `invalid_grant`, la clé refusée ; sinon le jeton et son échéance."""
    status, body = answer["status"], answer["body"]
    if 300 <= status < 400:
        return {"refusal": "upstream_error"}
    if status >= 400:
        rejected = isinstance(body, dict) and body.get("error") == "invalid_grant"
        return {"refusal": "credential_rejected" if rejected else "upstream_error"}
    return {"headers": {"authorization": f"Bearer {body['access_token']}"}, "expires_at": now + int(body["expires_in"])}


def _value(case: dict) -> str:
    return jwt_bearer_cases.credential_value(case, LOADED.test_key)


@pytest.mark.parametrize("case", LOADED.cases, ids=[case["name"] for case in LOADED.cases])
def test_jwt_bearer_case(case):
    key, private = read_key(case["auth"], _value(case))
    header, claims, signing_input, signature = assertion(case["auth"], key, private, case["now"])
    expected = case["assertion"]
    assert (list(header.items()), list(claims.items()), signature) == \
        (list(expected["header"].items()), list(expected["claims"].items()), expected["signature"])
    request = case["token_request"]
    assert request["url"] == case["auth"]["token_url"]
    assert token_body(f"{signing_input}.{signature}") == request["body"].replace(jwt_bearer_cases.ASSERTION, f"{signing_input}.{signature}")
    assert outcome(case["token_answer"], case["now"]) == case["outcome"]


@pytest.mark.parametrize("case", LOADED.refused, ids=[case["name"] for case in LOADED.refused])
def test_jwt_bearer_refused_key(case):
    with pytest.raises(Refused) as refused:
        read_key(case["auth"], _value(case))
    assert refused.value.code == case["refusal"]


@pytest.mark.parametrize("case", LOADED.cases, ids=[case["name"] for case in LOADED.cases])
def test_google_auth_signs_and_verifies_the_same_assertion(case, monkeypatch):
    """Recoupement : la bibliothèque de Google signe la même entrée de la même signature, et vérifie le jeton (signature,
    audience, `iat` et `exp`) à l'horloge du cas."""
    from google.auth import _helpers, crypt, jwt

    key = json.loads(_value(case))
    header, _, signing_input, signature = assertion(case["auth"], *read_key(case["auth"], _value(case)), case["now"])
    signer = crypt.RSASigner.from_service_account_info(key)
    assert _b64url(signer.sign(signing_input)) == signature
    assert signer.key_id == header.get("kid")
    public = serialization.load_pem_private_key(key["private_key"].encode("ascii"), password=None).public_key()
    certs = public.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")
    clock = datetime.datetime.fromtimestamp(case["now"], tz=datetime.timezone.utc).replace(tzinfo=None)
    monkeypatch.setattr(_helpers, "utcnow", lambda: clock)
    claims = jwt.decode(f"{signing_input}.{signature}", certs=certs, audience=case["auth"]["token_url"])
    assert claims == case["assertion"]["claims"]


def test_the_cases_cover_the_mode():
    kids = {"kid" in case["assertion"]["header"] for case in LOADED.cases}
    assert kids == {True, False}
    assert any(len(case["auth"]["scopes"]) > 1 for case in LOADED.cases)
    assert any("token_uri" not in case["key_file"] for case in LOADED.cases)
    assert {case["outcome"].get("refusal") for case in LOADED.cases} == {None, *jwt_bearer_cases.TOKEN_REFUSALS}
    assert {case["refusal"] for case in LOADED.refused} == set(jwt_bearer_cases.KEY_REFUSALS)
    assert {case.get("private_key") for case in LOADED.refused} >= {"absent", "truncated", "not_pem"}


# Les règles de secrets d'oto-core (`scripts/check-public.mjs`), qui copie la sortie TypeScript dans ses tests : un
# en-tête PEM de clé privée et un JWT écrits en clair y sont refusés, dans l'arbre comme dans l'historique.
PRIVATE_KEY_RULE = re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY(?: BLOCK)?-----")
JWT_RULE = re.compile(r"\beyJ[\w-]{7,}\.[\w-]{10,}\.[\w-]{10,}")


def test_no_private_key_nor_jwt_is_written_in_clear():
    texts = {jwt_bearer_cases.CASES.name: jwt_bearer_cases.CASES.read_text(encoding="utf-8"),
             jwt_bearer_cases.OUTPUT_NAME: generate().files[jwt_bearer_cases.OUTPUT_NAME],
             pathlib.Path(jwt_bearer_cases.__file__).name: pathlib.Path(jwt_bearer_cases.__file__).read_text(encoding="utf-8"),
             pathlib.Path(__file__).name: pathlib.Path(__file__).read_text(encoding="utf-8")}
    for name, text in texts.items():
        for line in text.splitlines():
            assert not PRIVATE_KEY_RULE.search(line) and not JWT_RULE.search(line), name
    assert PRIVATE_KEY_RULE.search(_value(LOADED.cases[0])), "the value framed at run time is a PEM private key"


def _write(tmp_path: pathlib.Path, mutate) -> pathlib.Path:
    data = yaml.safe_load(jwt_bearer_cases.CASES.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "jwt_bearer.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def _case(data, name):
    return next(case for case in data["cases"] + data["refused"] if case["name"] == name)


FIRST = LOADED.cases[0]["name"]
FIRST_REFUSED = LOADED.refused[0]["name"]


@pytest.mark.parametrize("mutate, message", [
    (lambda d: _case(d, FIRST)["auth"].update(key="other"), "auth.key names 'other', which is not a credential field"),
    (lambda d: _case(d, FIRST)["credential"].append({"name": "other", "label": "Other", "secret": True}),
     "takes a single credential field"),
    (lambda d: _case(d, FIRST)["credential"][0].update(secret=False), "must be a secret field"),
    (lambda d: _case(d, FIRST)["auth"].pop("scopes"), "does not match the description schema"),
    (lambda d: _case(d, FIRST)["auth"].update(token_url="https://{tenant}.example.test/token"), "does not match the description schema"),
    (lambda d: _case(d, FIRST)["auth"].update(kind="bearer"), "does not match the jwt bearer cases form"),
    (lambda d: _case(d, FIRST)["token_request"].update(url="https://other.example.test/token"), "token_request.url is not auth.token_url"),
    (lambda d: _case(d, FIRST)["token_request"].update(body="grant_type=x"), "ends with the one {assertion}"),
    (lambda d: _case(d, FIRST_REFUSED).update(key_file={"client_email": "x"}, private_key="absent"), "does not match the jwt bearer cases form"),
    (lambda d: _case(d, FIRST_REFUSED).update(name=FIRST), "declared twice"),
], ids=["key_not_a_field", "second_field", "key_not_secret", "without_scopes", "token_url_template", "kind_not_jwt_bearer",
        "request_elsewhere", "body_without_assertion", "key_text_and_key_file", "name_twice"])
def test_a_case_is_checked_like_a_description(tmp_path, mutate, message):
    with pytest.raises(DescriptionError, match=re.escape(message) if "{" in message else message):
        jwt_bearer_cases.load(_write(tmp_path, mutate))
