/**
 * static/js/scenarios/cards_overlays.js
 * Baseline Overlays Tray, Layer Toggling, and Plan View Filter Dropdown.
 */

import { state } from './state.js';
import { morphScenariosSection } from './main.js';

const showModalAlert = (...args) => (
    typeof window !== 'undefined' && window.showModalAlert
        ? window.showModalAlert(...args)
        : Promise.resolve()
);

/**
 * Reads user filter preferences from localStorage.
 */
export function getFilterSettings() {
    try {
        const strat = localStorage.getItem('scenarios_filter_strategy_plans');
        const layers = localStorage.getItem('scenarios_filter_baseline_overlays');
        const arch = localStorage.getItem('scenarios_filter_archived');
        const legacyArch = localStorage.getItem('scenarios_show_archived');

        return {
            strategyPlans: strat !== 'false',
            baselineOverlays: layers !== 'false',
            archivedPlans: arch === 'true' || legacyArch === 'true'
        };
    } catch {
        return {
            strategyPlans: true,
            baselineOverlays: true,
            archivedPlans: false
        };
    }
}

/**
 * Persists a filter preference key/value to localStorage.
 */
export function setFilterSetting(key, val) {
    try {
        const boolVal = Boolean(val);
        const map = {
            strategyPlans: 'scenarios_filter_strategy_plans',
            baselineOverlays: 'scenarios_filter_baseline_overlays',
            archivedPlans: 'scenarios_filter_archived'
        };
        const storageKey = map[key];
        if (storageKey) {
            localStorage.setItem(storageKey, boolVal ? 'true' : 'false');
        }
        if (key === 'archivedPlans') {
            localStorage.setItem('scenarios_show_archived', boolVal ? 'true' : 'false');
        }
    } catch {
        // Ignore storage errors in restricted iframe/private environments
    }
}

/**
 * Applies active plan visibility filters to the selector pills and comparison table rows.
 */
export function applyPlanFilters(customFilters) {
    const filters = customFilters || getFilterSettings();

    // 1. Sync filter checkboxes in the dropdown menu
    const chkStrat = document.getElementById('chk-filter-strategy-plans');
    const chkOverlays = document.getElementById('chk-filter-baseline-overlays');
    const chkArchived = document.getElementById('chk-filter-archived-plans');

    if (chkStrat && chkStrat.checked !== filters.strategyPlans) chkStrat.checked = filters.strategyPlans;
    if (chkOverlays && chkOverlays.checked !== filters.baselineOverlays) chkOverlays.checked = filters.baselineOverlays;
    if (chkArchived && chkArchived.checked !== filters.archivedPlans) chkArchived.checked = filters.archivedPlans;

    // 2. Filter scenario pills in the selector ribbon
    const pills = document.querySelectorAll('#scenario-selector-pills .pill-btn');
    pills.forEach(pill => {
        const isSelected = pill.classList.contains('active');
        const isArchived = pill.getAttribute('data-is-archived') === 'true' || pill.classList.contains('scen-pill-archived');
        const isLayer = pill.getAttribute('data-is-layer') === 'true' || pill.classList.contains('scen-pill-layer');
        const scenId = pill.getAttribute('data-scen-id') || '';
        const isBaseline = scenId === 'scen_baseline' || pill.getAttribute('data-is-baseline') === 'true';

        let visible = true;
        if (isSelected) {
            visible = true;
        } else if (isArchived) {
            visible = filters.archivedPlans;
        } else if (isLayer) {
            visible = filters.baselineOverlays;
        } else if (isBaseline) {
            visible = true;
        } else {
            visible = filters.strategyPlans;
        }

        pill.style.display = visible ? 'inline-flex' : 'none';
    });

    // 3. Filter comparison matrix table rows
    const rows = document.querySelectorAll('#tbody-scenarios-scorecard .scorecard-row');
    rows.forEach(row => {
        const isCurrent = row.classList.contains('active');
        const isArchived = row.getAttribute('data-is-archived') === 'true' || row.classList.contains('scorecard-row-archived');
        const isLayer = row.getAttribute('data-is-layer') === 'true' || row.classList.contains('scorecard-row-layer');
        const scenId = row.getAttribute('data-scen-id') || row.getAttribute('data-id') || '';
        const isBaseline = scenId === 'scen_baseline' || row.getAttribute('data-is-baseline') === 'true';

        let visible = true;
        if (isCurrent) {
            visible = true;
        } else if (isArchived) {
            visible = filters.archivedPlans;
        } else if (isLayer) {
            visible = filters.baselineOverlays;
        } else if (isBaseline) {
            visible = true;
        } else {
            visible = filters.strategyPlans;
        }

        row.style.display = visible ? '' : 'none';
    });

    // 4. Update legacy toggle button if present for backwards compatibility
    const toggleArchBtn = document.getElementById('btn-toggle-archived-scenarios');
    if (toggleArchBtn) {
        const count = parseInt(toggleArchBtn.getAttribute('data-archived-count') || '0', 10);
        toggleArchBtn.textContent = filters.archivedPlans ? `Hide Archived (${count})` : `Show Archived (${count})`;
        toggleArchBtn.classList.toggle('active', filters.archivedPlans);
    }
}

