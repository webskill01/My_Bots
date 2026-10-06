// Finance panel. Hash routes, all per month:
// #overview/<YYYY-MM>  #entries/<YYYY-MM>[/<cat id | 0 for none>]  #categories/<YYYY-MM>  #months  #settings
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

// Dates are 'YYYY-MM-DD' strings in the user's timezone (the server says
// what today is). UTC math on them keeps the browser's timezone out of it.
const D = s => new Date(s + 'T00:00:00Z');
const fmtDate = (s, o) => D(s).toLocaleDateString('en-IN', { timeZone: 'UTC', ...o });
const monthName = (m, short) => fmtDate(m + '-01', { month: short ? 'short' : 'long', year: 'numeric' });
const addMonths = (m, n) => { const [y, mo] = m.split('-').map(Number); const t = y * 12 + mo - 1 + n; return `${Math.floor(t / 12)}-${String(t % 12 + 1).padStart(2, '0')}`; };
const daysIn = m => { const [y, mo] = m.split('-').map(Number); return new Date(Date.UTC(y, mo, 0)).getUTCDate(); };
const isMonth = s => /^\d{4}-(0[1-9]|1[0-2])$/.test(s || '');

// Amounts arrive in paise. Indian grouping (1,23,456); paise only when there are any.
const money = (p, sign) => `${sign && p > 0 ? '+' : ''}${p < 0 ? '−' : ''}${S.currency}${(Math.abs(p) / 100).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
const pct = (a, b) => (b ? Math.min(100, Math.round(a * 100 / b)) : 0);

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
const TABS = [['overview', 'Overview'], ['entries', 'Entries'], ['categories', 'Categories'], ['months', 'Months'], ['settings', 'Settings']];
const MONTHLY = ['overview', 'entries', 'categories'];

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
function byCategory(kind) {
  const g = {};
  S.entries.filter(e => e.kind === kind).forEach(e => {
    const k = e.category_id || 0;
    g[k] = g[k] || { id: k, name: e.category, total: 0, count: 0 };
    g[k].total += e.amount; g[k].count++;
  });
  return Object.values(g).sort((a, b) => !a.id - !b.id || b.total - a.total);
}
const catTag = e => (e.category ? `<span class="tag" style="--tc:${tc(e.category)}">${esc(e.category)}</span>` : '');

function row(e) {
  return `<div class="row ${e.kind}" data-open="${e.id}" tabindex="0" style="--tc:${e.category ? tc(e.category) : 'var(--line)'}">
    <div style="min-width:0"><div class="t1">${esc(e.name) || '<span class="muted">—</span>'}</div>${e.category ? `<div class="t2">${catTag(e)}</div>` : ''}</div>
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
    history.replaceState(null, '', '/#overview');
    $('#joinSec').hidden = true;
    refresh(true);
    toast('Welcome! Add your first entry with the box at the top.');
  } catch (err) { $('#joinErr').textContent = err.message; $('#joinErr').hidden = false; }
  finally { btn.disabled = false; }
};

