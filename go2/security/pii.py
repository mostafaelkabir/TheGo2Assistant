# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""Detection and redaction of personally identifiable information.

Every detector here is validated rather than purely pattern-matched wherever a
checksum exists -- Luhn for card numbers, mod-97 for IBANs. A regex alone
matches any sixteen digits, which in a corpus full of run identifiers, model
hashes and timestamps means constant false positives. A control that cries wolf
gets switched off, so precision matters more than recall for a redactor that
sits in a hot path.

Detection runs locally and touches no network. It is deliberately independent
of the embedding provider: the point is to decide what may leave the machine
*before* anything does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class PiiKind(StrEnum):
    """Categories of sensitive value, ordered roughly by severity."""

    CREDIT_CARD = "credit_card"
    IBAN = "iban"

    # credential. Renaming it to satisfy the rule would make the public
    # placeholder ([SECRET]) worse for no security benefit.
    SECRET = "secret"  # noqa: S105
    NATIONAL_ID = "national_id"
    EMAIL = "email"
    PHONE = "phone"
    IP_ADDRESS = "ip_address"


@dataclass(frozen=True, slots=True)
class Finding:
    """One detected value and where it sits in the text."""

    kind: PiiKind
    start: int
    end: int
    text: str

    @property
    def placeholder(self) -> str:
        """What replaces this value when redacted."""
        return f"[{self.kind.upper()}]"


def _luhn(digits: str) -> bool:
    """Whether a digit string passes the Luhn checksum used by payment cards."""
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:  # noqa: PLR2004 -- the Luhn rule itself.
                value -= 9
        total += value
    return total % 10 == 0


_IBAN_MIN = 15
_IBAN_MAX = 34


def _iban_valid(candidate: str) -> bool:
    """Whether a candidate passes the ISO 13616 mod-97 check."""
    compact = candidate.replace(" ", "").upper()
    if not _IBAN_MIN <= len(compact) <= _IBAN_MAX:
        return False
    rearranged = compact[4:] + compact[:4]
    digits = "".join(str(int(c, 36)) if c.isalpha() else c for c in rearranged)
    if not digits.isdigit():
        return False
    return int(digits) % 97 == 1


# Card-like runs of 13-19 digits, optionally separated by spaces or hyphens.
_CARD = re.compile(r"(?<![\w-])(?:\d[ -]?){12,18}\d(?![\w-])")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[ ]?(?:[A-Z0-9]{4}[ ]?){2,7}[A-Z0-9]{1,4}\b")
_EMAIL = re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
# A phone number must announce itself, and must be long enough to be one.
#
# Dots are not accepted as separators: with them, "+0.027 IoU" parses as a
# country code and a subscriber number. That is not hypothetical -- it was
# every single phone "detection" in the first scan of a real ML corpus, where
# signed decimal deltas are on almost every line.
_PHONE = re.compile(
    r"(?<![\w.])(?:"
    r"\+\d{1,3}[ -]?(?:\(?\d{1,4}\)?[ -]?){1,4}\d{2,4}"  # +44 20 7946 0958
    r"|\(\d{2,4}\)[ -]?\d{3,4}[ -]?\d{3,4}"  # (020) 7946 0958
    r"|\d{3,4}-\d{3,4}-\d{3,4}"  # 020-7946-0958
    r"|00\d{8,14}"  # 00218911234567, international access code
    r"|09\d{8}"  # Libyan mobile in national form
    r")(?![\w.])"
)
# E.164 allows at most 15 digits; ITU reserves 7 as a practical minimum for a
# nationally significant number. Anything outside that is not a phone number.
_PHONE_MIN_DIGITS = 7
_PHONE_MAX_DIGITS = 15


def _phone_findings(text: str) -> list[Finding]:
    found: list[Finding] = []
    for match in _PHONE.finditer(text):
        digits = re.sub(r"\D", "", match.group())
        if _PHONE_MIN_DIGITS <= len(digits) <= _PHONE_MAX_DIGITS:
            found.append(Finding(PiiKind.PHONE, match.start(), match.end(), match.group()))
    return found


_IP = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
# Vendor key prefixes plus a long opaque tail. Matching on the prefix keeps
# precision high; a generic "long random string" rule would flag every hash.
_VENDOR_KEY = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}"
    r"|jina_[A-Za-z0-9_-]{16,}"
    r"|gh[pousr]_[A-Za-z0-9]{16,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|AIza[0-9A-Za-z_-]{35})\b"
)
# Loose national-identifier shapes (US SSN, and similar 9-11 digit grouped ids).
_NATIONAL_ID = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

