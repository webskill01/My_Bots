# Finance Panel

A web panel for expenses and earnings at https://finance.easebuilds.in. Run with
`python -m finance_bot`. It serves on `127.0.0.1:FINANCE_PORT` (8098) behind
nginx, from `finance.db`. The panel always opens on Entries.

## Setup

1. `cp .env.example .env`, set `FINANCE_PIN` (and the Gmail keys below).
2. `pip install -r requirements.txt`
3. `python -m finance_bot`

## Adding entries

Type in the add box, or use the + button for a form.

| You type | Result |
|---|---|
| `250 lunch` | expense ₹250, today |
| `+3000 freelance` | earning ₹3000, today |
| `250 chai #food` | expense in the "food" category |
| `250 lunch yesterday` | dated yesterday |
| `250 chai 24 aug` | dated 24 August |
| `+3000 client 24/8` | earning dated 24 August |
| `250 auto 2d` | dated 2 days ago |

Order is flexible. A `+` means earning, anything else is an expense.

Views are per month with ◀ / ▶: Entries, Overview (spent, earned, net, budgets,
salary, taxi bot, spending by day and category), Categories, Months.

## Bank sync (Canara alert emails)

A thread inside the panel process polls Gmail over IMAP every 30 s for mail
from `canarabank@canarabank.com` and adds each UPI/IMPS/NEFT debit or credit
as an entry (tagged "bank"). It also keeps the balance from the latest alert.

- `.env`: `GMAIL_USER`, `GMAIL_APP_PASSWORD` (Google App Password, needs
  2-Step Verification and IMAP on), `BANK_PARTNER` (partner's UPI as shown in
  alerts). No Gmail keys = sync off.
- No history import: the first run only notes where the inbox is and records
  mail from then on. The bank ref number stops duplicates.
- An alert it can't read (e.g. a card swipe) shows on Entries as
  "Couldn't read a bank email". Add it by hand, then dismiss.

Auto categories:

| Alert | Category |
|---|---|
| ₹90 in | Taxi bot unclaimed |
| ₹90 out, or a whole ₹90s to the partner | Taxi bot refund |
| any other amount to the partner | Taxi bot split |

The Taxi bot card shows payments received, refunded, the partner's 50% of
what's left, what was sent, and what's still owed.

## Salary and budgets

Tag the salary credit "Salary". The Salary card counts spending from the day
the latest salary landed (taxi bot money excluded) and shows what's left.

Settings → Categories → Budget sets a monthly limit per category (empty or 0
clears it). Overview and Categories show progress bars.

## Accounts

Admin logs in as `admin` with `FINANCE_PIN` (falls back to `SCHEDULE_PIN`),
then sets their own password. Bank sync records into the admin's ledger.

## Tests

```
pytest -q
```

---

# Schedule Panel

A web panel for a daily routine and one-time tasks, with reminders as phone
notifications (Web Push) at each task's time. Lives at
https://schedule.easebuilds.in. Run with `python -m schedule_bot`; it serves
on `127.0.0.1:SCHEDULE_PORT` (8096) behind nginx.

Set `SCHEDULE_PIN` (6+ characters) in `.env`. Push needs HTTPS (or localhost).

**Accounts:** the admin first logs in as `admin` with `SCHEDULE_PIN`, then sets
their own name and password in Settings → Account (the PIN stops working).
Old accounts without a login get a claim link from People. Everyone else
joins through an invite link the admin makes in Settings → People (one use,
7 days), picking their own name and password. Each person has a private
schedule, and reminders go only to their own phones. The admin sees who has
joined and can disable an account, but never sees anyone's tasks.

**Screens:** Today (Now / Next, main goal, tick-off list), Week (Mon–Sun like
the Creator OS sheet), Upcoming (one-time tasks by date, filter by tag),
Settings (reminders, install, tags, timezone).

**Adding:** the form on Today has real pickers: one time (date) or repeats
(weekday chips), start time in IST, tag. More options adds an end time (a
10:00–12:00 block), an early reminder (5–60 min before) and notes.

**Panel-only:** a live IST clock and a now line through today, Now / Next /
Missed per block, ticking off a past day you forgot, a history of every tick,
and a Stats tab (completion, streak, per-tag and per-routine consistency).

**Reminders:** Settings → Turn on reminders on each phone. Every notification
has ✅ Done and ⏰ 10 min. On Android, install the panel from Chrome's menu
(Add to Home screen). iPhone needs iOS 16.4+ and the installed app.

Missed while the server was down: one-time reminders still go out when it's
back; routine ones only if under 15 minutes late.
