import datetime as dt

import pytest

from finance_bot import parse

TODAY = dt.date(2026, 8, 26)  # a Wednesday


# --- amounts and sign -------------------------------------------------------

@pytest.mark.parametrize("text,kind,amount,name", [
    ("250 lunch", "exp", 25000, "lunch"),
    ("+3000 freelance", "earn", 300000, "freelance"),
    ("-250 lunch", "exp", 25000, "lunch"),
    ("250.50 lunch", "exp", 25050, "lunch"),
    ("250.5 lunch", "exp", 25050, "lunch"),
    ("1,000 rent", "exp", 100000, "rent"),
    ("40 chai   ", "exp", 4000, "chai"),
    ("  250   big  lunch  ", "exp", 25000, "big lunch"),
    ("250", "exp", 25000, ""),
])
def test_parse_entry_amount_and_sign(text, kind, amount, name):
    p = parse.parse_entry(text, TODAY)
    assert p is not None
    assert (p.kind, p.amount, p.name) == (kind, amount, name)


@pytest.mark.parametrize("text", [
    "12.345 lunch",   # more precision than money has
    "abc",
    "",
    "   ",
    "lunch 250",      # amount must lead
    "+ 250 lunch",    # sign must hug the number
    "0 lunch",        # zero is not a transaction
    "-0 lunch",
])
def test_parse_entry_rejects(text):
    assert parse.parse_entry(text, TODAY) is None


def test_parse_entry_defaults_to_today_and_no_category():
    p = parse.parse_entry("250 lunch", TODAY)
    assert p.on_date == TODAY
    assert p.category is None


@pytest.mark.parametrize("s,expected", [
    ("250", 25000),
    ("250.50", 25050),
    ("250.5", 25050),
    ("0.05", 5),
    ("1,23,456.50", 12345650),
    ("12.345", None),
    ("", None),
    ("abc", None),
    (".", None),
    ("1.2.3", None),
])
def test_parse_amount(s, expected):
    assert parse.parse_amount(s) == expected


def test_amounts_never_use_float():
    # 0.1 + 0.2 style drift must be impossible: paise are integers end to end.
    p = parse.parse_entry("0.10 a", TODAY)
    q = parse.parse_entry("0.20 b", TODAY)
    assert isinstance(p.amount, int)
    assert p.amount + q.amount == 30


# --- dates ------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("250 lunch today", dt.date(2026, 8, 26)),
    ("250 lunch yesterday", dt.date(2026, 8, 25)),
    ("250 auto 2d", dt.date(2026, 8, 24)),
    ("250 auto 0d", dt.date(2026, 8, 26)),
    ("250 x 24/8", dt.date(2026, 8, 24)),
    ("250 x 24/08/2026", dt.date(2026, 8, 24)),
    ("250 x 24/08/26", dt.date(2026, 8, 24)),
    ("250 chai 24 aug", dt.date(2026, 8, 24)),
    ("250 chai 24 august", dt.date(2026, 8, 24)),
    ("250 chai aug 24", dt.date(2026, 8, 24)),
    ("250 chai 24 AUG", dt.date(2026, 8, 24)),
    ("250 chai 1 sept", dt.date(2026, 9, 1)),
    ("250 rent 1 jan", dt.date(2026, 1, 1)),
])
def test_parse_entry_dates(text, expected):
    assert parse.parse_entry(text, TODAY).on_date == expected


def test_date_token_is_stripped_from_name():
    p = parse.parse_entry("250 big lunch 24 aug", TODAY)
    assert p.name == "big lunch"
    assert p.on_date == dt.date(2026, 8, 24)


@pytest.mark.parametrize("text,name", [
    ("250 aug", "aug"),            # bare month, no day — that's a name
    ("250 x 24", "x 24"),          # bare number is not a date
    ("250 x 31/2", "x 31/2"),      # no such calendar day
    ("250 x 45/13", "x 45/13"),
    ("250 lunch", "lunch"),
])
def test_non_dates_stay_in_the_name(text, name):
    p = parse.parse_entry(text, TODAY)
    assert p.name == name
    assert p.on_date == TODAY


def test_year_rolls_back_when_date_would_be_in_the_future():
    # Typed in August; "31 dec" means the December that already happened.
    assert parse.parse_entry("250 gift 31 dec", TODAY).on_date == dt.date(2025, 12, 31)


