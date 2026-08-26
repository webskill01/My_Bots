"""Handlers and keyboards. No SQL, no regex — those live in db.py and parse.py."""

import calendar
import datetime as dt
import html
import logging
from zoneinfo import ZoneInfo, available_timezones

from telegram import InlineKeyboardButton as Btn
from telegram import InlineKeyboardMarkup as Kb
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

from . import db, parse

log = logging.getLogger(__name__)

PAGE = 10
MAX_LINES = 50          # a Telegram message has a size limit; lists stay browsable
PERIODS = [("week", "This week"), ("month", "This month"),
           ("7d", "Last 7 days"), ("30d", "Last 30 days"),
           ("nd", "Last N days"), ("all", "All time")]
PERIOD_LABEL = dict(PERIODS)

WELCOME = (
    "<b>Finance Tracker</b>\n\n"
    "Just send me an amount and a name — no command needed.\n\n"
    "<code>250 lunch</code> — an expense\n"
    "<code>+3000 freelance</code> — an earning\n"
    "<code>250 chai #food</code> — with a category\n"
    "<code>250 chai 24 aug</code> — for an earlier day\n\n"
    "Dates take <code>today</code>, <code>yesterday</code>, <code>3d</code>, "
    "<code>24/8</code>, <code>24 aug</code> or <code>aug 24</code>, so you can "
    "always fill in a day you missed.\n\n"
    "/menu for summaries, editing and categories."
)


def _e(s) -> str:
    return html.escape(str(s or ""))


def _date(iso: str) -> dt.date:
    return dt.date.fromisoformat(iso)


def _fmt_date(d: dt.date) -> str:
    return d.strftime("%d %b")


def _local(created_at: str, user) -> dt.datetime:
    """created_at is stored in UTC — correct for a record, useless to read.
    Show it in the user's own timezone."""
    stamp = dt.datetime.fromisoformat(created_at)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=dt.timezone.utc)
    return stamp.astimezone(ZoneInfo(user["tz"]))


def _who(update: Update, context) -> tuple:
    """(conn, user_row). Creates the tenant on first contact."""
    conn = context.bot_data["conn"]
    return conn, db.get_or_create_user(conn, update.effective_user.id)


def _period(context) -> tuple[str, int | None]:
    return context.user_data.get("period", ("month", None))


def _range(context, today):
    key, n = _period(context)
    return parse.period_range(key, today, n)


def _period_name(context) -> str:
    key, n = _period(context)
    return f"Last {n} days" if key == "nd" else PERIOD_LABEL[key]


def _money(amount: int, user) -> str:
    return parse.fmt_money(amount, user["currency"])


def _signed(row, user) -> str:
    """Earnings lead with a +, so a list of both reads at a glance."""
    return ("+" if row["kind"] == "earn" else "") + _money(row["amount"], user)


# --- keyboards --------------------------------------------------------------

def menu_kb() -> Kb:
    return Kb([
        [Btn("📊 Summary", callback_data="sum"), Btn("📅 Day", callback_data="day")],
        [Btn("📝 Entries", callback_data="ent:0"), Btn("📂 Categories", callback_data="cat")],
        [Btn("💰 Add earning", callback_data="earn"), Btn("⚙️ Settings", callback_data="set")],
    ])


def period_kb(back: str) -> Kb:
    """One picker, reused by Summary, Entries and Categories."""
    rows, pair = [], []
    for key, label in PERIODS:
        pair.append(Btn(label, callback_data=f"per:{key}:{back}"))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([Btn("← Back", callback_data=back)])
    return Kb(rows)


def entry_kb(entry_id: int, fresh: bool = False) -> Kb:
    """The edit controls. `fresh` adds Undo, for a just-added entry."""
    rows = [
        [Btn("✏️ Amount", callback_data=f"e:{entry_id}:amt"),
         Btn("📝 Name", callback_data=f"e:{entry_id}:name")],
        [Btn("📂 Category", callback_data=f"e:{entry_id}:cat"),
         Btn("📅 Date", callback_data=f"e:{entry_id}:date")],
    ]
    if fresh:
        rows.append([Btn("✕ Undo", callback_data=f"e:{entry_id}:undo")])
    else:
        rows.append([Btn("🗑 Delete", callback_data=f"e:{entry_id}:del"),
                     Btn("← Back", callback_data="ent:0")])
    return Kb(rows)


