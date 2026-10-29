"""Qonto Business API client — French business banking (read-only).

Business API v2 (`https://thirdparty.qonto.com/v2`), authenticated by an
organization API key: **`Authorization: <login>:<secret key>`**, the two
values joined by a colon and sent as is (no `Basic`, no base64). Both are on
Qonto → Settings → Integrations and partnerships → API key; the login looks
like `acme-1234`, it is not an email. One key = one organization. One method =
one endpoint; responses are returned as-is, the client invents no semantics.

Scope: what an API key can read — the organization and its bank accounts
(balances), transactions with their VAT, labels and attachments, statements,
supplier invoices, client invoices, credit notes, quotes and clients, SEPA
transfers and beneficiaries, spend requests, memberships and labels.

What the caller needs to know, and cannot guess:

- **Some routes are OAuth only.** Cards, cash-flow categories and every
  payment or write route answer `401 "OAuth2 authentication is required
  here"` to an API key; they are not in this client. A 401 on a route here
  means the key itself was refused.
- **Transactions are per bank account**: `bank_account_id` or `iban` is
  required (422 otherwise); `get_organization` lists the accounts.
- **Lists are paged by number**: `page` from 1, `per_page` (100 at most on most
  routes, 500 on client invoices and quotes). Every list answers
  `{<resource>: [...], meta: {current_page, next_page, total_pages,
  total_count, per_page}}`; `meta.next_page` is null on the last page.
- **Array filters go in the query as `name[]=a&name[]=b`** (Rails style).
- **Dates** are ISO 8601 (`2026-10-01` or `2026-10-01T00:00:00Z`); a
  statement period is `MM-YYYY`.
- **An attachment's `url` is signed and expires after 30 minutes.**
- **Rate limit**: 1,000 requests per 10 seconds per IP; more than 200 answers
  401 in an hour throttles the IP, so a refused key is never retried.

Requires: requests
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

import requests

from ..common import raise_for_upstream
from ..common.credentials import require
from ..http.client import refuse_redirect

# (connect, read) — never an unbounded wait.
HTTP_TIMEOUT = (10, 60)

BASE_URL = "https://thirdparty.qonto.com/v2"

TRANSACTION_STATUSES = ("pending", "declined", "completed", "reversed")
TRANSACTION_INCLUDES = ("vat_details", "labels", "attachments")
SIDES = ("credit", "debit")
SUPPLIER_INVOICE_STATUSES = ("to_review", "to_approve", "awaiting_payment", "pending",
                             "scheduled", "paid", "archived", "rejected", "discarded")
CLIENT_INVOICE_STATUSES = ("draft", "unpaid", "paid", "canceled")
QUOTE_STATUSES = ("pending_approval", "approved", "canceled")
TRANSFER_STATUSES = ("pending", "processing", "canceled", "declined", "settled")
BENEFICIARY_STATUSES = ("pending", "validated", "declined")
REQUEST_STATUSES = ("pending", "approved", "canceled", "declined")
REQUEST_TYPES = ("transfer", "multi_transfer", "flash_card", "virtual_card")

# Every route here is a GET: a 429/5xx is safe to replay. Never a 401 (see above).
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 3

_KEY = re.compile(r"^[^:\s]+:\S+$")
# Ids land in the path: letters, digits, `-` and `_` only, so that no value can
# reshape the URL.
_PATH_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_WHEN = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])"
                   r"(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?)?$")
_PERIOD = re.compile(r"^(?:0[1-9]|1[0-2])-\d{4}$")
_SORT = re.compile(r"^[a-z_]+:(?:asc|desc)$")
_TRANSACTION_SORT = re.compile(r"^(created_at|updated_at|settled_at|emitted_at)?(:(asc|desc)?)?$")


class QontoClient:
    """Qonto Business API v2, read-only, one organization per key."""

    BASE_URL = BASE_URL

    def __init__(self, api_key: Optional[str] = None):
        """
        Args:
            api_key: `<login>:<secret key>`, joined by a colon, from Qonto →
                Settings → Integrations and partnerships → API key.
        """
        key = require(api_key, "QONTO_API_KEY").strip()
        if not _KEY.match(key):
            raise ValueError("The Qonto API key must be `login:secret-key` — the login "
                             "(e.g. acme-1234) and the secret key joined by a colon.")
        self.api_key = key
        self.session = requests.Session()
        self.session.headers.update({"Authorization": key, "Accept": "application/json"})

    # --- validation ---------------------------------------------------------

    @staticmethod
    def _path_id(name: str, value: Any) -> str:
        text = value.strip() if isinstance(value, str) else ""
        if not _PATH_ID.match(text):
            raise ValueError(f"`{name}` must be an id of letters, digits, '-' or '_'; got {value!r}.")
        return text

    @staticmethod
    def _when(name: str, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str) or not _WHEN.match(value.strip()):
            raise ValueError(f"`{name}` must be an ISO 8601 date or date-time "
                             f"(2026-10-01 or 2026-10-01T00:00:00Z); got {value!r}.")
        return value.strip()

    @staticmethod
    def _period(name: str, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str) or not _PERIOD.match(value.strip()):
            raise ValueError(f"`{name}` must be a month MM-YYYY (e.g. 10-2026); got {value!r}.")
        return value.strip()

    @staticmethod
    def _positive(name: str, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"`{name}` must be an integer >= 1; got {value!r}.")
        return value

    @staticmethod
    def _choice(name: str, value: Optional[str], allowed: tuple) -> Optional[str]:
        if value is None:
            return None
        if value not in allowed:
            raise ValueError(f"`{name}` invalid: {value!r}. Accepted values: "
                             + ", ".join(allowed) + ".")
        return value

    @classmethod
    def _choices(cls, name: str, values: Optional[List[str]],
                 allowed: Optional[tuple] = None) -> Optional[List[str]]:
        if values is None:
            return None
        if isinstance(values, str) or not isinstance(values, (list, tuple)) or not values:
            raise ValueError(f"`{name}` must be a non-empty list; got {values!r}.")
        for v in values:
            if not isinstance(v, str) or not v.strip():
                raise ValueError(f"`{name}` holds a value that is not a text: {v!r}.")
            if allowed is not None:
                cls._choice(name, v, allowed)
        return list(values)

    @staticmethod
    def _sort(name: str, value: Optional[str], pattern: re.Pattern = _SORT) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str) or not pattern.match(value):
            raise ValueError(f"`{name}` must be `property:asc` or `property:desc`; got {value!r}.")
        return value

    @staticmethod
    def _flag(value: Optional[bool]) -> Optional[str]:
        return None if value is None else ("true" if value else "false")

    # --- transport ----------------------------------------------------------

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """GET a route, with retry on 429/5xx. A list value goes as `name[]`,
        repeated. Redirects are refused: the key never follows a 3xx."""
        query = []
        for k, v in (params or {}).items():
            if v is None:
                continue
            if isinstance(v, list):
                query.extend((f"{k}[]", item) for item in v)
            else:
                query.append((k, v))
        last = None
        for attempt in range(MAX_ATTEMPTS):
            last = self.session.request(
                "GET", f"{self.BASE_URL}{path}", params=query or None,
                timeout=HTTP_TIMEOUT, allow_redirects=False)
            refuse_redirect(last)
            if last.status_code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS - 1:
                break
            time.sleep(float(2 ** attempt))
        raise_for_upstream(last, service="qonto")
        return last.json() if last.content else {}

    def _page(self, page: Optional[int], per_page: Optional[int]) -> Dict[str, Any]:
        return {"page": self._positive("page", page),
                "per_page": self._positive("per_page", per_page)}

    # --- probe --------------------------------------------------------------

    def probe(self) -> Any:
        """Check that the key authenticates, for the cost of one call."""
        return self.get_organization()

    # --- organization -------------------------------------------------------

    def get_organization(self, include_external_accounts: Optional[bool] = None) -> Any:
        """GET /organization — the organization and its bank accounts, each with
        `balance` and `authorized_balance` (euros) and `iban`."""
        return self._get("/organization", {
            "include_external_accounts": self._flag(include_external_accounts)})

    def list_memberships(self, page: Optional[int] = None,
                         per_page: Optional[int] = None) -> Any:
        """GET /memberships — the members of the organization, with role and team."""
        return self._get("/memberships", self._page(page, per_page))

    def list_labels(self, page: Optional[int] = None, per_page: Optional[int] = None) -> Any:
        """GET /labels — the labels that tag transactions."""
        return self._get("/labels", self._page(page, per_page))

    # --- transactions -------------------------------------------------------

    def list_transactions(self, bank_account_id: Optional[str] = None,
                          iban: Optional[str] = None, *,
                          status: Optional[List[str]] = None,
                          side: Optional[str] = None,
                          operation_type: Optional[List[str]] = None,
                          settled_at_from: Optional[str] = None,
                          settled_at_to: Optional[str] = None,
                          emitted_at_from: Optional[str] = None,
                          emitted_at_to: Optional[str] = None,
                          updated_at_from: Optional[str] = None,
                          updated_at_to: Optional[str] = None,
                          with_attachments: Optional[bool] = None,
                          includes: Optional[List[str]] = None,
                          sort_by: Optional[str] = None,
                          page: Optional[int] = None,
                          per_page: Optional[int] = None) -> Any:
        """GET /transactions — the transactions of ONE bank account
        (`bank_account_id` or `iban`, exactly one)."""
        if (bank_account_id is None) == (iban is None):
            raise ValueError("Give exactly one of `bank_account_id` or `iban`: "
                             "get_organization lists the bank accounts.")
        return self._get("/transactions", {
            "bank_account_id": (None if bank_account_id is None
                                else self._path_id("bank_account_id", bank_account_id)),
            "iban": iban.replace(" ", "") if isinstance(iban, str) else iban,
            "status": self._choices("status", status, TRANSACTION_STATUSES),
            "side": self._choice("side", side, SIDES),
            "operation_type": self._choices("operation_type", operation_type),
            "settled_at_from": self._when("settled_at_from", settled_at_from),
            "settled_at_to": self._when("settled_at_to", settled_at_to),
            "emitted_at_from": self._when("emitted_at_from", emitted_at_from),
            "emitted_at_to": self._when("emitted_at_to", emitted_at_to),
            "updated_at_from": self._when("updated_at_from", updated_at_from),
            "updated_at_to": self._when("updated_at_to", updated_at_to),
            "with_attachments": self._flag(with_attachments),
            "includes": self._choices("includes", includes, TRANSACTION_INCLUDES),
            "sort_by": self._sort("sort_by", sort_by, _TRANSACTION_SORT),
            **self._page(page, per_page),
        })

    def get_transaction(self, transaction_id: str,
                        includes: Optional[List[str]] = None) -> Any:
        """GET /transactions/{transaction_id} — one transaction by its `id` (the
        UUID, not the `transaction_id` slug)."""
        tid = self._path_id("transaction_id", transaction_id)
        return self._get(f"/transactions/{tid}", {
            "includes": self._choices("includes", includes, TRANSACTION_INCLUDES)})

    def list_transaction_attachments(self, transaction_id: str,
                                     page: Optional[int] = None,
                                     per_page: Optional[int] = None) -> Any:
        """GET /transactions/{transaction_id}/attachments — its receipts, each
        with a signed `url` valid 30 minutes."""
        tid = self._path_id("transaction_id", transaction_id)
        return self._get(f"/transactions/{tid}/attachments", self._page(page, per_page))

    def get_attachment(self, attachment_id: str) -> Any:
        """GET /attachments/{attachment_id} — one file: name, size, type and a
        signed `url` valid 30 minutes."""
        aid = self._path_id("attachment_id", attachment_id)
        return self._get(f"/attachments/{aid}")

    # --- statements ---------------------------------------------------------

    def list_statements(self, bank_account_ids: Optional[List[str]] = None,
                        ibans: Optional[List[str]] = None, *,
                        period_from: Optional[str] = None,
                        period_to: Optional[str] = None,
                        sort_by: Optional[str] = None,
                        page: Optional[int] = None,
                        per_page: Optional[int] = None) -> Any:
        """GET /statements — monthly account statements; `bank_account_ids` and
        `ibans` are exclusive."""
        if bank_account_ids is not None and ibans is not None:
            raise ValueError("`bank_account_ids` and `ibans` cannot be used together.")
        return self._get("/statements", {
            "bank_account_ids": self._choices("bank_account_ids", bank_account_ids),
            "ibans": self._choices("ibans", ibans),
            "period_from": self._period("period_from", period_from),
            "period_to": self._period("period_to", period_to),
            "sort_by": self._choice("sort_by", sort_by, ("period:asc", "period:desc")),
            **self._page(page, per_page),
        })

    def get_statement(self, statement_id: str) -> Any:
        """GET /statements/{statement_id} — one statement, with its signed file `url`."""
        sid = self._path_id("statement_id", statement_id)
        return self._get(f"/statements/{sid}")

    # --- spend: supplier invoices, transfers, beneficiaries, requests --------

    def list_supplier_invoices(self, status: Optional[str] = None, *,
                               created_at_from: Optional[str] = None,
                               created_at_to: Optional[str] = None,
                               updated_at_from: Optional[str] = None,
                               updated_at_to: Optional[str] = None,
                               query: Optional[str] = None,
                               page: Optional[int] = None,
                               per_page: Optional[int] = None) -> Any:
        """GET /supplier_invoices — invoices and receipts received, with their
        amounts, supplier, dates and matched transactions."""
        return self._get("/supplier_invoices", {
            "filter[status]": self._choice("status", status, SUPPLIER_INVOICE_STATUSES),
            "filter[created_at_from]": self._when("created_at_from", created_at_from),
            "filter[created_at_to]": self._when("created_at_to", created_at_to),
            "filter[updated_at_from]": self._when("updated_at_from", updated_at_from),
            "filter[updated_at_to]": self._when("updated_at_to", updated_at_to),
            "query": query,
            **self._page(page, per_page),
        })

    def get_supplier_invoice(self, supplier_invoice_id: str) -> Any:
        """GET /supplier_invoices/{supplier_invoice_id}."""
        iid = self._path_id("supplier_invoice_id", supplier_invoice_id)
        return self._get(f"/supplier_invoices/{iid}")

    def list_sepa_transfers(self, status: Optional[List[str]] = None, *,
                            beneficiary_ids: Optional[List[str]] = None,
                            updated_at_from: Optional[str] = None,
                            updated_at_to: Optional[str] = None,
                            scheduled_date_from: Optional[str] = None,
                            scheduled_date_to: Optional[str] = None,
                            sort_by: Optional[str] = None,
                            page: Optional[int] = None,
                            per_page: Optional[int] = None) -> Any:
        """GET /sepa/transfers — outgoing SEPA transfers."""
        return self._get("/sepa/transfers", {
            "status": self._choices("status", status, TRANSFER_STATUSES),
            "beneficiary_ids": self._choices("beneficiary_ids", beneficiary_ids),
            "updated_at_from": self._when("updated_at_from", updated_at_from),
            "updated_at_to": self._when("updated_at_to", updated_at_to),
            "scheduled_date_from": self._when("scheduled_date_from", scheduled_date_from),
            "scheduled_date_to": self._when("scheduled_date_to", scheduled_date_to),
            "sort_by": self._choice("sort_by", sort_by, (
                "updated_at:asc", "updated_at:desc",
                "scheduled_date:asc", "scheduled_date:desc")),
            **self._page(page, per_page),
        })

    def list_sepa_beneficiaries(self, status: Optional[List[str]] = None, *,
                                iban: Optional[List[str]] = None,
                                trusted: Optional[bool] = None,
                                sort_by: Optional[str] = None,
                                page: Optional[int] = None,
                                per_page: Optional[int] = None) -> Any:
        """GET /sepa/beneficiaries — saved SEPA payees (25 per page by default)."""
        return self._get("/sepa/beneficiaries", {
            "status": self._choices("status", status, BENEFICIARY_STATUSES),
            "iban": self._choices("iban", iban),
            "trusted": self._flag(trusted),
            "sort_by": self._choice("sort_by", sort_by,
                                    ("updated_at:asc", "updated_at:desc")),
            **self._page(page, per_page),
        })

    def list_requests(self, status: Optional[List[str]] = None, *,
                      request_type: Optional[List[str]] = None,
                      created_at_from: Optional[str] = None,
                      processed_at_from: Optional[str] = None,
                      sort_by: Optional[str] = None,
                      page: Optional[int] = None,
                      per_page: Optional[int] = None) -> Any:
        """GET /requests — spend requests awaiting or past approval (transfers,
        flash and virtual cards)."""
        return self._get("/requests", {
            "status": self._choices("status", status, REQUEST_STATUSES),
            "request_type": self._choices("request_type", request_type, REQUEST_TYPES),
            "created_at_from": self._when("created_at_from", created_at_from),
            "processed_at_from": self._when("processed_at_from", processed_at_from),
            "sort_by": self._sort("sort_by", sort_by),
            **self._page(page, per_page),
        })

    # --- invoicing: client invoices, credit notes, quotes, clients ----------

    def list_client_invoices(self, status: Optional[str] = None, *,
                             created_at_from: Optional[str] = None,
                             created_at_to: Optional[str] = None,
                             updated_at_from: Optional[str] = None,
                             updated_at_to: Optional[str] = None,
                             due_date_from: Optional[str] = None,
                             due_date_to: Optional[str] = None,
                             exclude_imported: Optional[bool] = None,
                             sort_by: Optional[str] = None,
                             page: Optional[int] = None,
                             per_page: Optional[int] = None) -> Any:
        """GET /client_invoices — invoices issued from Qonto (imported ones
        excluded unless `exclude_imported` is false)."""
        return self._get("/client_invoices", {
            "filter[status]": self._choice("status", status, CLIENT_INVOICE_STATUSES),
            "filter[created_at_from]": self._when("created_at_from", created_at_from),
            "filter[created_at_to]": self._when("created_at_to", created_at_to),
            "filter[updated_at_from]": self._when("updated_at_from", updated_at_from),
            "filter[updated_at_to]": self._when("updated_at_to", updated_at_to),
            "filter[due_date_from]": self._when("due_date_from", due_date_from),
            "filter[due_date_to]": self._when("due_date_to", due_date_to),
            "exclude_imported": self._flag(exclude_imported),
            "sort_by": self._choice("sort_by", sort_by, ("created_at:asc", "created_at:desc")),
            **self._page(page, per_page),
        })

    def get_client_invoice(self, client_invoice_id: str) -> Any:
        """GET /client_invoices/{client_invoice_id}."""
        iid = self._path_id("client_invoice_id", client_invoice_id)
        return self._get(f"/client_invoices/{iid}")

    def list_credit_notes(self, *, created_at_from: Optional[str] = None,
                          created_at_to: Optional[str] = None,
                          sort_by: Optional[str] = None,
                          page: Optional[int] = None,
                          per_page: Optional[int] = None) -> Any:
        """GET /credit_notes — credit notes issued against client invoices."""
        return self._get("/credit_notes", {
            "filter[created_at_from]": self._when("created_at_from", created_at_from),
            "filter[created_at_to]": self._when("created_at_to", created_at_to),
            "sort_by": self._choice("sort_by", sort_by, ("created_at:asc", "created_at:desc")),
            **self._page(page, per_page),
        })

    def list_quotes(self, status: Optional[str] = None, *,
                    created_at_from: Optional[str] = None,
                    created_at_to: Optional[str] = None,
                    sort_by: Optional[str] = None,
                    page: Optional[int] = None,
                    per_page: Optional[int] = None) -> Any:
        """GET /quotes — quotes issued from Qonto."""
        return self._get("/quotes", {
            "filter[status]": self._choice("status", status, QUOTE_STATUSES),
            "filter[created_at_from]": self._when("created_at_from", created_at_from),
            "filter[created_at_to]": self._when("created_at_to", created_at_to),
            "sort_by": self._choice("sort_by", sort_by, ("created_at:asc", "created_at:desc")),
            **self._page(page, per_page),
        })

    def list_clients(self, *, name: Optional[str] = None,
                     email: Optional[str] = None,
                     vat_number: Optional[str] = None,
                     tax_identification_number: Optional[str] = None,
                     updated_at_from: Optional[str] = None,
                     updated_at_to: Optional[str] = None,
                     sort_by: Optional[str] = None,
                     page: Optional[int] = None,
                     per_page: Optional[int] = None) -> Any:
        """GET /clients — the customers invoiced from Qonto. `name` matches
        partially (2 characters at least); the other filters match exactly."""
        if name is not None and (not isinstance(name, str) or len(name.strip()) < 2):
            raise ValueError("`name` must hold at least 2 characters.")
        return self._get("/clients", {
            "filter[name]": name,
            "filter[email]": email,
            "filter[vat_number]": vat_number,
            "filter[tax_identification_number]": tax_identification_number,
            "filter[updated_at_from]": self._when("updated_at_from", updated_at_from),
            "filter[updated_at_to]": self._when("updated_at_to", updated_at_to),
            "sort_by": self._choice("sort_by", sort_by, (
                "created_at:asc", "created_at:desc", "updated_at:asc",
                "updated_at:desc", "name:asc", "name:desc")),
            **self._page(page, per_page),
        })

    def get_client(self, client_id: str) -> Any:
        """GET /clients/{client_id}."""
        cid = self._path_id("client_id", client_id)
        return self._get(f"/clients/{cid}")
