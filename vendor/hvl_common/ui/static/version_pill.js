/**
 * HVL Deploy & Version Notification Pill
 * Automatically detects backend deploys and renders an update pill.
 * Hosted web only; strictly bypassed in local desktop / standalone mode.
 */
(function () {
    if (typeof window === 'undefined') return;
    if (window._hvlVersionPillInitialized) return;
    window._hvlVersionPillInitialized = true;
    if (window.__IS_LOCAL_MODE__ || window.__FO_STANDALONE__) return;

    function showUpdateNotification(newVersion) {
        if (typeof document === 'undefined') return;
        var pill = document.getElementById('app-update-pill');
        if (!pill) {
            pill = document.createElement('button');
            pill.id = 'app-update-pill';
            pill.type = 'button';
            pill.className = 'btn btn-sm btn-update-pill';
            var iconVer = window.__APP_VERSION__ ? '?v=' + encodeURIComponent(window.__APP_VERSION__) : '';
            pill.innerHTML = '<svg class="icon icon-sm" aria-hidden="true"><use href="/common/icons.svg' + iconVer + '#icon-sparkles"></use></svg> Update available — <span style="text-decoration: underline; font-weight: 700;">Reload</span>';
            pill.setAttribute('data-tooltip', 'A new version was deployed. Click to reload.');
            pill.style.cssText = 'background: rgba(59, 130, 246, 0.15); color: var(--accent-blue, #3b82f6); border: 1px solid var(--accent-blue, #3b82f6); border-radius: var(--radius-badge, 6px); font-weight: 600; font-size: 0.75rem; padding: 4px 12px; cursor: pointer; display: inline-flex; align-items: center; gap: 4px; z-index: var(--z-popover, 500); box-shadow: 0 4px 12px rgba(0,0,0,0.25); transition: all 0.2s ease;';
            pill.onclick = async function () {
                pill.textContent = 'Updating...';
                if (typeof window.hvlForceCacheReset === 'function') return window.hvlForceCacheReset();
                if ('caches' in window) {
                    try {
                        var keys = await caches.keys();
                        await Promise.all(keys.map(function (k) { return caches.delete(k); }));
                    } catch (_) {}
                }
                if ('serviceWorker' in navigator) {
                    try {
                        var regs = await navigator.serviceWorker.getRegistrations();
                        for (var i = 0; i < regs.length; i++) await regs[i].unregister().catch(function () {});
                    } catch (_) {}
                }
                window.location.reload();
            };

            var headerActions = document.querySelector('.header-actions');
            var topHeader = document.querySelector('.top-header') || document.querySelector('header');
            if (headerActions && window.getComputedStyle(headerActions).display !== 'none') {
                headerActions.prepend(pill);
            } else if (topHeader && window.getComputedStyle(topHeader).display !== 'none') {
                topHeader.appendChild(pill);
            } else {
                Object.assign(pill.style, { position: 'fixed', top: '14px', left: '50%', transform: 'translateX(-50%)', zIndex: '9999' });
                document.body.appendChild(pill);
            }
        } else {
            pill.style.display = 'inline-flex';
        }
    }

    function checkAppVersion(serverVersion) {
        if (!serverVersion || !window.__APP_VERSION__) return;
        var cleanServer = String(serverVersion).trim();
        var cleanCurrent = String(window.__APP_VERSION__).trim();
        if (cleanServer && cleanCurrent && cleanServer !== cleanCurrent) {
            showUpdateNotification(cleanServer);
        }
    }

    window.checkAppVersion = checkAppVersion;
    window.showUpdateNotification = showUpdateNotification;

    // 1. Hook fetch to inspect X-App-Version
    if (typeof window.fetch === 'function') {
        var _origFetch = window.fetch;
        window.fetch = async function () {
            var resp = await _origFetch.apply(this, arguments);
            try {
                if (resp && resp.headers && typeof resp.headers.get === 'function') {
                    var v = resp.headers.get('X-App-Version');
                    if (v) checkAppVersion(v);
                }
            } catch (e) {}
            return resp;
        };
    }

    // 2. Hook HTMX and Tab Visibility
    if (typeof document !== 'undefined') {
        document.addEventListener('htmx:afterOnLoad', function (evt) {
            var xhr = evt.detail && evt.detail.xhr;
            if (xhr && typeof xhr.getResponseHeader === 'function') {
                try {
                    var v = xhr.getResponseHeader('X-App-Version');
                    if (v) checkAppVersion(v);
                } catch (e) {}
            }
        });

        // 3. Tab visibility check (silent probe when switching back to tab)
        var _lastCheckTime = 0;
        document.addEventListener('visibilitychange', function () {
            if (document.visibilityState === 'visible') {
                var now = Date.now();
                // Throttle to at most once every 30 seconds on tab switch
                if (now - _lastCheckTime > 30000) {
                    _lastCheckTime = now;
                    fetch('/api/health', { method: 'HEAD', cache: 'no-cache' }).catch(function () {});
                }
            }
        });
    }
})();
