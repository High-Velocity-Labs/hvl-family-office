/**
 * static/js/scenarios/cards_overlays.js
 * Baseline Overlays Tray, Layer Toggling, and Plan View Filter Dropdown.
 */

import { state } from './state.js';
import { morphScenariosSection, setScenarioLoadingState } from './main.js';
import { delegate, listenOnce } from './event_delegation.js';

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
 * POSTs one overlay change to `url`, then re-morphs the section (keeping the selected plan, else `scenId`).
 */
async function postOverlayChange(url, body, failure, scenId = null) {
    // The forecast reruns after every overlay change; show it from the click, not only once the save returns.
    setScenarioLoadingState(true);
    try {
        const resp = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const res = await resp.json();

        if (resp.ok && (res.success || res.status === 'ok')) {
            if (state && res.active_baseline_layers) {
                state.activeBaselineLayers = res.active_baseline_layers;
            }
            const targetScenId = (state && state.selectedScenarioId) ? state.selectedScenarioId : scenId;
            await morphScenariosSection({ scenario_id: targetScenId });
        } else {
            setScenarioLoadingState(false);
            await showModalAlert(res.error || failure, { title: 'Overlay Error', type: 'error' });
        }
    } catch (err) {
        setScenarioLoadingState(false);
        console.error(`${failure}:`, err);
        await showModalAlert(`${failure}: ${err.message}`, { title: 'Overlay Error', type: 'error' });
    }
}

/**
 * Toggles a scenario's status as a merged Baseline layer via the backend API.
 */
export function toggleBaselineLayer(scenId) {
    if (!scenId) return Promise.resolve();
    const url = `/api/scenarios/${encodeURIComponent(scenId)}/toggle_baseline_layer`;
    return postOverlayChange(url, {}, 'Failed to toggle baseline overlay', scenId);
}

/**
 * Switches a merged overlay off (or back on) without unmerging it, so it keeps its place in the stack.
 */
export function setBaselineLayerSuspended(scenId, suspended) {
    if (!scenId) return Promise.resolve();
    const url = `/api/scenarios/${encodeURIComponent(scenId)}/suspend_baseline_layer`;
    return postOverlayChange(url, { suspended: Boolean(suspended) }, 'Failed to switch baseline overlay', scenId);
}

/**
 * Saves a new Baseline overlay stack order (the order merged plans are applied in).
 */
export function reorderBaselineLayers(layerIds) {
    if (!Array.isArray(layerIds) || layerIds.length === 0) return Promise.resolve();
    return postOverlayChange(
        '/api/scenarios/baseline_layers/reorder', { layer_ids: layerIds }, 'Failed to reorder baseline overlays',
        'scen_baseline'
    );
}

const DROPDOWNS = [
    { btnId: 'btn-scorecard-columns-dropdown', menuId: 'menu-scorecard-columns', reposition: true },
    { btnId: 'btn-view-plans-dropdown', menuId: 'menu-view-plans', reposition: true },
    { btnId: 'btn-add-overlay-dropdown', menuId: 'menu-add-overlay', reposition: false }
];

/**
 * Dynamically clamps the View Plans menu within viewport bounds.
 */