/**
 * Toggles a scenario's status as a merged Baseline layer via the backend API.
 */
export async function toggleBaselineLayer(scenId) {
    if (!scenId) return;

    try {
        const resp = await fetch(`/api/scenarios/${encodeURIComponent(scenId)}/toggle_baseline_layer`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        const res = await resp.json();

        if (resp.ok && (res.success || res.status === 'ok')) {
            if (state && res.active_baseline_layers) {
                state.activeBaselineLayers = res.active_baseline_layers;
            }
            const targetScenId = (state && state.selectedScenarioId) ? state.selectedScenarioId : scenId;
            await morphScenariosSection({ scenario_id: targetScenId });
        } else {
            await showModalAlert(res.error || 'Failed to toggle baseline overlay', { title: 'Overlay Error', type: 'error' });
        }
    } catch (err) {
        console.error('Failed to toggle baseline overlay:', err);
        await showModalAlert('Failed to toggle baseline overlay: ' + err.message, { title: 'Overlay Error', type: 'error' });
    }
}

/**
 * Dynamically clamps the View Plans menu within viewport bounds.
 */
export function positionViewPlansMenu(btn, menu) {
    if (!btn || !menu) return;
    menu.style.left = '0px';
    menu.style.right = 'auto';
    if (typeof window !== 'undefined' && typeof window.positionDropdownMenu === 'function') {
        window.positionDropdownMenu(menu);
    }
    const vw = window.innerWidth || document.documentElement.clientWidth || 0;
    const rect = menu.getBoundingClientRect();
    if (vw > 0 && rect.width > 0) {
        if (rect.right > vw - 12) {
            const btnRect = btn.getBoundingClientRect();
            if (btnRect.right - rect.width >= 12) {
                menu.style.left = 'auto';
                menu.style.right = '0px';
            } else {
                menu.style.left = Math.max(12 - btnRect.left, vw - 12 - rect.width - btnRect.left) + 'px';
                menu.style.right = 'auto';
            }
        } else if (rect.left < 12) {
            const btnRect = btn.getBoundingClientRect();
            menu.style.left = (12 - btnRect.left) + 'px';
            menu.style.right = 'auto';
        }
    }
}

/**
 * Binds click outside and checkbox handlers for the View Plans filter menu.
 */
export function bindViewPlansDropdown() {
    const btn = document.getElementById('btn-view-plans-dropdown');
    const menu = document.getElementById('menu-view-plans');
    if (!btn || !menu || btn.dataset.overlaysWired) return;
    btn.dataset.overlaysWired = 'true';

    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = menu.style.display !== 'none';
        menu.style.display = isOpen ? 'none' : 'block';
        btn.setAttribute('aria-expanded', isOpen ? 'false' : 'true');
        if (!isOpen) positionViewPlansMenu(btn, menu);
    });

    document.addEventListener('click', (e) => {
        if (!menu.contains(e.target) && e.target !== btn) {
            menu.style.display = 'none';
            btn.setAttribute('aria-expanded', 'false');
        }
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && menu.style.display !== 'none') {
            menu.style.display = 'none';
            btn.setAttribute('aria-expanded', 'false');
        }
    });

    const chkMap = [
        { id: 'chk-filter-strategy-plans', key: 'strategyPlans' },
        { id: 'chk-filter-baseline-overlays', key: 'baselineOverlays' },
        { id: 'chk-filter-archived-plans', key: 'archivedPlans' }
    ];

    chkMap.forEach(({ id, key }) => {
        const chk = document.getElementById(id);
        if (chk && !chk.dataset.overlaysWired) {
            chk.dataset.overlaysWired = 'true';
            chk.addEventListener('change', () => {
                setFilterSetting(key, chk.checked);
                applyPlanFilters();
            });
        }
    });
}

