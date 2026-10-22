"""Allo Power Dialer: the current queue of a user, the team's named queues, a dialing session.

The arguments of the named queues (`/{queue_id}`, `/{queue_id}/numbers`) mirror those of the current queue, without
`user_id` or `email`. Composed into `AlloClient`, which provides the transport (`_request`)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..const import DO_NOT_DISTURB, VOICEMAIL_HANDLING
from ._common import _choice, _segment, _size


def _numbers(numbers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not numbers:
        raise ValueError("`numbers` must list at least one entry.")
    return list(numbers)


def _removal(number: Optional[str], position: Optional[int], unassigned: Optional[bool]) -> Dict[str, Any]:
    """By `number`, `position`, both, or `unassigned=True`, never the last with another."""
    if unassigned and (number is not None or position is not None):
        raise ValueError("`unassigned` cannot be combined with `number` or `position`.")
    if not unassigned and number is None and position is None:
        raise ValueError("Give `number`, `position`, or `unassigned=true`.")
    return {"number": number, "position": position, "unassigned": True if unassigned else None}


class _DialerMixin:
    """One current queue per user (the key owner's, or a teammate's by `user_id` or `email`); named queues by id."""

    # --- the current queue -------------------------------------------------

    def get_dialing_queue(self, *, user_id: Optional[str] = None, email: Optional[str] = None,
                          page: Optional[int] = None, size: Optional[int] = None) -> Any:
        """The numbers of a user's current queue, by position, and the queue's settings."""
        return self._request("GET", "/v2/api/dialing-queues/current", params={
            "user_id": user_id, "email": email, "page": page, "size": _size(size)})

    def reset_dialing_queue(self, *, name: Optional[str] = None, user_id: Optional[str] = None,
                            email: Optional[str] = None) -> Any:
        """A fresh, empty queue for the user; the previous one is no longer current."""
        return self._request("POST", "/v2/api/dialing-queues/current", body={
            "name": name, "user_id": user_id, "email": email})

    def update_dialing_queue(self, *, name: Optional[str] = None,
                             voicemail_handling: Optional[str] = None,
                             do_not_disturb: Optional[str] = None, user_id: Optional[str] = None,
                             email: Optional[str] = None) -> Any:
        return self._request("PATCH", "/v2/api/dialing-queues/current", body={
            "name": name,
            "voicemail_handling": _choice("voicemail_handling", voicemail_handling, VOICEMAIL_HANDLING),
            "do_not_disturb": _choice("do_not_disturb", do_not_disturb, DO_NOT_DISTURB),
            "user_id": user_id, "email": email})

    def add_queue_numbers(self, numbers: List[Dict[str, Any]], *, user_id: Optional[str] = None,
                          email: Optional[str] = None) -> Any:
        """Append numbers (each `{number, name?, last_name?, company?, …}`) to the
        queue, made if none exists; answers `added` and `skipped`."""
        return self._request("POST", "/v2/api/dialing-queues/current/numbers", body={
            "numbers": _numbers(numbers), "user_id": user_id, "email": email})

    def remove_queue_numbers(self, *, number: Optional[str] = None,
                             position: Optional[int] = None, unassigned: Optional[bool] = None,
                             user_id: Optional[str] = None, email: Optional[str] = None) -> Any:
        """Remove by `number`, `position` (0-based), both, or `unassigned=True`
        (every entry not yet called)."""
        return self._request("DELETE", "/v2/api/dialing-queues/current/numbers", params={
            **_removal(number, position, unassigned), "user_id": user_id, "email": email})

    def delete_current_dialing_queue(self, *, user_id: Optional[str] = None,
                                     email: Optional[str] = None) -> Any:
        """Delete a user's current queue and its numbers."""
        return self._request("DELETE", "/v2/api/dialing-queues/current", params={
            "user_id": user_id, "email": email})

    # --- named queues ------------------------------------------------------

    def list_dialing_queues(self, *, page: Optional[int] = None, size: Optional[int] = None) -> Any:
        """The team's Power Dialer queues (`pdl-*`) the key may see."""
        return self._request("GET", "/v2/api/dialing-queues", params={"page": page, "size": _size(size)})

    def create_dialing_queue(self, *, name: Optional[str] = None, user_id: Optional[str] = None,
                             email: Optional[str] = None) -> Any:
        """A new, empty queue, assigned to the key owner or to a teammate."""
        return self._request("POST", "/v2/api/dialing-queues", body={
            "name": name, "user_id": user_id, "email": email})

    def get_dialing_queue_by_id(self, queue_id: str, *, page: Optional[int] = None,
                                size: Optional[int] = None) -> Any:
        """The numbers of one queue, by position, and its settings."""
        return self._request("GET", f"/v2/api/dialing-queues/{_segment(queue_id, 'queue_id')}",
                             params={"page": page, "size": _size(size)})

    def update_dialing_queue_by_id(self, queue_id: str, *, name: Optional[str] = None,
                                   voicemail_handling: Optional[str] = None,
                                   do_not_disturb: Optional[str] = None) -> Any:
        return self._request("PATCH", f"/v2/api/dialing-queues/{_segment(queue_id, 'queue_id')}", body={
            "name": name,
            "voicemail_handling": _choice("voicemail_handling", voicemail_handling, VOICEMAIL_HANDLING),
            "do_not_disturb": _choice("do_not_disturb", do_not_disturb, DO_NOT_DISTURB)})

    def delete_dialing_queue(self, queue_id: str) -> Any:
        """Delete one queue and its numbers."""
        return self._request("DELETE", f"/v2/api/dialing-queues/{_segment(queue_id, 'queue_id')}")

    def add_numbers_to_queue(self, queue_id: str, numbers: List[Dict[str, Any]]) -> Any:
        """Append numbers (each `{number, name?, last_name?, company?, …}`) to one queue."""
        return self._request("POST", f"/v2/api/dialing-queues/{_segment(queue_id, 'queue_id')}/numbers",
                             body={"numbers": _numbers(numbers)})

    def remove_numbers_from_queue(self, queue_id: str, *, number: Optional[str] = None,
                                  position: Optional[int] = None,
                                  unassigned: Optional[bool] = None) -> Any:
        """Remove from one queue by `number`, `position` (0-based), both, or `unassigned=True`."""
        return self._request("DELETE", f"/v2/api/dialing-queues/{_segment(queue_id, 'queue_id')}/numbers",
                             params=_removal(number, position, unassigned))

    def assign_dialing_queue(self, queue_id: str, *, user_id: Optional[str] = None,
                             email: Optional[str] = None) -> Any:
        """Hand a queue, numbers kept, to a teammate (`user_id` wins over `email`)."""
        if user_id is None and email is None:
            raise ValueError("Give `user_id` or `email`.")
        return self._request("PATCH", f"/v2/api/dialing-queues/{_segment(queue_id, 'queue_id')}/assignee",
                             body={"user_id": user_id, "email": email})

    def get_dialer_session(self, session_id: str) -> Any:
        """One Power Dialer session."""
        return self._request("GET", f"/v2/api/dialing-queues/sessions/{_segment(session_id, 'session_id')}")
