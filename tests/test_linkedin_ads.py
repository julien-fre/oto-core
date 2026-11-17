"""Contrat du connecteur LinkedIn Ads (Advertising API, lecture seule).

Aucun réseau : une doublure de session capture l'URL et les en-têtes envoyés. Vérifié
ici ce qui échoue en silence autrement — la syntaxe Rest.li 2.0 (`List(...)` aux
éléments encodés, `search` et `dateRange` en enregistrements, l'URN d'une publicité
encodé dans le chemin) comparée OCTET POUR OCTET aux exemples de la documentation de
LinkedIn, les en-têtes versionnés, le choix du finder selon le nombre de pivots, les
bornes (métriques, pivots, facettes), les portées en lecture seule, et qu'aucun appel
n'est autre chose qu'un GET.
"""
from __future__ import annotations

import ast
import pathlib
from urllib.parse import parse_qs, urlparse

import pytest

from oto.tools.common.errors import UpstreamHTTPError
from oto.tools.linkedin_ads import LinkedInAdsClient
from oto.tools.linkedin_ads import auth
from oto.tools.linkedin_ads import client as mod

BASE = "https://api.linkedin.com/rest"


class _Reponse:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self._payload = {} if payload is None else payload
        self.headers = headers or {}
        self.text = str(self._payload)
        self.request = None

    def json(self):
        return self._payload


class _Session:
    def __init__(self, reponse=None):
        self.headers: dict = {}
        self.appels: list = []
        self.reponse = reponse or _Reponse(payload={"elements": []})

    def get(self, url, headers=None, timeout=None, allow_redirects=True):
        self.appels.append({"url": url, "headers": headers or {}, "timeout": timeout,
                            "allow_redirects": allow_redirects})
        return self.reponse


@pytest.fixture
def li():
    c = LinkedInAdsClient("JETON")
    c.session = _Session()
    c.session.headers.update({"Authorization": "Bearer JETON"})
    return c


def _url(li) -> str:
    return li.session.appels[-1]["url"]


# --- en-têtes et construction --------------------------------------------------------

def test_headers_are_versioned_and_restli_2():
    c = LinkedInAdsClient("JETON")
    assert c.session.headers["Authorization"] == "Bearer JETON"
    assert c.session.headers["LinkedIn-Version"] == mod.LINKEDIN_VERSION
    assert c.session.headers["X-Restli-Protocol-Version"] == "2.0.0"


def test_a_token_is_required_and_a_version_is_yyyymm():
    from oto.tools.common.credentials import MissingCredential
    with pytest.raises(MissingCredential):
        LinkedInAdsClient("")
    with pytest.raises(ValueError, match="YYYYMM"):
        LinkedInAdsClient("JETON", version="2026-10")


def test_no_redirect_is_followed(li):
    li.get_ad_account(123)
    assert li.session.appels[-1]["allow_redirects"] is False


# --- URL octet pour octet (exemples de la documentation) ------------------------------

def test_account_search_matches_the_documented_sample(li):
    li.search_ad_accounts(statuses=["ACTIVE", "CANCELED"])
    assert _url(li) == (f"{BASE}/adAccounts?q=search"
                        "&search=(status:(values:List(ACTIVE,CANCELED)))")


def test_account_search_without_criteria_returns_all_and_test_is_a_scalar(li):
    li.search_ad_accounts()
    assert _url(li) == f"{BASE}/adAccounts?q=search"
    li.search_ad_accounts(test=False, page_size=50, page_token="DgGerr1iVQ_r-x")
    assert _url(li) == (f"{BASE}/adAccounts?q=search&search=(test:false)"
                        "&pageSize=50&pageToken=DgGerr1iVQ_r-x")


def test_campaign_group_search_matches_the_documented_sample(li):
    li.search_campaign_groups("506223315", statuses=["ACTIVE", "DRAFT"])
    assert _url(li) == (f"{BASE}/adAccounts/506223315/adCampaignGroups?q=search"
                        "&search=(status:(values:List(ACTIVE,DRAFT)))")


def test_campaign_search_encodes_group_urns_inside_the_list(li):
    li.search_campaigns(506333826, statuses=["ACTIVE"], types=["SPONSORED_UPDATES"],
                        campaign_group_ids=["urn:li:sponsoredCampaignGroup:42", 43])
    assert _url(li) == (
        f"{BASE}/adAccounts/506333826/adCampaigns?q=search&search=("
        "status:(values:List(ACTIVE)),"
        "campaignGroup:(values:List(urn%3Ali%3AsponsoredCampaignGroup%3A42,"
        "urn%3Ali%3AsponsoredCampaignGroup%3A43)),"
        "type:(values:List(SPONSORED_UPDATES)))")


def test_a_search_without_status_excludes_deleted_entities(li):
    li.search_campaigns(1)
    assert "status:(values:List(ACTIVE,PAUSED,ARCHIVED,COMPLETED,DRAFT))" in _url(li)
    li.search_campaign_groups(1)
    assert "status:(values:List(ACTIVE,PAUSED,ARCHIVED,DRAFT))" in _url(li)


