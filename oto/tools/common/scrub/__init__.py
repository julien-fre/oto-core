"""Pseudonymise sensitive values written in free text.

`TextScrubber` replaces each sensitive passage of a text by a stable token —
`[NIR-3f2a9c]`, `[PERSON-81be04]` — so that the same value gives the same token within a
response and across calls, without the value being readable. Two sources of passages:

- the SHAPES (`patterns.py`): NIR, IBAN, payment card, e-mail, phone, labelled secrets
  and known credential formats — local, validated by their checksum when they have one;
- the MODEL (`model.py`), for what only a reading finds: names, postal addresses,
  credentials told in a sentence. Asked only when a model kind is requested, and
  required then: no detector given ⇒ `ScrubConfigError`, never a silent shape-only run.

The token is a truncated keyed digest (`salt`) of the compacted value: short enough that
many values share it, so it cannot be reversed by trying all NIRs.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Optional

from . import patterns
from .model import MODEL_KINDS, ChatSpanDetector, ModelDetectionError

PATTERN_KINDS = tuple(patterns.DETECTORS)
KINDS = PATTERN_KINDS + MODEL_KINDS

__all__ = ["ChatSpanDetector", "KINDS", "MODEL_KINDS", "ModelDetectionError",
           "PATTERN_KINDS", "ScrubConfigError", "TextScrubber"]


class ScrubConfigError(ValueError):
    """A scrub asked for something the scrubber cannot do (unknown kind, model kind
    without a model)."""


class TextScrubber:
    def __init__(self, salt: str = "", detector: Optional[ChatSpanDetector] = None):
        self.salt = salt
        self.detector = detector

    def scrub_many(self, texts: list[str], kinds: tuple[str, ...]) -> list[str]:
        """Each text with the passages of `kinds` replaced by their token."""
        unknown = set(kinds) - set(KINDS)
        if unknown:
            raise ScrubConfigError(f"unknown kinds: {sorted(unknown)} (expected {list(KINDS)})")
        model_kinds = tuple(k for k in kinds if k in MODEL_KINDS)
        if model_kinds and self.detector is None:
            raise ScrubConfigError(
                f"kinds {list(model_kinds)} need a model detector, and none is configured")
        found = [[s for k in PATTERN_KINDS if k in kinds for s in patterns.DETECTORS[k](t)]
                 for t in texts]
        if model_kinds:
            for spans, more in zip(found, self.detector.find(texts, model_kinds)):
                spans += more
        return [self._replace(t, spans) for t, spans in zip(texts, found)]

    def token(self, value: str, kind: str) -> str:
        key = patterns.compact(value) if kind in PATTERN_KINDS else " ".join(value.casefold().split())
        digest = hmac.new(self.salt.encode(), f"{kind}:{key}".encode(), hashlib.sha256)
        return f"[{kind.upper()}-{digest.hexdigest()[:6]}]"

    def _replace(self, text: str, spans: list[tuple[int, int, str]]) -> str:
        """Overlapping spans: the earliest wins, then the longest; replaced from the end."""
        kept: list[tuple[int, int, str]] = []
        for start, end, kind in sorted(spans, key=lambda s: (s[0], -(s[1] - s[0]))):
            if kept and start < kept[-1][1]:
                continue
            kept.append((start, end, kind))
        for start, end, kind in reversed(kept):
            text = text[:start] + self.token(text[start:end], kind) + text[end:]
        return text
