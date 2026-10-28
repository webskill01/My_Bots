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

-- Web panel logins. Same shape as the schedule panel's, so its account
-- queries (imported below) work on this database unchanged.
CREATE TABLE IF NOT EXISTS session (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES user(user_id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invite (
    token      TEXT PRIMARY KEY,
    label      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_by    INTEGER REFERENCES user(user_id),
    claim_user INTEGER REFERENCES user(user_id)
);

-- Bank alert emails that looked like money but matched no known format.
CREATE TABLE IF NOT EXISTS bank_miss (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES user(user_id),
    subject     TEXT NOT NULL DEFAULT '',
    body        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
"""

# Columns added after the first release. Listed here rather than in SCHEMA so
# there is one source of truth: a fresh database and an existing one on disk
# both get them through the same ALTER.
# ponytail: add-column only. Enough until something needs a real migration tool.
_LATER_COLUMNS = [
    ("user", "budget", "INTEGER NOT NULL DEFAULT 0"),   # paise/month, 0 = off
    ("user", "alert_month", "TEXT"),                    # 'YYYY-MM' last alerted
    ("user", "alert_level", "INTEGER NOT NULL DEFAULT 0"),
    ("user", "name", "TEXT"),                           # panel login; NULL = never logged in
    ("user", "pw_hash", "TEXT"),                        # NULL for the admin (env PIN)
    ("user", "is_admin", "INTEGER NOT NULL DEFAULT 0"),
    ("user", "disabled", "INTEGER NOT NULL DEFAULT 0"),
    ("user", "bank_balance", "INTEGER"),                # paise, from the newest bank alert
    ("user", "bank_balance_at", "TEXT"),
    ("user", "bank_uid", "INTEGER"),                    # last IMAP UID read; NULL = never started
    ("entry", "bank_ref", "TEXT"),                      # UPI ref / UTR when a bank alert filed it
    ("category", "budget", "INTEGER NOT NULL DEFAULT 0"),   # paise/month, 0 = off
]

_SETTINGS = {"tz", "currency", "budget"}
_EDITABLE = {"kind", "amount", "name", "category_id", "on_date"}

ANY_CATEGORY = object()  # distinct from None, which means "uncategorized"


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # ON DELETE SET NULL needs this
    return conn


def init(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode = WAL")   # the panel's threads read while one writes
    conn.executescript(SCHEMA)
    for table, column, decl in _LATER_COLUMNS:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS user_name ON user(name COLLATE NOCASE)"
                 " WHERE name IS NOT NULL")
    # one entry per bank transaction, however often its alert is read
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS entry_bank_ref ON entry(user_id, bank_ref)"
                 " WHERE bank_ref IS NOT NULL")
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


def add_bank_entry(conn, user_id: int, kind: str, amount: int, name: str,
                   category_id: int | None, on_date, bank_ref: str) -> int | None:
    """None when this transaction is already in the ledger."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO entry (user_id, kind, amount, name, category_id, on_date,"
        " created_at, bank_ref) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, kind, amount, name, category_id, _iso(on_date), _now(), bank_ref))
    conn.commit()
    return cur.lastrowid if cur.rowcount else None


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


def count_entries(conn, user_id: int, start, end, category_id=ANY_CATEGORY,
                  kind: str | None = None) -> int:
    sql = "SELECT COUNT(*) FROM entry WHERE user_id = ? AND on_date BETWEEN ? AND ?"
    args = [user_id, _iso(start), _iso(end)]
    if category_id is not ANY_CATEGORY:
        sql += " AND category_id IS ?"
        args.append(category_id)
    if kind:
        sql += " AND kind = ?"
        args.append(kind)
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


def set_category_budget(conn, user_id: int, category_id: int, budget: int) -> bool:
    cur = conn.execute("UPDATE category SET budget = ? WHERE id = ? AND user_id = ?",
                       (budget, category_id, user_id))
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


def category_totals(conn, user_id: int, start, end, kind: str = "exp"):
    """One kind at a time, so spending and earning never net off each other
    inside a category. The uncategorized bucket comes last, with a NULL name."""
    return conn.execute(
        "SELECT c.id AS category_id, c.name AS name,"
        "       SUM(e.amount) AS total, COUNT(*) AS count"
        " FROM entry e LEFT JOIN category c ON c.id = e.category_id"
        " WHERE e.user_id = ? AND e.kind = ? AND e.on_date BETWEEN ? AND ?"
        " GROUP BY e.category_id"
        " ORDER BY (c.name IS NULL), total DESC",
        (user_id, kind, _iso(start), _iso(end))).fetchall()


def month_totals(conn, user_id: int):
    """Spent / earned per calendar month, newest first: the month-by-month view."""
    return conn.execute(
        "SELECT substr(on_date, 1, 7) AS month,"
        "       COALESCE(SUM(CASE WHEN kind = 'exp'  THEN amount END), 0) AS spent,"
        "       COALESCE(SUM(CASE WHEN kind = 'earn' THEN amount END), 0) AS earned,"
        "       COUNT(*) AS count"
        " FROM entry WHERE user_id = ? GROUP BY month ORDER BY month DESC",
        (user_id,)).fetchall()


def category_counts(conn, user_id: int):
    """Every category with how many entries it holds, all time."""
    return conn.execute(
        "SELECT c.id, c.name, c.budget, COUNT(e.id) AS count FROM category c"
        " LEFT JOIN entry e ON e.category_id = c.id"
        " WHERE c.user_id = ? GROUP BY c.id ORDER BY c.name", (user_id,)).fetchall()


def taxi_pool(conn, user_id: int, received: str, refund: str, split: str) -> dict:
    """All time, by category: what came in, what was refunded, what went to the
    partner. The partner's half is of what's left after refunds."""
    got = {(r["name"].lower(), r["kind"]): r for r in conn.execute(
        "SELECT c.name AS name, e.kind AS kind, COUNT(*) AS n, SUM(e.amount) AS total"
        " FROM entry e JOIN category c ON c.id = e.category_id"
        " WHERE e.user_id = ? AND c.name IN (?, ?, ?) GROUP BY c.id, e.kind",
        (user_id, received, refund, split))}
    pick = lambda name, kind: got.get((name.lower(), kind)) or {"n": 0, "total": 0}
    r, f, s = pick(received, "earn"), pick(refund, "exp"), pick(split, "exp")
    half = (r["total"] - f["total"]) // 2
    return {"received": r["total"], "received_n": r["n"], "refunded": f["total"],
            "refunded_n": f["n"], "sent": s["total"], "sent_n": s["n"],
            "partner_half": half, "owed": half - s["total"]}


def salary_status(conn, user_id: int, salary: str, exclude_like: str = "taxi bot%") -> dict | None:
    """The latest salary and what has been spent since the day it landed.
    Taxi bot money moves through the same account but isn't salary money."""
    pay = conn.execute(
        "SELECT e.on_date, SUM(e.amount) AS amount FROM entry e"
        " JOIN category c ON c.id = e.category_id"
        " WHERE e.user_id = ? AND e.kind = 'earn' AND c.name = ?"
        " GROUP BY e.on_date ORDER BY e.on_date DESC LIMIT 1", (user_id, salary)).fetchone()
    if pay is None:
        return None
    spent = conn.execute(
        "SELECT COALESCE(SUM(e.amount), 0) FROM entry e LEFT JOIN category c ON c.id = e.category_id"
        " WHERE e.user_id = ? AND e.kind = 'exp' AND e.on_date >= ?"
        " AND (c.name IS NULL OR c.name NOT LIKE ?)",
        (user_id, pay["on_date"], exclude_like)).fetchone()[0]
    return {"on_date": pay["on_date"], "amount": pay["amount"], "spent": spent,
            "left": pay["amount"] - spent}


# --- bank sync --------------------------------------------------------------

def set_bank_uid(conn, user_id: int, uid: int) -> None:
    conn.execute("UPDATE user SET bank_uid = ? WHERE user_id = ?", (uid, user_id))
    conn.commit()


def set_bank_balance(conn, user_id: int, balance: int) -> None:
    conn.execute("UPDATE user SET bank_balance = ?, bank_balance_at = ? WHERE user_id = ?",
                 (balance, _now(), user_id))
    conn.commit()


def add_bank_miss(conn, user_id: int, subject: str, body: str) -> None:
    conn.execute("INSERT INTO bank_miss (user_id, subject, body, created_at) VALUES (?, ?, ?, ?)",
                 (user_id, subject, body, _now()))
    conn.commit()


def bank_misses(conn, user_id: int):
    return conn.execute("SELECT * FROM bank_miss WHERE user_id = ? ORDER BY id",
                        (user_id,)).fetchall()


def drop_bank_miss(conn, user_id: int, miss_id: int) -> bool:
    cur = conn.execute("DELETE FROM bank_miss WHERE id = ? AND user_id = ?", (miss_id, user_id))
    conn.commit()
    return cur.rowcount > 0


def record_alert(conn, user_id: int, month: str, level: int) -> None:
    """Remember that we already warned this user, so one budget crossing
    produces one message rather than one per entry."""
    conn.execute("UPDATE user SET alert_month = ?, alert_level = ? WHERE user_id = ?",
                 (month, level, user_id))
    conn.commit()


# --- panel accounts ---------------------------------------------------------
# Sessions, invites, names and passwords live in the same tables the schedule
# panel uses, so its tested queries run here as-is. Only the ones that count
# rows (people, unclaimed) or touch push devices are finance's own.
from schedule_bot.db import (add_invite, add_session, delete_invite, drop_session,  # noqa: E402
                             get_user, invites, join, make_admin, open_invite,
                             rename_user, session_user, set_password, user_by_name)


def set_disabled(conn, user_id: int, disabled: bool) -> bool:
    """The admin can't be disabled: that would lock everyone out of admin."""
    cur = conn.execute("UPDATE user SET disabled = ? WHERE user_id = ? AND is_admin = 0",
                       (int(disabled), user_id))
    if disabled:
        conn.execute("DELETE FROM session WHERE user_id = ?", (user_id,))
    conn.commit()
    return cur.rowcount > 0


def people(conn):
    """Everyone with a login, for the admin's list. Counts only, never money."""
    return conn.execute(
        "SELECT u.user_id, u.name, u.is_admin, u.disabled, u.created_at,"
        " (SELECT COUNT(*) FROM entry e WHERE e.user_id = u.user_id) AS entries"
        " FROM user u WHERE u.name IS NOT NULL ORDER BY u.is_admin DESC, u.created_at").fetchall()


def unclaimed(conn):
    """Telegram-era ledgers with no login yet, waiting for a claim link."""
    return conn.execute(
        "SELECT u.user_id, u.created_at,"
        " (SELECT COUNT(*) FROM entry e WHERE e.user_id = u.user_id) AS entries"
        " FROM user u WHERE u.name IS NULL AND u.is_admin = 0 AND u.disabled = 0"
        " ORDER BY u.created_at").fetchall()
