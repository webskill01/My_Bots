"""Text to entry data, plus date and period math. No I/O, no telegram, no floats."""

import calendar
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

_CATEGORY_RE = re.compile(r"#(\w+)")

_MONTHS = {}
for _i in range(1, 13):
    _MONTHS[calendar.month_name[_i].lower()] = _i
    _MONTHS[calendar.month_abbr[_i].lower()] = _i
_MONTHS["sept"] = 9  # calendar only gives us "sep", but people type "sept"

# How far ahead a bare (yearless) date may sit before we read it as last year's.
_FUTURE_GRACE = dt.timedelta(days=7)


def parse_amount(s: str) -> int | None:
    """'250.50' -> 25050. None if it isn't an amount money can actually hold."""
    m = _AMOUNT_RE.match(s.replace(",", "").strip())
    if not m:
        return None
    rupees, paise = m.group(1), (m.group(2) or "").ljust(2, "0")
    return int(rupees) * 100 + int(paise)


def _from_parts(day: int, month: int, year: int | None, today: dt.date) -> dt.date | None:
    if year is not None:
        if year < 100:
            year += 2000
        try:
            return dt.date(year, month, day)
        except ValueError:
            return None
    try:
        d = dt.date(today.year, month, day)
    except ValueError:
        return None
    if d > today + _FUTURE_GRACE:
        # "31 dec" typed in August means the December that already happened.
        try:
            d = dt.date(today.year - 1, month, day)
        except ValueError:
            return None  # 29 Feb, and last year wasn't a leap year
    return d


def parse_date(token: str, today: dt.date) -> dt.date | None:
    """Understand one date token. None means 'this isn't a date, leave it alone'."""
    t = " ".join(token.lower().split())
    if not t:
        return None
    if t == "today":
        return today
    if t == "yesterday":
        return today - dt.timedelta(days=1)

    if m := re.fullmatch(r"(\d{1,3})d", t):
        return today - dt.timedelta(days=int(m[1]))

    if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", t):
        return _from_parts(int(m[1]), int(m[2]), int(m[3]) if m[3] else None, today)

    if m := re.fullmatch(r"(\d{1,2})\s+([a-z]+)", t):  # "24 aug"
        month = _MONTHS.get(m[2])
        return _from_parts(int(m[1]), month, None, today) if month else None

    if m := re.fullmatch(r"([a-z]+)\s+(\d{1,2})", t):  # "aug 24"
        month = _MONTHS.get(m[1])
        return _from_parts(int(m[2]), month, None, today) if month else None

    return None


def parse_entry(text: str, today: dt.date) -> Parsed | None:
    """Parse one free-text line into an entry. None means 'show the user a hint'."""
    text = text.strip()

    category = None
    if m := _CATEGORY_RE.search(text):
        category = m[1].lower()
        text = _CATEGORY_RE.sub("", text, count=1)

    # Pull a trailing date off the end: two words first ("24 aug"), then one.
    # Never consume the last token — that's the amount, and a bare number is
    # not a date anyway.
    tokens = text.split()
    on_date = today
    for n in (2, 1):
        if len(tokens) > n and (d := parse_date(" ".join(tokens[-n:]), today)):
            on_date, tokens = d, tokens[:-n]
            break

    m = _ENTRY_RE.match(" ".join(tokens))
    if not m:
        return None

    amount = parse_amount(m.group(2))
    if not amount:  # unparseable, or zero — zero is not a transaction
        return None

    name = " ".join((m.group(3) or "").split())
    kind = "earn" if m.group(1) == "+" else "exp"
    return Parsed(kind, amount, name, category, on_date)
