"""Resend call families, composed into `ResendClient`.

One module per API domain. Contract details: `../client.py`.
"""

from .contacts import _ContactsMixin
from .segments import _SegmentsMixin, _TopicsMixin

__all__ = ["_ContactsMixin", "_SegmentsMixin", "_TopicsMixin"]
