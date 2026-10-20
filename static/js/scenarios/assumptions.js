/**
 * static/js/scenarios/assumptions.js
 * Advanced Plan Assumptions Extension: Withdrawal Drawdown Order & LP Capital Call Pacing.
 * Wires #input-plan-drawdown-order and #scen-input-accelerate-lp into scenario auto-recalc and persistence.
 */

function getActiveScenario() {
    const scenarios = (window.state && window.state.scenariosData && window.state.scenariosData.scenarios) || [];
    const selId = window.state?.selectedScenarioId || window.state?.scenariosData?.active_scenario_id;
    return scenarios.find(s => s.id === selId) || scenarios[0] || {};
}

function updateDrawdownBadge(val) {
    const badge = document.getElementById('badge-plan-drawdown-order');
    if (!badge) return;
    const labels = {
        taxable_first: 'Taxable 1st',
        pretax_first: 'Pre-Tax 1st',
        pro_rata: 'Pro-Rata',
    };
    badge.textContent = `Drawdown: ${labels[val] || 'Taxable 1st'}`;
}

export function syncAssumptionsUi() {
    const scen = getActiveScenario();
    const elOrder = document.getElementById('input-plan-drawdown-order');
    const elAcc = document.getElementById('scen-input-accelerate-lp');

    if (elOrder && scen.drawdown_order) {
        elOrder.value = scen.drawdown_order;
        updateDrawdownBadge(scen.drawdown_order);
    }
    if (elAcc && scen.accelerate_lp_calls !== undefined) {
        elAcc.checked = Boolean(scen.accelerate_lp_calls);
    }
}

export function initAssumptionsControls() {
    const elOrder = document.getElementById('input-plan-drawdown-order');
    const elAcc = document.getElementById('scen-input-accelerate-lp');

    if (elOrder && !elOrder.dataset.boundAssumptions) {
        elOrder.dataset.boundAssumptions = 'true';
        elOrder.addEventListener('change', async (e) => {
            const val = e.target.value || 'taxable_first';
            updateDrawdownBadge(val);
            const scen = getActiveScenario();
            scen.drawdown_order = val;

            const saveBtn = document.getElementById('btn-save-to-plan');
            if (saveBtn) {
                saveBtn.disabled = false;
                saveBtn.style.opacity = '1';
            }

            if (typeof window.morphScenariosSection === 'function') {
                await window.morphScenariosSection({ drawdown_order: val });
            }
        });
    }

    if (elAcc && !elAcc.dataset.boundAssumptions) {
        elAcc.dataset.boundAssumptions = 'true';
        elAcc.addEventListener('change', async (e) => {
            const checked = Boolean(e.target.checked);
            const scen = getActiveScenario();
            scen.accelerate_lp_calls = checked;

            const saveBtn = document.getElementById('btn-save-to-plan');
            if (saveBtn) {
                saveBtn.disabled = false;
                saveBtn.style.opacity = '1';
            }

            if (typeof window.morphScenariosSection === 'function') {
                await window.morphScenariosSection({ accelerate_lp_calls: checked });
            }
        });
    }

    // Intercept or hook save button to guarantee drawdown_order and accelerate_lp_calls are persisted
    const saveBtn = document.getElementById('btn-save-to-plan');
    if (saveBtn && !saveBtn.dataset.boundLpAssumptions) {
        saveBtn.dataset.boundLpAssumptions = 'true';
        saveBtn.addEventListener('click', () => {
            const scen = getActiveScenario();
            const orderEl = document.getElementById('input-plan-drawdown-order');
            const accEl = document.getElementById('scen-input-accelerate-lp');
            if (orderEl) scen.drawdown_order = orderEl.value;
            if (accEl) scen.accelerate_lp_calls = Boolean(accEl.checked);
        }, true); // capture phase to run before controls_events.js saveAssumptionsToSelectedPlan
    }
}

// Auto-run on document ready and on htmx swaps
if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAssumptionsControls);
    } else {
        initAssumptionsControls();
    }
    document.addEventListener('htmx:afterSwap', () => {
        initAssumptionsControls();
        syncAssumptionsUi();
    });
}

if (typeof window !== 'undefined') {
    window.initAssumptionsControls = initAssumptionsControls;
    window.syncAssumptionsUi = syncAssumptionsUi;
}
