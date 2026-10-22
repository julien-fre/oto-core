"""The argument helpers every Allo call family shares: a path segment, a closed list, a page size, a body or a
query without its absent values, and the removal of a call's recording addresses."""
from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import quote

from ..const import MAX_SIZE, RECORDING_ADDRESS_FIELDS


def _segment(value: Any, name: str) -> str:
    """A path segment, percent-encoded whole (a `+`, a `/` never reshape the path)."""
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"`{name}` is required.")
    if text in (".", ".."):
        raise ValueError(f"`{name}` is not a valid value.")
    return quote(text, safe="")


def _choice(name: str, value: Optional[str], allowed: tuple) -> Optional[str]:
    if value is None:
        return None
    if value not in allowed:
        raise ValueError(f"`{name}` must be one of {', '.join(allowed)}.")
    return value


def _size(size: Optional[int]) -> Optional[int]:
    if size is not None and not 1 <= int(size) <= MAX_SIZE:
        raise ValueError(f"`size` must be from 1 to {MAX_SIZE}.")
    return size


def _clean(values: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None}


def _some(name: str, values: Dict[str, Any]) -> Dict[str, Any]:
    """A partial update: at least one field given, or nothing would change."""
    if not _clean(values):
        raise ValueError(f"`{name}` changes nothing: give at least one field.")
    return values


def _without_addresses(item: Any) -> None:
    """Remove the recording addresses (`RECORDING_ADDRESS_FIELDS`) of one item; anything but an object is left as is."""
    if isinstance(item, dict):
        for field in RECORDING_ADDRESS_FIELDS:
            item.pop(field, None)


def _items_without_addresses(answer: Any, *, under: Optional[str] = None) -> Any:
    """The answer whose items (`data`, one object or a list), or the `under` key of each, lost their recording
    addresses; the rest of the answer (`pagination`) is kept."""
    if isinstance(answer, dict):
        data = answer.get("data")
        for entry in data if isinstance(data, list) else [data]:
            _without_addresses(entry.get(under) if under and isinstance(entry, dict) else entry)
    return answer
