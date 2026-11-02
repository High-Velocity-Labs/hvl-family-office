/**
 * Scenario Studio & Longevity Forecaster: State Management & Constants
 * Core state store and orchestrator re-exporting categories, icon maps, and tooltips.
 */
import {
    EVENT_ICON_ALIASES, ICON_PICKER_GROUPS, ICON_PICKER_CATALOG,
    getEventIcon, getMilestoneIcon,
    resolveEventIcon, resolveMilestoneIcon,
    getEventCanvasImage, getMilestoneCanvasImage
} from './state_icons.js';
import {
    categoryTheme,
    formatCategoryLabel, getCategoryBadgeClass
} from './state_categories.js';

export {
    EVENT_ICON_ALIASES, ICON_PICKER_GROUPS, ICON_PICKER_CATALOG,
    getEventIcon, getMilestoneIcon,
    resolveEventIcon, resolveMilestoneIcon,
    getEventCanvasImage, getMilestoneCanvasImage,
    categoryTheme,
    formatCategoryLabel, getCategoryBadgeClass
};

/**
 * First projection year of the loaded plan, stamped by the server on the simulation as `start_year`.
 * Throws if no plan is loaded: a chart or modal must never guess what "now" is.
 */
export function getPlanStartYear() {
    const y = state.scenariosData && state.scenariosData.start_year;
    if (!Number.isInteger(y)) throw new Error('Scenario data carries no start_year');
    return y;
}

export const state = {
    scenariosData: null,
    selectedScenarioId: null,
    scenarioComparisonChart: null,
    cashFlowChart: null,
    longevityChart: null,
    monteCarloChart: null,
    currentLens: 'networth', // 'networth' | 'cashflow' | 'longevity' | 'montecarlo'
    currentZoom: 'lifetime', // 'lifetime' | '15y' | '5y' | 'dynamic'
    currentWindowMinYear: 2018,
    currentWindowMaxYear: 2060,
    currentPanStartYear: null,  // set from scenariosData.start_year when data hydrates
    inspectedYear: null,
    fastTooltipEl: null,
    ribbonUpdateScheduled: false,
    shelfFilterMode: 'inview', // 'inview' | 'all'
    showMonteCarloCorridor: true,
    cachedMonteCarloByScen: {},
    cachedMonteCarloData: null,
    cachedMonteCarloScenId: null,
    fetchingMcScenIds: new Set(),
    graphScenarioIds: {
        networth: null,
        cashflow: null,
        longevity: null,
        montecarlo: null,
    },
};

const GRAPH_SCEN_STORAGE_KEYS = {
    networth: 'scen_graph_networth_id',
    cashflow: 'scen_graph_cashflow_id',
    longevity: 'scen_graph_longevity_id',
    montecarlo: 'scen_graph_montecarlo_id',
};

if (typeof localStorage !== 'undefined') {
    try {
        const savedMc = localStorage.getItem('scen_show_mc_corridor');
        if (savedMc !== null) state.showMonteCarloCorridor = (savedMc === 'true');
        Object.entries(GRAPH_SCEN_STORAGE_KEYS).forEach(([key, storageKey]) => {
            const savedId = localStorage.getItem(storageKey);
            if (savedId) state.graphScenarioIds[key] = savedId;
        });
    } catch (e) {}
}

/**
 * Whether the charts give a plan its own line and pill. A merged overlay that is switched on is already part of the
 * Baseline Plan's line, so it gets neither, unless it is the plan being viewed.
 */
export function isDrawnOnCharts(scen) {
    return !scen.is_baseline_layer || scen.id === state.selectedScenarioId;
}

export function getGraphScenarioId(graphKey) {
    const scenarios = state.scenariosData?.scenarios || [];
    const localId = graphKey ? state.graphScenarioIds?.[graphKey] : null;
    if (localId && (!scenarios.length || scenarios.some(s => s.id === localId && isDrawnOnCharts(s)))) {
        return localId;
    }
    return state.selectedScenarioId || state.scenariosData?.active_scenario_id || 'scen_baseline';
}

export function setGraphScenarioId(graphKey, scenId) {
    if (!graphKey || !scenId) return;
    if (!state.graphScenarioIds) state.graphScenarioIds = {};
    state.graphScenarioIds[graphKey] = scenId;
    const storageKey = GRAPH_SCEN_STORAGE_KEYS[graphKey] || `scen_graph_${graphKey}_id`;
    if (typeof localStorage !== 'undefined') {
        try {
            localStorage.setItem(storageKey, scenId);
        } catch (e) {}
    }
}

// Formatting is owned by hvl_common utils.js (loaded before this module); delegate with no local fallback copies.
export const escapeHtml = (str) => window.escapeHtml(str);
export const fmtCurrency = (val, maxFrac = 2) => window.fmtCurrency(val, maxFrac);
export const fmtShortCurrency = (val) => window.fmtShortCurrency(val);

