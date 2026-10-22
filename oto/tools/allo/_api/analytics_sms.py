"""Allo team analytics and SMS sending. Composed into `AlloClient`, which provides the transport (`_request`)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ._common import _choice, _size


class _AnalyticsSmsMixin:
    """Team KPIs, the outbound funnel, and a text sent now."""

    def get_team_metrics(self, date: Dict[str, str], *,
                         compare_date: Optional[Dict[str, str]] = None,
                         user_ids: Optional[List[str]] = None,
                         allo_numbers: Optional[List[str]] = None) -> Any:
        """Team KPIs over `date` ({from, to}), against `compare_date`, per user."""
        return self._request("POST", "/v2/api/analytics/overview", body={
            "date": date, "compare_date": compare_date, "user_ids": user_ids,
            "allo_numbers": allo_numbers})

    def get_outbound_metrics(self, date: Dict[str, str], *,
                             compare_date: Optional[Dict[str, str]] = None,
                             user_ids: Optional[List[str]] = None,
                             allo_numbers: Optional[List[str]] = None,
                             tags: Optional[List[str]] = None, granularity: Optional[str] = None,
                             extend: Optional[str] = None, stage: Optional[str] = None,
                             page: Optional[int] = None, size: Optional[int] = None) -> Any:
        """The outbound funnel (dials → connected → conversations → conversions,
        a conversion being a call carrying one of `tags`), its time series,
        heatmap and leaderboard; `extend="items"` with `stage` lists the calls."""
        if extend is not None and extend != "items":
            raise ValueError("`extend` only takes `items`.")
        if extend and not stage:
            raise ValueError("`extend=items` requires `stage`.")
        return self._request("POST", "/v2/api/analytics/outbound", body={
            "date": date, "compare_date": compare_date, "user_ids": user_ids,
            "allo_numbers": allo_numbers, "tags": tags,
            "granularity": _choice("granularity", granularity, ("DAY", "WEEK", "MONTH")),
            "extend": extend,
            "stage": _choice("stage", stage, ("DIAL", "CONNECTED", "CONVERSATION", "CONVERSION")),
            "page": page, "size": _size(size)})

    def send_sms(self, to: str, message: str, *, from_number: Optional[str] = None,
                 sender_id: Optional[str] = None) -> Any:
        """Send a text now: from one of the team's numbers (`from_number`), or
        from a Sender ID verified by Allo (`sender_id`, France)."""
        if (from_number is None) == (sender_id is None):
            raise ValueError("Give exactly one of `from_number` or `sender_id`.")
        return self._request("POST", "/v1/api/sms", body={
            "from": from_number, "sender_id": sender_id, "to": to, "message": message})