def test_creative_search_matches_the_documented_sample_and_is_a_finder(li):
    li.search_creatives("520866471", campaign_ids=[360035215],
                        intended_statuses=["ARCHIVED", "CANCELED"])
    appel = li.session.appels[-1]
    assert appel["url"] == (
        f"{BASE}/adAccounts/520866471/creatives?q=criteria"
        "&campaigns=List(urn%3Ali%3AsponsoredCampaign%3A360035215)"
        "&intendedStatuses=List(ARCHIVED,CANCELED)")
    assert appel["headers"] == {"X-RestLi-Method": "FINDER"}


def test_a_creative_urn_goes_encoded_in_the_path(li):
    li.get_creative(520866471, "urn:li:sponsoredCreative:120491345")
    assert _url(li) == (f"{BASE}/adAccounts/520866471/creatives/"
                        "urn%3Ali%3AsponsoredCreative%3A120491345")


def test_entity_reads(li):
    li.get_ad_account("urn:li:sponsoredAccount:123")
    assert _url(li) == f"{BASE}/adAccounts/123"
    li.get_campaign_group(123, 456)
    assert _url(li) == f"{BASE}/adAccounts/123/adCampaignGroups/456"
    li.get_campaign(123, "urn:li:sponsoredCampaign:789")
    assert _url(li) == f"{BASE}/adAccounts/123/adCampaigns/789"
    li.list_account_roles()
    assert _url(li) == f"{BASE}/adAccountUsers?q=authenticatedUser"


def test_analytics_one_pivot_matches_the_documented_sample(li):
    li.get_analytics(["MEMBER_COMPANY"], "2024-05-28", "2024-09-30",
                     time_granularity="DAILY", account_ids=[502840441],
                     fields=["externalWebsiteConversions", "impressions",
                             "landingPageClicks", "reactions", "shares",
                             "costInLocalCurrency"])
    url = _url(li)
    assert url == (
        f"{BASE}/adAnalytics?q=analytics&pivot=MEMBER_COMPANY&timeGranularity=DAILY"
        "&dateRange=(start:(year:2024,month:5,day:28),end:(year:2024,month:9,day:30))"
        "&accounts=List(urn%3Ali%3AsponsoredAccount%3A502840441)"
        "&fields=dateRange,pivotValues,externalWebsiteConversions,impressions,"
        "landingPageClicks,reactions,shares,costInLocalCurrency")


def test_analytics_several_pivots_use_the_statistics_finder_and_open_end(li):
    li.get_analytics(["CAMPAIGN", "CREATIVE"], "2024-01-01", campaign_ids=[1234567])
    assert _url(li) == (
        f"{BASE}/adAnalytics?q=statistics&pivots=List(CAMPAIGN,CREATIVE)"
        "&timeGranularity=ALL&dateRange=(start:(year:2024,month:1,day:1))"
        "&campaigns=List(urn%3Ali%3AsponsoredCampaign%3A1234567)"
        "&fields=dateRange,pivotValues," + ",".join(mod.DEFAULT_METRICS))


@pytest.mark.parametrize("kwargs, motif", [
    ({"pivots": [], "start": "2024-01-01", "account_ids": [1]}, "1 to 3"),
    ({"pivots": ["CAMPAIGN"] * 4, "start": "2024-01-01", "account_ids": [1]}, "1 to 3"),
    ({"pivots": ["CAMPAIGN", "MEMBER_SENIORITY"], "start": "2024-01-01",
      "account_ids": [1]}, "only accepted alone"),
    ({"pivots": ["NOPE"], "start": "2024-01-01", "account_ids": [1]}, "Accepted values"),
    ({"pivots": ["CAMPAIGN"], "start": None, "account_ids": [1]}, "required"),
    ({"pivots": ["CAMPAIGN"], "start": "2024-02-30", "account_ids": [1]}, "real date"),
    ({"pivots": ["CAMPAIGN"], "start": "2024-03-01", "end": "2024-02-01",
      "account_ids": [1]}, "before"),
    ({"pivots": ["CAMPAIGN"], "start": "2024-01-01"}, "at least one"),
    ({"pivots": ["CAMPAIGN"], "start": "2024-01-01", "account_ids": [1],
      "fields": [f"m{i}" for i in range(19)]}, "at most 18"),
    ({"pivots": ["CAMPAIGN"], "start": "2024-01-01", "account_ids": [1],
      "fields": ["impressions&q=x"]}, "metric names"),
    ({"pivots": ["CAMPAIGN"], "start": "2024-01-01",
      "account_ids": list(range(21))}, "at most 20"),
])
def test_analytics_bounds_are_checked_before_any_call(li, kwargs, motif):
    with pytest.raises(ValueError, match=motif):
        li.get_analytics(**kwargs)
    assert li.session.appels == []


@pytest.mark.parametrize("valeur", ["12/3", "../x", "urn:li:sponsoredCampaign:1", "", None,
                                    "1 OR 1"])
def test_nothing_but_digits_or_the_right_urn_reaches_a_path(li, valeur):
    with pytest.raises(ValueError):
        li.get_ad_account(valeur)
    assert li.session.appels == []