# --- views: each returns (text, keyboard) -----------------------------------

def summary_view(conn, user, context) -> tuple[str, Kb]:
    today = db.user_today(user)
    start, end = _range(context, today)
    s = db.summary(conn, user["user_id"], start, end)

    span = f" · {_fmt_date(start)} – {_fmt_date(end)}" if start > dt.date.min else ""
    lines = [f"📊 <b>{_period_name(context)}</b>{span}", "",
             f"Earned   {_money(s['earned'], user)}",
             f"Spent    {_money(s['spent'], user)}",
             f"Net      {'+' if s['net'] >= 0 else ''}{_money(s['net'], user)}"]

    if user["budget"] and _period(context)[0] == "month":
        left = user["budget"] - s["spent"]
        lines.append(f"Budget   {_money(user['budget'], user)} · "
                     f"{_money(abs(left), user)} {'left' if left >= 0 else 'over'}")

    if s["top"]:
        top = " · ".join(f"{_e(t['name']) or '—'} {_money(t['total'], user)}"
                         for t in s["top"])
        lines += ["─────────────", f"Top: {top}"]
    if not s["count"]:
        lines += ["", "Nothing recorded in this period yet."]
    elif start > dt.date.min:
        days = (end - start).days + 1
        avg = s["spent"] // days // 100 * 100   # whole rupees; paise here are noise
        lines.append(f"{s['count']} entries · {_money(avg, user)}/day avg")
    else:
        lines.append(f"{s['count']} entries")  # "all time" has no meaningful daily avg

    return "\n".join(lines), period_kb("sum")


def day_view(conn, user, day: dt.date) -> tuple[str, Kb]:
    today = db.user_today(user)
    r = db.day_report(conn, user["user_id"], day)

    lines = [f"📅 <b>{day.strftime('%a, %d %b %Y')}</b>",
             f"Spent {_money(r['spent'], user)} · Earned {_money(r['earned'], user)} · "
             f"Net {'+' if r['net'] >= 0 else ''}{_money(r['net'], user)}", ""]
    if r["entries"]:
        for row in r["entries"][:MAX_LINES]:
            cat = f"  <i>{_e(row['category_name'])}</i>" if row["category_name"] else ""
            lines.append(f"  {_e(row['name']) or '—'}   {_signed(row, user)}{cat}")
        if len(r["entries"]) > MAX_LINES:
            lines.append(f"  …and {len(r['entries']) - MAX_LINES} more")
    else:
        lines.append("  No entries.")

    nav = [Btn("◀ Prev", callback_data=f"day:{day - dt.timedelta(days=1)}"),
           Btn("Today", callback_data=f"day:{today}")]
    if day < today:
        nav.append(Btn("Next ▶", callback_data=f"day:{day + dt.timedelta(days=1)}"))
    return "\n".join(lines), Kb([nav,
                                 [Btn("📆 Pick date", callback_data="day:pick"),
                                  Btn("← Back", callback_data="menu")]])


def entries_view(conn, user, context, page: int) -> tuple[str, Kb]:
    uid = user["user_id"]
    start, end = _range(context, db.user_today(user))
    total = db.count_entries(conn, uid, start, end)
    rows = db.list_entries(conn, uid, start, end, limit=PAGE, offset=page * PAGE)

    head = f"📝 <b>Entries</b> · {_period_name(context)} · {total} total"
    if not rows:
        return head + "\n\nNothing here yet.", period_kb("ent:0")

    lines = [head, f"Page {page + 1} of {(total + PAGE - 1) // PAGE}", ""]
    buttons = []
    for row in rows:
        cat = f" · {_e(row['category_name'])}" if row["category_name"] else ""
        lines.append(f"  {_fmt_date(_date(row['on_date']))}  {_e(row['name']) or '—'}"
                     f"   {_signed(row, user)}{cat}")
        buttons.append([Btn(f"{_fmt_date(_date(row['on_date']))} · "
                            f"{row['name'] or '—'} · {_signed(row, user)}",
                            callback_data=f"e:{row['id']}")])

    nav = []
    if page > 0:
        nav.append(Btn("◀ Newer", callback_data=f"ent:{page - 1}"))
    if (page + 1) * PAGE < total:
        nav.append(Btn("Older ▶", callback_data=f"ent:{page + 1}"))
    if nav:
        buttons.append(nav)
    buttons.append([Btn("🗓 Period", callback_data="ent:period"),
                    Btn("← Back", callback_data="menu")])
    return "\n".join(lines), Kb(buttons)


