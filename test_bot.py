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
