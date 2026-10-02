// Schedule panel. Hash routes: #today #day/<date> #week/<monday> #upcoming #settings
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

// Dates travel as 'YYYY-MM-DD' strings in the user's own timezone (the server
// decides "now"). UTC math on them keeps the browser's timezone out of it.
const D = s => new Date(s + 'T00:00:00Z');
const iso = d => d.toISOString().slice(0, 10);
const addDays = (s, n) => iso(new Date(D(s).getTime() + n * 864e5));
const wd = s => (D(s).getUTCDay() + 6) % 7;                  // Mon = 0
const fmtDate = (s, o) => D(s).toLocaleDateString('en-IN', { timeZone: 'UTC', ...o });
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const fmtTime = hm => { if (!hm) return ''; const [h, m] = hm.split(':').map(Number); return `${h % 12 || 12}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`; };
const mins = hm => { const [h, m] = hm.split(':').map(Number); return h * 60 + m; };
const inText = m => (m < 60 ? `${m} min` : `${Math.floor(m / 60)}h${m % 60 ? ` ${m % 60}m` : ''}`);
function fmtDays(mask) {
  if (mask === 127) return 'Every day';
  const on = DAYS.map((_, i) => i).filter(i => mask >> i & 1);
  const run = on.length > 2 && on[on.length - 1] - on[0] === on.length - 1;
  return run ? `${DAYS[on[0]]}–${DAYS[on[on.length - 1]]}` : on.map(i => DAYS[i]).join(', ');
}
function dayLabel(s) {
  const t = today();
  return s === t ? 'Today' : s === addDays(t, 1) ? 'Tomorrow' : s === addDays(t, -1) ? 'Yesterday' : fmtDate(s, { weekday: 'long' });
}

const PALETTE = ['#2563eb', '#1f7a4a', '#a8660b', '#d6336c', '#7048e8', '#0b6e76', '#c2410c', '#0e7490'];
const tc = name => { if (!name) return 'var(--line)'; let h = 0; for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0; return PALETTE[h % PALETTE.length]; };

