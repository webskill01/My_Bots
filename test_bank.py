import datetime as dt
from email.message import EmailMessage

import pytest

from finance_bot import bank, db

ME, OTHER = 111, 222
PARTNER = "9914623976@p"

UPI_CREDIT = """Dear Customer,

Thanking you for banking with Canara Bank.

An amount of INR 90.00 has been CREDITED on 28/10/26 to your account  XXX723 from SUNIL  DUTT with UPI Ref No.:666700742595. Total Available Balance INR 29,829.68.If you are not expecting this credit or suspect any fraudulent activity, please contact: 18001030"""

UPI_DEBIT = """An amount of INR 45.00 has been DEBITED on 28/10/26 from your account XXX723 to 9914623976@p with UPI Ref No.:666778314180. Total Available Balance INR 29,784.68.To report fraud & stop further debit transaction, Call : 18001030."""

NEFT_CREDIT = """An amount of INR 928.37 has been credited to XXX723 on 27/10/2026 towards NEFT by Sender PAYPAL PAYMENTS PVT L PACB INR, IFSC CITI0100000, Sender A/c XXXX8008, CITI BANK N.A, Mumbai, UTR CITIN26750199834, Total Avail. Bal INR 30168.68- Canara Bank"""


def alert(kind, amount, party="SOMEONE", ref="1", balance=1000_00, on=dt.date(2026, 10, 28)):
    return {"kind": kind, "amount": amount, "party": party, "ref": ref,
            "balance": balance, "on_date": on}


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    db.init(c)
    db.get_or_create_user(c, ME)
    db.get_or_create_user(c, OTHER)
    yield c
    c.close()


# --- reading the alerts -----------------------------------------------------

def test_upi_credit():
    assert bank.parse_alert(UPI_CREDIT) == {
        "kind": "earn", "amount": 90_00, "party": "SUNIL DUTT", "ref": "666700742595",
        "balance": 29829_68, "on_date": dt.date(2026, 10, 28)}


def test_upi_debit():
    t = bank.parse_alert(UPI_DEBIT)
    assert (t["kind"], t["amount"], t["party"], t["ref"], t["balance"]) == \
        ("exp", 45_00, PARTNER, "666778314180", 29784_68)


def test_neft_credit_with_a_four_digit_year():
    t = bank.parse_alert(NEFT_CREDIT)
    assert (t["kind"], t["amount"], t["party"], t["ref"], t["balance"], t["on_date"]) == \
        ("earn", 928_37, "PAYPAL PAYMENTS PVT L PACB INR", "CITIN26750199834", 30168_68,
         dt.date(2026, 10, 27))


def test_big_amounts_and_a_balance_without_paise():
    t = bank.parse_alert("An amount of INR 12,000.00 has been DEBITED on 26/10/26 from your account "
                         "XXX723 to BAJWA FILLIN with UPI Ref No.:666568535325. Total Available "
                         "Balance INR 28,835.")
    assert (t["amount"], t["balance"]) == (12000_00, 28835_00)


def test_other_mail_is_not_an_alert():
    assert bank.parse_alert("Your OTP for login is 123456") is None
    assert bank.parse_alert("Get a personal loan at 10.5%! INR 5,00,000 credited in minutes") is None


def test_html_mail_is_read_as_text():
    msg = EmailMessage()
    msg["Subject"] = "UPI/IMPS/MB Transaction Alert"
    msg.set_content(f"<html><body><p>{UPI_DEBIT.replace('&', '&amp;')}</p></body></html>", subtype="html")
    subject, text = bank.read_mail(msg.as_bytes())
    assert subject == "UPI/IMPS/MB Transaction Alert"
    assert bank.parse_alert(text)["ref"] == "666778314180"


# --- your rules -------------------------------------------------------------

@pytest.mark.parametrize("t, category", [
    (alert("earn", 90_00), bank.UNCLAIMED),                       # a taxi bot payment
    (alert("earn", 928_37), None),
    (alert("earn", 12000_00, "EASECAB MOBI"), bank.SALARY),       # salary
    (alert("earn", 1218_00, "EASECAB MOBI"), None),                # a refund, not salary
    (alert("exp", 45_00, PARTNER), bank.SPLIT),                    # partner's half
    (alert("exp", 180_00, PARTNER), bank.REFUND),                  # paying back his refunds
    (alert("exp", 90_00, "9914623976@P"), bank.REFUND),
    (alert("exp", 90_00, "RAKHPREET S"), bank.REFUND),             # refunding a user myself
    (alert("exp", 220_00, "BAJWA FILLIN"), None),
])
def test_category_rules(t, category):
    assert bank.category_for(t, PARTNER) == category


