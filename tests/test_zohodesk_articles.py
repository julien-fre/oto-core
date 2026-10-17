"""Zoho Desk — Help Center articles: listing and keyword search."""
from oto.tools.zohodesk.client import ZohoDeskClient, _required_scope


def _client(monkeypatch, answer):
    c = ZohoDeskClient(client_id="id", client_secret="secret", refresh_token="rt")
    calls = []

    def fake(method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs.get("params")))
        return answer

    monkeypatch.setattr(c, "_request", fake)
    return c, calls


def test_search_sends_query_as_all_and_only_given_criteria(monkeypatch):
    page = {"data": [{"id": "1", "title": "Reset a password"}], "count": 1}
    c, calls = _client(monkeypatch, page)
    assert c.search_articles("password", tag="account", limit=500) == page
    assert calls == [("GET", "articles/search",
                      {"from": 0, "limit": 100, "_all": "password", "tag": "account"})]


def test_search_with_no_match_is_an_empty_page(monkeypatch):
    c, _ = _client(monkeypatch, {})  # 204 No Content
    assert c.search_articles(title="nothing") == {"data": [], "count": 0}


def test_listing_limit_follows_zoho_range(monkeypatch):
    c, calls = _client(monkeypatch, {"data": []})
    c.list_articles(limit=100)
    assert calls[0][2]["limit"] == 50


def test_search_scope_is_named():
    assert _required_scope("articles/search", "GET") == "Desk.search.READ"
    assert _required_scope("articles/123", "GET") == "Desk.articles.READ"
