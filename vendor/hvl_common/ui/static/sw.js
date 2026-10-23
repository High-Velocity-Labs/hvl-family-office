/**
 * Shared Service Worker for High Velocity Labs Standalone iOS/iPadOS/Android PWAs.
 * Handles static asset caching, W3C Web Push notifications, and deep-link handoff.
 */

const CACHE_NAME = "hvl-pwa-v1";
const ASSETS_TO_CACHE = [
  "/manifest.json",
  "/common/theme.css",
  "/common/components.css",
  "/common/modal-dialog.css",
  "/common/chat-drawer.css",
  "/common/notifications-drawer.css",
  "/common/htmx.min.js",
  "/common/idiomorph-ext.min.js",
  "/common/marked.min.js",
  "/common/subnav.js",
  "/common/utils.js",
  "/common/modal-dialog.js",
  "/common/chat-drawer.js",
  "/common/chat-attachments.js",
  "/common/notifications-drawer.js",
  "/common/device-integrations.js",
  "/common/toast.js",
  "/common/icons.svg",
  "/common/hvl-logo-mark.svg",
  "/common/hvl-logo-120.png",
  "/common/fo-logo-mark.svg",
  "/common/fo-logo-120.png",
  "/common/asst-logo-mark.svg",
  "/common/asst-logo-120.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE).catch(() => {});
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") {
    return;
  }

  const url = new URL(event.request.url);

  if (
    url.pathname.startsWith("/api/") ||
    url.pathname.startsWith("/fragments/") ||
    url.pathname.startsWith("/mcp/") ||
    url.pathname.startsWith("/workspace/")
  ) {
    return;
  }

  if (event.request.mode === "navigate" || url.pathname === "/") {
    event.respondWith(
      fetch(event.request).catch(() => caches.match(event.request))
    );
    return;
  }

  if (url.pathname.startsWith("/static/") || url.pathname.startsWith("/common/")) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          if (response && response.status === 200) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
          }
          return response;
        })
        .catch(() => caches.match(event.request))
    );
  }
});

self.addEventListener("push", (event) => {
  let data = {};
  if (event.data) {
    try {
      data = event.data.json();
    } catch (e) {
      data = { body: event.data.text() };
    }
  }

  const title = data.title || "High Velocity Labs";
  const targetUrl = data.deep_link || data.url || "/";
  const options = {
    body: data.body || "",
    icon: data.icon || "/common/hvl-logo-120.png",
    tag: data.tag || "hvl-notification",
    data: {
      url: targetUrl,
      deep_link: targetUrl
    }
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const payload = event.notification.data || {};
  const targetUrl = payload.deep_link || payload.url || "/";

  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if ("focus" in client) {
          if ("navigate" in client && targetUrl) {
            client.navigate(targetUrl);
          }
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(targetUrl);
      }
      return null;
    })
  );
});
