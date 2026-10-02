"""Web panel + push reminders. Replaces the Telegram bot.

One process: a stdlib HTTP server (API + static files) and a reminder thread
that sends Web Push to every device that allowed notifications.

Env: SCHEDULE_PIN (login, 6+ digits), SCHEDULE_PORT (default 8096),
SCHEDULE_DB_PATH (default schedule.db), SCHEDULE_USER_ID (optional; default:
the one user in the database).
"""

import base64
import datetime as dt
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
SITE = "https://schedule.easebuilds.in"   # VAPID contact; push services want one

AUTH = {"pin": "", "token": ""}
FAILS = []                   # timestamps of wrong PINs
CFG = {"db": "", "uid": 0}

_TIME = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _conn():
    return db.connect(CFG["db"])


def _user(conn):
    return db.get_or_create_user(conn, CFG["uid"])


# --- shapes -----------------------------------------------------------------

def task_json(t) -> dict:
    return {k: t[k] for k in ("id", "title", "daily", "days", "on_date", "at_time",
                              "done_on", "snooze_until")} | {"tag": t["tag_name"]}


def state(conn) -> dict:
    """Everything the panel shows, in one go. A personal schedule is small:
    the client slices it into Today / Week / Upcoming."""
    user = _user(conn)
    uid, now = user["user_id"], db.user_now(user)
    since = now.date() - dt.timedelta(days=HISTORY_DAYS)
    return {
        "now": now.strftime("%Y-%m-%dT%H:%M"),
        "tz": user["tz"],
        "routine": [task_json(t) for t in db.routine(conn, uid)],
        "tasks": [task_json(t) for t in db.one_offs(conn, uid, since)],
        "tags": [{"id": g["id"], "name": g["name"], "open": g["open"]}
                 for g in db.list_tags(conn, uid)],
        "devices": len(db.subs(conn)),
        "vapid": vapid_public(conn),
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

    if old is not None:
        moved = any(f[k] != old[k] for k in ("at_time", "on_date", "daily", "days"))
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


def push_all(conn, payload: dict) -> bool | None:
    """Send to every device. True if any got it, None if there are no devices
    or every one is gone, False if all failed (worth retrying)."""
    from pywebpush import WebPushException, webpush
    vapid, delivered, tried = _vapid(conn), False, False
    for s in db.subs(conn):
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
    return {"title": t["title"], "body": f"{when}{tag}", "id": t["id"],
            "sig": sign(conn, t["id"]), "kind": "reminder"}


def tick(conn) -> int:
    """Send whatever is due. State lives in the database, so a restart loses
    nothing. Returns how many reminders went out."""
    user = _user(conn)
    now, sent = db.user_now(user), 0
    for t in db.reminder_candidates(conn, user["user_id"]):
        if not parse.is_due(t, now):
            continue
        if push_all(conn, reminder(conn, t)) is False:
            continue          # every device failed: leave it for the next tick
        db.update_task(conn, user["user_id"], t["id"],
                       reminded_on=now.date(), snooze_until=None)
        sent += 1
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

def set_done(conn, uid, task_id: int, done: bool, today: dt.date) -> bool:
    return db.update_task(conn, uid, task_id, snooze_until=None,
                          done_on=today if done else None)


def snooze(conn, user, task_id: int, minutes: int) -> bool:
    if minutes not in SNOOZES:
        raise ValueError("snooze is 10, 30 or 60 minutes")
    until = db.user_now(user) + dt.timedelta(minutes=minutes)
    return db.update_task(conn, user["user_id"], task_id,
                          snooze_until=until.strftime("%Y-%m-%dT%H:%M"))


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

    def authed(self) -> bool:
        c = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return "s" in c and hmac.compare_digest(c["s"].value.encode(), AUTH["token"].encode())

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
        if path in STATIC:
            name, ctype = STATIC[path]
            return self.send(200, (HERE / name).read_bytes(), ctype)
        if not self.authed():
            return self.send(401, {"error": "login"})
        if path == "/api/state":
            conn = _conn()
            try:
                return self.send(200, state(conn))
            finally:
                conn.close()
        self.send(404, {"error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            b = self.body()
        except ValueError:
            return self.send(400, {"error": "bad request"})
        if path == "/api/login":
            return self.login(b)
        if path == "/api/logout":
            return self.send(200, {"ok": True}, headers=[
                ("Set-Cookie", "s=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict")])
        if path != "/api/notify" and not self.authed():
            return self.send(401, {"error": "login"})
        conn = _conn()
        try:
            code, out = act(conn, path, b)
        except (KeyError, ValueError, TypeError) as e:
            code, out = 400, {"error": str(e) or "bad request"}
        finally:
            conn.close()
        self.send(code, out)

    def login(self, b):
        now = time.time()
        FAILS[:] = [t for t in FAILS if now - t < 900]
        # ponytail: global lockout, not per-IP; an attacker can lock you out for 15 min
        if len(FAILS) >= 10:
            return self.send(429, {"error": "Too many wrong PINs. Try again in 15 minutes."})
        if hmac.compare_digest(str(b.get("pin", "")).encode(), AUTH["pin"].encode()):
            secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
            return self.send(200, {"ok": True}, headers=[(
                "Set-Cookie",
                f"s={AUTH['token']}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax{secure}")])
        FAILS.append(now)
        time.sleep(1)
        self.send(401, {"error": "Wrong PIN"})


def act(conn, path: str, b: dict) -> tuple[int, dict]:
    """Every POST but login/logout. Returns (status, body)."""
    user = _user(conn)
    uid, today = user["user_id"], db.user_now(user).date()

    if path == "/api/notify":   # a notification button; signed, no cookie
        task_id = int(b["id"])
        if not hmac.compare_digest(str(b.get("sig", "")), sign(conn, task_id)):
            return 403, {"error": "bad signature"}
        if b.get("action") == "done":
            set_done(conn, uid, task_id, True, today)
        else:
            snooze(conn, user, task_id, int(b.get("minutes", 10)))
        return 200, {"ok": True}

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
                          f["at_time"], f["days"])
        return 200, {"task": task_json(db.get_task(conn, uid, tid))}

    if m := re.fullmatch(r"/api/task/(\d+)(?:/(done|snooze|delete))?", path):
        old = db.get_task(conn, uid, int(m[1]))
        if old is None:
            return 404, {"error": "That task is gone"}
        if m[2] == "done":
            set_done(conn, uid, old["id"], bool(b.get("done")), today)
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
        db.save_sub(conn, endpoint, json.dumps({"p256dh": keys["p256dh"], "auth": keys["auth"]}))
        return 200, {"ok": True}

    if path == "/api/push/unsubscribe":
        db.drop_sub(conn, str(b["endpoint"]))
        return 200, {"ok": True}

    if path == "/api/push/test":
        got = push_all(conn, {"title": "Notifications are on", "body": "Reminders will look like this.",
                              "kind": "test"})
        if not got:
            raise ValueError("No device got it. Turn notifications on again in Settings.")
        return 200, {"ok": True}

    if path == "/api/settings":
        tz = str(b.get("tz", ""))
        if tz not in available_timezones():
            raise ValueError("Unknown timezone")
        db.set_tz(conn, uid, tz)
        return 200, {"ok": True}

    return 404, {"error": "not found"}


def serve(db_path: str) -> None:
    pin = os.environ.get("SCHEDULE_PIN", "")
    if len(pin) < 6:
        sys.exit("Set SCHEDULE_PIN in .env (6+ digits)")
    # ponytail: session cookie derived from the PIN; changing the PIN logs every device out
    AUTH.update(pin=pin, token=hmac.new(pin.encode(), b"schedule-panel-session", "sha256").hexdigest())
    conn = db.connect(db_path)
    db.init(conn)
    uid = os.environ.get("SCHEDULE_USER_ID")
    if not uid:
        first = conn.execute("SELECT user_id FROM user ORDER BY created_at LIMIT 1").fetchone()
        uid = first["user_id"] if first else 1
    CFG.update(db=db_path, uid=int(uid))
    vapid_public(conn)   # make the key now, not on the first request
    conn.close()

    threading.Thread(target=_reminder_loop, daemon=True).start()
    port = int(os.environ.get("SCHEDULE_PORT", 8096))
    log.info("schedule panel on http://127.0.0.1:%s for user %s", port, CFG["uid"])
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
