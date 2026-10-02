"""Storage. Every function takes user_id first — tenancy is enforced here, not
in the handlers. If a query does not carry user_id, that query is a bug."""

import datetime as dt
import sqlite3
from zoneinfo import ZoneInfo

SCHEMA = """
CREATE TABLE IF NOT EXISTS user (
    user_id    INTEGER PRIMARY KEY,
    tz         TEXT NOT NULL DEFAULT 'Asia/Kolkata',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tag (
    id      INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user(user_id),
    name    TEXT NOT NULL COLLATE NOCASE,
    UNIQUE (user_id, name)
);

CREATE TABLE IF NOT EXISTS task (
    id           INTEGER PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES user(user_id),
    title        TEXT NOT NULL,
    tag_id       INTEGER REFERENCES tag(id) ON DELETE SET NULL,
    daily        INTEGER NOT NULL DEFAULT 0,   -- 1 = routine, repeats every day
    on_date      TEXT,       -- YYYY-MM-DD in the user's timezone; NULL when daily
    at_time      TEXT,       -- HH:MM local; NULL = no reminder
    done_on      TEXT,       -- date it was ticked off; for daily, only today's counts
    reminded_on  TEXT,       -- date the reminder went out; same rule
    snooze_until TEXT,       -- YYYY-MM-DDTHH:MM local, overrides at_time once
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS task_user_date ON task(user_id, on_date);

-- One row per browser/phone that allowed notifications.
CREATE TABLE IF NOT EXISTS push_sub (
    endpoint   TEXT PRIMARY KEY,
    keys       TEXT NOT NULL,      -- JSON {p256dh, auth} from the browser
    created_at TEXT NOT NULL
);

-- Server secrets generated on first run (VAPID key, notification signing key).
CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Columns added after the first release, applied to old and new databases alike.
# ponytail: add-column only. Enough until something needs a real migration tool.
_LATER_COLUMNS = [
    ("task", "days", "INTEGER NOT NULL DEFAULT 127"),   # weekday bits, Mon = 1
]

EVERY_DAY = 127

_EDITABLE = {"title", "tag_id", "daily", "on_date", "at_time", "done_on",
             "reminded_on", "snooze_until", "days"}


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # ON DELETE SET NULL needs this
    return conn


def init(conn: sqlite3.Connection) -> None:
    # WAL: the panel's request threads and the reminder thread read while one writes.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    for table, column, decl in _LATER_COLUMNS:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    conn.commit()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _iso(d) -> str | None:
    return d.isoformat() if isinstance(d, dt.date) else d


# --- users ------------------------------------------------------------------

def get_or_create_user(conn, user_id: int) -> sqlite3.Row:
    conn.execute("INSERT OR IGNORE INTO user (user_id, created_at) VALUES (?, ?)",
                 (user_id, _now()))
    conn.commit()
    return conn.execute("SELECT * FROM user WHERE user_id = ?", (user_id,)).fetchone()


def set_tz(conn, user_id: int, tz: str) -> None:
    conn.execute("UPDATE user SET tz = ? WHERE user_id = ?", (tz, user_id))
    conn.commit()


def user_now(user_row) -> dt.datetime:
    """Local wall-clock time, naive. Everything stored is in this frame."""
    return dt.datetime.now(ZoneInfo(user_row["tz"])).replace(tzinfo=None)


def all_users(conn):
    return conn.execute("SELECT * FROM user").fetchall()


# --- tasks ------------------------------------------------------------------

_SELECT = ("SELECT t.*, g.name AS tag_name FROM task t"
           " LEFT JOIN tag g ON g.id = t.tag_id")


def add_task(conn, user_id: int, title: str, tag_id: int | None, daily: bool,
             on_date, at_time: str | None, days: int = EVERY_DAY) -> int:
    cur = conn.execute(
        "INSERT INTO task (user_id, title, tag_id, daily, on_date, at_time, days, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, title, tag_id, int(daily), _iso(on_date), at_time, days, _now()))
    conn.commit()
    return cur.lastrowid


def get_task(conn, user_id: int, task_id: int):
    return conn.execute(_SELECT + " WHERE t.id = ? AND t.user_id = ?",
                        (task_id, user_id)).fetchone()


def update_task(conn, user_id: int, task_id: int, **fields) -> bool:
    unknown = set(fields) - _EDITABLE
    if unknown:
        raise ValueError(f"not editable: {sorted(unknown)}")
    if not fields:
        return False
    sets = ", ".join(f"{k} = ?" for k in fields)
    cur = conn.execute(f"UPDATE task SET {sets} WHERE id = ? AND user_id = ?",
                       (*map(_iso, fields.values()), task_id, user_id))
    conn.commit()
    return cur.rowcount > 0


def delete_task(conn, user_id: int, task_id: int) -> bool:
    cur = conn.execute("DELETE FROM task WHERE id = ? AND user_id = ?", (task_id, user_id))
    conn.commit()
    return cur.rowcount > 0


# Untimed tasks sort after timed ones within a day.
_ORDER = " ORDER BY t.at_time IS NULL, t.at_time, t.id"


def routine(conn, user_id: int, day=None):
    """The whole routine, or only what runs on `day`'s weekday."""
    mask = EVERY_DAY if day is None else 1 << day.weekday()
    return conn.execute(_SELECT + " WHERE t.user_id = ? AND t.daily = 1 AND t.days & ?"
                        + _ORDER, (user_id, mask)).fetchall()


