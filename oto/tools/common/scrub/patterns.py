"""Sensitive values found by their SHAPE in free text — no model, no network.

Each detector returns spans `(start, end, kind)` over the text it receives. A shape that
carries a checksum is validated by it (NIR key, IBAN mod 97, Luhn): a number that only
looks like one is left alone. Separators tolerated inside a number: space, no-break
space (also as the HTML entities `&nbsp;` / `&#160;`), dot, dash.
"""
from __future__ import annotations

import re

# One optional separator between two groups of a number.
_SEP = r"(?:[  .\-]|&nbsp;|&#160;)?"
_ENTITY = re.compile(r"&nbsp;|&#160;")

Span = tuple[int, int, str]


def compact(value: str) -> str:
    """The value without separators nor HTML spaces, upper-cased: what is validated and
    what a stable token is derived from."""
    return re.sub(r"[^0-9A-Za-z@._+\-]", "", _ENTITY.sub("", value)).upper()


def _alnum(value: str) -> str:
    return re.sub(r"[^0-9A-Z]", "", compact(value))


# --- NIR (French social security number) -------------------------------------------

_NIR = re.compile(
    rf"(?<![0-9A-Za-z])[12]{_SEP}\d\d{_SEP}\d\d{_SEP}(?:\d\d|2A|2B|2a|2b){_SEP}"
    rf"\d\d\d{_SEP}\d\d\d(?:{_SEP}\d\d)?(?![0-9A-Za-z])")


def _nir_ok(value: str) -> bool:
    v = _alnum(value)
    if len(v) == 13:
        # Without its key, only the separated layout of a NIR is taken (a bare run of
        # 13 digits is too often something else).
        return bool(re.search(r"\D", _ENTITY.sub(" ", value)))
    if len(v) != 15:
        return False
    body, key = v[:13], int(v[13:])
    body = body.replace("2A", "19").replace("2B", "18")
    return 97 - int(body) % 97 == key


def nir(text: str) -> list[Span]:
    return [(m.start(), m.end(), "nir") for m in _NIR.finditer(text) if _nir_ok(m.group())]


# --- IBAN -------------------------------------------------------------------------

_IBAN_START = re.compile(r"(?<![0-9A-Za-z])[A-Z]{2}\d\d")
_IBAN_CHAR = re.compile(rf"{_SEP}[0-9A-Z]")


def _iban_ok(v: str) -> bool:
    if not 15 <= len(v) <= 34:
        return False
    moved = v[4:] + v[:4]
    return int("".join(str(int(c, 36)) for c in moved)) % 97 == 1


def iban(text: str) -> list[Span]:
    """Longest run that validates: the greedy run of groups can swallow the next word
    (`… 189 MERCI`), so it shrinks until the checksum holds."""
    out: list[Span] = []
    pos = 0
    while (m := _IBAN_START.search(text, pos)) is not None:
        ends = [m.end()]
        cur = m.end()
        while len(ends) <= 30 and (c := _IBAN_CHAR.match(text, cur)) is not None:
            cur = c.end()
            ends.append(cur)
        found = next((e for e in reversed(ends)
                      if (e == len(text) or not text[e].isalnum())
                      and _iban_ok(_alnum(text[m.start():e]))), None)
        if found is not None:
            out.append((m.start(), found, "iban"))
            pos = found
        else:
            pos = m.start() + 1
    return out


# --- Payment card ------------------------------------------------------------------

_CARD = re.compile(rf"(?<![0-9])[2-6]\d{{3}}(?:{_SEP}\d){{9,15}}(?![0-9])")


def _luhn(digits: str) -> bool:
    total = 0
    for i, c in enumerate(reversed(digits)):
        n = int(c) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def card(text: str) -> list[Span]:
    out = []
    for m in _CARD.finditer(text):
        digits = _alnum(m.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            out.append((m.start(), m.end(), "card"))
    return out


# --- E-mail, phone -----------------------------------------------------------------

_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")


def email(text: str) -> list[Span]:
    return [(m.start(), m.end(), "email") for m in _EMAIL.finditer(text)]


_PHONE = re.compile(
    rf"(?<![0-9A-Za-z+])(?:(?:\+|00)33{_SEP}(?:\(0\){_SEP})?|0)[1-9](?:{_SEP}\d\d){{4}}(?![0-9])"
    rf"|(?<![0-9A-Za-z+])\+(?!33)[1-9]\d{{0,2}}(?:{_SEP}\d){{7,13}}(?![0-9])")


def phone(text: str) -> list[Span]:
    return [(m.start(), m.end(), "phone") for m in _PHONE.finditer(text)]


# --- Secrets: a value announced by its label, or a known credential format -----------

# A strong label (« mot de passe », « mdp »…) announces its value by `:`, `=` or « est »;
# a weak one (« token », « secret », « pin »…) only by `:` or `=` — « le token est
# expiré » is prose, not a secret.
_LABELLED = re.compile(
    r"(?i)\b(?:(?:mot\s+de\s+passe|mdp|password|passwd|pwd|code\s+secret|code\s+pin)"
    r"(?:\s+provisoire)?\s*(?:[:=]|\s(?:est|is)\b\s*:?)"
    r"|(?:passphrase|api[\s_-]?key|cl[ée]\s+d['’]api|token|secret|pin)\s*[:=])"
    r"(?:\s|&nbsp;|&#160;|<[^>]+>)*"
    r"(?P<value>[^\s<\"'«»&]{3,})")
_KNOWN_FORMATS = re.compile(
    r"\bsk-[A-Za-z0-9_\-]{20,}|\bgh[pousr]_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{30,}"
    r"|\bAKIA[0-9A-Z]{16}\b|\bxox[abpors]-[A-Za-z0-9-]{10,}"
    r"|\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----")


def secret(text: str) -> list[Span]:
    out = [(m.start("value"), m.end("value"), "secret") for m in _LABELLED.finditer(text)]
    out += [(m.start(), m.end(), "secret") for m in _KNOWN_FORMATS.finditer(text)]
    return out


# Order matters when two shapes overlap: the first kind listed wins the tie.
DETECTORS = {"nir": nir, "iban": iban, "card": card, "email": email, "phone": phone,
             "secret": secret}
