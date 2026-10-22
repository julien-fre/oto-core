"""Allo call summary templates and webhooks. Composed into `AlloClient`, which provides the transport (`_request`)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..const import WEBHOOK_TOPICS
from ._common import _items_without, _segment, _some

# A webhook's signing secret never leaves the client: it is read in Allo.
_WEBHOOK_SECRET_FIELDS = ("signing_secret",)


def _without_secret(answer: Any) -> Any:
    return _items_without(answer, fields=_WEBHOOK_SECRET_FIELDS)


def _topics(topics: Optional[List[str]], *, required: bool) -> Optional[List[str]]:
    if topics is None and not required:
        return None
    if not topics:
        raise ValueError("`topics` must list at least one event topic.")
    unknown = [t for t in topics if t not in WEBHOOK_TOPICS]
    if unknown:
        raise ValueError(f"Unknown topic {unknown[0]}: one of {', '.join(WEBHOOK_TOPICS)}.")
    return list(topics)


def _https(url: Optional[str]) -> Optional[str]:
    if url is not None and not str(url).startswith("https://"):
        raise ValueError("`url` must be an https:// address.")
    return url


class _TemplatesWebhooksMixin:
    """Summary templates (`tst-*`), webhook endpoints and their event topics."""

    # --- summary templates -------------------------------------------------

    def list_summary_templates(self) -> Any:
        return self._request("GET", "/v2/api/summary_templates")

    def get_summary_template(self, template_id: str) -> Any:
        return self._request("GET", f"/v2/api/summary_templates/{_segment(template_id, 'template_id')}")

    def create_summary_template(self, name: str, *, call_context: Optional[str] = None,
                                icon: Optional[str] = None,
                                sections: Optional[List[Dict[str, Any]]] = None) -> Any:
        """A summary template: `sections` (10 at most), each `{title, instructions, order}`."""
        return self._request("POST", "/v2/api/summary_templates", body={
            "name": name, "call_context": call_context, "icon": icon, "sections": sections})

    def update_summary_template(self, template_id: str, name: str, *, call_context: Optional[str] = None,
                                icon: Optional[str] = None,
                                sections: Optional[List[Dict[str, Any]]] = None) -> Any:
        """Replace a template whole: what is not given is cleared."""
        return self._request("PUT", f"/v2/api/summary_templates/{_segment(template_id, 'template_id')}", body={
            "name": name, "call_context": call_context, "icon": icon, "sections": sections})

    def delete_summary_template(self, template_id: str) -> Any:
        """Deactivate a template."""
        return self._request("DELETE", f"/v2/api/summary_templates/{_segment(template_id, 'template_id')}")

    def set_default_summary_template(self, number: str, *, summary_template_id: Optional[str] = None) -> Any:
        """The template a line's call summaries use; without `summary_template_id`, the default is cleared."""
        return self._request("PUT", f"/v2/api/numbers/{_segment(number, 'number')}/default_summary_template",
                             body={"summary_template_id": summary_template_id})

    # --- webhooks ----------------------------------------------------------

    def list_webhooks(self) -> Any:
        """The endpoints, without their signing secret (read in Allo)."""
        return _without_secret(self._request("GET", "/v2/api/webhooks"))

    def get_webhook(self, webhook_id: str) -> Any:
        """One endpoint, without its signing secret (read in Allo)."""
        return _without_secret(self._request("GET", f"/v2/api/webhooks/{_segment(webhook_id, 'webhook_id')}"))

    def create_webhook(self, url: str, topics: List[str], *, description: Optional[str] = None) -> Any:
        """An endpoint that receives the events of `topics` at `url` (https); answered without its signing secret
        (read in Allo)."""
        if not url:
            raise ValueError("`url` is required.")
        return _without_secret(self._request("POST", "/v2/api/webhooks", body={
            "url": _https(url), "topics": _topics(topics, required=True), "description": description}))

    def update_webhook(self, webhook_id: str, *, url: Optional[str] = None, topics: Optional[List[str]] = None,
                       description: Optional[str] = None, enabled: Optional[bool] = None) -> Any:
        """Only the fields given change; `topics` replaces the whole set. Answered without the signing secret."""
        body = _some("update_webhook", {"url": _https(url), "topics": _topics(topics, required=False),
                                        "description": description, "enabled": enabled})
        return _without_secret(self._request("PUT", f"/v2/api/webhooks/{_segment(webhook_id, 'webhook_id')}",
                                             body=body))

    def delete_webhook(self, webhook_id: str) -> Any:
        """Delete an endpoint and its delivery history."""
        return self._request("DELETE", f"/v2/api/webhooks/{_segment(webhook_id, 'webhook_id')}")

    def list_webhook_event_types(self) -> Any:
        """The event topics a webhook may subscribe to."""
        return self._request("GET", "/v2/api/webhooks/event_types")
