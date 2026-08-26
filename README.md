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

## Menu

`/menu` opens everything else:

- **📊 Summary** — earned, spent, net for a period
- **📅 Day** — one day's total and its full entry list
- **📝 Entries** — every entry, paged, tap to edit or delete
- **📂 Categories** — totals per category, tap for that category's full list
- **💰 Add earning** — guided path if you'd rather tap than type
- **⚙️ Settings** — timezone and currency

## Sharing with friends

Send them the bot link. That's it. Data is keyed on Telegram user ID, so nobody
sees anyone else's entries.

## Tests

```
pytest -q
```
