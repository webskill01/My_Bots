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
