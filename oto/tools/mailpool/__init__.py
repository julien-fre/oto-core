"""Mailpool client (cold-email domains, DNS, mailboxes, spam checks, warmup)."""

from ._mailboxes import MailpoolCreateRefused
from .client import (MailpoolClient, MailpoolDnsWriteError, is_secret_key,
                     project_mailbox, strip_secrets)

__all__ = ["MailpoolClient", "MailpoolCreateRefused", "MailpoolDnsWriteError", "is_secret_key",
           "project_mailbox", "strip_secrets"]