export function getMonteCarloForScenario(scenId) {
    if (!scenId) return null;
    if (state.scenariosData && state.scenariosData.active_monte_carlo && state.scenariosData.active_monte_carlo.scenario_id === scenId) {
        state.cachedMonteCarloByScen[scenId] = state.scenariosData.active_monte_carlo;
        state.cachedMonteCarloData = state.scenariosData.active_monte_carlo;
        state.cachedMonteCarloScenId = scenId;
        return state.scenariosData.active_monte_carlo;
    }
    if (state.cachedMonteCarloByScen[scenId]) {
        state.cachedMonteCarloData = state.cachedMonteCarloByScen[scenId];
        state.cachedMonteCarloScenId = scenId;
        return state.cachedMonteCarloByScen[scenId];
    }
    return null;
}

export async function ensureMonteCarloForScenario(scenId, onFetchedCallback) {
    if (!scenId || getMonteCarloForScenario(scenId)) return;
    if (state.fetchingMcScenIds.has(scenId)) return;
    state.fetchingMcScenIds.add(scenId);
    try {
        const resp = await fetch(`/api/scenarios/monte-carlo?scenario_id=${encodeURIComponent(scenId)}&trials=1000`);
        if (resp.ok) {
            const data = await resp.json();
            if (data && data.success) {
                state.cachedMonteCarloByScen[scenId] = data;
                state.cachedMonteCarloData = data;
                state.cachedMonteCarloScenId = scenId;
                if (onFetchedCallback) {
                    onFetchedCallback(data);
                } else {
                    const activeIds = new Set([
                        state.selectedScenarioId || state.scenariosData?.active_scenario_id || 'scen_baseline',
                        getGraphScenarioId('networth'),
                        getGraphScenarioId('cashflow'),
                        getGraphScenarioId('longevity'),
                        getGraphScenarioId('montecarlo'),
                    ]);
                    if (activeIds.has(scenId)) {
                        window.renderActiveLensChart();
                    }
                }
                return data;
            }
        }
    } catch (e) {
        console.error('Failed to fetch Monte Carlo for scenario:', scenId, e);
    } finally {
        state.fetchingMcScenIds.delete(scenId);
    }
}

export function initFastInstantTooltips() {
    const isTouchOrMobile = () => (
        window.isTouchDevice() ||
        (Boolean(window.ontouchstart !== undefined && window.ontouchstart !== null)) ||
        (typeof navigator !== 'undefined' && navigator.maxTouchPoints > 0) ||
        (Boolean(window.matchMedia)
            && window.matchMedia('(hover: none), (pointer: coarse), (max-width: 768px)').matches)
    );
    if (isTouchOrMobile()) return;

    if (!state.fastTooltipEl) {
        state.fastTooltipEl = document.getElementById('fast-instant-tooltip');
        if (!state.fastTooltipEl) {
            state.fastTooltipEl = document.createElement('div');
            state.fastTooltipEl.id = 'fast-instant-tooltip';
            state.fastTooltipEl.className = 'fast-instant-tooltip';
            document.body.appendChild(state.fastTooltipEl);
        }
    }

    if (state._fastTooltipsBound) return;
    state._fastTooltipsBound = true;

    const hide = () => {
        if (state.fastTooltipEl) {
            state.fastTooltipEl.classList.remove('visible');
        }
    };

    // Strip native title from any element on mouseover to avoid slow OS delay, converting to data-tooltip
    document.addEventListener('mouseover', (e) => {
        if (isTouchOrMobile() || !e.target.closest || e.target.closest('.sidebar')) {
            hide();
            return;
        }

        const withTitle = e.target.closest('[title]');
        if (withTitle && !withTitle.hasAttribute('data-tooltip')) {
            const t = withTitle.getAttribute('title');
            if (t && t.trim()) {
                withTitle.setAttribute('data-tooltip', t);
                withTitle.removeAttribute('title');
            }
        }

        const el = e.target.closest('[data-tooltip]');
        if (!el) {
            hide();
            return;
        }

        const text = el.getAttribute('data-tooltip');
        if (!text) {
            hide();
            return;
        }

        state.fastTooltipEl.textContent = text;
        state.fastTooltipEl.classList.add('visible');

        const rect = el.getBoundingClientRect();
        const tipWidth = state.fastTooltipEl.offsetWidth;
        const tipHeight = state.fastTooltipEl.offsetHeight;

        let left = rect.left + (rect.width / 2) - (tipWidth / 2);
        let top = rect.top - tipHeight - 8;

        if (top < 10) {
            top = rect.bottom + 8;
        }
        if (left < 10) left = 10;
        if (left + tipWidth > window.innerWidth - 10) {
            left = window.innerWidth - tipWidth - 10;
        }

        state.fastTooltipEl.style.left = `${Math.round(left)}px`;
        state.fastTooltipEl.style.top = `${Math.round(top)}px`;
    }, { passive: true });

    document.addEventListener('mouseout', (e) => {
        const el = e.target.closest('[data-tooltip]');
        if (el) {
            hide();
        }
    }, { passive: true });

    window.addEventListener('scroll', hide, { passive: true });
}

if (typeof window !== 'undefined') {
    window.scenariosState = state;
    try {
        Object.defineProperty(window, 'scenariosData', {
            get: () => state.scenariosData,
            set: (v) => { state.scenariosData = v; },
            configurable: true
        });
        Object.defineProperty(window, 'selectedScenarioId', {
            get: () => state.selectedScenarioId,
            set: (v) => { state.selectedScenarioId = v; },
            configurable: true
        });
    } catch (e) {}
}
