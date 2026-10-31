/**
 * static/js/scenarios/assumptions.js
 * Advanced Plan Assumptions Extension: Withdrawal Drawdown Order & LP Capital Call Pacing.
 * Wires #input-plan-drawdown-order and #scen-input-accelerate-lp into scenario auto-recalc and persistence.
 */

import { delegate, listenOnce } from './event_delegation.js';

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

function enableSaveToPlan() {
    const saveBtn = document.getElementById('btn-save-to-plan');
    if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.style.opacity = '1';
    }
}

/** Document-level listeners for the assumption inputs and the save button; installed once, immune to morphs. */
export function initAssumptionsControls() {
    delegate(document, 'assumptions', () => ({
        change: {
            'input-plan-drawdown-order': async (el) => {
                const val = el.value || 'taxable_first';
                updateDrawdownBadge(val);
                getActiveScenario().drawdown_order = val;
                enableSaveToPlan();
                await window.morphScenariosSection({ drawdown_order: val });
            },
            'scen-input-accelerate-lp': async (el) => {
                const checked = Boolean(el.checked);
                getActiveScenario().accelerate_lp_calls = checked;
                enableSaveToPlan();
                await window.morphScenariosSection({ accelerate_lp_calls: checked });
            }
        }
    }));

    // Capture phase, so the in-memory plan is current before controls_events.js saveAssumptionsToSelectedPlan runs.
    listenOnce(document, 'assumptions-save', 'click', (e) => {
        if (!e.target.closest('#btn-save-to-plan')) return;
        const scen = getActiveScenario();
        const orderEl = document.getElementById('input-plan-drawdown-order');
        const accEl = document.getElementById('scen-input-accelerate-lp');
        if (orderEl) scen.drawdown_order = orderEl.value;
        if (accEl) scen.accelerate_lp_calls = Boolean(accEl.checked);
    }, true);
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
