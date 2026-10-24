/**
 * Forecasting Controller (Scenario Studio & Longevity Forecaster)
 * Main Orchestrator & Public API Facade (ES Module)
 * Uses pure SSR + Idiomorph DOM morphing (/fragments/scenarios).
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
import { renderActiveLensChart, switchToLens } from './charts/index.js';
import { switchScenarioInPlace } from './charts/net_worth_highlight.js';
import { setCfSubMode } from './charts/cash_flow.js';
import { setMcSubMode } from './charts/monte_carlo.js';
import {
    renderEventChecklistAndCatalog, openNewChildScenarioModal, openNewScenarioModal,
    openEditScenarioModal, openCreateEventModal, openEditEventModal, cloneScenario, cloneEvent,
    initEventWizardControls, initCatalogModalControls, initScenarioModalControls,
    renderCatalogModalList
} from './modals.js';
import {
    consumeSsrDataScript,
    setScenarioLoadingState,
    buildForecastCsvExportUrl,
    syncExportCsvLink,
    exportForecastCsv,
    preserveInteractiveExpansionStates,
    consumeScenarioDeepLinkParams
} from './main_helpers.js';

export {
    setScenarioLoadingState,
    buildForecastCsvExportUrl,
    syncExportCsvLink,
    exportForecastCsv,
    consumeScenarioDeepLinkParams
};

let inFlightFetch = null;
let lastInFlightParamsKey = null;

export function hydrateSsrScenariosSection(data) {
    if (!data || !data.success) {
        setScenarioLoadingState(false);
        return null;
    }

    state.scenariosData = data;
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
        setScenarioLoadingState(false);
        initFastInstantTooltips();
        initScenarioControls();
        initScenarioModalControls();
        initEventWizardControls();
        initCatalogModalControls();
        syncAssumptionInputs(data);
        bindSsrScenarioCardsAndTables(data);
        bindSsrContinuousRibbon(data);
        renderActiveLensChart();
        renderEventChecklistAndCatalog(data);
        syncExportCsvLink();
        if (typeof window !== 'undefined' && typeof window.applyWidgetEditModeUI === 'function') {
            window.applyWidgetEditModeUI('scenarios');
        }
        if (typeof window !== 'undefined' && typeof window.hydrateWidgetCharts === 'function') {
            window.hydrateWidgetCharts('scenarios');
        }
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

    const targetSection = document.getElementById('section-scenarios');
    const wasVisible = targetSection ? targetSection.style.display !== 'none' : true;
    const expansionStates = {
        scorecardOpen: document.getElementById('container-side-by-side-scorecard')?.style.display === 'block',
        scheduleOpen: document.getElementById('scen-schedule-container')?.style.display === 'block',
        topEventsOpen: document.getElementById('selected-scen-events-expanded')?.style.display === 'flex',
        planDetailsOpen: typeof localStorage !== 'undefined' && localStorage.getItem('scen_plan_details_expanded') === 'true',
        assetGrowthOpen: typeof localStorage !== 'undefined' && localStorage.getItem('scen_asset_growth_expanded') === 'true'
    };

    let resp;
    try {
        resp = await fetch(url, {
            headers: { 'HX-Request': 'true' }
        });
    } catch (err) {
        setScenarioLoadingState(false);
        throw err;
    }
    if (!resp.ok) {
        console.error('Failed to fetch scenarios fragment:', resp.status);
        setScenarioLoadingState(false);
        return state.scenariosData;
    }

    const html = await resp.text();
    let newSection = null;
    if (typeof DOMParser !== 'undefined') {
        const doc = new DOMParser().parseFromString(html, 'text/html');
        newSection = doc.getElementById('section-scenarios') || doc.querySelector('#section-scenarios');
    } else {
        const tmp = document.createElement('div');
        tmp.innerHTML = html;
        newSection = tmp.querySelector('#section-scenarios');
    }

    if (!newSection) {
        setScenarioLoadingState(false);
        return state.scenariosData;
    }

    if (wasVisible) {
        newSection.style.display = '';
    }

    preserveInteractiveExpansionStates(newSection, expansionStates);

    const parsedData = consumeSsrDataScript(newSection);

    if (targetSection) {
        window.Idiomorph.morph(targetSection, newSection, {
            morphStyle: 'outerHTML',
            callbacks: {
                beforeNodeMorphed: function (oldNode, newNode) {
                    if (oldNode && (oldNode.tagName === 'CANVAS' || oldNode.id === 'chart-scenarios-comparison')) {
                        return false;
                    }
                    if (oldNode && newNode && oldNode.dataset && newNode.dataset) {
                        if (oldNode.dataset.wired) newNode.dataset.wired = oldNode.dataset.wired;
                        if (oldNode.dataset.wiredEvents) newNode.dataset.wiredEvents = oldNode.dataset.wiredEvents;
                        if (oldNode.dataset.ssrWired) newNode.dataset.ssrWired = oldNode.dataset.ssrWired;
                    }
                    return true;
                }
            }
        });
        if (typeof window !== 'undefined' && window.BugReporter && typeof window.BugReporter.ensurePaneTriggers === 'function') {
            window.BugReporter.ensurePaneTriggers();
        }
    }

    const finalData = parsedData || consumeSsrDataScript(document) || state.scenariosData;
    if (finalData) {
        hydrateSsrScenariosSection(finalData);
    } else if (typeof document !== 'undefined') {
        setScenarioLoadingState(false);
    }
    return state.scenariosData;
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
    if (typeof window.registerSectionHydrator === 'function') {
        window.registerSectionHydrator('section-scenarios', () => fetchScenariosData(), {
            morphFn: () => morphScenariosSection(),
            onInvalidate: () => {
                state.cachedMonteCarloByScen = {};
                window.hasLoadedScenarios = false;
                window.scenariosDirty = true;
            }
        });
    }
}

// Initialize scenario module controls and trigger initial hydration
if (typeof document !== 'undefined') {
    const initAll = () => {
        initFastInstantTooltips();
        initScenarioControls();
        initScenarioModalControls();
        initEventWizardControls();
        initCatalogModalControls();
        const isScenariosActive = (typeof window !== 'undefined') && (
            window.INITIAL_ACTIVE_SECTION === 'section-scenarios' ||
            window.currentSectionId === 'section-scenarios' ||
            window.location.hash === '#forecasting' ||
            window.location.hash === '#scenarios' ||
            window.location.hash === '#section-scenarios' ||
            (window.location.pathname && (window.location.pathname.toLowerCase().includes('/forecasting') || window.location.pathname.toLowerCase().includes('/scenarios'))) ||
            window.currentViewMode === 'all'
        );
        if (isScenariosActive && typeof fetchScenariosData === 'function') {
            if (typeof window !== 'undefined' && typeof window.hydrateSection === 'function') {
                window.hydrateSection('section-scenarios');
            } else {
                fetchScenariosData();
            }
        }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAll);
    } else {
        initAll();
    }
}
