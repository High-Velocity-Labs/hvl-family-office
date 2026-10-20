/**
 * HVL Common UI - Shared Utility Functions (hvl_common)
 * Lightweight, pure, dependency-free helpers for formatting, escaping, and device detection.
 * Universal Module Definition (UMD): works as standard script, CommonJS, and ES environments.
 */
(function (root, factory) {
    const u = factory();
    if (typeof exports === 'object' && typeof module !== 'undefined') {
        module.exports = u;
    }
    const target = (typeof window !== 'undefined') ? window : root;
    if (target) {
        target.utils = u;
        target.escapeHtml = u.escapeHtml;
        target.fmtCurrency = u.fmtCurrency;
        target.fmtShortCurrency = u.fmtShortCurrency;
        target.fmtPct = u.fmtPct;
        target.isTouchDevice = u.isTouchDevice;
        target.morphFragment = u.morphFragment;
        target.getThemePreference = u.getThemePreference;
        target.getResolvedTheme = u.getResolvedTheme;
        target.applyTheme = u.applyTheme;
        target.setThemePreference = u.setThemePreference;
        target.toggleTheme = u.toggleTheme;
        target.initTheme = u.initTheme;
        target.initScrollableRibbon = u.initScrollableRibbon;
        target.initSubnav = u.initSubnav;
    }
}(typeof globalThis !== 'undefined' ? globalThis : typeof window !== 'undefined' ? window : this, function () {
    'use strict';

    const THEME_STORAGE_KEYS = ['hvl_theme', 'fo_theme', 'ff_theme'];

    /**
     * Escape special HTML characters to prevent XSS.
     * @param {string} str
     * @returns {string}
     */
    const escapeHtml = (str) => {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    };

    /**
     * Format number as standard US currency.
     * @param {number} val
     * @param {number} [maxFrac=2]
     * @returns {string}
     */
    const fmtCurrency = (val, maxFrac = 2) => {
        if (val === null || val === undefined || isNaN(val)) return '$0.00';
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD',
            minimumFractionDigits: maxFrac,
            maximumFractionDigits: maxFrac
        }).format(val);
    };

    /**
     * Format large numbers into compact human-readable representations ($1.23M, $45.6k).
     * @param {number} val
     * @returns {string}
     */
    const fmtShortCurrency = (val) => {
        if (val === null || val === undefined || isNaN(val)) return '$0';
        if (Math.abs(val) >= 1e6) return `$${(val / 1e6).toFixed(2)}M`;
        if (Math.abs(val) >= 1e3) return `$${(val / 1e3).toFixed(1)}k`;
        return fmtCurrency(val);
    };

    /**
     * Format float into percentage representation (0.125 -> 12.5%).
     * @param {number} val
     * @returns {string}
     */
    const fmtPct = (val) => {
        if (val === null || val === undefined || isNaN(val)) return '0.0%';
        return `${(val * 100).toFixed(1)}%`;
    };

    /**
     * Detect touch-enabled devices for mobile-optimized interactions.
     * @returns {boolean}
     */
    const isTouchDevice = () => {
        if (typeof window === 'undefined') return false;
        return ('ontouchstart' in window) || (navigator.maxTouchPoints > 0) || (window.matchMedia && window.matchMedia('(hover: none)').matches);
    };

    /**
     * Fetch an SSR HTML fragment via HTMX and morph it into the target container via Idiomorph.
     * @param {string|Element} target - CSS selector, element ID, or DOM element
     * @param {string} url - Fragment endpoint URL
     * @param {Object} [options={}] - Optional HTMX ajax context options
     * @returns {Promise<void>}
     */
    const morphFragment = (target, url, options = {}) => {
        if (!target || !url) return Promise.resolve();
        let resolvedTarget = target;
        if (typeof target === 'string' && typeof document !== 'undefined') {
            if (!target.startsWith('#') && !target.startsWith('.') && !target.startsWith('[')) {
                const byId = document.getElementById(target);
                if (byId) resolvedTarget = byId;
            }
        }
        const ctx = Object.assign({}, options || {}, {
            target: resolvedTarget,
            swap: (options && options.swap) || 'morph'
        });
        if (typeof window !== 'undefined' && window.htmx && typeof window.htmx.ajax === 'function') {
            return window.htmx.ajax('GET', url, ctx);
        }
        return Promise.resolve();
    };

    /**
     * Retrieve stored theme preference ('light', 'dark', or 'system').
     * @param {string} [storageKey]
     * @returns {string}
     */
    const getThemePreference = (storageKey) => {
        const keys = storageKey ? [storageKey, ...THEME_STORAGE_KEYS] : THEME_STORAGE_KEYS;
        try {
            if (typeof localStorage !== 'undefined') {
                for (const k of keys) {
                    const val = localStorage.getItem(k);
                    if (val === 'light' || val === 'dark' || val === 'system') {
                        return val;
                    }
                }
            }
        } catch (_) {}
        return 'system';
    };

    /**
     * Resolve effective theme ('light' or 'dark') from user preference or OS color scheme.
     * @param {string} [storageKey]
     * @param {string} [defaultTheme='light']
     * @returns {string}
     */
    const getResolvedTheme = (storageKey, defaultTheme = 'light') => {
        const pref = getThemePreference(storageKey);
        if (pref === 'light' || pref === 'dark') {
            return pref;
        }
        if (typeof window !== 'undefined' && window.matchMedia) {
            try {
                return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
            } catch (_) {}
        }
        return defaultTheme === 'dark' ? 'dark' : 'light';
    };

    /**
     * Apply resolved theme to document root, sync toggle labels/cards, and emit 'themechange'.
     * @param {string} resolvedTheme
     * @param {string} [pref]
     */
    const applyTheme = (resolvedTheme, pref) => {
        const theme = resolvedTheme === 'dark' ? 'dark' : 'light';
        const effectivePref = pref || getThemePreference();
        if (typeof document !== 'undefined' && document.documentElement) {
            document.documentElement.setAttribute('data-theme', theme);
            const lbl = document.getElementById('theme-toggle-label');
            if (lbl) {
                lbl.textContent = theme === 'dark' ? 'Dark' : 'Light';
            }
            const btnLbl = document.getElementById('theme-btn-label');
            if (btnLbl) {
                btnLbl.textContent = theme === 'dark' ? 'Light Mode' : 'Dark Mode';
            }
            if (typeof document.querySelectorAll === 'function') {
                const cards = document.querySelectorAll('.theme-choice-card');
                cards.forEach((card) => {
                    const val = card.getAttribute('data-theme-value');
                    const radio = card.querySelector ? card.querySelector('input[type="radio"]') : null;
                    const isSelected = val === effectivePref;
                    if (radio) radio.checked = isSelected;
                    if (card.style) {
                        if (isSelected) {
                            card.style.borderColor = 'var(--accent-blue)';
                            card.style.boxShadow = '0 0 0 2px var(--accent-blue-border, rgba(59, 130, 246, 0.25))';
                        } else {
                            card.style.borderColor = 'var(--border-subtle)';
                            card.style.boxShadow = 'none';
                        }
                    }
                });
            }
        }
        if (typeof window !== 'undefined' && typeof window.dispatchEvent === 'function' && typeof CustomEvent === 'function') {
            try {
                window.dispatchEvent(new CustomEvent('themechange', {
                    detail: { theme, preference: effectivePref }
                }));
            } catch (_) {}
        }
    };

    /**
     * Persist theme preference ('light', 'dark', or 'system') and apply immediately.
     * @param {string} pref
     * @param {string} [storageKey]
     * @returns {string} Resolved theme ('light' or 'dark')
     */
    const setThemePreference = (pref, storageKey) => {
        try {
            if (typeof localStorage !== 'undefined') {
                localStorage.setItem('hvl_theme', pref);
                if (storageKey && storageKey !== 'hvl_theme') {
                    localStorage.setItem(storageKey, pref);
                }
            }
        } catch (_) {}
        const resolved = (pref === 'light' || pref === 'dark') ? pref : getResolvedTheme(storageKey);
        applyTheme(resolved, pref);
        return resolved;
    };

    /**
     * Toggle active theme between 'dark' and 'light' and persist preference.
     * @param {string} [storageKey]
     * @returns {string} Newly active theme ('light' or 'dark')
     */
    const toggleTheme = (storageKey) => {
        let current = null;
        if (typeof document !== 'undefined' && document.documentElement) {
            current = document.documentElement.getAttribute('data-theme');
        }
        if (current !== 'dark' && current !== 'light') {
            current = getResolvedTheme(storageKey);
        }
        const next = current === 'dark' ? 'light' : 'dark';
        setThemePreference(next, storageKey);
        return next;
    };

    /**
     * Initialize theme on load and bind appearance cards, OS media query, and cross-tab storage sync.
     * @param {Object} [options={}]
     */
    const initTheme = (options = {}) => {
        const storageKey = options.storageKey || 'hvl_theme';
        const defaultTheme = options.defaultTheme || 'light';
        const pref = getThemePreference(storageKey);
        const resolved = (pref === 'light' || pref === 'dark') ? pref : getResolvedTheme(storageKey, defaultTheme);
        applyTheme(resolved, pref);

        if (typeof document !== 'undefined' && typeof document.querySelectorAll === 'function') {
            const themeCards = document.querySelectorAll('.theme-choice-card');
            themeCards.forEach((card) => {
                if (card.dataset && card.dataset.themeBound === '1') return;
                if (card.dataset) card.dataset.themeBound = '1';
                card.addEventListener('click', () => {
                    const val = card.getAttribute('data-theme-value');
                    if (val) setThemePreference(val, storageKey);
                });
            });
        }

        if (typeof window !== 'undefined') {
            if (window.matchMedia && !window._hvlThemeMediaBound) {
                window._hvlThemeMediaBound = true;
                try {
                    const mq = window.matchMedia('(prefers-color-scheme: dark)');
                    if (mq && typeof mq.addEventListener === 'function') {
                        mq.addEventListener('change', (e) => {
                            if (getThemePreference(storageKey) === 'system') {
                                applyTheme(e.matches ? 'dark' : 'light', 'system');
                            }
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
                if (subnavMod && typeof subnavMod.initScrollableRibbon === 'function') {
                    return subnavMod.initScrollableRibbon(container, opts);
                }
            } catch (_) {}
        }
        if (typeof document === 'undefined') return [];
        const hasTargets = container || document.querySelector('.hvl-subnav-container, .features-subnav-container, [data-subnav-container]');
        if (!hasTargets) return [];
        if (typeof navigator !== 'undefined' && /jsdom/i.test(navigator.userAgent || '')) return [];
        _subnavPendingCalls.push([container, opts]);
        if (!_subnavLoading && document.head && typeof document.createElement === 'function') {
            _subnavLoading = true;
            const s = document.createElement('script');
            s.src = (typeof window !== 'undefined' && window.location && window.location.protocol === 'file:')
                ? './common/subnav.js'
                : '/common/subnav.js';
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

    if (typeof document !== 'undefined') {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => initScrollableRibbon());
        } else {
            setTimeout(() => initScrollableRibbon(), 30);
        }
    }

    return {
        escapeHtml,
        fmtCurrency,
        fmtShortCurrency,
        fmtPct,
        isTouchDevice,
        morphFragment,
        getThemePreference,
        getResolvedTheme,
        applyTheme,
        setThemePreference,
        toggleTheme,
        initTheme,
        initScrollableRibbon,
        initSubnav
    };
}));