def entry_view(conn, user, entry_id: int) -> tuple[str, Kb] | None:
    row = db.get_entry(conn, user["user_id"], entry_id)
    if row is None:
        return None
    filed = _local(row["created_at"], user).strftime("%d %b %Y, %H:%M")
    kind = "Earning" if row["kind"] == "earn" else "Expense"
    lines = [f"<b>{kind}</b> · {_signed(row, user)}",
             f"Name: {_e(row['name']) or '—'}",
             f"Category: {_e(row['category_name']) if row['category_name'] else '—'}",
             f"Date: {_date(row['on_date']).strftime('%a, %d %b %Y')}",
             f"<i>filed {filed}</i>"]
    return "\n".join(lines), entry_kb(entry_id)


def cats_view(conn, user, context) -> tuple[str, Kb]:
    uid = user["user_id"]
    start, end = _range(context, db.user_today(user))
    totals = db.category_totals(conn, uid, start, end)
    named = {t["category_id"]: t for t in totals if t["category_id"]}

    lines = [f"📂 <b>Categories</b> · {_period_name(context)}", ""]
    buttons = []
    for cat in db.list_categories(conn, uid):
        t = named.get(cat["id"])
        spent = _money(t["total"], user) if t else _money(0, user)
        count = t["count"] if t else 0
        lines.append(f"  {_e(cat['name'])}   {spent}  ({count})")
        buttons.append([Btn(f"{cat['name']} · {spent}", callback_data=f"cat:{cat['id']}:0")])

    unc = next((t for t in totals if t["category_id"] is None), None)
    if unc:
        lines.append(f"  <i>Uncategorized</i>   {_money(unc['total'], user)}  ({unc['count']})")
        buttons.append([Btn(f"Uncategorized · {_money(unc['total'], user)}",
                            callback_data="cat:0:0")])
    if len(lines) == 2:
        lines.append("  No categories yet. Add one, or tag an entry with #food.")

    buttons.append([Btn("＋ New category", callback_data="cat:new"),
                    Btn("🗓 Period", callback_data="cat:period")])
    buttons.append([Btn("← Back", callback_data="menu")])
    return "\n".join(lines), Kb(buttons)


def cat_view(conn, user, context, cat_id: int, page: int) -> tuple[str, Kb]:
    uid = user["user_id"]
    start, end = _range(context, db.user_today(user))
    key = cat_id or None  # 0 is our stand-in for uncategorized
    cat = next((c for c in db.list_categories(conn, uid) if c["id"] == key), None)
    if key and cat is None:
        return "That category is gone.", Kb([[Btn("← Back", callback_data="cat")]])
    name = cat["name"] if cat else "Uncategorized"

    total = db.count_entries(conn, uid, start, end, category_id=key)
    rows = db.list_entries(conn, uid, start, end, limit=PAGE, offset=page * PAGE,
                           category_id=key, kind="exp")
    spent = sum(r["amount"] for r in
                db.list_entries(conn, uid, start, end, category_id=key, kind="exp"))

    lines = [f"📂 <b>{_e(name)}</b> · {_money(spent, user)} · {_period_name(context)}", ""]
    buttons = []
    for row in rows:
        lines.append(f"  {_fmt_date(_date(row['on_date']))}  {_e(row['name']) or '—'}"
                     f"   {_money(row['amount'], user)}")
        buttons.append([Btn(f"{_fmt_date(_date(row['on_date']))} · "
                            f"{row['name'] or '—'} · {_money(row['amount'], user)}",
                            callback_data=f"e:{row['id']}")])
    if not rows:
        lines.append("  Nothing in this period.")

    nav = []
    if page > 0:
        nav.append(Btn("◀ Newer", callback_data=f"cat:{cat_id}:{page - 1}"))
    if (page + 1) * PAGE < total:
        nav.append(Btn("Older ▶", callback_data=f"cat:{cat_id}:{page + 1}"))
    if nav:
        buttons.append(nav)
    if key:
        buttons.append([Btn("✏️ Rename", callback_data=f"cat:{cat_id}:ren"),
                        Btn("🗑 Delete", callback_data=f"cat:{cat_id}:del")])
    buttons.append([Btn("← Back", callback_data="cat")])
    return "\n".join(lines), Kb(buttons)


