"""Allo constants: host, timeout, page size and the closed lists the client checks before sending.

Re-exported by `client.py`; the vocabularies are those of Allo's OpenAPI."""
from __future__ import annotations

_HTTP_TIMEOUT = (10, 60)  # (connect, read) — never an unbounded wait
BASE_URL = "https://api.withallo.com"

SORTS = ("DATE_DESC", "DATE_ASC", "NAME_ASC", "NAME_DESC", "CREATED_DESC", "CREATED_ASC")
CONVERSATION_ACTIONS = ("READ", "UNREAD", "ARCHIVE", "UNARCHIVE")
MAX_SIZE = 100
# The addresses of a call's recording: `recording_url`, `recording_download_url` (signed, 48 hours, no login) and its
# expiry. They never leave the client; the audio comes as a file (`get_call_recording`).
RECORDING_ADDRESS_FIELDS = ("recording_url", "recording_download_url", "recording_download_expires_at")

ATTRIBUTE_TYPES = ("TEXT", "NUMBER", "DATE", "BOOLEAN", "DROPDOWN")
THREAD_ENTITY_TYPES = ("CALL", "TEXT_MESSAGE", "CONVERSATION_NOTE")
WEBHOOK_TOPICS = ("call.received", "call.triggered", "call.answered", "call.completed", "tag.added", "tag.removed",
                  "sms.received", "sms.sent", "contact.created", "contact.updated", "summary.updated")
VOICEMAIL_HANDLING = ("SKIP", "NO_SKIP")
DO_NOT_DISTURB = ("ENABLED", "DISABLED")
