/**
 * Forecasting Controller (Scenario Studio & Longevity Forecaster)
 * Main Orchestrator & Public API Facade (ES Module)
 * Pure SSR: /fragments/scenarios is swapped by the standard HTMX morph path (see wireScenariosSwapEvents).
 */
import { state, initFastInstantTooltips, ensureMonteCarloForScenario } from './state.js';
import {
    initScenarioControls, syncAssumptionInputs, updateSaveButtonState,
    triggerAutoRecalc, applyQuickAssumptions, saveAssumptionsToSelectedPlan, setScenarioSetting
} from './controls.js';
import {
    updateActiveScenarioButton, formatScenarioOverrides,
    bindSsrScenarioCardsAndTables, bindSsrDomEvents
} from './cards.js';
import { bindSsrContinuousRibbon, setDynamicWindow, inspectTimelineYear } from './scrubber.js';
import { switchToLens } from './charts/index.js';
import { switchScenarioInPlace } from './charts/net_worth_highlight.js';
import { setCfSubMode } from './charts/cash_flow.js';
import { setMcSubMode } from './charts/monte_carlo.js';
import {
    renderEventChecklistAndCatalog, openNewChildScenarioModal, openNewScenarioModal,
    openEditScenarioModal, openCreateEventModal, openEditEventModal, cloneScenario, cloneEvent,
    initEventWizardControls, initCatalogModalControls, initScenarioModalControls,
    renderCatalogModalList
} from './modals.js';
import { ensureScheduleRows } from './schedule_table.js';

export function consumeSsrDataScript(root = document) {
    const ssrScript = root.querySelector('#ssr-scenarios-data');
    if (!ssrScript) return null;
    try {
        const raw = ssrScript.textContent;
        ssrScript.remove();
        if (raw && raw.trim().length > 0) {
            return JSON.parse(raw);
        }
    } catch (e) {
        console.warn('Failed to parse SSR scenarios data:', e);
    }
    return null;
}

export function setScenarioLoadingState(isLoading, labelText = 'Running forecast...') {
    const throbber = document.getElementById('scenario-switch-loading');
    const throbberText = document.getElementById('scenario-switch-loading-text');
    if (throbber) {
        if (throbberText && labelText) {
            throbberText.textContent = labelText;
        }
        throbber.style.display = isLoading ? 'inline-flex' : 'none';
    }
    const loader = document.getElementById('scenarios-chart-loading');
    if (loader) {
        if (isLoading) {
            loader.classList.remove('hidden');
            loader.style.display = 'flex';
        } else {
            loader.classList.add('hidden');
            loader.style.display = 'none';
        }
    }
    const planCard = document.getElementById('selected-scenario-plan-card');
    if (planCard) {
        planCard.style.opacity = isLoading ? '0.65' : '';
        planCard.style.transition = 'opacity 0.15s ease';
    }
}

export function buildForecastCsvExportUrl() {
    const params = {};
    if (state.selectedScenarioId) {
        params.scenario_id = state.selectedScenarioId;
    }
    if (state.scenariosData?.view_mode) {
        params.view_mode = state.scenariosData.view_mode;
    }
    const pRet = document.getElementById('scen-input-primary-retire-age')?.value;
    const sRet = document.getElementById('scen-input-spouse-retire-age')?.value;
    const spend = document.getElementById('scen-input-living-spend')?.value;
    const sav = document.getElementById('scen-input-annual-savings')?.value;
    const inf = document.getElementById('scen-input-inflation-rate')?.value;
    if (pRet) params.primary_retirement_age = pRet;
    if (sRet) params.spouse_retirement_age = sRet;
    if (spend) params.annual_living_spend = spend;
    if (sav) params.annual_savings = sav;
    if (inf) {
        const infNum = parseFloat(inf);
        if (!isNaN(infNum)) {
            params.inflation_rate = infNum > 1 ? String(infNum / 100) : String(infNum);
        }
    }
    const qs = new URLSearchParams(params).toString();
    return `/api/scenarios/export_csv${qs ? `?${qs}` : ''}`;
}

