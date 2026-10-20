/**
 * Scenario Studio & Longevity Forecaster: State Management & Constants
 * Core state store and orchestrator re-exporting categories, icon maps, and tooltips.
 */
import {
    EVENT_SVG_MAP, ICON_PICKER_GROUPS, ICON_PICKER_CATALOG,
    MILESTONE_SVG_MAP, getEventIcon, getMilestoneIcon,
    resolveEventIcon, resolveMilestoneIcon,
    getEventCanvasImage, getMilestoneCanvasImage
} from './state_icons.js';
import {
    CATEGORY_THEMES, EVENT_CATEGORY_GROUPS,
    formatCategoryLabel, getCategoryBadgeClass
} from './state_categories.js';

export {
    EVENT_SVG_MAP, ICON_PICKER_GROUPS, ICON_PICKER_CATALOG,
    MILESTONE_SVG_MAP, getEventIcon, getMilestoneIcon,
    resolveEventIcon, resolveMilestoneIcon,
    getEventCanvasImage, getMilestoneCanvasImage,
    CATEGORY_THEMES, EVENT_CATEGORY_GROUPS,
    formatCategoryLabel, getCategoryBadgeClass
};

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
    currentPanStartYear: 2026,
    inspectedYear: 2026,
    fastTooltipEl: null,
    ribbonUpdateScheduled: false,
    shelfFilterMode: 'inview', // 'inview' | 'all'
    showMonteCarloCorridor: true,
    cachedMonteCarloByScen: {},
    cachedMonteCarloData: null,
    cachedMonteCarloScenId: null,
    fetchingMcScenIds: new Set(),
};

if (typeof localStorage !== 'undefined') {
    try {
        const savedMc = localStorage.getItem('scen_show_mc_corridor');
        if (savedMc !== null) state.showMonteCarloCorridor = (savedMc === 'true');
    } catch (e) {}
}

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
                if (typeof onFetchedCallback === 'function') {
                    onFetchedCallback(data);
                } else if (typeof window !== 'undefined' && typeof window.renderActiveLensChart === 'function') {
                    const activeId = state.selectedScenarioId || state.scenariosData?.active_scenario_id || 'scen_baseline';
                    if (activeId === scenId) {
                        window.renderActiveLensChart();
                    }
                }
            }
        }
    } catch (e) {
        console.error('Failed to fetch Monte Carlo for scenario:', scenId, e);
    } finally {
        state.fetchingMcScenIds.delete(scenId);
    }
}

export function initFastInstantTooltips() {
    const isTouchOrMobile = () => (typeof window !== 'undefined') && (
        (typeof window.isTouchDevice === 'function' && window.isTouchDevice()) ||
        (Boolean(window.ontouchstart !== undefined && window.ontouchstart !== null)) ||
        (typeof navigator !== 'undefined' && navigator.maxTouchPoints > 0) ||
        (typeof window.matchMedia === 'function' && window.matchMedia('(hover: none), (pointer: coarse), (max-width: 768px)').matches)
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
        if (isTouchOrMobile() || !e.target || typeof e.target.closest !== 'function' || e.target.closest('.sidebar')) {
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
