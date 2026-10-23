/**
 * HVL Deploy & Version Notification Pill
 * Automatically detects backend deploys and renders an update pill.
 * Hosted web only; strictly bypassed in local desktop / standalone mode.
 */
(function () {
    if (typeof window === 'undefined') return;

    if (!window._hvlViewportSyncInitialized) {
        window._hvlViewportSyncInitialized = true;
        var _hvlBaselineViewportH = 0;
        var _hvlBlurringInput = false;
        window.hvlSyncStandaloneViewport = function () {
            var isStandalone = Boolean(
                (window.navigator && window.navigator.standalone) || (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches)
            );
            if (typeof document !== 'undefined' && document.body) {
                document.body.classList.toggle('hvl-standalone', isStandalone);
                document.body.classList.toggle('asst-standalone', isStandalone);
            }
            if (!window.visualViewport || typeof document === 'undefined') return false;
            var root = document.documentElement;
            var activeEl = document.activeElement;
            var isInput = !_hvlBlurringInput && Boolean(activeEl && (activeEl.id === 'asst-chat-input' || activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA' || activeEl.isContentEditable));
            var vvH = window.visualViewport.height || 0;
            var ih = window.innerHeight || 0;
            var docH = (root && root.clientHeight) || 0;
            var currentMax = Math.max(ih, docH, vvH);
            if (currentMax > _hvlBaselineViewportH) _hvlBaselineViewportH = currentMax;
            var screenH = (isStandalone && window.screen && window.screen.height && (!window.innerWidth || window.innerWidth <= window.screen.height)) ? window.screen.height : 0;
            var refH = Math.max(ih, docH, _hvlBaselineViewportH, screenH);
            var isKeyboardOpen = Boolean(isInput && vvH > 0 && (refH - vvH) > 100);
            if (isKeyboardOpen) {
                if (root) root.style.setProperty('--vvh', Math.round(vvH) + 'px');
                if (document.body) document.body.classList.add('hvl-keyboard-open', 'asst-keyboard-open');
                var logs = document.querySelectorAll('#asst-chat-log, #ai-advisor-messages, #chat-messages, #chat-box');
                for (var li = 0; li < logs.length; li++) {
                    if (logs[li] && logs[li].offsetParent !== null) {
                        logs[li].scrollTop = logs[li].scrollHeight;
                    }
                }
            } else {
                if (root) root.style.removeProperty('--vvh');
                if (document.body) document.body.classList.remove('hvl-keyboard-open', 'asst-keyboard-open');
            }
            var vvOffsetTop = Math.round(window.visualViewport.offsetTop || 0);
            var docScrollTop = (root && root.scrollTop) || (document.body && document.body.scrollTop) || 0;
            if ((isKeyboardOpen || window.scrollY !== 0 || vvOffsetTop !== 0 || docScrollTop !== 0) && typeof window.scrollTo === 'function') {
                if (root && root.scrollTop) root.scrollTop = 0;
                if (document.body && document.body.scrollTop) document.body.scrollTop = 0;
                window.scrollTo(0, 0);
            }
            return isKeyboardOpen;
        };
        var _hvlHandleFocusViewport = function (e) {
            var t = e && e.target;
            if (!t || !(t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
            var rel = e && e.relatedTarget;
            _hvlBlurringInput = Boolean(e && e.type === 'focusout' && !(rel && (rel.tagName === 'INPUT' || rel.tagName === 'TEXTAREA' || rel.isContentEditable)));
            window.hvlSyncStandaloneViewport();
            _hvlBlurringInput = false;
            setTimeout(window.hvlSyncStandaloneViewport, 80);
            setTimeout(window.hvlSyncStandaloneViewport, 250);
            setTimeout(window.hvlSyncStandaloneViewport, 420);
        };
        if (typeof document !== 'undefined') {
            if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', window.hvlSyncStandaloneViewport);
            else window.hvlSyncStandaloneViewport();
            document.addEventListener('focusin', _hvlHandleFocusViewport);
            document.addEventListener('focusout', _hvlHandleFocusViewport);
        }
        window.addEventListener('resize', window.hvlSyncStandaloneViewport);
        window.addEventListener('orientationchange', function () {
            _hvlBaselineViewportH = 0;
            setTimeout(window.hvlSyncStandaloneViewport, 60);
        });
        if (window.visualViewport) {
            window.visualViewport.addEventListener('resize', window.hvlSyncStandaloneViewport);
            window.visualViewport.addEventListener('scroll', window.hvlSyncStandaloneViewport);
        }
    }

    if (window._hvlVersionPillInitialized) return;
    window._hvlVersionPillInitialized = true;
    if (window.__IS_LOCAL_MODE__ || window.__FO_STANDALONE__) return;

    function isVisibleElement(el) {
        if (!el || typeof window.getComputedStyle !== 'function') return false;
        if (window.getComputedStyle(el).display === 'none') return false;
        var hdr = el.closest ? el.closest('header, .top-header') : null;
        if (hdr && window.getComputedStyle(hdr).display === 'none') return false;
        return true;
    }

    function applyInlinePillLayout(pill, pos, width, margin) {
        pill.style.position = pos;
        pill.style.top = pos === 'fixed' ? 'calc(12px + env(safe-area-inset-top, 0px))' : '';
        pill.style.left = pos === 'fixed' ? '50%' : '';
        pill.style.transform = pos === 'fixed' ? 'translateX(-50%)' : '';
        pill.style.width = width;
        pill.style.boxSizing = 'border-box';
        pill.style.justifyContent = 'center';
        pill.style.margin = margin;
        pill.style.flexShrink = '0';
        if (pos === 'fixed') pill.style.zIndex = '9999';
    }

    function placeUpdatePill(pill) {
        if (!pill || typeof document === 'undefined') return;
        var isMobile = Boolean(window.innerWidth && window.innerWidth <= 768);
        var headerActions = !isMobile
            ? document.querySelector('.header-actions, .asst-navbar-actions, .ff-controls')
            : null;
        if (isVisibleElement(headerActions)) {
            applyInlinePillLayout(pill, 'static', 'auto', '0');
            headerActions.prepend(pill);
            return;
        }
        var flowContainer = document.querySelector(
            '.asst-main-column, .content-body, main.asst-content, main, .ff-shell'
        );
        if (isVisibleElement(flowContainer)) {
            applyInlinePillLayout(pill, 'static', '100%', '0 0 8px 0');
            flowContainer.prepend(pill);
            return;
        }
        var topHeader = document.querySelector('.top-header, header');
        if (isVisibleElement(topHeader)) {
            applyInlinePillLayout(pill, 'static', 'auto', '0');
            topHeader.appendChild(pill);
            return;
        }
        applyInlinePillLayout(pill, 'fixed', 'auto', '0');
        if (document.body) document.body.appendChild(pill);
    }

    function showUpdateNotification(newVersion) {
        if (typeof document === 'undefined') return;
        var pill = document.getElementById('app-update-pill');
        if (!pill) {
            pill = document.createElement('button');
            pill.id = 'app-update-pill';
            pill.type = 'button';
            pill.className = 'btn btn-sm btn-update-pill';
            var iconVer = window.__APP_VERSION__ ? '?v=' + encodeURIComponent(window.__APP_VERSION__) : '';
            pill.innerHTML = '<svg class="hvl-icon icon-sm" width="14" height="14" aria-hidden="true" style="width:14px;height:14px;flex-shrink:0;"><use href="/common/icons.svg' + iconVer + '#icon-sparkles"></use></svg> Update available — <span style="text-decoration: underline; font-weight: 700;">Reload</span>';
            pill.setAttribute('data-tooltip', 'A new version was deployed. Click to reload.');
            pill.style.cssText = 'background-color: var(--bg-surface, #ffffff); background: color-mix(in srgb, var(--accent-blue, #3b82f6) 14%, var(--bg-surface, #ffffff)); color: var(--accent-blue, #3b82f6); border: 1px solid var(--accent-blue, #3b82f6); border-radius: var(--radius-badge, 6px); font-weight: 600; font-size: 0.75rem; padding: 4px 12px; cursor: pointer; display: inline-flex; align-items: center; gap: 4px; z-index: var(--z-popover, 500); box-shadow: 0 4px 12px rgba(0,0,0,0.25); transition: all 0.2s ease;';
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
        }
        pill.style.display = 'inline-flex';
        placeUpdatePill(pill);
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
    window.addEventListener('resize', function () {
        var pill = typeof document !== 'undefined' ? document.getElementById('app-update-pill') : null;
        if (pill && pill.style.display !== 'none') placeUpdatePill(pill);
    });

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
