"""Text to task data, plus the 'is this reminder due' rule. No I/O, no telegram."""

import calendar
import datetime as dt
import re
from typing import NamedTuple


class Parsed(NamedTuple):
    title: str
    tag: str | None
    daily: bool
    on_date: dt.date | None    # None for daily tasks
    at_time: str | None        # 'HH:MM', None = no reminder


_TAG_RE = re.compile(r"#(\w+)")

# "6pm", "6:30pm", "6.30 pm", "18:30". A bare "6" is not a time — "meet 2 friends".
_TIME_RE = re.compile(r"\b(?:(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)|(\d{1,2})[:.](\d{2}))\b")

_MONTHS = {}
for _i in range(1, 13):
    _MONTHS[calendar.month_name[_i].lower()] = _i
    _MONTHS[calendar.month_abbr[_i].lower()] = _i
_MONTHS["sept"] = 9

_WEEKDAYS = {}
for _i in range(7):
    _WEEKDAYS[calendar.day_name[_i].lower()] = _i
    _WEEKDAYS[calendar.day_abbr[_i].lower()] = _i

# A reminder that was missed while the bot was down still fires if it's this
# recent. Older daily ones are skipped: nobody wants 9 routine pings at once.
DAILY_GRACE = dt.timedelta(minutes=15)


def parse_time(s: str) -> str | None:
    """'6:30pm' -> '18:30'. None if it isn't a clock time."""
    m = _TIME_RE.fullmatch(" ".join(s.lower().split()))
    if not m:
        return None
    if m[3]:
        h, mins = int(m[1]), int(m[2] or 0)
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if m[3] == "pm" else 0)
    else:
        h, mins = int(m[4]), int(m[5])
    if h > 23 or mins > 59:
        return None
    return f"{h:02d}:{mins:02d}"


def _future(day: int, month: int, year: int | None, today: dt.date) -> dt.date | None:
    """A schedule looks forward: a yearless date already gone means next year's."""
    try:
        d = dt.date(year if year is not None else today.year, month, day)
        if year is None and d < today:
            d = d.replace(year=today.year + 1)
        return d
    except ValueError:
        return None


def parse_date(token: str, today: dt.date) -> dt.date | None:
    t = " ".join(token.lower().split())
    if t == "today":
        return today
    if t in ("tomorrow", "tmrw", "tmr"):
        return today + dt.timedelta(days=1)
    if t in _WEEKDAYS:  # the next one; "mon" typed on a Monday means next week
        return today + dt.timedelta(days=(_WEEKDAYS[t] - today.weekday() - 1) % 7 + 1)
    if m := re.fullmatch(r"in (\d{1,3})d", t):
        return today + dt.timedelta(days=int(m[1]))
    if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", t):
        year = int(m[3]) if m[3] else None
        if year is not None and year < 100:
            year += 2000
        return _future(int(m[1]), int(m[2]), year, today)
    if m := re.fullmatch(r"(\d{1,2})\s+([a-z]+)", t):   # "24 aug"
        return _future(int(m[1]), _MONTHS[m[2]], None, today) if m[2] in _MONTHS else None
    if m := re.fullmatch(r"([a-z]+)\s+(\d{1,2})", t):   # "aug 24"
        return _future(int(m[2]), _MONTHS[m[1]], None, today) if m[1] in _MONTHS else None
    return None


def parse_task(text: str, now: dt.datetime) -> Parsed | None:
    """One free-text line into a task. None means 'show the user a hint'.

    'gym 7am #daily', 'call mom 6pm', 'dentist tomorrow 10:30 #health'.
    Date and time may sit anywhere in the line; the rest is the title.
    """
    today = now.date()
    tags = [t.lower() for t in _TAG_RE.findall(text)]
    daily = "daily" in tags
    tag = next((t for t in tags if t != "daily"), None)
    text = _TAG_RE.sub(" ", text)

    at_time = None
    if m := _TIME_RE.search(text.lower()):
        at_time = parse_time(m[0])
        if at_time:
            text = text[:m.start()] + " " + text[m.end():]

    on_date, tokens = None, text.split()
    for n in (2, 1):   # two-word dates first, so "24 aug" isn't read as just "24"
        for i in range(len(tokens) - n + 1):
            if d := parse_date(" ".join(tokens[i:i + n]), today):
                on_date, tokens = d, tokens[:i] + tokens[i + n:]
                break
        if on_date:
            break

    # "at 6pm" / "on monday" leave a dangling word behind.
    while tokens and tokens[-1].lower() in ("at", "on", "by"):
        tokens.pop()
    title = " ".join(tokens)[:100]
    if not title:
        return None

    if daily:
        return Parsed(title, tag, True, None, at_time)
    if on_date is None:
        on_date = today
        # "call mom 9am" typed at 10am means tomorrow, not a reminder already missed.
        if at_time and at_time <= now.strftime("%H:%M"):
            on_date = today + dt.timedelta(days=1)
    return Parsed(title, tag, False, on_date, at_time)


def is_due(task, now: dt.datetime) -> bool:
    """Should this task's reminder go out right now? `now` is the user's local time.
    `task` is any mapping with the task columns."""
    today, today_iso = now.date(), now.date().isoformat()
    stamp = now.strftime("%Y-%m-%dT%H:%M")

    if task["daily"]:
        if not task["days"] >> today.weekday() & 1 or task["done_on"] == today_iso:
            return False
        if task["snooze_until"]:
            return task["snooze_until"] <= stamp
        if not task["at_time"] or task["reminded_on"] == today_iso:
            return False
        lo = now - DAILY_GRACE
        floor = lo.strftime("%H:%M") if lo.date() == today else "00:00"
        return floor <= task["at_time"] <= now.strftime("%H:%M")

    if task["done_on"]:
        return False
    if task["snooze_until"]:
        return task["snooze_until"] <= stamp
    if not task["at_time"] or task["reminded_on"]:
        return False
    # One-offs catch up: a missed appointment reminder is still worth sending.
    return f"{task['on_date']}T{task['at_time']}" <= stamp


def fmt_days(days: int) -> str:
    """127 -> 'Every day', 63 -> 'Mon–Sat', 0b0100101 -> 'Mon, Wed, Sat'."""
    if days == 127:
        return "Every day"
    on = [i for i in range(7) if days >> i & 1]
    if len(on) > 2 and on == list(range(on[0], on[-1] + 1)):
        return f"{calendar.day_abbr[on[0]]}–{calendar.day_abbr[on[-1]]}"
    return ", ".join(calendar.day_abbr[i] for i in on)


def fmt_time(hhmm: str | None) -> str:
    """'18:30' -> '6:30 PM'."""
    if not hhmm:
        return ""
    h, m = map(int, hhmm.split(":"))
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"
