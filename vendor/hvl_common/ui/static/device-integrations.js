/**
 * Shared High Velocity Labs PWA Service Worker Registration, W3C Web Push
 * Subscription / Test Push, and Siri Shortcut Key Management (`/common/device-integrations.js`).
 */

(function () {
  "use strict";

  function notifyToast(message, type) {
    if (typeof window.showToast === "function") {
      window.showToast(message, type || "info");
    } else if (typeof window.hvlToast === "function") {
      window.hvlToast(message, type || "info");
    }
  }

  function jsonRequest(url, method, body) {
    if (typeof window.asstApiRequest === "function") {
      return window.asstApiRequest(url, method, body);
    }
    return fetch(url, {
      method: method || "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : null
    }).then(function (resp) {
      return resp.json();
    });
  }

  function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; i += 1) {
      outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
  }

  function registerServiceWorker() {
    if (!("serviceWorker" in navigator)) {
      return Promise.resolve(null);
    }
    return navigator.serviceWorker
      .register("/sw.js", { scope: "/" })
      .catch(function () {
        return null;
      });
  }

  window.hvlRegisterServiceWorker = registerServiceWorker;

  async function handleEnablePush(btn) {
    const statusSel = btn.getAttribute("data-status-target") || "#asst-push-status";
    const statusEl = document.querySelector(statusSel) || document.getElementById("asst-push-status");
    const isIOS =
      /iPhone|iPad|iPod/.test(navigator.userAgent) ||
      (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    const isStandalone =
      (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) ||
      window.navigator.standalone === true;

    if (!("serviceWorker" in navigator) || !("Notification" in window)) {
      const msg =
        isIOS && !isStandalone
          ? "iOS requires installing to Home Screen first: Share -> Add to Home Screen."
          : "Push notifications are not supported on this browser.";
      if (statusEl) {
        statusEl.textContent = msg;
      }
      notifyToast(msg, "warning");
      return;
    }

    try {
      if (statusEl) {
        statusEl.textContent = "Requesting permission...";
      }
      const perm = await Notification.requestPermission();
      if (perm !== "granted") {
        if (statusEl) {
          statusEl.textContent = "Permission denied.";
        }
        return;
      }

      let endpoint = "https://push.apple.com/sub/device_" + Date.now();
      let keys = { p256dh: "key_p256dh", auth: "key_auth" };

      if ("PushManager" in window) {
        try {
          await registerServiceWorker();
          const reg = await navigator.serviceWorker.ready;
          let sub = await reg.pushManager.getSubscription();
          if (!sub) {
            const subOpts = { userVisibleOnly: true };
            try {
              const vapidResp = await fetch("/api/notifications/vapid-public-key").then(function (r) {
                return r.json();
              });
              if (vapidResp && vapidResp.public_key) {
                subOpts.applicationServerKey = urlBase64ToUint8Array(vapidResp.public_key);
              }
            } catch (_) {}
            sub = await reg.pushManager.subscribe(subOpts);
          }
          if (sub) {
            endpoint = sub.endpoint;
            const jsonSub = typeof sub.toJSON === "function" ? sub.toJSON() : null;
            if (jsonSub && jsonSub.keys) {
              keys = jsonSub.keys;
            }
          }
        } catch (_) {}
      }

      const label = isIOS ? "Apple PWA" : "Web Device";
      const res = await jsonRequest("/api/notifications/subscribe", "POST", {
        endpoint: endpoint,
        keys: keys,
        device_label: label
      });
      const okMsg = res && res.success ? "Notifications enabled!" : (res && res.error) || "Failed to enable.";
      if (statusEl) {
        statusEl.textContent = okMsg;
      }
      if (res && res.success) {
        notifyToast("Push notifications enabled on this device.", "success");
      }
    } catch (err) {
      if (statusEl) {
        statusEl.textContent = "Error: " + (err && err.message ? err.message : String(err));
      }
    }
  }

  async function handleTestPush(btn) {
    const statusSel = btn.getAttribute("data-status-target") || "#asst-push-status";
    const statusEl = document.querySelector(statusSel) || document.getElementById("asst-push-status");
    try {
      if (statusEl) {
        statusEl.textContent = "Sending test push...";
      }
      const res = await jsonRequest("/api/notifications/test-push", "POST", {});
      if (res && (res.success || res.status === "ok")) {
        const msg =
          res.devices_notified > 0
            ? "Test push sent (" + res.devices_notified + " device(s))."
            : "Test notification created in drawer.";
        if (statusEl) {
          statusEl.textContent = msg;
        }
        notifyToast(msg, "success");
        if (
          "serviceWorker" in navigator &&
          "Notification" in window &&
          Notification.permission === "granted"
        ) {
          try {
            const reg = await navigator.serviceWorker.ready;
            if (reg && typeof reg.showNotification === "function") {
              await reg.showNotification(res.title || "HVL Test Push", {
                body: res.body || "Push notifications are active on this device.",
                icon: "/common/hvl-logo-120.png",
                data: { url: "/", deep_link: "/" }
              });
            }
          } catch (_) {}
        }
      } else {
        const errMsg = (res && res.error) || "Failed to send test push.";
        if (statusEl) {
          statusEl.textContent = errMsg;
        }
        notifyToast(errMsg, "error");
      }
    } catch (err) {
      if (statusEl) {
        statusEl.textContent = "Error: " + (err && err.message ? err.message : String(err));
      }
    }
  }

  async function handleSiriAction(btn, action) {
    const targetSel = btn.getAttribute("data-display-target") || "#siri-token-display";
    const disp = document.querySelector(targetSel) || document.getElementById("siri-token-display");

    if (action === "hvl-copy-siri") {
      const val = disp ? disp.textContent.trim() : "";
      if (val && navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(val);
        notifyToast("Siri Shortcut key copied to clipboard.", "success");
      }
      return;
    }

    if (action === "hvl-revoke-siri") {
      const rev = await jsonRequest("/api/siri/revoke-token", "POST", {});
      if (disp) {
        disp.textContent = rev && rev.success ? "Siri key revoked." : (rev && rev.error) || "Failed to revoke key.";
      }
      return;
    }

    const data = await jsonRequest("/api/siri/mint-token", "POST", {});
    const tok = (data && (data.siri_token || data.token)) || "";
    if (disp) {
      disp.textContent = tok || (data && data.error) || "Failed to generate Siri key.";
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    registerServiceWorker();
  });

  document.addEventListener("click", function (e) {
    const btn = e.target.closest("button");
    if (!btn) {
      return;
    }
    const action = btn.getAttribute("data-action") || "";
    if (action === "hvl-enable-push" || btn.id === "asst-enable-push-btn") {
      handleEnablePush(btn);
    } else if (action === "hvl-test-push" || btn.id === "hvl-test-push-btn") {
      handleTestPush(btn);
    } else if (action === "hvl-mint-siri" || btn.id === "asst-mint-siri-btn") {
      handleSiriAction(btn, "hvl-mint-siri");
    } else if (action === "hvl-revoke-siri" || btn.id === "hvl-revoke-siri-btn") {
      handleSiriAction(btn, "hvl-revoke-siri");
    } else if (action === "hvl-copy-siri") {
      handleSiriAction(btn, "hvl-copy-siri");
    }
  });
})();
