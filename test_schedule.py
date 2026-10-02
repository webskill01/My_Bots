import datetime as dt
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from schedule_bot import db, panel, parse

NOW = dt.datetime(2026, 10, 2, 14, 0)   # a Friday, 2 PM
TODAY = NOW.date()


# --- parsing ----------------------------------------------------------------

@pytest.mark.parametrize("s,expected", [
    ("6pm", "18:00"), ("6 pm", "18:00"), ("6:30pm", "18:30"), ("6.30PM", "18:30"),
    ("12am", "00:00"), ("12pm", "12:00"), ("18:30", "18:30"), ("7:05", "07:05"),
    ("13pm", None), ("25:00", None), ("6:75", None), ("6", None), ("abc", None),
])
def test_parse_time(s, expected):
    assert parse.parse_time(s) == expected


@pytest.mark.parametrize("token,expected", [
    ("today", TODAY), ("tomorrow", TODAY + dt.timedelta(days=1)),
    ("tmrw", TODAY + dt.timedelta(days=1)),
    ("mon", dt.date(2026, 10, 5)), ("friday", dt.date(2026, 10, 9)),  # never today
    ("in 3d", dt.date(2026, 10, 5)),
    ("5/10", dt.date(2026, 10, 5)), ("5 oct", dt.date(2026, 10, 5)),
    ("oct 5", dt.date(2026, 10, 5)),
    ("24 aug", dt.date(2027, 8, 24)),        # already gone this year
    ("2 oct", TODAY),                         # today is not "gone"
    ("1/1/2028", dt.date(2028, 1, 1)),
    ("31/2", None), ("lunch", None), ("5", None),
])
def test_parse_date(token, expected):
    assert parse.parse_date(token, TODAY) == expected


@pytest.mark.parametrize("text,title,tag,daily,on_date,at_time", [
    ("call mom 6pm", "call mom", None, False, TODAY, "18:00"),
    ("call mom at 6pm", "call mom", None, False, TODAY, "18:00"),
    ("dentist tomorrow 10:30 #health", "dentist", "health", False,
     TODAY + dt.timedelta(days=1), "10:30"),
    ("tomorrow 9am standup #Work", "standup", "work", False,
     TODAY + dt.timedelta(days=1), "09:00"),
    ("pay rent 5 oct", "pay rent", None, False, dt.date(2026, 10, 5), None),
    ("buy milk", "buy milk", None, False, TODAY, None),
    ("gym 7am #daily", "gym", None, True, None, "07:00"),
    ("#daily #health meds 9:30pm", "meds", "health", True, None, "21:30"),
    ("meet 2 friends 5pm", "meet 2 friends", None, False, TODAY, "17:00"),
])
def test_parse_task(text, title, tag, daily, on_date, at_time):
    assert parse.parse_task(text, NOW) == (title, tag, daily, on_date, at_time)


def test_a_time_already_past_today_means_tomorrow():
    p = parse.parse_task("call mom 9am", NOW)
    assert (p.on_date, p.at_time) == (TODAY + dt.timedelta(days=1), "09:00")


def test_a_past_time_with_an_explicit_date_is_left_alone():
    p = parse.parse_task("call mom today 9am", NOW)
    assert p.on_date == TODAY


@pytest.mark.parametrize("text", ["", "   ", "#work", "6pm", "tomorrow 6pm #daily"])
def test_parse_task_needs_a_title(text):
    assert parse.parse_task(text, NOW) is None


@pytest.mark.parametrize("hhmm,expected", [
    ("00:00", "12:00 AM"), ("07:05", "7:05 AM"), ("12:00", "12:00 PM"),
    ("18:30", "6:30 PM"), (None, ""),
])
def test_fmt_time(hhmm, expected):
    assert parse.fmt_time(hhmm) == expected


# --- is_due -----------------------------------------------------------------

def _t(**kw):
    base = dict(daily=0, on_date=TODAY.isoformat(), at_time="14:00", done_on=None,
                reminded_on=None, snooze_until=None, days=127)
    return base | kw


def test_one_off_is_due_at_its_time_and_not_before():
    assert parse.is_due(_t(), NOW)
    assert not parse.is_due(_t(at_time="14:01"), NOW)


def test_one_off_catches_up_after_downtime():
    assert parse.is_due(_t(on_date="2026-10-01", at_time="09:00"), NOW)


