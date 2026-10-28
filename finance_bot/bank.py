"""Canara Bank alert emails -> entries in one ledger (the admin's).

A thread in the panel process polls Gmail over IMAP. Only mail that arrives
after the first start is read: the first run remembers where the mailbox ends
and starts from there, so nothing already entered by hand comes in twice.
Every entry it files can be corrected in the panel like any other.

Env: GMAIL_USER, GMAIL_APP_PASSWORD (Google account -> Security -> App
passwords), BANK_PARTNER (the partner's UPI handle exactly as the debit alerts
show it, e.g. 99xxxxxxxx@p).
"""

import datetime as dt
import email
import email.policy
import html
import imaplib
import logging
import os
import re
import threading
import time

from . import db, parse

log = logging.getLogger(__name__)

SENDER = "canarabank@canarabank.com"
# ponytail: All Mail so a Gmail filter that skips the inbox can't hide alerts.
# Accounts set to UK/German Gmail call it "[Google Mail]/All Mail".
MAILBOX = '"[Gmail]/All Mail"'
POLL = 30            # seconds between checks
RETRY = 120          # after an error, before reconnecting

TAXI = 90_00                          # every taxi bot payment is ₹90
UNCLAIMED = "Taxi bot unclaimed"      # ₹90 in from a user
SPLIT = "Taxi bot split"              # the partner's share, sent to them
REFUND = "Taxi bot refund"            # ₹90 back to a user, or repaying the partner who refunded
SALARY = "Salary"

STATUS = {"on": False, "checked_at": None, "error": None}   # read by the panel

_MONEY = r"[\d,]+(?:\.\d+)?"
_DATE = r"(?P<d>\d{2})/(?P<m>\d{2})/(?P<y>\d{2,4})"
# One per alert format. A new kind of alert lands in bank_miss until it gets one.
PATTERNS = [
    # "UPI/IMPS/MB Transaction Alert"
    re.compile(rf"INR (?P<amount>{_MONEY}) has been (?P<type>CREDITED|DEBITED) on {_DATE}"
               rf" (?:to|from) your account (?P<account>\S+) (?:from|to) (?P<party>.+?)"
               rf" with (?:\w+ )?Ref No\.?:\s?(?P<ref>\w+).*?Balance INR (?P<balance>{_MONEY})", re.I),
    # "Incoming NEFT/RTGS Transaction"
    re.compile(rf"INR (?P<amount>{_MONEY}) has been (?P<type>credited|debited) (?:to|from)"
               rf" (?P<account>\S+) on {_DATE} towards (?:NEFT|RTGS) by (?:Sender )?(?P<party>.+?),"
               rf" .*?UTR (?P<ref>\w+), Total Avail\. Bal INR (?P<balance>{_MONEY})", re.I),
]


def parse_alert(text: str) -> dict | None:
    text = " ".join(text.split())
    m = next(filter(None, (p.search(text) for p in PATTERNS)), None)
    if m is None:
        return None
    amount, balance = parse.parse_amount(m["amount"]), parse.parse_amount(m["balance"])
    if not amount or balance is None:
        return None
    y = int(m["y"])
    return {"kind": "earn" if m["type"].lower() == "credited" else "exp",
            "amount": amount, "party": m["party"].strip(), "ref": m["ref"],
            "balance": balance, "on_date": dt.date(y + 2000 if y < 100 else y, int(m["m"]), int(m["d"]))}


def category_for(t: dict, partner: str) -> str | None:
    """The owner's rules. A best guess: anything wrong gets fixed at night."""
    if t["kind"] == "earn":
        return UNCLAIMED if t["amount"] == TAXI else None
    if partner and t["party"].lower() == partner.lower():
        # whole ₹90s repay refunds he made for us; anything else is his share
        return REFUND if t["amount"] % TAXI == 0 else SPLIT
    return REFUND if t["amount"] == TAXI else None


def record(conn, user_id: int, t: dict, partner: str) -> int | None:
    """The new entry's id, or None when this transaction was already filed."""
    cat = category_for(t, partner)
    cid = db.get_or_create_category(conn, user_id, cat) if cat else None
    eid = db.add_bank_entry(conn, user_id, t["kind"], t["amount"], t["party"][:100], cid,
                            t["on_date"], t["ref"])
    db.set_bank_balance(conn, user_id, t["balance"])
    return eid


def read_mail(raw: bytes) -> tuple[str, str]:
    """(subject, body as plain text)."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    part = msg.get_body(("plain", "html"))
    text = part.get_content() if part is not None else ""
    if part is not None and part.get_content_type() == "text/html":
        text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return str(msg["Subject"] or ""), text


def poll(imap, conn, user_id: int, partner: str) -> int:
    """One pass over mail that arrived since the last one. Returns entries added."""
    last = db.get_user(conn, user_id)["bank_uid"]
    if last is None:   # first start: begin from now, import nothing
        _, data = imap.status(MAILBOX, "(UIDNEXT)")
        db.set_bank_uid(conn, user_id, int(re.search(rb"UIDNEXT (\d+)", data[0])[1]) - 1)
        return 0
    imap.select(MAILBOX, readonly=True)
    _, data = imap.uid("SEARCH", None, f'FROM "{SENDER}" UID {last + 1}:*')
    added = 0
    # "N:*" always matches the newest message, even when it's below N
    for n in sorted(u for u in map(int, data[0].split()) if u > last):
        _, fetched = imap.uid("FETCH", str(n), "(BODY.PEEK[])")
        subject, text = read_mail(fetched[0][1])
        t = parse_alert(text)
        if t is not None:
            added += record(conn, user_id, t, partner) is not None
        elif re.search(r"\b(debited|credited)\b", text, re.I):   # money, but a format we don't know
            log.warning("bank alert not understood: %r", subject)
            db.add_bank_miss(conn, user_id, subject[:200], " ".join(text.split())[:1000])
        db.set_bank_uid(conn, user_id, n)   # per mail: a crash mid-batch never re-reads one
    return added


def _run(db_path: str, user_id: int, login: tuple[str, str], partner: str) -> None:
    imap = None
    while True:
        try:
            if imap is None:
                imap = imaplib.IMAP4_SSL("imap.gmail.com", timeout=60)
                imap.login(*login)
            conn = db.connect(db_path)
            try:
                if n := poll(imap, conn, user_id, partner):
                    log.info("bank: %d new entries", n)
            finally:
                conn.close()
            STATUS.update(checked_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                          error=None)
            time.sleep(POLL)
        except Exception as e:   # keep the thread alive through network trouble and bad mail
            log.warning("bank sync failed: %s", e)
            STATUS["error"] = str(e)[:200]
            try:
                imap and imap.logout()
            except Exception:
                pass
            imap = None
            time.sleep(RETRY)


def start(db_path: str, user_id: int) -> bool:
    user = os.environ.get("GMAIL_USER", "")
    password = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not (user and password):
        log.info("bank sync off: set GMAIL_USER and GMAIL_APP_PASSWORD to turn it on")
        return False
    conn = db.connect(db_path)
    db.get_or_create_category(conn, user_id, SALARY)   # ready to pick when it lands
    conn.close()
    STATUS["on"] = True
    threading.Thread(target=_run, args=(db_path, user_id, (user, password),
                                        os.environ.get("BANK_PARTNER", "")),
                     daemon=True, name="bank").start()
    log.info("bank sync on for %s, ledger %s", user, user_id)
    return True
