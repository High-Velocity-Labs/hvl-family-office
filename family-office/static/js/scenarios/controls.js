/**
 * static/js/scenarios/controls.js
 * Scenario Studio Controls: Quick Tuning, Assumptions Sync, and Auto-Recalculation
 */
import { state, initFastInstantTooltips } from './state.js';
import { delegate } from './event_delegation.js';
import {
    updateShelfFilterButtons,
    updateScrubberNeedle,
    inspectTimelineYear,
    renderTimelineContinuous
} from './scrubber.js';
import { setSmoothZoom, panSmooth, initChartZoomAndPan } from './zoom_engine.js';
import { switchToLens } from './charts/index.js';
import {
    bindScenSpendPresetButtons,
    bindScenSavingsPresetButtons,
    parseAssetRateInput,
    updateSaveButtonState,
    initAssetGrowthControls,
    syncAssumptionInputs
} from './controls_sliders.js';
import {
    setScenarioSetting,
    triggerAutoRecalc,
    saveAssumptionsToSelectedPlan,
    applyQuickAssumptions
} from './controls_events.js';
import { initAssumptionsControls, syncAssumptionsUi } from './assumptions.js';
import { ensureScheduleRows } from './schedule_table.js';

export {
    bindScenSpendPresetButtons,
    bindScenSavingsPresetButtons,
    parseAssetRateInput,
    updateSaveButtonState,
    initAssetGrowthControls,
    syncAssumptionInputs,
    setScenarioSetting,
    triggerAutoRecalc,
    saveAssumptionsToSelectedPlan,
    applyQuickAssumptions
};

// The plan modals register these on window when main.js loads; resolved at call time (modules import in a cycle).
const openNewScenarioModal = (...args) => window.openNewScenarioModal(...args);
const openEditScenarioModal = (...args) => window.openEditScenarioModal(...args);
const cloneScenario = (...args) => window.cloneScenario(...args);
const renderCatalogModalList = (...args) => window.renderCatalogModalList(...args);

const ASSUMPTION_INPUT_IDS = [
    'scen-input-primary-ret-age', 'scen-input-spouse-ret-age', 'scen-input-living-spend',
    'scen-input-annual-savings', 'scen-input-inflation'
];

let isSavingAssumptions = false;

function selectedOrActiveScenario() {
    const scenarios = (state.scenariosData && state.scenariosData.scenarios) || [];
    return scenarios.find(s => s.id === state.selectedScenarioId)
        || scenarios.find(s => (
            s.id === state.scenariosData?.active_scenario_id || s.is_active || s.id === 'scen_baseline'
        ))
        || scenarios[0];
}

function toggleWideMode() {
    window.toggleSidebar();
    setTimeout(() => {
        if (state.scenarioComparisonChart) state.scenarioComparisonChart.resize();
    }, 250);
}

function saveToPlan(btn, e) {
    if (btn.disabled || isSavingAssumptions) return;
    e.preventDefault();
    document.activeElement?.blur();
    isSavingAssumptions = true;
    saveAssumptionsToSelectedPlan().finally(() => {
        isSavingAssumptions = false;
    });
}

function openCatalogFromToolbar() {
    const modalCatalog = document.getElementById('modal-events-catalog');
    if (!modalCatalog) return;
    modalCatalog.hidden = false;
    modalCatalog.classList.remove('hidden');
    if (state.scenariosData) renderCatalogModalList(state.scenariosData);
}

function editSelectedPlan() {
    const scenObj = selectedOrActiveScenario();
    if (scenObj) {
        state.selectedScenarioId = scenObj.id;
        openEditScenarioModal(scenObj);
    } else {
        openNewScenarioModal();
    }
}

function setShelfFilter(mode) {
    state.shelfFilterMode = mode;
    updateShelfFilterButtons();
    renderTimelineContinuous();
}

const assumptionInputHandlers = (handler) => Object.fromEntries(ASSUMPTION_INPUT_IDS.map(id => [id, handler]));

/** Document-level listeners for the scenario toolbar, zoom/pan, assumption inputs and timeline; installed once. */
function installControlsDelegation() {
    delegate(document, 'scenario-controls', () => ({
        click: {
            'btn-zoom-5y': () => setSmoothZoom('5y'),
            'btn-chart-zoom-5y': () => setSmoothZoom('5y'),
            'btn-zoom-15y': () => setSmoothZoom('15y'),
            'btn-chart-zoom-15y': () => setSmoothZoom('15y'),
            'btn-zoom-lifetime': () => setSmoothZoom('lifetime'),
            'btn-chart-zoom-lifetime': () => setSmoothZoom('lifetime'),
            'btn-pan-prev': () => panSmooth(-1),
            'btn-chart-pan-prev': () => panSmooth(-1),
            'btn-pan-next': () => panSmooth(1),
            'btn-chart-pan-next': () => panSmooth(1),
            'btn-forecasting-wide-mode': toggleWideMode,
            'btn-scen-view-real': () => setScenarioSetting({ view_mode: 'real' }),
            'btn-scen-view-nominal': () => setScenarioSetting({ view_mode: 'nominal' }),
            'btn-save-to-plan': saveToPlan,
            'btn-shelf-filter-inview': () => setShelfFilter('inview'),
            'btn-shelf-filter-all': () => setShelfFilter('all'),
            'btn-open-catalog-top': openCatalogFromToolbar,
            'btn-add-event-top': () => window.openCreateEventModal(),
            'btn-create-scenario-bar': () => openNewScenarioModal(),
            'btn-edit-selected-scenario': editSelectedPlan,
            'btn-clone-selected-scenario': () => {
                const scenObj = selectedOrActiveScenario();
                if (scenObj) cloneScenario(scenObj.id);
            }
        },
        change: {
            'select-equity-growth': (el) => setScenarioSetting({ equity_growth_preset: el.value }),
            ...assumptionInputHandlers(() => {
                updateSaveButtonState();
                applyQuickAssumptions(false);
            })
        },
        input: {
            'timeline-scrubber': (el) => {
                const yr = parseInt(el.value);
                state.inspectedYear = yr;
                updateScrubberNeedle(yr);
                inspectTimelineYear(yr);
            },
            ...assumptionInputHandlers(() => updateSaveButtonState())
        },
        keydown: assumptionInputHandlers((el, e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                el.blur();
            }
        })
    }));
}

