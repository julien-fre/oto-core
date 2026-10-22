"""Zeendoc client — document management (GED), read-only.

A Zeendoc cabinet (`https://armoires.zeendoc.com/{url_client}`) stores documents
in binders (`coll_1`, `coll_2`…), each with its own indexing plan: fields
`custom_t<N>` (text), `custom_d<N>` (date), `custom_f<N>` (amount),
`custom_n<N>` (list or number), under labels the cabinet chose. An account is a
Zeendoc user — login and password, the same as the web application's — and
every read sees exactly what that user sees. One method = one call: REST API v4
for binders, searches and counts; the application pages for a document's text
and files, with the same session (`auth.py`).

What the caller needs to know, and cannot guess:

- **Discover before searching.** `get_context` lists the binders the user can
  open, their rights, and each binder's fields under `index` (`indexes` is
  empty): name, label, type, list choices. Criteria name fields, not labels.
- **Criteria** are `{field, operator, value}`, or `{field, operator: BETWEEN,
  start, end}`, combined by `match` (`all` = AND, `any` = OR) on one level; `|`
  inside a value means OR. `field` is a binder field, `Plain_Text` (the
  document's full text), or a property: `Res_Id`, `Creation_Date`, `N_Status`,
  `Filename`, `Format`. EQUALS matches the whole value, case-insensitive;
  CONTAINS matches whole words, `*` as wildcard. Dates as `YYYY-MM-DD` or
  `DD/MM/YYYY`. A list field is filtered by the id of its choice, not its label.
- **Pages of at most 50**: the API silently caps a larger page, so a larger
  `limit` is refused here. Page with `offset` up to `nbDocs`.
- **Statuses**: by default indexed (1) and to-index (2) documents; deleted ones
  (-1) only on `N_Status EQUALS -1`.
- **Index values are lists** (a field may hold several values). A search
  returns the stored value (`indexes`: list ids, ISO dates, numbers) and its
  display (`displayableIndexes`: list labels, French dates and amounts), both
  keyed by field name (`custom_t2`); `stats` gives min, max and sum of the
  amount fields over every matching document, not only the page.

Requires: requests
"""
from __future__ import annotations

import mimetypes
import re
import time
from typing import Any, Dict, List, Optional, Sequence

import requests

from ..common import UpstreamHTTPError, raise_for_upstream
from ..common.credentials import require
from ..http.client import refuse_redirect
from . import auth

# (connect, read) — never an unbounded wait.
HTTP_TIMEOUT = (10, 60)

BASE_URL = "https://armoires.zeendoc.com"

# Every call here reads. 500 is not replayed: Zeendoc also answers it to a
# request it cannot serve (an unknown field, a search it cannot run).
RETRY_STATUSES = frozenset({429, 502, 503, 504})
MAX_ATTEMPTS = 3

PAGE_MAX = 50
MAX_CRITERIA = 100
MAX_FILE_BYTES = 50 * 1024 * 1024

OPERATORS = ("EQUALS", "DIFFERS", "CONTAINS", "DO_NOT_CONTAINS", "NULL",
             "ABOVE", "LOWER", "BETWEEN")
MATCHES = {"all": "AND", "any": "OR"}
ORDERS = ("asc", "desc")
FILE_VERSIONS = {"pdf": "PDF", "original": "ORIGINAL"}

# Properties returned with every document when `columns` is not given.
PROPERTIES = ("Filename", "Creation_Date", "N_Status", "Page_Count", "Format")

# url_client and binder land in the path: no value may reshape the URL.
_SLUG = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_FIELD = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_CAMEL = re.compile(r"(?<!^)(?=[A-Z])")
_FILENAME = re.compile(r'filename="?([^";]+)"?')


