"""Allo contacts CRM: people, companies, deals and the custom fields of people and companies.

Composed into `AlloClient`, which provides the transport (`_request`)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..const import ATTRIBUTE_TYPES, SORTS
from ._common import _choice, _segment, _size, _some


def _options(type: str, options: Optional[List[Dict[str, str]]]) -> Optional[List[Dict[str, str]]]:
    """A DROPDOWN field needs at least one option; any other type takes none."""
    if type == "DROPDOWN" and not options:
        raise ValueError("A `DROPDOWN` field needs at least one option in `options`.")
    if type != "DROPDOWN" and options:
        raise ValueError("Only a `DROPDOWN` field takes `options`.")
    return list(options) if options else None


def _type(type: str) -> str:
    if type is None:
        raise ValueError("`type` is required.")
    return _choice("type", type, ATTRIBUTE_TYPES)


class _CrmMixin:
    """People (`per-*`), companies (`com-*`), deals (`dea-*`) and custom fields."""

    # --- people ------------------------------------------------------------

    def search_people(self, *, filters: Optional[Dict[str, Any]] = None,
                      search: Optional[str] = None, sort: Optional[str] = None,
                      page: Optional[int] = None, size: Optional[int] = None) -> Any:
        return self._request("POST", "/v2/api/crm/people/search", body={
            "filters": filters, "search": search, "sort": _choice("sort", sort, SORTS),
            "page": page, "size": _size(size)})

    def get_person(self, person_id: str) -> Any:
        return self._request("GET", f"/v2/api/crm/people/{_segment(person_id, 'person_id')}")

    def create_person(self, numbers: List[str], **fields: Any) -> Any:
        """A person; `fields`: name, last_name, job_title, website, address, emails,
        company_id, allow_duplicate_number, custom_attributes."""
        if not numbers:
            raise ValueError("`numbers` must list at least one phone number.")
        return self._request("POST", "/v2/api/crm/people", body={"numbers": list(numbers), **fields})

    def update_person(self, person_id: str, **fields: Any) -> Any:
        """Only the fields given change."""
        return self._request("PUT", f"/v2/api/crm/people/{_segment(person_id, 'person_id')}",
                             body=fields)

    # --- companies and deals -----------------------------------------------

    def search_companies(self, *, filters: Optional[Dict[str, Any]] = None,
                         sort: Optional[str] = None, page: Optional[int] = None,
                         size: Optional[int] = None) -> Any:
        return self._request("POST", "/v2/api/crm/companies/search", body={
            "filters": filters, "sort": _choice("sort", sort, SORTS),
            "page": page, "size": _size(size)})

    def get_company(self, company_id: str) -> Any:
        return self._request("GET", f"/v2/api/crm/companies/{_segment(company_id, 'company_id')}")

    def create_company(self, name: str, **fields: Any) -> Any:
        """A company; `fields`: website, industry, custom_attributes."""
        return self._request("POST", "/v2/api/crm/companies", body={"name": name, **fields})

    def update_company(self, company_id: str, **fields: Any) -> Any:
        return self._request("PUT", f"/v2/api/crm/companies/{_segment(company_id, 'company_id')}",
                             body=fields)

    def search_deals(self, *, filters: Optional[Dict[str, Any]] = None,
                     search: Optional[str] = None, sort: Optional[str] = None,
                     page: Optional[int] = None, size: Optional[int] = None) -> Any:
        return self._request("POST", "/v2/api/crm/deals/search", body={
            "filters": filters, "search": search, "sort": _choice("sort", sort, SORTS),
            "page": page, "size": _size(size)})

    def get_deal(self, deal_id: str) -> Any:
        return self._request("GET", f"/v2/api/crm/deals/{_segment(deal_id, 'deal_id')}")

    # --- custom fields of people -------------------------------------------

    def list_person_attributes(self, *, page: Optional[int] = None,
                               size: Optional[int] = None) -> Any:
        """The custom fields of people (created or synced from a CRM)."""
        return self._request("GET", "/v2/api/crm/attributes",
                             params={"page": page, "size": _size(size)})

    def create_person_attribute(self, label: str, type: str, *,
                                options: Optional[List[Dict[str, str]]] = None) -> Any:
        """A custom field of people, its key derived from `label`. The same label and type again return the
        existing field (`already_existed`); the label of a deleted field restores it with its values."""
        return self._request("POST", "/v2/api/crm/attributes", body={
            "label": label, "type": _type(type), "options": _options(type, options)})

    def update_person_attribute(self, key: str, *, label: Optional[str] = None,
                                description: Optional[str] = None,
                                options: Optional[List[Dict[str, str]]] = None) -> Any:
        """Only the fields given change; `options` replaces the whole list (DROPDOWN only)."""
        return self._request("PATCH", f"/v2/api/crm/attributes/{_segment(key, 'key')}", body=_some(
            "update_person_attribute", {"label": label, "description": description, "options": options}))

    def delete_person_attribute(self, key: str) -> Any:
        """The field leaves the API; its values are kept, and creating it again restores them."""
        return self._request("DELETE", f"/v2/api/crm/attributes/{_segment(key, 'key')}")

    # --- custom attributes of companies ------------------------------------

    def list_company_attributes(self, *, page: Optional[int] = None,
                                size: Optional[int] = None) -> Any:
        return self._request("GET", "/v2/api/crm/companies/attributes",
                             params={"page": page, "size": _size(size)})

    def create_company_attribute(self, label: str, type: str, *,
                                 options: Optional[List[Dict[str, str]]] = None,
                                 prompt: Optional[str] = None,
                                 should_prompt_override: Optional[bool] = None) -> Any:
        """A custom attribute of companies, its key derived from `label`; the same key and type again return the
        existing one (`already_existed`). `prompt` tells Allo's AI how to fill it from calls."""
        return self._request("POST", "/v2/api/crm/companies/attributes", body={
            "label": label, "type": _type(type), "options": _options(type, options), "prompt": prompt,
            "should_prompt_override": should_prompt_override})

    def update_company_attribute(self, key: str, *, label: Optional[str] = None,
                                 options: Optional[List[Dict[str, str]]] = None,
                                 prompt: Optional[str] = None,
                                 should_prompt_override: Optional[bool] = None,
                                 is_visible: Optional[bool] = None) -> Any:
        """Only the fields given change; `options` replaces the whole list (DROPDOWN only)."""
        return self._request("PATCH", f"/v2/api/crm/companies/attributes/{_segment(key, 'key')}", body=_some(
            "update_company_attribute", {"label": label, "options": options, "prompt": prompt,
                                         "should_prompt_override": should_prompt_override,
                                         "is_visible": is_visible}))

    def delete_company_attribute(self, key: str) -> Any:
        """Irreversible: the attribute goes, and its value on every company with it."""
        return self._request("DELETE", f"/v2/api/crm/companies/attributes/{_segment(key, 'key')}")
