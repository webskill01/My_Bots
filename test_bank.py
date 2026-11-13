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
    (alert("earn", 12000_00, "EASECAB MOBI"), bank.SALARY),       # salary
    (alert("earn", 1218_00, "EASECAB MOBI"), None),                # a refund, not salary
    (alert("earn", 928_37), None),
])
def test_category_rules(t, category):
    assert bank.category_for(t) == category


@pytest.mark.parametrize("t, rule", [
    (alert("earn", 90_00), "in"),                                  # a taxi bot payment
    (alert("earn", 45_00), "in"),
    (alert("earn", 100_00), None),                                 # rare, usually real money
    (alert("earn", 90_00, "EASECAB MOBI"), None),                  # employer money is never taxi
    (alert("earn", 928_37), None),
    (alert("earn", 90_00, PARTNER), "split"),                      # partner paying back
    (alert("exp", 45_00, PARTNER), "split"),                       # partner's half
    (alert("exp", 135_00, PARTNER), "split"),
    (alert("exp", 180_00, PARTNER), "refund"),                     # paying back his refunds
    (alert("exp", 90_00, "9914623976@P"), "refund"),
    (alert("exp", 90_00, "RAKHPREET S"), "refund"),                # refunding a user myself
    (alert("exp", 45_00, "RAKHPREET S"), "refund"),
    (alert("exp", 220_00, "BAJWA FILLIN"), None),
])
def test_taxi_rules(t, rule):
    assert bank.taxi_rule(t, PARTNER) == rule


def test_without_a_partner_set_only_the_90_and_45_rules_apply():
    assert bank.taxi_rule(alert("exp", 135_00, PARTNER), "") is None
    assert bank.taxi_rule(alert("exp", 45_00, PARTNER), "") == "refund"


def test_credits_from_the_partner_match_his_name():
    assert bank.taxi_rule(alert("earn", 45_00, "TANISHQ KUMA"), f"{PARTNER},Tanishq") == "split"
    assert bank.taxi_rule(alert("exp", 135_00, PARTNER), f"{PARTNER},Tanishq") == "split"
    assert bank.taxi_rule(alert("earn", 45_00, "TANISHQ KUMA"), PARTNER) == "in"


# --- recording --------------------------------------------------------------

ALL = ("2000-01-01", "2100-01-01")


def test_record_files_an_entry_with_its_category_and_balance(conn):
    eid = bank.record(conn, ME, bank.parse_alert(NEFT_CREDIT), PARTNER)
    e = db.get_entry(conn, ME, eid)
    assert (e["kind"], e["amount"], e["category_name"], e["on_date"], e["bank_ref"]) == \
        ("earn", 928_37, None, "2026-10-27", "CITIN26750199834")
    assert db.get_user(conn, ME)["bank_balance"] == 30168_68


def test_taxi_money_goes_under_taxi_and_out_of_totals(conn):
    bank.record(conn, ME, bank.parse_alert(UPI_CREDIT), PARTNER)
    bank.record(conn, ME, bank.parse_alert(UPI_DEBIT), PARTNER)
    assert db.list_entries(conn, ME, *ALL, taxi=False) == []
    assert db.summary(conn, ME, *ALL)["earned"] == 0 and db.month_totals(conn, ME) == []
    assert [(e["name"], e["taxi"], e["category_name"]) for e in db.list_entries(conn, ME, *ALL, taxi=True)] == \
        [(PARTNER, "split", "taxi"), ("SUNIL DUTT", "in", "taxi")]
    assert db.get_user(conn, ME)["bank_balance"] == 29784_68   # the balance still updates


def test_the_same_alert_twice_is_one_row(conn):
    for text in (UPI_CREDIT, NEFT_CREDIT):
        t = bank.parse_alert(text)
        assert bank.record(conn, ME, t, PARTNER) is not None
        assert bank.record(conn, ME, t, PARTNER) is None
    assert db.count_entries(conn, ME, *ALL) == 2


def test_bank_refs_are_per_ledger(conn):
    t = bank.parse_alert(UPI_CREDIT)
    assert bank.record(conn, ME, t, PARTNER) and bank.record(conn, OTHER, t, PARTNER)


def test_editing_a_bank_entry_keeps_it_deduplicated(conn):
    t = bank.parse_alert(NEFT_CREDIT)
    eid = bank.record(conn, ME, t, PARTNER)
    db.update_entry(conn, ME, eid, name="PayPal", category_id=None)
    assert bank.record(conn, ME, t, PARTNER) is None