class ZeendocClient:
    """Zeendoc REST API v4 and document pages, read-only, one cabinet per client."""

    BASE_URL = BASE_URL

    def __init__(self, login: Optional[str] = None, password: Optional[str] = None,
                 url_client: Optional[str] = None):
        """
        Args:
            login: the Zeendoc user's login (an email).
            password: that user's password.
            url_client: the cabinet's id, as in armoires.zeendoc.com/<url_client>/.
        """
        self.login = require(login, "ZEENDOC_LOGIN")
        self.password = require(password, "ZEENDOC_PASSWORD")
        self.url_client = self._slug(
            "url_client", require(url_client, "ZEENDOC_URL_CLIENT"))
        self.root = f"{self.BASE_URL}/{self.url_client}"
        self._key = auth.cred_key(self.root, self.login, self.password)
        self.session = requests.Session()
        # binder → its field names, read once per client.
        self._columns: Dict[str, List[str]] = {}

    # --- validation ---------------------------------------------------------

    @staticmethod
    def _slug(name: str, value: Any) -> str:
        text = value.strip() if isinstance(value, str) else ""
        if not _SLUG.match(text):
            raise ValueError(
                f"`{name}` must be an id of letters, digits, '-' or '_'; got {value!r}.")
        return text

    @staticmethod
    def _field(name: str, value: Any) -> str:
        if not isinstance(value, str) or not _FIELD.match(value.strip()):
            raise ValueError(
                f"`{name}` must be a field or property name such as custom_t1 or "
                f"Creation_Date; got {value!r}.")
        return value.strip()

    @staticmethod
    def _res_id(value: Any) -> int:
        if isinstance(value, str) and value.strip().isdigit():
            value = int(value.strip())
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"`res_id` must be a document id (integer >= 1); got {value!r}.")
        return value

    @staticmethod
    def _value(name: str, value: Any) -> str:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)) \
                or str(value).strip() == "":
            raise ValueError(f"`{name}` must be a non-empty text or number; got {value!r}.")
        return str(value).strip()

    @staticmethod
    def _choice(name: str, value: Any, allowed: Sequence[str]) -> str:
        if value not in allowed:
            raise ValueError(f"`{name}` invalid: {value!r}. Accepted values: "
                             + ", ".join(allowed) + ".")
        return value

    @classmethod
    def _query(cls, criteria: Optional[List[Dict[str, Any]]], match: str) -> Dict[str, Any]:
        """Criteria → the API's `indexList`. Each criterion gets its own id: two
        criteria under one id would silently overwrite each other."""
        if criteria is not None and not isinstance(criteria, list):
            raise ValueError("`criteria` must be a list of {field, operator, value}.")
        if len(criteria or []) > MAX_CRITERIA:
            raise ValueError(f"At most {MAX_CRITERIA} criteria.")
        body: Dict[str, Any] = {
            "queryOperator": MATCHES[cls._choice("match", match, tuple(MATCHES))]}
        items = []
        for n, c in enumerate(criteria or [], start=1):
            if not isinstance(c, dict):
                raise ValueError(f"Criterion {n} must be an object {{field, operator, value}}.")
            stray = set(c) - {"field", "operator", "value", "start", "end"}
            if stray:
                raise ValueError(f"Criterion {n} has unknown keys: {', '.join(sorted(stray))}.")
            item = {"id": n, "label": cls._field(f"criteria[{n}].field", c.get("field")),
                    "operator": cls._choice(f"criteria[{n}].operator",
                                            c.get("operator"), OPERATORS)}
            given = {k for k in ("value", "start", "end") if c.get(k) is not None}
            expected = ({"start", "end"} if item["operator"] == "BETWEEN"
                        else set() if item["operator"] == "NULL" else {"value"})
            if given != expected:
                raise ValueError(
                    f"Criterion {n} ({item['operator']}) takes "
                    + (", ".join(sorted(expected)) or "no value") + ".")
            if "value" in expected:
                item["value"] = cls._value(f"criteria[{n}].value", c["value"])
            if "start" in expected:
                item["startValue"] = cls._value(f"criteria[{n}].start", c["start"])
                item["endValue"] = cls._value(f"criteria[{n}].end", c["end"])
            items.append(item)
        if items:
            body["indexList"] = items
        return body

    # --- transport ----------------------------------------------------------

    def _attempt(self, method: str, path: str, cookie: str, *,
                 params: Optional[Dict[str, Any]], json: Any,
                 stream: bool) -> requests.Response:
        """One call with the session cookie, replayed on 429/502-504. Redirects are
        refused: the session must never follow a 3xx to another host."""
        last = None
        for attempt in range(MAX_ATTEMPTS):
            last = self.session.request(
                method, f"{self.root}{path}", params=params, json=json,
                headers={"Cookie": f"ZeenDoc={cookie}", "Accept": "application/json"},
                timeout=HTTP_TIMEOUT, allow_redirects=False, stream=stream)
            if not self._no_right(path, last):
                refuse_redirect(last)
            if last.status_code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS - 1:
                break
            last.close()
            time.sleep(float(2 ** attempt))
        return last

    @staticmethod
    def _session_over(path: str, resp: requests.Response) -> bool:
        """The API answers 401 to a closed session; a document page answers 200
        with a script that sends the browser to the login page."""
        if resp.status_code == 401:
            return True
        return (path.startswith("/Ihm/") and resp.status_code == 200
                and "text/html" in (resp.headers.get("Content-Type") or "")
                and b"window.location" in resp.content[:300])

    @staticmethod
    def _no_right(path: str, resp: requests.Response) -> bool:
        """A file page answers a document the user cannot see, or that does not
        exist, by a redirect to the application's `no_right` page."""
        return (path.startswith("/Ihm/") and 300 <= resp.status_code < 400
                and "page=no_right" in (resp.headers.get("Location") or ""))

    def _send(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None,
              json: Any = None, stream: bool = False) -> requests.Response:
        """A call in the account's session, logging in again once if Zeendoc says
        the session is over."""
        for renewed in (False, True):
            cookie = auth.get_session_cookie(
                self.root, login=self.login, password=self.password, key=self._key)
            resp = self._attempt(method, path, cookie, params=params, json=json,
                                 stream=stream)
            if not self._session_over(path, resp):
                return resp
            resp.close()
            auth.invalidate(self._key)
        raise UpstreamHTTPError(401, {"error": "Zeendoc closed the session right after login"},
                                service="zeendoc", method=method, url=f"{self.root}{path}")

    def _json(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None,
              json: Any = None) -> Any:
        resp = self._send(method, path, params=params, json=json)
        raise_for_upstream(resp, service="zeendoc")
        if "json" not in (resp.headers.get("Content-Type") or ""):
            # e.g. a bare `OPERATOR NOT KNOWN` under a 200.
            raise UpstreamHTTPError.from_response(
                resp, service="zeendoc",
                body={"error": "Zeendoc answered a non-JSON page", "text": resp.text[:200]})
        return resp.json() if resp.content else {}

    # --- shaping ------------------------------------------------------------

    @staticmethod
    def _keyed_by_field(values: Any) -> Dict[str, Any]:
        """`{customT2: …}` → `{custom_t2: …}`, the names `get_context` and criteria use;
        an empty object comes as `[]`."""
        if not isinstance(values, dict):
            return {}
        return {_CAMEL.sub("_", k).lower(): v for k, v in values.items()}

    @classmethod
    def _documents(cls, found: Dict[str, Any]) -> Dict[str, Any]:
        docs = found.get("document") or []
        for doc in docs:
            doc["properties"] = doc.get("properties") or {}
            for key in ("indexes", "displayableIndexes"):
                doc[key] = cls._keyed_by_field(doc.get(key))
        found["document"] = docs
        return found

    def _all_columns(self, binder: str) -> List[str]:
        """Every field of the binder, with the default properties."""
        if binder not in self._columns:
            for coll in self.get_context().get("collections") or []:
                if coll.get("collId"):
                    self._columns[coll["collId"]] = [
                        f["indexId"] for f in coll.get("index") or [] if f.get("indexId")]
            if binder not in self._columns:
                raise UpstreamHTTPError(
                    403, {"error": f"binder {binder!r} is not one this user can open"},
                    service="zeendoc")
        return list(PROPERTIES) + self._columns[binder]

    def _columns_of(self, binder: str, columns: Optional[List[str]]) -> str:
        if columns is None:
            return ";".join(self._all_columns(binder))
        if not isinstance(columns, list) or not columns:
            raise ValueError("`columns` must be a non-empty list of field or property names.")
        return ";".join(self._field("columns", c) for c in columns)

    # --- probe --------------------------------------------------------------

    def probe(self) -> Any:
        """Check that the login, password and cabinet authenticate, for the cost of
        one login and one read."""
        return self.get_context()

    # --- binders and fields -------------------------------------------------

    def get_context(self) -> Any:
        """GET /api/v4/context — the user, the cabinet's document statuses, and the
        binders the user can open: `collections[] {collId, label, rights
        {canSearchDocs, canViewDocs, canUploadDocs}, index[] {indexId, label, type,
        isMultivalued, isListchoice, possibleValue}}`. An entry without `collId` is
        the cross-binder search, not a binder."""
        return self._json("GET", "/api/v4/context")

    def list_field_choices(self, binder: str, field: str) -> Any:
        """GET /api/v4/binders/{binder}/fields/{field}/item-list — the choices of a
        list field `{nb, itemsList [{id, label, nbDocuments}]}`, with how many
        documents use each; 404 on a field that is not a list, 403 when the user
        may not administer the binder (the choices are then in `get_context`)."""
        b = self._slug("binder", binder)
        f = self._field("field", field)
        return self._json("GET", f"/api/v4/binders/{b}/fields/{f}/item-list")

    def suggest_field_values(self, binder: str, field: str, term: str) -> Any:
        """GET /api/v4/binders/{binder}/fields/{field}/autocomplete-search — the
        values of a text field that start like `term` (`{value: [...]}`), to find
        the exact spelling before an EQUALS."""
        b = self._slug("binder", binder)
        f = self._field("field", field)
        return self._json("GET", f"/api/v4/binders/{b}/fields/{f}/autocomplete-search",
                          params={"term": self._value("term", term)})

    # --- documents ----------------------------------------------------------

    def search_documents(self, binder: str, criteria: Optional[List[Dict[str, Any]]] = None,
                         *, match: str = "all", order_by: Optional[str] = None,
                         order: str = "desc", offset: int = 0, limit: int = PAGE_MAX,
                         columns: Optional[List[str]] = None) -> Any:
        """POST /api/v4/binders/{binder}/documents/search — `{nbDocs, stats,
        document [{resId, properties, indexes, displayableIndexes}]}`, newest first
        unless `order_by` names a field or property. Without `columns`, every field
        of the binder is returned (one more call to read them)."""
        b = self._slug("binder", binder)
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError(f"`offset` must be an integer >= 0; got {offset!r}.")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= PAGE_MAX:
            raise ValueError(f"`limit` must be an integer from 1 to {PAGE_MAX}; got {limit!r}.")
        body = self._query(criteria, match)
        if order_by is not None:
            body["orderCol"] = self._field("order_by", order_by)
            body["order"] = self._choice("order", order, ORDERS).upper()
        body.update({"from": offset, "nbResults": limit,
                     "wantedColumns": self._columns_of(b, columns)})
        return self._documents(
            self._json("POST", f"/api/v4/binders/{b}/documents/search", json=body))

    def count_documents(self, binder: str, criteria: Optional[List[Dict[str, Any]]] = None,
                        *, match: str = "all") -> Any:
        """POST /api/v4/binders/{binder}/documents/count — `{nbDocs}` for the same
        criteria as a search."""
        b = self._slug("binder", binder)
        return self._json("POST", f"/api/v4/binders/{b}/documents/count",
                          json=self._query(criteria, match))

    def get_document(self, binder: str, res_id: int,
                     columns: Optional[List[str]] = None) -> Any:
        """One document by id, as a search returns it (stored and displayed values):
        a search on `Res_Id`. 404 when the binder holds no such document visible to
        this user."""
        rid = self._res_id(res_id)
        found = self.search_documents(
            binder, [{"field": "Res_Id", "operator": "EQUALS", "value": rid}],
            limit=1, columns=columns)
        if not found["document"]:
            raise UpstreamHTTPError(
                404, {"error": f"no document {rid} visible to this user in {binder}"},
                service="zeendoc")
        return found["document"][0]

    def get_document_text(self, binder: str, res_id: int) -> str:
        """GET /Ihm/View/Get_Texte_Document.php — the text Zeendoc extracted from the
        document (OCR), laid out as on the page. 404 on an unknown document."""
        b = self._slug("binder", binder)
        rid = self._res_id(res_id)
        resp = self._send("GET", "/Ihm/View/Get_Texte_Document.php",
                          params={"Coll_Id": b, "Res_Id": rid, "Format": "Raw"})
        raise_for_upstream(resp, service="zeendoc")
        if resp.content.strip() == b"ERROR":
            raise UpstreamHTTPError(
                404, {"error": f"no document {rid} visible to this user in {b}"},
                service="zeendoc")
        try:
            text = resp.content.decode("utf-8")
        except UnicodeDecodeError:
            text = resp.content.decode("cp1252", errors="replace")
        return text.replace("\r\n", "\n")

    def download_document(self, binder: str, res_id: int, version: str = "pdf") -> Dict[str, Any]:
        """GET /Ihm/View/Get_Doc.php — the document's file: `pdf`, the PDF Zeendoc
        keeps with its stamps and comments, or `original`, the file as received.
        Returns `{filename, content_type, content}` (bytes, at most 50 MB)."""
        b = self._slug("binder", binder)
        rid = self._res_id(res_id)
        wanted = FILE_VERSIONS[self._choice("version", version, tuple(FILE_VERSIONS))]
        resp = self._send("GET", "/Ihm/View/Get_Doc.php", stream=True, params={
            "Coll_Id": b, "Id": rid, "Confirm": "Ok", "Action": "DOWNLOAD",
            "Version": wanted, "Pages": 0, "linked_option": "no", "Comments": 1,
            "Valider_Download": "ok"})
        with resp:
            if self._no_right("/Ihm/", resp):
                raise UpstreamHTTPError(
                    404, {"error": f"no document {rid} visible to this user in {b}"},
                    service="zeendoc", method="GET", url=resp.url)
            raise_for_upstream(resp, service="zeendoc")
            content = bytearray()
            for chunk in resp.iter_content(chunk_size=1 << 16):
                content.extend(chunk)
                if len(content) > MAX_FILE_BYTES:
                    raise UpstreamHTTPError(
                        413, {"error": f"file larger than {MAX_FILE_BYTES // (1 << 20)} MB"},
                        service="zeendoc", method="GET", url=resp.url)
            named = _FILENAME.search(resp.headers.get("Content-Disposition") or "")
        filename = named.group(1).strip() if named else f"{b}_{rid}"
        if wanted == "PDF":
            if not content.startswith(b"%PDF"):
                raise UpstreamHTTPError(502, {"error": "Zeendoc did not answer a PDF"},
                                        service="zeendoc", method="GET", url=resp.url)
            content_type = "application/pdf"
        else:
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return {"filename": filename, "content_type": content_type, "content": bytes(content)}