def test_one_off_fires_once_and_never_when_done():
    assert not parse.is_due(_t(reminded_on=TODAY.isoformat()), NOW)
    assert not parse.is_due(_t(done_on=TODAY.isoformat()), NOW)
    assert not parse.is_due(_t(at_time=None), NOW)


def test_daily_fires_every_day_once():
    assert parse.is_due(_t(daily=1, on_date=None, reminded_on="2026-10-01"), NOW)
    assert not parse.is_due(_t(daily=1, on_date=None, reminded_on=TODAY.isoformat()), NOW)


def test_daily_done_today_stays_quiet_but_yesterdays_done_does_not_count():
    assert not parse.is_due(_t(daily=1, on_date=None, done_on=TODAY.isoformat()), NOW)
    assert parse.is_due(_t(daily=1, on_date=None, done_on="2026-10-01"), NOW)


def test_daily_skips_reminders_missed_long_ago():
    assert parse.is_due(_t(daily=1, on_date=None, at_time="13:50"), NOW)
    assert not parse.is_due(_t(daily=1, on_date=None, at_time="09:00"), NOW)


def test_daily_grace_does_not_wrap_past_midnight():
    just_after = dt.datetime(2026, 10, 2, 0, 5)
    assert parse.is_due(_t(daily=1, on_date=None, at_time="00:00"), just_after)
    assert not parse.is_due(_t(daily=1, on_date=None, at_time="23:55"), just_after)


def test_snooze_overrides_reminded_and_waits_for_its_time():
    t = _t(reminded_on=TODAY.isoformat(), snooze_until="2026-10-02T14:10")
    assert not parse.is_due(t, NOW)
    assert parse.is_due(t, NOW + dt.timedelta(minutes=10))
    d = _t(daily=1, on_date=None, reminded_on=TODAY.isoformat(),
           snooze_until="2026-10-02T13:59")
    assert parse.is_due(d, NOW)


# --- storage ----------------------------------------------------------------

@pytest.fixture
def conn():
    c = db.connect(":memory:")
    db.init(c)
    db.get_or_create_user(c, 1)
    db.get_or_create_user(c, 2)
    return c


def test_init_is_idempotent(conn):
    db.init(conn)


def test_tasks_are_scoped_to_their_owner(conn):
    tid = db.add_task(conn, 1, "gym", None, False, TODAY, "07:00")
    assert db.get_task(conn, 2, tid) is None
    assert not db.update_task(conn, 2, tid, title="x")
    assert not db.delete_task(conn, 2, tid)
    assert db.tasks_on(conn, 2, TODAY) == []
    assert db.reminder_candidates(conn, 2) == []


def test_update_task_only_writes_known_columns(conn):
    tid = db.add_task(conn, 1, "gym", None, False, TODAY, None)
    with pytest.raises(ValueError):
        db.update_task(conn, 1, tid, created_at="x")


def test_day_lists_split_routine_one_offs_and_overdue(conn):
    db.add_task(conn, 1, "gym", None, True, None, "07:00")
    db.add_task(conn, 1, "late", None, False, TODAY - dt.timedelta(days=2), None)
    done_late = db.add_task(conn, 1, "done late", None, False, TODAY - dt.timedelta(days=1), None)
    db.update_task(conn, 1, done_late, done_on=TODAY)
    db.add_task(conn, 1, "b", None, False, TODAY, None)
    db.add_task(conn, 1, "a", None, False, TODAY, "09:00")
    db.add_task(conn, 1, "later", None, False, TODAY + dt.timedelta(days=3), None)

    assert [t["title"] for t in db.routine(conn, 1)] == ["gym"]
    assert [t["title"] for t in db.overdue(conn, 1, TODAY)] == ["late"]
    assert [t["title"] for t in db.tasks_on(conn, 1, TODAY)] == ["a", "b"]  # timed first
    assert [t["title"] for t in db.upcoming(conn, 1, TODAY, 10)] == ["later"]
    assert db.count_upcoming(conn, 1, TODAY) == 1


def test_reminder_candidates_drop_reminded_one_offs(conn):
    a = db.add_task(conn, 1, "a", None, False, TODAY, "09:00")
    db.add_task(conn, 1, "no time", None, False, TODAY, None)
    d = db.add_task(conn, 1, "daily", None, True, None, "07:00")
    db.update_task(conn, 1, a, reminded_on=TODAY)
    db.update_task(conn, 1, d, reminded_on=TODAY)
    assert [t["title"] for t in db.reminder_candidates(conn, 1)] == ["daily"]


