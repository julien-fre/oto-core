"""Contacts: the account's contact list, each contact's segments and topics,
and `upsert_contact`.

Never instantiated on its own: composed into `ResendClient`, which provides
the transport (`_get`, `_post`, `_patch`, `_delete`) and the checks (`_need`,
`_page`, `_seg`).

What the caller needs to know, and cannot guess:

- **A contact is one email address, global to the account.** Every contact
  route takes either its id or its email in the path.
- **`unsubscribed` is the GLOBAL opt-out**: true means no Broadcast reaches
  the contact, whatever its segments. A topic opt-out is per topic, and set by
  the recipient (`list_contact_topics`).
- **Only creation takes segments inline.** An existing contact joins a
  segment one call per segment (`add_contact_to_segment`).
- **The API documents no upsert.** `upsert_contact` reads the contact by email,
  then creates it or updates what differs.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from ...common.errors import UpstreamHTTPError
from ..const import MAX_PAGE_SIZE, MAX_WALK_PAGES

_SCALARS = (str, int, float, bool)


class _ContactsMixin:
    """Contacts, their segment memberships and topic subscriptions."""

    # --- checks -------------------------------------------------------------

    @staticmethod
    def _email(value: Any) -> str:
        if not isinstance(value, str) or "@" not in value or any(
                c.isspace() for c in value.strip()):
            raise ValueError(f"`email`: {value!r} is not an email address.")
        return value.strip()

    @staticmethod
    def _ids(name: str, values: Optional[Sequence[str]]) -> List[str]:
        """A list of non-empty string ids, duplicates dropped, order kept."""
        if values is None:
            return []
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise ValueError(f"`{name}` must be a list of ids.")
        out: List[str] = []
        for v in values:
            if not isinstance(v, str) or not v.strip():
                raise ValueError(f"`{name}`: each id must be a non-empty string; got {v!r}.")
            if v.strip() not in out:
                out.append(v.strip())
        return out

    @staticmethod
    def _fields(first_name: Optional[str], last_name: Optional[str],
                unsubscribed: Optional[bool],
                properties: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """The contact fields that were GIVEN — an omitted one is never sent,
        so it never overwrites what the contact already has."""
        out: Dict[str, Any] = {}
        for name, value in (("first_name", first_name), ("last_name", last_name)):
            if value is not None:
                if not isinstance(value, str):
                    raise ValueError(f"`{name}` must be a string.")
                out[name] = value
        if unsubscribed is not None:
            if not isinstance(unsubscribed, bool):
                raise ValueError("`unsubscribed` must be true or false.")
            out["unsubscribed"] = unsubscribed
        if properties is not None:
            if not isinstance(properties, dict):
                raise ValueError("`properties` must be an object {key: value}.")
            for key, value in properties.items():
                if not isinstance(key, str) or not key:
                    raise ValueError("`properties`: each key must be a non-empty string.")
                if value is not None and not isinstance(value, _SCALARS):
                    raise ValueError(
                        f"`properties.{key}` must be a string, a number, a boolean "
                        "or null.")
            if properties:
                out["properties"] = dict(properties)
        return out

    # --- reads --------------------------------------------------------------

    def list_contacts(self, segment_id: Optional[str] = None, *,
                      limit: Optional[int] = None, after: Optional[str] = None,
                      before: Optional[str] = None) -> Any:
        """GET /contacts — `{object, has_more, data: [{id, email, first_name,
        last_name, created_at, unsubscribed}]}`. `segment_id` keeps the
        contacts of that segment only."""
        params = self._page(limit, after, before)
        if segment_id is not None:
            params["segment_id"] = self._need(segment_id, "segment_id").strip()
        return self._get("/contacts", params)

    def get_contact(self, contact: str) -> Any:
        """GET /contacts/{id|email} — the contact, with its custom
        `properties` as `{key: {value, type}}`."""
        return self._get(f"/contacts/{self._seg(contact, 'contact')}")

    def find_contact(self, contact: str) -> Optional[Dict[str, Any]]:
        """`get_contact`, or None when the API answers 404 (no such contact)."""
        try:
            return self.get_contact(contact)
        except UpstreamHTTPError as e:
            if e.status_code == 404:
                return None
            raise

    def list_contact_segments(self, contact: str, *, limit: Optional[int] = None,
                              after: Optional[str] = None,
                              before: Optional[str] = None) -> Any:
        """GET /contacts/{id|email}/segments — `{object, has_more, data:
        [{id, name, created_at}]}`."""
        return self._get(f"/contacts/{self._seg(contact, 'contact')}/segments",
                         self._page(limit, after, before))

    def list_contact_topics(self, contact: str, *, limit: Optional[int] = None,
                            after: Optional[str] = None,
                            before: Optional[str] = None) -> Any:
        """GET /contacts/{id|email}/topics — `{object, has_more, data: [{id,
        name, description, subscription}]}`, `subscription` = opt_in | opt_out."""
        return self._get(f"/contacts/{self._seg(contact, 'contact')}/topics",
                         self._page(limit, after, before))

    # --- writes -------------------------------------------------------------

    def create_contact(self, email: str, *, first_name: Optional[str] = None,
                       last_name: Optional[str] = None,
                       unsubscribed: Optional[bool] = None,
                       properties: Optional[Dict[str, Any]] = None,
                       segment_ids: Optional[Sequence[str]] = None) -> Any:
        """POST /contacts — `{object, id}`. `segment_ids` puts the new contact
        in those segments in the same call."""
        body: Dict[str, Any] = {"email": self._email(email)}
        body.update(self._fields(first_name, last_name, unsubscribed, properties))
        segments = self._ids("segment_ids", segment_ids)
        if segments:
            body["segments"] = [{"id": s} for s in segments]
        return self._post("/contacts", body)

    def update_contact(self, contact: str, *, first_name: Optional[str] = None,
                       last_name: Optional[str] = None,
                       unsubscribed: Optional[bool] = None,
                       properties: Optional[Dict[str, Any]] = None) -> Any:
        """PATCH /contacts/{id|email} — `{object, id}`. Only the given fields
        change; a property set to None is cleared."""
        fields = self._fields(first_name, last_name, unsubscribed, properties)
        if not fields:
            raise ValueError("Nothing to update: pass first_name, last_name, "
                             "unsubscribed or properties.")
        return self._patch(f"/contacts/{self._seg(contact, 'contact')}", fields)

    def delete_contact(self, contact: str) -> Any:
        """DELETE /contacts/{id|email} — `{object, contact, deleted}`."""
        return self._delete(f"/contacts/{self._seg(contact, 'contact')}")

    def add_contact_to_segment(self, contact: str, segment_id: str) -> Any:
        """POST /contacts/{id|email}/segments/{segment_id} — `{id}`."""
        return self._post(f"/contacts/{self._seg(contact, 'contact')}/segments/"
                          f"{self._seg(segment_id, 'segment_id')}", None)

    def remove_contact_from_segment(self, contact: str, segment_id: str) -> Any:
        """DELETE /contacts/{id|email}/segments/{segment_id} — `{object, id,
        deleted}`."""
        return self._delete(f"/contacts/{self._seg(contact, 'contact')}/segments/"
                            f"{self._seg(segment_id, 'segment_id')}")

    # --- upsert -------------------------------------------------------------

    def _segment_ids_of(self, contact: str) -> List[str]:
        """Every segment id the contact belongs to, all pages read — or a
        refusal, never a partial answer."""
        ids: List[str] = []
        after = None
        for _ in range(MAX_WALK_PAGES):
            page = self.list_contact_segments(contact, limit=MAX_PAGE_SIZE, after=after)
            data = (page or {}).get("data") or []
            ids += [s["id"] for s in data if isinstance(s, dict) and s.get("id")]
            if not page.get("has_more") or not data:
                return ids
            after = data[-1].get("id")
        raise ValueError(
            f"The contact belongs to more than {MAX_WALK_PAGES * MAX_PAGE_SIZE} "
            "segments; its memberships were not read in full.")

    def upsert_contact(self, email: str, *, first_name: Optional[str] = None,
                       last_name: Optional[str] = None,
                       unsubscribed: Optional[bool] = None,
                       properties: Optional[Dict[str, Any]] = None,
                       segment_ids: Optional[Sequence[str]] = None,
                       dry_run: bool = False) -> Dict[str, Any]:
        """Create the contact, or update what differs — and make it a member of
        `segment_ids`. Safe to run again: a second run finds nothing to do.

        Reads the contact by email (404 = absent). Absent: one create, with the
        segments inline. Present: a PATCH of the given fields that DIFFER (none
        if nothing differs), then one add per segment it is not yet in. Omitted
        fields are never sent.

        ⚠️ **An upsert never resubscribes.** A contact that unsubscribed stays
        unsubscribed even if `unsubscribed=False` is passed: the receipt says
        `kept_unsubscribed`. Reversing an opt-out is a deliberate
        `update_contact(..., unsubscribed=False)`, never a side effect of a batch.

        `dry_run=True` does the reads and no write. Receipt: `{email, id,
        action, unsubscribed, changes?, fields?, segments_added? (dry run:
        segments_to_add), already_in_segments?, kept_unsubscribed?, dry_run?}`
        — `action` is created | updated | unchanged (dry run: would_create |
        would_update | unchanged).
        """
        email = self._email(email)
        fields = self._fields(first_name, last_name, unsubscribed, properties)
        segments = self._ids("segment_ids", segment_ids)
        current = self.find_contact(email)

        if current is None:
            out: Dict[str, Any] = {
                "email": email, "id": None,
                "action": "would_create" if dry_run else "created",
                "unsubscribed": bool(fields.get("unsubscribed", False))}
            if fields:
                out["fields"] = fields
            if segments:
                out["segments_to_add" if dry_run else "segments_added"] = segments
            if dry_run:
                out["dry_run"] = True
                return out
            created = self.create_contact(email, segment_ids=segments, **fields)
            out["id"] = (created or {}).get("id")
            return out

        contact_id = current.get("id") or email
        changes, kept = _diff(current, fields)
        member = set(self._segment_ids_of(contact_id)) if segments else set()
        to_add = [s for s in segments if s not in member]
        already = [s for s in segments if s in member]

        state = changes.get("unsubscribed", {}).get("to", current.get("unsubscribed"))
        out = {"email": email, "id": current.get("id"),
               "action": ("unchanged" if not (changes or to_add)
                          else "would_update" if dry_run else "updated"),
               "unsubscribed": bool(state)}
        if changes:
            out["changes"] = changes
        if to_add:
            out["segments_to_add" if dry_run else "segments_added"] = to_add
        if already:
            out["already_in_segments"] = already
        if kept:
            out["kept_unsubscribed"] = True
        if dry_run:
            out["dry_run"] = True
            return out

        if changes:
            patch = {k: v["to"] for k, v in changes.items() if k != "properties"}
            if "properties" in changes:
                patch["properties"] = changes["properties"]["to"]
            self.update_contact(contact_id, **patch)
        for segment in to_add:
            self.add_contact_to_segment(contact_id, segment)
        return out


def _same(current: Any, wanted: Any) -> bool:
    """A property value read back (`{value, type}` unwrapped) against the one
    given: `5` and `"5"` are the same value for a string property."""
    if current == wanted:
        return True
    return current is not None and wanted is not None and str(current) == str(wanted)


def _diff(current: Dict[str, Any], fields: Dict[str, Any]):
    """`(changes, kept_unsubscribed)` — the given fields that differ from the
    contact as read, as `{field: {from, to}}`; `properties` diffs key by key.
    A move from unsubscribed to subscribed is dropped, and reported."""
    changes: Dict[str, Any] = {}
    kept = False
    for name in ("first_name", "last_name", "unsubscribed"):
        if name in fields and fields[name] != current.get(name):
            changes[name] = {"from": current.get(name), "to": fields[name]}
    if current.get("unsubscribed") is True and fields.get("unsubscribed") is False:
        changes.pop("unsubscribed", None)
        kept = True
    if "properties" in fields:
        have = {k: (v.get("value") if isinstance(v, dict) else v)
                for k, v in (current.get("properties") or {}).items()}
        wanted = {k: v for k, v in fields["properties"].items()
                  if not _same(have.get(k), v)}
        if wanted:
            changes["properties"] = {"from": {k: have.get(k) for k in wanted},
                                     "to": wanted}
    return changes, kept
