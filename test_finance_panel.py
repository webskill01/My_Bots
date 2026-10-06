import datetime as dt
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from finance_bot import db, panel

TG = 5332135237      # a Telegram-era ledger: becomes the admin
OLD = 7985971941     # another one, waiting to be claimed


@pytest.fixture
def pconn(tmp_path, monkeypatch):
    path = str(tmp_path / "f.db")
    c = db.connect(path)
    db.init(c)
    db.get_or_create_user(c, TG)
    db.get_or_create_user(c, OLD)
    monkeypatch.setitem(panel.CFG, "db", path)
    monkeypatch.setitem(panel.AUTH, "pin", "123456")
    monkeypatch.setitem(panel.AUTH, "admin", "admin")
    panel.setup(c, TG)
    yield c
    c.close()


def me(c, uid=TG):
    return db.get_user(c, uid)


def _invite(c, claim=None, days=7):
    token = f"tok{'x' * 20}{claim or ''}{days}"
    exp = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days)).isoformat(timespec="seconds")
    db.add_invite(c, token, "", exp, claim_user=claim)
    return token


def test_init_upgrades_a_bot_database_in_place(tmp_path):
    path = str(tmp_path / "old.db")
    c = db.connect(path)
    c.executescript(db.SCHEMA.split("-- Web panel")[0])   # the bot-era schema
    c.execute("INSERT INTO user (user_id, created_at) VALUES (1, 'x')")
    c.commit()
    db.init(c)
    db.init(c)   # and again: idempotent
    assert db.get_user(c, 1)["name"] is None and db.unclaimed(c)[0]["user_id"] == 1


def test_state_is_one_month_and_months_cover_everything(pconn):
    for amt, on in [(10000, "2026-08-31"), (20000, "2026-09-01"), (30000, "2026-09-30"), (5000, "2026-10-01")]:
        db.add_entry(pconn, TG, "exp", amt, "x", None, on)
    db.add_entry(pconn, TG, "earn", 900000, "salary", None, "2026-09-05")
    s = panel.state(pconn, me(pconn), "2026-09")
    assert s["month"] == "2026-09"
    assert sorted(e["on_date"] for e in s["entries"]) == ["2026-09-01", "2026-09-05", "2026-09-30"]
    assert [m["month"] for m in s["months"]] == ["2026-10", "2026-09", "2026-08"]
    sep = s["months"][1]
    assert (sep["spent"], sep["earned"], sep["count"]) == (50000, 900000, 3)


def test_a_bad_month_falls_back_to_this_one(pconn):
    today = db.user_today(me(pconn))
    for bad in (None, "2026-13", "x", "2026-9"):
        assert panel.state(pconn, me(pconn), bad)["month"] == today.strftime("%Y-%m")


def test_quick_add_speaks_the_bots_language(pconn):
    _, out = panel.act(pconn, me(pconn), "/api/quick", {"text": "+3000 freelance #gigs 2/9/2026"})
    e = out["entry"]
    assert (e["kind"], e["amount"], e["name"], e["category"], e["on_date"]) == \
        ("earn", 300000, "freelance", "gigs", "2026-09-02")
    with pytest.raises(ValueError):
        panel.act(pconn, me(pconn), "/api/quick", {"text": "lunch"})


def test_form_add_edit_and_delete(pconn):
    today = db.user_today(me(pconn)).isoformat()
    body = {"kind": "exp", "amount": "1,250.5", "name": "  rent  share ", "category": "#Home", "on_date": today}
    _, out = panel.act(pconn, me(pconn), "/api/entry", body)
    e = out["entry"]
    assert (e["amount"], e["name"], e["category"]) == (125050, "rent share", "Home")
    _, out = panel.act(pconn, me(pconn), f"/api/entry/{e['id']}", body | {"amount": "99", "category": ""})
    assert (out["entry"]["amount"], out["entry"]["category"]) == (9900, None)
    assert panel.act(pconn, me(pconn), f"/api/entry/{e['id']}/delete", {})[0] == 200
    assert db.get_entry(pconn, TG, e["id"]) is None


