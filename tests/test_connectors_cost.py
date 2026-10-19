"""Le coût d'un appel côté Python : `oto.connectors.cost` sur les données générées (`oto.connectors.declared`).

Même sémantique que le paquet d'oto 2 (`costOf`, `settledQuantity`, `collectionOf`) : pire cas avant l'appel, quantité
relue après, relève d'un travail soumis. Les cas `request` et `page` se jouent sur des connecteurs décrits ; le coût
pondéré, sur `fullenrich.submit`.
"""
from __future__ import annotations

import pytest

from oto.connectors import cost
from oto.connectors.cost import CostError, collection_of, settled_quantity, worst_case, value_at
from oto.connectors.declared import DECLARED

CONTACT = {"first_name": "Jane", "last_name": "Doe", "domain": "example.com"}


def _contacts(*fields: list[str]) -> dict:
    return {"name": "batch", "contacts": [{**CONTACT, "enrich_fields": f} for f in fields]}


def test_declared_carries_the_weighted_cost_and_the_job():
    submit = DECLARED["fullenrich"]["submit"]
    assert submit["cost"] == {"per": "item", "items": "contacts",
                              "weights": {"field": "enrich_fields",
                                          "values": {"contact.work_emails": 1, "contact.personal_emails": 3, "contact.phones": 10}},
                              "unit": "credits", "settle": {"path": "cost.credits"}}
    assert submit["async"] == {"collect": "fetch", "job_id": {"from": "enrichment_id", "to": "enrichment_id"}, "no_deadline": True}
    assert "fetch" not in DECLARED["fullenrich"]


def test_weighted_worst_case_sums_the_weights_each_item_lists():
    args = _contacts(["contact.work_emails", "contact.phones"], ["contact.personal_emails"], ["contact.work_emails"])
    assert worst_case("fullenrich", "submit", args) == {"quantity": 11 + 3 + 1, "unit": "credits"}


@pytest.mark.parametrize("args", [
    _contacts(["contact.work_emails", "contact.company"]),
    _contacts([]),
    {"name": "batch", "contacts": []},
    {"name": "batch"},
    {"name": "batch", "contacts": [CONTACT]},
], ids=["value_without_weight", "empty_field", "empty_items", "missing_items", "missing_field"])
def test_weighted_worst_case_refuses_unvalidated_arguments(args):
    with pytest.raises(CostError):
        worst_case("fullenrich", "submit", args)


def test_settled_in_credits_from_the_collect_answers():
    args = _contacts(["contact.work_emails", "contact.phones"])
    answers = [{"status": "IN_PROGRESS"}, {"status": "FINISHED", "cost": {"credits": 10}}]
    assert settled_quantity("fullenrich", "submit", args, answers) == {"quantity": 10, "unit": "credits", "from": "response", "exceeded": False}


def test_settled_above_the_worst_case_is_settled_as_read_and_reported():
    args = _contacts(["contact.work_emails"])
    settled = settled_quantity("fullenrich", "submit", args, [{"cost": {"credits": 4}}])
    assert settled == {"quantity": 4, "unit": "credits", "from": "response", "exceeded": True}


@pytest.mark.parametrize("answers", [[], [{"status": "IN_PROGRESS"}], [{"cost": {"credits": "4"}}], [{"cost": {"credits": -1}}],
                                     [{"cost": {"credits": True}}], [{"cost": {"credits": float("inf")}}]],
                         ids=["none", "absent", "text", "negative", "boolean", "infinite"])
def test_unreadable_quantity_settles_the_worst_case(answers):
    args = _contacts(["contact.phones"])
    assert settled_quantity("fullenrich", "submit", args, answers) == {"quantity": 10, "unit": "credits", "from": "unreadable", "exceeded": False}


def test_request_and_page_count_the_requests_sent():
    assert DECLARED["gmail"]["list_messages"] == {"cost": {"per": "page"}, "pagination": {"max_pages": 10}}
    assert worst_case("gmail", "list_messages", {}) == {"quantity": 1, "unit": "pages"}
    assert worst_case("gmail", "list_messages", {"all_pages": True}) == {"quantity": 10, "unit": "pages"}
    assert worst_case("gmail", "list_messages", {"all_pages": True, "max_pages": 3}) == {"quantity": 3, "unit": "pages"}
    assert worst_case("gmail", "list_messages", {"all_pages": True, "max_pages": 30}) == {"quantity": 10, "unit": "pages"}
    assert settled_quantity("gmail", "list_messages", {"all_pages": True}, [{}, {}]) == {"quantity": 2, "unit": "pages", "from": "requests", "exceeded": False}
    assert worst_case("gmail", "get_profile", {}) == {"quantity": 1, "unit": "requests"}
    with pytest.raises(CostError):
        settled_quantity("gmail", "get_profile", {}, [])


def test_function_without_cost_has_none():
    assert worst_case("fullenrich", "fetch", {"enrichment_id": "x"}) is None
    assert settled_quantity("fullenrich", "fetch", {"enrichment_id": "x"}, [{}]) is None
    assert worst_case("nope", "nope", {}) is None


def test_item_times_and_settle_on_other_shapes(monkeypatch):
    monkeypatch.setitem(cost.DECLARED, "example", {"batch": {"cost": {"per": "item", "items": "ids", "times": "fields", "unit": "fields"}}})
    assert worst_case("example", "batch", {"ids": [1, 2], "fields": ["a", "b", "c"]}) == {"quantity": 6, "unit": "fields"}
    assert settled_quantity("example", "batch", {"ids": [1], "fields": ["a"]}, [{}]) == {"quantity": 1, "unit": "fields", "from": "worst_case", "exceeded": False}
    with pytest.raises(CostError):
        worst_case("example", "batch", {"ids": [1], "fields": []})


def test_collection_of_a_submitted_job():
    assert collection_of("fullenrich", "submit", {"enrichment_id": "2db5ea61"}) == {
        "function": "fullenrich.fetch", "args": {"enrichment_id": "2db5ea61"}, "within_s": None, "no_deadline": True}
    assert collection_of("amplitude", "request_cohort_download", {"request_id": 42})["no_deadline"] is False
    assert collection_of("fullenrich", "fetch", {}) is None
    for answer in ({}, {"enrichment_id": ""}, {"enrichment_id": True}, {"enrichment_id": None}):
        with pytest.raises(CostError):
            collection_of("fullenrich", "submit", answer)


def test_value_at_reads_dotted_paths_and_list_indexes():
    assert value_at({"a": [{"b": 3}]}, "a.0.b") == 3
    assert value_at({"a": [{"b": 3}]}, "a.1.b") is None
    assert value_at({"a": 1}, "a.b") is None