/**
 * Binds click events on child plan card layer toggle, scorecard table layer toggles, and Baseline tray unmerge buttons.
 */
export function bindBaselineLayerToggles() {
    const cardToggle = document.getElementById('btn-toggle-baseline-layer');
    if (cardToggle && !cardToggle.dataset.overlaysWired) {
        cardToggle.dataset.overlaysWired = 'true';
        cardToggle.addEventListener('click', () => {
            const scenId = cardToggle.getAttribute('data-scen-id');
            if (scenId) toggleBaselineLayer(scenId);
        });
    }

    document.querySelectorAll('.btn-unmerge-baseline-layer').forEach(btn => {
        if (!btn.dataset.overlaysWired) {
            btn.dataset.overlaysWired = 'true';
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const lyrId = btn.getAttribute('data-layer-id');
                if (lyrId) toggleBaselineLayer(lyrId);
            });
        }
    });

    document.querySelectorAll('.btn-toggle-overlay-scenario').forEach(btn => {
        if (!btn.dataset.overlaysWired) {
            btn.dataset.overlaysWired = 'true';
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const scenId = btn.getAttribute('data-scen-id') || btn.getAttribute('data-id');
                if (scenId) toggleBaselineLayer(scenId);
            });
        }
    });
}

/**
 * Binds click events and open/close state for the Baseline Overlays Tray "+ Add Overlay" dropdown menu.
 */
export function bindAddOverlayDropdown() {
    const btn = document.getElementById('btn-add-overlay-dropdown');
    const menu = document.getElementById('menu-add-overlay');
    if (!btn || !menu || btn.dataset.overlaysWired) return;
    btn.dataset.overlaysWired = 'true';

    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = menu.style.display !== 'none';
        menu.style.display = isOpen ? 'none' : 'block';
        btn.setAttribute('aria-expanded', isOpen ? 'false' : 'true');
    });

    document.addEventListener('click', (e) => {
        if (!menu.contains(e.target) && e.target !== btn) {
            menu.style.display = 'none';
            btn.setAttribute('aria-expanded', 'false');
        }
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && menu.style.display !== 'none') {
            menu.style.display = 'none';
            btn.setAttribute('aria-expanded', 'false');
        }
    });

    menu.querySelectorAll('.btn-add-baseline-overlay-item').forEach(item => {
        if (!item.dataset.overlaysWired) {
            item.dataset.overlaysWired = 'true';
            item.addEventListener('click', async (e) => {
                e.stopPropagation();
                menu.style.display = 'none';
                btn.setAttribute('aria-expanded', 'false');
                const scenId = item.getAttribute('data-scen-id');
                if (scenId) await toggleBaselineLayer(scenId);
            });
        }
    });
}

/**
 * Main initialization entry point for scenario overlay controls and filters.
 */
export function initCardsOverlays() {
    bindViewPlansDropdown();
    bindBaselineLayerToggles();
    bindAddOverlayDropdown();
    applyPlanFilters();
}

// Auto-run on document ready and htmx morph swaps
if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initCardsOverlays);
    } else {
        initCardsOverlays();
    }
    document.addEventListener('htmx:afterSwap', initCardsOverlays);
}

// Expose runtime helpers on window for external callers and tests
if (typeof window !== 'undefined') {
    window.initCardsOverlays = initCardsOverlays;
    window.toggleBaselineLayer = toggleBaselineLayer;
    window.applyPlanFilters = applyPlanFilters;
    window.getFilterSettings = getFilterSettings;
    window.setFilterSetting = setFilterSetting;
    window.bindBaselineLayerToggles = bindBaselineLayerToggles;
    window.bindAddOverlayDropdown = bindAddOverlayDropdown;
    window.bindViewPlansDropdown = bindViewPlansDropdown;
    window.positionViewPlansMenu = positionViewPlansMenu;
}
