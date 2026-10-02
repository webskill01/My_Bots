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

-- A logged-in browser. Only the token's hash is stored: a leaked database
-- doesn't hand out live logins.
CREATE TABLE IF NOT EXISTS session (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES user(user_id),
    created_at TEXT NOT NULL
);

-- One-time join links the admin hands out.
CREATE TABLE IF NOT EXISTS invite (
    token      TEXT PRIMARY KEY,
    label      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,          -- UTC ISO
    used_by    INTEGER REFERENCES user(user_id)
);
"""

# Columns added after the first release, applied to old and new databases alike.
# ponytail: add-column only. Enough until something needs a real migration tool.
_LATER_COLUMNS = [
    ("task", "days", "INTEGER NOT NULL DEFAULT 127"),   # weekday bits, Mon = 1
    ("user", "name", "TEXT"),                           # login name; NULL = never logged in
    ("user", "pw_hash", "TEXT"),                        # NULL for the admin (env PIN)
    ("user", "is_admin", "INTEGER NOT NULL DEFAULT 0"),
    ("user", "disabled", "INTEGER NOT NULL DEFAULT 0"),
    ("push_sub", "user_id", "INTEGER REFERENCES user(user_id)"),  # whose reminders
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
    # ALTER can't add UNIQUE, an index can. Partial: many users have no name yet.
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS user_name ON user(name COLLATE NOCASE)"
                 " WHERE name IS NOT NULL")
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

def save_sub(conn, user_id: int, endpoint: str, keys: str) -> None:
    """A phone belongs to whoever enabled reminders on it last: a shared phone
    that switches accounts moves over instead of ringing for both."""
    conn.execute("INSERT OR REPLACE INTO push_sub (endpoint, keys, user_id, created_at)"
                 " VALUES (?, ?, ?, ?)", (endpoint, keys, user_id, _now()))
    conn.commit()


def drop_sub(conn, endpoint: str, user_id: int | None = None) -> None:
    """With user_id, only that user's own device (a logout); without, any (gone)."""
    if user_id is None:
        conn.execute("DELETE FROM push_sub WHERE endpoint = ?", (endpoint,))
    else:
        conn.execute("DELETE FROM push_sub WHERE endpoint = ? AND user_id = ?", (endpoint, user_id))
    conn.commit()


def subs(conn, user_id: int):
    return conn.execute("SELECT * FROM push_sub WHERE user_id = ?", (user_id,)).fetchall()


def adopt_orphan_subs(conn, user_id: int) -> None:
    """Subscriptions from before accounts existed belong to the admin."""
    conn.execute("UPDATE push_sub SET user_id = ? WHERE user_id IS NULL", (user_id,))
    conn.commit()


def task_owner(conn, task_id: int) -> int | None:
    """Only for notification buttons, which carry a per-task signature instead
    of a login. Everything else goes through user-scoped queries."""
    row = conn.execute("SELECT user_id FROM task WHERE id = ?", (task_id,)).fetchone()
    return row and row["user_id"]


# --- accounts, sessions, invites --------------------------------------------

def make_admin(conn, user_id: int, name: str) -> None:
    conn.execute("INSERT OR IGNORE INTO user (user_id, created_at) VALUES (?, ?)", (user_id, _now()))
    conn.execute("UPDATE user SET is_admin = 1, name = ?, disabled = 0 WHERE user_id = ?",
                 (name, user_id))
    conn.commit()


def user_by_name(conn, name: str):
    return conn.execute("SELECT * FROM user WHERE name = ? COLLATE NOCASE", (name.strip(),)).fetchone()


def get_user(conn, user_id: int):
    return conn.execute("SELECT * FROM user WHERE user_id = ?", (user_id,)).fetchone()


def set_password(conn, user_id: int, pw_hash: str) -> None:
    conn.execute("UPDATE user SET pw_hash = ? WHERE user_id = ?", (pw_hash, user_id))
    conn.commit()


