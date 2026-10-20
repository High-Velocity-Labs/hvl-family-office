/**
 * static/js/scenarios/controls.js
 * Scenario Studio Controls: Quick Tuning, Assumptions Sync, and Auto-Recalculation
 */
import { state, initFastInstantTooltips } from './state.js';
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

const openNewScenarioModal = (...args) => (
    typeof window !== 'undefined' && window.openNewScenarioModal
        ? window.openNewScenarioModal(...args)
        : null
);
const openEditScenarioModal = (...args) => (
    typeof window !== 'undefined' && window.openEditScenarioModal
        ? window.openEditScenarioModal(...args)
        : null
);
const cloneScenario = (...args) => (
    typeof window !== 'undefined' && window.cloneScenario
        ? window.cloneScenario(...args)
        : null
);
const renderCatalogModalList = (...args) => (
    typeof window !== 'undefined' && window.renderCatalogModalList
        ? window.renderCatalogModalList(...args)
        : null
);

function bindDelegatedControls() {
    if (typeof document === 'undefined' || typeof window === 'undefined' || window._scenDelegatedBound) return;
    window._scenDelegatedBound = true;
    document.addEventListener('click', (e) => {
        const zoomBtn = e.target.closest('#btn-zoom-5y, #btn-chart-zoom-5y, #btn-zoom-15y, #btn-chart-zoom-15y, #btn-zoom-lifetime, #btn-chart-zoom-lifetime');
        if (zoomBtn) {
            if (zoomBtn.id.includes('5y')) setSmoothZoom('5y');
            else if (zoomBtn.id.includes('15y')) setSmoothZoom('15y');
            else if (zoomBtn.id.includes('lifetime')) setSmoothZoom('lifetime');
            return;
        }
        const panPrev = e.target.closest('#btn-pan-prev, #btn-chart-pan-prev');
        if (panPrev) {
            panSmooth(-1);
            return;
        }
        const panNext = e.target.closest('#btn-pan-next, #btn-chart-pan-next');
        if (panNext) {
            panSmooth(1);
            return;
        }
    });
}

function bindHeaderActionButtons() {
    const btnWideMode = document.getElementById('btn-forecasting-wide-mode');
    if (btnWideMode && !btnWideMode._wired) {
        btnWideMode._wired = true;
        btnWideMode.addEventListener('click', () => {
            if (typeof window.toggleSidebar === 'function') {
                window.toggleSidebar();
                setTimeout(() => {
                    if (state.scenarioComparisonChart) state.scenarioComparisonChart.resize();
                }, 250);
            }
        });
    }

    const btnReal = document.getElementById('btn-scen-view-real');
    const btnNominal = document.getElementById('btn-scen-view-nominal');
    if (btnReal && !btnReal._wired) {
        btnReal._wired = true;
        btnReal.addEventListener('click', () => setScenarioSetting({ view_mode: 'real' }));
    }
    if (btnNominal && !btnNominal._wired) {
        btnNominal._wired = true;
        btnNominal.addEventListener('click', () => setScenarioSetting({ view_mode: 'nominal' }));
    }

    const selectGrowth = document.getElementById('select-equity-growth');
    if (selectGrowth && !selectGrowth._wired) {
        selectGrowth._wired = true;
        selectGrowth.addEventListener('change', (e) => {
            setScenarioSetting({ equity_growth_preset: e.target.value });
        });
    }
}

function bindAssumptionsPanel() {
    const btnTogglePlan = document.getElementById('btn-toggle-current-plan') || document.getElementById('btn-toggle-assumptions-bar');
    const planBody = document.getElementById('current-plan-collapsible-body') || document.getElementById('forecasting-assumptions-grid');
    const txtTogglePlan = document.getElementById('txt-toggle-current-plan') || document.getElementById('txt-toggle-assumptions');

    if (btnTogglePlan && planBody) {
        const isExpanded = localStorage.getItem('scen_plan_details_expanded') === 'true';
        planBody.style.display = isExpanded ? 'block' : 'none';
        if (txtTogglePlan) {
            txtTogglePlan.textContent = isExpanded ? '▲ Plan Details' : '▼ Plan Details';
        }
        btnTogglePlan.classList.toggle('active', isExpanded);

        btnTogglePlan.onclick = () => {
            const curBody = document.getElementById('current-plan-collapsible-body') || document.getElementById('forecasting-assumptions-grid');
            const curTxt = document.getElementById('txt-toggle-current-plan') || document.getElementById('txt-toggle-assumptions');
            if (!curBody) return;
            const isHidden = curBody.style.display === 'none';
            curBody.style.display = isHidden ? 'block' : 'none';
            if (curTxt) {
                curTxt.textContent = isHidden ? '▲ Plan Details' : '▼ Plan Details';
            }
            btnTogglePlan.classList.toggle('active', isHidden);
            localStorage.setItem('scen_plan_details_expanded', isHidden ? 'true' : 'false');
        };
    }

    const btnSaveToPlan = document.getElementById('btn-save-to-plan');
    if (btnSaveToPlan && !btnSaveToPlan._wired) {
        btnSaveToPlan._wired = true;
        let isSaving = false;
        btnSaveToPlan.addEventListener('click', (e) => {
            if (btnSaveToPlan.disabled || isSaving) return;
            if (e) e.preventDefault();
            if (document.activeElement && typeof document.activeElement.blur === 'function') {
                document.activeElement.blur();
            }
            isSaving = true;
            saveAssumptionsToSelectedPlan().finally(() => {
                isSaving = false;
            });
        });
    }

    ['scen-input-primary-ret-age', 'scen-input-spouse-ret-age', 'scen-input-living-spend', 'scen-input-annual-savings', 'scen-input-inflation'].forEach(id => {
        const el = document.getElementById(id);
        if (el && !el._wired) {
            el._wired = true;
            el.addEventListener('input', () => {
                updateSaveButtonState();
            });
            el.addEventListener('change', () => {
                updateSaveButtonState();
                applyQuickAssumptions(false);
            });
            el.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    el.blur();
                }
            });
        }
    });

    initAssetGrowthControls();
}