const ICON = {
  today: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  week: '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M8 3v4M16 3v4M3 10h18"/>',
  upcoming: '<path d="M4 6h16M4 12h10M4 18h7"/><path d="M17 15l3 3-3 3"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  check: '<path d="M5 12l5 5L20 7"/>',
  repeat: '<path d="M17 2l4 4-4 4"/><path d="M3 11V9a3 3 0 0 1 3-3h15M7 22l-4-4 4-4"/><path d="M21 13v2a3 3 0 0 1-3 3H3"/>',
  prev: '<path d="M15 18l-6-6 6-6"/>',
  next: '<path d="M9 18l6-6-6-6"/>',
};
const svg = k => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[k]}</svg>`;
const TABS = [['today', 'Today'], ['week', 'Week'], ['upcoming', 'Upcoming'], ['settings', 'Settings']];

let S = null;              // /api/state
let fetchedAt = 0;         // Date.now() when S arrived; S.now advances from there
let lastJson = '';
let tagFilter = 'all';
let swReg = null;
let installEvt = null;
let pushOn = false;        // this browser has a live subscription
let synced = false;

// "now" in the user's timezone: the server's clock plus the time since it said so
function liveNow() {
  const t = new Date(Date.parse(S.now + ':00Z') + (Date.now() - fetchedAt));
  return t.toISOString().slice(0, 16);
}
const today = () => liveNow().slice(0, 10);
const nowHM = () => liveNow().slice(11, 16);

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

// ---- the schedule model ----
const byTime = (a, b) => (a.at_time == null) - (b.at_time == null) || (a.at_time || '').localeCompare(b.at_time || '') || a.id - b.id;
const itemsOn = date => [...S.routine.filter(t => t.days >> wd(date) & 1), ...S.tasks.filter(t => t.on_date === date)].sort(byTime);
// a routine task's tick only lives for today: the server keeps one done date
const isDone = (t, date) => (t.daily ? t.done_on === date && date === today() : !!t.done_on);
const canTick = (t, date) => !t.daily || date === today();
const overdue = () => S.tasks.filter(t => !t.done_on && t.on_date < today()).sort((a, b) => a.on_date.localeCompare(b.on_date) || byTime(a, b));
const findTask = id => S.routine.find(t => t.id === id) || S.tasks.find(t => t.id === id);

function tagHtml(t) { return t.tag ? `<span class="tag" style="--tc:${tc(t.tag)}">${esc(t.tag)}</span>` : ''; }

function row(t, date, badges = '', cur = false) {
  const done = isDone(t, date);
  const snz = t.snooze_until && !done ? `<span class="badge snz">Snoozed · ${fmtTime(t.snooze_until.slice(11))}</span>` : '';
  const meta = [tagHtml(t), t.daily ? `<span>${svg('repeat')} ${esc(fmtDays(t.days))}</span>` : '',
    !t.daily && t.on_date !== date ? `<span>${esc(fmtDate(t.on_date, { day: 'numeric', month: 'short' }))}</span>` : ''].filter(Boolean).join('');
  return `<div class="row ${done ? 'done' : ''} ${cur ? 'cur' : ''}" data-open="${t.id}" style="--tc:${tc(t.tag)}">
    <button class="check" type="button" data-done="${t.id}" data-date="${date}" aria-pressed="${done}" aria-label="${done ? 'Mark not done' : 'Mark done'}: ${esc(t.title)}" ${canTick(t, date) ? '' : 'disabled'}>${svg('check')}</button>
    <div class="tm">${t.at_time ? fmtTime(t.at_time).replace(' ', '<small>') + '</small>' : '<small>Anytime</small>'}</div>
    <div style="min-width:0"><div class="t1">${esc(t.title)}</div>${meta ? `<div class="t2">${meta}</div>` : ''}</div>
    <div class="r">${badges}${snz}</div></div>`;
}

function wireRows() {
  $$('[data-done]').forEach(b => b.onclick = e => {
    e.stopPropagation();
    const t = findTask(+b.dataset.done), done = b.getAttribute('aria-pressed') !== 'true';
    busy(b, async () => {
      await api(`/api/task/${t.id}/done`, { done });
      t.done_on = done ? today() : null;   // instant feedback; the refresh confirms
      render(true);
      refresh();
    });
  });
  $$('[data-open]').forEach(r => r.onclick = () => openEdit(findTask(+r.dataset.open)));
}

// ---- shell ----
$('.top .tabs').innerHTML = TABS.map(([k, l]) => `<a href="#${k}" data-tab="${k}">${l}</a>`).join('');
$('.bottom').innerHTML = TABS.map(([k, l]) => `<a href="#${k}" data-tab="${k}">${svg(k)}${l}</a>`).join('');
function showLogin() {
  $('#app').hidden = true; $('#joinSec').hidden = true; $('#login').hidden = false;
  try { $('#un').value = $('#un').value || localStorage.getItem('schedName') || ''; } catch (e) {}
  ($('#un').value ? $('#pw') : $('#un')).focus();
}
$('#loginForm').onsubmit = async e => {
  e.preventDefault();
  $('#loginErr').hidden = true;
  try {
    await api('/api/login', { name: $('#un').value, password: $('#pw').value });
    try { localStorage.setItem('schedName', $('#un').value.trim()); } catch (e) {}
    $('#pw').value = ''; $('#login').hidden = true; refresh(true);
  } catch (err) { $('#loginErr').textContent = err.message; $('#loginErr').hidden = false; }
};

// ---- joining from an invite link: /join/<token> ----
const joinToken = (location.pathname.match(/^\/join\/([\w-]{20,64})$/) || [])[1];
async function startJoin() {
  $('#login').hidden = true; $('#app').hidden = true; $('#joinSec').hidden = false;
  try {
    const inv = await api(`/api/invite/${joinToken}`);
    $('#joinSub').textContent = inv.label ? `Invite for ${inv.label} · create your account` : 'Create your account';
    if (inv.label && !$('#jName').value) $('#jName').value = inv.label;
    $('#jName').focus();
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
    try { localStorage.setItem('schedName', $('#jName').value.trim()); } catch (e) {}
    history.replaceState(null, '', '/#today');
    $('#joinSec').hidden = true;
    refresh(true);
    toast('Welcome! Turn on reminders in Settings.');
  } catch (err) { $('#joinErr').textContent = err.message; $('#joinErr').hidden = false; }
  finally { btn.disabled = false; }
};

const VIEWS = { today: dayView, day: dayView, week: weekView, upcoming: upcomingView, settings: settingsView };
function route() {
  let [name, ...arg] = location.hash.slice(1).split('/');
  if (!VIEWS[name]) name = 'today';
  const tab = name === 'day' ? 'today' : name;
  $$('[data-tab]').forEach(a => (a.dataset.tab === tab ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current')));
  return [name, arg];
}
function render(force) {
  if (!S) return;
  const [name, arg] = route();
  $('#clock').textContent = `${fmtDate(today(), { weekday: 'short', day: 'numeric', month: 'short' })} · ${fmtTime(nowHM())}`;
  $('#bell').hidden = pushOn || !pushSupported();
  // never redraw under the user's fingers: typing or a dialog
  const typing = document.activeElement && $('#view').contains(document.activeElement) && /INPUT|SELECT/.test(document.activeElement.tagName);
  if (!force && (typing || $('#dlg').open || $('#edit').open)) return;
  const y = window.scrollY;
  VIEWS[name](...arg);
  if (!force) window.scrollTo(0, y);
}
window.addEventListener('hashchange', () => {
  if (route()[0] === 'settings') A = null;   // people and invites, fresh each visit
  render(true); window.scrollTo(0, 0);
});

async function refresh(force) {
  clearTimeout(refresh.t);
  try {
    const st = await api('/api/state');
    $('#login').hidden = true; $('#app').hidden = false;
    S = st; fetchedAt = Date.now();
    const json = JSON.stringify(st);
    if (force || json !== lastJson) { lastJson = json; render(force); }
    if (!synced) { synced = true; syncPush(); }
  } catch (e) {
    if (e.status === 401) showLogin();
    else if (S) toast('Connection lost, retrying…', true);
  }
  refresh.t = setTimeout(refresh, 30000);
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
setInterval(() => render(false), 60000);   // Now / Next move with the clock

// ---- Today (and any single day) ----
function dayView(date) {
  const t = today();
  date = /^\d{4}-\d{2}-\d{2}$/.test(date || '') ? date : t;
  const items = itemsOn(date), isToday = date === t;
  const timed = items.filter(i => i.at_time), anytime = items.filter(i => !i.at_time);
  const done = items.filter(i => isDone(i, date)).length;

  // Now = the block that started most recently, unless it's already ticked off
  // (an earlier block you skipped isn't "now"); Next = the first one still ahead
  let cur = null, next = null;
  if (isToday) {
    const hm = nowHM();
    cur = [...timed].reverse().find(i => i.at_time <= hm) || null;
    if (cur && isDone(cur, date)) cur = null;
    next = timed.find(i => i.at_time > hm && !isDone(i, date)) || null;
  }
  const goal = items.find(i => i.tag === 'goal');
  const late = isToday ? overdue() : [];

  const badges = i => (i === cur ? '<span class="badge now">Now</span>' : i === next ? `<span class="badge next">in ${inText(mins(i.at_time) - mins(nowHM()))}</span>` : '');
  $('#view').innerHTML = `
    <div class="head">
      <div><h1>${esc(dayLabel(date))}</h1><p class="sub">${esc(fmtDate(date, { weekday: 'long', day: 'numeric', month: 'long' }))}</p></div>
      <div class="nav">
        <a class="b icon line" href="#day/${addDays(date, -1)}" aria-label="Previous day">${svg('prev')}</a>
        ${isToday ? '' : '<a class="b line" href="#today">Today</a>'}
        <a class="b icon line" href="#day/${addDays(date, 1)}" aria-label="Next day">${svg('next')}</a>
      </div>
    </div>
    <form class="quick" id="quick">
      <input id="qText" placeholder="call mom 6pm #family · gym 7am #daily" autocomplete="off" aria-label="Quick add">
      <button class="b primary" type="submit">Add</button>
    </form>
    <div class="tiles">
      ${goal ? `<div class="tile goal"><div class="l">Main goal</div><div class="v txt">${esc(goal.title.replace(/^🎯\s*(Goal:\s*)?/, ''))}</div></div>` : ''}
      <div class="tile"><div class="l">Done</div><div class="v">${done}<span class="muted" style="font-size:15px"> / ${items.length}</span></div>
        <div class="bar"><i style="width:${items.length ? Math.round(done * 100 / items.length) : 0}%"></i></div></div>
      ${isToday ? `<div class="tile"><div class="l">${cur ? 'Now' : 'Next'}</div>${(cur || next)
        ? `<div class="v txt">${esc((cur || next).title)}</div><div class="s">${cur ? `since ${fmtTime(cur.at_time)}` : `${fmtTime(next.at_time)} · in ${inText(mins(next.at_time) - mins(nowHM()))}`}</div>`
        : '<div class="v txt">All clear</div><div class="s">Nothing else timed today</div>'}</div>` : ''}
    </div>
    ${late.length ? `<div class="sec-h"><h2>Overdue</h2><span class="cnt">${late.length}</span></div>
      <div class="list">${late.map(i => row(i, date, `<span class="badge late">${esc(fmtDate(i.on_date, { day: 'numeric', month: 'short' }))}</span>`)).join('')}</div>` : ''}
    <div class="sec-h"><h2>Schedule</h2><span class="cnt">${timed.length}</span></div>
    <div class="list">${timed.map(i => row(i, date, badges(i), i === cur)).join('') || '<div class="empty">Nothing timed on this day.</div>'}</div>
    ${anytime.length ? `<div class="sec-h"><h2>Anytime</h2><span class="cnt">${anytime.length}</span></div>
      <div class="list">${anytime.map(i => row(i, date)).join('')}</div>` : ''}`;
  wireRows();
  $('#quick').onsubmit = e => {
    e.preventDefault();
    const text = $('#qText').value.trim();
    if (!text) return;
    busy(e.submitter, async () => {
      const { task } = await api('/api/quick', { text });
      $('#qText').value = '';
      $('#qText').blur();
      toast(`Added: ${task.title} · ${task.daily ? fmtDays(task.days) : dayLabel(task.on_date)}${task.at_time ? ' ' + fmtTime(task.at_time) : ''}`);
      await refresh(true);
    });
  };
}

// ---- Week ----
function weekView(start) {
  const t = today();
  start = /^\d{4}-\d{2}-\d{2}$/.test(start || '') ? start : addDays(t, -wd(t));
  start = addDays(start, -wd(start));   // always a Monday
  const end = addDays(start, 6);
  const same = D(start).getUTCMonth() === D(end).getUTCMonth();
  const span = `${fmtDate(start, { day: 'numeric', ...(same ? {} : { month: 'short' }) })} – ${fmtDate(end, { day: 'numeric', month: 'short' })}`;
  const days = [...Array(7)].map((_, i) => addDays(start, i));
  $('#view').innerHTML = `
    <div class="head">
      <div><h1>${start === addDays(t, -wd(t)) ? 'This week' : 'Week'}</h1><p class="sub">${esc(span)}</p></div>
      <div class="nav">
        <a class="b icon line" href="#week/${addDays(start, -7)}" aria-label="Previous week">${svg('prev')}</a>
        <a class="b line" href="#week">This week</a>
        <a class="b icon line" href="#week/${addDays(start, 7)}" aria-label="Next week">${svg('next')}</a>
      </div>
    </div>
    <div class="week">${days.map(d => `
      <section class="wd ${d === t ? 'today' : ''}">
        <a class="day-t" href="#day/${d}"><b>${DAYS[wd(d)]}</b><span>${fmtDate(d, { day: 'numeric', month: 'short' })}${d === t ? ' · today' : ''}</span></a>
        ${itemsOn(d).map(i => `<div class="wi ${isDone(i, d) ? 'done' : ''}" data-open="${i.id}" style="--tc:${tc(i.tag)}" tabindex="0">
          <span class="wt">${i.at_time ? fmtTime(i.at_time) : 'Anytime'}</span><span class="wn">${esc(i.title)}</span></div>`).join('') || '<p class="muted small">Free</p>'}
      </section>`).join('')}</div>`;
  $$('[data-open]').forEach(r => { r.onclick = () => openEdit(findTask(+r.dataset.open)); r.onkeydown = e => { if (e.key === 'Enter') r.click(); }; });
}

// ---- Upcoming ----
function upcomingView() {
  const t = today();
  const pick = list => list.filter(i => tagFilter === 'all' || i.tag === tagFilter);
  const late = pick(overdue());
  const ahead = pick(S.tasks.filter(i => !i.done_on && i.on_date >= t));
  const groups = {};
  ahead.forEach(i => (groups[i.on_date] = groups[i.on_date] || []).push(i));
  const tags = S.tags.filter(g => g.open);
  if (tagFilter !== 'all' && !tags.some(g => g.name === tagFilter)) tagFilter = 'all';
  $('#view').innerHTML = `
    <div class="head"><div><h1>Upcoming</h1><p class="sub">One-time tasks from today on. Your routine lives in Week.</p></div></div>
    ${tags.length ? `<div class="chips" role="group" aria-label="Tag">${[['all', 'All'], ...tags.map(g => [g.name, g.name])].map(([k, l]) =>
      `<button class="chip" data-tag="${esc(k)}" aria-pressed="${tagFilter === k}">${k !== 'all' ? `<span class="dot" style="--tc:${tc(k)}"></span>` : ''}${esc(l)}</button>`).join('')}</div>` : ''}
    ${late.length ? `<div class="sec-h"><h2>Overdue</h2><span class="cnt">${late.length}</span></div>
      <div class="list">${late.map(i => row(i, i.on_date, `<span class="badge late">${esc(fmtDate(i.on_date, { day: 'numeric', month: 'short' }))}</span>`)).join('')}</div>` : ''}
    ${Object.keys(groups).sort().map(d => `<div class="sec-h"><h2>${esc(dayLabel(d))}</h2><span class="cnt">${esc(fmtDate(d, { day: 'numeric', month: 'short' }))}</span></div>
      <div class="list">${groups[d].sort(byTime).map(i => row(i, d)).join('')}</div>`).join('')}
    ${!late.length && !ahead.length ? '<div class="empty" style="margin-top:8px">Nothing coming up. Add one with the + button or type it on Today.</div>' : ''}`;
  $$('[data-tag]').forEach(b => b.onclick = () => { tagFilter = b.dataset.tag; render(true); });
  wireRows();
}

// ---- Settings ----
const pushSupported = () => 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
const standalone = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone;

function settingsView() {
  const perm = pushSupported() ? Notification.permission : 'unsupported';
  const ios = /iPhone|iPad/.test(navigator.userAgent);
  let pushBox;
  if (perm === 'unsupported') {
    pushBox = `<p class="note warn">${ios && !standalone()
      ? 'On iPhone, notifications only work from the installed app: tap Share → Add to Home Screen, open Schedule from there, then come back here.'
      : 'This browser can’t receive notifications. Use Chrome on Android.'}</p>`;
  } else if (perm === 'denied') {
    pushBox = '<p class="note warn">Notifications are blocked for this site. Tap the lock icon next to the address (or the app’s info → Notifications), allow them, then reload.</p>';
  } else if (pushOn) {
    pushBox = `<p class="note ok">On for this device. ${S.devices > 1 ? `${S.devices} devices get reminders.` : ''}</p>
      <div class="acts"><button class="b primary" id="pushTest">Send a test</button><button class="b line" id="pushOff">Turn off here</button></div>`;
  } else {
    pushBox = `<p class="muted small">Reminders arrive as phone notifications at each task’s time, with Done and Snooze buttons, even when the app is closed.</p>
      <div class="acts"><button class="b primary" id="pushOn">Turn on reminders</button></div>`;
  }
  const tzs = [...new Set([S.tz, 'Asia/Kolkata', 'Asia/Dubai', 'Europe/London', 'America/New_York', 'America/Los_Angeles', 'Australia/Sydney'])];
  $('#view').innerHTML = `
    <div class="head"><div><h1>Settings</h1></div></div>
    <div class="card"><h2>Reminders</h2>${pushBox}</div>
    <div class="card">
      <h2>Install</h2>
      ${standalone() ? '<p class="note ok">Installed. Open it from your home screen like any app.</p>'
        : installEvt ? '<p class="muted small">Puts Schedule on your home screen as its own app.</p><div class="acts"><button class="b primary" id="install">Install app</button></div>'
        : '<p class="muted small">In Chrome: menu ⋮ → <b>Add to Home screen</b> (or <b>Install app</b>). On iPhone: Share → <b>Add to Home Screen</b>.</p>'}
    </div>
    <div class="card">
      <h2>Tags</h2>
      ${S.tags.map(g => `<div class="srow"><div class="tx"><b><span class="dot" style="--tc:${tc(g.name)}"></span> ${esc(g.name)}</b><span>${g.open} open</span></div>
        <div class="acts" style="margin:0"><button class="b sm line" data-ren="${g.id}">Rename</button><button class="b sm warn" data-deltag="${g.id}">Delete</button></div></div>`).join('')
        || '<p class="muted small">No tags yet. Type one when adding a task, like <b>#gym</b>.</p>'}
    </div>
    <div class="card">
      <h2>Timezone</h2>
      <p class="muted small">Reminders go out on this clock.</p>
      <form id="tzForm" class="inrow" style="margin-top:10px"><select id="tz">${tzs.map(z => `<option ${z === S.tz ? 'selected' : ''}>${esc(z)}</option>`).join('')}</select><button class="b primary" type="submit">Save</button></form>
    </div>
    ${S.me.admin ? peopleCard() : ''}
    <div class="card">
      <h2>Account</h2>
      <div class="srow"><div class="tx"><b>${esc(S.me.name)}</b><span>${S.me.admin ? 'Admin · password is the panel PIN' : 'Stays logged in on this device'}</span></div><button class="b warn" id="logout">Log out</button></div>
      ${S.me.admin ? '' : `<form id="pwForm" style="border-top:1px solid var(--line);padding-top:4px">
        <label for="pwCur">Current password</label><input id="pwCur" type="password" autocomplete="current-password" required>
        <label for="pwNew">New password</label><input id="pwNew" type="password" autocomplete="new-password" minlength="6" required>
        <div class="acts"><button class="b line" type="submit">Change password</button></div></form>`}
    </div>`;
  if (S.me.admin) wirePeople();
  $('#pwForm') && ($('#pwForm').onsubmit = e => {
    e.preventDefault();
    busy(e.submitter, async () => { await api('/api/password', { current: $('#pwCur').value, new: $('#pwNew').value }); $('#pwForm').reset(); toast('Password changed'); });
  });

  $('#pushOn') && ($('#pushOn').onclick = e => busy(e.currentTarget, enablePush));
  $('#pushOff') && ($('#pushOff').onclick = e => busy(e.currentTarget, disablePush));
  $('#pushTest') && ($('#pushTest').onclick = e => busy(e.currentTarget, async () => { await api('/api/push/test', {}); toast('Sent. It should pop up in a moment.'); }));
  $('#install') && ($('#install').onclick = async () => { installEvt.prompt(); await installEvt.userChoice; installEvt = null; render(true); });
  $$('[data-ren]').forEach(b => b.onclick = () => {
    const g = S.tags.find(x => x.id === +b.dataset.ren);
    const name = prompt('New name for this tag', g.name);
    if (name && name.trim() !== g.name) busy(b, async () => { await api(`/api/tag/${g.id}/rename`, { name }); await refresh(true); });
  });
  $$('[data-deltag]').forEach(b => b.onclick = () => busy(b, async () => {
    const g = S.tags.find(x => x.id === +b.dataset.deltag);
    if (!await ask(`Delete “${g.name}”?`, 'Its tasks are kept — they just lose the tag.', 'Delete', true)) return;
    await api(`/api/tag/${g.id}/delete`, {}); await refresh(true);
  }));
  $('#tzForm').onsubmit = e => { e.preventDefault(); busy(e.submitter, async () => { await api('/api/settings', { tz: $('#tz').value }); toast('Timezone saved'); await refresh(true); }); };
  $('#logout').onclick = e => busy(e.currentTarget, async () => {
    if (!await ask('Log out?', 'This device stops getting your reminders until you log in and turn them on again.', 'Log out')) return;
    // the next person on this phone mustn't get my reminders
    try {
      const sub = await (await navigator.serviceWorker.ready).pushManager.getSubscription();
      if (sub) { await api('/api/push/unsubscribe', { endpoint: sub.endpoint }).catch(() => {}); await sub.unsubscribe(); }
    } catch (err) { /* no push here */ }
    await api('/api/logout', {}).catch(() => {});
    S = null; A = null; pushOn = false; synced = false; lastJson = '';
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
  if (route()[0] === 'settings') render(true);
}
function peopleCard() {
  if (!A) { loadAdmin(); return '<div class="card"><h2>People</h2><p class="muted small">Loading…</p></div>'; }
  const pending = A.invites.filter(i => !i.joined && !i.expired);
  return `<div class="card">
    <h2>People</h2>
    <p class="muted small">Each person gets a private schedule and their own reminders. You see who’s here, never their tasks.</p>
    <form id="invForm" class="inrow" style="margin-top:10px"><input id="invLabel" maxlength="40" placeholder="Who is it for? (optional)" autocomplete="off"><button class="b primary" type="submit">Invite</button></form>
    ${freshLink ? `<div class="link"><code>${esc(freshLink)}</code><button class="b sm line" data-copy="${esc(freshLink)}">Copy</button>${navigator.share ? `<button class="b sm line" data-share="${esc(freshLink)}">Share</button>` : ''}</div>
      <p class="hint">Works once, for ${7} days. Send it on WhatsApp or anywhere.</p>` : ''}
    ${A.people.map(p => `<div class="srow"><div class="tx"><b>${esc(p.name)} ${p.is_admin ? '<span class="pill admin">admin</span>' : ''}${p.disabled ? '<span class="pill off">disabled</span>' : ''}</b>
        <span>${p.tasks} tasks · ${p.devices ? `${p.devices} device${p.devices > 1 ? 's' : ''} with reminders` : 'reminders off'} · joined ${ago(p.created_at)}</span></div>
        ${p.is_admin ? '' : `<button class="b sm ${p.disabled ? 'line' : 'warn'}" data-user="${p.user_id}" data-off="${p.disabled ? 0 : 1}">${p.disabled ? 'Enable' : 'Disable'}</button>`}</div>`).join('')}
    ${pending.length ? `<h2 style="margin-top:16px">Unused invites</h2>${pending.map(i => `<div class="srow"><div class="tx"><b>${esc(i.label || 'No name')}</b><span>made ${ago(i.created_at)} · expires in ${Math.max(0, Math.ceil((Date.parse(i.expires_at) - Date.now()) / 864e5))} days</span></div>
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
  $$('[data-copy]').forEach(b => b.onclick = () => copy(b.dataset.copy, 'Link copied'));
  $$('[data-share]').forEach(b => b.onclick = () => navigator.share({ title: 'Schedule invite', text: 'Your invite to Schedule:', url: b.dataset.share }).catch(() => {}));
  $$('[data-revoke]').forEach(b => b.onclick = () => busy(b, async () => {
    if (!await ask('Revoke this invite?', 'The link stops working. You can make a new one any time.', 'Revoke', true)) return;
    await api(`/api/admin/invite/${b.dataset.revoke}/revoke`, {});
    if (freshLink.endsWith(b.dataset.revoke)) freshLink = '';
    await loadAdmin();
  }));
  $$('[data-user]').forEach(b => b.onclick = () => busy(b, async () => {
    const p = A.people.find(x => x.user_id === +b.dataset.user), off = b.dataset.off === '1';
    if (off && !await ask(`Disable ${p.name}?`, 'They’re logged out everywhere and stop getting reminders. Their tasks are kept; you can enable them again.', 'Disable', true)) return;
    await api(`/api/admin/user/${p.user_id}/${off ? 'disable' : 'enable'}`, {});
    await loadAdmin();
  }));
}
async function copy(text, msg) {
  try { await navigator.clipboard.writeText(text); toast(msg); } catch (e) { toast('Copy failed — long-press the link to copy it', true); }
}