_MIN_CARD_DIGITS = 13
_MAX_CARD_DIGITS = 19
# ISO/IEC 7812 assigns the first digit as the Major Industry Identifier, and
# every payment scheme sits in 3-6 (Amex/Diners, Visa, Mastercard, Discover).
# Nothing is issued under 0, 1, 2, 7, 8 or 9.
#
# This is not pedantry. A Libyan mobile written with the international access
# code -- 00218... -- is fourteen digits and passes Luhn about one time in ten.
# Without this check a job advert gets reported as containing a credit card,
# which is both wrong and alarming.
_CARD_LEADING = frozenset("3456")


def _card_findings(text: str) -> list[Finding]:
    found: list[Finding] = []
    for match in _CARD.finditer(text):
        digits = re.sub(r"[ -]", "", match.group())
        if (
            _MIN_CARD_DIGITS <= len(digits) <= _MAX_CARD_DIGITS
            and digits[0] in _CARD_LEADING
            and _luhn(digits)
        ):
            found.append(Finding(PiiKind.CREDIT_CARD, match.start(), match.end(), match.group()))
    return found


def _iban_findings(text: str) -> list[Finding]:
    return [
        Finding(PiiKind.IBAN, m.start(), m.end(), m.group())
        for m in _IBAN.finditer(text)
        if _iban_valid(m.group())
    ]


def _simple_findings(text: str, pattern: re.Pattern[str], kind: PiiKind) -> list[Finding]:
    return [Finding(kind, m.start(), m.end(), m.group()) for m in pattern.finditer(text)]


def detect(text: str, *, kinds: frozenset[PiiKind] | None = None) -> list[Finding]:
    """Find sensitive values in text.

    Args:
        text: The text to scan.
        kinds: Restrict to these categories. Defaults to all.

    Returns:
        Findings ordered by position, with overlaps resolved in favour of the
        more severe category -- a card number inside a longer digit run should
        be reported as a card, not a phone number.
    """
    wanted = kinds if kinds is not None else frozenset(PiiKind)
    found: list[Finding] = []

    if PiiKind.CREDIT_CARD in wanted:
        found += _card_findings(text)
    if PiiKind.IBAN in wanted:
        found += _iban_findings(text)
    if PiiKind.SECRET in wanted:
        found += _simple_findings(text, _VENDOR_KEY, PiiKind.SECRET)
    if PiiKind.NATIONAL_ID in wanted:
        found += _simple_findings(text, _NATIONAL_ID, PiiKind.NATIONAL_ID)
    if PiiKind.EMAIL in wanted:
        found += _simple_findings(text, _EMAIL, PiiKind.EMAIL)
    if PiiKind.PHONE in wanted:
        found += _phone_findings(text)
    if PiiKind.IP_ADDRESS in wanted:
        found += _simple_findings(text, _IP, PiiKind.IP_ADDRESS)

    # Severity order matches PiiKind declaration order.
    severity = {kind: index for index, kind in enumerate(PiiKind)}
    found.sort(key=lambda f: (f.start, severity[f.kind]))

    kept: list[Finding] = []
    for finding in found:
        if kept and finding.start < kept[-1].end:
            continue  # overlapped by an earlier, more severe finding
        kept.append(finding)
    return kept


def redact(text: str, *, kinds: frozenset[PiiKind] | None = None) -> tuple[str, list[Finding]]:
    """Replace sensitive values with category placeholders.

    Placeholders rather than deletion, so the surrounding sentence keeps its
    shape and an embedding of the redacted text still means roughly what the
    original did.

    Args:
        text: The text to redact.
        kinds: Restrict to these categories. Defaults to all.

    Returns:
        The redacted text and what was found.
    """
    findings = detect(text, kinds=kinds)
    if not findings:
        return text, []

    out: list[str] = []
    cursor = 0
    for finding in findings:
        out.append(text[cursor : finding.start])
        out.append(finding.placeholder)
        cursor = finding.end
    out.append(text[cursor:])
    return "".join(out), findings


def summarise(findings: list[Finding]) -> dict[str, int]:
    """Count findings by category, for reporting without exposing values."""
    counts: dict[str, int] = {}
    for finding in findings:
        counts[str(finding.kind)] = counts.get(str(finding.kind), 0) + 1
    return counts