def test_page_bounds(li):
    with pytest.raises(ValueError, match="between 1 and 100"):
        li.search_creatives(1, page_size=101)
    with pytest.raises(ValueError, match="between 1 and 1000"):
        li.search_campaigns(1, page_size=0)


# --- réponses ------------------------------------------------------------------------

def test_a_search_page_is_reduced_to_elements_and_next_token(li):
    li.session.reponse = _Reponse(payload={"elements": [{"id": 1}],
                                           "metadata": {"nextPageToken": "T2"}})
    assert li.search_ad_accounts() == {"elements": [{"id": 1}], "next_page_token": "T2"}
    li.session.reponse = _Reponse(payload={"elements": []})
    assert li.search_ad_accounts() == {"elements": [], "next_page_token": None}


def test_a_refusal_is_a_typed_upstream_error_with_retry_after(li):
    li.session.reponse = _Reponse(429, {"status": 429, "message": "Too many"},
                                  headers={"Retry-After": "30"})
    with pytest.raises(UpstreamHTTPError) as e:
        li.get_ad_account(1)
    assert e.value.status_code == 429 and e.value.retry_after == 30.0
    assert e.value.service == "linkedin_ads"


# --- lecture seule -------------------------------------------------------------------

def test_scopes_are_read_only():
    assert auth.SCOPES == ("r_ads", "r_ads_reporting")
    assert not any(s.startswith("rw_") or s.startswith("w_") for s in auth.SCOPES)


def test_the_data_client_only_ever_calls_get():
    """Aucun verbe d'écriture dans le client : ni `.post(`, ni `.put(`, ni `.patch(`,
    ni `.delete(`, ni `.request(`. Le seul POST du connecteur est le jeton (`auth`)."""
    source = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
    appels = {n.func.attr for n in ast.walk(ast.parse(source))
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not appels & {"post", "put", "patch", "delete", "request", "send"}


def test_authorize_url_asks_the_read_scopes_only():
    url = auth.authorize_url("CID", "https://h.test/cb", "S1")
    q = parse_qs(urlparse(url).query)
    assert url.startswith(auth.AUTHORIZE_URL + "?")
    assert q == {"response_type": ["code"], "client_id": ["CID"],
                 "redirect_uri": ["https://h.test/cb"], "state": ["S1"],
                 "scope": ["r_ads r_ads_reporting"]}


class _Post:
    def __init__(self, reponse):
        self.reponse = reponse
        self.appels = []

    def __call__(self, url, data=None, timeout=None, allow_redirects=True, **kw):
        assert "params" not in kw
        self.appels.append({"url": url, "data": data, "allow_redirects": allow_redirects})
        return self.reponse


def test_code_exchange_sends_secrets_in_the_body_only(monkeypatch):
    post = _Post(_Reponse(payload={"access_token": "AT", "expires_in": 5184000,
                                   "refresh_token": "RT",
                                   "refresh_token_expires_in": 31536000,
                                   "scope": "r_ads,r_ads_reporting"}))
    monkeypatch.setattr(auth.requests, "post", post)
    grant = auth.exchange_code("CID", "SECRET", "CODE", "https://h.test/cb")
    assert grant == auth.Grant("AT", 5184000, "RT", 31536000, "r_ads,r_ads_reporting")
    appel = post.appels[0]
    assert appel["url"] == auth.TOKEN_URL and appel["allow_redirects"] is False
    assert appel["data"]["client_secret"] == "SECRET" and appel["data"]["code"] == "CODE"
    assert "?" not in appel["url"]


def test_a_grant_without_refresh_token_says_so(monkeypatch):
    monkeypatch.setattr(auth.requests, "post", _Post(_Reponse(payload={
        "access_token": "AT", "expires_in": 5184000})))
    grant = auth.exchange_code("CID", "SECRET", "CODE", "https://h.test/cb")
    assert grant.refresh_token == "" and grant.refresh_token_expires_in == 0


def test_refresh_keeps_the_refresh_token_when_linkedin_omits_it(monkeypatch):
    monkeypatch.setattr(auth.requests, "post", _Post(_Reponse(payload={
        "access_token": "AT2", "expires_in": 5184000})))
    assert auth.refresh("CID", "SECRET", "RT").refresh_token == "RT"


def test_a_dead_refresh_token_is_a_grant_expired(monkeypatch):
    monkeypatch.setattr(auth.requests, "post", _Post(_Reponse(400, {
        "error": "invalid_request",
        "error_description": "The provided authorization grant or refresh token is "
                             "invalid, expired or revoked"})))
    with pytest.raises(auth.LinkedInAdsGrantExpired):
        auth.refresh("CID", "SECRET", "RT")


def test_an_application_refusal_is_not_a_dead_grant(monkeypatch):
    monkeypatch.setattr(auth.requests, "post", _Post(_Reponse(401, {
        "error": "invalid_client", "error_description": "Client authentication failed"})))
    with pytest.raises(auth.LinkedInAdsAuthError) as e:
        auth.refresh("CID", "SECRET", "RT")
    assert not isinstance(e.value, auth.LinkedInAdsGrantExpired)
    assert "SECRET" not in str(e.value)