// ---- push ----
function keyBytes(b64) {
  const s = atob((b64 + '='.repeat((4 - b64.length % 4) % 4)).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(s, c => c.charCodeAt(0));
}
async function enablePush() {
  if (await Notification.requestPermission() !== 'granted') { render(true); throw new Error('Notifications weren’t allowed.'); }
  const reg = await navigator.serviceWorker.ready;
  let sub = await reg.pushManager.getSubscription();
  if (sub && !sameKey(sub)) { await sub.unsubscribe(); sub = null; }
  sub = sub || await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(S.vapid) });
  await api('/api/push/subscribe', { subscription: sub.toJSON() });
  pushOn = true;
  await refresh(true);
  await api('/api/push/test', {}).catch(() => {});
  toast('Reminders are on. A test notification is on its way.');
}
async function disablePush() {
  const sub = await (await navigator.serviceWorker.ready).pushManager.getSubscription();
  if (sub) { await api('/api/push/unsubscribe', { endpoint: sub.endpoint }); await sub.unsubscribe(); }
  pushOn = false;
  await refresh(true);
  toast('Reminders are off on this device.');
}
function sameKey(sub) {
  const k = sub.options && sub.options.applicationServerKey;
  if (!k) return true;
  const a = new Uint8Array(k), b = keyBytes(S.vapid);
  return a.length === b.length && a.every((x, i) => x === b[i]);
}
// Re-register an existing subscription on every load: if the server forgot it
// (new database, cleared row) reminders quietly start working again.
async function syncPush() {
  if (!pushSupported() || Notification.permission !== 'granted') { render(false); return; }
  try {
    const sub = await (await navigator.serviceWorker.ready).pushManager.getSubscription();
    if (sub && sameKey(sub)) { await api('/api/push/subscribe', { subscription: sub.toJSON() }); pushOn = true; }
  } catch (e) { /* stays off; Settings offers to turn it on */ }
  render(false);
}

