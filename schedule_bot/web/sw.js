// Service worker: shows reminders and handles their buttons. No offline cache:
// the panel is useless without the server anyway.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

const tellPages = () => self.clients.matchAll({ type: 'window' })
  .then(cs => cs.forEach(c => c.postMessage('refresh')));

self.addEventListener('push', e => {
  const d = e.data ? e.data.json() : { title: 'Schedule', body: '' };
  const reminder = d.kind === 'reminder';
  e.waitUntil(Promise.all([
    self.registration.showNotification(d.title, {
      body: d.body,
      icon: '/icon-192.png',
      badge: '/badge.png',
      tag: reminder ? 'task-' + d.id : 'schedule',
      renotify: true,               // a snoozed task rings again, not silently
      silent: false,                // sound + vibration: what lets Android pop it on screen
      timestamp: Date.now(),
      requireInteraction: reminder, // stays until you act on it
      vibrate: [200, 100, 200, 100, 200],
      data: d,
      actions: reminder ? [{ action: 'done', title: '✅ Done' }, { action: 'snooze', title: '⏰ 10 min' }] : [],
    }),
    tellPages(),
  ]));
});

self.addEventListener('notificationclick', e => {
  const d = e.notification.data || {};
  e.notification.close();
  if (e.action === 'done' || e.action === 'snooze') {
    // Signed per task, so this works without the login cookie.
    e.waitUntil(fetch('/api/notify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: d.id, sig: d.sig, action: e.action, minutes: 10 }),
    }).then(tellPages, () => {}));
    return;
  }
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(cs => {
    const open = cs.find(c => new URL(c.url).origin === self.location.origin);
    if (open) { open.postMessage('refresh'); return open.focus(); }
    return self.clients.openWindow('/#today');
  }));
});