def set_disabled(conn, user_id: int, disabled: bool) -> bool:
    """The admin can't be disabled: that would lock everyone out of admin."""
    cur = conn.execute("UPDATE user SET disabled = ? WHERE user_id = ? AND is_admin = 0",
                       (int(disabled), user_id))
    if disabled:
        conn.execute("DELETE FROM session WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM push_sub WHERE user_id = ?", (user_id,))
    conn.commit()
    return cur.rowcount > 0


def people(conn):
    """Everyone with a login, for the admin's list. Counts only, never tasks."""
    return conn.execute(
        "SELECT u.user_id, u.name, u.is_admin, u.disabled, u.created_at,"
        " (SELECT COUNT(*) FROM task t WHERE t.user_id = u.user_id) AS tasks,"
        " (SELECT COUNT(*) FROM push_sub p WHERE p.user_id = u.user_id) AS devices"
        " FROM user u WHERE u.name IS NOT NULL ORDER BY u.is_admin DESC, u.created_at").fetchall()


def active_users(conn):
    return conn.execute("SELECT * FROM user WHERE disabled = 0").fetchall()


def add_session(conn, user_id: int, token_hash: str) -> None:
    conn.execute("INSERT INTO session (token_hash, user_id, created_at) VALUES (?, ?, ?)",
                 (token_hash, user_id, _now()))
    conn.commit()


def session_user(conn, token_hash: str):
    return conn.execute(
        "SELECT u.* FROM session s JOIN user u ON u.user_id = s.user_id"
        " WHERE s.token_hash = ? AND u.disabled = 0", (token_hash,)).fetchone()


def drop_session(conn, token_hash: str) -> None:
    conn.execute("DELETE FROM session WHERE token_hash = ?", (token_hash,))
    conn.commit()


def add_invite(conn, token: str, label: str, expires_at: str) -> None:
    conn.execute("INSERT INTO invite (token, label, created_at, expires_at) VALUES (?, ?, ?, ?)",
                 (token, label, _now(), expires_at))
    conn.commit()


def open_invite(conn, token: str):
    """The invite, if it can still be used."""
    return conn.execute("SELECT * FROM invite WHERE token = ? AND used_by IS NULL AND expires_at > ?",
                        (token, _now())).fetchone()


def join(conn, token: str, name: str, pw_hash: str, tz: str = "Asia/Kolkata") -> int | None:
    """Spend the invite and create the account, all or nothing. None: the
    invite is gone/used/expired, or the name is taken."""
    # Write lock first, so two people opening the same link at once can't
    # both pass the "still unused?" check.
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        if not conn.execute("SELECT 1 FROM invite WHERE token = ? AND used_by IS NULL"
                            " AND expires_at > ?", (token, _now())).fetchone():
            conn.rollback()
            return None
        cur = conn.execute("INSERT INTO user (tz, created_at, name, pw_hash) VALUES (?, ?, ?, ?)",
                           (tz, _now(), name.strip(), pw_hash))
        conn.execute("UPDATE invite SET used_by = ? WHERE token = ?", (cur.lastrowid, token))
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:   # name taken
        conn.rollback()
        return None


def invites(conn):
    """Unused ones first; used ones show who joined."""
    return conn.execute(
        "SELECT i.*, u.name AS joined_name FROM invite i LEFT JOIN user u ON u.user_id = i.used_by"
        " ORDER BY i.used_by IS NOT NULL, i.created_at DESC LIMIT 50").fetchall()


def delete_invite(conn, token: str) -> bool:
    """Only an unused invite can be revoked; a used one is the join record."""
    cur = conn.execute("DELETE FROM invite WHERE token = ? AND used_by IS NULL", (token,))
    conn.commit()
    return cur.rowcount > 0


def kv_get(conn, key: str, make=None) -> str | None:
    """The stored value; with `make`, generate and store it on first use."""
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    if row or make is None:
        return row and row["value"]
    conn.execute("INSERT OR IGNORE INTO kv (key, value) VALUES (?, ?)", (key, make()))
    conn.commit()
    return kv_get(conn, key)
