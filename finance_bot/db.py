"""Storage. Every function takes user_id first — tenancy is enforced here, not
in the handlers. If a query does not carry user_id, that query is a bug."""

import datetime as dt
import sqlite3
from zoneinfo import ZoneInfo

SCHEMA = """
CREATE TABLE IF NOT EXISTS user (
    user_id    INTEGER PRIMARY KEY,
    tz         TEXT NOT NULL DEFAULT 'Asia/Kolkata',
    currency   TEXT NOT NULL DEFAULT '₹',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS category (
    id      INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user(user_id),
    name    TEXT NOT NULL COLLATE NOCASE,
    UNIQUE (user_id, name)
);

CREATE TABLE IF NOT EXISTS entry (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES user(user_id),
    kind        TEXT NOT NULL CHECK (kind IN ('exp', 'earn')),
    amount      INTEGER NOT NULL CHECK (amount > 0),   -- paise, never a float
    name        TEXT NOT NULL DEFAULT '',
    category_id INTEGER REFERENCES category(id) ON DELETE SET NULL,
    on_date     TEXT NOT NULL,   -- YYYY-MM-DD, already in the user's timezone
    created_at  TEXT NOT NULL    -- UTC, when it was actually filed
);

CREATE INDEX IF NOT EXISTS entry_user_date ON entry(user_id, on_date);
"""

# Columns added after the first release. Listed here rather than in SCHEMA so
# there is one source of truth: a fresh database and an existing one on disk
# both get them through the same ALTER.
# ponytail: add-column only. Enough until something needs a real migration tool.
_LATER_COLUMNS = [
    ("user", "budget", "INTEGER NOT NULL DEFAULT 0"),   # paise/month, 0 = off
    ("user", "alert_month", "TEXT"),                    # 'YYYY-MM' last alerted
    ("user", "alert_level", "INTEGER NOT NULL DEFAULT 0"),
]

_SETTINGS = {"tz", "currency", "budget"}
_EDITABLE = {"kind", "amount", "name", "category_id", "on_date"}

ANY_CATEGORY = object()  # distinct from None, which means "uncategorized"


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # ON DELETE SET NULL needs this
    return conn


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table, column, decl in _LATER_COLUMNS:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    conn.commit()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _iso(d) -> str:
    return d.isoformat() if isinstance(d, dt.date) else str(d)


# --- users ------------------------------------------------------------------

def get_or_create_user(conn, user_id: int) -> sqlite3.Row:
    conn.execute("INSERT OR IGNORE INTO user (user_id, created_at) VALUES (?, ?)",
                 (user_id, _now()))
    conn.commit()
    return conn.execute("SELECT * FROM user WHERE user_id = ?", (user_id,)).fetchone()


def set_setting(conn, user_id: int, key: str, value: str) -> None:
    if key not in _SETTINGS:
        raise ValueError(f"not a setting: {key}")
    conn.execute(f"UPDATE user SET {key} = ? WHERE user_id = ?", (value, user_id))
    conn.commit()


def user_today(user_row) -> dt.date:
    return dt.datetime.now(ZoneInfo(user_row["tz"])).date()


# --- entries ----------------------------------------------------------------