export function syncExportCsvLink() {
    const btn = document.getElementById('btn-export-forecast-csv');
    if (btn) {
        btn.setAttribute('href', buildForecastCsvExportUrl());
    }
}

export function exportForecastCsv(event) {
    const url = buildForecastCsvExportUrl();
    const btn = document.getElementById('btn-export-forecast-csv');
    if (btn) btn.setAttribute('href', url);
    if (!event) {
        window.location.href = url;
    }
    return true;
}

export function preserveInteractiveExpansionStates(newSection, { scorecardOpen, scheduleOpen, topEventsOpen, planDetailsOpen, assetGrowthOpen }) {
    if (!newSection) return;

    const newScorecard = newSection.querySelector('#container-side-by-side-scorecard');
    const newScorecardBtn = newSection.querySelector('#btn-toggle-scorecard-table');
    if (newScorecard && scorecardOpen !== undefined) {
        newScorecard.style.display = scorecardOpen ? 'block' : 'none';
        if (newScorecardBtn) {
            const count = (state.scenariosData?.scorecard || []).length;
            newScorecardBtn.textContent = scorecardOpen
                ? (count > 0 ? `▲ Hide Plans (${count})` : '▲ Hide Plans')
                : (count > 0 ? `Compare Plans (${count}) ▼` : 'Compare Plans ▼');
            newScorecardBtn.classList.toggle('active', Boolean(scorecardOpen));
        }
    }

    const newSched = newSection.querySelector('#scen-schedule-container');
    const newSchedBtn = newSection.querySelector('#btn-toggle-scen-schedule');
    if (newSched && scheduleOpen) {
        newSched.style.display = 'block';
        if (newSchedBtn) {
            newSchedBtn.textContent = 'Hide Schedule ▲';
        }
    }

    const newTopEvents = newSection.querySelector('#selected-scen-events-expanded');
    const newTopChev = newSection.querySelector('.scen-evt-top-chevron');
    if (newTopEvents && topEventsOpen) {
        newTopEvents.style.display = 'flex';
        if (newTopChev) newTopChev.textContent = '▼';
    }

    const newPlanBody = newSection.querySelector('#current-plan-collapsible-body');
    const newPlanBtn = newSection.querySelector('#btn-toggle-current-plan');
    const newPlanTxt = newSection.querySelector('#txt-toggle-current-plan');
    if (newPlanBody && planDetailsOpen) {
        newPlanBody.style.display = 'block';
        if (newPlanTxt) newPlanTxt.textContent = '▲ Plan Details';
        if (newPlanBtn) newPlanBtn.classList.add('active');
    }

    const newAssetBody = newSection.querySelector('#asset-growth-body');
    const newAssetBtn = newSection.querySelector('#btn-toggle-asset-growth');
    const newAssetTxt = newSection.querySelector('#txt-toggle-asset-growth');
    if (newAssetBody && assetGrowthOpen) {
        newAssetBody.style.display = 'block';
        if (newAssetTxt) newAssetTxt.textContent = '▲ Advanced Levers';
        if (newAssetBtn) newAssetBtn.classList.add('active');
    }
}

