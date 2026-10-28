// Finance panel. Hash routes (Entries is home):
// #entries/<YYYY-MM>[/<cat id | 0 for none>]  #day/<YYYY-MM-DD>  #overview/<YYYY-MM>
// #categories/<YYYY-MM>  #months  #settings
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

// Dates are 'YYYY-MM-DD' strings in the user's timezone (the server says
// what today is). UTC math on them keeps the browser's timezone out of it.
const D = s => new Date(s + 'T00:00:00Z');
const iso = d => d.toISOString().slice(0, 10);
const addDays = (s, n) => iso(new Date(D(s).getTime() + n * 864e5));
const wd = s => (D(s).getUTCDay() + 6) % 7;                  // Mon = 0
const fmtDate = (s, o) => D(s).toLocaleDateString('en-IN', { timeZone: 'UTC', ...o });
const monthName = (m, short) => fmtDate(m + '-01', { month: short ? 'short' : 'long', year: 'numeric' });
const addMonths = (m, n) => { const [y, mo] = m.split('-').map(Number); const t = y * 12 + mo - 1 + n; return `${Math.floor(t / 12)}-${String(t % 12 + 1).padStart(2, '0')}`; };
const daysIn = m => { const [y, mo] = m.split('-').map(Number); return new Date(Date.UTC(y, mo, 0)).getUTCDate(); };
const isMonth = s => /^\d{4}-(0[1-9]|1[0-2])$/.test(s || '');
const isDate = s => /^\d{4}-\d{2}-\d{2}$/.test(s || '') && !isNaN(D(s));
const fmtTime = hm => { if (!hm) return ''; const [h, m] = hm.split(':').map(Number); return `${h % 12 || 12}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`; };
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
function dayLabel(d) {
  return d === S.today ? 'Today' : d === addDays(S.today, -1) ? 'Yesterday' : fmtDate(d, { weekday: 'long' });
}

// Amounts arrive in paise. Indian grouping (1,23,456); paise only when there are any.
const money = (p, sign) => `${sign && p > 0 ? '+' : ''}${p < 0 ? '−' : ''}${S.currency}${(Math.abs(p) / 100).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
// For tight spots like calendar cells: ₹840, ₹1.2k, ₹1.5L
function short(p) {
  const r = p / 100;
  const n = r >= 1e5 ? (r / 1e5).toFixed(r >= 1e6 ? 0 : 1) + 'L' : r >= 1e3 ? (r / 1e3).toFixed(r >= 1e4 ? 0 : 1) + 'k' : Math.round(r);
  return S.currency + String(n).replace('.0', '');
}
const pct = (a, b) => (b ? Math.min(100, Math.round(a * 100 / b)) : 0);
const paise = s => Math.round(parseFloat(String(s).replace(/[,\s₹$]/g, '')) * 100) || 0;

const PALETTE = ['#2563eb', '#1f7a4a', '#a8660b', '#d6336c', '#7048e8', '#0b6e76', '#c2410c', '#0e7490'];
const tc = name => { if (!name) return '#9a9a92'; let h = 0; for (const c of name.toLowerCase()) h = (h * 31 + c.charCodeAt(0)) >>> 0; return PALETTE[h % PALETTE.length]; };

const ICON = {
  overview: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  entries: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  categories: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  months: '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M8 3v4M16 3v4M3 10h18"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  prev: '<path d="M15 18l-6-6 6-6"/>',
  next: '<path d="M9 18l6-6-6-6"/>',
};
const svg = k => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[k]}</svg>`;
const TABS = [['entries', 'Entries'], ['overview', 'Overview'], ['categories', 'Categories'], ['months', 'Months'], ['settings', 'Settings']];
const MONTHLY = ['entries', 'overview', 'categories'];

let S = null;              // /api/state for one month
let kindFilter = 'all';
let query = '';

// ---- helpers ----
function toast(msg, err) {
  const t = $('#toast');
  t.textContent = msg; t.className = 'toast show' + (err ? ' err' : '');
  clearTimeout(toast.t); toast.t = setTimeout(() => (t.className = 'toast'), 3200);
}
async function api(path, body) {
  const res = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {});
  const data = await res.json().catch(() => ({ error: 'Network error. Try again.' }));
  if (!res.ok) throw Object.assign(new Error(data.error || 'Something went wrong.'), { status: res.status });
  return data;
}
async function busy(btn, fn) {
  if (btn) btn.disabled = true;
  try { await fn(); } catch (e) { if (e.status === 401) showLogin(); else toast(e.message, true); } finally { if (btn) btn.disabled = false; }
}
function ask(title, text, yes = 'OK', danger = false) {
  const d = $('#dlg');
  $('#dlgTitle').textContent = title; $('#dlgText').textContent = text;
  $('#dlgYes').textContent = yes; $('#dlgYes').className = 'b ' + (danger ? 'warn' : 'primary');
  d.returnValue = '';
  d.showModal();
  return new Promise(ok => d.addEventListener('close', () => ok(d.returnValue === 'yes'), { once: true }));
}
$('#dlgYes').onclick = () => $('#dlg').close('yes');
$('#dlgNo').onclick = () => $('#dlg').close('no');

// ---- the month's numbers ----
const thisMonth = () => S.today.slice(0, 7);
function totals(list) {
  let spent = 0, earned = 0;
  list.forEach(e => (e.kind === 'exp' ? (spent += e.amount) : (earned += e.amount)));
  return { spent, earned, net: earned - spent };
}
// [{id, name, total, count}] for one kind, biggest first, uncategorized last
function byCategory(kind, list = S.entries) {
  const g = {};
  list.filter(e => e.kind === kind).forEach(e => {
    const k = e.category_id || 0;
    g[k] = g[k] || { id: k, name: e.category, total: 0, count: 0 };
    g[k].total += e.amount; g[k].count++;
  });
  return Object.values(g).sort((a, b) => !a.id - !b.id || b.total - a.total);
}
const spentOn = d => S.entries.filter(e => e.kind === 'exp' && e.on_date === d).reduce((a, e) => a + e.amount, 0);
const catTag = e => (e.category ? `<span class="tag" style="--tc:${tc(e.category)}">${esc(e.category)}</span>` : '');
const bankTag = e => (e.bank ? '<span class="tag" style="--tc:#0b6e76" title="Recorded from a bank alert">bank</span>' : '');
const byTime = (a, b) => a.time.localeCompare(b.time) || a.id - b.id;

// an entry row; `timed` puts the time it was added in its own column
function row(e, timed) {
  const meta = [catTag(e), bankTag(e), timed ? '' : `<span>${fmtTime(e.time)}</span>`].filter(Boolean).join('');
  return `<div class="row ${e.kind} ${timed ? 'timed' : ''}" data-open="${e.id}" tabindex="0" style="--tc:${e.category ? tc(e.category) : 'var(--line)'}">
    ${timed ? `<div class="tm">${fmtTime(e.time).replace(' ', '<small>')}</small></div>` : ''}
    <div style="min-width:0"><div class="t1">${esc(e.name) || '<span class="muted">—</span>'}</div>${meta ? `<div class="t2">${meta}</div>` : ''}</div>
    <div class="amt">${money(e.amount, e.kind === 'earn')}</div></div>`;
}
function wireRows() {
  $$('[data-open]').forEach(r => {
    r.onclick = () => openEdit(S.entries.find(e => e.id === +r.dataset.open));
    r.onkeydown = ev => { if (ev.key === 'Enter') r.click(); };
  });
}

// ◀ Month ▶ — the same control on every monthly view
function monthNav(view, m) {
  const cur = m === thisMonth();
  return `<div class="nav">
    <a class="b icon line" href="#${view}/${addMonths(m, -1)}" aria-label="Previous month">${svg('prev')}</a>
    <a class="b line ${cur ? 'gap' : ''}" href="#${view}/${thisMonth()}" ${cur ? 'tabindex="-1" aria-hidden="true"' : ''}>This month</a>
    <a class="b icon line" href="#${view}/${addMonths(m, 1)}" aria-label="Next month" ${cur ? 'hidden' : ''}>${svg('next')}</a>
  </div>`;
}
function head(view, title, sub) {
  return `<div class="head"><div><h1>${esc(title)}</h1><p class="sub">${sub}</p></div>${monthNav(view, S.month)}</div>`;
}