function bindTimelineAndCatalogControls() {
    const btnShelfInView = document.getElementById('btn-shelf-filter-inview');
    const btnShelfAll = document.getElementById('btn-shelf-filter-all');
    if (btnShelfInView && !btnShelfInView._wired) {
        btnShelfInView._wired = true;
        btnShelfInView.addEventListener('click', () => {
            state.shelfFilterMode = 'inview';
            updateShelfFilterButtons();
            renderTimelineContinuous();
        });
    }
    if (btnShelfAll && !btnShelfAll._wired) {
        btnShelfAll._wired = true;
        btnShelfAll.addEventListener('click', () => {
            state.shelfFilterMode = 'all';
            updateShelfFilterButtons();
            renderTimelineContinuous();
        });
    }

    const scrubber = document.getElementById('timeline-scrubber');
    if (scrubber && !scrubber._wired) {
        scrubber._wired = true;
        scrubber.addEventListener('input', (e) => {
            const yr = parseInt(e.target.value);
            state.inspectedYear = yr;
            updateScrubberNeedle(yr);
            inspectTimelineYear(yr);
        });
    }

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
            const isHidden = curContainer.style.display === 'none';
            curContainer.style.display = isHidden ? 'block' : 'none';
            const count = (state.scenariosData?.scorecard || []).length;
            btnToggleScorecard.innerHTML = isHidden ? '▲ Collapse Comparison' : (count > 0 ? `Compare Plans (${count}) ▼` : 'Compare Plans ▼');
            btnToggleScorecard.classList.toggle('active', isHidden);
            if (isHidden && typeof initFastInstantTooltips === 'function') {
                setTimeout(initFastInstantTooltips, 50);
            }
        };
    }

    const btnOpenCatalogTop = document.getElementById('btn-open-catalog-top');
    if (btnOpenCatalogTop && !btnOpenCatalogTop._wired) {
        btnOpenCatalogTop._wired = true;
        btnOpenCatalogTop.addEventListener('click', () => {
            const modalCatalog = document.getElementById('modal-events-catalog');
            if (modalCatalog) {
                modalCatalog.style.display = 'flex';
                if (state.scenariosData) renderCatalogModalList(state.scenariosData);
            }
        });
    }

    const btnAddEventTop = document.getElementById('btn-add-event-top');
    if (btnAddEventTop && !btnAddEventTop._wired) {
        btnAddEventTop._wired = true;
        btnAddEventTop.addEventListener('click', () => {
            if (typeof window.openCreateEventModal === 'function') {
                window.openCreateEventModal();
            }
        });
    }

    const btnCreateBar = document.getElementById('btn-create-scenario-bar');
    if (btnCreateBar && !btnCreateBar._wired) {
        btnCreateBar._wired = true;
        btnCreateBar.addEventListener('click', () => {
            openNewScenarioModal();
        });
    }

    const btnEditTop = document.getElementById('btn-edit-selected-scenario');
    if (btnEditTop && !btnEditTop._wired) {
        btnEditTop._wired = true;
        btnEditTop.addEventListener('click', () => {
            const scenarios = (state.scenariosData && state.scenariosData.scenarios) || [];
            let scenObj = scenarios.find(s => s.id === state.selectedScenarioId)
                || scenarios.find(s => s.id === state.scenariosData?.active_scenario_id || s.is_active || s.id === 'scen_baseline')
                || scenarios[0];
            if (scenObj) {
                state.selectedScenarioId = scenObj.id;
                openEditScenarioModal(scenObj);
            } else {
                openNewScenarioModal();
            }
        });
    }

    const btnCloneTop = document.getElementById('btn-clone-selected-scenario');
    if (btnCloneTop && !btnCloneTop._wired) {
        btnCloneTop._wired = true;
        btnCloneTop.addEventListener('click', () => {
            const scenObj = (state.scenariosData && state.scenariosData.scenarios || []).find(s => s.id === state.selectedScenarioId)
                || (state.scenariosData && state.scenariosData.scenarios || []).find(s => s.id === state.scenariosData?.active_scenario_id || s.is_active || s.id === 'scen_baseline')
                || (state.scenariosData && state.scenariosData.scenarios && state.scenariosData.scenarios[0]);
            if (scenObj) {
                cloneScenario(scenObj.id);
            }
        });
    }

    const btnToggleSchedule = document.getElementById('btn-toggle-scen-schedule');
    const scheduleContainer = document.getElementById('scen-schedule-container');
    if (btnToggleSchedule && scheduleContainer) {
        btnToggleSchedule.onclick = () => {
            const curSched = document.getElementById('scen-schedule-container');
            if (!curSched) return;
            const isHidden = curSched.style.display === 'none';
            curSched.style.display = isHidden ? 'block' : 'none';
            btnToggleSchedule.textContent = isHidden ? 'Hide Schedule ▲' : 'Show Full Schedule (53 Years) ▼';
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
    bindDelegatedControls();
    bindHeaderActionButtons();
    bindAssumptionsPanel();
    bindTimelineAndCatalogControls();
    bindSocialSecurityButtons();
}
