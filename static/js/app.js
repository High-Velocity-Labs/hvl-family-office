/**
 * HVL Family Office Client Application - Main Controller
 * Modular architecture orchestrating navigation, hydration, and account sync.
 */

// Global state accessible across modules
var globalSnapshot = null;
var globalProjections = null;
var globalDashboardData = null;
var currentViewMode = 'focused'; // 'focused' or 'all'
var currentSectionId = (typeof window !== 'undefined' && window.INITIAL_ACTIVE_SECTION) ? window.INITIAL_ACTIVE_SECTION : 'section-overview';
if (typeof window !== 'undefined') {
    window.currentSectionId = currentSectionId;
}

// Formatting Utilities (provided by /common/utils.js)
var fmtCurrency = window.fmtCurrency;
var fmtShortCurrency = window.fmtShortCurrency;
var fmtPct = window.fmtPct;
var escapeHtml = window.escapeHtml;
window.formatCurrency = fmtCurrency;
window.formatShortCurrency = fmtShortCurrency;

const EDIT_SVG = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 4px; vertical-align: -1px;"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>`;
window.EDIT_SVG = EDIT_SVG;

document.addEventListener('DOMContentLoaded', () => {
    if (typeof initNavigation === 'function') initNavigation();
    initGlobalControls();
    if (typeof initScrollSpy === 'function') initScrollSpy();
    initInstantTooltips();
    initTouchTooltipGuard();
    if (typeof fetchDashboardData === 'function') fetchDashboardData();
    if (window.SandboxManager && typeof window.SandboxManager.initCountdown === 'function') {
        window.SandboxManager.initCountdown();
    }
});

function initGlobalControls() {
    const btnToggleSidebar = document.getElementById('btn-toggle-sidebar');
    const appWrapper = document.querySelector('.app-wrapper');

    const updateSidebarTooltips = (isCollapsed) => {
        const tooltipText = isCollapsed ? 'Expand Sidebar (Standard View)' : 'Collapse Sidebar (Wide Screen Canvas)';
        if (btnToggleSidebar) {
            btnToggleSidebar.removeAttribute('title');
            btnToggleSidebar.setAttribute('data-tooltip', tooltipText);
        }
    };

    if (localStorage.getItem('sidebar_collapsed') === 'true' && appWrapper) {
        appWrapper.classList.add('sidebar-collapsed');
        appWrapper.classList.add('wide-mode');
        updateSidebarTooltips(true);
    }

    const toggleSidebar = () => {
        if (!appWrapper) return;
        const willBeCollapsed = !appWrapper.classList.contains('sidebar-collapsed');
        appWrapper.classList.toggle('sidebar-collapsed', willBeCollapsed);
        appWrapper.classList.toggle('wide-mode', willBeCollapsed);
        localStorage.setItem('sidebar_collapsed', willBeCollapsed);
        updateSidebarTooltips(willBeCollapsed);
        if (window.hideInstantTooltip) window.hideInstantTooltip();

        setTimeout(() => {
            window.dispatchEvent(new Event('resize'));
        }, 220);
    };

    if (btnToggleSidebar) btnToggleSidebar.addEventListener('click', toggleSidebar);
    window.toggleSidebar = toggleSidebar;

    const btnLogout = document.getElementById('btn-logout');
    const btnMobileLogout = document.getElementById('btn-mobile-logout');
    if (btnLogout && typeof doLogout === 'function') btnLogout.addEventListener('click', doLogout);
    if (btnMobileLogout && typeof doLogout === 'function') btnMobileLogout.addEventListener('click', doLogout);

    const btnSync = document.getElementById('btn-sync');
    const btnMobileSync = document.getElementById('btn-mobile-sync');
    if (btnSync && typeof triggerMonarchSync === 'function') btnSync.addEventListener('click', triggerMonarchSync);
    if (btnMobileSync && typeof triggerMonarchSync === 'function') btnMobileSync.addEventListener('click', triggerMonarchSync);
}

function initInstantTooltips() {
    let tooltipEl = document.getElementById('sidebar-floating-tooltip');
    if (!tooltipEl) {
        tooltipEl = document.createElement('div');
        tooltipEl.id = 'sidebar-floating-tooltip';
        tooltipEl.className = 'sidebar-tooltip';
        document.body.appendChild(tooltipEl);
    }

    const appWrapper = document.querySelector('.app-wrapper');
    const sidebar = document.querySelector('.sidebar');

    const hideTooltip = () => {
        if (tooltipEl) tooltipEl.classList.remove('visible');
    };
    window.hideInstantTooltip = hideTooltip;

    if (!sidebar) return;

    sidebar.querySelectorAll('[data-tooltip], [title]').forEach(el => {
        const rawTitle = el.getAttribute('title');
        if (rawTitle && !el.getAttribute('data-tooltip')) {
            el.setAttribute('data-tooltip', rawTitle);
        }
        el.removeAttribute('title');
    });

    if (sidebar._instantTooltipsBound) return;
    sidebar._instantTooltipsBound = true;

    sidebar.addEventListener('mouseover', (e) => {
        const titled = e.target && typeof e.target.closest === 'function' ? e.target.closest('[title]') : null;
        if (titled && sidebar.contains(titled)) {
            const rawTitle = titled.getAttribute('title');
            if (rawTitle && !titled.getAttribute('data-tooltip')) {
                titled.setAttribute('data-tooltip', rawTitle);
            }
            titled.removeAttribute('title');
        }

        const isCollapsed = Boolean(
            (appWrapper && appWrapper.classList.contains('sidebar-collapsed')) ||
            document.body.classList.contains('sidebar-collapsed') ||
            sidebar.classList.contains('collapsed') ||
            (sidebar.offsetWidth > 0 && sidebar.offsetWidth <= 100)
        );

        if (!isCollapsed) {
            hideTooltip();
            return;
        }

        const target = e.target.closest('[data-tooltip]');
        if (!target || !sidebar.contains(target)) {
            hideTooltip();
            return;
        }

        const text = target.getAttribute('data-tooltip');
        if (!text || !text.trim()) {
            hideTooltip();
            return;
        }

        target.removeAttribute('title');
        tooltipEl.textContent = text;
        tooltipEl.classList.add('visible');

        const rect = target.getBoundingClientRect();
        const tipRect = tooltipEl.getBoundingClientRect();
        const left = rect.right + 10;
        const top = rect.top + (rect.height - tipRect.height) / 2;

        tooltipEl.style.left = `${Math.round(left)}px`;
        tooltipEl.style.top = `${Math.round(top)}px`;
    });

    sidebar.addEventListener('mouseout', (e) => {
        const related = e.relatedTarget;
        const currentTarget = e.target.closest('[data-tooltip]');
        if (currentTarget && (!related || !currentTarget.contains(related))) {
            hideTooltip();
        }
    });

    sidebar.addEventListener('click', hideTooltip);
    window.addEventListener('scroll', hideTooltip, { passive: true });
}

