"""Scrub the string leaves of a connector response, in one pass per set of kinds.

A response holds many texts (tickets, threads, articles): they are gathered first, then
scrubbed together — one batch of model requests per response, not one per leaf.
"""
from __future__ import annotations

from typing import Any, Optional

from . import TextScrubber


class _Slot:
    __slots__ = ("i",)

    def __init__(self, i: int):
        self.i = i


def scrub_tree(data: Any, by_field: dict[str, tuple[str, ...]],
               everywhere: Optional[tuple[str, ...]], scrubber: TextScrubber) -> Any:
    """`data` with every string leaf scrubbed for the kinds that cover it: those of the
    nearest enclosing key named in `by_field` (lower-cased), else `everywhere` (None:
    leaves under no named key are left alone). Keys are never scrubbed."""
    texts: list[str] = []
    kinds_of: list[tuple[str, ...]] = []

    def gather(value: Any, kinds: Optional[tuple[str, ...]]) -> Any:
        if isinstance(value, dict):
            return {k: gather(v, by_field.get(k.lower(), kinds) if isinstance(k, str) else kinds)
                    for k, v in value.items()}
        if isinstance(value, list):
            return [gather(v, kinds) for v in value]
        if isinstance(value, str) and kinds and value.strip():
            texts.append(value)
            kinds_of.append(kinds)
            return _Slot(len(texts) - 1)
        return value

    shaped = gather(data, everywhere)
    if not texts:
        return data
    scrubbed: list[str] = [""] * len(texts)
    for kinds in dict.fromkeys(kinds_of):
        idx = [i for i, k in enumerate(kinds_of) if k == kinds]
        for i, text in zip(idx, scrubber.scrub_many([texts[i] for i in idx], kinds)):
            scrubbed[i] = text

    def fill(value: Any) -> Any:
        if isinstance(value, _Slot):
            return scrubbed[value.i]
        if isinstance(value, dict):
            return {k: fill(v) for k, v in value.items()}
        if isinstance(value, list):
            return [fill(v) for v in value]
        return value

    return fill(shaped)
