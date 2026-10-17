"""Constants of the Resend connector — transport and pagination.

Single home: `client.py` re-exports them through its `__all__`, and the
`_api/` mixins import them from here. The backend pins oto-core by tag and
only imports `oto.tools.resend.client`.
"""
from __future__ import annotations

BASE_URL = "https://api.resend.com"

# (connect, read) — never an unbounded wait.
HTTP_TIMEOUT = (10, 60)

# Rate limit: 10 requests per second per TEAM, shared by every key of the
# account (sending included), answered by a 429 with `retry-after`. One client
# paces its own calls at most this often, so a batch of upserts (two to four
# calls each) stays under the limit by construction.
MIN_INTERVAL_S = 0.12

# A READ is retried on 429 (when `retry-after` is short) and on 5xx. Writes are
# never replayed: the contact routes take no idempotency key. An upsert is
# idempotent by construction, so the caller can simply run it again.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 3
RATE_LIMIT_MAX_WAIT = 5.0

# Cursor pagination: `limit` (1–100), `after` / `before` (an object id, never
# both). Out: `{object: "list", has_more, data}`.
MAX_PAGE_SIZE = 100

# Pages read when a method walks a whole list for its own use (a contact's
# segments, inside `upsert_contact`). A contact in more than this many
# segments is refused rather than half-read.
MAX_WALK_PAGES = 10
