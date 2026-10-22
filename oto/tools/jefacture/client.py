"""jefacture.com client — French e-invoicing platform, read-only.

jefacture.com runs on the Banqup platform, French region: one API,
`https://api.btx.fr.banqup.com`, authenticated by `Authorization: Bearer
<access token>` (see `auth`). Every route but the caller's identity and the
list of spaces is scoped to one **space** (`spaceId` in the path): the
workspace of one company. A person or an application may reach several spaces
(an accounting firm reaches its clients'), hence `space_id` on every read,
taken from `list_spaces`. One method = one endpoint; responses are returned
as-is, the client invents no semantics.

Scope: issued and received invoices and their statuses, what remains due and
how payments were matched to them, customers and suppliers, and the payment
accounts with their movements. Not here: bookkeeping entries, the balance
sheet, and sales to private customers that never become an invoice.

What the caller needs to know, and cannot guess:

- **Lists are paged by number from 0**: `page` (0 = first) and `page_size`
  (at most 200 for documents, connections and reconciliations, 100 for
  movements). Each list answers its items with `totalElements`,
  `currentPage` and `pageSize`.
- **Issued or received is a folder**: `SALES` holds issued invoices,
  `PURCHASES` received ones; `category` tells an invoice from a credit note.
- **A document carries three statuses** in `status`: `document` (validation),
  `pay` (UNPAID, PARTIALLY_PAID, FULLY_PAID…) and `delivery`. `status_query`
  filters on them with the platform's query language, e.g.
  `pay=UNPAID OR pay=PARTIALLY_PAID`.
- **What remains due** is `openBalance`; the matching of payments to a
  document is in its `balanceOffsets` and in the reconciliation aggregations.

Requires: requests
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, Optional

import requests

from ..common import raise_for_upstream
from ..common.credentials import require
from ..http.client import refuse_redirect

# (connect, read) — never an unbounded wait.
HTTP_TIMEOUT = (10, 60)

BASE_URL = "https://api.btx.fr.banqup.com"

FOLDERS = ("SALES", "PURCHASES", "DRAFTS", "INBOX")
CATEGORIES = ("INVOICE", "CREDIT_NOTE", "SELF_BILLED_INVOICE", "SELF_BILLED_CREDIT_NOTE",
              "PROFORMA_INVOICE", "INVOICE_REMINDER", "RECEIPT", "QUOTE")
DOCUMENT_SORTS = ("issueDate.desc", "issueDate.asc", "dueDate.asc", "dueDate.desc",
                  "updatedAt.desc", "updatedAt.asc", "openBalance.desc",
                  "payableAmount.desc", "documentNumber.asc")
RELATION_TYPES = ("CUSTOMER", "SUPPLIER")
MATCHING_STATUSES = ("PROPOSED", "UNMATCHED", "MATCHED")
BOOKING_TYPES = ("BOOKED", "PLANNED", "RESERVED")

# The linked resources a document read brings along.
_LIST_INCLUDE = "connections,balanceOffsets"
_DETAIL_INCLUDE = "lines,connections,balanceOffsets"

# Every route here is a GET: a 429/5xx is safe to replay.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 3

# Ids land in the path: UUIDs only, so that no value can reshape the URL.
_UUID = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_DAY = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$")
_INSTANT = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])(?:T[0-9:.]+(?:Z|[+-]\d{2}:\d{2})?)?$")


class JefactureClient:
    """jefacture.com (Banqup, region France), read-only, one access token per client."""

    BASE_URL = BASE_URL

    def __init__(self, access_token: Optional[str] = None):
        """
        Args:
            access_token: a Banqup access token (authorization code or client
                credentials, see `auth`).
        """
        self.access_token = require(access_token, "JEFACTURE_ACCESS_TOKEN")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        })

    # --- validation ---------------------------------------------------------

    @staticmethod
    def _uuid(name: str, value: Any) -> str:
        text = value.strip() if isinstance(value, str) else ""
        if not _UUID.match(text):
            raise ValueError(f"`{name}` must be a UUID; got {value!r}.")
        return text

    @staticmethod
    def _day(name: str, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str) or not _DAY.match(value.strip()):
            raise ValueError(f"`{name}` must be a date YYYY-MM-DD; got {value!r}.")
        return value.strip()

    @staticmethod
    def _instant(name: str, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str) or not _INSTANT.match(value.strip()):
            raise ValueError(
                f"`{name}` must be a date YYYY-MM-DD or an ISO 8601 date-time; got {value!r}.")
        return value.strip()

    @staticmethod
    def _bounded(name: str, value: Optional[int], low: int, high: Optional[int] = None) -> Optional[int]:
        if value is None:
            return None
        if (isinstance(value, bool) or not isinstance(value, int) or value < low
                or (high is not None and value > high)):
            bounds = f">= {low}" if high is None else f"between {low} and {high}"
            raise ValueError(f"`{name}` must be an integer {bounds}; got {value!r}.")
        return value

    @staticmethod
    def _choice(name: str, value: Optional[str], allowed: tuple) -> Optional[str]:
        if value is None:
            return None
        if value not in allowed:
            raise ValueError(f"`{name}` invalid: {value!r}. Accepted values: "
                             + ", ".join(allowed) + ".")
        return value

    @staticmethod
    def _text(name: str, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"`{name}` must be a non-empty string; got {value!r}.")
        return value.strip()

    # --- transport ----------------------------------------------------------

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """GET a route, with retry on 429/5xx. Redirects are refused: the token
        must never follow a 3xx to another host."""
        query = {k: v for k, v in (params or {}).items() if v is not None}
        url = f"{self.BASE_URL}{path}"
        last = None
        for attempt in range(MAX_ATTEMPTS):
            last = self.session.request(
                "GET", url, params=query or None, timeout=HTTP_TIMEOUT,
                allow_redirects=False)
            refuse_redirect(last)
            if last.status_code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS - 1:
                break
            time.sleep(float(2 ** attempt))
        raise_for_upstream(last, service="jefacture")
        return last.json() if last.content else {}

    def _space(self, space_id: Any) -> str:
        return self._uuid("space_id", space_id)

    # --- identity and spaces ------------------------------------------------

    def get_me(self) -> Any:
        """GET /workspace/user/business/v1/users/me — the person the token acts as."""
        return self._get("/workspace/user/business/v1/users/me")

    def list_spaces(self, page: Optional[int] = None,
                    page_size: Optional[int] = None) -> Any:
        """GET /workspace/space/v2/spaces — the spaces the token reaches."""
        return self._get("/workspace/space/v2/spaces", {
            "sortBy": "name.asc",
            "page": self._bounded("page", page, 0),
            "pageSize": self._bounded("page_size", page_size, 1, 200),
        })

    # --- documents ----------------------------------------------------------

    def list_documents(self, space_id: str, *,
                       folder: Optional[str] = None,
                       category: Optional[str] = None,
                       status_query: Optional[str] = None,
                       issued_from: Optional[str] = None,
                       issued_to: Optional[str] = None,
                       due_from: Optional[str] = None,
                       due_to: Optional[str] = None,
                       updated_since: Optional[str] = None,
                       document_number: Optional[str] = None,
                       counterpart: Optional[str] = None,
                       sort_by: Optional[str] = None,
                       page: Optional[int] = None,
                       page_size: Optional[int] = None) -> Any:
        """GET /documents/core/transaction/v2/spaces/{spaceId}/documents —
        invoices and credit notes, with their counterparts and matched payments."""
        sid = self._space(space_id)
        return self._get(f"/documents/core/transaction/v2/spaces/{sid}/documents", {
            "include": _LIST_INCLUDE,
            "folder": self._choice("folder", folder, FOLDERS),
            "category": self._choice("category", category, CATEGORIES),
            "status[ql]": self._text("status_query", status_query),
            "issueDate[gte]": self._day("issued_from", issued_from),
            "issueDate[lte]": self._day("issued_to", issued_to),
            "dueDate[gte]": self._day("due_from", due_from),
            "dueDate[lte]": self._day("due_to", due_to),
            "updatedAt[gte]": self._instant("updated_since", updated_since),
            "documentNumber[icont]": self._text("document_number", document_number),
            "connectionName[icont]": self._text("counterpart", counterpart),
            "sortBy": self._choice("sort_by", sort_by, DOCUMENT_SORTS),
            "page": self._bounded("page", page, 0),
            "pageSize": self._bounded("page_size", page_size, 1, 200),
        })

    def get_document(self, space_id: str, document_id: str) -> Any:
        """GET /documents/core/transaction/v2/spaces/{spaceId}/documents/{documentId}
        — one document with its lines, counterparts and matched payments."""
        sid = self._space(space_id)
        did = self._uuid("document_id", document_id)
        return self._get(f"/documents/core/transaction/v2/spaces/{sid}/documents/{did}",
                         {"include": _DETAIL_INCLUDE})

    # --- payments and matching ----------------------------------------------

    def list_balance_offsets(self, space_id: str, document_id: str) -> Any:
        """GET /documents/payment/pay/v1/spaces/{spaceId}/documents/{documentId}/balanceOffsets
        — the payments imputed to one document."""
        sid = self._space(space_id)
        did = self._uuid("document_id", document_id)
        return self._get(
            f"/documents/payment/pay/v1/spaces/{sid}/documents/{did}/balanceOffsets")

    def get_payment(self, space_id: str, payment_id: str) -> Any:
        """GET /documents/payment/business/v2/spaces/{spaceId}/payments/{paymentId}."""
        sid = self._space(space_id)
        pid = self._uuid("payment_id", payment_id)
        return self._get(f"/documents/payment/business/v2/spaces/{sid}/payments/{pid}")

    def list_reconciliations(self, space_id: str, *,
                             matching_status: Optional[str] = None,
                             page: Optional[int] = None,
                             page_size: Optional[int] = None) -> Any:
        """GET /payments/reconciliation/documents/v2/spaces/{spaceId}/documents/aggregations
        — documents with the payments matched or proposed for them."""
        sid = self._space(space_id)
        return self._get(
            f"/payments/reconciliation/documents/v2/spaces/{sid}/documents/aggregations", {
                "matchingStatus": self._choice("matching_status", matching_status,
                                               MATCHING_STATUSES),
                "page": self._bounded("page", page, 0, 10000),
                "size": self._bounded("page_size", page_size, 1, 200),
            })

    # --- customers and suppliers --------------------------------------------

    def list_connections(self, space_id: str, *,
                         relation_type: Optional[str] = None,
                         search: Optional[str] = None,
                         identifier: Optional[str] = None,
                         page: Optional[int] = None,
                         page_size: Optional[int] = None) -> Any:
        """GET /network/core/transaction/v3/spaces/{spaceId}/connections —
        customers and suppliers of the space."""
        sid = self._space(space_id)
        return self._get(f"/network/core/transaction/v3/spaces/{sid}/connections", {
            "relationTypes": self._choice("relation_type", relation_type, RELATION_TYPES),
            "search[cont]": self._text("search", search),
            "identifierKeyValue": self._text("identifier", identifier),
            "sortBy": "name.asc",
            "page": self._bounded("page", page, 0),
            "pageSize": self._bounded("page_size", page_size, 1, 200),
        })

    def get_connection(self, space_id: str, connection_id: str) -> Any:
        """GET /network/core/transaction/v3/spaces/{spaceId}/connections/{connectionId}."""
        sid = self._space(space_id)
        cid = self._uuid("connection_id", connection_id)
        return self._get(f"/network/core/transaction/v3/spaces/{sid}/connections/{cid}")

    # --- payment accounts ---------------------------------------------------

    def list_payment_accounts(self, space_id: str) -> Any:
        """GET /payments/paymentaccounts/v2/spaces/{spaceId}/paymentAccounts —
        active or requested accounts, with their last known balances."""
        sid = self._space(space_id)
        return self._get(f"/payments/paymentaccounts/v2/spaces/{sid}/paymentAccounts")

    def list_account_movements(self, space_id: str, payment_account_id: str, *,
                               booking_type: Optional[str] = None,
                               date_from: Optional[str] = None,
                               date_to: Optional[str] = None,
                               page: Optional[int] = None,
                               page_size: Optional[int] = None) -> Any:
        """GET /payments/paymentaccounts/v1/spaces/{spaceId}/paymentAccounts/{id}/movements."""
        sid = self._space(space_id)
        aid = self._uuid("payment_account_id", payment_account_id)
        start = self._day("date_from", date_from)
        end = self._day("date_to", date_to)
        if start and end and end < start:
            raise ValueError("`date_to` must not be before `date_from`.")
        return self._get(
            f"/payments/paymentaccounts/v1/spaces/{sid}/paymentAccounts/{aid}/movements", {
                "bookingType": self._choice("booking_type", booking_type, BOOKING_TYPES),
                "dateFrom": start,
                "dateTo": end,
                "page": self._bounded("page", page, 0),
                "size": self._bounded("page_size", page_size, 1, 100),
            })