def test_near_future_dates_are_left_alone():
    # A few days ahead is a legitimate post-date, not a typo for last year.
    assert parse.parse_entry("250 x 28 aug", TODAY).on_date == dt.date(2026, 8, 28)


def test_explicit_year_is_never_rolled_back():
    assert parse.parse_entry("250 x 31/12/2026", TODAY).on_date == dt.date(2026, 12, 31)


# --- categories -------------------------------------------------------------

def test_category_is_extracted_and_removed_from_name():
    p = parse.parse_entry("250 chai #food", TODAY)
    assert (p.category, p.name, p.amount) == ("food", "chai", 25000)


def test_category_before_the_amount():
    p = parse.parse_entry("#food 250 chai", TODAY)
    assert (p.category, p.name) == ("food", "chai")


def test_category_is_lowercased_for_matching():
    assert parse.parse_entry("250 chai #Food", TODAY).category == "food"


def test_category_and_date_together():
    p = parse.parse_entry("250 chai #food 24 aug", TODAY)
    assert p.kind == "exp"
    assert p.amount == 25000
    assert p.name == "chai"
    assert p.category == "food"
    assert p.on_date == dt.date(2026, 8, 24)


def test_earning_with_category_and_date():
    p = parse.parse_entry("+3000 client #work 24/8", TODAY)
    assert p.kind == "earn"
    assert p.amount == 300000
    assert p.category == "work"
    assert p.on_date == dt.date(2026, 8, 24)


@pytest.mark.parametrize("token,expected", [
    ("today", dt.date(2026, 8, 26)),
    ("yesterday", dt.date(2026, 8, 25)),
    ("3d", dt.date(2026, 8, 23)),
    ("24/8", dt.date(2026, 8, 24)),
    ("24 aug", dt.date(2026, 8, 24)),
    ("aug 24", dt.date(2026, 8, 24)),
    ("lunch", None),
    ("24", None),
    ("", None),
    ("31/2", None),
])
def test_parse_date(token, expected):
    assert parse.parse_date(token, TODAY) == expected


# --- periods and formatting -------------------------------------------------

@pytest.mark.parametrize("key,n,start,end", [
    ("week",  None, dt.date(2026, 8, 24), TODAY),   # Monday of this week
    ("month", None, dt.date(2026, 8, 1),  TODAY),
    ("7d",    None, dt.date(2026, 8, 20), TODAY),   # inclusive of today
    ("30d",   None, dt.date(2026, 7, 28), TODAY),
    ("nd",    3,    dt.date(2026, 8, 24), TODAY),
    ("nd",    1,    TODAY,                TODAY),
])
def test_period_range(key, n, start, end):
    assert parse.period_range(key, TODAY, n) == (start, end)


def test_period_range_all_covers_everything():
    start, end = parse.period_range("all", TODAY)
    assert start <= dt.date(1, 1, 1)
    assert end == TODAY


def test_week_on_a_monday_is_just_that_day():
    monday = dt.date(2026, 8, 24)
    assert parse.period_range("week", monday) == (monday, monday)


@pytest.mark.parametrize("paise,expected", [
    (0, "₹0"),
    (25000, "₹250"),
    (25050, "₹250.50"),
    (5, "₹0.05"),
    (100000, "₹1,000"),
    (300000, "₹3,000"),
    (12345650, "₹1,23,456.50"),
    (-25000, "-₹250"),
])
def test_fmt_money(paise, expected):
    assert parse.fmt_money(paise, "₹") == expected


def test_fmt_money_uses_the_given_symbol():
    assert parse.fmt_money(25000, "$") == "$250"


# --- db: schema and tenancy -------------------------------------------------

from finance_bot import db as dbm

A, B = 111, 222  # two tenants


@pytest.fixture
def conn():
    c = dbm.connect(":memory:")
    dbm.init(c)
    dbm.get_or_create_user(c, A)
    dbm.get_or_create_user(c, B)
    yield c
    c.close()


def test_init_is_idempotent():
    c = dbm.connect(":memory:")
    dbm.init(c)
    dbm.init(c)
    c.close()


def test_get_or_create_user_is_stable_and_defaults_to_ist(conn):
    u1 = dbm.get_or_create_user(conn, A)
    u2 = dbm.get_or_create_user(conn, A)
    assert u1["user_id"] == u2["user_id"] == A
    assert u1["tz"] == "Asia/Kolkata"
    assert u1["currency"] == "₹"