// ---- shell ----
$('.top .tabs').innerHTML = TABS.map(([k, l]) => `<a href="#${k}" data-tab="${k}">${l}</a>`).join('');
$('.bottom').innerHTML = TABS.map(([k, l]) => `<a href="#${k}" data-tab="${k}">${svg(k)}${l}</a>`).join('');
$('.brand').setAttribute('href', '#entries');
function showLogin() {
  $('#app').hidden = true; $('#joinSec').hidden = true; $('#login').hidden = false;
  try { $('#un').value = $('#un').value || localStorage.getItem('finName') || ''; } catch (e) {}
}
$('#loginForm').onsubmit = async e => {
  e.preventDefault();
  $('#loginErr').hidden = true;
  try {
    await api('/api/login', { name: $('#un').value, password: $('#pw').value });
    try { localStorage.setItem('finName', $('#un').value.trim()); } catch (err) {}
    $('#pw').value = ''; $('#login').hidden = true; refresh(true);
  } catch (err) { $('#loginErr').textContent = err.message; $('#loginErr').hidden = false; }
};

// ---- joining from an invite link: /join/<token> ----
const joinToken = (location.pathname.match(/^\/join\/([\w-]{20,64})$/) || [])[1];
async function startJoin() {
  $('#login').hidden = true; $('#app').hidden = true; $('#joinSec').hidden = false;
  try {
    const inv = await api(`/api/invite/${joinToken}`);
    $('#joinSub').textContent = inv.claim_entries ? `Your ledger is ready (${inv.claim_entries} entries from Telegram). Pick a name and password to take it over.`
      : inv.label ? `Invite for ${inv.label} · create your account` : 'Create your account';
    if (inv.label && !inv.claim_entries && !$('#jName').value) $('#jName').value = inv.label;
  } catch (err) {
    $('#joinForm').innerHTML = `<p class="err" style="margin:0">${esc(err.message)}</p><p class="muted small" style="margin-top:8px">Ask for a new link, or <a href="/">log in</a> if you already have an account.</p>`;
  }
}
$('#joinForm').onsubmit = async e => {
  e.preventDefault();
  $('#joinErr').hidden = true;
  if ($('#jPw').value !== $('#jPw2').value) { $('#joinErr').textContent = 'The two passwords don’t match.'; $('#joinErr').hidden = false; return; }
  const btn = e.submitter || $('#joinForm button[type=submit]'); btn.disabled = true;
  try {
    await api('/api/join', { token: joinToken, name: $('#jName').value, password: $('#jPw').value });
    try { localStorage.setItem('finName', $('#jName').value.trim()); } catch (err) {}
    history.replaceState(null, '', '/#entries');
    $('#joinSec').hidden = true;
    refresh(true);
    toast('Welcome! Add your first entry with the box at the top.');
  } catch (err) { $('#joinErr').textContent = err.message; $('#joinErr').hidden = false; }
  finally { btn.disabled = false; }
};