function initTouchTooltipGuard() {
    const isTouch = () => (window.isTouchDevice ? window.isTouchDevice() : (Boolean(window.ontouchstart !== undefined && window.ontouchstart !== null) || (navigator.maxTouchPoints > 0))) ||
        Boolean(window.matchMedia && window.matchMedia('(hover: none), (pointer: coarse), (max-width: 768px)').matches);

    const stripTooltips = (root = document) => {
        if (!isTouch()) return;
        root.querySelectorAll('[title], [data-tooltip]').forEach(el => {
            const titleText = el.getAttribute('title') || el.getAttribute('data-tooltip');
            if (titleText) {
                if (!el.getAttribute('aria-label')) el.setAttribute('aria-label', titleText);
                el.setAttribute('data-title', titleText);
                el.removeAttribute('title');
                el.removeAttribute('data-tooltip');
            }
        });
    };

    stripTooltips();

    if (typeof MutationObserver !== 'undefined') {
        const observer = new MutationObserver((mutations) => {
            if (!isTouch()) return;
            mutations.forEach(m => {
                m.addedNodes.forEach(node => {
                    if (node.nodeType === 1) {
                        if (node.hasAttribute('title')) {
                            const t = node.getAttribute('title');
                            if (!node.getAttribute('aria-label')) node.setAttribute('aria-label', t);
                            node.setAttribute('data-title', t);
                            node.removeAttribute('title');
                        }
                        stripTooltips(node);
                    }
                });
            });
        });
        if (document.body) {
            observer.observe(document.body, { childList: true, subtree: true });
        }
    }

    document.addEventListener('touchstart', (e) => {
        const target = e.target.closest('[title]');
        if (target) {
            const t = target.getAttribute('title');
            if (t) {
                if (!target.getAttribute('aria-label')) target.setAttribute('aria-label', t);
                target.setAttribute('data-title', t);
                target.removeAttribute('title');
            }
        }
    }, { passive: true });

    document.addEventListener('touchend', (e) => {
        const btn = e.target.closest('button, [role="button"], .pill-btn, .modal-close-btn');
        if (btn) {
            setTimeout(() => {
                if (document.activeElement === btn) btn.blur();
            }, 80);
        }
    }, { passive: true });
}

// Global declarative click delegation
document.addEventListener('click', (e) => {
    const actionEl = e.target.closest('[data-action]');
    if (actionEl) {
        const action = actionEl.getAttribute('data-action');
        if (action === 'open-advisor') {
            e.preventDefault();
            if (typeof window.toggleAiAdvisorDrawer === 'function') window.toggleAiAdvisorDrawer(true);
            return;
        }
        if (action === 'close-advisor') {
            e.preventDefault();
            if (typeof window.toggleAiAdvisorDrawer === 'function') window.toggleAiAdvisorDrawer(false);
            return;
        }
        if (action === 'open-settings') {
            e.preventDefault();
            if (typeof window.openSettingsModal === 'function') window.openSettingsModal();
            return;
        }
        if (action === 'close-settings') {
            e.preventDefault();
            if (typeof window.closeSettingsModal === 'function') {
                window.closeSettingsModal();
            } else {
                const modal = document.getElementById('settings-modal');
                if (modal) modal.style.display = 'none';
            }
            return;
        }
    }

    const btnAdvisor = e.target.closest('#btn-open-ai-advisor, #btn-sidebar-advisor');
    if (btnAdvisor) {
        e.preventDefault();
        if (typeof window.toggleAiAdvisorDrawer === 'function') window.toggleAiAdvisorDrawer(true);
        return;
    }

    const btnSettings = e.target.closest('#btn-open-settings, #btn-sidebar-settings');
    if (btnSettings) {
        e.preventDefault();
        if (typeof window.openSettingsModal === 'function') window.openSettingsModal();
    }
});

initTouchTooltipGuard();
if (typeof window !== 'undefined' && typeof window.initTheme === 'function') {
    window.initTheme({ storageKey: 'fo_theme' });
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        globalSnapshot,
        globalProjections,
        globalDashboardData,
        currentViewMode,
        initGlobalControls,
        initInstantTooltips,
        initTouchTooltipGuard
    });
}
