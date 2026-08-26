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
