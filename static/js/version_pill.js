/**
 * HVL Deploy & Version Notification Pill
 * Automatically detects backend deploys and renders an update pill.
 * Hosted web only; strictly bypassed in local desktop / standalone mode.
 */
(function () {
    if (typeof window === 'undefined') return;
    if (window.__IS_LOCAL_MODE__ || window.__FO_STANDALONE__) return;

    function showUpdateNotification(newVersion) {
        if (typeof document === 'undefined') return;
        var pill = document.getElementById('app-update-pill');
        if (!pill) {
            pill = document.createElement('button');
            pill.id = 'app-update-pill';
            pill.type = 'button';
            pill.className = 'btn btn-sm btn-update-pill';
            pill.innerHTML = '✨ Update available — <span style="text-decoration: underline; font-weight: 700;">Reload</span>';
            pill.setAttribute('data-tooltip', 'A new version of HVL Family Office was deployed. Click to reload.');
            pill.style.cssText = 'background: rgba(59, 130, 246, 0.15); color: var(--accent-blue, #3b82f6); border: 1px solid var(--accent-blue, #3b82f6); border-radius: var(--radius-badge, 6px); font-weight: 600; font-size: 0.75rem; padding: 4px 12px; cursor: pointer; display: inline-flex; align-items: center; gap: 4px; z-index: var(--z-popover, 500); box-shadow: 0 4px 12px rgba(0,0,0,0.25); transition: all 0.2s ease;';
            pill.onclick = function () {
                window.location.reload();
            };

            var headerActions = document.querySelector('.header-actions');
            var topHeader = document.querySelector('.top-header') || document.querySelector('header');
            if (headerActions) {
                headerActions.prepend(pill);
            } else if (topHeader) {
                topHeader.appendChild(pill);
            } else {
                pill.style.position = 'fixed';
                pill.style.top = '14px';
                pill.style.left = '50%';
                pill.style.transform = 'translateX(-50%)';
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