def test_deleting_a_tag_keeps_its_tasks(conn):
    tag = db.get_or_create_tag(conn, 1, "work")
    assert db.get_or_create_tag(conn, 1, "WORK") == tag
    tid = db.add_task(conn, 1, "standup", tag, False, TODAY, None)
    assert db.list_tags(conn, 1)[0]["open"] == 1
    assert not db.delete_tag(conn, 2, tag)
    assert db.delete_tag(conn, 1, tag)
    assert db.get_task(conn, 1, tid)["tag_id"] is None


def test_two_users_may_share_a_tag_name(conn):
    assert db.create_tag(conn, 1, "work") and db.create_tag(conn, 2, "work")
    assert db.create_tag(conn, 1, "Work") is None


# --- weekday routines -------------------------------------------------------

FRI = 1 << 4


def test_weekday_routine_is_only_due_on_its_days():
    assert parse.is_due(_t(daily=1, on_date=None, days=FRI), NOW)
    assert not parse.is_due(_t(daily=1, on_date=None, days=127 & ~FRI), NOW)
    snoozed = _t(daily=1, on_date=None, days=1, snooze_until="2026-10-02T13:00")
    assert not parse.is_due(snoozed, NOW)


def test_routine_for_a_day_filters_by_weekday(conn):
    db.add_task(conn, 1, "gym", None, True, None, "12:30", days=0b0111111)
    db.add_task(conn, 1, "recovery", None, True, None, "12:30", days=0b1000000)
    sunday = dt.date(2026, 10, 4)
    assert [t["title"] for t in db.routine(conn, 1, TODAY)] == ["gym"]
    assert [t["title"] for t in db.routine(conn, 1, sunday)] == ["recovery"]
    assert len(db.routine(conn, 1)) == 2


@pytest.mark.parametrize("days,expected", [
    (127, "Every day"), (0b0111111, "Mon–Sat"), (0b0010010, "Tue, Fri"),
    (0b1000000, "Sun"), (0b0100100, "Wed, Sat"),
])
def test_fmt_days(days, expected):
    assert parse.fmt_days(days) == expected


def test_init_adds_days_to_an_old_database():
    c = db.connect(":memory:")
    c.executescript(db.SCHEMA)   # the first release had no days column
    db.init(c)
    db.get_or_create_user(c, 1)
    tid = db.add_task(c, 1, "x", None, True, None, None)
    assert db.get_task(c, 1, tid)["days"] == 127



# --- panel: validation ------------------------------------------------------

@pytest.fixture
def pconn(tmp_path, monkeypatch):
    """A file database the panel's helpers can open, owned by user 1."""
    path = str(tmp_path / "s.db")
    c = db.connect(path)
    db.init(c)
    db.get_or_create_user(c, 1)
    monkeypatch.setitem(panel.CFG, "db", path)
    monkeypatch.setitem(panel.CFG, "uid", 1)
    return c


def test_fields_from_a_one_off(pconn):
    f = panel.fields_from(pconn, 1, {"title": "  call   mom ", "on_date": "2026-10-05",
                                     "at_time": "18:30", "tag": "#Family"})
    assert (f["title"], f["daily"], f["on_date"], f["at_time"]) == ("call mom", 0, "2026-10-05", "18:30")
    assert db.get_tag(pconn, 1, f["tag_id"])["name"] == "family"


def test_fields_from_a_routine(pconn):
    f = panel.fields_from(pconn, 1, {"title": "gym", "daily": True, "days": 63, "at_time": None})
    assert (f["daily"], f["days"], f["on_date"], f["tag_id"]) == (1, 63, None, None)


@pytest.mark.parametrize("body", [
    {"title": "", "on_date": "2026-10-05"},
    {"title": "x"},                                        # one-off without a date
    {"title": "x", "on_date": "2026-02-31"},
    {"title": "x", "on_date": "2026-10-05", "at_time": "25:00"},
    {"title": "x", "daily": True, "days": 0},
    {"title": "x", "daily": True, "days": 128},
    {"title": "x", "on_date": "2026-10-05", "tag": "daily"},
])
def test_fields_from_rejects(pconn, body):
    with pytest.raises(ValueError):
        panel.fields_from(pconn, 1, body)