export function consumeScenarioDeepLinkParams({ switchToLens, setCfSubMode, setMcSubMode, openCreateEventModal }) {
    if (!window.location.search) return false;
    const params = new URLSearchParams(window.location.search);
    const lens = params.get('lens');
    const view = params.get('view');
    const mcMode = params.get('mc_mode');
    const openEvent = params.get('open_event');
    const openGuardrails = params.get('open_guardrails') === '1';
    const compare = params.get('compare') === '1';
    const askAi = params.get('ask_ai');

    if (!lens && !view && !mcMode && !openEvent && !openGuardrails && !compare && !askAi) {
        return false;
    }

    ['lens', 'view', 'mc_mode', 'open_event', 'open_guardrails', 'compare', 'ask_ai'].forEach(k => params.delete(k));
    const rest = params.toString();
    window.history.replaceState({}, '', `${window.location.pathname}${rest ? `?${rest}` : ''}${window.location.hash}`);

    if (view === 'sankey' || view === 'timeline') setCfSubMode(view);
    if (mcMode === 'historical' || mcMode === 'stochastic') setMcSubMode(mcMode);

    const targetLens = lens || (view === 'sankey' ? 'cashflow' : (mcMode ? 'montecarlo' : null));
    if (targetLens && ['networth', 'cashflow', 'longevity', 'montecarlo'].includes(targetLens)) {
        switchToLens(targetLens, true);
    }

    if (compare) {
        const sc = document.getElementById('container-side-by-side-scorecard');
        const scBtn = document.getElementById('btn-toggle-scorecard-table');
        if (sc) sc.style.display = 'block';
        if (scBtn) {
            scBtn.textContent = '▲ Collapse Comparison';
            scBtn.classList.add('active');
        }
        const planBody = document.getElementById('current-plan-collapsible-body');
        const planBtn = document.getElementById('btn-toggle-current-plan');
        const planTxt = document.getElementById('txt-toggle-current-plan');
        if (planBody) planBody.style.display = 'block';
        if (planTxt) planTxt.textContent = '▲ Plan Details';
        if (planBtn) planBtn.classList.add('active');
    }

    if (openGuardrails) {
        const planBody = document.getElementById('current-plan-collapsible-body');
        const planBtn = document.getElementById('btn-toggle-current-plan');
        const planTxt = document.getElementById('txt-toggle-current-plan');
        if (planBody) planBody.style.display = 'block';
        if (planTxt) planTxt.textContent = '▲ Plan Details';
        if (planBtn) planBtn.classList.add('active');

        const assetBody = document.getElementById('asset-growth-body');
        const assetBtn = document.getElementById('btn-toggle-asset-growth');
        const assetTxt = document.getElementById('txt-toggle-asset-growth');
        if (assetBody) assetBody.style.display = 'block';
        if (assetTxt) assetTxt.textContent = '▲ Advanced Levers';
        if (assetBtn) assetBtn.classList.add('active');

        const grEl = document.getElementById('scen-input-spending-guardrails');
        if (grEl) {
            grEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
            grEl.focus();
        }
    }

    if (openEvent) {
        openCreateEventModal(openEvent);
    }

    if (askAi) {
        window.toggleAiAdvisorDrawer(true);
        const aiInput = document.getElementById('ai-advisor-input');
        if (aiInput) {
            aiInput.value = askAi;
            const charCounter = document.getElementById('advisor-char-counter');
            if (charCounter) charCounter.textContent = `${askAi.length} / 2000`;
            aiInput.focus();
        }
    }

    return true;
}

let pendingExpansionStates = null;
let inFlightFetch = null;
let lastInFlightParamsKey = null;

export function hydrateSsrScenariosSection(data) {
    if (!data || !data.success) {
        setScenarioLoadingState(false);
        return null;
    }

    state.scenariosData = data;
    if (state.inspectedYear === null) state.inspectedYear = data.start_year;
    if (state.currentPanStartYear === null) state.currentPanStartYear = data.start_year;
    if (typeof window !== 'undefined') {
        window.hasLoadedScenarios = true;
        window.scenariosDirty = false;
        window.isLoadingScenarios = false;
    }

    if (data.active_monte_carlo && data.active_monte_carlo.scenario_id) {
        state.cachedMonteCarloByScen[data.active_monte_carlo.scenario_id] = data.active_monte_carlo;
    }

    const scenarios = data.scenarios || [];
    const targetId = data.selected_scenario_id || state.selectedScenarioId || data.active_scenario_id;
    const exists = scenarios.some(s => s.id === targetId);
    state.selectedScenarioId = exists
        ? targetId
        : (data.active_scenario_id
            || (scenarios.find(s => s.is_active || s.id === 'scen_baseline')?.id)
            || (scenarios[0] && scenarios[0].id)
            || null);

    if (state.selectedScenarioId && typeof localStorage !== 'undefined') {
        try { localStorage.setItem('scen_selected_id', state.selectedScenarioId); } catch (e) {}
    }

    if (typeof document !== 'undefined') {
        if (pendingExpansionStates) {
            preserveInteractiveExpansionStates(document.getElementById('section-scenarios'), pendingExpansionStates);
            pendingExpansionStates = null;
        }
        ensureScheduleRows();
        setScenarioLoadingState(false);
        initFastInstantTooltips();
        initScenarioControls();
        initScenarioModalControls();
        initEventWizardControls();
        initCatalogModalControls();
        syncAssumptionInputs(data);
        bindSsrScenarioCardsAndTables(data);
        bindSsrContinuousRibbon(data);
        renderEventChecklistAndCatalog(data);
        syncExportCsvLink();
        window.applyWidgetEditModeUI('scenarios');
        // The one chart draw for this data: chart sizes and collapsed state first, then every forecasting chart.
        window.hydrateWidgetCharts('scenarios');
        consumeScenarioDeepLinkParams({ switchToLens, setCfSubMode, setMcSubMode, openCreateEventModal });
    }

    return data;
}

