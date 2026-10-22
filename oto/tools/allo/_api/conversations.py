"""Allo conversations: the calls and texts, the audio of a call as a file, a call's summary, a conversation's state.

Composed into `AlloClient`, which provides the transport (`_request`, `_send`, `session`)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ....connectors.files import FileOut, file_output
from ..const import BASE_URL, CONVERSATION_ACTIONS
from ._common import _choice, _items_without_addresses, _segment, _size


class _ConversationsMixin:
    """Calls (`cll-*`) and texts (`msg-*`); every read of a call loses its recording addresses."""

    def list_conversations(self, allo_number: str, *, last_activity_since: Optional[str] = None,
                           unread: Optional[bool] = None, page: Optional[int] = None,
                           size: Optional[int] = None, extend: Optional[str] = None) -> Any:
        """The conversations of one line, by contact, most recent activity first; the
        last item of each without its recording addresses."""
        return _items_without_addresses(self._request("GET", "/v2/api/conversations", params={
            "allo_number": allo_number, "last_activity_since": last_activity_since,
            "unread": unread, "page": page, "size": _size(size), "extend": extend}), under="last_item")

    def search_conversation_items(self, *, allo_number: Optional[str] = None,
                                  contact_number: Optional[str] = None,
                                  user_id: Optional[str] = None, direction: Optional[str] = None,
                                  type: Optional[str] = None, result: Optional[str] = None,
                                  tags: Optional[List[str]] = None, unread: Optional[bool] = None,
                                  unresponded: Optional[bool] = None, search: Optional[str] = None,
                                  date: Optional[Dict[str, str]] = None, sort: Optional[str] = None,
                                  extend: Optional[str] = None, page: Optional[int] = None,
                                  size: Optional[int] = None) -> Any:
        """Calls and texts across every conversation, filtered, without their
        recording addresses; `search` is a keyword over transcripts, summaries and
        message content."""
        return _items_without_addresses(self._request("POST", "/v2/api/conversations/items/search", body={
            "allo_number": allo_number, "contact_number": contact_number, "user_id": user_id,
            "direction": _choice("direction", direction, ("INBOUND", "OUTBOUND")),
            "type": _choice("type", type, ("CALL", "SMS", "ALL")),
            "result": _choice("result", result, ("ANSWERED", "VOICEMAIL", "TRANSFERRED")),
            "tags": tags, "unread": unread, "unresponded": unresponded, "search": search,
            "date": date, "sort": _choice("sort", sort, ("DATE_DESC", "DATE_ASC", "RELEVANCE")),
            "extend": extend, "page": page, "size": _size(size)}))

    def get_conversation_item(self, item_id: str, *, extend: Optional[str] = None) -> Any:
        """One call (`cll-*`) or text (`msg-*`), without its recording addresses."""
        return _items_without_addresses(self._request(
            "GET", f"/v2/api/conversations/items/{_segment(item_id, 'item_id')}", params={"extend": extend}))

    def get_conversation_items(self, ids: List[str]) -> Any:
        """Several items by id in one request, without their recording addresses."""
        if not ids:
            raise ValueError("`ids` must list at least one item id.")
        return _items_without_addresses(
            self._request("POST", "/v2/api/conversations/items/batch", body={"ids": list(ids)}))

    def get_call_recording(self, item_id: str) -> FileOut:
        """The recording of one call (`cll-*`), as a file (`call-<id>-recording.mp3`).

        Raises `UpstreamHTTPError` when the API refuses the call (404: unknown call, or no recording; 403: the key's
        user may not play it, or a HIPAA-enabled team), `FileOutputError` when the file is refused, `requests.Timeout`
        beyond the 120 s of the function."""
        segment = _segment(item_id, "item_id")
        answer = self._send("GET", f"/v2/api/conversations/items/{segment}/recording", stream=True)
        return file_output("allo", "get_call_recording", answer=answer, args={"item_id": str(item_id).strip()},
                           session=self.session, base_url=BASE_URL)

    def update_call_summary(self, item_id: str, content: str, *,
                            template_key: Optional[str] = None) -> Any:
        """Replace the markdown of a call's AI summary."""
        return self._request(
            "PATCH", f"/v2/api/conversations/items/{_segment(item_id, 'item_id')}/summary",
            body={"content": content, "template_key": template_key})

    def update_conversation(self, contact_number: str, action: str, *,
                            allo_number: Optional[str] = None) -> Any:
        """Mark a conversation read or unread, archive or unarchive it."""
        return self._request(
            "PUT", f"/v2/api/conversations/{_segment(contact_number, 'contact_number')}/action",
            body={"action": _choice("action", action, CONVERSATION_ACTIONS),
                  "allo_number": allo_number})
