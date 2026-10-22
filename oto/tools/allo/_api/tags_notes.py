"""Allo tags and internal notes (on a conversation, on a person of the CRM).

Composed into `AlloClient`, which provides the transport (`_request`)."""
from __future__ import annotations

from typing import Any, List, Optional

from ._common import _segment, _size


class _TagsNotesMixin:
    """Team tags on calls, and team notes that the contact never sees."""

    # --- tags --------------------------------------------------------------

    def list_tags(self) -> Any:
        return self._request("GET", "/v2/api/tags")

    def create_tag(self, name: str, *, color: Optional[str] = None) -> Any:
        """A team tag; its key is the slug of its name."""
        return self._request("POST", "/v2/api/tags", body={"name": name, "color": color})

    def delete_tag(self, tag_id: str) -> Any:
        """Delete a team tag by its key; a tag synced from a CRM integration cannot be."""
        return self._request("DELETE", f"/v2/api/tags/{_segment(tag_id, 'tag_id')}")

    def add_item_tags(self, item_id: str, tags: List[str]) -> Any:
        """Tag a call with tag keys."""
        if not tags:
            raise ValueError("`tags` must list at least one tag key.")
        return self._request(
            "POST", f"/v2/api/conversations/items/{_segment(item_id, 'item_id')}/tags",
            body={"tags": list(tags)})

    def remove_item_tag(self, item_id: str, tag: str) -> Any:
        return self._request(
            "DELETE",
            f"/v2/api/conversations/items/{_segment(item_id, 'item_id')}/tags/{_segment(tag, 'tag')}")

    # --- notes on a conversation -------------------------------------------

    def list_conversation_notes(self, contact_number: str, allo_number: str, *,
                                page: Optional[int] = None, size: Optional[int] = None) -> Any:
        return self._request(
            "GET", f"/v2/api/conversations/{_segment(contact_number, 'contact_number')}/notes",
            params={"allo_number": allo_number, "page": page, "size": _size(size)})

    def create_conversation_note(self, contact_number: str, content: str, *,
                                 allo_number: Optional[str] = None,
                                 sender_id: Optional[str] = None) -> Any:
        """An internal team note on a conversation, never shown to the contact."""
        return self._request(
            "POST", f"/v2/api/conversations/{_segment(contact_number, 'contact_number')}/notes",
            body={"content": content, "allo_number": allo_number, "sender_id": sender_id})

    def get_conversation_note(self, note_id: str) -> Any:
        """One note on a conversation (`not-*`)."""
        return self._request("GET", f"/v2/api/conversations/notes/{_segment(note_id, 'note_id')}")

    def update_conversation_note(self, note_id: str, content: str) -> Any:
        """Replace a note's content; only its author may."""
        return self._request("PATCH", f"/v2/api/conversations/notes/{_segment(note_id, 'note_id')}",
                             body={"content": content})

    def delete_conversation_note(self, note_id: str) -> Any:
        """Only the note's author may delete it."""
        return self._request("DELETE", f"/v2/api/conversations/notes/{_segment(note_id, 'note_id')}")

    # --- notes on a person -------------------------------------------------

    def list_person_notes(self, person_id: str, *, page: Optional[int] = None,
                          size: Optional[int] = None) -> Any:
        return self._request("GET", f"/v2/api/crm/people/{_segment(person_id, 'person_id')}/notes",
                             params={"page": page, "size": _size(size)})

    def create_person_note(self, person_id: str, content: str) -> Any:
        return self._request("POST", f"/v2/api/crm/people/{_segment(person_id, 'person_id')}/notes",
                             body={"content": content})

    def update_person_note(self, person_id: str, note_id: str, content: str) -> Any:
        """Replace a person note's content; only its author may."""
        return self._request(
            "PATCH", f"/v2/api/crm/people/{_segment(person_id, 'person_id')}/notes/{_segment(note_id, 'note_id')}",
            body={"content": content})

    def delete_person_note(self, person_id: str, note_id: str) -> Any:
        """Only the note's author may delete it."""
        return self._request(
            "DELETE", f"/v2/api/crm/people/{_segment(person_id, 'person_id')}/notes/{_segment(note_id, 'note_id')}")
