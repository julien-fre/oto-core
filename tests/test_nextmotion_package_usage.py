"""`consumed_by_billing` : les séances décomptées, additionnées par devis ou facture et
par tarif — sans appel réseau, sur des lignes déjà réduites."""
import pytest

from oto.tools.nextmotion import consumed_by_billing


def _row(i, *, invoice=None, quote=None, pricing="P1", qty=1, when="2026-10-01T09:00:00Z"):
    return {"id": i, "invoice": invoice, "quote": quote, "treatment_pricing": pricing,
            "quantity": qty, "treatment_time": when, "treatment_type": "T"}


def test_two_packages_of_the_same_service_stay_apart():
    rows = [_row("a", invoice="F1", when="2026-10-01T09:00:00Z"),
            _row("b", invoice="F2", when="2026-10-03T09:00:00Z"),
            _row("c", invoice="F1", when="2026-10-08T09:00:00Z"),
            _row("d", invoice="F1", qty=None, when="2026-10-15T09:00:00Z")]
    out = consumed_by_billing(rows)
    assert out == [
        {"quote": None, "invoice": "F1", "treatment_type": "T", "treatment_pricing": "P1", "consumed": 3,
         "sessions": 3, "first": "2026-10-01T09:00:00Z", "last": "2026-10-15T09:00:00Z"},
        {"quote": None, "invoice": "F2", "treatment_type": "T", "treatment_pricing": "P1", "consumed": 1,
         "sessions": 1, "first": "2026-10-03T09:00:00Z", "last": "2026-10-03T09:00:00Z"}]


def test_a_session_counted_against_nothing_is_its_own_group():
    out = consumed_by_billing([_row("a"), _row("b", quote="D1", pricing="P2", qty=2)])
    assert [(g["quote"], g["invoice"], g["consumed"]) for g in out] == [
        (None, None, 1), ("D1", None, 2)]


def test_a_strange_quantity_is_refused_rather_than_counted():
    with pytest.raises(ValueError, match="quantity"):
        consumed_by_billing([_row("a", qty="2")])


def test_an_id_that_is_not_an_id_is_refused():
    with pytest.raises(ValueError, match="unexpected id"):
        consumed_by_billing([_row("a", invoice={"id": "F1"})])
