/**
 * HVL Common UI - Scrollable Subnav Ribbon Widget (hvl_common)
 * Stateful horizontal scrollable navigation ribbon with arrow buttons, wheel forwarding,
 * click-to-center, ResizeObserver, and optional IntersectionObserver scroll-spy.
 */
(function (root, factory) {
    const mod = factory();
    if (typeof exports === 'object' && typeof module !== 'undefined') {
        module.exports = mod;
    }
    const target = (typeof window !== 'undefined') ? window : root;
    if (target) {
        target.HVLSubnav = mod;
        target.initScrollableRibbon = mod.initScrollableRibbon;
        target.initSubnav = mod.initSubnav;
        target.switchSettingsTab = mod.switchSettingsTab;
        target.initSettingsTabs = mod.initSettingsTabs;
        target.positionDropdownMenu = mod.positionDropdownMenu;
        target.initDropdowns = mod.initDropdowns;
    }
}(typeof globalThis !== 'undefined' ? globalThis : typeof window !== 'undefined' ? window : this, function () {
    'use strict';

    /**
     * Initializes scrollable subnav ribbons with left/right scroll buttons and wheel forwarding.
     * @param {HTMLElement|string} [container] - Container element or selector
     * @param {Object} [opts]
     * @param {number} [opts.scrollStep=260] - Pixels to scroll on button click
     * @returns {Array<{container: HTMLElement, inner: HTMLElement, updateArrows: Function, destroy: Function}>}
     */
    const initScrollableRibbon = (container, opts = {}) => {
        if (typeof document === 'undefined') return [];
        const step = opts.scrollStep || 260;
        let containers = [];
        if (!container) {
            containers = Array.from(document.querySelectorAll('.hvl-subnav-container, .features-subnav-container, [data-subnav-container]'));
        } else if (typeof container === 'string') {
            containers = Array.from(document.querySelectorAll(container));
        } else if (container instanceof Element) {
            containers = [container];
        }

        return containers.map((el) => {
            if (el._hvlSubnavInitialized && el._hvlSubnavInstance) {
                el._hvlSubnavInstance.updateArrows();
                setTimeout(el._hvlSubnavInstance.updateArrows, 60);
                return el._hvlSubnavInstance;
            }
            const inner = el.querySelector('.hvl-subnav-inner, .features-subnav-inner, [data-subnav-inner]');
            if (!inner) return null;
            let prevBtn = el.querySelector('.subnav-arrow-btn.prev, [data-subnav-prev]');
            let nextBtn = el.querySelector('.subnav-arrow-btn.next, [data-subnav-next]');
            if (!prevBtn && typeof document.createElement === 'function' && inner.parentNode === el) {
                prevBtn = document.createElement('button');
                prevBtn.type = 'button';
                prevBtn.className = 'subnav-arrow-btn prev';
                prevBtn.setAttribute('aria-label', 'Scroll navigation left');
                prevBtn.setAttribute('title', 'Scroll Left');
                prevBtn.style.display = 'none';
                prevBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="15 18 9 12 15 6"></polyline></svg>';
                el.insertBefore(prevBtn, inner);
            }
            if (!nextBtn && typeof document.createElement === 'function' && inner.parentNode === el) {
                nextBtn = document.createElement('button');
                nextBtn.type = 'button';
                nextBtn.className = 'subnav-arrow-btn next';
                nextBtn.setAttribute('aria-label', 'Scroll navigation right');
                nextBtn.setAttribute('title', 'Scroll Right');
                nextBtn.style.display = 'none';
                nextBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"></polyline></svg>';
                el.appendChild(nextBtn);
            }

            el._hvlSubnavInitialized = true;

            const updateArrows = () => {
                const maxScroll = inner.scrollWidth - inner.clientWidth;
                if (maxScroll <= 6) {
                    if (prevBtn) prevBtn.style.display = 'none';
                    if (nextBtn) nextBtn.style.display = 'none';
                    return;
                }
                if (prevBtn) prevBtn.style.display = inner.scrollLeft > 6 ? 'inline-flex' : 'none';
                if (nextBtn) nextBtn.style.display = inner.scrollLeft < maxScroll - 6 ? 'inline-flex' : 'none';
            };

            const onPrev = () => {
                if (inner.scrollLeft <= 0) {
                    inner.scrollBy({ left: -step, behavior: 'smooth' });
                    return;
                }
                let target = Math.max(0, inner.scrollLeft - step);
                if (target < 64) target = 0;
                inner.scrollBy({ left: target - inner.scrollLeft, behavior: 'smooth' });
            };
            const onNext = () => {
                if (prevBtn && prevBtn.style.display === 'none') {
                    prevBtn.style.display = 'inline-flex';
                }
                const maxScroll = inner.scrollWidth - inner.clientWidth;
                if (maxScroll <= 0) {
                    inner.scrollBy({ left: step, behavior: 'smooth' });
                    return;
                }
                let target = Math.min(maxScroll, inner.scrollLeft + step);
                if (maxScroll - target < 64) target = maxScroll;
                inner.scrollBy({ left: target - inner.scrollLeft, behavior: 'smooth' });
            };
            const onWheel = (e) => {
                if (Math.abs(e.deltaY) > Math.abs(e.deltaX) && inner.scrollWidth > inner.clientWidth) {
                    inner.scrollLeft += e.deltaY;
                    e.preventDefault();
                }
            };
            let clickScrollLockUntil = 0;

            const centerItemInRibbon = (item) => {
                if (!item || !inner.contains(item) || inner.scrollWidth <= inner.clientWidth) return;
                let itemRect = item.getBoundingClientRect();
                let cRect = inner.getBoundingClientRect();
                let offset = (itemRect.left - cRect.left) - (cRect.width / 2) + (itemRect.width / 2);
                if (inner.scrollLeft + offset > 6 && prevBtn && prevBtn.style.display === 'none') {
                    prevBtn.style.display = 'inline-flex';
                    itemRect = item.getBoundingClientRect();
                    cRect = inner.getBoundingClientRect();
                    offset = (itemRect.left - cRect.left) - (cRect.width / 2) + (itemRect.width / 2);
                }
                const maxScroll = Math.max(0, inner.scrollWidth - inner.clientWidth);
                let target = Math.max(0, Math.min(maxScroll, inner.scrollLeft + offset));
                if (target < 48) target = 0;
                else if (maxScroll - target < 48) target = maxScroll;
                inner.scrollBy({ left: target - inner.scrollLeft, behavior: 'smooth' });
                setTimeout(updateArrows, 180);
            };

            const onWindowScroll = () => {
                if (clickScrollLockUntil > Date.now()) {
                    clickScrollLockUntil = Date.now() + 180;
                }
            };

            const onItemClick = (e) => {
                const item = e.target && typeof e.target.closest === 'function'
                    ? e.target.closest('.hvl-subnav-link, .features-nav-link, .pill-btn, .advisor-chip')
                    : null;
                if (!item || !inner.contains(item)) return;
                const href = item.getAttribute && item.getAttribute('href');
                if (href && href.startsWith('#')) {
                    clickScrollLockUntil = Date.now() + 900;
                    Array.from(inner.querySelectorAll('a[href^="#"]')).forEach((l) => {
                        l.classList.toggle('active', l === item);
                    });
                }
                centerItemInRibbon(item);
            };

            if (prevBtn) prevBtn.addEventListener('click', onPrev);
            if (nextBtn) nextBtn.addEventListener('click', onNext);
            inner.addEventListener('scroll', updateArrows, { passive: true });
            inner.addEventListener('wheel', onWheel, { passive: false });
            inner.addEventListener('click', onItemClick, { passive: true });
            if (typeof window !== 'undefined') {
                window.addEventListener('resize', updateArrows, { passive: true });
                window.addEventListener('scroll', onWindowScroll, { passive: true });
            }

            let resizeObserver = null;
            if (typeof ResizeObserver !== 'undefined') {
                try {
                    resizeObserver = new ResizeObserver(() => updateArrows());
                    resizeObserver.observe(inner);
                } catch (_) {}
            }

            let observer = null;
            if (opts.scrollSpy !== false && typeof window !== 'undefined' && 'IntersectionObserver' in window) {
                const links = Array.from(inner.querySelectorAll('a[href^="#"]'));
                const sections = links.map((l) => {
                    const id = (l.getAttribute('href') || '').slice(1);
                    return id ? document.getElementById(id) : null;
                }).filter(Boolean);

                if (sections.length > 0 && (opts.scrollSpy || el.hasAttribute('data-scrollspy') || sections.length >= 3)) {
                    observer = new IntersectionObserver((entries) => {
                        if (Date.now() < clickScrollLockUntil) return;
                        entries.forEach((entry) => {
                            if (entry.isIntersecting) {
                                const id = entry.target.getAttribute('id');
                                links.forEach((l) => {
                                    if (l.getAttribute('href') === '#' + id) {
                                        l.classList.add('active');
                                        centerItemInRibbon(l);
                                    } else {
                                        l.classList.remove('active');
                                    }
                                });
                            }
                        });
                    }, { rootMargin: '-100px 0px -60% 0px', threshold: 0 });
                    sections.forEach((s) => observer.observe(s));
                }
            }

            setTimeout(updateArrows, 60);

            const instance = {
                container: el,
                inner,
                updateArrows,
                destroy: () => {
                    el._hvlSubnavInitialized = false;
                    el._hvlSubnavInstance = null;
                    if (observer) observer.disconnect();
                    if (resizeObserver) resizeObserver.disconnect();
                    if (prevBtn) prevBtn.removeEventListener('click', onPrev);
                    if (nextBtn) nextBtn.removeEventListener('click', onNext);
                    inner.removeEventListener('scroll', updateArrows);
                    inner.removeEventListener('wheel', onWheel);
                    inner.removeEventListener('click', onItemClick);
                    if (typeof window !== 'undefined') {
                        window.removeEventListener('resize', updateArrows);
                        window.removeEventListener('scroll', onWindowScroll);
                    }
                }
            };
            el._hvlSubnavInstance = instance;
            return instance;
        }).filter(Boolean);
    };

    const initSubnav = initScrollableRibbon;

    const switchSettingsTab = (tabId, rootEl) => {
        if (typeof document === 'undefined' || !tabId) return false;
        const scope = (rootEl && typeof rootEl.querySelectorAll === 'function')
            ? rootEl
            : (document.querySelector('#tab-settings, .settings-modal-dialog') || document);
        const targetPane = scope.querySelector(`#settings-tab-${tabId}`) || document.getElementById(`settings-tab-${tabId}`);
        if (!targetPane) return false;
        scope.querySelectorAll('.settings-tab-btn[data-tab]').forEach((btn) => {
            const isMatch = btn.getAttribute('data-tab') === tabId;
            btn.classList.toggle('active', isMatch);
            btn.setAttribute('aria-pressed', isMatch ? 'true' : 'false');
        });
        scope.querySelectorAll('.settings-tab-content').forEach((pane) => {
            pane.style.display = (pane === targetPane) ? 'block' : 'none';
        });
        try {
            if (typeof sessionStorage !== 'undefined') sessionStorage.setItem('hvl_active_settings_tab', tabId);
        } catch (_) {}
        initScrollableRibbon();
        return true;
    };

    const initSettingsTabs = (rootEl) => {
        if (typeof document === 'undefined') return;
        if (typeof document.addEventListener === 'function' && !document._hvlSettingsTabsBound) {
            document._hvlSettingsTabsBound = true;
            document.addEventListener('click', (e) => {
                const btn = e.target && e.target.closest ? e.target.closest('.settings-tab-btn[data-tab]') : null;
                if (!btn) return;
                const tabId = btn.getAttribute('data-tab');
                const scope = btn.closest('#tab-settings, .settings-modal-dialog') || document;
                switchSettingsTab(tabId, scope);
            });
            document.addEventListener('htmx:afterSettle', (e) => {
                const target = (e && e.detail && e.detail.elt) || (e && e.target) || null;
                if (target && (target.id === 'tab-settings' || (target.querySelector && target.querySelector('#settings-subnav-container')))) {
                    try {
                        const saved = typeof sessionStorage !== 'undefined' && sessionStorage.getItem('hvl_active_settings_tab');
                        if (saved) switchSettingsTab(saved, target);
                    } catch (_) {}
                    initScrollableRibbon(target);
                }
            });
        }
        try {
            const scope = rootEl || document.querySelector('#tab-settings');
            const saved = typeof sessionStorage !== 'undefined' && sessionStorage.getItem('hvl_active_settings_tab');
            if (scope && saved && scope.id === 'tab-settings') {
                switchSettingsTab(saved, scope);
            }
        } catch (_) {}
    };

    const positionDropdownMenu = (menuEl, opts = {}) => {
        if (!menuEl || !menuEl.style) return;
        const wrap = (menuEl.closest && menuEl.closest('.hvl-dropdown-wrap, .resources-dropdown-wrap, .view-plans-dropdown-container')) || menuEl.offsetParent || menuEl.parentElement;
        const vw = (typeof window !== 'undefined' && (window.innerWidth || (document.documentElement && document.documentElement.clientWidth))) || 0;
        if (!vw || !wrap || typeof wrap.getBoundingClientRect !== 'function' || typeof menuEl.getBoundingClientRect !== 'function') return;
        const wrapRect = wrap.getBoundingClientRect();
        if (!wrapRect || !wrapRect.width) return;
        menuEl.style.left = '';
        menuEl.style.right = '';
        const menuRect = menuEl.getBoundingClientRect();
        const margin = (opts && typeof opts.margin === 'number') ? opts.margin : 12;
        if (!menuRect || !menuRect.width || (menuRect.left >= margin && menuRect.right <= vw - margin)) return;
        const width = Math.min(menuRect.width, vw - margin * 2);
        let targetViewportLeft;
        if (wrapRect.left >= margin && wrapRect.left + width <= vw - margin) {
            targetViewportLeft = wrapRect.left;
        } else if (wrapRect.right - width >= margin && wrapRect.right <= vw - margin) {
            targetViewportLeft = wrapRect.right - width;
        } else {
            targetViewportLeft = Math.max(margin, Math.min(wrapRect.left, vw - margin - width));
        }
        menuEl.style.left = `${Math.round(targetViewportLeft - wrapRect.left)}px`;
        menuEl.style.right = 'auto';
    };

    const repositionOpenDropdowns = () => {
        if (typeof document === 'undefined' || typeof document.querySelectorAll !== 'function') return;
        const menus = document.querySelectorAll('.hvl-dropdown-menu.open, .hvl-dropdown-menu.active, .view-plans-dropdown-menu, .add-overlay-dropdown-menu');
        menus.forEach((menu) => {
            if (menu.style && menu.style.display === 'none') return;
            positionDropdownMenu(menu);
        });
    };

    const initDropdowns = () => {
        if (typeof document === 'undefined' || typeof document.addEventListener !== 'function' || document._hvlDropdownsBound) return;
        document._hvlDropdownsBound = true;
        document.addEventListener('click', () => {
            repositionOpenDropdowns();
            if (typeof requestAnimationFrame === 'function') requestAnimationFrame(repositionOpenDropdowns);
        });
        if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
            window.addEventListener('resize', repositionOpenDropdowns, { passive: true });
        }
    };

    if (typeof document !== 'undefined') {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => {
                initScrollableRibbon();
                initSettingsTabs();
                initDropdowns();
            });
        } else {
            setTimeout(() => {
                initScrollableRibbon();
                initSettingsTabs();
                initDropdowns();
            }, 30);
        }
    }

    return {
        initScrollableRibbon,
        initSubnav,
        switchSettingsTab,
        initSettingsTabs,
        positionDropdownMenu,
        initDropdowns
    };
}));