// ---- add / edit ----
const E = { task: null, kind: 'once', days: 127 };
$('#fDays').innerHTML = DAYS.map((d, i) => `<button type="button" data-day="${i}">${d.slice(0, 2)}</button>`).join('');
function paintEdit() {
  $$('[data-kind]').forEach(b => b.setAttribute('aria-pressed', b.dataset.kind === E.kind));
  $('#onceBox').hidden = E.kind !== 'once';
  $('#dailyBox').hidden = E.kind !== 'daily';
  $$('[data-day]').forEach(b => b.setAttribute('aria-pressed', !!(E.days >> b.dataset.day & 1)));
  $('#timeHint').hidden = !!$('#fTime').value;
}
$$('[data-kind]').forEach(b => b.onclick = () => { E.kind = b.dataset.kind; paintEdit(); });
$$('[data-day]').forEach(b => b.onclick = () => { E.days ^= 1 << b.dataset.day; paintEdit(); });
$$('[data-preset]').forEach(b => b.onclick = () => { E.days = +b.dataset.preset; paintEdit(); });
$('#fTime').oninput = paintEdit;

function openEdit(t) {
  const [name, arg] = route();
  const viewing = name === 'day' && arg[0] ? arg[0] : today();
  E.task = t || null;
  E.kind = t && t.daily ? 'daily' : 'once';
  E.days = t && t.daily ? t.days : 127;
  $('#editTitle').textContent = t ? 'Edit task' : 'New task';
  $('#fTitle').value = t ? t.title : '';
  $('#fDate').value = t && t.on_date ? t.on_date : viewing;
  $('#fTime').value = t && t.at_time ? t.at_time : '';
  $('#fTag').value = t && t.tag ? t.tag : '';
  $('#tagList').innerHTML = S.tags.map(g => `<option value="${esc(g.name)}">`).join('');
  $('#fDelete').hidden = !t;
  $('#editErr').hidden = true;
  paintEdit();
  $('#edit').showModal();
  if (!t) $('#fTitle').focus();
}
$('#fab').onclick = () => openEdit(null);
$('#fCancel').onclick = () => $('#edit').close();
$('#editForm').onsubmit = e => {
  e.preventDefault();
  const body = { title: $('#fTitle').value, daily: E.kind === 'daily', days: E.days, on_date: $('#fDate').value,
    at_time: $('#fTime').value || null, tag: $('#fTag').value };
  busy($('#fSave'), async () => {
    try {
      await api(E.task ? `/api/task/${E.task.id}` : '/api/task', body);
    } catch (err) {
      if (err.status === 401) throw err;
      $('#editErr').textContent = err.message; $('#editErr').hidden = false;
      return;
    }
    $('#edit').close();
    toast(E.task ? 'Saved' : 'Added');
    await refresh(true);
  });
};
$('#fDelete').onclick = () => busy($('#fDelete'), async () => {
  const t = E.task;
  $('#edit').close();
  if (!await ask(`Delete “${t.title}”?`, t.daily ? 'It leaves your routine on every day it was on.' : 'This can’t be undone.', 'Delete', true)) return;
  await api(`/api/task/${t.id}/delete`, {});
  toast('Deleted');
  await refresh(true);
});

// ---- boot ----
window.addEventListener('beforeinstallprompt', e => { e.preventDefault(); installEvt = e; if (route()[0] === 'settings') render(true); });
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').then(r => (swReg = r)).catch(() => {});
  navigator.serviceWorker.addEventListener('message', () => { if (S) refresh(); });   // a reminder arrived or was acted on
}
if (joinToken) startJoin(); else refresh(true);
