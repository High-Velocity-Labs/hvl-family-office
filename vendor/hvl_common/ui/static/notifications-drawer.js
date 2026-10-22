/**
 * High Velocity Labs Shared Notification Bell & Slide-Over Drawer Controller (hvl_common)
 * File: /common/notifications-drawer.js
 */
(function (root, factory) {
    const api = factory();
    if (typeof exports === 'object' && typeof module !== 'undefined') {
        module.exports = api;
    }
    const target = typeof window !== 'undefined' ? window : root;
    if (target) {
        Object.assign(target, api);
    }
}(typeof globalThis !== 'undefined' ? globalThis : typeof window !== 'undefined' ? window : this, function () {
    'use strict';

    function formatRelativeNotificationTime(isoStr) {
        if (!isoStr) {
            return '';
        }
        const normalized = String(isoStr).trim().replace(' ', 'T');
        const withTz = /Z$|[+-]\d{2}:?\d{2}$/.test(normalized) ? normalized : `${normalized}Z`;
        const ts = Date.parse(withTz);
        if (Number.isNaN(ts)) {
            return '';
        }
        const diffSec = Math.max(0, Math.floor((Date.now() - ts) / 1000));
        if (diffSec < 60) {
            return 'just now';
        }
        const diffMin = Math.floor(diffSec / 60);
        if (diffMin < 60) {
            return `${diffMin}m`;
        }
        const diffHr = Math.floor(diffMin / 60);
        if (diffHr < 24) {
            return `${diffHr}h`;
        }
        const diffDay = Math.floor(diffHr / 24);
        return `${diffDay}d`;
    }

    function hydrateNotificationTimestamps(rootEl) {
        if (typeof document === 'undefined') {
            return;
        }
        const container = rootEl || document;
        if (typeof container.querySelectorAll !== 'function') {
            return;
        }
        const nodes = container.querySelectorAll('.hvl-notif-time[data-timestamp]');
        nodes.forEach((node) => {
            const raw = node.getAttribute('data-timestamp') || '';
            const formatted = formatRelativeNotificationTime(raw);
            if (formatted) {
                node.textContent = formatted;
            }
        });
    }

    function setNotificationBadgeCount(count) {
        if (typeof document === 'undefined') {
            return;
        }
        const badge = document.getElementById('hvl-notification-badge');
        if (!badge) {
            return;
        }
        const safeCount = Math.max(0, Number(count) || 0);
        badge.setAttribute('data-unread-count', String(safeCount));
        if (safeCount <= 0) {
            badge.textContent = '0';
            badge.setAttribute('hidden', '');
        } else {
            badge.textContent = safeCount > 9 ? '9+' : String(safeCount);
            badge.removeAttribute('hidden');
        }
    }

    function getNotificationBadgeCount() {
        if (typeof document === 'undefined') {
            return 0;
        }
        const badge = document.getElementById('hvl-notification-badge');
        if (!badge) {
            return 0;
        }
        return Math.max(0, Number(badge.getAttribute('data-unread-count') || 0));
    }

    function _resolveUrl(path) {
        if (typeof window !== 'undefined' && typeof window.appendSessionQuery === 'function') {
            return window.appendSessionQuery(path);
        }
        return path;
    }

    async function refreshNotificationsDrawer() {
        if (typeof document === 'undefined' || typeof fetch !== 'function') {
            return;
        }
        const bodyEl = document.getElementById('hvl-notifications-drawer-body');
        if (!bodyEl) {
            return;
        }
        try {
            const resp = await fetch(_resolveUrl('/api/notifications/fragment'), {
                method: 'GET',
                headers: { 'Accept': 'text/html' },
                skipReactiveMorph: true
            });
            if (!resp || !resp.ok) {
                return;
            }
            const html = await resp.text();
            const hdrCount = resp.headers && typeof resp.headers.get === 'function'
                ? resp.headers.get('X-Notification-Count')
                : null;
            if (typeof window !== 'undefined' && window.Idiomorph && typeof window.Idiomorph.morph === 'function') {
                window.Idiomorph.morph(bodyEl, html);
            } else {
                const temp = document.createElement('div');
                temp.innerHTML = html.trim();
                const replacement = temp.firstElementChild;
                if (replacement && bodyEl.parentNode) {
                    bodyEl.parentNode.replaceChild(replacement, bodyEl);
                }
            }
            const updatedBody = document.getElementById('hvl-notifications-drawer-body');
            hydrateNotificationTimestamps(updatedBody);
            const attrCount = updatedBody ? updatedBody.getAttribute('data-unread-count') : null;
            if (hdrCount !== null && hdrCount !== undefined) {
                setNotificationBadgeCount(Number(hdrCount));
            } else if (attrCount !== null && attrCount !== undefined) {
                setNotificationBadgeCount(Number(attrCount));
            }
        } catch (_) {}
    }

    function openNotificationsDrawer() {
        if (typeof document === 'undefined') {
            return;
        }
        const drawer = document.getElementById('hvl-notifications-drawer');
        const backdrop = document.getElementById('hvl-notifications-backdrop');
        if (!drawer) {
            return;
        }
        if (backdrop) {
            backdrop.removeAttribute('hidden');
            backdrop.classList.add('open');
        }
        drawer.classList.add('open');
        drawer.setAttribute('aria-hidden', 'false');
        hydrateNotificationTimestamps(drawer);
        refreshNotificationsDrawer();
    }

    function closeNotificationsDrawer() {
        if (typeof document === 'undefined') {
            return;
        }
        const drawer = document.getElementById('hvl-notifications-drawer');
        const backdrop = document.getElementById('hvl-notifications-backdrop');
        if (drawer) {
            drawer.classList.remove('open');
            drawer.setAttribute('aria-hidden', 'true');
        }
        if (backdrop) {
            backdrop.classList.remove('open');
            backdrop.setAttribute('hidden', '');
        }
    }

    function toggleNotificationsDrawer() {
        if (typeof document === 'undefined') {
            return;
        }
        const drawer = document.getElementById('hvl-notifications-drawer');
        if (!drawer) {
            return;
        }
        if (drawer.classList.contains('open')) {
            closeNotificationsDrawer();
        } else {
            openNotificationsDrawer();
        }
    }

    function hvlNavigateNotification(deepLink) {
        const targetUrl = String(deepLink || '/').trim() || '/';
        if (typeof window !== 'undefined' && typeof window.handleNotificationDeepLink === 'function') {
            try {
                const handled = window.handleNotificationDeepLink(targetUrl);
                if (handled === true) {
                    return;
                }
            } catch (_) {}
        }
        if (typeof window !== 'undefined' && window.location) {
            window.location.href = targetUrl;
        }
    }

    async function _postNotificationAction(endpoint, payload) {
        if (typeof fetch !== 'function') {
            return null;
        }
        try {
            return await fetch(_resolveUrl(endpoint), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload || {})
            });
        } catch (_) {
            return null;
        }
    }

    async function handleNotificationItemClick(itemEl, evt) {
        if (!itemEl) {
            return;
        }
        if (evt && typeof evt.preventDefault === 'function') {
            evt.preventDefault();
        }
        const notifId = itemEl.getAttribute('data-notif-id') || '';
        const dedupeKey = itemEl.getAttribute('data-dedupe-key') || '';
        const deepLink = itemEl.getAttribute('data-deep-link') || itemEl.getAttribute('href') || '/';
        const currentCount = getNotificationBadgeCount();
        if (currentCount > 0 && !itemEl.classList.contains('is-read')) {
            setNotificationBadgeCount(currentCount - 1);
            itemEl.classList.add('is-read');
        }
        await _postNotificationAction('/api/notifications/mark-read', {
            id: notifId,
            dedupe_key: dedupeKey
        });
        closeNotificationsDrawer();
        hvlNavigateNotification(deepLink);
    }

    async function markAllNotificationsRead() {
        const resp = await _postNotificationAction('/api/notifications/mark-read', { all: true });
        if (resp && resp.status === 403 && typeof window !== 'undefined' && typeof window.showSandboxToast === 'function') {
            window.showSandboxToast();
            return;
        }
        setNotificationBadgeCount(0);
        await refreshNotificationsDrawer();
    }

    async function clearAllNotifications() {
        const resp = await _postNotificationAction('/api/notifications/clear', { clear_computed: true });
        if (resp && resp.status === 403 && typeof window !== 'undefined' && typeof window.showSandboxToast === 'function') {
            window.showSandboxToast();
            return;
        }
        setNotificationBadgeCount(0);
        await refreshNotificationsDrawer();
    }

    function initNotificationsDrawer() {
        if (typeof document === 'undefined' || typeof window === 'undefined') {
            return;
        }
        if (window._hvlNotificationsDrawerBound) {
            hydrateNotificationTimestamps(document);
            return;
        }
        window._hvlNotificationsDrawerBound = true;
        hydrateNotificationTimestamps(document);

        document.addEventListener('click', (evt) => {
            const target = evt.target;
            if (!target || typeof target.closest !== 'function') {
                return;
            }
            const toggleBtn = target.closest('[data-action="toggle-notifications-drawer"]');
            if (toggleBtn) {
                evt.preventDefault();
                toggleNotificationsDrawer();
                return;
            }
            if (target.closest('#btn-notif-drawer-close') || target.id === 'hvl-notifications-backdrop') {
                evt.preventDefault();
                closeNotificationsDrawer();
                return;
            }
            if (target.closest('#btn-notif-mark-all-read')) {
                evt.preventDefault();
                markAllNotificationsRead();
                return;
            }
            if (target.closest('#btn-notif-clear-all')) {
                evt.preventDefault();
                clearAllNotifications();
                return;
            }
            const itemEl = target.closest('.hvl-notif-item[data-notif-item="true"]');
            if (itemEl) {
                handleNotificationItemClick(itemEl, evt);
            }
        });

        document.addEventListener('keydown', (evt) => {
            if (evt.key === 'Escape') {
                closeNotificationsDrawer();
            }
        });

        if (typeof window.registerSectionHydrator === 'function') {
            window.registerSectionHydrator('hvl-notifications-drawer-body', () => {
                hydrateNotificationTimestamps(document.getElementById('hvl-notifications-drawer-body'));
            });
        }

        if (typeof window.effect === 'function' && typeof window.getDomainSignal === 'function') {
            let initialized = false;
            window.effect(() => {
                const sig = window.getDomainSignal('notifications');
                const ver = sig.value;
                if (initialized && ver > 0) {
                    refreshNotificationsDrawer();
                }
                initialized = true;
            });
        }
    }

    if (typeof document !== 'undefined') {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initNotificationsDrawer);
        } else {
            initNotificationsDrawer();
        }
    }

    return {
        formatRelativeNotificationTime,
        hydrateNotificationTimestamps,
        setNotificationBadgeCount,
        getNotificationBadgeCount,
        refreshNotificationsDrawer,
        openNotificationsDrawer,
        closeNotificationsDrawer,
        toggleNotificationsDrawer,
        hvlNavigateNotification,
        markAllNotificationsRead,
        clearAllNotifications,
        initNotificationsDrawer
    };
}));