def test_without_a_partner_set_only_the_90_rules_apply():
    assert bank.category_for(alert("exp", 45_00, PARTNER), "") is None
    assert bank.category_for(alert("exp", 90_00, PARTNER), "") == bank.REFUND


# --- recording --------------------------------------------------------------

def test_record_files_an_entry_with_its_category_and_balance(conn):
    eid = bank.record(conn, ME, bank.parse_alert(UPI_CREDIT), PARTNER)
    e = db.get_entry(conn, ME, eid)
    assert (e["kind"], e["amount"], e["name"], e["category_name"], e["on_date"], e["bank_ref"]) == \
        ("earn", 90_00, "SUNIL DUTT", bank.UNCLAIMED, "2026-10-28", "666700742595")
    assert db.get_user(conn, ME)["bank_balance"] == 29829_68


def test_the_same_alert_twice_is_one_entry(conn):
    t = bank.parse_alert(UPI_CREDIT)
    assert bank.record(conn, ME, t, PARTNER) is not None
    assert bank.record(conn, ME, t, PARTNER) is None
    assert db.count_entries(conn, ME, "2000-01-01", "2100-01-01") == 1


def test_bank_refs_are_per_ledger(conn):
    t = bank.parse_alert(UPI_CREDIT)
    assert bank.record(conn, ME, t, PARTNER) and bank.record(conn, OTHER, t, PARTNER)


def test_editing_a_bank_entry_keeps_it_deduplicated(conn):
    t = bank.parse_alert(UPI_CREDIT)
    eid = bank.record(conn, ME, t, PARTNER)
    db.update_entry(conn, ME, eid, name="Sunil, taxi", category_id=None)
    assert bank.record(conn, ME, t, PARTNER) is None


# --- polling Gmail ----------------------------------------------------------

class FakeImap:
    """Just the IMAP calls poll() makes, over a list of (uid, raw mail)."""
    def __init__(self, mails, uidnext):
        self.mails, self.uidnext = mails, uidnext

    def status(self, box, what):
        return "OK", [f'"{box}" (UIDNEXT {self.uidnext})'.encode()]

    def select(self, box, readonly=False):
        assert readonly
        return "OK", [b"1"]

    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            lo = int(args[-1].split("UID ")[1].split(":")[0])
            # like a real server, "N:*" also returns the newest message when N is past it
            hits = [u for u, _ in self.mails if u >= lo] or [self.mails[-1][0]]
            return "OK", [" ".join(map(str, hits)).encode()]
        if cmd == "FETCH":
            raw = dict(self.mails)[int(args[0])]
            return "OK", [(b"x", raw), b")"]
        raise AssertionError(cmd)


def mail(body, subject="UPI/IMPS/MB Transaction Alert"):
    m = EmailMessage()
    m["From"], m["Subject"] = bank.SENDER, subject
    m.set_content(body)
    return m.as_bytes()


def test_first_poll_starts_from_now_and_imports_nothing(conn):
    imap = FakeImap([(7, mail(UPI_CREDIT))], uidnext=8)
    assert bank.poll(imap, conn, ME, PARTNER) == 0
    assert db.get_user(conn, ME)["bank_uid"] == 7
    assert db.count_entries(conn, ME, "2000-01-01", "2100-01-01") == 0


def test_later_polls_record_only_new_mail(conn):
    db.set_bank_uid(conn, ME, 7)
    imap = FakeImap([(7, mail(UPI_CREDIT)), (9, mail(UPI_DEBIT)), (12, mail(NEFT_CREDIT))], uidnext=13)
    assert bank.poll(imap, conn, ME, PARTNER) == 2
    assert db.get_user(conn, ME)["bank_uid"] == 12
    assert db.get_user(conn, ME)["bank_balance"] == 30168_68      # the newest alert's
    assert bank.poll(imap, conn, ME, PARTNER) == 0                # nothing new: nothing twice