def test_settings_are_per_user(conn):
    dbm.set_setting(conn, A, "currency", "$")
    assert dbm.get_or_create_user(conn, A)["currency"] == "$"
    assert dbm.get_or_create_user(conn, B)["currency"] == "₹"


def test_user_today_follows_the_users_timezone(conn):
    dbm.set_setting(conn, A, "tz", "Pacific/Kiritimati")   # UTC+14
    dbm.set_setting(conn, B, "tz", "Pacific/Midway")       # UTC-11
    # 25 hours apart: they cannot be on the same calendar day.
    assert dbm.user_today(dbm.get_or_create_user(conn, A)) != \
           dbm.user_today(dbm.get_or_create_user(conn, B))


# --- db: entries are private ------------------------------------------------

def _entry(conn, user, name="lunch", amount=25000, kind="exp", cat=None,
           on=dt.date(2026, 8, 26)):
    return dbm.add_entry(conn, user, kind, amount, name, cat, on)


def test_get_entry_is_scoped_to_its_owner(conn):
    eid = _entry(conn, A)
    assert dbm.get_entry(conn, A, eid)["name"] == "lunch"
    assert dbm.get_entry(conn, B, eid) is None


def test_list_entries_never_leaks_across_tenants(conn):
    _entry(conn, A, "a-lunch")
    _entry(conn, B, "b-lunch")
    rows = dbm.list_entries(conn, A, dt.date(2026, 1, 1), dt.date(2026, 12, 31))
    assert [r["name"] for r in rows] == ["a-lunch"]


def test_update_entry_by_a_stranger_is_refused(conn):
    eid = _entry(conn, A)
    assert dbm.update_entry(conn, B, eid, amount=999) is False
    assert dbm.get_entry(conn, A, eid)["amount"] == 25000


def test_delete_entry_by_a_stranger_is_refused(conn):
    eid = _entry(conn, A)
    assert dbm.delete_entry(conn, B, eid) is False
    assert dbm.get_entry(conn, A, eid) is not None
    assert dbm.delete_entry(conn, A, eid) is True
    assert dbm.get_entry(conn, A, eid) is None


def test_update_entry_only_writes_known_columns(conn):
    eid = _entry(conn, A)
    with pytest.raises(ValueError):
        dbm.update_entry(conn, A, eid, created_at="1999-01-01")  # unforgeable
    with pytest.raises(ValueError):
        dbm.update_entry(conn, A, eid, nonsense=1)


def test_update_entry_changes_the_fields_given(conn):
    eid = _entry(conn, A)
    assert dbm.update_entry(conn, A, eid, amount=50000, name="dinner",
                            on_date=dt.date(2026, 8, 20)) is True
    row = dbm.get_entry(conn, A, eid)
    assert (row["amount"], row["name"], row["on_date"]) == (50000, "dinner", "2026-08-20")


def test_created_at_survives_a_backdated_edit(conn):
    # The whole point of two date columns: filing late stays visible.
    eid = _entry(conn, A, on=dt.date(2026, 8, 26))
    before = dbm.get_entry(conn, A, eid)["created_at"]
    dbm.update_entry(conn, A, eid, on_date=dt.date(2026, 8, 20))
    row = dbm.get_entry(conn, A, eid)
    assert row["created_at"] == before
    assert row["on_date"] == "2026-08-20"


# --- db: categories are private ---------------------------------------------

def test_two_users_may_each_have_a_food_category(conn):
    assert dbm.create_category(conn, A, "Food") is not None
    assert dbm.create_category(conn, B, "Food") is not None


def test_one_user_cannot_create_the_same_category_twice(conn):
    dbm.create_category(conn, A, "Food")
    assert dbm.create_category(conn, A, "Food") is None
    assert dbm.create_category(conn, A, "food") is None  # case-insensitive


def test_get_or_create_category_is_idempotent(conn):
    cid = dbm.get_or_create_category(conn, A, "food")
    assert dbm.get_or_create_category(conn, A, "FOOD") == cid


def test_list_categories_is_scoped(conn):
    dbm.create_category(conn, A, "Food")
    dbm.create_category(conn, B, "Travel")
    assert [c["name"] for c in dbm.list_categories(conn, A)] == ["Food"]


