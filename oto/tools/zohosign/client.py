"""Zoho Sign API client — https://www.zoho.com/sign/api/ (v1).

Signature requests ("documents" in Zoho's reference) and templates, on behalf of
one Zoho account: list and read requests with their recipients, download the
signed PDF or the completion certificate, list and read templates, send a
request from a template, remind its recipients, recall it.

OAuth scopes (Zoho Sign reference, "OAuth 2.0"): `ZohoSign.documents.CREATE /
READ / UPDATE`, `ZohoSign.templates.CREATE / READ / UPDATE`,
`ZohoSign.account.CREATE / READ / UPDATE`. Zoho does not map each endpoint to a
scope: `_SCOPE_BY_CALL` is this client's reading of the three groups, used to
name the scope a refused call expects.

Credentials, always provided by the consumer:
  client_id, client_secret, refresh_token
  api_domain    `https://sign.zoho.<domain>` of the account's data center
  accounts_url  `https://accounts.zoho.<domain>` of the same data center

Both addresses are parameters without default: the OAuth app, the refresh token
and the account are bound to one data center, and a call to another one fails.

The token refresh is the Zoho family's (`..zoho.auth`): process-wide cache keyed
by credential, secrets in the form body, never in a URL.

Request lists and template creation take their arguments as ONE JSON document in
a `data` field (query string for a list, form body for a creation), as Zoho's
reference shows.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Optional

import requests

from ..common.credentials import require
from ..common.errors import UpstreamHTTPError, raise_for_upstream, retry_after_seconds
from ..http.client import refuse_redirect
from ..zoho.auth import cred_key, get_access_token, invalidate

SERVICE = "zohosign"
_HTTP_TIMEOUT = (10, 60)  # (connect, read) — never wait indefinitely
_MAX_RETRY_WAIT = 30.0    # seconds: a longer Retry-After is the caller's to honour

#: The documented sort columns of a request list (Zoho reference, "Get documents list").
REQUEST_SORT_COLUMNS = ("request_name", "folder_name", "owner_full_name",
                        "recipient_email", "form_name", "created_time")
#: The documented filters (`search_columns`) of a request list.
REQUEST_SEARCH_COLUMNS = ("request_name", "folder_name", "owner_full_name",
                          "recipient_email", "recipient_name", "form_name",
                          "template_name")
#: The page sizes Zoho documents for a template list.
TEMPLATE_ROW_COUNTS = (10, 25, 50, 100)
SORT_ORDERS = ("ASC", "DESC")

_DOCUMENTS_READ = "ZohoSign.documents.READ"
_DOCUMENTS_CREATE = "ZohoSign.documents.CREATE"
_DOCUMENTS_UPDATE = "ZohoSign.documents.UPDATE"
_TEMPLATES_READ = "ZohoSign.templates.READ"

# (method, path pattern) → the scope the call expects. Read in order, first match wins.
_SCOPE_BY_CALL = (
    ("POST", re.compile(r"^templates/[^/]+/createdocument$"), _DOCUMENTS_CREATE),
    ("GET", re.compile(r"^templates(/[^/]+)?$"), _TEMPLATES_READ),
    ("POST", re.compile(r"^requests/[^/]+/(remind|recall)$"), _DOCUMENTS_UPDATE),
    ("GET", re.compile(r"^requests(/[^/]+(/pdf|/completioncertificate)?)?$"), _DOCUMENTS_READ),
)


def required_scope(method: str, endpoint: str) -> Optional[str]:
    """The scope a call to `endpoint` expects, or None when the call is not mapped."""
    path = (endpoint or "").split("?", 1)[0].strip("/")
    for verb, pattern, scope in _SCOPE_BY_CALL:
        if verb == method.upper() and pattern.match(path):
            return scope
    return None


def _filename(resp: requests.Response, fallback: str) -> str:
    """The file name Zoho gives in `Content-Disposition`, else `fallback`."""
    disposition = resp.headers.get("Content-Disposition") or ""
    m = re.search(r"filename\*=UTF-8''([^;]+)", disposition, re.I) or re.search(
        r'filename="?([^";]+)"?', disposition, re.I)
    if m:
        from urllib.parse import unquote
        name = unquote(m.group(1)).strip()
        if name and "/" not in name and "\\" not in name:
            return name
    return fallback


class ZohoSignClient:
    API_VERSION = "v1"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
        *,
        api_domain: Optional[str] = None,
        accounts_url: Optional[str] = None,
        on_refresh: Optional[Callable[[dict], None]] = None,
    ):
        self.client_id = require(client_id, "ZOHO_SIGN_CLIENT_ID")
        self.client_secret = require(client_secret, "ZOHO_SIGN_CLIENT_SECRET")
        # OPTIONAL at construction: obtained by the consent, not pasted. Its absence is
        # reported at refresh time, with the step that is missing (`..zoho.auth`).
        self.refresh_token = refresh_token
        if not api_domain or not accounts_url:
            raise ValueError("Zoho Sign needs the API domain and the accounts URL of the "
                             "account's data center.")
        self.api_domain = api_domain.rstrip("/")
        self.accounts_url = accounts_url.rstrip("/")
        self._on_refresh = on_refresh
        self._cred_key = cred_key(self.accounts_url, self.client_id, self.refresh_token)

    # --- transport ----------------------------------------------------------------

    def _token(self) -> str:
        return get_access_token(self.accounts_url, self.client_id, self.client_secret,
                                self.refresh_token, key=self._cred_key,
                                on_refresh=self._on_refresh)

    def _send(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """One call, with ONE new token after a 401 and bounded waits on a 429. A 3xx is
        never followed: the token travels in a header `requests` would replay."""
        url = f"{self.api_domain}/api/{self.API_VERSION}/{endpoint}"
        headers = {"Authorization": f"Zoho-oauthtoken {self._token()}"}
        renewed = False
        for _ in range(3):
            resp = requests.request(method, url, headers=headers, timeout=_HTTP_TIMEOUT,
                                    allow_redirects=False, **kwargs)
            refuse_redirect(resp)
            if resp.status_code == 401 and not renewed:
                invalidate(self._cred_key)
                headers["Authorization"] = f"Zoho-oauthtoken {self._token()}"
                renewed = True
                continue
            if resp.status_code == 429:
                wait = retry_after_seconds(resp)
                if wait is not None and wait <= _MAX_RETRY_WAIT:
                    time.sleep(wait)
                    continue
            break
        if resp.status_code in (401, 403):
            scope = required_scope(method, endpoint)
            if scope:
                raise UpstreamHTTPError(
                    resp.status_code,
                    f"Zoho Sign refused this call; it expects the scope `{scope}` "
                    f"on the consent. Zoho said: {self._message(resp)}",
                    service=SERVICE)
        raise_for_upstream(resp, service=SERVICE)
        return resp

    @staticmethod
    def _message(resp: requests.Response) -> str:
        try:
            body = resp.json()
        except ValueError:
            return (resp.text or "")[:300]
        if isinstance(body, dict):
            return str(body.get("message") or body.get("code") or body)[:300]
        return str(body)[:300]

    def _json(self, method: str, endpoint: str, **kwargs) -> dict:
        resp = self._send(method, endpoint, **kwargs)
        try:
            body = resp.json() if resp.content else {}
        except ValueError:
            raise UpstreamHTTPError(resp.status_code, "Zoho Sign answered a non-JSON body.",
                                    service=SERVICE) from None
        # Zoho Sign says the outcome in `status`: a `failure` is a refusal, whatever the
        # HTTP status that carries it — never handed back as a success.
        if isinstance(body, dict) and body.get("status") == "failure":
            raise UpstreamHTTPError(resp.status_code if resp.status_code >= 400 else 400,
                                    body, service=SERVICE)
        return body

    def _file(self, endpoint: str, fallback_name: str, params: Optional[dict] = None) -> dict:
        resp = self._send("GET", endpoint, params=params)
        content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
        if content_type == "application/json":
            # A JSON body is never the file: a refusal, whatever its HTTP status.
            self._json_failure(resp)
        if not resp.content:
            raise UpstreamHTTPError(resp.status_code, "Zoho Sign sent an empty file.",
                                    service=SERVICE)
        if content_type == "application/zip" and fallback_name.endswith(".pdf"):
            fallback_name = fallback_name[:-4] + ".zip"
        return {"filename": _filename(resp, fallback_name),
                "content_type": content_type or "application/octet-stream",
                "content": resp.content}

    @staticmethod
    def _json_failure(resp: requests.Response) -> None:
        try:
            body = resp.json()
        except ValueError:
            return
        raise UpstreamHTTPError(resp.status_code if resp.status_code >= 400 else 400,
                                body, service=SERVICE)

    @staticmethod
    def _page_context(start_index: int, row_count: int, sort_column: str,
                      sort_order: str, search_columns: Optional[dict]) -> str:
        if sort_order not in SORT_ORDERS:
            raise ValueError(f"sort_order: one of {', '.join(SORT_ORDERS)}.")
        if start_index < 1 or row_count < 1:
            raise ValueError("start_index and row_count start at 1.")
        return json.dumps({"page_context": {
            "row_count": row_count, "start_index": start_index,
            "search_columns": search_columns or {}, "sort_column": sort_column,
            "sort_order": sort_order}})

    # --- signature requests -------------------------------------------------------

    def list_requests(self, start_index: int = 1, row_count: int = 25,
                      sort_column: str = "created_time", sort_order: str = "DESC",
                      search_columns: Optional[dict] = None) -> dict:
        """One page of signature requests (`GET /requests`). `search_columns` filters on
        the documented columns (`REQUEST_SEARCH_COLUMNS`), e.g. {"recipient_email": …}.
        The answer carries `requests` and `page_context` (`has_more_rows`, `total_count`)."""
        if sort_column not in REQUEST_SORT_COLUMNS:
            raise ValueError(f"sort_column: one of {', '.join(REQUEST_SORT_COLUMNS)}.")
        unknown = set(search_columns or {}) - set(REQUEST_SEARCH_COLUMNS)
        if unknown:
            raise ValueError(f"search_columns: unknown {sorted(unknown)}; one of "
                             f"{', '.join(REQUEST_SEARCH_COLUMNS)}.")
        return self._json("GET", "requests", params={"data": self._page_context(
            start_index, row_count, sort_column, sort_order, search_columns)})

    def get_request(self, request_id: str) -> dict:
        """One request with its recipients (`actions`) and their status (`GET /requests/{id}`)."""
        return self._json("GET", f"requests/{require(request_id, 'request_id')}")

    def download_pdf(self, request_id: str, with_coc: bool = False,
                     merge: bool = False) -> dict:
        """The request's documents (`GET /requests/{id}/pdf`): a PDF, or a ZIP when the
        request holds several documents and `merge` is false. `with_coc` adds the
        completion certificate. Returns {filename, content_type, content (bytes)}."""
        rid = require(request_id, "request_id")
        params = {k: "true" for k, v in (("with_coc", with_coc), ("merge", merge)) if v}
        return self._file(f"requests/{rid}/pdf", f"{rid}.pdf", params=params or None)

    def download_completion_certificate(self, request_id: str) -> dict:
        """The completion certificate (`GET /requests/{id}/completioncertificate`).
        Returns {filename, content_type, content (bytes)}."""
        rid = require(request_id, "request_id")
        return self._file(f"requests/{rid}/completioncertificate",
                          f"{rid}-completion-certificate.pdf")

    def remind(self, request_id: str) -> dict:
        """Remind the recipients who have not signed yet (`POST /requests/{id}/remind`)."""
        return self._json("POST", f"requests/{require(request_id, 'request_id')}/remind")

    def recall(self, request_id: str) -> dict:
        """Recall a request (`POST /requests/{id}/recall`): signing stops, recipients can
        no longer view or sign it."""
        return self._json("POST", f"requests/{require(request_id, 'request_id')}/recall")

    # --- templates ----------------------------------------------------------------

    def list_templates(self, start_index: int = 1, row_count: int = 25,
                       sort_column: str = "created_time", sort_order: str = "DESC",
                       search_columns: Optional[dict] = None) -> dict:
        """One page of templates (`GET /templates`); `row_count` among 10, 25, 50, 100."""
        if row_count not in TEMPLATE_ROW_COUNTS:
            raise ValueError(f"row_count: one of {', '.join(map(str, TEMPLATE_ROW_COUNTS))}.")
        return self._json("GET", "templates", params={"data": self._page_context(
            start_index, row_count, sort_column, sort_order, search_columns)})

    def get_template(self, template_id: str) -> dict:
        """One template, with its recipient roles (`actions`) and the fields a request
        made from it can prefill (`document_fields`) (`GET /templates/{id}`)."""
        return self._json("GET", f"templates/{require(template_id, 'template_id')}")

    def create_from_template(self, template_id: str, actions: list[dict], *,
                             request_name: Optional[str] = None,
                             field_data: Optional[dict] = None,
                             notes: Optional[str] = None,
                             quick_send: bool = True) -> dict:
        """A request from a template (`POST /templates/{id}/createdocument`). `actions`
        gives every recipient of the template (`action_id`, `recipient_name`,
        `recipient_email`…): their number cannot change. `field_data` prefills fields
        ({field_text_data, field_boolean_data, field_date_data}). `quick_send` true sends
        it for signature at once; false leaves it a draft."""
        tid = require(template_id, "template_id")
        if not actions:
            raise ValueError("actions: one entry per recipient of the template.")
        # `notes` is marked required by Zoho's reference: an empty message when none.
        templates: dict[str, Any] = {"actions": actions, "notes": notes or ""}
        for key, value in (("request_name", request_name), ("field_data", field_data)):
            if value is not None:
                templates[key] = value
        return self._json("POST", f"templates/{tid}/createdocument", data={
            "data": json.dumps({"templates": templates}),
            "is_quicksend": "true" if quick_send else "false"})