function bindAssumptionsPanel() {
    initAssumptionsControls();
    syncAssumptionsUi();
    const btnTogglePlan = document.getElementById('btn-toggle-current-plan') || document.getElementById('btn-toggle-assumptions-bar');
    const planBody = document.getElementById('current-plan-collapsible-body') || document.getElementById('forecasting-assumptions-grid');
    const txtTogglePlan = document.getElementById('txt-toggle-current-plan') || document.getElementById('txt-toggle-assumptions');

    if (btnTogglePlan && planBody) {
        const isExpanded = localStorage.getItem('scen_plan_details_expanded') === 'true';
        planBody.hidden = !isExpanded;
        planBody.classList.toggle('hidden', !isExpanded);
        if (txtTogglePlan) {
            txtTogglePlan.textContent = isExpanded ? '▲ Plan Details' : '▼ Plan Details';
        }
        btnTogglePlan.classList.toggle('active', isExpanded);

        btnTogglePlan.onclick = () => {
            const curBody = document.getElementById('current-plan-collapsible-body') || document.getElementById('forecasting-assumptions-grid');
            const curTxt = document.getElementById('txt-toggle-current-plan') || document.getElementById('txt-toggle-assumptions');
            if (!curBody) return;
            const isHidden = curBody.hidden || curBody.classList.contains('hidden');
            curBody.hidden = !isHidden;
            curBody.classList.toggle('hidden', !isHidden);
            if (curTxt) {
                curTxt.textContent = isHidden ? '▲ Plan Details' : '▼ Plan Details';
            }
            btnTogglePlan.classList.toggle('active', isHidden);
            localStorage.setItem('scen_plan_details_expanded', isHidden ? 'true' : 'false');
        };
    }

    initAssetGrowthControls();
}

function bindTimelineAndCatalogControls() {
    const chartCanvas = document.getElementById('chart-scenarios-comparison');
    if (chartCanvas) {
        initChartZoomAndPan(chartCanvas);
    }

    const btnToggleScorecard = document.getElementById('btn-toggle-scorecard-table');
    const containerScorecard = document.getElementById('container-side-by-side-scorecard');
    if (btnToggleScorecard && containerScorecard) {
        btnToggleScorecard.onclick = () => {
            const curContainer = document.getElementById('container-side-by-side-scorecard');
            if (!curContainer) return;
            const isHidden = curContainer.hidden || curContainer.classList.contains('hidden');
            curContainer.hidden = !isHidden;
            curContainer.classList.toggle('hidden', !isHidden);
            const count = (state.scenariosData?.scorecard || []).length;
            btnToggleScorecard.textContent = isHidden
                ? (count > 0 ? `▲ Hide Plans (${count})` : '▲ Hide Plans')
                : (count > 0 ? `Compare Plans (${count}) ▼` : 'Compare Plans ▼');
            btnToggleScorecard.classList.toggle('active', isHidden);
            if (isHidden) {
                setTimeout(initFastInstantTooltips, 50);
            }
        };
    }

    const btnToggleSchedule = document.getElementById('btn-toggle-scen-schedule');
    const scheduleContainer = document.getElementById('scen-schedule-container');
    if (btnToggleSchedule && scheduleContainer) {
        btnToggleSchedule.onclick = () => {
            const curSched = document.getElementById('scen-schedule-container');
            if (!curSched) return;
            const isHidden = curSched.hidden || curSched.classList.contains('hidden');
            curSched.hidden = !isHidden;
            curSched.classList.toggle('hidden', !isHidden);
            btnToggleSchedule.textContent = isHidden ? 'Hide Schedule ▲' : 'Show Full Schedule (53 Years) ▼';
            ensureScheduleRows();
        };
    }
}

function bindSocialSecurityButtons() {
    bindScenSpendPresetButtons();
    bindScenSavingsPresetButtons();

    document.querySelectorAll('.btn-scen-primary-ss-age').forEach(btn => {
        btn.onclick = () => {
            document.querySelectorAll('.btn-scen-primary-ss-age').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            updateSaveButtonState();
            applyQuickAssumptions(false);
        };
    });

    document.querySelectorAll('.btn-scen-spouse-ss-age').forEach(btn => {
        btn.onclick = () => {
            document.querySelectorAll('.btn-scen-spouse-ss-age').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            updateSaveButtonState();
            applyQuickAssumptions(false);
        };
    });

    document.querySelectorAll('.btn-scen-ss-age').forEach(btn => {
        btn.onclick = () => {
            document.querySelectorAll('.btn-scen-ss-age').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            updateSaveButtonState();
            applyQuickAssumptions(false);
        };
    });
}

export function initScenarioControls() {
    installControlsDelegation();
    bindAssumptionsPanel();
    bindTimelineAndCatalogControls();
    bindSocialSecurityButtons();
}