def test_rename_and_delete_category_by_a_stranger_are_refused(conn):
    cid = dbm.create_category(conn, A, "Food")
    assert dbm.rename_category(conn, B, cid, "Hacked") is False
    assert dbm.delete_category(conn, B, cid) is False
    assert [c["name"] for c in dbm.list_categories(conn, A)] == ["Food"]


def test_deleting_a_category_keeps_its_entries_and_uncategorizes_them(conn):
    cid = dbm.create_category(conn, A, "Food")
    eid = _entry(conn, A, cat=cid)
    assert dbm.delete_category(conn, A, cid) is True
    row = dbm.get_entry(conn, A, eid)
    assert row is not None
    assert row["category_id"] is None


def test_a_category_can_exist_before_it_has_any_entry(conn):
    dbm.create_category(conn, A, "Rent")
    assert [c["name"] for c in dbm.list_categories(conn, A)] == ["Rent"]


# --- db: reports ------------------------------------------------------------

D1, D2, D3 = dt.date(2026, 8, 24), dt.date(2026, 8, 25), dt.date(2026, 8, 26)


@pytest.fixture
def ledger(conn):
    """Two tenants with overlapping dates. B's numbers are absurd on purpose:
    if one leaks into A's totals it is unmissable."""
    food = dbm.create_category(conn, A, "Food")
    travel = dbm.create_category(conn, A, "Travel")
    for kind, amount, name, cat, on in [
        ("exp",   10000, "chai",      food,   D1),
        ("exp",   20000, "auto",      travel, D1),
        ("earn", 500000, "salary",    None,   D1),
        ("exp",   30000, "lunch",     food,   D2),
        ("exp",    5000, "misc",      None,   D2),
        ("exp",   80000, "rent",      None,   D3),
        ("exp",   15000, "bus",       travel, D3),
        ("earn", 100000, "freelance", None,   D3),
    ]:
        dbm.add_entry(conn, A, kind, amount, name, cat, on)

    b_food = dbm.create_category(conn, B, "Food")
    dbm.add_entry(conn, B, "exp", 9999900, "yacht", b_food, D2)
    dbm.add_entry(conn, B, "earn", 7777700, "lottery", None, D3)
    return conn


def test_summary_totals(ledger):
    s = dbm.summary(ledger, A, D1, D3)
    assert s["spent"] == 160000
    assert s["earned"] == 600000
    assert s["net"] == 440000
    assert s["count"] == 8


def test_summary_net_is_exact(ledger):
    s = dbm.summary(ledger, A, D1, D3)
    assert s["net"] == s["earned"] - s["spent"]


def test_summary_top_expenses_are_grouped_by_name(ledger):
    dbm.add_entry(ledger, A, "exp", 10000, "chai", None, D3)  # second chai
    top = dbm.summary(ledger, A, D1, D3)["top"]
    assert [(t["name"], t["total"]) for t in top][:3] == [
        ("rent", 80000), ("lunch", 30000), ("chai", 20000)]


def test_summary_respects_the_date_range(ledger):
    s = dbm.summary(ledger, A, D3, D3)
    assert s["spent"] == 95000
    assert s["earned"] == 100000


def test_summary_is_scoped_to_the_tenant(ledger):
    assert dbm.summary(ledger, A, D1, D3)["spent"] == 160000       # no yacht
    assert dbm.summary(ledger, B, D1, D3)["earned"] == 7777700     # no salary


def test_summary_of_an_empty_ledger_is_zeros_not_a_crash(conn):
    s = dbm.summary(conn, A, D1, D3)
    assert (s["spent"], s["earned"], s["net"], s["count"], s["top"]) == (0, 0, 0, 0, [])


def test_day_report_covers_only_that_day(ledger):
    d = dbm.day_report(ledger, A, D3)
    assert d["spent"] == 95000
    assert d["earned"] == 100000
    assert d["net"] == 5000
    assert sorted(e["name"] for e in d["entries"]) == ["bus", "freelance", "rent"]


def test_day_report_is_scoped(ledger):
    assert dbm.day_report(ledger, A, D2)["spent"] == 35000  # not the yacht


def test_day_report_of_an_empty_day(ledger):
    d = dbm.day_report(ledger, A, dt.date(2026, 1, 1))
    assert (d["spent"], d["earned"], d["net"], d["entries"]) == (0, 0, 0, [])


def test_category_totals(ledger):
    rows = {r["name"]: (r["total"], r["count"]) for r in
            dbm.category_totals(ledger, A, D1, D3)}
    assert rows["Food"] == (40000, 2)
    assert rows["Travel"] == (35000, 2)


