/** HVL Common UI - Shared Utility Functions (hvl_common) | UMD */
(function (root, factory) {
    const u = factory();
    if (typeof exports === 'object' && typeof module !== 'undefined') module.exports = u;
    const target = (typeof window !== 'undefined') ? window : root;
    if (target) Object.assign(target, { utils: u }, u);
}(typeof globalThis !== 'undefined' ? globalThis : typeof window !== 'undefined' ? window : this, function () {
    'use strict';
    const THEME_STORAGE_KEYS = ['hvl_theme', 'asst_theme', 'fo_theme', 'ff_theme'];
    let _activeThemeKey = 'hvl_theme';

    /** Escape special HTML characters to prevent XSS. */
    const escapeHtml = (str) => (!str ? '' : String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'));

    /** Format number as standard US currency. */
    const fmtCurrency = (val, maxFrac = 2) => (val === null || val === undefined || isNaN(val))
        ? '$0.00'
        : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: maxFrac, maximumFractionDigits: maxFrac }).format(val);

    /** Format large numbers into compact human-readable representations ($1.23M, $45.6k). */
    const fmtShortCurrency = (val) => {
        if (val === null || val === undefined || isNaN(val)) return '$0';
        if (Math.abs(val) >= 1e6) return `$${(val / 1e6).toFixed(2)}M`;
        if (Math.abs(val) >= 1e3) return `$${(val / 1e3).toFixed(1)}k`;
        return fmtCurrency(val);
    };

    /** Format float into percentage representation (0.125 -> 12.5%). */
    const fmtPct = (val) => (val === null || val === undefined || isNaN(val) ? '0.0%' : `${(val * 100).toFixed(1)}%`);

    /** Detect touch-enabled devices for mobile-optimized interactions. */
    const isTouchDevice = () => typeof window !== 'undefined' && (('ontouchstart' in window) || (navigator.maxTouchPoints > 0) || Boolean(window.matchMedia && window.matchMedia('(hover: none)').matches));

    /** Fetch an SSR HTML fragment via HTMX and morph it into the target container via Idiomorph. */
    const morphFragment = (target, url, options = {}) => {
        if (!target || !url) return Promise.resolve();
        let resolvedTarget = target;
        if (typeof target === 'string' && typeof document !== 'undefined' && !target.startsWith('#') && !target.startsWith('.') && !target.startsWith('[')) {
            resolvedTarget = document.getElementById(target) || target;
        }
        const ctx = Object.assign({}, options || {}, { target: resolvedTarget, swap: (options && options.swap) || 'morph' });
        return (typeof window !== 'undefined' && window.htmx && typeof window.htmx.ajax === 'function') ? window.htmx.ajax('GET', url, ctx) : Promise.resolve();
    };

    /** Retrieve stored theme preference ('light', 'dark', or 'system'). */
    const getThemePreference = (storageKey) => {
        const keys = storageKey ? [storageKey, ...THEME_STORAGE_KEYS] : THEME_STORAGE_KEYS;
        try {
            if (typeof localStorage !== 'undefined') {
                for (const k of keys) {
                    const val = localStorage.getItem(k);
                    if (val === 'light' || val === 'dark' || val === 'system') return val;
                }
            }
        } catch (_) {}
        return 'system';
    };

    /** Resolve effective theme ('light' or 'dark') from user preference or OS color scheme. */
    const getResolvedTheme = (storageKey, defaultTheme = 'light') => {
        const pref = getThemePreference(storageKey);
        if (pref === 'light' || pref === 'dark') return pref;
        if (typeof window !== 'undefined' && window.matchMedia) {
            try { return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'; } catch (_) {}
        }
        return defaultTheme === 'dark' ? 'dark' : 'light';
    };

    /** Apply resolved theme to document root, sync toggle labels/cards, and emit 'themechange'. */
    const applyTheme = (resolvedTheme, pref) => {
        const theme = resolvedTheme === 'dark' ? 'dark' : 'light';
        const effectivePref = pref || getThemePreference();
        if (typeof document !== 'undefined' && document.documentElement) {
            document.documentElement.setAttribute('data-theme', theme);
            const csMeta = document.querySelector ? document.querySelector('meta[name="color-scheme"]') : null;
            if (csMeta) csMeta.setAttribute('content', effectivePref === 'system' ? 'light dark' : theme);
            const lbl = document.getElementById('theme-toggle-label');
            if (lbl) lbl.textContent = theme === 'dark' ? 'Dark' : 'Light';
            const btnLbl = document.getElementById('theme-btn-label');
            if (btnLbl) btnLbl.textContent = theme === 'dark' ? 'Light Mode' : 'Dark Mode';
            if (typeof document.querySelectorAll === 'function') {
                document.querySelectorAll('.theme-icon-sun, #theme-icon-sun').forEach((el) => {
                    if (el.style) el.style.display = theme === 'dark' ? 'inline-block' : 'none';
                });
                document.querySelectorAll('.theme-icon-moon, #theme-icon-moon').forEach((el) => {
                    if (el.style) el.style.display = theme === 'dark' ? 'none' : 'inline-block';
                });
                document.querySelectorAll('.theme-choice-card').forEach((card) => {
                    const isSelected = card.getAttribute('data-theme-value') === effectivePref;
                    const radio = card.querySelector ? card.querySelector('input[type="radio"]') : null;
                    if (radio) radio.checked = isSelected;
                    if (card.style) {
                        card.style.borderColor = isSelected ? 'var(--accent-blue)' : 'var(--border-subtle)';
                        card.style.boxShadow = isSelected ? '0 0 0 2px var(--accent-blue-border, rgba(59, 130, 246, 0.25))' : 'none';
                    }
                });
            }
        }
        if (typeof window !== 'undefined' && typeof window.dispatchEvent === 'function' && typeof CustomEvent === 'function') {
            try { window.dispatchEvent(new CustomEvent('themechange', { detail: { theme, preference: effectivePref } })); } catch (_) {}
        }
    };

    /** Persist theme preference ('light', 'dark', or 'system') and apply immediately. */
    const setThemePreference = (pref, storageKey) => {
        const effKey = storageKey || _activeThemeKey || 'hvl_theme';
        try {
            if (typeof localStorage !== 'undefined') {
                THEME_STORAGE_KEYS.forEach((k) => localStorage.setItem(k, pref));
                if (effKey && !THEME_STORAGE_KEYS.includes(effKey)) localStorage.setItem(effKey, pref);
            }
        } catch (_) {}
        const resolved = (pref === 'light' || pref === 'dark') ? pref : getResolvedTheme(effKey);
        applyTheme(resolved, pref);
        return resolved;
    };

    /** Toggle active theme between 'dark' and 'light' and persist preference. */
    const toggleTheme = (storageKey) => {
        const effKey = storageKey || _activeThemeKey || 'hvl_theme';
        let current = (typeof document !== 'undefined' && document.documentElement) ? document.documentElement.getAttribute('data-theme') : null;
        if (current !== 'dark' && current !== 'light') current = getResolvedTheme(effKey);
        const next = current === 'dark' ? 'light' : 'dark';
        setThemePreference(next, effKey);
        return next;
    };

    /** Initialize theme on load and bind appearance cards, OS media query, and cross-tab storage sync. */
    const initTheme = (options = {}) => {
        const storageKey = options.storageKey || _activeThemeKey || 'hvl_theme';
        _activeThemeKey = storageKey;
        const defaultTheme = options.defaultTheme || 'light';
        const pref = getThemePreference(storageKey);
        const resolved = (pref === 'light' || pref === 'dark') ? pref : getResolvedTheme(storageKey, defaultTheme);
        applyTheme(resolved, pref);
        if (typeof document !== 'undefined') {
            if (typeof document.querySelectorAll === 'function') {
                document.querySelectorAll('.theme-choice-card').forEach((card) => {
                    if (card.dataset && card.dataset.themeBound === '1') return;
                    if (card.dataset) card.dataset.themeBound = '1';
                    card.addEventListener('click', () => {
                        const val = card.getAttribute('data-theme-value');
                        if (val) setThemePreference(val, _activeThemeKey);
                    });
                });
            }
            if (typeof document.addEventListener === 'function' && !document._hvlThemeDelegated) {
                document._hvlThemeDelegated = true;
                document.addEventListener('click', (e) => {
                    const t = e && e.target && e.target.closest ? e.target.closest('.theme-choice-card[data-theme-value], [data-action="toggle-theme"], #btn-theme-toggle') : null;
                    if (!t) return;
                    if (t.classList && t.classList.contains('theme-choice-card')) {
                        if (t.dataset && t.dataset.themeBound === '1') return;
                        const val = t.getAttribute('data-theme-value');
                        if (val) setThemePreference(val, _activeThemeKey);
                    } else {
                        toggleTheme(_activeThemeKey);
                    }
                });
                document.addEventListener('htmx:afterSettle', () => {
                    const curPref = getThemePreference(_activeThemeKey);
                    applyTheme(getResolvedTheme(_activeThemeKey, defaultTheme), curPref);
                });
            }
        }
        if (typeof window !== 'undefined') {
            if (window.matchMedia && !window._hvlThemeMediaBound) {
                window._hvlThemeMediaBound = true;
                try {
                    const mq = window.matchMedia('(prefers-color-scheme: dark)');
                    if (mq && typeof mq.addEventListener === 'function') {
                        mq.addEventListener('change', (e) => {
                            if (getThemePreference(storageKey) === 'system') applyTheme(e.matches ? 'dark' : 'light', 'system');
                        });
                    }
                } catch (_) {}
            }
            if (typeof window.addEventListener === 'function' && !window._hvlThemeStorageBound) {
                window._hvlThemeStorageBound = true;
                window.addEventListener('storage', (e) => {
                    if (!e || !e.key || THEME_STORAGE_KEYS.includes(e.key) || e.key === storageKey) {
                        const updatedPref = getThemePreference(storageKey);
                        applyTheme(getResolvedTheme(storageKey, defaultTheme), updatedPref);
                    }
                });
            }
        }
        return resolved;
    };

    let _subnavPendingCalls = [];
    let _subnavLoading = false;

    const initScrollableRibbon = (container, opts = {}) => {
        if (typeof window !== 'undefined' && window.HVLSubnav && typeof window.HVLSubnav.initScrollableRibbon === 'function') {
            return window.HVLSubnav.initScrollableRibbon(container, opts);
        }
        if (typeof require === 'function') {
            try {
                const subnavMod = require('./subnav.js');
                if (subnavMod && typeof subnavMod.initScrollableRibbon === 'function') return subnavMod.initScrollableRibbon(container, opts);
            } catch (_) {}
        }
        if (typeof document === 'undefined') return [];
        const hasTargets = container || document.querySelector('.hvl-subnav-container, .features-subnav-container, [data-subnav-container]');
        if (!hasTargets || (typeof navigator !== 'undefined' && /jsdom/i.test(navigator.userAgent || ''))) return [];
        _subnavPendingCalls.push([container, opts]);
        if (!_subnavLoading && document.head && typeof document.createElement === 'function') {
            _subnavLoading = true;
            const s = document.createElement('script');
            s.src = (typeof window !== 'undefined' && window.location && window.location.protocol === 'file:') ? './common/subnav.js' : '/common/subnav.js';
            s.onload = () => {
                const q = _subnavPendingCalls.splice(0);
                if (typeof window !== 'undefined' && window.HVLSubnav && typeof window.HVLSubnav.initScrollableRibbon === 'function') {
                    q.forEach(([c, o]) => window.HVLSubnav.initScrollableRibbon(c, o));
                }
            };
            document.head.appendChild(s);
        }
        return [];
    };

    const initSubnav = initScrollableRibbon;

    /** Initialize reactive X-Domain-Versions + BroadcastChannel + [data-depends][data-fragment] morphing. */
    const initDomainSync = (options = {}) => {
        const domainVersions = Object.assign({}, options.initialVersions || (typeof window !== 'undefined' && window.__DOMAIN_VERSIONS__) || {});
        const channelName = options.channelName || 'hvl_domain_versions';
        const fragmentPrefix = options.fragmentPrefix || '/fragments/';
        const bc = (typeof BroadcastChannel !== 'undefined') ? new BroadcastChannel(channelName) : null;
        const applyDomainVersions = (incoming, fromBroadcast = false) => {
            if (!incoming || typeof incoming !== 'object') return [];
            const changed = new Set();
            Object.entries(incoming).forEach(([dom, ver]) => {
                const nextVer = Number(ver || 0);
                const prevVer = Number(domainVersions[dom] || 0);
                if (nextVer > prevVer) { domainVersions[dom] = nextVer; changed.add(dom); }
            });
            if (changed.size === 0) return [];
            if (!fromBroadcast && bc) {
                try { bc.postMessage({ type: 'domain-versions', versions: domainVersions }); } catch (_) {}
            }
            if (options.morphFragments !== false && typeof document !== 'undefined' && typeof document.querySelectorAll === 'function') {
                document.querySelectorAll('[data-depends][data-fragment]').forEach((sec) => {
                    const deps = (sec.getAttribute('data-depends') || '').split(',').map((s) => s.trim()).filter(Boolean);
                    if (deps.some((d) => changed.has(d))) {
                        const frag = sec.getAttribute('data-fragment');
                        const url = typeof options.resolveFragmentUrl === 'function' ? options.resolveFragmentUrl(frag, sec) : `${fragmentPrefix}${encodeURIComponent(frag)}`;
                        morphFragment(sec, url, { swap: 'innerHTML' });
                    }
                });
            }
            if (typeof options.onDomainsChanged === 'function') options.onDomainsChanged(Array.from(changed), domainVersions, fromBroadcast);
            return Array.from(changed);
        };
        if (bc) {
            bc.addEventListener('message', (ev) => {
                if (ev.data && ev.data.type === 'domain-versions') applyDomainVersions(ev.data.versions, true);
            });
        }
        if (typeof window !== 'undefined') window.applyDomainVersions = applyDomainVersions;
        return { domainVersions, applyDomainVersions, broadcastChannel: bc };
    };

    /** Initialize instant floating tooltips for collapsed sidebars (`[data-tooltip]` / `[title]`). */
    const initInstantTooltips = (options = {}) => {
        if (typeof document === 'undefined' || !document.body) return;
        const sidebarSel = options.sidebarSelector || '.sidebar, .asst-chat-sidebar';
        const sidebar = document.querySelector(sidebarSel);
        if (!sidebar) return;
        let tip = document.getElementById('sidebar-floating-tooltip');
        if (!tip) {
            tip = Object.assign(document.createElement('div'), { id: 'sidebar-floating-tooltip', className: 'sidebar-tooltip' });
            document.body.appendChild(tip);
        }
        const hide = () => tip.classList.remove('visible');
        if (typeof window !== 'undefined') window.hideInstantTooltip = hide;
        sidebar.querySelectorAll('[title]').forEach((el) => {
            if (!el.getAttribute('data-tooltip')) el.setAttribute('data-tooltip', el.getAttribute('title') || '');
            el.removeAttribute('title');
        });
        if (document._instantTooltipsBound) return;
        document._instantTooltipsBound = true;
        document.addEventListener('mouseover', (e) => {
            const sb = document.querySelector(sidebarSel);
            if (!sb || !e.target || !sb.contains(e.target)) return;
            const titled = e.target.closest ? e.target.closest('[title]') : null;
            if (titled && sb.contains(titled)) {
                titled.setAttribute('data-tooltip', titled.getAttribute('data-tooltip') || titled.getAttribute('title') || '');
                titled.removeAttribute('title');
            }
            const wrapper = document.querySelector(options.wrapperSelector || '.app-wrapper, .asst-viewport');
            const isCollapsed = Boolean((wrapper && wrapper.classList.contains('sidebar-collapsed')) || sb.classList.contains('collapsed') || (sb.offsetWidth > 0 && sb.offsetWidth <= 100));
            const item = isCollapsed && e.target.closest ? e.target.closest('[data-tooltip]') : null;
            const text = item && sb.contains(item) ? (item.getAttribute('data-tooltip') || '').trim() : '';
            if (!text || isTouchDevice()) return hide();
            tip.textContent = text;
            tip.classList.add('visible');
            const r = item.getBoundingClientRect();
            const tr = tip.getBoundingClientRect();
            tip.style.left = `${Math.round(r.right + 10)}px`;
            tip.style.top = `${Math.round(r.top + (r.height - tr.height) / 2)}px`;
        });
        document.addEventListener('mouseout', (e) => {
            const cur = e.target && e.target.closest ? e.target.closest('[data-tooltip]') : null;
            if (cur && (!e.relatedTarget || !cur.contains(e.relatedTarget))) hide();
        });
        document.addEventListener('click', hide);
    };

    /** Initialize collapsible sidebar shell (`#btn-toggle-sidebar`, `.sidebar-collapsed`, `.wide-mode`). */
    const initSidebar = (options = {}) => {
        if (typeof document === 'undefined') return null;
        const wrapperSel = options.wrapperSelector || '.app-wrapper, .asst-viewport';
        const toggleBtnId = options.toggleBtnId || 'btn-toggle-sidebar';
        const storageKey = options.storageKey || 'sidebar_collapsed';
        const sync = (collapsed) => {
            const wrapper = document.querySelector(wrapperSel);
            if (!wrapper) return;
            wrapper.classList.toggle('sidebar-collapsed', collapsed);
            wrapper.classList.toggle('wide-mode', collapsed);
            const btn = document.getElementById(toggleBtnId);
            if (btn) btn.setAttribute('data-tooltip', collapsed ? 'Expand Sidebar (Standard View)' : 'Collapse Sidebar (Wide Screen Canvas)');
        };
        try { if (typeof localStorage !== 'undefined' && localStorage.getItem(storageKey) === 'true') sync(true); } catch (_) {}
        const toggleSidebar = (ev) => {
            const wrapper = document.querySelector(wrapperSel);
            if (!wrapper) return false;
            if (ev && ev._hvlSidebarHandled) return wrapper.classList.contains('sidebar-collapsed');
            if (ev && typeof ev === 'object') ev._hvlSidebarHandled = true;
            const next = !wrapper.classList.contains('sidebar-collapsed');
            sync(next);
            try { if (typeof localStorage !== 'undefined') localStorage.setItem(storageKey, String(next)); } catch (_) {}
            if (typeof window !== 'undefined' && window.hideInstantTooltip) window.hideInstantTooltip();
            return next;
        };
        if (typeof document.addEventListener === 'function' && !document._hvlSidebarDelegated) {
            document._hvlSidebarDelegated = true;
            document.addEventListener('click', (e) => {
                const t = e && e.target && e.target.closest ? e.target.closest(`#${toggleBtnId}, [data-action="toggle-sidebar"]`) : null;
                if (t && typeof window !== 'undefined' && typeof window.toggleSidebar === 'function') window.toggleSidebar(e);
            });
            document.addEventListener('htmx:afterSettle', () => {
                const wrapper = document.querySelector(wrapperSel);
                if (wrapper) sync(wrapper.classList.contains('sidebar-collapsed'));
                initInstantTooltips(options);
            });
        }
        initInstantTooltips(options);
        if (typeof window !== 'undefined') window.toggleSidebar = toggleSidebar;
        return { toggleSidebar };
    };

    /** Purge Service Worker CacheStorage, unregister service workers, and hard-reload. */
    const forceCacheReset = async (options = {}) => {
        if (typeof window === 'undefined') return;
        if (options.statusElement) {
            const el = typeof options.statusElement === 'string' ? document.querySelector(options.statusElement) : options.statusElement;
            if (el) el.textContent = options.statusMessage || 'Purging offline caches...';
        }
        if ('caches' in window) {
            try {
                const keys = await caches.keys();
                await Promise.all(keys.map((k) => caches.delete(k)));
            } catch (_) {}
        }
        if ('serviceWorker' in navigator) {
            try {
                const regs = await navigator.serviceWorker.getRegistrations();
                for (const reg of regs) await reg.unregister().catch(() => {});
            } catch (_) {}
        }
        if (options.clearStorage === true) { try { sessionStorage.clear(); } catch (_) {} }
        window.location.reload();
    };

    if (typeof window !== 'undefined') window.hvlForceCacheReset = forceCacheReset;
    if (typeof document !== 'undefined') {
        if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => initScrollableRibbon());
        else setTimeout(() => initScrollableRibbon(), 30);
        document.addEventListener('click', (e) => {
            const btn = e.target && e.target.closest ? e.target.closest('[data-action="hvl-cache-reset"]') : null;
            if (btn) {
                e.preventDefault();
                btn.textContent = btn.getAttribute('data-loading-text') || 'Reloading...';
                forceCacheReset({ statusElement: btn.getAttribute('data-status-target'), statusMessage: btn.getAttribute('data-status-message') });
            }
        });
    }

    return {
        escapeHtml, fmtCurrency, fmtShortCurrency, fmtPct, isTouchDevice, morphFragment,
        getThemePreference, getResolvedTheme, applyTheme, setThemePreference, toggleTheme,
        initTheme, initScrollableRibbon, initSubnav, initDomainSync, initInstantTooltips, initSidebar,
        forceCacheReset, hvlForceCacheReset: forceCacheReset
    };
}));
