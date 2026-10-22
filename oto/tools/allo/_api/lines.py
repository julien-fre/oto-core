"""Allo line settings: the call flow of a line, its AI receptionist, the calendars it books on and its voices.

A line is named by its number (E.164), percent-encoded in the path. Composed into `AlloClient`, which provides the
transport (`_request`)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ._common import _choice, _items_without, _segment

# The address of a voice's audio sample: no audio address leaves the client.
_VOICE_SAMPLE_FIELDS = ("demo_url",)


def _line(number: str) -> str:
    return f"/v2/api/numbers/{_segment(number, 'number')}"


class _LinesMixin:
    """Call flow (draft, then publish), AI receptionist, calendars and voices."""

    # --- call flow ---------------------------------------------------------

    def get_call_flow(self, number: str, *, status: Optional[str] = None) -> Any:
        """The published call flow of a line, or its draft (`status="draft"`, the published one when none)."""
        return self._request("GET", f"{_line(number)}/call_flow",
                             params={"status": _choice("status", status, ("draft", "published"))})

    def get_call_flow_draft(self, number: str) -> Any:
        """The draft only, with its `lock_version`: 404 when the line has none."""
        return self._request("GET", f"{_line(number)}/call_flow/draft")

    def save_call_flow_draft(self, number: str, definition: Dict[str, Any], schema_version: int, *,
                             lock_version: Optional[int] = None, base_published_version: Optional[int] = None,
                             engine_subset: Optional[str] = None) -> Any:
        """Create or replace the draft; nothing is live until `publish_call_flow`."""
        return self._request("PUT", f"{_line(number)}/call_flow/draft", body={
            "definition": definition, "schema_version": schema_version, "lock_version": lock_version,
            "base_published_version": base_published_version,
            "engine_subset": _choice("engine_subset", engine_subset, ("NESTED_IVR", "FULL_FLOW"))})

    def publish_call_flow(self, number: str, lock_version: int) -> Any:
        """Make the draft the live routing of the line, at once; the draft is consumed."""
        return self._request("POST", f"{_line(number)}/call_flow/publish", body={"lock_version": lock_version})

    # --- AI receptionist ---------------------------------------------------

    def get_receptionist(self, number: str) -> Any:
        """The whole configuration of a line's AI receptionist: read it before any write."""
        return self._request("GET", f"{_line(number)}/agent")

    def update_receptionist(self, number: str, **fields: Any) -> Any:
        """`fields`: name, business_*, language, voice_id, greeting_message, closing_message, tone_of_voice,
        answer_type, capabilities, business_hours, transfer_rules, scheduling, knowledge. A single value given
        changes, one left out stays; a collection given replaces the configured one whole."""
        if not fields:
            raise ValueError("`update_receptionist` changes nothing: give at least one field.")
        return self._request("PATCH", f"{_line(number)}/agent", body=fields)

    def set_receptionist_status(self, number: str, status: str) -> Any:
        """`ACTIVE` puts the receptionist on the line; `FORWARDING` sends calls to the business phone."""
        if status is None:
            raise ValueError("`status` is required.")
        return self._request("PUT", f"{_line(number)}/agent/status",
                             body={"status": _choice("status", status, ("ACTIVE", "FORWARDING"))})

    def set_receptionist_prompt(self, number: str, sections: List[Dict[str, Any]]) -> Any:
        """Replace the whole prompt: every section, the unchanged ones included."""
        if not sections:
            raise ValueError("`sections` must list the prompt's sections.")
        return self._request("PUT", f"{_line(number)}/agent/prompt", body={"sections": list(sections)})

    def add_receptionist_website(self, number: str, url: str) -> Any:
        """A website Allo crawls in the background for the receptionist to answer from."""
        if not url:
            raise ValueError("`url` is required.")
        return self._request("POST", f"{_line(number)}/agent/knowledge/websites", body={"url": url})

    def update_receptionist_website(self, number: str, website_id: str, status: str) -> Any:
        """Turn a website on (`ACTIVE`) or off (`DISABLED`) for this line, its crawled content kept."""
        if status is None:
            raise ValueError("`status` is required.")
        return self._request(
            "PATCH", f"{_line(number)}/agent/knowledge/websites/{_segment(website_id, 'website_id')}",
            body={"status": _choice("status", status, ("ACTIVE", "DISABLED"))})

    def delete_receptionist_website(self, number: str, website_id: str) -> Any:
        """Delete a website from the team's knowledge library, for every line."""
        return self._request(
            "DELETE", f"{_line(number)}/agent/knowledge/websites/{_segment(website_id, 'website_id')}")

    def delete_receptionist_file(self, number: str, file_id: str) -> Any:
        """Delete an uploaded document from the team's knowledge library, for every line."""
        return self._request("DELETE", f"{_line(number)}/agent/knowledge/files/{_segment(file_id, 'file_id')}")

    # --- calendars and voices ----------------------------------------------

    def list_calendars(self) -> Any:
        """The calendars connected to the workspace that the key's user can see."""
        return self._request("GET", "/v2/api/calendars")

    def get_calendar(self, calendar_id: str) -> Any:
        """One calendar with the event types its provider offers now."""
        return self._request("GET", f"/v2/api/calendars/{_segment(calendar_id, 'calendar_id')}")

    def list_voices(self) -> Any:
        """The voices a receptionist may speak with, by language, without the address of their audio sample."""
        return _items_without(self._request("GET", "/v2/api/voices"), fields=_VOICE_SAMPLE_FIELDS)