const VIEWS = { entries: entriesView, day: dayView, overview: overviewView, categories: categoriesView, months: monthsView, settings: settingsView };
function route() {
  let [name, ...arg] = location.hash.slice(1).split('/');
  if (!VIEWS[name] || (name === 'day' && !isDate(arg[0]))) [name, arg] = ['entries', []];
  const tab = name === 'day' ? 'entries' : name;
  $$('[data-tab]').forEach(a => (a.dataset.tab === tab ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current')));
  return [name, arg];
}
// The month a view wants: from the hash, else the one already loaded.
function wantedMonth() {
  const [name, arg] = route();
  if (name === 'day') return arg[0].slice(0, 7);
  return MONTHLY.includes(name) && isMonth(arg[0]) ? arg[0] : S ? S.month : '';
}
let shown = '';            // the route last drawn: a new one gets the entrance animation
let fromHome = false;      // a day page opened from Entries: its back link is history.back()
const calm = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
function render(force = true) {
  if (!S) return;
  const [name, arg] = route();
  $('#who').textContent = S.me.name || '';
  $('#fab').hidden = name === 'settings';
  // never redraw under the user's fingers: a dialog, or typing
  const typing = document.activeElement && $('#view').contains(document.activeElement) && document.activeElement.tagName === 'INPUT';
  if ($('#dlg').open || $('#edit').open || (!force && typing)) return;
  const y = window.scrollY, key = location.hash || '#entries';
  const fresh = key !== shown;
  shown = key;
  const v = $('#view');
  v.ontouchstart = v.ontouchend = null;
  const dir = slideIn;
  VIEWS[name](...arg);
  v.classList.remove('enter', 'slide-l', 'slide-r');
  // a swiped month card slides by itself; everything else fades up
  if (fresh && !(dir && name === 'entries')) { void v.offsetWidth; v.classList.add(name === 'day' && dir ? 'slide-' + dir : 'enter'); }
  if (name === 'day') slideIn = '';
  window.scrollTo(0, y);
}
// links marked data-replace move without adding a Back step; day links opened
// from Entries remember they came from home
document.addEventListener('click', e => {
  const a = e.target.closest('a[href^="#"]');
  if (!a) return;
  if (a.hasAttribute('data-replace')) {
    e.preventDefault();
    if (a.dataset.dir) slideIn = a.dataset.dir;
    location.replace(a.getAttribute('href'));
  } else if (a.id !== 'goHome') {
    fromHome = a.getAttribute('href').startsWith('#day/') && route()[0] === 'entries';
  }
});
window.addEventListener('hashchange', async () => {
  if (route()[0] === 'settings') A = null;   // people and invites, fresh each visit
  if (S && wantedMonth() !== S.month) await refresh(true); else render();
  window.scrollTo(0, 0);
});

async function refresh(force) {
  clearTimeout(refresh.t);
  try {
    const m = wantedMonth();
    const st = await api('/api/state' + (m ? `?month=${m}` : ''));
    $('#login').hidden = true; $('#app').hidden = false;
    const changed = force || !S || JSON.stringify(st) !== JSON.stringify(S);
    S = st;
    if (changed) render(!!force);
  } catch (e) {
    if (e.status === 401) showLogin();
    else if (S) toast('Connection lost, retrying…', true);
  }
  refresh.t = setTimeout(refresh, 60000);
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });

// Go wherever a just-saved day lives: that day's page, or its month.
async function showSaved(day) {
  const [name] = route();
  const target = name === 'day' ? `#day/${day}` : day.slice(0, 7) !== S.month && MONTHLY.includes(name) ? `#${name}/${day.slice(0, 7)}` : '';
  if (target && target !== location.hash) location.hash = target; else await refresh(true);
}

// ---- quick add: "250 lunch #food 24 aug", the same words the bot took ----
let draft = '';
function quickAddHtml() {
  return `<form class="card add" id="quick" autocomplete="off">
    <div class="add-top">
      <input id="qText" placeholder="250 lunch #food" value="${esc(draft)}" aria-label="New entry" enterkeyhint="done">
      <button class="b primary" type="submit">Add</button>
      <button class="b line" type="button" id="qForm">Several</button>
    </div>
    <p class="hint"><code>+3000 salary</code> for income · <code>#food</code> sets a category · end with <code>24 aug</code> or <code>yesterday</code> for another day</p>
  </form>`;
}
function wireQuickAdd() {
  $('#qText').oninput = e => (draft = e.target.value);
  $('#qForm').onclick = () => openAdd(defaultDay());
  $('#quick').onsubmit = e => {
    e.preventDefault();
    if (!draft.trim()) return $('#qText').focus();
    busy(e.submitter, async () => {
      const { entry } = await api('/api/quick', { text: draft });
      draft = '';
      toast(`${entry.kind === 'earn' ? 'Earned' : 'Spent'} ${money(entry.amount)}${entry.name ? ' · ' + entry.name : ''} · ${fmtDate(entry.on_date, { day: 'numeric', month: 'short' })}`);
      await showSaved(entry.on_date);
      $('#qText') && $('#qText').focus();
    });
  };
}

// ---- bank sync: alerts it couldn't read, and trouble reaching Gmail ----
function bankNotice() {
  const b = S.bank;
  if (!b) return '';
  return b.misses.map(x => `<div class="note warn">Couldn’t read a bank email: <b>${esc(x.subject)}</b>
      <div class="small" style="font-weight:400;margin-top:4px">${esc(x.body.slice(0, 240))}</div>
      <div class="acts"><button class="b sm line" data-miss="${x.id}" type="button">Added it by hand · dismiss</button></div></div>`).join('')
    + (b.error ? `<div class="note warn">Bank sync can’t reach Gmail right now: ${esc(b.error)}</div>` : '');
}
function wireBankNotice() {
  $$('[data-miss]').forEach(btn => btn.onclick = () => busy(btn, async () => {
    await api(`/api/bank/miss/${btn.dataset.miss}/dismiss`, {}); await refresh(true);
  }));
}

// ---- money right now: bank balance, salary left, what the partner is owed ----
const TAXI_IN = 'taxi bot unclaimed';
const meterColor = (used, cap) => (used > cap ? 'var(--bad)' : used * 100 >= cap * 80 ? 'var(--deep)' : 'var(--ok)');
const hasTaxi = () => S.taxi.received_n || S.taxi.sent_n || S.taxi.refunded_n;
function nowTiles() {
  const tiles = [];
  if (S.bank && S.bank.balance != null) tiles.push(`<div class="tile"><div class="l">In the bank</div><div class="v">${money(S.bank.balance)}</div><div class="s">from the latest alert</div></div>`);
  if (S.salary) tiles.push(`<div class="tile"><div class="l">Salary left</div><div class="v ${S.salary.left < 0 ? 'neg' : 'pos'}">${money(S.salary.left)}</div><div class="s">${money(S.salary.spent)} spent since ${esc(fmtDate(S.salary.on_date, { day: 'numeric', month: 'short' }))}</div></div>`);
  if (hasTaxi()) tiles.push(`<div class="tile"><div class="l">${S.taxi.owed < 0 ? 'Partner overpaid' : 'Owed to partner'}</div><div class="v">${money(Math.abs(S.taxi.owed))}</div><div class="s">taxi bot, all time</div></div>`);
  return tiles.length ? `<div class="tiles">${tiles.join('')}</div>` : '';
}
function salaryCard() {
  const s = S.salary;
  if (!s) return '';
  return `<div class="card budget">
    <div class="top-l"><span>Salary ${money(s.amount)} · ${esc(fmtDate(s.on_date, { day: 'numeric', month: 'short' }))}</span><span class="${s.left < 0 ? 'neg' : 'muted'}">${s.left < 0 ? money(-s.left) + ' over' : money(s.left) + ' left'}</span></div>
    <div class="meter" style="--tc:${meterColor(s.spent, s.amount)}"><i style="--v:${pct(s.spent, s.amount)}"></i></div>
    <p class="hint">${pct(s.spent, s.amount)}% used since it landed · taxi bot money isn’t counted</p></div>`;
}
function taxiCard() {
  if (!hasTaxi()) return '';
  const t = S.taxi;
  const month = S.entries.filter(e => e.kind === 'earn' && (e.category || '').toLowerCase() === TAXI_IN).length;
  const line = (l, n, v, cls = '') => `<div class="mrow"><span class="ml">${l}</span><span class="muted small">${n}</span><span class="mv ${cls}">${v}</span></div>`;
  return `<div class="card"><h2>Taxi bot</h2>
    ${line('Received', `${t.received_n} payments`, money(t.received, true), 'pos')}
    ${line('Refunded', `${t.refunded_n}×`, money(t.refunded))}
    ${line('Partner’s half', 'of what’s left', money(t.partner_half))}
    ${line('Sent to partner', `${t.sent_n}×`, money(t.sent))}
    ${line(t.owed < 0 ? 'Overpaid' : 'Still owed', '', money(Math.abs(t.owed)), t.owed > 0 ? 'neg' : '')}
    <p class="hint">All time. ${month} ${month === 1 ? 'payment' : 'payments'} in ${esc(monthName(S.month))}. ₹90 in is filed as “Taxi bot unclaimed”, ₹90 out (or whole ₹90s to your partner) as “Taxi bot refund”, other amounts to your partner as “Taxi bot split”.</p></div>`;
}
// categories with their own monthly budget, against this month's spending
function budgetsCard(spentBy) {
  const list = S.categories.filter(c => c.budget);
  if (!list.length) return '';
  return `<div class="card"><h2>Category budgets</h2>${list.map(c => {
    const s = (spentBy.find(x => x.id === c.id) || { total: 0 }).total;
    return `<a class="mrow" href="#entries/${S.month}/${c.id}">
      <span class="ml"><span class="dot" style="--tc:${tc(c.name)}"></span>${esc(c.name)}</span>
      <div class="meter" style="--tc:${meterColor(s, c.budget)}"><i style="--v:${pct(s, c.budget)}"></i></div>
      <span class="mv">${money(s)}<small>of ${money(c.budget)} · ${s > c.budget ? money(s - c.budget) + ' over' : money(c.budget - s) + ' left'}</small></span></a>`;
  }).join('')}</div>`;
}

// ---- Entries (home): the month as a calendar, then every entry by day ----
// The month card on Entries: name, totals, then the calendar. Swipe it (or use
// the arrow keys / the desktop chevrons) to change month.
function monthCard(m) {
  const days = daysIn(m), lead = wd(m + '-01'), cur = m === thisMonth(), t = totals(S.entries);
  const dayOf = i => `${m}-${String(i + 1).padStart(2, '0')}`;
  const spent = [...Array(days)].map((_, i) => spentOn(dayOf(i)));
  const earned = [...Array(days)].map((_, i) => S.entries.filter(e => e.kind === 'earn' && e.on_date === dayOf(i)).reduce((a, e) => a + e.amount, 0));
  // shade against a typical day, not the peak: one rent day mustn't wash out the rest
  const sorted = spent.filter(Boolean).sort((a, b) => a - b);
  const ref = sorted.length ? sorted[Math.floor(sorted.length * 0.8)] || sorted[sorted.length - 1] : 1;
  const level = v => (!v ? 0 : v >= ref * 1.5 ? 4 : v >= ref ? 3 : v >= ref * 0.45 ? 2 : 1);
  const topEarn = Math.max(1, ...earned);
  const cells = spent.map((v, i) => {
    const d = dayOf(i), e = earned[i];
    const label = `${fmtDate(d, { weekday: 'long', day: 'numeric', month: 'long' })}: ${v ? money(v) + ' spent' : 'nothing spent'}${e ? ', ' + money(e) + ' earned' : ''}`;
    return `<a class="cd lv${level(v)} ${d === S.today ? 'today' : ''} ${d > S.today ? 'future' : ''}" href="#day/${d}" style="--i:${i}" aria-label="${esc(label)}" title="${esc(label)}">
      <b>${i + 1}</b><span>${v ? short(v) : ''}</span>${e ? `<em class="ea">+${short(e)}</em><i class="eb" style="--f:${Math.max(0.3, e / topEarn).toFixed(2)}"></i>` : ''}</a>`;
  });
  return `<section class="card month ${slideIn ? 'slide-' + slideIn : ''}" id="monthCard" tabindex="-1" aria-label="${esc(monthName(m))}">
    <div class="m-top">
      <button class="chev" data-month="-1" aria-label="Previous month" type="button">${svg('prev')}</button>
      <div class="m-name"><h1>${esc(monthName(m))}</h1>${cur ? '<span class="pill">this month</span>' : `<a class="pill now" href="#entries/${thisMonth()}" data-replace>back to this month</a>`}</div>
      <button class="chev" data-month="1" aria-label="Next month" type="button" ${cur ? 'disabled' : ''}>${svg('next')}</button>
    </div>
    <div class="m-stats">
      <div><span>Spent</span><b class="sp">${money(t.spent)}</b></div>
      <div><span>Earned</span><b class="pos">${money(t.earned, true)}</b></div>
      <div><span>Net</span><b class="${t.net < 0 ? 'neg' : 'pos'}">${money(t.net, true)}</b></div>
      <div><span>Entries</span><b>${S.entries.length}</b></div>
    </div>
    ${S.budget ? `<div class="meter m-budget" style="--tc:${t.spent > S.budget ? 'var(--bad)' : t.spent * 100 >= S.budget * 80 ? 'var(--deep)' : 'var(--ok)'}" title="Budget ${money(S.budget)}: ${pct(t.spent, S.budget)}% used"><i style="--v:${pct(t.spent, S.budget)}"></i></div>` : ''}
    <div class="cal">${DAYS.map(d => `<span class="cal-h">${d.slice(0, 2)}</span>`).join('')}
      ${'<span></span>'.repeat(lead)}${cells.join('')}</div>
    <div class="cal-legend"><span><i style="background:color-mix(in srgb,var(--spend) 22%,#fff)"></i>spent: darker = more</span><span><i style="background:var(--ok)"></i>earned</span><span class="swipe-hint">Swipe for other months</span></div>
  </section>`;
}
let slideIn = '';   // 'l' or 'r': which way the next card or day slides in
function goMonth(step) {
  const m = addMonths(S.month, step);
  if (m > thisMonth()) {   // no future months: a small shake instead
    const c = $('#monthCard');
    if (c && !calm()) c.animate([{ transform: 'translateX(0)' }, { transform: 'translateX(-10px)' }, { transform: 'translateX(5px)' }, { transform: 'none' }], 260);
    return;
  }
  slideIn = step > 0 ? 'r' : 'l';
  location.replace(`#entries/${m}`);   // months don't pile up in Back
}
function wireMonthCard() {
  const c = $('#monthCard');
  slideIn = '';
  if (!c) return;
  $$('[data-month]', c).forEach(b => b.onclick = () => goMonth(+b.dataset.month));
  c.onkeydown = e => { if (e.key === 'ArrowLeft') goMonth(-1); if (e.key === 'ArrowRight') goMonth(1); };
  // the card follows the finger a little, then a flick changes month
  let x0 = null, y0 = 0, dx = 0, lock = null;
  c.addEventListener('touchstart', e => { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; dx = 0; lock = null; c.style.transition = 'none'; }, { passive: true });
  c.addEventListener('touchmove', e => {
    if (x0 === null) return;
    dx = e.touches[0].clientX - x0;
    const dy = e.touches[0].clientY - y0;
    if (lock === null && Math.abs(dx) + Math.abs(dy) > 8) lock = Math.abs(dx) > Math.abs(dy) ? 'x' : 'y';
    if (lock === 'x') c.style.transform = `translateX(${dx * 0.35}px)`;
  }, { passive: true });
  c.addEventListener('touchend', () => {
    c.style.transition = ''; c.style.transform = '';
    if (lock === 'x' && Math.abs(dx) > 60) goMonth(dx < 0 ? 1 : -1);
    x0 = null;
  });
}

function entriesView(_, cat) {
  const m = S.month;
  const catId = cat === undefined || cat === '' ? null : +cat;
  const catName = catId === null ? '' : catId ? (S.categories.find(c => c.id === catId) || {}).name || 'Category' : 'Uncategorized';
  const q = query.trim().toLowerCase();
  const filtered = kindFilter !== 'all' || catId !== null || q;
  const list = S.entries.filter(e => (kindFilter === 'all' || e.kind === kindFilter)
    && (catId === null || (e.category_id || 0) === catId)
    && (!q || (e.name || '').toLowerCase().includes(q) || (e.category || '').toLowerCase().includes(q)));
  const t = totals(list);
  const groups = {};
  list.forEach(e => (groups[e.on_date] = groups[e.on_date] || []).push(e));
  $('#view').innerHTML = `
    ${quickAddHtml()}
    ${bankNotice()}
    ${catId === null ? monthCard(m) : head('entries', catName, `${esc(monthName(m))} · ${list.length} ${list.length === 1 ? 'entry' : 'entries'} · spent ${money(t.spent)}${t.earned ? ` · earned ${money(t.earned, true)}` : ''}`)}
    <div class="chips" role="group" aria-label="Filter" style="margin-top:14px">
      ${[['all', 'All'], ['exp', 'Spent'], ['earn', 'Earned']].map(([k, l]) => `<button class="chip" data-kind-f="${k}" aria-pressed="${kindFilter === k}">${l}</button>`).join('')}
      ${catId !== null ? `<a class="chip" aria-pressed="true" href="#entries/${m}">${esc(catName)} ✕</a>` : ''}
    </div>
    <input class="search" id="q" type="search" placeholder="Search this month" value="${esc(query)}" aria-label="Search">
    ${Object.keys(groups).sort().reverse().map(d => { const dt = totals(groups[d]); return `
      <div class="day-h"><a href="#day/${d}"><b>${esc(fmtDate(d, { weekday: 'short', day: 'numeric', month: 'short' }))}${d === S.today ? ' · today' : ''} ›</b></a>
        <span>${dt.spent ? money(dt.spent) : ''}${dt.spent && dt.earned ? ' · ' : ''}${dt.earned ? `<span class="pos">${money(dt.earned, true)}</span>` : ''}</span></div>
      <div class="list">${groups[d].sort((a, b) => byTime(b, a)).map(e => row(e)).join('')}</div>`; }).join('')
      || `<div class="empty">${filtered ? 'Nothing matches.' : `Nothing recorded in ${esc(monthName(m))}. Type above, or tap a day in the calendar.`}</div>`}`;
  $$('[data-kind-f]').forEach(b => b.onclick = () => { kindFilter = b.dataset.kindF; render(); });
  $('#q').oninput = e => {
    query = e.target.value; render();
    const el = $('#q'); el.focus(); el.setSelectionRange(el.value.length, el.value.length);
  };
  wireQuickAdd();
  wireBankNotice();
  wireMonthCard();
  wireRows();
}

// ---- Day: one date, in the order things were added ----
function dayView(d) {
  const list = S.entries.filter(e => e.on_date === d).sort(byTime);
  const t = totals(list), m = d.slice(0, 7);
  const isToday = d === S.today, future = d > S.today;
  // month to date, and what an even split of the budget allows per day
  const mtd = S.entries.filter(e => e.kind === 'exp' && e.on_date <= d).reduce((a, e) => a + e.amount, 0);
  const daily = S.budget ? Math.round(S.budget / daysIn(m) / 100) * 100 : 0;   // whole rupees
  const spentBy = byCategory('exp', list);
  const sub = isToday ? fmtDate(d, { weekday: 'long', day: 'numeric', month: 'long' })
    : fmtDate(d, { day: 'numeric', month: 'long', year: 'numeric' });
  $('#view').innerHTML = `
    <div class="head">
      <div><a class="back" href="#entries/${m}" id="goHome">${svg('prev')} Entries</a><h1>${esc(dayLabel(d))}</h1><p class="sub">${esc(sub)}</p></div>
      <div class="nav">
        <a class="b icon line" href="#day/${addDays(d, -1)}" data-replace data-dir="l" aria-label="Previous day">${svg('prev')}</a>
        <a class="b line ${isToday ? 'gap' : ''}" href="#day/${S.today}" data-replace ${isToday ? 'tabindex="-1" aria-hidden="true"' : ''}>Today</a>
        <a class="b icon line" href="#day/${addDays(d, 1)}" data-replace data-dir="r" aria-label="Next day" ${d >= S.today ? 'hidden' : ''}>${svg('next')}</a>
      </div>
    </div>
    <div class="tiles">
      <div class="tile spent"><div class="l">Spent</div><div class="v">${money(t.spent)}</div><div class="s">${list.filter(e => e.kind === 'exp').length} items</div></div>
      <div class="tile earned"><div class="l">Earned</div><div class="v">${money(t.earned, true)}</div><div class="s">&nbsp;</div></div>
      ${daily ? `<div class="tile"><div class="l">Daily budget</div><div class="v ${t.spent > daily ? 'neg' : 'pos'}">${money(Math.abs(daily - t.spent))}</div><div class="s">${t.spent > daily ? 'over' : 'under'} ${money(daily)}/day</div></div>`
        : `<div class="tile"><div class="l">Net</div><div class="v ${t.net < 0 ? 'neg' : 'pos'}">${money(t.net, true)}</div><div class="s">&nbsp;</div></div>`}
      <div class="tile"><div class="l">Month so far</div><div class="v">${money(mtd)}</div><div class="s">spent up to ${esc(fmtDate(d, { day: 'numeric', month: 'short' }))}</div></div>
    </div>
    ${spentBy.length > 1 ? `<div class="card"><h2>Where it went</h2>
      <div class="split">${spentBy.map(c => `<i style="--v:${c.total};--tc:${c.id ? tc(c.name) : '#9a9a92'}" title="${esc(c.name || 'Uncategorized')}: ${money(c.total)}"></i>`).join('')}</div>
      <div class="cal-legend">${spentBy.map(c => `<span><i style="background:${c.id ? tc(c.name) : '#9a9a92'}"></i>${esc(c.name || 'Uncategorized')} ${money(c.total)}</span>`).join('')}</div></div>` : ''}
    ${future ? '' : `<button class="b primary add-day" id="addDay" type="button">＋ Add items for ${esc(isToday ? 'today' : fmtDate(d, { day: 'numeric', month: 'short' }))}</button>`}
    <div class="sec-h"><h2>${list.length ? `${list.length} ${list.length === 1 ? 'entry' : 'entries'}` : ''}</h2></div>
    <div class="list">${list.map(e => row(e, true)).join('') || `<div class="empty">Nothing on this day${future ? '' : ' yet. Add what you spent with the button above'}.</div>`}</div>`;
  $('#addDay') && ($('#addDay').onclick = () => openAdd(d));
  // Home is one Back step away when we came from it, however many days were stepped through
  $('#goHome').onclick = e => {
    e.preventDefault();
    if (fromHome) history.back(); else location.replace(e.currentTarget.getAttribute('href'));
  };
  // swipe between days too
  const v = $('#view');
  let x0 = null;
  v.ontouchstart = e => { x0 = e.target.closest('.row') ? null : e.touches[0].clientX; };
  v.ontouchend = e => {
    if (x0 === null) return;
    const dx = e.changedTouches[0].clientX - x0;
    x0 = null;
    if (Math.abs(dx) < 70) return;
    const to = addDays(d, dx < 0 ? 1 : -1);
    if (to <= S.today) { slideIn = dx < 0 ? 'r' : 'l'; location.replace(`#day/${to}`); }
  };
  wireRows();
}

// ---- Overview ----
function overviewView() {
  const m = S.month, t = totals(S.entries), cur = m === thisMonth();
  const days = daysIn(m), upto = cur ? +S.today.slice(8) : days;
  const perDay = [...Array(days)].map((_, i) => spentOn(`${m}-${String(i + 1).padStart(2, '0')}`));
  const peak = Math.max(1, ...perDay);
  const spentBy = byCategory('exp'), earnedBy = byCategory('earn');
  const top = Object.values(S.entries.filter(e => e.kind === 'exp').reduce((g, e) => {
    const k = (e.name || '—').toLowerCase(); g[k] = g[k] || { name: e.name || '—', total: 0, count: 0 }; g[k].total += e.amount; g[k].count++; return g;
  }, {})).sort((a, b) => b.total - a.total).slice(0, 5);
  const prev = S.months.find(x => x.month === addMonths(m, -1));
  const vsPrev = prev && prev.spent ? Math.round((t.spent - prev.spent) * 100 / prev.spent) : null;
  const busiest = perDay.indexOf(Math.max(...perDay));
  const budget = S.budget ? `<div class="card budget">
      <div class="top-l"><span>Budget ${money(S.budget)}</span><span class="${t.spent > S.budget ? 'neg' : 'muted'}">${t.spent > S.budget ? money(t.spent - S.budget) + ' over' : money(S.budget - t.spent) + ' left'}</span></div>
      <div class="meter" style="--tc:${t.spent > S.budget ? 'var(--bad)' : t.spent * 100 >= S.budget * 80 ? 'var(--deep)' : 'var(--ok)'}"><i style="--v:${pct(t.spent, S.budget)}"></i></div>
      <p class="hint">${pct(t.spent, S.budget)}% used${cur && upto < days ? ` · ${days - upto} days left · ${S.budget > t.spent ? `about ${money(Math.floor((S.budget - t.spent) / (days - upto) / 100) * 100)} a day keeps you inside it` : 'already over'}` : ''}</p></div>` : '';
  const catList = (list, kind, top = Math.max(1, ...list.map(x => x.total))) => list.map(c => `<a class="mrow" href="#entries/${m}/${c.id}">
      <span class="ml"><span class="dot" style="--tc:${c.id ? tc(c.name) : '#9a9a92'}"></span>${c.id ? esc(c.name) : '<i>Uncategorized</i>'}</span>
      <div class="meter" style="--tc:${c.id ? tc(c.name) : '#9a9a92'}"><i style="--v:${pct(c.total, top)}"></i></div>
      <span class="mv ${kind === 'earn' ? 'pos' : ''}">${money(c.total, kind === 'earn')}<small>${c.count} ${c.count === 1 ? 'entry' : 'entries'} · ${pct(c.total, kind === 'earn' ? t.earned : t.spent)}%</small></span></a>`).join('');

  $('#view').innerHTML = `
    ${head('overview', monthName(m), cur ? `So far this month · day ${upto} of ${days}` : `${S.entries.length} entries`)}
    ${cur ? nowTiles() : ''}
    <div class="tiles">
      <div class="tile spent"><div class="l">Spent</div><div class="v">${money(t.spent)}</div><div class="s">${vsPrev === null ? '&nbsp;' : `${vsPrev > 0 ? '▲' : vsPrev < 0 ? '▼' : ''} ${Math.abs(vsPrev)}% vs ${esc(monthName(addMonths(m, -1), true))}`}</div></div>
      <div class="tile earned"><div class="l">Earned</div><div class="v">${money(t.earned, true)}</div><div class="s">${earnedBy.length ? `${earnedBy.reduce((a, c) => a + c.count, 0)} entries` : '&nbsp;'}</div></div>
      <div class="tile"><div class="l">Net</div><div class="v ${t.net < 0 ? 'neg' : 'pos'}">${money(t.net, true)}</div><div class="s">${t.earned ? `${t.net < 0 ? 'spent more than earned' : `saved ${pct(t.net, t.earned)}% of income`}` : '&nbsp;'}</div></div>
      <div class="tile"><div class="l">Per day</div><div class="v">${money(Math.round(t.spent / Math.max(1, upto) / 100) * 100)}</div><div class="s">${perDay[busiest] ? `biggest: ${esc(fmtDate(`${m}-${String(busiest + 1).padStart(2, '0')}`, { day: 'numeric', month: 'short' }))}` : 'average spend'}</div></div>
    </div>
    ${budget}
    ${budgetsCard(spentBy)}
    ${cur ? salaryCard() : ''}
    ${taxiCard()}
    ${S.entries.length ? `
    <div class="card"><h2>Spending by day</h2>
      <div class="bars">${perDay.map((v, i) => { const d = `${m}-${String(i + 1).padStart(2, '0')}`; return `<a class="barcol ${d === S.today ? 'today' : ''} ${d > S.today ? 'future' : ''}" style="--i:${i}" href="#day/${d}" title="${esc(fmtDate(d, { weekday: 'short', day: 'numeric', month: 'short' }))}: ${money(v)}">
        <span class="bt"><i style="--v:${pct(v, peak)}"></i></span><span class="bl ${(i + 1) % 5 && i ? 'hide' : ''}">${i + 1}</span></a>`; }).join('')}</div>
    </div>
    <div class="grid2">
      <div class="card"><h2>Spent by category</h2>${catList(spentBy, 'exp') || '<p class="muted small">Nothing spent this month.</p>'}</div>
      <div>
        ${earnedBy.length ? `<div class="card"><h2>Earned by category</h2>${catList(earnedBy, 'earn')}</div>` : ''}
        ${top.length ? `<div class="card"><h2>Top spends</h2>${top.map(x => `<div class="mrow"><span class="ml">${esc(x.name)}</span><span class="muted small">${x.count}×</span><span class="mv">${money(x.total)}</span></div>`).join('')}</div>` : ''}
      </div>
    </div>` : `<div class="empty">Nothing recorded in ${esc(monthName(m))}. Add entries from the Entries tab.</div>`}`;
}

// ---- Categories ----
function wireBudgets() {
  $$('[data-bud]').forEach(b => b.onclick = () => {
    const c = S.categories.find(x => x.id === +b.dataset.bud);
    const v = prompt(`Monthly budget for ${c.name} (leave empty to switch it off)`, c.budget ? c.budget / 100 : '');
    if (v !== null) busy(b, async () => { await api(`/api/category/${c.id}/budget`, { budget: v.trim() || '0' }); toast('Saved'); await refresh(true); });
  });
}
function categoriesView() {
  const m = S.month;
  const spent = byCategory('exp'), earned = byCategory('earn');
  const ids = [...new Set([...spent, ...earned].map(c => c.id))];
  const get = (list, id) => list.find(c => c.id === id) || { total: 0, count: 0 };
  const rows = ids.map(id => { const s = get(spent, id), e = get(earned, id); return { id, name: (s.name || e.name), s, e }; })
    .sort((a, b) => !a.id - !b.id || b.s.total - a.s.total || b.e.total - a.e.total);
  const peak = Math.max(1, ...rows.map(r => r.s.total));
  const used = new Set(ids);
  const idle = S.categories.filter(c => !used.has(c.id));
  $('#view').innerHTML = `
    ${head('categories', 'Categories', esc(monthName(m)))}
    ${budgetsCard(spent)}
    <div class="card">${rows.map(r => `<a class="mrow" href="#entries/${m}/${r.id}">
        <span class="ml"><span class="dot" style="--tc:${r.id ? tc(r.name) : '#9a9a92'}"></span>${r.id ? esc(r.name) : '<i>Uncategorized</i>'}</span>
        <div class="meter" style="--tc:${r.id ? tc(r.name) : '#9a9a92'}"><i style="--v:${pct(r.s.total, peak)}"></i></div>
        <span class="mv">${r.s.total || !r.e.total ? money(r.s.total) : ''}${r.e.total ? `<span class="pos">${r.s.total ? ' · ' : ''}${money(r.e.total, true)}</span>` : ''}<small>${r.s.count + r.e.count} ${r.s.count + r.e.count === 1 ? 'entry' : 'entries'}</small></span></a>`).join('')
      || `<p class="muted small">Nothing recorded in ${esc(monthName(m))}.</p>`}</div>
    ${idle.length ? `<p class="muted small" style="margin:12px 2px 6px">Not used this month</p><div class="chips wrap">${idle.map(c => `<span class="chip" style="cursor:default"><span class="dot" style="--tc:${tc(c.name)}"></span>${esc(c.name)}</span>`).join('')}</div>` : ''}
    <div class="card"><h2>Monthly budgets</h2>${S.categories.map(c => `<div class="srow"><div class="tx"><b><span class="dot" style="--tc:${tc(c.name)}"></span> ${esc(c.name)}</b><span>${c.budget ? `${money(c.budget)} a month` : 'no budget'}</span></div>
      <div class="acts" style="margin:0"><button class="b sm line" data-bud="${c.id}">${c.budget ? 'Change' : 'Set budget'}</button></div></div>`).join('') || '<p class="muted small">No categories yet.</p>'}</div>
    <p class="hint" style="margin-top:10px">Rename or delete a category in Settings.</p>`;
  wireBudgets();
}

// ---- Months: every month side by side ----
function monthsView() {
  const list = S.months;
  const peak = Math.max(1, ...list.map(x => Math.max(x.spent, x.earned)));
  const all = list.reduce((a, x) => ({ spent: a.spent + x.spent, earned: a.earned + x.earned }), { spent: 0, earned: 0 });
  const avg = list.length ? Math.round(all.spent / list.length / 100) * 100 : 0;
  $('#view').innerHTML = `
    <div class="head"><div><h1>Months</h1><p class="sub">Every month at a glance. Tap one to open it.</p></div></div>
    ${list.length ? `<div class="tiles">
      <div class="tile spent"><div class="l">Spent, all time</div><div class="v">${money(all.spent)}</div></div>
      <div class="tile earned"><div class="l">Earned, all time</div><div class="v">${money(all.earned, true)}</div></div>
      <div class="tile"><div class="l">Net, all time</div><div class="v ${all.earned - all.spent < 0 ? 'neg' : 'pos'}">${money(all.earned - all.spent, true)}</div></div>
      <div class="tile"><div class="l">Average month</div><div class="v">${money(avg)}</div><div class="s">spent, over ${list.length} months</div></div>
    </div>
    <div class="card">${list.map(x => `<a class="mon ${x.month === thisMonth() ? 'cur' : ''}" href="#entries/${x.month}">
      <span class="mn"><b>${esc(monthName(x.month, true))}</b><span>${x.count} entries</span></span>
      <span class="pair">
        <span class="pl"><span class="meter" style="--tc:var(--spend)"><i style="--v:${pct(x.spent, peak)}"></i></span><span>${money(x.spent)}</span></span>
        <span class="pl"><span class="meter" style="--tc:var(--ok)"><i style="--v:${pct(x.earned, peak)}"></i></span><span class="pos">${money(x.earned, true)}</span></span>
      </span>
      <span class="net ${x.earned - x.spent < 0 ? 'neg' : 'pos'}">net ${money(x.earned - x.spent, true)}</span></a>`).join('')}</div>`
      : '<div class="empty">No entries yet. Add one on Entries.</div>'}`;
}

// ---- Settings ----
function settingsView() {
  const tzs = [...new Set([S.tz, 'Asia/Kolkata', 'Asia/Dubai', 'Europe/London', 'America/New_York', 'America/Los_Angeles', 'Australia/Sydney'])];
  $('#view').innerHTML = `
    <div class="head"><div><h1>Settings</h1></div></div>
    <div class="card">
      <h2>Money</h2>
      <form id="setForm">
        <div class="three">
          <div><label for="sBudget">Monthly budget</label><input id="sBudget" inputmode="decimal" value="${S.budget ? S.budget / 100 : ''}" placeholder="off"></div>
          <div><label for="sCur">Currency</label><input id="sCur" maxlength="3" value="${esc(S.currency)}" required></div>
          <div><label for="sTz">Timezone</label><select id="sTz">${tzs.map(z => `<option ${z === S.tz ? 'selected' : ''}>${esc(z)}</option>`).join('')}</select></div>
        </div>
        <p class="hint">The budget shows as a bar on Overview and a daily allowance on each day. Leave it empty to switch it off. Timezone decides what counts as today, and the times shown on entries.</p>
        <div class="acts"><button class="b primary" type="submit">Save</button></div>
      </form>
    </div>
    <div class="card">
      <h2>Categories</h2>
      ${S.categories.map(c => `<div class="srow"><div class="tx"><b><span class="dot" style="--tc:${tc(c.name)}"></span> ${esc(c.name)}</b><span>${c.count} ${c.count === 1 ? 'entry' : 'entries'}, all time${c.budget ? ` · budget ${money(c.budget)}/month` : ''}</span></div>
        <div class="acts" style="margin:0"><button class="b sm line" data-bud="${c.id}">Budget</button><button class="b sm line" data-ren="${c.id}">Rename</button><button class="b sm warn" data-delcat="${c.id}">Delete</button></div></div>`).join('')
        || '<p class="muted small">No categories yet. Pick “New category” when adding, or type <b>#food</b>.</p>'}
    </div>
    ${S.me.admin ? peopleCard() : ''}
    <div class="card">
      <h2>Install</h2>
      <p class="muted small">In Chrome: menu ⋮ → <b>Add to Home screen</b>. On iPhone: Share → <b>Add to Home Screen</b>. It opens like an app.</p>
    </div>
    <div class="card">
      <h2>Account</h2>
      <div class="srow"><div class="tx"><b>${esc(S.me.name)}</b><span>${S.me.admin ? 'Admin' : 'Stays logged in on this device'}</span></div><button class="b warn" id="logout">Log out</button></div>
      ${S.me.admin && !S.me.has_password ? '<p class="note warn">You’re still on the shared PIN. Set your own name and password below: after that only your password logs in as admin.</p>' : ''}
      <form id="pwForm" style="border-top:1px solid var(--line);padding-top:4px;margin-top:8px">
        <label for="acName">Login name</label><input id="acName" value="${esc(S.me.name || '')}" autocomplete="username" required minlength="2" maxlength="32">
        <label for="pwCur">${S.me.has_password ? 'Current password' : 'Current PIN'}</label><input id="pwCur" type="password" autocomplete="current-password" required>
        <label for="pwNew">New password ${S.me.has_password ? '<span class="muted">(leave blank to keep)</span>' : ''}</label>
        <input id="pwNew" type="password" autocomplete="new-password" minlength="6" ${S.me.has_password ? '' : 'required'}>
        <div class="acts"><button class="b ${S.me.has_password ? 'line' : 'primary'}" type="submit">Save</button></div></form>
    </div>`;
  if (S.me.admin) wirePeople();
  $('#setForm').onsubmit = e => {
    e.preventDefault();
    busy(e.submitter, async () => {
      await api('/api/settings', { budget: $('#sBudget').value.trim() || '0', currency: $('#sCur').value, tz: $('#sTz').value });
      toast('Saved'); await refresh(true);
    });
  };
  $('#pwForm').onsubmit = e => {
    e.preventDefault();
    busy(e.submitter, async () => {
      await api('/api/account', { name: $('#acName').value, current: $('#pwCur').value, new: $('#pwNew').value });
      try { localStorage.setItem('finName', $('#acName').value.trim()); } catch (err) {}
      toast('Account saved'); await refresh(true);
    });
  };
  $$('[data-ren]').forEach(b => b.onclick = () => {
    const c = S.categories.find(x => x.id === +b.dataset.ren);
    const name = prompt('New name for this category', c.name);
    if (name && name.trim() !== c.name) busy(b, async () => { await api(`/api/category/${c.id}/rename`, { name }); await refresh(true); });
  });
  wireBudgets();
  $$('[data-delcat]').forEach(b => b.onclick = () => busy(b, async () => {
    const c = S.categories.find(x => x.id === +b.dataset.delcat);
    if (!await ask(`Delete “${c.name}”?`, 'Its entries are kept: they just become uncategorized.', 'Delete', true)) return;
    await api(`/api/category/${c.id}/delete`, {}); await refresh(true);
  }));
  $('#logout').onclick = e => busy(e.currentTarget, async () => {
    if (!await ask('Log out?', 'You can log back in any time with your name and password.', 'Log out')) return;
    await api('/api/logout', {}).catch(() => {});
    S = null; A = null;
    showLogin();
  });
}

// ---- People (admin only): invites and accounts ----
let A = null;            // /api/admin
let freshLink = '';      // the invite just made, shown until the next one
const absLink = p => location.origin + p;
const ago = isoStr => { const d = Math.round((Date.now() - Date.parse(isoStr)) / 864e5); return d <= 0 ? 'today' : d === 1 ? 'yesterday' : `${d} days ago`; };
async function loadAdmin() {
  try { A = await api('/api/admin'); } catch (e) { if (e.status === 401) return showLogin(); toast(e.message, true); return; }
  if (route()[0] === 'settings') render();
}
function peopleCard() {
  if (!A) { loadAdmin(); return '<div class="card"><h2>People</h2><p class="muted small">Loading…</p></div>'; }
  const pending = A.invites.filter(i => !i.joined && !i.expired);
  return `<div class="card">
    <h2>People</h2>
    <p class="muted small">Each person gets a private ledger. You see who’s here, never their money.</p>
    <form id="invForm" class="inrow" style="margin-top:10px"><input id="invLabel" maxlength="40" placeholder="Who is it for? (optional)" autocomplete="off"><button class="b primary" type="submit">Invite</button></form>
    ${freshLink ? `<div class="link"><code>${esc(freshLink)}</code><button class="b sm line" data-copy="${esc(freshLink)}">Copy</button>${navigator.share ? `<button class="b sm line" data-share="${esc(freshLink)}">Share</button>` : ''}</div>
      <p class="hint">Works once, for 7 days. Send it on WhatsApp or anywhere.</p>` : ''}
    ${A.people.map(p => `<div class="srow"><div class="tx"><b>${esc(p.name)} ${p.is_admin ? '<span class="pill admin">admin</span>' : ''}${p.disabled ? '<span class="pill off">disabled</span>' : ''}</b>
        <span>${p.entries} entries · joined ${ago(p.created_at)}</span></div>
        ${p.is_admin ? '' : `<button class="b sm ${p.disabled ? 'line' : 'warn'}" data-user="${p.user_id}" data-off="${p.disabled ? 0 : 1}">${p.disabled ? 'Enable' : 'Disable'}</button>`}</div>`).join('')}
    ${A.unclaimed.length ? `<h2 style="margin-top:16px">Waiting to be claimed</h2>
      <p class="muted small">Ledgers from the Telegram bot. A claim link lets the owner take one over, with all its entries.</p>
      ${A.unclaimed.map(u => `<div class="srow"><div class="tx"><b>Telegram #${u.user_id}</b><span>${u.entries} entries · no login yet</span></div>
        <button class="b sm primary" data-claim="${u.user_id}">Make claim link</button></div>`).join('')}` : ''}
    ${pending.length ? `<h2 style="margin-top:16px">Unused invites</h2>${pending.map(i => `<div class="srow"><div class="tx"><b>${esc(i.label || 'No name')}${i.claim ? ' <span class="pill admin">claim</span>' : ''}</b><span>made ${ago(i.created_at)} · expires in ${Math.max(0, Math.ceil((Date.parse(i.expires_at) - Date.now()) / 864e5))} days</span></div>
        <div class="acts" style="margin:0"><button class="b sm line" data-copy="${esc(absLink('/join/' + i.token))}">Copy</button><button class="b sm warn" data-revoke="${esc(i.token)}">Revoke</button></div></div>`).join('')}` : ''}
  </div>`;
}
function wirePeople() {
  if (!A) return;
  $('#invForm').onsubmit = e => {
    e.preventDefault();
    busy(e.submitter, async () => {
      const { path } = await api('/api/admin/invite', { label: $('#invLabel').value });
      freshLink = absLink(path);
      await copy(freshLink, 'Invite link made and copied');
      await loadAdmin();
    });
  };
  $$('[data-claim]').forEach(b => b.onclick = () => busy(b, async () => {
    const { path } = await api(`/api/admin/claim/${b.dataset.claim}`, { label: `Telegram #${b.dataset.claim}` });
    freshLink = absLink(path);
    await copy(freshLink, 'Claim link made and copied');
    await loadAdmin();
  }));
  $$('[data-copy]').forEach(b => b.onclick = () => copy(b.dataset.copy, 'Link copied'));
  $$('[data-share]').forEach(b => b.onclick = () => navigator.share({ title: 'Finance invite', text: 'Your invite to Finance:', url: b.dataset.share }).catch(() => {}));
  $$('[data-revoke]').forEach(b => b.onclick = () => busy(b, async () => {
    if (!await ask('Revoke this invite?', 'The link stops working. You can make a new one any time.', 'Revoke', true)) return;
    await api(`/api/admin/invite/${b.dataset.revoke}/revoke`, {});
    if (freshLink.endsWith(b.dataset.revoke)) freshLink = '';
    await loadAdmin();
  }));
  $$('[data-user]').forEach(b => b.onclick = () => busy(b, async () => {
    const p = A.people.find(x => x.user_id === +b.dataset.user), off = b.dataset.off === '1';
    if (off && !await ask(`Disable ${p.name}?`, 'They’re logged out everywhere. Their entries are kept; you can enable them again.', 'Disable', true)) return;
    await api(`/api/admin/user/${p.user_id}/${off ? 'disable' : 'enable'}`, {});
    await loadAdmin();
  }));
}
async function copy(text, msg) {
  try { await navigator.clipboard.writeText(text); toast(msg); } catch (e) { toast('Copy failed — long-press the link to copy it', true); }
}

// ---- the form: several items for one day, or one entry to edit ----
const F = { entry: null };   // the entry being edited; null when adding
const NEW = '__new';
// a new entry lands where you're looking: that day, today, or a past month's last day
function defaultDay() {
  const [name, arg] = route();
  if (name === 'day' && arg[0] <= S.today) return arg[0];
  return S.month < thisMonth() ? `${S.month}-${String(daysIn(S.month)).padStart(2, '0')}` : S.today;
}
function catOptions(sel) {
  const known = S.categories.some(c => c.name.toLowerCase() === (sel || '').toLowerCase());
  return `<option value="">No category</option>
    ${S.categories.map(c => `<option value="${esc(c.name)}" ${known && c.name.toLowerCase() === sel.toLowerCase() ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}
    <option value="${NEW}" ${sel && !known ? 'selected' : ''}>＋ New category…</option>`;
}
function itemHtml(it = {}) {
  const kind = it.kind || 'exp', cat = it.category || '';
  const isNew = cat && !S.categories.some(c => c.name.toLowerCase() === cat.toLowerCase());
  return `<div class="item" data-kind="${kind}">
    <button type="button" class="kb ${kind}" aria-label="${kind === 'earn' ? 'Earned: tap for spent' : 'Spent: tap for earned'}">${kind === 'earn' ? '+' : '−'}</button>
    <input class="ia" inputmode="decimal" placeholder="Amount" aria-label="Amount" value="${it.amount ? it.amount / 100 : ''}" enterkeyhint="next">
    <input class="in" maxlength="100" placeholder="What for" aria-label="What for" value="${esc(it.name || '')}" enterkeyhint="next">
    <select class="ic" aria-label="Category">${catOptions(cat)}</select>
    <input class="inew" maxlength="32" placeholder="New category name" aria-label="New category name" value="${isNew ? esc(cat) : ''}" ${isNew ? '' : 'hidden'}>
    <button type="button" class="rm" aria-label="Remove this item">✕</button>
  </div>`;
}
function readItem(el) {
  const sel = $('.ic', el).value;
  return { kind: el.dataset.kind, amount: $('.ia', el).value.replace(/[,\s₹$]/g, ''), name: $('.in', el).value.trim(),
    category: sel === NEW ? $('.inew', el).value.trim() : sel, newCat: sel === NEW };
}
const blank = it => !it.amount && !it.name;
function addItem(it, focus) {
  $('#items').insertAdjacentHTML('beforeend', itemHtml(it));
  paintTotal();
  if (focus) $('#items .item:last-child .ia').focus();
}
function paintTotal() {
  const items = $$('#items .item').map(readItem).filter(i => !blank(i));
  let spent = 0, earned = 0;
  items.forEach(i => (i.kind === 'earn' ? (earned += paise(i.amount)) : (spent += paise(i.amount))));
  $('#fTotal').innerHTML = !F.entry && items.length ? `<span>${items.length} ${items.length === 1 ? 'item' : 'items'}</span>${spent ? `<span>Spent ${money(spent)}</span>` : ''}${earned ? `<span class="pos">Earned ${money(earned, true)}</span>` : ''}` : '';
  $('#fSave').textContent = F.entry ? 'Save' : items.length > 1 ? `Save ${items.length} items` : 'Save';
  $$('#items .rm').forEach(b => (b.hidden = !!F.entry));
}
function paintRecent() {
  $('#recent').innerHTML = S.recent.map((r, i) => `<button type="button" class="chip sm" data-recent="${i}">${r.category ? `<span class="dot" style="--tc:${tc(r.category)}"></span>` : ''}${esc(r.name)} <span class="${r.kind === 'earn' ? 'pos' : 'muted'}">${money(r.amount, r.kind === 'earn')}</span></button>`).join('');
  $('#recentBox').hidden = !!F.entry || !S.recent.length;
}
function openForm(title, sub, day, items) {
  $('#editTitle').textContent = title;
  $('#editSub').textContent = sub;
  $('#editSub').className = 'small muted';
  $('#fDate').value = day;
  $('#fDate').max = addDays(S.today, 7);
  $('#items').innerHTML = '';
  items.forEach(it => addItem(it));
  $('#addRow').hidden = $('#rowHint').hidden = !!F.entry;
  $('#fDelete').hidden = !F.entry;
  $('#editErr').hidden = true;
  $('#edit').classList.toggle('wide', !F.entry);
  paintRecent(); paintTotal();
  $('#edit').showModal();
  if (!F.entry) $('#items .ia').focus();
}
function openAdd(day) {
  F.entry = null;
  openForm('Add items', 'Several things on one day? Add them all here.', day, [{}]);
}
function openEdit(e) {
  F.entry = e;
  openForm('Edit entry', `${e.bank ? 'From a bank alert · recorded' : 'Added'} at ${fmtTime(e.time)}`, e.on_date, [e]);
}
$('#fab').onclick = () => openAdd(defaultDay());
$('#fCancel').onclick = () => $('#edit').close();
$('#addRow').onclick = () => addItem({}, true);
$('#items').addEventListener('click', ev => {
  const item = ev.target.closest('.item');
  if (ev.target.closest('.kb')) {
    const k = item.dataset.kind === 'exp' ? 'earn' : 'exp', b = $('.kb', item);
    item.dataset.kind = k; b.className = 'kb ' + k; b.textContent = k === 'earn' ? '+' : '−';
    b.setAttribute('aria-label', k === 'earn' ? 'Earned: tap for spent' : 'Spent: tap for earned');
    paintTotal();
  } else if (ev.target.closest('.rm')) {
    if ($$('#items .item').length > 1) item.remove(); else { item.outerHTML = itemHtml(); }
    paintTotal();
  }
});
$('#items').addEventListener('change', ev => {
  if (!ev.target.matches('.ic')) return;
  const box = $('.inew', ev.target.closest('.item'));
  box.hidden = ev.target.value !== NEW;
  if (!box.hidden) box.focus();
});
$('#items').addEventListener('input', paintTotal);
// Enter moves on: amount → what for → the next item (made if needed). Save is the button.
$('#items').addEventListener('keydown', ev => {
  if (ev.key !== 'Enter' || ev.target.tagName !== 'INPUT') return;
  ev.preventDefault();
  const item = ev.target.closest('.item');
  if (ev.target.matches('.ia')) return $('.in', item).focus();
  if (F.entry) return $('#editForm').requestSubmit();
  const next = item.nextElementSibling;
  if (next) $('.ia', next).focus(); else if (!blank(readItem(item))) addItem({}, true);
});
$('#recent').addEventListener('click', ev => {
  const b = ev.target.closest('[data-recent]');
  if (!b) return;
  const r = S.recent[+b.dataset.recent];
  const free = $$('#items .item').find(el => blank(readItem(el)));
  if (free) free.outerHTML = itemHtml(r); else addItem(r);
  paintTotal();
  b.animate([{ transform: 'scale(.92)' }, { transform: 'none' }], 160);
});
$('#editForm').onsubmit = ev => {
  ev.preventDefault();
  const fail = m => { $('#editErr').textContent = m; $('#editErr').hidden = false; };
  const items = $$('#items .item').map(readItem).filter(i => F.entry || !blank(i));
  const day = $('#fDate').value;
  if (!items.length) return fail('Add at least one item.');
  const bad = items.findIndex(i => !(paise(i.amount) > 0));
  if (bad >= 0) return fail(items.length > 1 ? `Item ${bad + 1} needs an amount.` : 'Type an amount, like 250.');
  if (items.some(i => i.newCat && !i.category)) return fail('Name the new category, or pick one from the list.');
  if (!day) return fail('Pick a day.');
  const body = items.map(({ kind, amount, name, category }) => ({ kind, amount, name, category }));
  busy($('#fSave'), async () => {
    try {
      if (F.entry) await api(`/api/entry/${F.entry.id}`, { ...body[0], on_date: day });
      else await api('/api/entries', { on_date: day, items: body });
    } catch (err) {
      if (err.status === 401) throw err;
      return fail(err.message);
    }
    $('#edit').close();
    const sum = body.reduce((a, i) => a + (i.kind === 'exp' ? paise(i.amount) : 0), 0);
    toast(F.entry ? 'Saved' : `Added ${body.length} ${body.length === 1 ? 'item' : 'items'}${sum ? ' · ' + money(sum) : ''} · ${dayLabel(day)}`);
    await showSaved(day);
  });
};
$('#fDelete').onclick = () => busy($('#fDelete'), async () => {
  const e = F.entry;
  $('#edit').close();
  if (!await ask('Delete this entry?', `${money(e.amount)}${e.name ? ' · ' + e.name : ''} on ${fmtDate(e.on_date, { day: 'numeric', month: 'short' })}. This can’t be undone.`, 'Delete', true)) return;
  await api(`/api/entry/${e.id}/delete`, {});
  toast('Deleted');
  await refresh(true);
});

// ---- boot ----
if (joinToken) startJoin();
else {
  history.replaceState(null, '', '/#entries');   // every fresh open starts on Entries, whatever tab it was left on
  refresh(true);
}