def test_the_old_taxi_log_moves_into_the_ledger_once(conn):
    conn.execute("CREATE TABLE taxi (id INTEGER PRIMARY KEY, user_id INTEGER, kind TEXT, amount INTEGER,"
                 " party TEXT, rule TEXT, on_date TEXT, bank_ref TEXT, created_at TEXT)")
    rows = [(ME, "earn", 90_00, "SUNIL", "in", "r1", "2026-11-01T00:00:00+00:00"),
            (ME, "exp", 45_00, PARTNER, "split", "r2", "2026-11-03T00:00:00+00:00")]
    conn.executemany("INSERT INTO taxi (user_id, kind, amount, party, rule, on_date, bank_ref, created_at)"
                     " VALUES (?, ?, ?, ?, ?, '2026-11-01', ?, ?)", rows)
    conn.execute("UPDATE user SET taxi_settled_at = '2026-11-02T00:00:00+00:00' WHERE user_id = ?", (ME,))
    conn.execute("PRAGMA user_version = 0")
    db.init(conn)
    db.init(conn)                                                   # only once
    got = [(e["name"], e["taxi"], e["taxi_done"], e["category_name"], e["created_at"][:10])
           for e in db.list_entries(conn, ME, *ALL)]
    assert got == [(PARTNER, "split", 0, "taxi", "2026-11-03"), ("SUNIL", "in", 1, "taxi", "2026-11-01")]


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


def taxi(conn, kind, amount, rule, name="U", uid=ME):
    cid = db.get_or_create_category(conn, uid, "taxi")
    return db.add_entry(conn, uid, kind, amount, name, cid, "2026-10-28", rule)


def test_taxi_pool(conn):
    for _ in range(10):                                              # 10 × ₹90 = ₹900 in
        taxi(conn, "earn", 90_00, "in")
    taxi(conn, "exp", 90_00, "refund")                               # one refunded
    taxi(conn, "exp", 200_00, "split", PARTNER)                      # sent to partner
    taxi(conn, "earn", 50_00, "split", PARTNER)                      # partner sent some back
    taxi(conn, "earn", 90_00, "in", uid=OTHER)
    add(conn, "earn", 90_00, "taxi", "2026-10-28")                   # an old hand entry: ordinary
    p = db.taxi_pool(conn, ME)
    assert p == {"received": 900_00, "received_n": 10, "refunded": 90_00, "refunded_n": 1,
                 "sent": 150_00, "sent_n": 2, "partner_half": 405_00, "mine": 405_00,
                 "carry": 0, "owed": 255_00, "settled_at": None}


def test_settling_adds_your_half_and_carries_what_is_owed(conn):
    for _ in range(12):
        taxi(conn, "earn", 90_00, "in")                              # ₹1,080 in
    eid = db.settle_taxi(conn, ME, dt.date(2026, 11, 13), "Taxi settled")   # before paying him
    e = db.get_entry(conn, ME, eid)
    assert (e["kind"], e["amount"], e["category_id"], e["taxi"]) == ("earn", 540_00, None, None)
    p = db.taxi_pool(conn, ME)
    assert (p["received"], p["mine"], p["owed"], p["carry"]) == (0, 0, 540_00, 540_00) and p["settled_at"]
    taxi(conn, "exp", 460_00, "split", PARTNER)                      # his share goes after
    assert db.taxi_pool(conn, ME)["owed"] == 80_00
    assert db.settle_taxi(conn, ME, dt.date(2026, 11, 13), "Taxi settled") is None   # no half to add
    assert db.taxi_pool(conn, ME)["carry"] == 80_00
    assert db.summary(conn, ME, *ALL)["earned"] == 540_00            # only your half counts
    assert db.taxi_pool(conn, OTHER)["settled_at"] is None


def test_salary_counts_only_spending_since_it_landed(conn):
    add(conn, "earn", 50000_00, "Salary", "2026-09-26")
    add(conn, "exp", 1000_00, "food", "2026-10-25")
    add(conn, "earn", 60000_00, "salary", "2026-10-26")
    add(conn, "exp", 500_00, "food", "2026-10-26")
    add(conn, "exp", 250_00, None, "2026-10-27")
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
