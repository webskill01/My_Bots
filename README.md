# Finance Tracker Bot

A Telegram bot for tracking expenses and daily earnings. Multi-tenant — every
Telegram user who starts it gets their own private ledger.

## Setup

1. Talk to [@BotFather](https://t.me/BotFather), send `/newbot`, copy the token.
2. `cp .env.example .env` and paste the token into `BOT_TOKEN=`.
3. `pip install -r requirements.txt`
4. `python -m finance_bot`

## Adding entries

Just send a message. No command needed.

| You type | Result |
|---|---|
| `250 lunch` | expense ₹250, today |
| `+3000 freelance` | earning ₹3000, today |
| `250 chai #food` | expense in the "food" category |
| `250 lunch yesterday` | dated yesterday |
| `250 chai 24 aug` | dated 24 August |
| `+3000 client 24/8` | earning dated 24 August |
| `250 auto 2d` | dated 2 days ago |

Order is flexible: `250 chai #food 24 aug` works. A `+` means earning, anything
else is an expense. Dates accept `today`, `yesterday`, `Nd`, `24/8`,
`24/08/2026`, `24 aug`, `24 august`, and `aug 24`.

## Commands

Each screen has its own command, and all of them show up when you type `/`.
`/menu` opens the same screens as buttons.

- **/summary** — earned, spent, net for a period, plus earnings per category
- **/day** — one day's total and its full entry list
- **/entries** — every entry, paged, tap to edit or delete
- **/categories** — earned and spent per category, tap for that category's list
- **/earn** — guided path if you'd rather tap than type
- **/settings** — timezone, currency and monthly budget

Tag earnings to split income by source: `+3000 payout #sofi`,
`+1500 driver-bot #taxi`. /summary and /categories then show each one's total.

## Monthly budget

Set one in Settings and the bot warns you twice a month, at most: once when you
cross 80% of it, and once when you go over. Expenses only — earnings don't
offset it. It resets on the 1st.

## Sharing with friends

Send them the bot link. That's it. Data is keyed on Telegram user ID, so nobody
sees anyone else's entries.

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

**Accounts:** the admin logs in as `admin` with `SCHEDULE_PIN`. Everyone else
joins through an invite link the admin makes in Settings → People (one use,
7 days), picking their own name and password. Each person has a private
schedule, and reminders go only to their own phones. The admin sees who has
joined and can disable an account, but never sees anyone's tasks.

**Screens:** Today (Now / Next, main goal, tick-off list), Week (Mon–Sun like
the Creator OS sheet), Upcoming (one-time tasks by date, filter by tag),
Settings (reminders, install, tags, timezone).

**Adding:** the + button opens a form (one time or repeating on chosen days,
time, tag). Or type on Today:

| You type | Result |
|---|---|
| `call mom 6pm` | today at 6 PM (tomorrow if 6 PM has passed) |
| `dentist tomorrow 10:30 #health` | dated, timed and tagged |
| `pay rent 5 oct` | on that date, no reminder |
| `gym 7am #daily` | repeats every day at 7 |

**Reminders:** Settings → Turn on reminders on each phone. Every notification
has ✅ Done and ⏰ 10 min. On Android, install the panel from Chrome's menu
(Add to Home screen). iPhone needs iOS 16.4+ and the installed app.

Missed while the server was down: one-time reminders still go out when it's
back; routine ones only if under 15 minutes late.