export async function morphScenariosSection(params = {}) {
    if (typeof document === 'undefined') return null;

    if (!params.background) {
        setScenarioLoadingState(true);
    }

    const mergedParams = { ...params };
    if (mergedParams.scenario_id === undefined && state.selectedScenarioId) {
        mergedParams.scenario_id = state.selectedScenarioId;
    }
    if (mergedParams.view_mode === undefined && state.scenariosData?.view_mode) {
        mergedParams.view_mode = state.scenariosData.view_mode;
    }
    if (mergedParams.widgets === undefined && typeof window !== 'undefined' && window.__demoWidgetsScenarios !== undefined) {
        mergedParams.widgets = window.__demoWidgetsScenarios;
    }

    const cleanParams = {};
    Object.entries(mergedParams).forEach(([k, v]) => {
        if (v !== undefined && v !== null && v !== '') {
            cleanParams[k] = String(v);
        }
    });

    const qs = new URLSearchParams(cleanParams).toString();
    const url = `/fragments/scenarios${qs ? `?${qs}` : ''}`;

    try {
        await window.htmx.ajax('GET', url, { target: '#section-scenarios', swap: 'morph' });
    } finally {
        setScenarioLoadingState(false);
    }
    return state.scenariosData;
}

const storedFlag = (key) => typeof localStorage !== 'undefined' && localStorage.getItem(key) === 'true';

export function captureExpansionStates() {
    return {
        scorecardOpen: document.getElementById('container-side-by-side-scorecard')?.style.display !== 'none',
        scheduleOpen: document.getElementById('scen-schedule-container')?.style.display === 'block',
        topEventsOpen: document.getElementById('selected-scen-events-expanded')?.style.display === 'flex',
        planDetailsOpen: storedFlag('scen_plan_details_expanded'),
        assetGrowthOpen: storedFlag('scen_asset_growth_expanded')
    };
}

// The standard HTMX morph swap is the only way this section is refreshed. Around any swap into it
// (tab navigation, domain-version refresh, morphScenariosSection) we keep the user's open/closed panels
// and hydrate from the SSR data script the fragment carries.
export function wireScenariosSwapEvents() {
    const isScenarios = (evt) => evt.detail && evt.detail.target && evt.detail.target.id === 'section-scenarios';
    document.addEventListener('htmx:beforeSwap', (evt) => {
        if (isScenarios(evt)) pendingExpansionStates = captureExpansionStates();
    });
    document.addEventListener('htmx:afterSwap', (evt) => {
        if (!isScenarios(evt)) return;
        const data = consumeSsrDataScript(evt.detail.target);
        if (data) hydrateSsrScenariosSection(data);
        else setScenarioLoadingState(false);
    });
    ['htmx:responseError', 'htmx:sendError'].forEach(name => document.addEventListener(name, (evt) => {
        if (isScenarios(evt)) setScenarioLoadingState(false);
    }));
}

