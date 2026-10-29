"""PipecornClient: the hosts, the body sent, the local refusals, the cost read."""
from unittest.mock import MagicMock

import pytest

from oto.tools.common.errors import UpstreamHTTPError
from oto.tools.http.client import RedirectRefused
from oto.tools.pipecorn import PipecornClient, credits_spent
from oto.tools.common.credentials import MissingCredential


def _resp(status=200, body=None, headers=None):
    import json as _json
    r = MagicMock()
    r.status_code = status
    r.headers = headers or {}
    r.content = _json.dumps(body if body is not None else {}).encode()
    r.json.return_value = body if body is not None else {}
    r.text = r.content.decode()
    return r


@pytest.fixture
def client():
    c = PipecornClient(api_key="pc_test_demo")
    c.session.request = MagicMock(return_value=_resp(body={"status": "finished"}))
    return c


def _sent(c):
    args, kwargs = c.session.request.call_args
    return args[0], args[1], kwargs


def test_key_is_required():
    with pytest.raises(MissingCredential):
        PipecornClient(api_key=None)


def test_key_goes_in_x_api_key(client):
    assert client.session.headers["X-API-KEY"] == "pc_test_demo"
    assert "Authorization" not in client.session.headers


def test_sync_enrichment_goes_to_the_api_host_never_the_app_host(client):
    # The same path on app.pipecorn.com/api/v2 is the ASYNC enrichment: it answers
    # 200 "pending" with no result, silently.
    client.enrich_contact(["phone"], linkedin_url="https://www.linkedin.com/in/x/")
    method, url, _ = _sent(client)
    assert method == "POST"
    assert url == "https://api.pipecorn.com/v2/contacts/single_enrich"


def test_credits_and_account_go_to_the_app_host(client):
    client.get_credits()
    assert _sent(client)[1] == "https://app.pipecorn.com/api/v2/credits"
    client.get_account_info()
    assert _sent(client)[1] == "https://app.pipecorn.com/api/v2/account"
    client.probe()
    assert _sent(client)[:2] == ("GET", "https://app.pipecorn.com/api/v2/credits")


def test_body_phone_type_and_countries(client):
    client.enrich_contact(["phone", "phone"], linkedin_url=" https://www.linkedin.com/in/x/ ",
                          phone_type="mobile", phone_country_codes=["fr", "US"],
                          idempotency_key="k-1", timeout=15)
    _, _, kw = _sent(client)
    assert kw["json"] == {"enrichment_type": ["phone"],
                          "linkedin_url": "https://www.linkedin.com/in/x/",
                          "phone_type": ["mobile"], "phone_country_codes": ["FR", "US"]}
    assert kw["headers"] == {"Idempotency-Key": "k-1"}
    assert kw["timeout"] == 15
    assert kw["allow_redirects"] is False


def test_email_by_name_and_domain(client):
    client.enrich_contact(["email"], firstname="Ada", lastname="Lovelace", domain="acme.com")
    assert _sent(client)[2]["json"] == {"enrichment_type": ["email"], "firstname": "Ada",
                                        "lastname": "Lovelace", "domain": "acme.com"}
    assert _sent(client)[2]["headers"] is None


@pytest.mark.parametrize("kwargs, match", [
    ({"enrichment_type": ["phone"]}, "linkedin_url"),
    ({"enrichment_type": ["personal_email"]}, "linkedin_url"),
    ({"enrichment_type": ["email"], "firstname": "A", "domain": "a.com"}, "firstname"),
    ({"enrichment_type": ["email"], "firstname": "A", "lastname": "B"}, "domain"),
    ({"enrichment_type": []}, "non-empty"),
    ({"enrichment_type": ["fax"], "linkedin_url": "u"}, "Unknown"),
    ({"enrichment_type": ["phone"], "linkedin_url": "u", "phone_type": "landline"}, "phone_type"),
    ({"enrichment_type": ["phone"], "linkedin_url": "u", "phone_country_codes": ["FRA"]}, "alpha-2"),
    ({"enrichment_type": ["phone"], "linkedin_url": "u", "phone_country_codes": []}, "alpha-2"),
    ({"enrichment_type": ["phone"], "linkedin_url": "u", "custom": "x"}, "custom"),
])
def test_refused_before_any_call(client, kwargs, match):
    with pytest.raises(ValueError, match=match):
        client.enrich_contact(**kwargs)
    client.session.request.assert_not_called()


def test_upstream_refusal_is_typed_and_never_retried(client):
    client.session.request.return_value = _resp(
        402, {"error": "Not enough enrichment credits left", "code": "insufficient_credits"})
    with pytest.raises(UpstreamHTTPError) as e:
        client.enrich_contact(["phone"], linkedin_url="u")
    assert e.value.status_code == 402
    assert client.session.request.call_count == 1


def test_redirect_is_refused(client):
    client.session.request.return_value = _resp(302, headers={"Location": "https://evil.example"})
    with pytest.raises(RedirectRefused):
        client.get_credits()


@pytest.mark.parametrize("answer, spent", [
    ({"phones": [], "phone_details": [], "phone_status": "not_found"}, 0),
    ({"phone_details": [{"number": "+33612345678", "type": "mobile"}]}, 30),
    ({"phone_details": [{"number": "+12015550123", "type": "fixed_or_mobile"}]}, 30),
    ({"phone_details": [{"number": "+33145678901", "type": "fixed_line"}]}, 0),
    ({"phone_details": [{"number": "Contacts not shared", "type": "mobile"}]}, 0),
    ({"email": "a@b.com", "email_status": "deliverable",
      "phone_details": [{"number": "+33612345678", "type": "mobile"},
                        {"number": "+33612345679", "type": "mobile"}]}, 33),
    ({"email": None, "personal_email": "a@gmail.com"}, 9),
    (None, 0),
    ("oops", 0),
])
def test_credits_spent(answer, spent):
    assert credits_spent(answer) == spent


def test_credits_spent_counts_only_what_was_asked():
    # The sandbox answers every field whatever was asked: a phone-only call that
    # comes back with an email too costs the phone alone.
    answer = {"email": "a@b.com",
              "phone_details": [{"number": "+33612345678", "type": "mobile"}]}
    assert credits_spent(answer, ["phone"]) == 30
    assert credits_spent(answer, ["email"]) == 3
    assert credits_spent(answer) == 33