def test_moving_a_task_rearms_its_reminder(pconn):
    tid = db.add_task(pconn, 1, "call", None, False, "2026-10-05", "09:00")
    db.update_task(pconn, 1, tid, reminded_on="2026-10-05", snooze_until="2026-10-05T09:10")
    old = db.get_task(pconn, 1, tid)
    same = panel.fields_from(pconn, 1, {"title": "call again", "on_date": "2026-10-05", "at_time": "09:00"}, old)
    assert "reminded_on" not in same          # renaming alone doesn't re-ring
    moved = panel.fields_from(pconn, 1, {"title": "call", "on_date": "2026-10-05", "at_time": "10:00"}, old)
    assert moved["reminded_on"] is None and moved["snooze_until"] is None


def test_turning_a_routine_into_a_one_off_clears_done(pconn):
    tid = db.add_task(pconn, 1, "gym", None, True, None, "07:00")
    db.update_task(pconn, 1, tid, done_on="2026-10-02")
    f = panel.fields_from(pconn, 1, {"title": "gym", "on_date": "2026-10-03"}, db.get_task(pconn, 1, tid))
    assert f["done_on"] is None and f["daily"] == 0


# --- panel: actions ---------------------------------------------------------

def test_quick_add_parses_like_the_bot_did(pconn):
    code, out = panel.act(pconn, "/api/quick", {"text": "gym 7am #daily #health"})
    assert code == 200
    t = out["task"]
    assert (t["title"], t["daily"], t["days"], t["at_time"], t["tag"]) == ("gym", 1, 127, "07:00", "health")


def test_done_toggle_and_snooze(pconn):
    tid = db.add_task(pconn, 1, "call", None, False, "2026-10-05", "09:00")
    assert panel.act(pconn, f"/api/task/{tid}/done", {"done": True})[1]["task"]["done_on"]
    assert panel.act(pconn, f"/api/task/{tid}/done", {"done": False})[1]["task"]["done_on"] is None
    assert panel.act(pconn, f"/api/task/{tid}/snooze", {"minutes": 30})[1]["task"]["snooze_until"]
    with pytest.raises(ValueError):
        panel.act(pconn, f"/api/task/{tid}/snooze", {"minutes": 7})


def test_someone_elses_task_is_not_found(pconn):
    db.get_or_create_user(pconn, 2)
    tid = db.add_task(pconn, 2, "theirs", None, False, "2026-10-05", None)
    assert panel.act(pconn, f"/api/task/{tid}/delete", {})[0] == 404
    assert db.get_task(pconn, 2, tid) is not None


def test_notification_buttons_need_the_tasks_signature(pconn):
    tid = db.add_task(pconn, 1, "call", None, False, "2026-10-05", "09:00")
    other = db.add_task(pconn, 1, "other", None, False, "2026-10-05", "09:00")
    assert panel.act(pconn, "/api/notify", {"id": tid, "sig": panel.sign(pconn, other),
                                            "action": "done"})[0] == 403
    assert panel.act(pconn, "/api/notify", {"id": tid, "sig": panel.sign(pconn, tid),
                                            "action": "done"})[0] == 200
    assert db.get_task(pconn, 1, tid)["done_on"]


def test_subscribe_validates_and_is_idempotent(pconn):
    sub = {"endpoint": "https://fcm.googleapis.com/x", "keys": {"p256dh": "a", "auth": "b"}}
    panel.act(pconn, "/api/push/subscribe", {"subscription": sub})
    panel.act(pconn, "/api/push/subscribe", {"subscription": sub})
    assert len(db.subs(pconn)) == 1
    with pytest.raises(ValueError):
        panel.act(pconn, "/api/push/subscribe",
                  {"subscription": {"endpoint": "http://evil", "keys": sub["keys"]}})


def test_state_holds_routine_open_tasks_and_recent_history(pconn):
    today = db.user_now(db.get_or_create_user(pconn, 1)).date()
    db.add_task(pconn, 1, "gym", None, True, None, "07:00")
    db.add_task(pconn, 1, "open old", None, False, today - dt.timedelta(days=200), None)
    old_done = db.add_task(pconn, 1, "done old", None, False, today - dt.timedelta(days=200), None)
    db.update_task(pconn, 1, old_done, done_on=today)
    s = panel.state(pconn)
    assert [t["title"] for t in s["routine"]] == ["gym"]
    assert [t["title"] for t in s["tasks"]] == ["open old"]
    assert len(s["vapid"]) == 87      # base64url of a 65-byte P-256 point