def test_category_totals_include_an_uncategorized_bucket(ledger):
    rows = {r["name"]: r["total"] for r in dbm.category_totals(ledger, A, D1, D3)}
    assert rows[None] == 85000  # misc + rent


def test_category_totals_exclude_earnings(ledger):
    total = sum(r["total"] for r in dbm.category_totals(ledger, A, D1, D3))
    assert total == dbm.summary(ledger, A, D1, D3)["spent"]


def test_category_totals_are_scoped(ledger):
    rows = {r["name"]: r["total"] for r in dbm.category_totals(ledger, B, D1, D3)}
    assert rows == {"Food": 9999900}


def test_category_totals_of_an_empty_ledger(conn):
    assert dbm.category_totals(conn, A, D1, D3) == []


def test_listing_one_categorys_entries(ledger):
    food = dbm.find_category(ledger, A, "Food")["id"]
    rows = dbm.list_entries(ledger, A, D1, D3, category_id=food)
    assert sorted(r["name"] for r in rows) == ["chai", "lunch"]


def test_listing_uncategorized_entries(ledger):
    rows = dbm.list_entries(ledger, A, D1, D3, category_id=None, kind="exp")
    assert sorted(r["name"] for r in rows) == ["misc", "rent"]


def test_paging_entries(ledger):
    page1 = dbm.list_entries(ledger, A, D1, D3, limit=3, offset=0)
    page2 = dbm.list_entries(ledger, A, D1, D3, limit=3, offset=3)
    assert len(page1) == len(page2) == 3
    assert not {r["id"] for r in page1} & {r["id"] for r in page2}
    assert dbm.count_entries(ledger, A, D1, D3) == 8


# --- views render without a telegram connection -----------------------------

from finance_bot import bot as botm


class Ctx:
    """Just enough of a PTB context for the view functions."""
    def __init__(self, period=("all", None)):
        self.user_data = {"period": period}


@pytest.fixture
def user(ledger):
    return dbm.get_or_create_user(ledger, A)


def _all_buttons(kb):
    return [b for row in (kb.inline_keyboard if kb else []) for b in row]


def test_summary_view_shows_the_totals(ledger, user):
    text, kb = botm.summary_view(ledger, user, Ctx())
    assert "₹1,600" in text      # spent
    assert "₹6,000" in text      # earned
    assert "+₹4,400" in text     # net
    assert kb is not None


def test_summary_view_of_an_empty_ledger(conn):
    text, _ = botm.summary_view(conn, dbm.get_or_create_user(conn, A), Ctx())
    assert "Nothing recorded" in text


def test_day_view_lists_that_days_entries(ledger, user):
    text, kb = botm.day_view(ledger, user, D3)
    for name in ("rent", "bus", "freelance"):
        assert name in text
    assert "chai" not in text          # that was D1
    assert "+₹1,000" in text           # the earning is signed
    assert _all_buttons(kb)


def test_day_view_hides_next_on_a_future_day(ledger, user):
    _, kb = botm.day_view(ledger, user, dbm.user_today(user) + dt.timedelta(days=5))
    assert not any("Next" in b.text for b in _all_buttons(kb))


def test_day_view_of_an_empty_day(ledger, user):
    text, _ = botm.day_view(ledger, user, dt.date(2020, 1, 1))
    assert "No entries." in text


def test_entries_view_gives_one_button_per_entry(ledger, user):
    text, kb = botm.entries_view(ledger, user, Ctx(), 0)
    entry_buttons = [b for b in _all_buttons(kb) if b.callback_data.startswith("e:")]
    assert len(entry_buttons) == 8
    assert "8 total" in text


def test_entries_view_pages(ledger, user):
    for i in range(20):
        dbm.add_entry(ledger, A, "exp", 100 + i, f"item{i}", None, D2)
    _, kb1 = botm.entries_view(ledger, user, Ctx(), 0)
    labels = [b.text for b in _all_buttons(kb1)]
    assert any("Older" in x for x in labels)
    assert not any("Newer" in x for x in labels)   # no page before the first
    _, kb2 = botm.entries_view(ledger, user, Ctx(), 1)
    assert any("Newer" in b.text for b in _all_buttons(kb2))