def settings_view(conn, user) -> tuple[str, Kb]:
    budget = (f"{_money(user['budget'], user)} / month" if user["budget"] else "not set")
    return ("⚙️ <b>Settings</b>\n\n"
            f"Timezone: <code>{_e(user['tz'])}</code>\n"
            f"Currency: <code>{_e(user['currency'])}</code>\n"
            f"Budget: <code>{_e(budget)}</code>\n\n"
            "<i>Timezone decides what counts as \"today\".</i>",
            Kb([[Btn("🌏 Timezone", callback_data="set:tz"),
                 Btn("💱 Currency", callback_data="set:cur")],
                [Btn("🎯 Monthly budget", callback_data="set:budget")],
                [Btn("← Back", callback_data="menu")]]))


# --- monthly budget ---------------------------------------------------------

BUDGET_LEVELS = (100, 80)   # checked high to low; the first match wins


def budget_alert(conn, user, today: dt.date | None = None) -> str | None:
    """Message to send, or None. Records the crossing, so one budget breach
    produces one warning rather than one per entry for the rest of the month."""
    budget = user["budget"]
    if not budget:
        return None

    today = today or db.user_today(user)
    spent = db.summary(conn, user["user_id"], today.replace(day=1), today)["spent"]
    level = next((pct for pct in BUDGET_LEVELS if spent * 100 >= budget * pct), 0)
    if not level:
        return None

    month = today.strftime("%Y-%m")
    if user["alert_month"] == month and (user["alert_level"] or 0) >= level:
        return None
    db.record_alert(conn, user["user_id"], month, level)

    left = budget - spent
    days = calendar.monthrange(today.year, today.month)[1] - today.day
    remaining = (f"{days} days left in the month" if days
                 else "and it's the last day of the month")
    if level == 100:
        return (f"🚨 <b>Over budget.</b>\n"
                f"{_money(spent, user)} of {_money(budget, user)} this month — "
                f"{_money(-left, user)} over, with {remaining}.")
    return (f"⚠️ <b>80% of your monthly budget.</b>\n"
            f"{_money(spent, user)} of {_money(budget, user)} — "
            f"{_money(left, user)} left, with {remaining}.")


def category_picker(conn, user, entry_id: int) -> tuple[str, Kb]:
    buttons = [[Btn(c["name"], callback_data=f"setc:{entry_id}:{c['id']}")]
               for c in db.list_categories(conn, user["user_id"])]
    buttons.append([Btn("＋ New", callback_data=f"setc:{entry_id}:new"),
                    Btn("✕ None", callback_data=f"setc:{entry_id}:0")])
    buttons.append([Btn("← Back", callback_data=f"e:{entry_id}")])
    return "Pick a category:", Kb(buttons)


def date_picker(entry_id: int, today: dt.date) -> tuple[str, Kb]:
    days = [("Today", today), ("Yesterday", today - dt.timedelta(days=1)),
            ("2 days ago", today - dt.timedelta(days=2)),
            ("3 days ago", today - dt.timedelta(days=3))]
    buttons = [[Btn(label, callback_data=f"ed:{entry_id}:{d}")] for label, d in days]
    buttons.append([Btn("📆 Type a date", callback_data=f"e:{entry_id}:datetyped")])
    buttons.append([Btn("← Back", callback_data=f"e:{entry_id}")])
    return "Which day does this belong to?", Kb(buttons)


# --- rendering --------------------------------------------------------------

async def _show(query, view) -> None:
    text, kb = view
    try:
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise


async def _confirm(message, conn, user, entry_id: int) -> None:
    row = db.get_entry(conn, user["user_id"], entry_id)
    tick = "💰" if row["kind"] == "earn" else "✅"
    cat = f" · {_e(row['category_name'])}" if row["category_name"] else ""
    day = _date(row["on_date"])
    when = "Today" if day == db.user_today(user) else day.strftime("%a, %d %b")
    await message.reply_text(
        f"{tick} {_signed(row, user)} · {_e(row['name']) or '—'}{cat}\n{when}",
        reply_markup=entry_kb(entry_id, fresh=True), parse_mode=ParseMode.HTML)