# --- panel: reminders -------------------------------------------------------

def test_tick_pushes_due_reminders_once(pconn, monkeypatch):
    now = db.user_now(db.get_or_create_user(pconn, 1))
    past = (now - dt.timedelta(minutes=1)).strftime("%H:%M")
    tid = db.add_task(pconn, 1, "call mom", None, False, now.date() - dt.timedelta(days=1), past)
    sent = []
    monkeypatch.setattr(panel, "push_all", lambda c, p: sent.append(p) or True)
    assert panel.tick(pconn) == 1
    assert panel.tick(pconn) == 0
    assert sent[0]["title"] == "call mom" and sent[0]["sig"] == panel.sign(pconn, tid)


def test_tick_retries_when_every_device_failed(pconn, monkeypatch):
    now = db.user_now(db.get_or_create_user(pconn, 1))
    tid = db.add_task(pconn, 1, "call", None, False, now.date() - dt.timedelta(days=1), "09:00")
    monkeypatch.setattr(panel, "push_all", lambda c, p: False)
    panel.tick(pconn)
    assert db.get_task(pconn, 1, tid)["reminded_on"] is None
    monkeypatch.setattr(panel, "push_all", lambda c, p: None)   # no devices: don't pile up
    panel.tick(pconn)
    assert db.get_task(pconn, 1, tid)["reminded_on"] is not None


def test_push_all_forgets_devices_that_are_gone(pconn, monkeypatch):
    import pywebpush

    class Gone:
        status_code = 410

    def fake(*a, **kw):
        raise pywebpush.WebPushException("gone", response=Gone())
    monkeypatch.setattr(pywebpush, "webpush", fake)
    db.save_sub(pconn, "https://push.example/1", json.dumps({"p256dh": "a", "auth": "b"}))
    assert panel.push_all(pconn, {"title": "x"}) is None
    assert db.subs(pconn) == []


# --- panel: HTTP ------------------------------------------------------------

def test_http_login_gates_the_api(pconn, monkeypatch):
    monkeypatch.setitem(panel.AUTH, "pin", "123456")
    monkeypatch.setitem(panel.AUTH, "token", "tok")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), panel.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"

    def call(path, body=None, cookie=None):
        headers = {"Content-Type": "application/json", **({"Cookie": cookie} if cookie else {})}
        req = urllib.request.Request(base + path, headers=headers,
                                     data=None if body is None else json.dumps(body).encode())
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers
    try:
        assert call("/")[0] == 200 and call("/sw.js")[0] == 200
        assert call("/api/state")[0] == 401
        assert call("/api/quick", {"text": "x"})[0] == 401
        code, _, headers = call("/api/login", {"pin": "123456"})
        assert code == 200 and "s=tok" in headers["Set-Cookie"]
        code, body, _ = call("/api/state", cookie="s=tok")
        assert code == 200 and "routine" in json.loads(body)
        assert call("/api/task", {"title": ""}, cookie="s=tok")[0] == 400
    finally:
        srv.shutdown()


def test_push_all_sends_a_signed_encrypted_message_the_device_can_read(pconn, monkeypatch):
    """End to end against a fake push service: VAPID header present, body
    decrypts with the device's keys to the payload we sent."""
    import base64
    import http_ece
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from http.server import BaseHTTPRequestHandler

    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    device_key, auth = ec.generate_private_key(ec.SECP256R1()), b"0123456789abcdef"
    got = {}

    class PushService(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            got["auth"] = self.headers.get("Authorization", "")
            got["body"] = self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(201)
            self.end_headers()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), PushService)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        point = device_key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        db.save_sub(pconn, f"http://127.0.0.1:{srv.server_port}/push/1",
                    json.dumps({"p256dh": b64(point), "auth": b64(auth)}))
        assert panel.push_all(pconn, {"title": "gym", "id": 7}) is True
    finally:
        srv.shutdown()
    assert got["auth"].startswith("vapid t=") and panel.vapid_public(pconn) in got["auth"]
    plain = http_ece.decrypt(got["body"], private_key=device_key, auth_secret=auth, version="aes128gcm")
    assert json.loads(plain) == {"title": "gym", "id": 7}