def test_entry_view_shows_detail_and_filing_time(ledger, user):
    eid = dbm.list_entries(ledger, A, D1, D3)[0]["id"]
    text, _ = botm.entry_view(ledger, user, eid)
    assert "filed" in text


def test_entry_view_of_someone_elses_entry_is_none(ledger):
    eid = dbm.list_entries(ledger, A, D1, D3)[0]["id"]
    assert botm.entry_view(ledger, dbm.get_or_create_user(ledger, B), eid) is None


def test_cats_view_lists_categories_and_uncategorized(ledger, user):
    text, kb = botm.cats_view(ledger, user, Ctx())
    assert "Food" in text and "Travel" in text and "Uncategorized" in text
    assert "₹400" in text     # food: chai + lunch
    assert "₹850" in text     # uncategorized: misc + rent


def test_cats_view_shows_an_empty_category(ledger, user):
    dbm.create_category(ledger, A, "Rent")
    text, _ = botm.cats_view(ledger, user, Ctx())
    assert "Rent" in text


def test_cat_view_lists_only_that_categorys_expenses(ledger, user):
    food = dbm.find_category(ledger, A, "Food")["id"]
    text, _ = botm.cat_view(ledger, user, Ctx(), food, 0)
    assert "chai" in text and "lunch" in text
    assert "auto" not in text


def test_cat_view_uncategorized_bucket(ledger, user):
    text, _ = botm.cat_view(ledger, user, Ctx(), 0, 0)
    assert "misc" in text and "rent" in text
    assert "salary" not in text    # earnings are not spending


def test_cat_view_of_a_deleted_category(ledger, user):
    text, _ = botm.cat_view(ledger, user, Ctx(), 9999, 0)
    assert "gone" in text


def test_settings_view(ledger, user):
    text, _ = botm.settings_view(ledger, user)
    assert "Asia/Kolkata" in text


# --- the bug that would actually bite ---------------------------------------

def test_user_text_is_html_escaped_everywhere(ledger, user):
    dbm.add_entry(ledger, A, "exp", 100, "<b>hack</b> & co", None, D3)
    dbm.create_category(ledger, A, "<i>tag</i>")
    for text, _ in [botm.day_view(ledger, user, D3),
                    botm.entries_view(ledger, user, Ctx(), 0),
                    botm.cats_view(ledger, user, Ctx()),
                    botm.summary_view(ledger, user, Ctx())]:
        assert "<b>hack</b>" not in text
        assert "&lt;b&gt;hack&lt;/b&gt;" in text or "hack" not in text


def test_callback_data_fits_telegrams_64_byte_limit(ledger, user):
    views = [botm.summary_view(ledger, user, Ctx()),
             botm.day_view(ledger, user, D3),
             botm.entries_view(ledger, user, Ctx(), 0),
             botm.cats_view(ledger, user, Ctx()),
             botm.cat_view(ledger, user, Ctx(), 0, 0),
             botm.settings_view(ledger, user),
             botm.category_picker(ledger, user, 1),
             botm.date_picker(1, D3),
             (None, botm.menu_kb()),
             (None, botm.period_kb("sum")),
             (None, botm.entry_kb(1, fresh=True))]
    for _, kb in views:
        for b in _all_buttons(kb):
            assert len(b.callback_data.encode()) <= 64, b.callback_data


# --- migration --------------------------------------------------------------

def test_init_adds_budget_columns_to_an_existing_database():
    """The VM already has a finance.db from before budgets existed."""
    c = dbm.connect(":memory:")
    c.executescript("""
        CREATE TABLE user (user_id INTEGER PRIMARY KEY, tz TEXT NOT NULL
            DEFAULT 'Asia/Kolkata', currency TEXT NOT NULL DEFAULT '₹',
            created_at TEXT NOT NULL);
    """)
    c.execute("INSERT INTO user (user_id, created_at) VALUES (1, '2026-01-01')")
    dbm.init(c)
    row = dbm.get_or_create_user(c, 1)
    assert row["budget"] == 0
    assert row["alert_month"] is None
    assert row["created_at"] == "2026-01-01"     # existing data survives
    c.close()


# --- monthly budget ---------------------------------------------------------

def _budget(conn, amount):
    dbm.set_setting(conn, A, "budget", amount)
    return dbm.get_or_create_user(conn, A)


def test_no_alert_when_no_budget_is_set(ledger, user):
    assert botm.budget_alert(ledger, user, D3) is None