const VIEWS = { overview: overviewView, entries: entriesView, categories: categoriesView, months: monthsView, settings: settingsView };
function route() {
  let [name, ...arg] = location.hash.slice(1).split('/');
  if (!VIEWS[name]) name = 'overview';
  $$('[data-tab]').forEach(a => (a.dataset.tab === name ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current')));
  return [name, arg];
}
// The month a monthly view wants: from the hash, else the one already loaded.
function wantedMonth() {
  const [name, arg] = route();
  return MONTHLY.includes(name) && isMonth(arg[0]) ? arg[0] : S ? S.month : '';
}
function render(force = true) {
  if (!S) return;
  const [name, arg] = route();
  $('#who').textContent = S.me.name || '';
  $('#fab').hidden = name === 'settings';
  // never redraw under the user's fingers: a dialog, or typing
  const typing = document.activeElement && $('#view').contains(document.activeElement) && document.activeElement.tagName === 'INPUT';
  if ($('#dlg').open || $('#edit').open || (!force && typing)) return;
  const y = window.scrollY;
  VIEWS[name](...arg);
  window.scrollTo(0, y);
}
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

// ---- quick add: "250 lunch #food 24 aug", the same words the bot took ----
let draft = '';
function quickAddHtml() {
  return `<form class="card add" id="quick" autocomplete="off">
    <div class="add-top">
      <input id="qText" placeholder="250 lunch #food" value="${esc(draft)}" aria-label="New entry" enterkeyhint="done">
      <button class="b primary" type="submit">Add</button>
      <button class="b line" type="button" id="qForm">Form</button>
    </div>
    <p class="hint"><code>+3000 salary</code> for income · <code>#food</code> sets a category · end with <code>24 aug</code> or <code>yesterday</code> for another day</p>
  </form>`;
}
function wireQuickAdd() {
  $('#qText').oninput = e => (draft = e.target.value);
  $('#qForm').onclick = () => openEdit(null);
  $('#quick').onsubmit = e => {
    e.preventDefault();
    if (!draft.trim()) return $('#qText').focus();
    busy(e.submitter, async () => {
      const { entry } = await api('/api/quick', { text: draft });
      draft = '';
      toast(`${entry.kind === 'earn' ? 'Earned' : 'Spent'} ${money(entry.amount)}${entry.name ? ' · ' + entry.name : ''} · ${fmtDate(entry.on_date, { day: 'numeric', month: 'short' })}`);
      // an entry for another month: go and show it there
      if (entry.on_date.slice(0, 7) !== S.month) location.hash = `#${route()[0]}/${entry.on_date.slice(0, 7)}`;
      else await refresh(true);
      $('#qText') && $('#qText').focus();
    });
  };
}

// ---- Overview ----
function overviewView() {
  const m = S.month, t = totals(S.entries), cur = m === thisMonth();
  const days = daysIn(m), upto = cur ? +S.today.slice(8) : days;
  const perDay = [...Array(days)].map((_, i) => S.entries.filter(e => e.kind === 'exp' && +e.on_date.slice(8) === i + 1).reduce((a, e) => a + e.amount, 0));
  const peak = Math.max(1, ...perDay);
  const spentBy = byCategory('exp'), earnedBy = byCategory('earn');
  const top = Object.values(S.entries.filter(e => e.kind === 'exp').reduce((g, e) => {
    const k = (e.name || '—').toLowerCase(); g[k] = g[k] || { name: e.name || '—', total: 0, count: 0 }; g[k].total += e.amount; g[k].count++; return g;
  }, {})).sort((a, b) => b.total - a.total).slice(0, 5);
  const prev = S.months.find(x => x.month === addMonths(m, -1));
  const vsPrev = prev && prev.spent ? Math.round((t.spent - prev.spent) * 100 / prev.spent) : null;
  const budget = S.budget ? `<div class="card budget">
      <div class="top-l"><span>Budget ${money(S.budget)}</span><span class="${t.spent > S.budget ? 'neg' : 'muted'}">${t.spent > S.budget ? money(t.spent - S.budget) + ' over' : money(S.budget - t.spent) + ' left'}</span></div>
      <div class="meter" style="--tc:${t.spent > S.budget ? 'var(--bad)' : t.spent * 100 >= S.budget * 80 ? 'var(--deep)' : 'var(--ok)'}"><i style="--v:${pct(t.spent, S.budget)}"></i></div>
      <p class="hint">${pct(t.spent, S.budget)}% used${cur && upto < days ? ` · ${days - upto} days left in the month` : ''}</p></div>` : '';
  const catList = (list, kind, peak = Math.max(1, ...list.map(x => x.total))) => list.map(c => `<a class="mrow" href="#entries/${m}/${c.id}">
      <span class="ml"><span class="dot" style="--tc:${c.id ? tc(c.name) : '#9a9a92'}"></span>${c.id ? esc(c.name) : '<i>Uncategorized</i>'}</span>
      <div class="meter" style="--tc:${c.id ? tc(c.name) : '#9a9a92'}"><i style="--v:${pct(c.total, peak)}"></i></div>
      <span class="mv ${kind === 'earn' ? 'pos' : ''}">${money(c.total, kind === 'earn')}<small>${c.count} ${c.count === 1 ? 'entry' : 'entries'}</small></span></a>`).join('');

  $('#view').innerHTML = `
    ${head('overview', monthName(m), cur ? `So far this month · day ${upto} of ${days}` : `${S.entries.length} entries`)}
    ${quickAddHtml()}
    <div class="tiles">
      <div class="tile spent"><div class="l">Spent</div><div class="v">${money(t.spent)}</div><div class="s">${vsPrev === null ? '&nbsp;' : `${vsPrev > 0 ? '▲' : vsPrev < 0 ? '▼' : ''} ${Math.abs(vsPrev)}% vs ${esc(monthName(addMonths(m, -1), true))}`}</div></div>
      <div class="tile earned"><div class="l">Earned</div><div class="v">${money(t.earned, true)}</div><div class="s">${earnedBy.length ? `${earnedBy.reduce((a, c) => a + c.count, 0)} entries` : '&nbsp;'}</div></div>
      <div class="tile"><div class="l">Net</div><div class="v ${t.net < 0 ? 'neg' : 'pos'}">${money(t.net, true)}</div><div class="s">${t.net < 0 ? 'spent more than earned' : 'saved'}</div></div>
      <div class="tile"><div class="l">Per day</div><div class="v">${money(Math.round(t.spent / Math.max(1, upto) / 100) * 100)}</div><div class="s">average spend</div></div>
    </div>
    ${budget}
    ${S.entries.length ? `
    <div class="card"><h2>Spending by day</h2>
      <div class="bars">${perDay.map((v, i) => { const d = `${m}-${String(i + 1).padStart(2, '0')}`; return `<a class="barcol ${d === S.today ? 'today' : ''} ${d > S.today ? 'future' : ''}" href="#entries/${m}" title="${esc(fmtDate(d, { weekday: 'short', day: 'numeric', month: 'short' }))}: ${money(v)}">
        <span class="bt"><i style="--v:${pct(v, peak)}"></i></span><span class="bl ${(i + 1) % 5 && i ? 'hide' : ''}">${i + 1}</span></a>`; }).join('')}</div>
    </div>
    <div class="grid2">
      <div class="card"><h2>Spent by category</h2>${catList(spentBy, 'exp') || '<p class="muted small">Nothing spent this month.</p>'}</div>
      <div>
        ${earnedBy.length ? `<div class="card"><h2>Earned by category</h2>${catList(earnedBy, 'earn')}</div>` : ''}
        ${top.length ? `<div class="card"><h2>Top spends</h2>${top.map(x => `<div class="mrow"><span class="ml">${esc(x.name)}</span><span class="muted small">${x.count}×</span><span class="mv">${money(x.total)}</span></div>`).join('')}</div>` : ''}
      </div>
    </div>` : `<div class="empty">Nothing recorded in ${esc(monthName(m))}.${cur ? '' : ' Fill it in with the box above: end with a date like <b>24 ' + esc(fmtDate(m + '-01', { month: 'short' }).toLowerCase()) + '</b>.'}</div>`}`;
  wireQuickAdd();
}

// ---- Entries ----
function entriesView(_, cat) {
  const m = S.month;
  const catId = cat === undefined || cat === '' ? null : +cat;
  const catName = catId === null ? '' : catId ? (S.categories.find(c => c.id === catId) || {}).name || 'Category' : 'Uncategorized';
  const q = query.trim().toLowerCase();
  const list = S.entries.filter(e => (kindFilter === 'all' || e.kind === kindFilter)
    && (catId === null || (e.category_id || 0) === catId)
    && (!q || (e.name || '').toLowerCase().includes(q) || (e.category || '').toLowerCase().includes(q)));
  const t = totals(list);
  const groups = {};
  list.forEach(e => (groups[e.on_date] = groups[e.on_date] || []).push(e));
  const base = `#entries/${m}`;
  $('#view').innerHTML = `
    ${head('entries', catName || 'Entries', `${esc(monthName(m))} · ${list.length} ${list.length === 1 ? 'entry' : 'entries'} · spent ${money(t.spent)}${t.earned ? ` · earned ${money(t.earned, true)}` : ''}`)}
    <div class="chips" role="group" aria-label="Filter">
      ${[['all', 'All'], ['exp', 'Spent'], ['earn', 'Earned']].map(([k, l]) => `<button class="chip" data-kind-f="${k}" aria-pressed="${kindFilter === k}">${l}</button>`).join('')}
      ${catId !== null ? `<a class="chip" aria-pressed="true" href="${base}">${esc(catName)} ✕</a>` : ''}
    </div>
    <input class="search" id="q" type="search" placeholder="Search this month" value="${esc(query)}" aria-label="Search">
    ${Object.keys(groups).sort().reverse().map(d => { const dt = totals(groups[d]); return `
      <div class="day-h"><b>${esc(fmtDate(d, { weekday: 'short', day: 'numeric', month: 'short' }))}${d === S.today ? ' · today' : ''}</b>
        <span>${dt.spent ? money(dt.spent) : ''}${dt.spent && dt.earned ? ' · ' : ''}${dt.earned ? `<span class="pos">${money(dt.earned, true)}</span>` : ''}</span></div>
      <div class="list">${groups[d].map(row).join('')}</div>`; }).join('')
      || `<div class="empty">${S.entries.length ? 'Nothing matches.' : `Nothing recorded in ${esc(monthName(m))}.`}</div>`}`;
  $$('[data-kind-f]').forEach(b => b.onclick = () => { kindFilter = b.dataset.kindF; render(); });
  $('#q').oninput = e => {
    query = e.target.value; render();
    const el = $('#q'); el.focus(); el.setSelectionRange(el.value.length, el.value.length);
  };
  wireRows();
}

// ---- Categories ----
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
    <div class="card">${rows.map(r => `<a class="mrow" href="#entries/${m}/${r.id}">
        <span class="ml"><span class="dot" style="--tc:${r.id ? tc(r.name) : '#9a9a92'}"></span>${r.id ? esc(r.name) : '<i>Uncategorized</i>'}</span>
        <div class="meter" style="--tc:${r.id ? tc(r.name) : '#9a9a92'}"><i style="--v:${pct(r.s.total, peak)}"></i></div>
        <span class="mv">${r.s.total || !r.e.total ? money(r.s.total) : ''}${r.e.total ? `<span class="pos">${r.s.total ? ' · ' : ''}${money(r.e.total, true)}</span>` : ''}<small>${r.s.count + r.e.count} ${r.s.count + r.e.count === 1 ? 'entry' : 'entries'}</small></span></a>`).join('')
      || `<p class="muted small">Nothing recorded in ${esc(monthName(m))}.</p>`}</div>
    ${idle.length ? `<p class="muted small" style="margin:12px 2px 6px">Not used this month</p><div class="chips" style="flex-wrap:wrap">${idle.map(c => `<span class="chip" style="cursor:default"><span class="dot" style="--tc:${tc(c.name)}"></span>${esc(c.name)}</span>`).join('')}</div>` : ''}
    <p class="hint" style="margin-top:10px">Rename or delete categories in Settings.</p>`;
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
    <div class="card">${list.map(x => `<a class="mon ${x.month === thisMonth() ? 'cur' : ''}" href="#overview/${x.month}">
      <span class="mn"><b>${esc(monthName(x.month, true))}</b><span>${x.count} entries</span></span>
      <span class="pair">
        <span class="pl"><span class="meter" style="--tc:var(--spend)"><i style="--v:${pct(x.spent, peak)}"></i></span><span>${money(x.spent)}</span></span>
        <span class="pl"><span class="meter" style="--tc:var(--ok)"><i style="--v:${pct(x.earned, peak)}"></i></span><span class="pos">${money(x.earned, true)}</span></span>
      </span>
      <span class="net ${x.earned - x.spent < 0 ? 'neg' : 'pos'}">net ${money(x.earned - x.spent, true)}</span></a>`).join('')}</div>`
      : '<div class="empty">No entries yet. Add one on Overview.</div>'}`;
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
        <p class="hint">The budget shows as a bar on Overview for every month. Leave it empty to switch it off. Timezone decides what counts as today.</p>
        <div class="acts"><button class="b primary" type="submit">Save</button></div>
      </form>
    </div>
    <div class="card">
      <h2>Categories</h2>
      ${S.categories.map(c => `<div class="srow"><div class="tx"><b><span class="dot" style="--tc:${tc(c.name)}"></span> ${esc(c.name)}</b><span>${c.count} ${c.count === 1 ? 'entry' : 'entries'}, all time</span></div>
        <div class="acts" style="margin:0"><button class="b sm line" data-ren="${c.id}">Rename</button><button class="b sm warn" data-delcat="${c.id}">Delete</button></div></div>`).join('')
        || '<p class="muted small">No categories yet. Type one when adding, like <b>#food</b>.</p>'}
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
const ago = iso => { const d = Math.round((Date.now() - Date.parse(iso)) / 864e5); return d <= 0 ? 'today' : d === 1 ? 'yesterday' : `${d} days ago`; };
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

// ---- add / edit ----
const E = { entry: null, kind: 'exp' };
function paintKind() { $$('[data-kind]').forEach(b => b.setAttribute('aria-pressed', b.dataset.kind === E.kind)); }
$$('[data-kind]').forEach(b => b.onclick = () => { E.kind = b.dataset.kind; paintKind(); });

function openEdit(e) {
  E.entry = e || null;
  E.kind = e ? e.kind : 'exp';
  // a new entry lands in the month being viewed: today, or that month's last day
  const day = S.month === thisMonth() ? S.today : S.month < thisMonth() ? `${S.month}-${String(daysIn(S.month)).padStart(2, '0')}` : S.today;
  $('#editTitle').textContent = e ? 'Edit entry' : 'New entry';
  $('#fAmount').value = e ? e.amount / 100 : '';
  $('#fDate').value = e ? e.on_date : day;
  $('#fName').value = e ? e.name : '';
  $('#fCat').value = e ? e.category || '' : '';
  $('#catList').innerHTML = S.categories.map(c => `<option value="${esc(c.name)}">`).join('');
  $('#fDelete').hidden = !e;
  $('#editErr').hidden = true;
  paintKind();
  $('#edit').showModal();
  if (!e) $('#fAmount').focus();
}
$('#fab').onclick = () => openEdit(null);
$('#fCancel').onclick = () => $('#edit').close();
$('#editForm').onsubmit = ev => {
  ev.preventDefault();
  const body = { kind: E.kind, amount: $('#fAmount').value.replace(/[,\s₹]/g, ''), on_date: $('#fDate').value, name: $('#fName').value, category: $('#fCat').value };
  busy($('#fSave'), async () => {
    let saved;
    try {
      saved = (await api(E.entry ? `/api/entry/${E.entry.id}` : '/api/entry', body)).entry;
    } catch (err) {
      if (err.status === 401) throw err;
      $('#editErr').textContent = err.message; $('#editErr').hidden = false;
      return;
    }
    $('#edit').close();
    toast(E.entry ? 'Saved' : `Added ${money(saved.amount)}${saved.name ? ' · ' + saved.name : ''}`);
    if (saved.on_date.slice(0, 7) !== S.month && MONTHLY.includes(route()[0])) location.hash = `#${route()[0]}/${saved.on_date.slice(0, 7)}`;
    else await refresh(true);
  });
};
$('#fDelete').onclick = () => busy($('#fDelete'), async () => {
  const e = E.entry;
  $('#edit').close();
  if (!await ask('Delete this entry?', `${money(e.amount)}${e.name ? ' · ' + e.name : ''} on ${fmtDate(e.on_date, { day: 'numeric', month: 'short' })}. This can’t be undone.`, 'Delete', true)) return;
  await api(`/api/entry/${e.id}/delete`, {});
  toast('Deleted');
  await refresh(true);
});

// ---- boot ----
if (joinToken) startJoin(); else refresh(true);