# --- commands ---------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _who(update, context)
    await update.message.reply_text(WELCOME, reply_markup=menu_kb(),
                                    parse_mode=ParseMode.HTML)


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _who(update, context)
    await update.message.reply_text("What do you want to look at?",
                                    reply_markup=menu_kb())


async def cmd_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conn, user = _who(update, context)
    text, kb = day_view(conn, user, db.user_today(user))
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


# --- text: either an answer to a prompt, or a new entry ---------------------

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conn, user = _who(update, context)
    uid = user["user_id"]
    text = (update.message.text or "").strip()
    pending = context.user_data.pop("pending", None)

    if pending:
        handled = await _handle_pending(update, context, conn, user, pending, text)
        if handled:
            return

    forced = "earn" if pending and pending["what"] == "earn" else None
    p = parse.parse_entry(text, db.user_today(user))
    if p is None:
        await update.message.reply_text(
            "I didn't catch an amount there.\n"
            "Try <code>250 lunch</code>, or <code>+3000 freelance</code> for income.",
            parse_mode=ParseMode.HTML)
        return

    cat_id = db.get_or_create_category(conn, uid, p.category) if p.category else None
    kind = forced or p.kind
    entry_id = db.add_entry(conn, uid, kind, p.amount, p.name, cat_id, p.on_date)
    await _confirm(update.message, conn, user, entry_id)

    if kind == "exp" and (alert := budget_alert(conn, user)):
        await update.message.reply_text(alert, parse_mode=ParseMode.HTML)


async def _handle_pending(update, context, conn, user, pending, text) -> bool:
    """True if the text was consumed by the prompt. False falls through to a new entry."""
    uid, what = user["user_id"], pending["what"]
    reply = update.message.reply_text

    if what == "earn":
        return False  # let the normal parser handle it, with kind forced

    if what == "amount":
        amount = parse.parse_amount(text)
        if not amount:
            context.user_data["pending"] = pending
            await reply("That isn't an amount. Try 250 or 250.50.")
            return True
        db.update_entry(conn, uid, pending["entry_id"], amount=amount)
        await _reshow(update, conn, user, pending["entry_id"])
        return True

    if what == "name":
        db.update_entry(conn, uid, pending["entry_id"], name=text[:100])
        await _reshow(update, conn, user, pending["entry_id"])
        return True

    if what == "date":
        day = parse.parse_date(text, db.user_today(user))
        if day is None:
            context.user_data["pending"] = pending
            await reply("I can't read that date. Try 24 aug, 24/8, or yesterday.")
            return True
        db.update_entry(conn, uid, pending["entry_id"], on_date=day)
        await _reshow(update, conn, user, pending["entry_id"])
        return True

    if what == "dayjump":
        day = parse.parse_date(text, db.user_today(user))
        if day is None:
            context.user_data["pending"] = pending
            await reply("I can't read that date. Try 24 aug, 24/8, or yesterday.")
            return True
        body, kb = day_view(conn, user, day)
        await reply(body, reply_markup=kb, parse_mode=ParseMode.HTML)
        return True

    if what in ("newcat", "newcat_for"):
        name = " ".join(text.split())[:32]
        if not name:
            await reply("A category needs a name.")
            return True
        cat_id = db.create_category(conn, uid, name)
        if cat_id is None:
            await reply(f"You already have a category called {name}.")
            return True
        if what == "newcat_for":
            db.update_entry(conn, uid, pending["entry_id"], category_id=cat_id)
            await _reshow(update, conn, user, pending["entry_id"])
        else:
            body, kb = cats_view(conn, user, context)
            await reply(body, reply_markup=kb, parse_mode=ParseMode.HTML)
        return True

    if what == "rencat":
        name = " ".join(text.split())[:32]
        if not name or not db.rename_category(conn, uid, pending["cat_id"], name):
            await reply("Couldn't rename it — that name may already be taken.")
            return True
        body, kb = cats_view(conn, user, context)
        await reply(body, reply_markup=kb, parse_mode=ParseMode.HTML)
        return True

    if what == "nd":
        if not text.isdigit() or not 1 <= int(text) <= 3650:
            context.user_data["pending"] = pending
            await reply("Give me a number of days between 1 and 3650.")
            return True
        context.user_data["period"] = ("nd", int(text))
        body, kb = _view_by_name(conn, user, context, pending["back"])
        await reply(body, reply_markup=kb, parse_mode=ParseMode.HTML)
        return True

    if what == "tz":
        if text not in available_timezones():
            context.user_data["pending"] = pending
            await reply("I don't know that timezone. Use a name like "
                        "<code>Asia/Kolkata</code> or <code>Europe/London</code>.",
                        parse_mode=ParseMode.HTML)
            return True
        db.set_setting(conn, uid, "tz", text)
        body, kb = settings_view(conn, db.get_or_create_user(conn, uid))
        await reply(body, reply_markup=kb, parse_mode=ParseMode.HTML)
        return True

    if what == "budget":
        amount = parse.parse_amount(text)
        if amount is None:
            context.user_data["pending"] = pending
            await reply("That isn't an amount. Try 20000, or 0 to switch it off.")
            return True
        db.set_setting(conn, uid, "budget", amount)
        body, kb = settings_view(conn, db.get_or_create_user(conn, uid))
        await reply(body, reply_markup=kb, parse_mode=ParseMode.HTML)
        return True

    if what == "currency":
        symbol = text.strip()
        if not 1 <= len(symbol) <= 3:
            context.user_data["pending"] = pending
            await reply("One to three characters, like ₹ or $ or USD.")
            return True
        db.set_setting(conn, uid, "currency", symbol)
        body, kb = settings_view(conn, db.get_or_create_user(conn, uid))
        await reply(body, reply_markup=kb, parse_mode=ParseMode.HTML)
        return True

    return False