def test_no_alert_below_eighty_percent(ledger):
    u = _budget(ledger, 1000000)          # ₹10,000 vs ₹1,600 spent
    assert botm.budget_alert(ledger, u, D3) is None


def test_alert_at_eighty_percent(ledger):
    u = _budget(ledger, 200000)           # ₹2,000; spent ₹1,600 is exactly 80%
    msg = botm.budget_alert(ledger, u, D3)
    assert msg is not None
    assert "80%" in msg and "₹1,600" in msg and "₹2,000" in msg
    assert "₹400" in msg                  # what's left


def test_alert_when_over_budget(ledger):
    u = _budget(ledger, 100000)           # ₹1,000; spent ₹1,600
    msg = botm.budget_alert(ledger, u, D3)
    assert "Over budget" in msg and "₹600" in msg   # the overshoot


def test_each_level_warns_only_once_a_month(ledger):
    u = _budget(ledger, 200000)
    assert botm.budget_alert(ledger, u, D3) is not None
    u = dbm.get_or_create_user(ledger, A)
    assert botm.budget_alert(ledger, u, D3) is None
    assert botm.budget_alert(ledger, dbm.get_or_create_user(ledger, A), D3) is None


def test_crossing_a_higher_level_warns_again(ledger):
    u = _budget(ledger, 200000)
    assert "80%" in botm.budget_alert(ledger, u, D3)
    u = _budget(ledger, 100000)           # budget cut: now over
    assert "Over budget" in botm.budget_alert(ledger, u, D3)


def test_dropping_back_does_not_re_warn(ledger):
    u = _budget(ledger, 100000)
    assert "Over budget" in botm.budget_alert(ledger, u, D3)
    u = _budget(ledger, 190000)           # now at 84%, level 80
    assert botm.budget_alert(ledger, u, D3) is None


def test_the_alert_resets_next_month(ledger):
    u = _budget(ledger, 200000)
    assert botm.budget_alert(ledger, u, D3) is not None
    sept = dt.date(2026, 9, 15)
    u = dbm.get_or_create_user(ledger, A)
    assert botm.budget_alert(ledger, u, sept) is None      # nothing spent in Sept
    dbm.add_entry(ledger, A, "exp", 200000, "rent", None, sept)
    assert "Over budget" in botm.budget_alert(ledger, u, sept)


def test_budget_counts_only_the_current_month(ledger):
    dbm.add_entry(ledger, A, "exp", 5000000, "car", None, dt.date(2026, 7, 15))
    u = _budget(ledger, 200000)
    msg = botm.budget_alert(ledger, u, D3)
    assert "₹1,600" in msg      # July's ₹50,000 is not August's problem


def test_earnings_do_not_count_against_the_budget(ledger):
    dbm.add_entry(ledger, A, "earn", 9000000, "bonus", None, D3)
    u = _budget(ledger, 200000)
    assert "₹1,600" in botm.budget_alert(ledger, u, D3)


def test_summary_shows_the_budget_line_for_the_month(ledger):
    u = _budget(ledger, 200000)
    text, _ = botm.summary_view(ledger, u, Ctx(("month", None)))
    assert "Budget" in text
    text, _ = botm.summary_view(ledger, u, Ctx(("all", None)))
    assert "Budget" not in text   # the budget is monthly; other periods would lie


def test_settings_shows_the_budget(ledger):
    u = _budget(ledger, 200000)
    assert "₹2,000 / month" in botm.settings_view(ledger, u)[0]
    u = _budget(ledger, 0)
    assert "not set" in botm.settings_view(ledger, u)[0]


# --- created_at renders in the user's timezone ------------------------------

def test_filed_time_is_shown_in_the_users_timezone(ledger, user):
    eid = dbm.list_entries(ledger, A, D1, D3)[0]["id"]
    stamp = dbm.get_entry(ledger, A, eid)["created_at"]
    utc = dt.datetime.fromisoformat(stamp)
    ist = botm._local(stamp, user)
    assert ist.utcoffset() == dt.timedelta(hours=5, minutes=30)
    assert ist.hour == (utc.hour + 5 + (utc.minute + 30) // 60) % 24


def test_filed_time_handles_a_naive_legacy_timestamp(ledger, user):
    naive = botm._local("2026-08-26T16:11:25", user)
    assert naive.hour == 21 and naive.minute == 41    # 16:11 UTC is 21:41 IST