def tasks_on(conn, user_id: int, day):
    """One-off tasks on that day, done or not."""
    return conn.execute(_SELECT + " WHERE t.user_id = ? AND t.daily = 0 AND t.on_date = ?"
                        + _ORDER, (user_id, _iso(day))).fetchall()


def overdue(conn, user_id: int, today):
    return conn.execute(
        _SELECT + " WHERE t.user_id = ? AND t.daily = 0 AND t.done_on IS NULL"
        " AND t.on_date < ? ORDER BY t.on_date, t.at_time IS NULL, t.at_time",
        (user_id, _iso(today))).fetchall()


def upcoming(conn, user_id: int, after, limit: int, offset: int = 0):
    """Open one-offs strictly after `after`, soonest first."""
    return conn.execute(
        _SELECT + " WHERE t.user_id = ? AND t.daily = 0 AND t.done_on IS NULL"
        " AND t.on_date > ? ORDER BY t.on_date, t.at_time IS NULL, t.at_time, t.id"
        " LIMIT ? OFFSET ?", (user_id, _iso(after), limit, offset)).fetchall()


def one_offs(conn, user_id: int, since):
    """Every open one-off, plus done ones from `since` on."""
    return conn.execute(
        _SELECT + " WHERE t.user_id = ? AND t.daily = 0 AND (t.done_on IS NULL OR t.on_date >= ?)"
        " ORDER BY t.on_date, t.at_time IS NULL, t.at_time, t.id",
        (user_id, _iso(since))).fetchall()


def count_upcoming(conn, user_id: int, after) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM task WHERE user_id = ? AND daily = 0"
        " AND done_on IS NULL AND on_date > ?", (user_id, _iso(after))).fetchone()[0]


def tasks_tagged(conn, user_id: int, tag_id: int, today):
    """Everything still live under a tag: its routine, every open one-off, and
    whatever was done today. Older done ones are history, not schedule."""
    return conn.execute(
        _SELECT + " WHERE t.user_id = ? AND t.tag_id = ?"
        " AND (t.daily = 1 OR t.done_on IS NULL OR t.on_date = ?)"
        " ORDER BY t.daily DESC, t.on_date, t.at_time IS NULL, t.at_time",
        (user_id, tag_id, _iso(today))).fetchall()


def reminder_candidates(conn, user_id: int):
    """Everything that could possibly need a reminder. parse.is_due decides.
    Reminded one-offs drop out here, so this stays small as history grows."""
    return conn.execute(
        _SELECT + " WHERE t.user_id = ? AND (t.snooze_until IS NOT NULL OR"
        " (t.at_time IS NOT NULL AND (t.daily = 1 OR"
        "  (t.reminded_on IS NULL AND t.done_on IS NULL))))", (user_id,)).fetchall()


# --- tags -------------------------------------------------------------------

def list_tags(conn, user_id: int):
    """With a count of what's still open under each, so the list means something."""
    return conn.execute(
        "SELECT g.*, (SELECT COUNT(*) FROM task t WHERE t.tag_id = g.id"
        "   AND (t.daily = 1 OR t.done_on IS NULL)) AS open"
        " FROM tag g WHERE g.user_id = ? ORDER BY g.name", (user_id,)).fetchall()


def get_tag(conn, user_id: int, tag_id: int):
    return conn.execute("SELECT * FROM tag WHERE id = ? AND user_id = ?",
                        (tag_id, user_id)).fetchone()


def create_tag(conn, user_id: int, name: str) -> int | None:
    """None means the name is already taken (compared case-insensitively)."""
    try:
        cur = conn.execute("INSERT INTO tag (user_id, name) VALUES (?, ?)",
                           (user_id, name.strip()))
    except sqlite3.IntegrityError:
        return None
    conn.commit()
    return cur.lastrowid


def get_or_create_tag(conn, user_id: int, name: str) -> int:
    row = conn.execute("SELECT id FROM tag WHERE user_id = ? AND name = ?",
                       (user_id, name.strip())).fetchone()
    return row["id"] if row else create_tag(conn, user_id, name)


def rename_tag(conn, user_id: int, tag_id: int, name: str) -> bool:
    try:
        cur = conn.execute("UPDATE tag SET name = ? WHERE id = ? AND user_id = ?",
                           (name.strip(), tag_id, user_id))
    except sqlite3.IntegrityError:
        return False
    conn.commit()
    return cur.rowcount > 0


def delete_tag(conn, user_id: int, tag_id: int) -> bool:
    """Tasks survive; they just lose the tag."""
    cur = conn.execute("DELETE FROM tag WHERE id = ? AND user_id = ?", (tag_id, user_id))
    conn.commit()
    return cur.rowcount > 0


# --- push subscriptions and server secrets ----------------------------------

def save_sub(conn, endpoint: str, keys: str) -> None:
    conn.execute("INSERT OR REPLACE INTO push_sub (endpoint, keys, created_at) VALUES (?, ?, ?)",
                 (endpoint, keys, _now()))
    conn.commit()


def drop_sub(conn, endpoint: str) -> None:
    conn.execute("DELETE FROM push_sub WHERE endpoint = ?", (endpoint,))
    conn.commit()


def subs(conn):
    return conn.execute("SELECT * FROM push_sub").fetchall()


def kv_get(conn, key: str, make=None) -> str | None:
    """The stored value; with `make`, generate and store it on first use."""
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    if row or make is None:
        return row and row["value"]
    conn.execute("INSERT OR IGNORE INTO kv (key, value) VALUES (?, ?)", (key, make()))
    conn.commit()
    return kv_get(conn, key)