def add_entry(conn, user_id: int, kind: str, amount: int, name: str,
              category_id: int | None, on_date) -> int:
    cur = conn.execute(
        "INSERT INTO entry (user_id, kind, amount, name, category_id, on_date, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, kind, amount, name, category_id, _iso(on_date), _now()))
    conn.commit()
    return cur.lastrowid


def get_entry(conn, user_id: int, entry_id: int):
    return conn.execute(
        "SELECT e.*, c.name AS category_name FROM entry e"
        " LEFT JOIN category c ON c.id = e.category_id"
        " WHERE e.id = ? AND e.user_id = ?", (entry_id, user_id)).fetchone()


def update_entry(conn, user_id: int, entry_id: int, **fields) -> bool:
    unknown = set(fields) - _EDITABLE
    if unknown:
        raise ValueError(f"not editable: {sorted(unknown)}")
    if not fields:
        return False
    values = [_iso(v) if k == "on_date" else v for k, v in fields.items()]
    sets = ", ".join(f"{k} = ?" for k in fields)
    cur = conn.execute(f"UPDATE entry SET {sets} WHERE id = ? AND user_id = ?",
                       (*values, entry_id, user_id))
    conn.commit()
    return cur.rowcount > 0


def delete_entry(conn, user_id: int, entry_id: int) -> bool:
    cur = conn.execute("DELETE FROM entry WHERE id = ? AND user_id = ?",
                       (entry_id, user_id))
    conn.commit()
    return cur.rowcount > 0


def list_entries(conn, user_id: int, start, end, limit: int | None = None,
                 offset: int = 0, category_id=ANY_CATEGORY, kind: str | None = None):
    sql = ("SELECT e.*, c.name AS category_name FROM entry e"
           " LEFT JOIN category c ON c.id = e.category_id"
           " WHERE e.user_id = ? AND e.on_date BETWEEN ? AND ?")
    args = [user_id, _iso(start), _iso(end)]
    if category_id is not ANY_CATEGORY:
        sql += " AND e.category_id IS ?"
        args.append(category_id)
    if kind:
        sql += " AND e.kind = ?"
        args.append(kind)
    sql += " ORDER BY e.on_date DESC, e.id DESC"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        args += [limit, offset]
    return conn.execute(sql, args).fetchall()


def count_entries(conn, user_id: int, start, end, category_id=ANY_CATEGORY) -> int:
    sql = "SELECT COUNT(*) FROM entry WHERE user_id = ? AND on_date BETWEEN ? AND ?"
    args = [user_id, _iso(start), _iso(end)]
    if category_id is not ANY_CATEGORY:
        sql += " AND category_id IS ?"
        args.append(category_id)
    return conn.execute(sql, args).fetchone()[0]


# --- categories -------------------------------------------------------------

def list_categories(conn, user_id: int):
    return conn.execute(
        "SELECT * FROM category WHERE user_id = ? ORDER BY name", (user_id,)).fetchall()


def find_category(conn, user_id: int, name: str):
    return conn.execute("SELECT * FROM category WHERE user_id = ? AND name = ?",
                        (user_id, name.strip())).fetchone()


def create_category(conn, user_id: int, name: str) -> int | None:
    """None means the name is already taken (compared case-insensitively)."""
    try:
        cur = conn.execute("INSERT INTO category (user_id, name) VALUES (?, ?)",
                           (user_id, name.strip()))
    except sqlite3.IntegrityError:
        return None
    conn.commit()
    return cur.lastrowid


def get_or_create_category(conn, user_id: int, name: str) -> int:
    """For the inline #tag path, which must not fail on an existing name."""
    row = find_category(conn, user_id, name)
    return row["id"] if row else create_category(conn, user_id, name)


def rename_category(conn, user_id: int, category_id: int, name: str) -> bool:
    try:
        cur = conn.execute("UPDATE category SET name = ? WHERE id = ? AND user_id = ?",
                           (name.strip(), category_id, user_id))
    except sqlite3.IntegrityError:
        return False  # that name is already taken
    conn.commit()
    return cur.rowcount > 0


def delete_category(conn, user_id: int, category_id: int) -> bool:
    """Entries survive; they just become uncategorized."""
    cur = conn.execute("DELETE FROM category WHERE id = ? AND user_id = ?",
                       (category_id, user_id))
    conn.commit()
    return cur.rowcount > 0


# --- reports ----------------------------------------------------------------

def summary(conn, user_id: int, start, end) -> dict:
    args = (user_id, _iso(start), _iso(end))
    row = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN kind = 'exp'  THEN amount END), 0) AS spent,"
        "       COALESCE(SUM(CASE WHEN kind = 'earn' THEN amount END), 0) AS earned,"
        "       COUNT(*) AS count"
        " FROM entry WHERE user_id = ? AND on_date BETWEEN ? AND ?", args).fetchone()
    top = conn.execute(
        "SELECT name, SUM(amount) AS total FROM entry"
        " WHERE user_id = ? AND kind = 'exp' AND on_date BETWEEN ? AND ?"
        " GROUP BY name COLLATE NOCASE ORDER BY total DESC LIMIT 3", args).fetchall()
    return {"spent": row["spent"], "earned": row["earned"],
            "net": row["earned"] - row["spent"], "count": row["count"], "top": top}


def day_report(conn, user_id: int, on_date) -> dict:
    entries = list_entries(conn, user_id, on_date, on_date)
    spent = sum(e["amount"] for e in entries if e["kind"] == "exp")
    earned = sum(e["amount"] for e in entries if e["kind"] == "earn")
    return {"spent": spent, "earned": earned, "net": earned - spent, "entries": entries}


def category_totals(conn, user_id: int, start, end):
    """Expenses only — an earning has no category to spend from.
    The uncategorized bucket comes last, with a NULL name."""
    return conn.execute(
        "SELECT c.id AS category_id, c.name AS name,"
        "       SUM(e.amount) AS total, COUNT(*) AS count"
        " FROM entry e LEFT JOIN category c ON c.id = e.category_id"
        " WHERE e.user_id = ? AND e.kind = 'exp' AND e.on_date BETWEEN ? AND ?"
        " GROUP BY e.category_id"
        " ORDER BY (c.name IS NULL), total DESC",
        (user_id, _iso(start), _iso(end))).fetchall()


def record_alert(conn, user_id: int, month: str, level: int) -> None:
    """Remember that we already warned this user, so one budget crossing
    produces one message rather than one per entry."""
    conn.execute("UPDATE user SET alert_month = ?, alert_level = ? WHERE user_id = ?",
                 (month, level, user_id))
    conn.commit()