async def _reshow(update, conn, user, entry_id: int) -> None:
    view = entry_view(conn, user, entry_id)
    if view is None:
        await update.message.reply_text("That entry is gone.")
        return
    await update.message.reply_text(view[0], reply_markup=view[1],
                                    parse_mode=ParseMode.HTML)


def _view_by_name(conn, user, context, name: str):
    if name.startswith("ent"):
        return entries_view(conn, user, context, 0)
    if name.startswith("cat"):
        return cats_view(conn, user, context)
    return summary_view(conn, user, context)


# --- the one callback router ------------------------------------------------

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()                       # first, always — buttons must not spin
    conn, user = _who(update, context)
    uid = user["user_id"]
    data = q.data
    head, _, rest = data.partition(":")

    if data == "menu":
        await _show(q, ("What do you want to look at?", menu_kb()))

    elif data == "sum":
        await _show(q, summary_view(conn, user, context))

    elif head == "per":
        key, _, back = rest.partition(":")
        if key == "nd":
            context.user_data["pending"] = {"what": "nd", "back": back}
            await q.message.reply_text("How many days back?")
            return
        context.user_data["period"] = (key, None)
        await _show(q, _view_by_name(conn, user, context, back))

    elif head == "day":
        if rest == "pick":
            context.user_data["pending"] = {"what": "dayjump"}
            await q.message.reply_text("Which day? e.g. 24 aug, 24/8, yesterday")
            return
        day = dt.date.fromisoformat(rest) if rest else db.user_today(user)
        await _show(q, day_view(conn, user, day))

    elif head == "ent":
        if rest == "period":
            await _show(q, ("Show entries for:", period_kb("ent:0")))
        else:
            await _show(q, entries_view(conn, user, context, int(rest)))

    elif head == "e":
        await _entry_action(q, context, conn, user, rest)

    elif head == "ed":
        entry_id, _, iso = rest.partition(":")
        db.update_entry(conn, uid, int(entry_id), on_date=dt.date.fromisoformat(iso))
        await _show(q, entry_view(conn, user, int(entry_id)) or
                    ("That entry is gone.", menu_kb()))

    elif head == "setc":
        entry_id, _, cid = rest.partition(":")
        if cid == "new":
            context.user_data["pending"] = {"what": "newcat_for", "entry_id": int(entry_id)}
            await q.message.reply_text("Name for the new category?")
            return
        db.update_entry(conn, uid, int(entry_id), category_id=int(cid) or None)
        await _show(q, entry_view(conn, user, int(entry_id)) or
                    ("That entry is gone.", menu_kb()))

    elif head == "cat":
        await _category_action(q, context, conn, user, rest)

    elif head == "set":
        if rest == "tz":
            context.user_data["pending"] = {"what": "tz"}
            await q.message.reply_text("Send your timezone, e.g. Asia/Kolkata")
        elif rest == "cur":
            context.user_data["pending"] = {"what": "currency"}
            await q.message.reply_text("Send a currency symbol, e.g. ₹")
        elif rest == "budget":
            context.user_data["pending"] = {"what": "budget"}
            await q.message.reply_text(
                "What's your monthly spending budget? e.g. 20000\n"
                "I'll warn you once at 80% and once when you go over.\n"
                "Send 0 to switch it off.")
        else:
            await _show(q, settings_view(conn, user))

    elif data == "earn":
        context.user_data["pending"] = {"what": "earn"}
        await q.message.reply_text("Send the earning — amount then name, "
                                   "e.g. 3000 freelance. Add a date if it's for "
                                   "an earlier day.")


