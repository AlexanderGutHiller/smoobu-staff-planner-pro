/* Basic Service Worker for Web Push Notifications */
self.addEventListener('push', function (event) {
  let payload = {};
  try {
    if (event.data) payload = event.data.json();
  } catch (e) {
    payload = { title: 'Benachrichtigung', body: event.data ? event.data.text() : '' };
  }
  const title = payload.title || 'Benachrichtigung';
  const body = payload.body || '';
  const url = payload.url || '/';
  const options = {
    body,
    icon: '/static/icon-192.png',
    badge: '/static/icon-192.png',
    data: { url }
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  const url = (event.notification && event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (clientList) {
      for (let i = 0; i < clientList.length; i++) {
        const client = clientList[i];
        if ('focus' in client) {
          client.navigate(url);
          return client.focus();
        }
      }
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});

