"""Web panel, one private ledger per person. Replaces the Telegram bot.

A stdlib HTTP server (API + static files). Accounts work exactly like the
schedule panel's: the admin logs in as FINANCE_ADMIN_NAME (default "admin")
with FINANCE_PIN until they set their own password; everyone else joins
through a one-time invite link. Telegram-era ledgers are handed over with a
claim link, so nobody loses their history.

Env: FINANCE_PIN (6+ chars; falls back to SCHEDULE_PIN), FINANCE_PORT
(default 8098), DB_PATH (default finance.db), FINANCE_ADMIN_NAME,
FINANCE_USER_ID (which existing ledger is the admin's; default the oldest).
"""

import calendar
import datetime as dt
import hmac
import json
import logging
import os
import re
import secrets
import sys
import time
import urllib.parse
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo, available_timezones

# Same login machinery as the schedule panel: one implementation to trust.
from schedule_bot.panel import _JOIN, _NAME, _cookie, _token_hash, check_pw, hash_pw, valid_password

from . import db, parse

log = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent / "web"
STATIC = {  # path -> (file, content type)
    "/": ("panel.html", "text/html; charset=utf-8"),
    "/panel.js": ("panel.js", "text/javascript; charset=utf-8"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/icon-192.png": ("icon-192.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
}
INVITE_DAYS = 7
SESSION_MAX_AGE = 365 * 86400
MAX_AMOUNT = 100_000_000_00      # ₹10 crore in paise: anything bigger is a typo
MAX_ITEMS = 30                   # per multi-item save
RECENT_DAYS = 90                 # how far back "recent items" look
FUTURE_DAYS = 7                  # an entry may sit this far ahead (a bill due soon)

AUTH = {"pin": "", "admin": "admin"}
CFG = {"db": "", "admin_uid": 0}
FAILS: dict[str, list[float]] = {}   # client IP -> wrong-login timestamps

_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _conn():
    return db.connect(CFG["db"])


# --- logins -----------------------------------------------------------------

def pin_ok(password: str) -> bool:
    return bool(AUTH["pin"]) and hmac.compare_digest(password.encode(), AUTH["pin"].encode())


def check_login(conn, name: str, password: str):
    """The user row, or None. Until the admin sets their own password,
    "admin" (or a blank name) + the PIN gets them in; after that it doesn't."""
    name = " ".join(name.split())
    user = db.user_by_name(conn, name) if name else None
    if user is not None and user["pw_hash"]:
        if user["disabled"]:
            return None
        return user if check_pw(password, user["pw_hash"]) else None
    admin = db.get_user(conn, CFG["admin_uid"])
    if (not name or name.lower() == AUTH["admin"].lower()) and admin and not admin["pw_hash"]:
        return admin if pin_ok(password) else None
    check_pw(password, hash_pw("x"))   # same work either way: no name probing by timing
    return None


def new_session(conn, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    db.add_session(conn, user_id, _token_hash(token))
    return token


# --- shapes -----------------------------------------------------------------

def entry_json(e, tz: str) -> dict:
    """`time` is when it was filed, on the user's clock: "14:05"."""
    filed = dt.datetime.fromisoformat(e["created_at"])
    if filed.tzinfo is None:   # legacy naive stamps are UTC
        filed = filed.replace(tzinfo=dt.timezone.utc)
    return {"id": e["id"], "kind": e["kind"], "amount": e["amount"], "name": e["name"],
            "category": e["category_name"], "category_id": e["category_id"],
            "on_date": e["on_date"], "time": filed.astimezone(ZoneInfo(tz)).strftime("%H:%M")}


def recent_items(conn, uid: int, today: dt.date, tz: str, limit: int = 10) -> list[dict]:
    """What this person logs most often lately (chai, uber, rent), each with
    its last amount and category: one tap in the form fills a row."""
    seen: dict[tuple, dict] = {}
    for e in db.list_entries(conn, uid, today - dt.timedelta(days=RECENT_DAYS), today):
        if not e["name"]:
            continue
        key = (e["kind"], e["name"].lower())
        if key in seen:
            seen[key]["n"] += 1
        else:   # newest first, so the first one seen carries the latest amount
            seen[key] = {"kind": e["kind"], "name": e["name"], "amount": e["amount"],
                         "category": e["category_name"], "n": 1}
    return sorted(seen.values(), key=lambda x: -x["n"])[:limit]


def month_bounds(month: str) -> tuple[dt.date, dt.date]:
    y, m = map(int, month.split("-"))
    return dt.date(y, m, 1), dt.date(y, m, calendar.monthrange(y, m)[1])


def state(conn, user, month: str | None) -> dict:
    """One month of one user's ledger, plus the month-by-month totals. A month
    of personal entries is small: the client does the sums and charts."""
    uid, today = user["user_id"], db.user_today(user)
    month = month if month and _MONTH.fullmatch(month) else today.strftime("%Y-%m")
    start, end = month_bounds(month)
    return {
        "today": today.isoformat(),
        "month": month,
        "tz": user["tz"],
        "currency": user["currency"],
        "budget": user["budget"],
        "me": {"name": user["name"], "admin": bool(user["is_admin"]),
               "has_password": bool(user["pw_hash"])},
        "entries": [entry_json(e, user["tz"]) for e in db.list_entries(conn, uid, start, end)],
        "months": [dict(m) for m in db.month_totals(conn, uid)],
        "categories": [dict(c) for c in db.category_counts(conn, uid)],
        "recent": recent_items(conn, uid, today, user["tz"]),
    }


def admin_state(conn) -> dict:
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    return {
        "people": [dict(p) for p in db.people(conn)],
        "invites": [{"token": i["token"], "label": i["label"], "created_at": i["created_at"],
                     "expires_at": i["expires_at"], "joined": i["joined_name"],
                     "claim": i["claim_user"],
                     "expired": not i["used_by"] and i["expires_at"] <= now}
                    for i in db.invites(conn)],
        "unclaimed": [dict(u) for u in db.unclaimed(conn)],
    }


# --- validation: panel input -> entry columns -------------------------------

def _category_id(conn, uid, name) -> int | None:
    name = " ".join(str(name or "").lstrip("#").split())[:32]
    return db.get_or_create_category(conn, uid, name) if name else None


def _amount(raw) -> int:
    amount = parse.parse_amount(str(raw or ""))
    if not amount:
        raise ValueError("Amount must be a number like 250 or 250.50")
    if amount > MAX_AMOUNT:
        raise ValueError("That amount looks too big")
    return amount


def _on_date(raw, today: dt.date) -> dt.date:
    s = str(raw or "")
    if not _DATE.fullmatch(s):
        raise ValueError("Pick a date")
    d = dt.date.fromisoformat(s)   # 2026-02-31 raises ValueError
    if d > today + dt.timedelta(days=FUTURE_DAYS):
        raise ValueError("That date is too far ahead")
    if d.year < 2000:
        raise ValueError("That date is too far back")
    return d


def fields_from(conn, uid, b: dict, today: dt.date) -> dict:
    """Validated columns from the add/edit form. Raises ValueError with a
    message fit to show the user."""
    kind = b.get("kind")
    if kind not in ("exp", "earn"):
        raise ValueError("Pick spent or earned")
    return {"kind": kind, "amount": _amount(b.get("amount")),
            "name": " ".join(str(b.get("name") or "").split())[:100],
            "category_id": _category_id(conn, uid, b.get("category")),
            "on_date": _on_date(b.get("on_date"), today)}


# --- HTTP -------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet: pm2 logs only trouble
        pass

    def send(self, code, body=b"", ctype="application/json", headers=()):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    @property
    def https(self) -> bool:
        return self.headers.get("X-Forwarded-Proto") == "https"

    def ip(self) -> str:
        # Bound to 127.0.0.1, so every request came through nginx + Cloudflare.
        return (self.headers.get("CF-Connecting-IP")
                or (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
                or self.client_address[0])

    def token(self) -> str:
        c = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return c["s"].value if "s" in c else ""

    def user(self, conn):
        t = self.token()
        return db.session_user(conn, _token_hash(t)) if t else None

    def body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 20_000:
            raise ValueError("body too large")
        b = json.loads(self.rfile.read(n) or b"{}")
        if not isinstance(b, dict):
            raise ValueError("expected an object")
        return b

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        path = url.path
        if path in STATIC or _JOIN.fullmatch(path):   # /join/<token> is the page; JS takes over
            name, ctype = STATIC.get(path, STATIC["/"])
            return self.send(200, (HERE / name).read_bytes(), ctype)
        conn = _conn()
        try:
            if m := re.fullmatch(r"/api/invite/([\w\-]{20,64})", path):
                inv = db.open_invite(conn, m[1])
                claim = inv and inv["claim_user"] and conn.execute(
                    "SELECT COUNT(*) FROM entry WHERE user_id = ?", (inv["claim_user"],)).fetchone()[0]
                return self.send(200, {"label": inv["label"], "claim_entries": claim or 0}) if inv else \
                    self.send(404, {"error": "This invite link was already used or has expired."})
            user = self.user(conn)
            if user is None:
                return self.send(401, {"error": "login"})
            if path == "/api/state":
                month = urllib.parse.parse_qs(url.query).get("month", [None])[0]
                return self.send(200, state(conn, user, month))
            if path == "/api/admin":
                return self.send(200, admin_state(conn)) if user["is_admin"] else \
                    self.send(403, {"error": "admin only"})
            self.send(404, {"error": "not found"})
        finally:
            conn.close()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            b = self.body()
        except ValueError:
            return self.send(400, {"error": "bad request"})
        conn = _conn()
        try:
            if path == "/api/login":
                return self.login(conn, b)
            if path == "/api/join":
                return self.join(conn, b)
            if path == "/api/logout":
                if t := self.token():
                    db.drop_session(conn, _token_hash(t))
                return self.send(200, {"ok": True}, headers=[_cookie("", 0, self.https)])
            user = self.user(conn)
            if user is None:
                return self.send(401, {"error": "login"})
            try:
                code, out = act(conn, user, path, b)
            except (KeyError, ValueError, TypeError) as e:
                code, out = 400, {"error": str(e) or "bad request"}
            self.send(code, out)
        finally:
            conn.close()

    def throttled(self) -> bool:
        # ponytail: per IP, in memory; resets on restart, enough for a handful of people
        now, ip = time.time(), self.ip()
        FAILS[ip] = [t for t in FAILS.get(ip, []) if now - t < 900]
        return len(FAILS[ip]) >= 10

    def failed(self, msg: str):
        FAILS.setdefault(self.ip(), []).append(time.time())
        time.sleep(1)
        self.send(401, {"error": msg})

    def login(self, conn, b):
        if self.throttled():
            return self.send(429, {"error": "Too many wrong tries. Wait 15 minutes."})
        user = check_login(conn, str(b.get("name", "")), str(b.get("password", "")))
        if user is None:
            return self.failed("Wrong name or password")
        token = new_session(conn, user["user_id"])
        self.send(200, {"ok": True}, headers=[_cookie(token, SESSION_MAX_AGE, self.https)])

    def join(self, conn, b):
        if self.throttled():
            return self.send(429, {"error": "Too many tries. Wait 15 minutes."})
        token = str(b.get("token", ""))
        name = " ".join(str(b.get("name", "")).split())
        if not db.open_invite(conn, token):
            return self.failed("This invite link was already used or has expired.")
        if not _NAME.fullmatch(name):
            return self.send(400, {"error": "Name: 2–32 letters, numbers, spaces, dots or dashes"})
        try:
            pw = valid_password(str(b.get("password", "")))
        except ValueError as e:
            return self.send(400, {"error": str(e)})
        if name.lower() == AUTH["admin"].lower():
            return self.send(400, {"error": "That name is taken. Pick another."})
        uid = db.join(conn, token, name, hash_pw(pw))
        if uid is None:   # lost a race for the link, or the name is taken
            return self.send(400, {"error": "That name is taken, or the link was just used."})
        log.info("user %s joined as %r", uid, name)
        token = new_session(conn, uid)
        self.send(200, {"ok": True}, headers=[_cookie(token, SESSION_MAX_AGE, self.https)])


def act(conn, user, path: str, b: dict) -> tuple[int, dict]:
    """Every POST from a logged-in user. Returns (status, body)."""
    uid, today = user["user_id"], db.user_today(user)

    if path == "/api/quick":   # "250 lunch #food 24 aug", same as the old bot
        p = parse.parse_entry(str(b.get("text", "")), today)
        if p is None:
            raise ValueError("Start with an amount: 250 lunch, or +3000 salary")
        if p.amount > MAX_AMOUNT:
            raise ValueError("That amount looks too big")
        eid = db.add_entry(conn, uid, p.kind, p.amount, p.name[:100],
                           _category_id(conn, uid, p.category), p.on_date)
        return 200, {"entry": entry_json(db.get_entry(conn, uid, eid), user["tz"])}

    if path == "/api/entries":   # several items for one day, all or nothing
        items = b.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
            raise ValueError(f"Add 1 to {MAX_ITEMS} items")
        for i, item in enumerate(items, 1):   # check every amount before writing anything
            try:
                _amount(item.get("amount"))
            except ValueError as e:
                raise ValueError(f"Item {i}: {e}") from None
        rows = [fields_from(conn, uid, dict(item, on_date=b.get("on_date")), today) for item in items]
        ids = [db.add_entry(conn, uid, f["kind"], f["amount"], f["name"], f["category_id"], f["on_date"])
               for f in rows]
        return 200, {"entries": [entry_json(db.get_entry(conn, uid, i), user["tz"]) for i in ids]}

    if path == "/api/entry":
        f = fields_from(conn, uid, b, today)
        eid = db.add_entry(conn, uid, f["kind"], f["amount"], f["name"], f["category_id"], f["on_date"])
        return 200, {"entry": entry_json(db.get_entry(conn, uid, eid), user["tz"])}

    if m := re.fullmatch(r"/api/entry/(\d+)(/delete)?", path):
        if db.get_entry(conn, uid, int(m[1])) is None:
            return 404, {"error": "That entry is gone"}
        if m[2]:
            db.delete_entry(conn, uid, int(m[1]))
            return 200, {"ok": True}
        db.update_entry(conn, uid, int(m[1]), **fields_from(conn, uid, b, today))
        return 200, {"entry": entry_json(db.get_entry(conn, uid, int(m[1])), user["tz"])}

    if m := re.fullmatch(r"/api/category/(\d+)/(rename|delete)", path):
        if m[2] == "delete":
            db.delete_category(conn, uid, int(m[1]))
            return 200, {"ok": True}
        name = " ".join(str(b.get("name", "")).lstrip("#").split())[:32]
        if not name or not db.rename_category(conn, uid, int(m[1]), name):
            raise ValueError("That name is taken")
        return 200, {"ok": True}

    if path == "/api/settings":
        tz, cur = str(b.get("tz", "")), str(b.get("currency", "")).strip()
        if tz not in available_timezones():
            raise ValueError("Unknown timezone")
        if not 1 <= len(cur) <= 3:
            raise ValueError("Currency: one to three characters, like ₹ or $")
        budget = str(b.get("budget") or "0").strip()
        budget = 0 if budget == "0" else _amount(budget)
        for key, value in (("tz", tz), ("currency", cur), ("budget", budget)):
            db.set_setting(conn, uid, key, value)
        return 200, {"ok": True}

    if path == "/api/account":
        # Proof first: the current password, or the PIN for an admin who has
        # never set one. Then a new name and/or a new password.
        current = str(b.get("current", ""))
        if user["pw_hash"]:
            ok = check_pw(current, user["pw_hash"])
        else:
            ok = bool(user["is_admin"]) and pin_ok(current)
        if not ok:
            raise ValueError("Current password is wrong")
        name = " ".join(str(b.get("name") or user["name"] or "").split())
        new = str(b.get("new") or "")
        if user["is_admin"] and not user["pw_hash"] and not new:
            raise ValueError("Set a new password: the PIN stops working for admin once you do")
        if name != user["name"]:
            if not _NAME.fullmatch(name):
                raise ValueError("Name: 2–32 letters, numbers, spaces, dots or dashes")
            reserved = not user["is_admin"] and name.lower() == AUTH["admin"].lower()
            if reserved or not db.rename_user(conn, uid, name):
                raise ValueError("That name is taken")
        if new:
            db.set_password(conn, uid, hash_pw(valid_password(new)))
        return 200, {"ok": True}

    if path.startswith("/api/admin/"):
        if not user["is_admin"]:
            return 403, {"error": "admin only"}
        return admin_act(conn, path, b)

    return 404, {"error": "not found"}


def admin_act(conn, path: str, b: dict) -> tuple[int, dict]:
    label = " ".join(str(b.get("label", "")).split())[:40]
    expires = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=INVITE_DAYS)).isoformat(timespec="seconds")
    if m := re.fullmatch(r"/api/admin/claim/(\d+)", path):
        uid = int(m[1])
        if not any(u["user_id"] == uid for u in db.unclaimed(conn)):
            raise ValueError("That ledger already has a login")
        token = secrets.token_urlsafe(24)
        db.add_invite(conn, token, label, expires, claim_user=uid)
        return 200, {"path": f"/join/{token}"}
    if path == "/api/admin/invite":
        token = secrets.token_urlsafe(24)
        db.add_invite(conn, token, label, expires)
        return 200, {"path": f"/join/{token}"}
    if m := re.fullmatch(r"/api/admin/invite/([\w\-]{20,64})/revoke", path):
        if not db.delete_invite(conn, m[1]):
            raise ValueError("That invite was already used")
        return 200, {"ok": True}
    if m := re.fullmatch(r"/api/admin/user/(\d+)/(disable|enable)", path):
        if not db.set_disabled(conn, int(m[1]), m[2] == "disable"):
            raise ValueError("Can't change that account")
        return 200, {"ok": True}
    return 404, {"error": "not found"}


def setup(conn, admin_uid: int | None = None) -> None:
    """Mark the admin account: by default the oldest ledger (the first
    Telegram user, i.e. whoever ran the bot)."""
    if admin_uid is None:
        first = conn.execute("SELECT user_id FROM user ORDER BY is_admin DESC, created_at"
                             " LIMIT 1").fetchone()
        admin_uid = first["user_id"] if first else 1
    db.make_admin(conn, admin_uid, AUTH["admin"])
    CFG["admin_uid"] = admin_uid


def serve(db_path: str) -> None:
    pin = os.environ.get("FINANCE_PIN") or os.environ.get("SCHEDULE_PIN", "")
    if len(pin) < 6:
        sys.exit("Set FINANCE_PIN in .env (6+ characters)")
    AUTH.update(pin=pin, admin=os.environ.get("FINANCE_ADMIN_NAME", "admin"))
    CFG["db"] = db_path
    conn = db.connect(db_path)
    db.init(conn)
    uid = os.environ.get("FINANCE_USER_ID")
    setup(conn, int(uid) if uid else None)
    conn.close()

    port = int(os.environ.get("FINANCE_PORT", 8098))
    log.info("finance panel on http://127.0.0.1:%s, admin is user %s", port, CFG["admin_uid"])
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