async def _entry_action(q, context, conn, user, rest: str) -> None:
    uid = user["user_id"]
    entry_id, _, action = rest.partition(":")
    entry_id = int(entry_id)

    if action == "undo":
        db.delete_entry(conn, uid, entry_id)
        await _show(q, ("✕ Removed.", None))
    elif action == "amt":
        context.user_data["pending"] = {"what": "amount", "entry_id": entry_id}
        await q.message.reply_text("New amount?")
    elif action == "name":
        context.user_data["pending"] = {"what": "name", "entry_id": entry_id}
        await q.message.reply_text("New name?")
    elif action == "cat":
        await _show(q, category_picker(conn, user, entry_id))
    elif action == "date":
        await _show(q, date_picker(entry_id, db.user_today(user)))
    elif action == "datetyped":
        context.user_data["pending"] = {"what": "date", "entry_id": entry_id}
        await q.message.reply_text("Which date? e.g. 24 aug, 24/8, yesterday")
    elif action == "del":
        await _show(q, ("Delete this entry for good?",
                        Kb([[Btn("🗑 Yes, delete", callback_data=f"e:{entry_id}:delok"),
                             Btn("← Cancel", callback_data=f"e:{entry_id}")]])))
    elif action == "delok":
        db.delete_entry(conn, uid, entry_id)
        await _show(q, ("🗑 Deleted.", Kb([[Btn("← Entries", callback_data="ent:0")]])))
    else:
        await _show(q, entry_view(conn, user, entry_id) or
                    ("That entry is gone.", menu_kb()))


async def _category_action(q, context, conn, user, rest: str) -> None:
    uid = user["user_id"]
    if rest == "":
        await _show(q, cats_view(conn, user, context))
        return
    if rest == "new":
        context.user_data["pending"] = {"what": "newcat"}
        await q.message.reply_text("Name for the new category?")
        return
    if rest == "period":
        await _show(q, ("Show categories for:", period_kb("cat")))
        return

    cat_id, _, action = rest.partition(":")
    cat_id = int(cat_id)
    if action == "ren":
        context.user_data["pending"] = {"what": "rencat", "cat_id": cat_id}
        await q.message.reply_text("New name for this category?")
    elif action == "del":
        await _show(q, ("Delete this category?\n"
                        "<i>Its entries are kept — they just become uncategorized.</i>",
                        Kb([[Btn("🗑 Yes, delete", callback_data=f"cat:{cat_id}:delok"),
                             Btn("← Cancel", callback_data=f"cat:{cat_id}:0")]])))
    elif action == "delok":
        db.delete_category(conn, uid, cat_id)
        await _show(q, cats_view(conn, user, context))
    else:
        await _show(q, cat_view(conn, user, context, cat_id, int(action or 0)))


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("handler failed", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "Something broke on my side. Try that again.")
        except Exception:  # the reply itself can fail; don't loop on it
            pass


def build(token: str, conn) -> Application:
    app = Application.builder().token(token).build()
    app.bot_data["conn"] = conn
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("day", cmd_day))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    return app