export async function fetchScenariosData(customParams = {}, isPreview = false) {
    const paramsKey = JSON.stringify(customParams) + (isPreview ? '_prev' : '');
    if (inFlightFetch && lastInFlightParamsKey === paramsKey) {
        return inFlightFetch;
    }

    const hasCustomParams = customParams && Object.keys(customParams).length > 0;
    const initialSsrData = (!hasCustomParams && !isPreview) ? consumeSsrDataScript(document) : null;

    lastInFlightParamsKey = paramsKey;
    inFlightFetch = (async () => {
        try {
            if (initialSsrData && initialSsrData.success) {
                return hydrateSsrScenariosSection(initialSsrData);
            }
            if (!hasCustomParams && !isPreview && state.scenariosData && state.scenariosData.success) {
                return hydrateSsrScenariosSection(state.scenariosData);
            }
            return await morphScenariosSection(customParams);
        } catch (err) {
            console.error('Error in fetchScenariosData:', err);
            setScenarioLoadingState(false);
            return state.scenariosData;
        } finally {
            inFlightFetch = null;
            lastInFlightParamsKey = null;
            if (typeof window !== 'undefined') {
                window.isLoadingScenarios = false;
            }
            if (!state.scenariosData && typeof document !== 'undefined') {
                setScenarioLoadingState(false);
            }
        }
    })();

    return inFlightFetch;
}

export const loadAndRenderScenarios = fetchScenariosData;

export async function switchToScenario(scenId) {
    return switchScenarioInPlace(scenId);
}

export async function revertScenarioOverride(key) {
    const scenarios = (state.scenariosData && state.scenariosData.scenarios) || [];
    const currentScen = scenarios.find(s => s.id === state.selectedScenarioId);
    if (!currentScen || !currentScen.parent_id) return;

    currentScen[key] = null;
    try {
        const resp = await fetch('/api/scenarios', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(currentScen)
        });
        const res = await resp.json();
        if (res.success) {
            await morphScenariosSection({ scenario_id: state.selectedScenarioId });
        }
    } catch (e) {
        console.error('Failed to revert override:', e);
    }
}

// Attach backwards-compatible global hooks on window
if (typeof window !== 'undefined') {
    window.fetchScenariosData = fetchScenariosData;
    window.loadAndRenderScenarios = loadAndRenderScenarios;
    window.morphScenariosSection = morphScenariosSection;
    window.switchToScenario = switchToScenario;
    window.switchToLens = switchToLens;
    window.openNewChildScenarioModal = openNewChildScenarioModal;
    window.openNewScenarioModal = openNewScenarioModal;
    window.openEditScenarioModal = openEditScenarioModal;
    window.cloneScenario = cloneScenario;
    window.cloneEvent = cloneEvent;
    window.revertScenarioOverride = revertScenarioOverride;
    window.formatScenarioOverrides = formatScenarioOverrides;
    window.triggerAutoRecalc = triggerAutoRecalc;
    window.updateSaveButtonState = updateSaveButtonState;
    window.renderCatalogModalList = renderCatalogModalList;
    window.bindSsrDomEvents = bindSsrDomEvents;
    window.exportForecastCsv = exportForecastCsv;
    window.syncExportCsvLink = syncExportCsvLink;
    window.hasLoadedScenarios = false;
    window.scenariosDirty = false;
    window.registerSectionHydrator('section-scenarios', () => fetchScenariosData(), {
        morphFn: () => morphScenariosSection(),
        onInvalidate: () => {
            state.cachedMonteCarloByScen = {};
            window.hasLoadedScenarios = false;
            window.scenariosDirty = true;
        }
    });
}

// Initialize scenario module controls and trigger initial hydration
if (typeof document !== 'undefined') {
    wireScenariosSwapEvents();
    const initAll = () => {
        initFastInstantTooltips();
        initScenarioControls();
        initScenarioModalControls();
        initEventWizardControls();
        initCatalogModalControls();
        const path = window.location.pathname.toLowerCase();
        const isScenariosActive = window.INITIAL_ACTIVE_SECTION === 'section-scenarios'
            || window.currentSectionId === 'section-scenarios'
            || ['#forecasting', '#scenarios', '#section-scenarios'].includes(window.location.hash)
            || path.includes('/forecasting') || path.includes('/scenarios');
        if (isScenariosActive) window.hydrateSection('section-scenarios');
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAll);
    } else {
        initAll();
    }
}