@pytest.mark.parametrize("change", [
    {"kind": "loan"}, {"amount": "0"}, {"amount": "abc"}, {"amount": "-5"},
    {"amount": "9999999999"}, {"on_date": "2026-02-31"}, {"on_date": "1999-01-01"},
    {"on_date": "2099-01-01"}, {"on_date": ""},
])
def test_the_form_rejects(pconn, change):
    body = {"kind": "exp", "amount": "100", "name": "", "category": "", "on_date": "2026-09-01"} | change
    with pytest.raises(ValueError):
        panel.fields_from(pconn, TG, body, dt.date(2026, 10, 6))


def test_settings_validate_and_budget_zero_switches_off(pconn):
    ok = {"tz": "Asia/Kolkata", "currency": "$", "budget": "20,000"}
    panel.act(pconn, me(pconn), "/api/settings", ok)
    assert (me(pconn)["currency"], me(pconn)["budget"]) == ("$", 2000000)
    panel.act(pconn, me(pconn), "/api/settings", ok | {"budget": "0"})
    assert me(pconn)["budget"] == 0
    for bad in ({"tz": "Mars/Base"}, {"currency": ""}, {"currency": "RUPEE"}, {"budget": "lots"}):
        with pytest.raises(ValueError):
            panel.act(pconn, me(pconn), "/api/settings", ok | bad)


def test_admin_is_the_oldest_ledger_and_logs_in_with_the_pin(pconn):
    assert panel.check_login(pconn, "admin", "123456")["user_id"] == TG
    assert panel.check_login(pconn, "", "123456")["user_id"] == TG
    assert panel.check_login(pconn, "admin", "nope") is None


def test_a_claim_link_hands_over_a_telegram_ledger_with_its_history(pconn):
    db.add_entry(pconn, OLD, "exp", 4200, "old chai", None, "2026-09-10")
    assert [u["user_id"] for u in db.unclaimed(pconn)] == [OLD]
    _, out = panel.admin_act(pconn, f"/api/admin/claim/{OLD}", {"label": "Telegram"})
    token = out["path"].split("/")[-1]
    uid = db.join(pconn, token, "Ravi", panel.hash_pw("ravi-pw"))
    assert uid == OLD
    assert panel.check_login(pconn, "ravi", "ravi-pw")["user_id"] == OLD
    assert [e["name"] for e in panel.state(pconn, me(pconn, OLD), "2026-09")["entries"]] == ["old chai"]
    assert db.unclaimed(pconn) == []
    with pytest.raises(ValueError):   # already claimed: no second link
        panel.admin_act(pconn, f"/api/admin/claim/{OLD}", {})


def test_users_never_see_or_touch_each_others_money(pconn):
    other = db.join(pconn, _invite(pconn), "Ravi", panel.hash_pw("x" * 6))
    mine = db.add_entry(pconn, TG, "exp", 100, "mine", None, "2026-09-01")
    panel.act(pconn, me(pconn, other), "/api/quick", {"text": "200 theirs 2/9/2026"})
    s1 = panel.state(pconn, me(pconn), "2026-09")
    s2 = panel.state(pconn, me(pconn, other), "2026-09")
    assert [e["name"] for e in s1["entries"]] == ["mine"]
    assert [e["name"] for e in s2["entries"]] == ["theirs"]
    assert s2["months"][0]["spent"] == 20000
    assert panel.act(pconn, me(pconn, other), f"/api/entry/{mine}/delete", {})[0] == 404
    assert panel.act(pconn, me(pconn, other), "/api/admin/invite", {})[0] == 403


def test_people_counts_entries_not_amounts(pconn):
    db.add_entry(pconn, TG, "exp", 100, "x", None, "2026-09-01")
    p = panel.admin_state(pconn)["people"][0]
    assert p["entries"] == 1 and "amount" not in p and "spent" not in p


# --- HTTP -------------------------------------------------------------------