export function positionViewPlansMenu(btn, menu) {
    if (!btn || !menu) return;
    menu.style.left = '0px';
    menu.style.right = 'auto';
    window.positionDropdownMenu(menu);
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
 * Closes all open dropdown menus in the Forecasting scorecard/overlays toolbar
 * except the optionally specified menu element.
 */
export function closeAllScenarioDropdowns(exceptMenu = null) {
    DROPDOWNS.forEach(({ btnId, menuId }) => {
        const m = document.getElementById(menuId);
        if (m && m !== exceptMenu) {
            m.style.display = 'none';
            const b = document.getElementById(btnId);
            if (b) b.setAttribute('aria-expanded', 'false');
        }
    });
    document.querySelectorAll('.scorecard-more-dropdown-menu').forEach(m => {
        if (m !== exceptMenu) {
            m.style.display = 'none';
            const trigger = m.parentElement ? m.parentElement.querySelector('.btn-scorecard-more-actions') : null;
            if (trigger) trigger.setAttribute('aria-expanded', 'false');
        }
    });
}

const DISMISS_SAFE = DROPDOWNS.flatMap(({ btnId, menuId }) => [`#${menuId}`, `#${btnId}`])
    .concat('.scorecard-row-menu-wrap').join(',');

function toggleDropdown({ btnId, menuId, reposition }) {
    const btn = document.getElementById(btnId);
    const menu = document.getElementById(menuId);
    if (!btn || !menu) return;
    const isOpen = menu.style.display !== 'none' && menu.style.display !== '';
    closeAllScenarioDropdowns(menu);
    menu.style.display = isOpen ? 'none' : 'block';
    btn.setAttribute('aria-expanded', isOpen ? 'false' : 'true');
    if (!isOpen && reposition) positionViewPlansMenu(btn, menu);
}

const layerToggle = (attr) => (el) => {
    const id = attr.map(a => el.getAttribute(a)).find(Boolean);
    if (id) toggleBaselineLayer(id);
};

/** Document-level listeners for the overlays toolbar; installed once, they survive every morph of the markup. */
export function installOverlayDelegation() {
    listenOnce(document, 'scenario-dropdown-dismiss', 'click', (e) => {
        if (!e.target.closest(DISMISS_SAFE)) closeAllScenarioDropdowns();
    });
    listenOnce(document, 'scenario-dropdown-dismiss', 'keydown', (e) => {
        if (e.key === 'Escape') closeAllScenarioDropdowns();
    });
    delegate(document, 'scenario-overlays', () => ({
        click: {
            ...Object.fromEntries(DROPDOWNS.map(d => [d.btnId, () => toggleDropdown(d)])),
            'btn-toggle-baseline-layer': layerToggle(['data-scen-id']),
            '.btn-unmerge-baseline-layer': layerToggle(['data-layer-id']),
            '.btn-toggle-overlay-scenario': layerToggle(['data-scen-id', 'data-id']),
            '.btn-add-baseline-overlay-item': (el) => {
                closeAllScenarioDropdowns();
                layerToggle(['data-scen-id'])(el);
            }
        },
        change: {
            'chk-filter-strategy-plans': (el) => filterChanged('strategyPlans', el),
            'chk-filter-baseline-overlays': (el) => filterChanged('baselineOverlays', el),
            'chk-filter-archived-plans': (el) => filterChanged('archivedPlans', el),
            '.chk-baseline-layer-on': (el) => setBaselineLayerSuspended(el.getAttribute('data-layer-id'), !el.checked),
            '#menu-scorecard-columns input[data-col-key]': (el) => {
                setColumnSetting(el.getAttribute('data-col-key'), el.checked);
                applyScorecardColumns();
            }
        }
    }));
}

function filterChanged(key, el) {
    setFilterSetting(key, el.checked);
    applyPlanFilters();
}

/**
 * Reads user column visibility preferences from localStorage.
 */
export function getColumnSettings() {
    const defaults = {
        primary_ret: false,
        spouse_ret: false,
        nw65: true,
        nw85: true,
        nw95: true,
        solvency: true
    };
    try {
        const raw = localStorage.getItem('scenarios_scorecard_columns');
        if (!raw) return defaults;
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== 'object') return defaults;
        return {
            primary_ret: parsed.primary_ret === true,
            spouse_ret: parsed.spouse_ret === true,
            nw65: parsed.nw65 !== false,
            nw85: parsed.nw85 !== false,
            nw95: parsed.nw95 !== false,
            solvency: parsed.solvency !== false
        };
    } catch {
        return defaults;
    }
}

/**
 * Persists a column visibility preference to localStorage.
 */
export function setColumnSetting(colKey, visible) {
    try {
        const current = getColumnSettings();
        current[colKey] = Boolean(visible);
        localStorage.setItem('scenarios_scorecard_columns', JSON.stringify(current));
    } catch {
        // Ignore storage errors
    }
}

/**
 * Applies column visibility settings to the comparison table headers and cells.
 */
export function applyScorecardColumns(customCols) {
    const cols = customCols || getColumnSettings();
    const colKeys = ['primary_ret', 'spouse_ret', 'nw65', 'nw85', 'nw95', 'solvency'];

    colKeys.forEach(colKey => {
        const visible = Boolean(cols[colKey]);
        const chk = document.querySelector(`#menu-scorecard-columns input[data-col-key="${colKey}"]`);
        if (chk && chk.checked !== visible) {
            chk.checked = visible;
        }
        document.querySelectorAll(`#table-scenarios-scorecard [data-scorecard-col="${colKey}"]`).forEach(cell => {
            cell.style.display = visible ? '' : 'none';
        });
    });
}

/**
 * Main initialization entry point for scenario overlay controls and filters.
 */
export function initCardsOverlays() {
    installOverlayDelegation();
    applyScorecardColumns();
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
    window.closeAllScenarioDropdowns = closeAllScenarioDropdowns;
    window.toggleBaselineLayer = toggleBaselineLayer;
    window.setBaselineLayerSuspended = setBaselineLayerSuspended;
    window.reorderBaselineLayers = reorderBaselineLayers;
    window.applyPlanFilters = applyPlanFilters;
    window.getFilterSettings = getFilterSettings;
    window.setFilterSetting = setFilterSetting;
    window.getColumnSettings = getColumnSettings;
    window.setColumnSetting = setColumnSetting;
    window.applyScorecardColumns = applyScorecardColumns;
    window.installOverlayDelegation = installOverlayDelegation;
    window.positionViewPlansMenu = positionViewPlansMenu;
}
