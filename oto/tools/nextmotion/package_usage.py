"""Nextmotion — sessions consumed from a package sold on a quote or an invoice.

Nextmotion shows, in its interface, how many sessions of a sold package were
used; its API has no counter for it. What it has is, per appointment, the
care rows counted against a quote or an invoice
(`NextmotionClient.list_appointment_billed_counts`, already reduced to ids and
quantities). This module adds those rows up — it never calls the API itself,
so it is testable without a key.

What it does NOT know: the API does not say which LINE of the quote or invoice
a care row decrements. A row carries the catalogue pricing it applied
(`treatment_pricing`) and the quote or invoice; the sold lines carry a name and
a quantity. Matching a consumed group to a sold line is the caller's reading —
say so to whoever gets the numbers.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Tuple


def consumed_by_billing(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group reduced care rows by (quote, invoice, treatment_type, treatment_pricing).

    Each group: the ids, `consumed` (sum of `quantity`, a missing quantity
    counting 1 — one row is one session), `sessions` (number of rows) and the
    `first` / `last` session dates. Rows tied to neither a quote nor an invoice
    form their own groups (`quote` and `invoice` both None): consumed outside
    any sale. Ordered by first session.
    """
    groups: Dict[Tuple[Any, Any, Any, Any], Dict[str, Any]] = defaultdict(
        lambda: {"consumed": 0, "sessions": 0, "first": None, "last": None})
    for row in rows:
        key = (row.get("quote"), row.get("invoice"), row.get("treatment_type"),
               row.get("treatment_pricing"))
        if any(k is not None and not isinstance(k, str) for k in key):
            raise ValueError(f"unexpected id on care row {row.get('id')}: "
                             "quote, invoice, treatment_type and treatment_pricing are ids.")
        g = groups[key]
        qty = row.get("quantity")
        if qty is not None and (not isinstance(qty, int) or isinstance(qty, bool)):
            raise ValueError(f"unexpected quantity {qty!r} on care row {row.get('id')}.")
        g["consumed"] += 1 if qty is None else qty
        g["sessions"] += 1
        when = row.get("treatment_time")
        if when:
            g["first"] = when if g["first"] is None else min(g["first"], when)
            g["last"] = when if g["last"] is None else max(g["last"], when)
    out = [{"quote": q, "invoice": i, "treatment_type": t, "treatment_pricing": p, **g}
           for (q, i, t, p), g in groups.items()]
    return sorted(out, key=lambda g: (g["first"] or "", str(g["treatment_pricing"])))