def test_http_login_then_month_state(pconn):
    db.add_entry(pconn, TG, "exp", 100, "chai", None, "2026-09-01")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), panel.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(path, body=None, cookie=""):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", "Cookie": cookie})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.headers, json.loads(r.read()) if "json" in r.headers["Content-Type"] else None
        except urllib.error.HTTPError as e:
            return e.code, e.headers, json.loads(e.read())

    try:
        assert call("/api/state")[0] == 401
        assert call("/")[0] == 200 and call("/join/" + "a" * 30)[0] == 200
        code, headers, _ = call("/api/login", {"name": "admin", "password": "123456"})
        assert code == 200
        cookie = headers["Set-Cookie"].split(";")[0]
        code, _, s = call("/api/state?month=2026-09", cookie=cookie)
        assert code == 200 and [e["name"] for e in s["entries"]] == ["chai"]
        assert call("/api/entry", {"kind": "exp"}, cookie)[0] == 400   # validation, not a crash
    finally:
        srv.shutdown()


# --- several items at once, times, recent items -----------------------------

def test_several_items_for_one_day_are_saved_together(pconn):
    day = db.user_today(me(pconn)).isoformat()
    _, out = panel.act(pconn, me(pconn), "/api/entries", {"on_date": day, "items": [
        {"kind": "exp", "amount": "20", "name": "chai", "category": "Food"},
        {"kind": "exp", "amount": "150.50", "name": "auto", "category": "Brand New"},
        {"kind": "earn", "amount": "500", "name": "refund", "category": ""},
    ]})
    assert [(e["name"], e["amount"], e["category"], e["on_date"]) for e in out["entries"]] == [
        ("chai", 2000, "Food", day), ("auto", 15050, "Brand New", day), ("refund", 50000, None, day)]
    assert "Brand New" in [c["name"] for c in db.category_counts(pconn, TG)]   # in the dropdown next time


@pytest.mark.parametrize("items", [[], "x", [{"kind": "exp", "amount": "1"}] * 31,
                                   [{"kind": "exp", "amount": "20"}, {"kind": "exp", "amount": ""}]])
def test_several_items_are_all_or_nothing(pconn, items):
    with pytest.raises(ValueError):
        panel.act(pconn, me(pconn), "/api/entries", {"on_date": "2026-10-01", "items": items})
    assert db.count_entries(pconn, TG, "2000-01-01", "2100-01-01") == 0


def test_entries_carry_the_time_they_were_filed_in_the_users_timezone(pconn):
    eid = db.add_entry(pconn, TG, "exp", 100, "x", None, "2026-09-01")
    pconn.execute("UPDATE entry SET created_at = '2026-09-01T16:11:25+00:00' WHERE id = ?", (eid,))
    assert panel.entry_json(db.get_entry(pconn, TG, eid), "Asia/Kolkata")["time"] == "21:41"
    pconn.execute("UPDATE entry SET created_at = '2026-09-01T16:11:25' WHERE id = ?", (eid,))   # legacy naive
    assert panel.entry_json(db.get_entry(pconn, TG, eid), "Asia/Kolkata")["time"] == "21:41"


def test_recent_items_are_the_most_logged_with_their_latest_amount(pconn):
    today = db.user_today(me(pconn))
    food = db.create_category(pconn, TG, "Food")
    for amt in (1500, 2000, 2500):   # newest last
        db.add_entry(pconn, TG, "exp", amt, "Chai", food, today)
    db.add_entry(pconn, TG, "exp", 9000, "uber", None, today)
    db.add_entry(pconn, TG, "exp", 100, "", None, today)                       # unnamed: skipped
    db.add_entry(pconn, TG, "exp", 100, "ancient", None, today - dt.timedelta(days=200))
    recent = panel.recent_items(pconn, TG, today, "Asia/Kolkata")
    assert [(r["name"], r["amount"], r["category"], r["n"]) for r in recent] == [
        ("Chai", 2500, "Food", 3), ("uber", 9000, None, 1)]
