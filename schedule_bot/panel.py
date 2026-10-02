"""Web panel + push reminders, one account per person.

One process: a stdlib HTTP server (API + static files) and a reminder thread
that sends Web Push to each user's own devices.

Accounts: the admin logs in as SCHEDULE_ADMIN_NAME (default "admin") with
SCHEDULE_PIN. Everyone else joins through a one-time invite link the admin
makes in Settings, choosing their own name and password.

Env: SCHEDULE_PIN (admin password, 6+ chars), SCHEDULE_PORT (default 8096),
SCHEDULE_DB_PATH (default schedule.db), SCHEDULE_ADMIN_NAME, SCHEDULE_USER_ID
(optional: which existing user is the admin; default the oldest one).
"""

import base64
import datetime as dt
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sys
import threading
import time
import urllib.parse
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import available_timezones

from . import db, parse

log = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent / "web"
STATIC = {  # path -> (file, content type)
    "/": ("panel.html", "text/html; charset=utf-8"),
    "/panel.js": ("panel.js", "text/javascript; charset=utf-8"),
    "/sw.js": ("sw.js", "text/javascript; charset=utf-8"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/icon-192.png": ("icon-192.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
    "/badge.png": ("badge.png", "image/png"),
}
TICK_SECONDS = 20
HISTORY_DAYS = 60            # done one-offs older than this stay out of the panel
SNOOZES = (10, 30, 60)
REMIND_BEFORE = (0, 5, 10, 15, 30, 60)   # minutes; the form offers these
INVITE_DAYS = 7
SESSION_MAX_AGE = 365 * 86400
PW_ITERATIONS = 200_000
SITE = "https://schedule.easebuilds.in"   # VAPID contact; push services want one

AUTH = {"pin": "", "admin": "admin"}
CFG = {"db": "", "admin_uid": 0}
FAILS: dict[str, list[float]] = {}   # client IP -> wrong-login timestamps

_TIME = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_NAME = re.compile(r"[\w .\-]{2,32}")
_JOIN = re.compile(r"/join/([\w\-]{20,64})")


def _conn():
    return db.connect(CFG["db"])


# --- passwords and tokens ---------------------------------------------------

def hash_pw(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, PW_ITERATIONS)
    return f"pbkdf2${PW_ITERATIONS}${salt.hex()}${h.hex()}"


def check_pw(pw: str, stored: str | None) -> bool:
    if not stored:
        return False
    _, n, salt, want = stored.split("$")
    got = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(n))
    return hmac.compare_digest(got.hex(), want)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_session(conn, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    db.add_session(conn, user_id, _token_hash(token))
    return token


def pin_ok(password: str) -> bool:
    return bool(AUTH["pin"]) and hmac.compare_digest(password.encode(), AUTH["pin"].encode())


def check_login(conn, name: str, password: str):
    """The user row, or None. Everyone logs in by name + password. Until the
    admin sets their own password, "admin" (or a blank name) + SCHEDULE_PIN
    gets them in; after that the PIN no longer does."""
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


def valid_password(pw: str) -> str:
    if not 6 <= len(pw) <= 200:
        raise ValueError("Password must be at least 6 characters")
    return pw


# --- shapes -----------------------------------------------------------------

def task_json(t) -> dict:
    return {k: t[k] for k in ("id", "title", "daily", "days", "on_date", "at_time", "end_time",
                              "remind_before", "notes", "done_on", "snooze_until")} | {
        "tag": t["tag_name"], "created": t["created_at"][:10]}   # stats skip days before it existed


def state(conn, user) -> dict:
    """Everything one user's panel shows, in one go. A personal schedule is
    small: the client slices it into Today / Week / Upcoming."""
    uid, now = user["user_id"], db.user_now(user)
    since = now.date() - dt.timedelta(days=HISTORY_DAYS)
    return {
        "now": now.strftime("%Y-%m-%dT%H:%M"),
        "tz": user["tz"],
        "me": {"name": user["name"], "admin": bool(user["is_admin"]),
               "has_password": bool(user["pw_hash"])},
        "routine": [task_json(t) for t in db.routine(conn, uid)],
        "tasks": [task_json(t) for t in db.one_offs(conn, uid, since)],
        "log": [[r["task_id"], r["day"]] for r in db.done_days(conn, uid, since)],
        "tags": [{"id": g["id"], "name": g["name"], "open": g["open"]}
                 for g in db.list_tags(conn, uid)],
        "devices": len(db.subs(conn, uid)),
        "vapid": vapid_public(conn),
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


# --- validation: panel input -> task columns ---------------------------------

def _tag_id(conn, uid, name) -> int | None:
    name = "".join(str(name or "").lstrip("#").split()).lower()[:32]
    if not name:
        return None
    if name == "daily":
        raise ValueError("'daily' is not a tag; use Repeats instead")
    return db.get_or_create_tag(conn, uid, name)


def fields_from(conn, uid, b: dict, old=None) -> dict:
    """Validated columns from a create/edit body. Raises ValueError with a
    message fit to show the user."""
    title = " ".join(str(b.get("title", "")).split())[:100]
    if not title:
        raise ValueError("A task needs a title")
    at_time = b.get("at_time") or None
    if at_time is not None and not _TIME.fullmatch(at_time):
        raise ValueError("Time must look like 18:30")
    daily = bool(b.get("daily"))
    f = {"title": title, "at_time": at_time, "daily": int(daily),
         "tag_id": _tag_id(conn, uid, b.get("tag"))}
    if daily:
        days = int(b.get("days") or 0)
        if not 1 <= days <= db.EVERY_DAY:
            raise ValueError("Pick at least one day")
        f |= {"days": days, "on_date": None}
    else:
        on_date = str(b.get("on_date") or "")
        if not _DATE.fullmatch(on_date):
            raise ValueError("Pick a date")
        dt.date.fromisoformat(on_date)  # 2026-02-31 raises ValueError
        f |= {"days": db.EVERY_DAY, "on_date": on_date}

    end_time = b.get("end_time") or None
    if end_time is not None:
        if not _TIME.fullmatch(end_time) or not at_time or end_time <= at_time:
            raise ValueError("The end time must come after the start time")
    before = int(b.get("remind_before") or 0)
    if before not in REMIND_BEFORE:
        raise ValueError("Remind 0, 5, 10, 15, 30 or 60 minutes before")
    f |= {"end_time": end_time, "remind_before": before,
          "notes": str(b.get("notes") or "").strip()[:1000]}

    if old is not None:
        moved = any(f[k] != old[k] for k in ("at_time", "on_date", "daily", "days", "remind_before"))
        if moved:   # a new time is a new reminder: forget the old one went out
            f |= {"reminded_on": None, "snooze_until": None}
        if f["daily"] != old["daily"]:
            f["done_on"] = None
    return f


# --- push -------------------------------------------------------------------

def _vapid(conn):
    from py_vapid import Vapid02  # RFC 8292 "vapid t=, k=" header

    def make():
        v = Vapid02()
        v.generate_keys()
        return v.private_pem().decode()
    return Vapid02.from_pem(db.kv_get(conn, "vapid_pem", make).encode())


def vapid_public(conn) -> str:
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    raw = _vapid(conn).public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def sign(conn, task_id: int) -> str:
    """Lets a notification's Done/Snooze buttons act without the login cookie,
    which a service worker can't be trusted to carry."""
    key = db.kv_get(conn, "notify_key", lambda: secrets.token_hex(32))
    return hmac.new(key.encode(), str(task_id).encode(), "sha256").hexdigest()[:32]


def push_all(conn, user_id: int, payload: dict) -> bool | None:
    """Send to every one of this user's devices. True if any got it, None if
    there are no devices or every one is gone, False if all failed (retry)."""
    from pywebpush import WebPushException, webpush
    vapid, delivered, tried = _vapid(conn), False, False
    for s in db.subs(conn, user_id):
        try:
            webpush({"endpoint": s["endpoint"], "keys": json.loads(s["keys"])},
                    json.dumps(payload), vapid_private_key=vapid,
                    vapid_claims={"sub": SITE}, ttl=6 * 3600, timeout=10,
                    headers={"Urgency": "high"})
            delivered = True
        except WebPushException as e:
            code = getattr(e.response, "status_code", None)
            if code in (404, 410):   # unsubscribed or app data cleared: forget it
                db.drop_sub(conn, s["endpoint"])
                continue
            tried = True
            log.warning("push to %s… failed: %s", s["endpoint"][:40], e)
        except Exception as e:     # network trouble
            tried = True
            log.warning("push failed: %s", e)
    return True if delivered else (False if tried else None)


def reminder(conn, t) -> dict:
    tag = f" · {t['tag_name']}" if t["tag_name"] else ""
    when = parse.fmt_time(t["at_time"]) or "Now"
    if t["end_time"]:
        when += f" – {parse.fmt_time(t['end_time'])}"
    if t["remind_before"] and not t["snooze_until"]:
        when = f"In {t['remind_before']} min · {when}"
    return {"title": t["title"], "body": f"{when}{tag}", "id": t["id"],
            "sig": sign(conn, t["id"]), "kind": "reminder"}


def tick(conn) -> int:
    """Send whatever is due, for everyone. State lives in the database, so a
    restart loses nothing. Returns how many reminders went out."""
    sent = 0
    for user in db.active_users(conn):
        uid, now = user["user_id"], db.user_now(user)
        try:
            for t in db.reminder_candidates(conn, uid):
                if not parse.is_due(t, now):
                    continue
                if push_all(conn, uid, reminder(conn, t)) is False:
                    continue          # every device failed: leave it for the next tick
                db.update_task(conn, uid, t["id"], reminded_on=now.date(), snooze_until=None)
                sent += 1
        except Exception:             # one user's trouble mustn't stop the rest
            log.exception("reminders for user %s failed", uid)
    return sent


def _reminder_loop():
    conn = _conn()
    while True:
        try:
            tick(conn)
        except Exception:
            log.exception("reminder tick failed")
        time.sleep(TICK_SECONDS)


# --- actions shared by the panel and notification buttons -------------------

def set_done(conn, uid, task_id: int, done: bool, day: dt.date, today: dt.date | None = None) -> bool:
    """Tick (or untick) a task for `day`, which may be a past day you forgot.
    A routine's done_on (what silences today's reminder) only follows today."""
    t = db.get_task(conn, uid, task_id)
    if t is None:
        return False
    today = today or day
    if t["daily"]:
        db.log_done(conn, uid, task_id, day, done)
        if day == today:
            db.update_task(conn, uid, task_id, snooze_until=None, done_on=today if done else None)
        return True
    # One-off: undoing clears the day it was actually ticked on.
    logged = day if done else dt.date.fromisoformat(t["done_on"]) if t["done_on"] else day
    db.log_done(conn, uid, task_id, logged, done)
    return db.update_task(conn, uid, task_id, snooze_until=None, done_on=day if done else None)


def snooze(conn, user, task_id: int, minutes: int) -> bool:
    if minutes not in SNOOZES:
        raise ValueError("snooze is 10, 30 or 60 minutes")
    until = db.user_now(user) + dt.timedelta(minutes=minutes)
    return db.update_task(conn, user["user_id"], task_id,
                          snooze_until=until.strftime("%Y-%m-%dT%H:%M"))


def notify_action(conn, b: dict) -> tuple[int, dict]:
    """A notification's Done / Snooze. No login: the per-task signature is the
    proof, and the task's own owner is who it acts for."""
    task_id = int(b["id"])
    if not hmac.compare_digest(str(b.get("sig", "")), sign(conn, task_id)):
        return 403, {"error": "bad signature"}
    owner = db.task_owner(conn, task_id)
    user = owner and db.get_user(conn, owner)
    if not user or user["disabled"]:
        return 404, {"error": "That task is gone"}
    if b.get("action") == "done":
        set_done(conn, owner, task_id, True, db.user_now(user).date())
    else:
        snooze(conn, user, task_id, int(b.get("minutes", 10)))
    return 200, {"ok": True}


# --- HTTP -------------------------------------------------------------------

def _cookie(token: str, max_age: int, https: bool) -> tuple[str, str]:
    secure = "; Secure" if https else ""
    return ("Set-Cookie", f"s={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax{secure}")


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
        path = urllib.parse.urlparse(self.path).path
        if path in STATIC or _JOIN.fullmatch(path):   # /join/<token> is the page; JS takes over
            name, ctype = STATIC.get(path, STATIC["/"])
            return self.send(200, (HERE / name).read_bytes(), ctype)
        conn = _conn()
        try:
            if m := re.fullmatch(r"/api/invite/([\w\-]{20,64})", path):
                inv = db.open_invite(conn, m[1])
                claim = inv and inv["claim_user"] and conn.execute(
                    "SELECT COUNT(*) FROM task WHERE user_id = ?", (inv["claim_user"],)).fetchone()[0]
                return self.send(200, {"label": inv["label"], "claim_tasks": claim or 0}) if inv else \
                    self.send(404, {"error": "This invite link was already used or has expired."})
            user = self.user(conn)
            if user is None:
                return self.send(401, {"error": "login"})
            if path == "/api/state":
                return self.send(200, state(conn, user))
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
            try:
                if path == "/api/notify":
                    code, out = notify_action(conn, b)
                else:
                    user = self.user(conn)
                    if user is None:
                        return self.send(401, {"error": "login"})
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
        # "pin" is the old one-field admin login, kept so an open tab still works
        user = check_login(conn, str(b.get("name", "")), str(b.get("password", b.get("pin", ""))))
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
    uid, today = user["user_id"], db.user_now(user).date()

    if path == "/api/quick":
        p = parse.parse_task(str(b.get("text", "")), db.user_now(user))
        if p is None:
            raise ValueError("Couldn't find a title in that")
        tag_id = _tag_id(conn, uid, p.tag)
        tid = db.add_task(conn, uid, p.title, tag_id, p.daily, p.on_date, p.at_time)
        return 200, {"task": task_json(db.get_task(conn, uid, tid))}

    if path == "/api/task":
        f = fields_from(conn, uid, b)
        tid = db.add_task(conn, uid, f["title"], f["tag_id"], f["daily"], f["on_date"],
                          f["at_time"], f["days"], f["end_time"], f["remind_before"], f["notes"])
        return 200, {"task": task_json(db.get_task(conn, uid, tid))}

    if m := re.fullmatch(r"/api/task/(\d+)(?:/(done|snooze|delete))?", path):
        old = db.get_task(conn, uid, int(m[1]))
        if old is None:
            return 404, {"error": "That task is gone"}
        if m[2] == "done":
            day = dt.date.fromisoformat(str(b.get("day") or today))
            if not today - dt.timedelta(days=HISTORY_DAYS) <= day <= today:
                raise ValueError("You can tick today or a past day, not the future")
            set_done(conn, uid, old["id"], bool(b.get("done")), day, today)
        elif m[2] == "snooze":
            snooze(conn, user, old["id"], int(b.get("minutes", 10)))
        elif m[2] == "delete":
            db.delete_task(conn, uid, old["id"])
            return 200, {"ok": True}
        else:
            db.update_task(conn, uid, old["id"], **fields_from(conn, uid, b, old))
        return 200, {"task": task_json(db.get_task(conn, uid, old["id"]))}

    if m := re.fullmatch(r"/api/tag/(\d+)/(rename|delete)", path):
        if m[2] == "delete":
            db.delete_tag(conn, uid, int(m[1]))
            return 200, {"ok": True}
        name = "".join(str(b.get("name", "")).lstrip("#").split()).lower()[:32]
        if not name or name == "daily" or not db.rename_tag(conn, uid, int(m[1]), name):
            raise ValueError("That name is taken or not allowed")
        return 200, {"ok": True}

    if path == "/api/push/subscribe":
        sub = b["subscription"]
        endpoint, keys = str(sub["endpoint"]), sub["keys"]
        if not endpoint.startswith("https://") or not {"p256dh", "auth"} <= set(keys):
            raise ValueError("not a push subscription")
        db.save_sub(conn, uid, endpoint, json.dumps({"p256dh": keys["p256dh"], "auth": keys["auth"]}))
        return 200, {"ok": True}

    if path == "/api/push/unsubscribe":
        db.drop_sub(conn, str(b["endpoint"]), uid)
        return 200, {"ok": True}

    if path == "/api/push/test":
        got = push_all(conn, uid, {"title": "Notifications are on",
                                   "body": "Reminders will look like this.", "kind": "test"})
        if not got:
            raise ValueError("No device got it. Turn notifications on again in Settings.")
        return 200, {"ok": True}

    if path == "/api/settings":
        tz = str(b.get("tz", ""))
        if tz not in available_timezones():
            raise ValueError("Unknown timezone")
        db.set_tz(conn, uid, tz)
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
    if m := re.fullmatch(r"/api/admin/claim/(\d+)", path):
        uid = int(m[1])
        if not any(u["user_id"] == uid for u in db.unclaimed(conn)):
            raise ValueError("That account already has a login")
        token = secrets.token_urlsafe(24)
        expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=INVITE_DAYS)
        db.add_invite(conn, token, " ".join(str(b.get("label", "")).split())[:40],
                      expires.isoformat(timespec="seconds"), claim_user=uid)
        return 200, {"path": f"/join/{token}"}
    if path == "/api/admin/invite":
        token = secrets.token_urlsafe(24)
        expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=INVITE_DAYS)
        db.add_invite(conn, token, " ".join(str(b.get("label", "")).split())[:40],
                      expires.isoformat(timespec="seconds"))
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
    """Mark the admin account and give it any phones from before accounts."""
    if admin_uid is None:
        first = conn.execute("SELECT user_id FROM user ORDER BY is_admin DESC, created_at"
                             " LIMIT 1").fetchone()
        admin_uid = first["user_id"] if first else 1
    db.make_admin(conn, admin_uid, AUTH["admin"])
    db.adopt_orphan_subs(conn, admin_uid)
    CFG["admin_uid"] = admin_uid


def serve(db_path: str) -> None:
    pin = os.environ.get("SCHEDULE_PIN", "")
    if len(pin) < 6:
        sys.exit("Set SCHEDULE_PIN in .env (6+ characters)")
    AUTH.update(pin=pin, admin=os.environ.get("SCHEDULE_ADMIN_NAME", "admin"))
    CFG["db"] = db_path
    conn = db.connect(db_path)
    db.init(conn)
    uid = os.environ.get("SCHEDULE_USER_ID")
    setup(conn, int(uid) if uid else None)
    vapid_public(conn)   # make the key now, not on the first request
    conn.close()

    threading.Thread(target=_reminder_loop, daemon=True).start()
    port = int(os.environ.get("SCHEDULE_PORT", 8096))
    log.info("schedule panel on http://127.0.0.1:%s, admin is user %s", port, CFG["admin_uid"])
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
