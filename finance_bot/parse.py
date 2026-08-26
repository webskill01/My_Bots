"""Text to entry data. No I/O, no telegram, no floats."""

import datetime as dt
import re
from typing import NamedTuple


class Parsed(NamedTuple):
    kind: str          # "exp" | "earn"
    amount: int        # minor units (paise)
    name: str
    category: str | None
    on_date: dt.date


# Rupees, optionally two decimal places. Commas are ignored so "1,000" works.
_AMOUNT_RE = re.compile(r"^(\d+)(?:\.(\d{1,2}))?$")

# Sign hugs the number, number leads the message: "+3000 freelance".
_ENTRY_RE = re.compile(r"^([+-]?)([\d,]+(?:\.\d+)?)(?:\s+(.*))?$", re.S)


def parse_amount(s: str) -> int | None:
    """'250.50' -> 25050. None if it isn't an amount money can actually hold."""
    m = _AMOUNT_RE.match(s.replace(",", "").strip())
    if not m:
        return None
    rupees, paise = m.group(1), (m.group(2) or "").ljust(2, "0")
    return int(rupees) * 100 + int(paise)


def parse_entry(text: str, today: dt.date) -> Parsed | None:
    """Parse one free-text line into an entry. None means 'show the user a hint'."""
    m = _ENTRY_RE.match(text.strip())
    if not m:
        return None

    amount = parse_amount(m.group(2))
    if not amount:  # unparseable, or zero — zero is not a transaction
        return None

    name = " ".join((m.group(3) or "").split())
    kind = "earn" if m.group(1) == "+" else "exp"
    return Parsed(kind, amount, name, None, today)