def test_an_alert_we_cannot_read_is_kept_for_review(conn):
    db.set_bank_uid(conn, ME, 1)
    odd = "Rs.500.00 debited from A/c XXX723 by POS at SOME SHOP on 28-10-26"
    imap = FakeImap([(2, mail(odd, "Debit card transaction")), (3, mail("Your OTP is 4321", "OTP"))], uidnext=4)
    assert bank.poll(imap, conn, ME, PARTNER) == 0
    misses = db.bank_misses(conn, ME)
    assert [m["subject"] for m in misses] == ["Debit card transaction"]    # the OTP is ignored
    assert "SOME SHOP" in misses[0]["body"]
    assert db.drop_bank_miss(conn, OTHER, misses[0]["id"]) is False        # not theirs
    assert db.drop_bank_miss(conn, ME, misses[0]["id"]) is True
    assert db.bank_misses(conn, ME) == []


# --- reports ----------------------------------------------------------------

def add(conn, kind, amount, cat, on, uid=ME):
    cid = db.get_or_create_category(conn, uid, cat) if cat else None
    return db.add_entry(conn, uid, kind, amount, "", cid, on)


def test_taxi_pool(conn):
    for _ in range(10):
        add(conn, "earn", 90_00, bank.UNCLAIMED, "2026-10-28")    # 10 × ₹90 = ₹900 in
    add(conn, "exp", 90_00, bank.REFUND, "2026-10-28")             # one refunded
    add(conn, "exp", 200_00, bank.SPLIT, "2026-10-28")             # sent to partner
    add(conn, "earn", 90_00, bank.UNCLAIMED, "2026-10-28", uid=OTHER)
    p = db.taxi_pool(conn, ME, bank.UNCLAIMED, bank.REFUND, bank.SPLIT)
    assert p == {"received": 900_00, "received_n": 10, "refunded": 90_00, "refunded_n": 1,
                 "sent": 200_00, "sent_n": 1, "partner_half": 405_00, "owed": 205_00}


def test_salary_counts_only_spending_since_it_landed(conn):
    add(conn, "earn", 50000_00, "Salary", "2026-09-26")
    add(conn, "exp", 1000_00, "food", "2026-10-25")
    add(conn, "earn", 60000_00, "salary", "2026-10-26")
    add(conn, "exp", 500_00, "food", "2026-10-26")
    add(conn, "exp", 250_00, None, "2026-10-27")
    add(conn, "exp", 45_00, bank.SPLIT, "2026-10-28")              # taxi money isn't salary money
    add(conn, "exp", 999_00, "food", "2026-10-28", uid=OTHER)
    s = db.salary_status(conn, ME, "salary")
    assert s == {"on_date": "2026-10-26", "amount": 60000_00, "spent": 750_00, "left": 59250_00}


def test_no_salary_yet(conn):
    assert db.salary_status(conn, ME, "salary") is None


def test_category_budget_is_per_owner(conn):
    cid = db.create_category(conn, ME, "food")
    assert db.set_category_budget(conn, OTHER, cid, 5000_00) is False
    assert db.set_category_budget(conn, ME, cid, 5000_00) is True
    assert [c["budget"] for c in db.category_counts(conn, ME)] == [5000_00]


@pytest.mark.parametrize("today, start, end", [
    ("2026-10-28", "2026-10-26", "2026-11-25"),
    ("2026-10-26", "2026-10-26", "2026-11-25"),
    ("2026-10-25", "2026-09-26", "2026-10-25"),
    ("2027-01-05", "2026-12-26", "2027-01-25"),                    # across the year
    ("2027-03-01", "2027-02-26", "2027-03-25"),                    # short February
])
def test_pay_cycle_runs_26th_to_25th(today, start, end):
    assert db.pay_cycle(dt.date.fromisoformat(today), 26) ==         (dt.date.fromisoformat(start), dt.date.fromisoformat(end))


def test_spent_by_category_counts_only_the_cycle(conn):
    add(conn, "exp", 100_00, "food", "2026-10-25")                 # last cycle
    add(conn, "exp", 200_00, "food", "2026-10-26")
    add(conn, "exp", 300_00, "food", "2026-11-25")
    add(conn, "earn", 999_00, "food", "2026-10-27")                # earnings don't use a budget
    add(conn, "exp", 999_00, "food", "2026-10-27", uid=OTHER)
    cid = db.get_or_create_category(conn, ME, "food")
    assert db.spent_by_category(conn, ME, dt.date(2026, 10, 26), dt.date(2026, 11, 25)) == {cid: 500_00}
