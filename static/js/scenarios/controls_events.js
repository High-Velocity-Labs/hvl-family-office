/**
 * static/js/scenarios/controls_events.js
 * Scenario settings, persistence, and auto-recalculation handlers.
 */

import { state } from './state.js';
import { morphScenariosSection } from './main.js';
import { updateSaveButtonState, parseAssetRateInput } from './controls_sliders.js';

const showModalAlert = (...args) => (
    typeof window !== 'undefined' && window.showModalAlert
        ? window.showModalAlert(...args)
        : Promise.resolve()
);

let autoRecalcTimer = null;

function isReadOnlyOrDemo() {
    if (typeof window !== 'undefined' && typeof window.isDemoSession === 'function' && window.isDemoSession()) {
        return true;
    }
    if (typeof document !== 'undefined' && document.body) {
        if (document.body.dataset.isDemo === 'true' || document.body.dataset.role === 'viewer') {
            return true;
        }
    }
    if (typeof window !== 'undefined' && window.location && new URLSearchParams(window.location.search).get('demo') === '1') {
        return true;
    }
    return false;
}

export async function setScenarioSetting(params) {
    try {
        if (!isReadOnlyOrDemo()) {
            await fetch('/api/scenarios/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(params)
            });
        }
        await morphScenariosSection(params || {});
    } catch (err) {
        console.error('Failed to update scenario setting:', err);
    }
}

export function triggerAutoRecalc() {
    updateSaveButtonState();
    clearTimeout(autoRecalcTimer);
    autoRecalcTimer = setTimeout(() => {
        applyQuickAssumptions(false);
    }, 350);
}

export async function saveAssumptionsToSelectedPlan() {
    const btnSave = document.getElementById('btn-save-to-plan');
    const statusEl = document.getElementById('scen-assumptions-status');

    clearTimeout(autoRecalcTimer);

    const scenarios = (state.scenariosData && state.scenariosData.scenarios) || [];
    let currentScen = scenarios.find(s => s.id === state.selectedScenarioId)
        || scenarios.find(s => s.id === state.scenariosData?.active_scenario_id)
        || scenarios[0];
    if (!currentScen) {
        await showModalAlert('No plan is currently selected.', { title: 'No Plan Selected', type: 'error' });
        return;
    }

    const pCurrentAge = state.scenariosData?.primary_current_age || 49;
    const sCurrentAge = state.scenariosData?.spouse_current_age || 47;
    const elPri = document.getElementById('scen-input-primary-ret-age');
    const elSpouse = document.getElementById('scen-input-spouse-ret-age');
    const elSpend = document.getElementById('scen-input-living-spend');
    const elSavings = document.getElementById('scen-input-annual-savings');
    const elInflation = document.getElementById('scen-input-inflation');

    const defaultPriAge = currentScen.primary_retirement_age || Math.max(50, pCurrentAge);
    const defaultSpouseAge = currentScen.spouse_retirement_age || Math.max(50, sCurrentAge);
    let pRetAge = parseInt(elPri ? elPri.value : defaultPriAge) || defaultPriAge;
    let sRetAge = parseInt(elSpouse ? elSpouse.value : defaultSpouseAge) || defaultSpouseAge;
    if (pRetAge < pCurrentAge) {
        pRetAge = pCurrentAge;
        if (elPri) elPri.value = pRetAge;
    }
    if (sRetAge < sCurrentAge) {
        sRetAge = sCurrentAge;
        if (elSpouse) elSpouse.value = sRetAge;
    }

    const defaultLiving = currentScen.annual_living_spend || (typeof state.scenariosData !== 'undefined' ? state.scenariosData.annual_living_spend : 0) || 0;
    const defaultSavings = currentScen.annual_savings || (typeof state.scenariosData !== 'undefined' ? state.scenariosData.annual_savings : 0) || 0;
    const living = parseFloat(elSpend ? elSpend.value : defaultLiving) || defaultLiving;
    const savings = parseFloat(elSavings ? elSavings.value : defaultSavings) || defaultSavings;
    const inflation = parseFloat(elInflation ? elInflation.value : 0.025) || 0.025;

    const activePriSsBtn = document.querySelector('.btn-scen-primary-ss-age.active') || document.querySelector('.btn-scen-ss-age.active');
    const curPriSsAge = activePriSsBtn ? parseInt(activePriSsBtn.getAttribute('data-age') || 67) : 67;

    const activeSpouseSsBtn = document.querySelector('.btn-scen-spouse-ss-age.active');
    const curSpouseSsAge = activeSpouseSsBtn ? parseInt(activeSpouseSsBtn.getAttribute('data-age') || 67) : curPriSsAge;

    const selectGrowth = document.getElementById('select-scenario-inline-growth');
    const curGrowth = selectGrowth?.value || 'moderate';
    const elGuardrails = document.getElementById('scen-input-spending-guardrails');
    const curGuardrails = elGuardrails?.value || 'off';

    const curUs = parseAssetRateInput('scen-growth-us-equity', 0.085);
    const curIntl = parseAssetRateInput('scen-growth-intl-equity', 0.070);
    const curBonds = parseAssetRateInput('scen-growth-bonds', 0.045);
    const curCash = parseAssetRateInput('scen-growth-cash', 0.035);
    const curPriv = parseAssetRateInput('scen-growth-private', 0.100);
    const curRe = parseAssetRateInput('scen-growth-real-estate', 0.035);

    currentScen.primary_retirement_age = pRetAge;
    currentScen.spouse_retirement_age = sRetAge;
    currentScen.annual_living_spend = living;
    currentScen.annual_savings = savings;
    currentScen.inflation_rate = inflation;
    currentScen.primary_ss_claim_age = curPriSsAge;
    currentScen.spouse_ss_claim_age = curSpouseSsAge;
    currentScen.ss_claim_age = curPriSsAge;
    currentScen.equity_growth_preset = curGrowth;
    currentScen.spending_guardrail_mode = curGuardrails;
    currentScen.growth_us_equity = curUs;
    currentScen.growth_intl_equity = curIntl;
    currentScen.growth_bonds = curBonds;
    currentScen.growth_cash = curCash;
    currentScen.growth_private_investments = curPriv;
    currentScen.growth_real_estate = curRe;

    if (btnSave) {
        btnSave.disabled = true;
        btnSave.innerHTML = 'Saving...';
        btnSave.style.opacity = '0.7';
    }
    if (statusEl) {
        statusEl.textContent = `Saving parameters to "${currentScen.name}"...`;
        statusEl.style.color = 'var(--accent-orange)';
    }

    try {
        const controller = (typeof AbortController !== 'undefined') ? new AbortController() : null;
        const timeoutId = controller ? setTimeout(() => controller.abort(), 12000) : null;

        const resp = await fetch('/api/scenarios', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(currentScen),
            signal: controller ? controller.signal : undefined
        });
        if (timeoutId) clearTimeout(timeoutId);

        if (resp.status === 403) {
            if (btnSave) {
                btnSave.innerHTML = 'Save';
                updateSaveButtonState();
            }
            if (statusEl) {
                statusEl.textContent = 'Demo persona is read-only. Database changes are not saved.';
                statusEl.style.color = 'var(--accent-orange)';
            }
            return;
        }

        if (resp.status === 401) {
            if (btnSave) {
                btnSave.innerHTML = 'Save';
                updateSaveButtonState();
            }
            if (statusEl) {
                statusEl.textContent = 'Session expired. Please reload or log in again.';
                statusEl.style.color = 'var(--status-red, #EF4444)';
            }
            return;
        }

        const res = await resp.json();
        if (res.success) {
            try { localStorage.setItem('scen_selected_id', currentScen.id); } catch (e) {}
            if (selectGrowth) delete selectGrowth.dataset.userChanged;
            if (typeof window !== 'undefined') window._scenForceSyncSavedAssumptions = true;
            if (state.cachedMonteCarloByScen && currentScen.id) {
                delete state.cachedMonteCarloByScen[currentScen.id];
            }
            try {
                await morphScenariosSection({ scenario_id: currentScen.id });
            } catch (refErr) {
                console.warn('Background data refresh after save:', refErr);
            }
            const morphedStatus = document.getElementById('scen-assumptions-status');
            if (morphedStatus) {
                morphedStatus.textContent = `✓ Saved to "${currentScen.name}"!`;
                morphedStatus.style.color = 'var(--accent-green, #10B981)';
                setTimeout(() => { if (morphedStatus) morphedStatus.textContent = ''; }, 3000);
            }
        } else {
            if (btnSave) {
                btnSave.innerHTML = 'Save';
                updateSaveButtonState();
            }
            if (statusEl) {
                statusEl.textContent = `Save failed: ${res.error || 'Unknown error'}`;
                statusEl.style.color = 'var(--status-red, #EF4444)';
            }
        }
    } catch (err) {
        console.error('Failed to save scenario parameters:', err);
        if (btnSave) {
            btnSave.innerHTML = 'Save';
            updateSaveButtonState();
        }
        if (statusEl) {
            statusEl.textContent = (err.name === 'AbortError')
                ? 'Save timed out. Please check your network connection.'
                : 'Save failed: ' + err.message;
            statusEl.style.color = 'var(--status-red, #EF4444)';
        }
    } finally {
        const finalBtn = document.getElementById('btn-save-to-plan');
        if (finalBtn && finalBtn.innerHTML.includes('Saving')) {
            finalBtn.innerHTML = 'Save';
            updateSaveButtonState();
        }
    }
}

export async function applyQuickAssumptions(saveAsPersistentDefault = false) {
    const scenarios = (state.scenariosData && state.scenariosData.scenarios) || [];
    const currentScen = scenarios.find(s => s.id === state.selectedScenarioId)
        || scenarios.find(s => s.id === state.scenariosData?.active_scenario_id)
        || scenarios[0] || {};
    const pCurrentAge = state.scenariosData?.primary_current_age || 49;
    const sCurrentAge = state.scenariosData?.spouse_current_age || 47;
    const elPri = document.getElementById('scen-input-primary-ret-age');
    const elSpouse = document.getElementById('scen-input-spouse-ret-age');
    const defaultPriAge = currentScen.primary_retirement_age || Math.max(50, pCurrentAge);
    const defaultSpouseAge = currentScen.spouse_retirement_age || Math.max(50, sCurrentAge);
    let pRetAge = parseInt(elPri ? elPri.value : defaultPriAge) || defaultPriAge;
    let sRetAge = parseInt(elSpouse ? elSpouse.value : defaultSpouseAge) || defaultSpouseAge;
    if (pRetAge < pCurrentAge) {
        pRetAge = pCurrentAge;
        if (elPri) elPri.value = pRetAge;
    }
    if (sRetAge < sCurrentAge) {
        sRetAge = sCurrentAge;
        if (elSpouse) elSpouse.value = sRetAge;
    }
    const defaultLiving = currentScen.annual_living_spend || (typeof state.scenariosData !== 'undefined' ? state.scenariosData.annual_living_spend : 0) || 0;
    const defaultSavings = currentScen.annual_savings || (typeof state.scenariosData !== 'undefined' ? state.scenariosData.annual_savings : 0) || 0;
    const living = parseFloat(document.getElementById('scen-input-living-spend')?.value) || defaultLiving;
    const savings = parseFloat(document.getElementById('scen-input-annual-savings')?.value) || defaultSavings;
    const inflation = parseFloat(document.getElementById('scen-input-inflation')?.value) || 0.025;

    const activePriSsBtn = document.querySelector('.btn-scen-primary-ss-age.active') || document.querySelector('.btn-scen-ss-age.active');
    const primarySsClaimAge = activePriSsBtn ? parseInt(activePriSsBtn.getAttribute('data-age') || 67) : 67;

    const activeSpouseSsBtn = document.querySelector('.btn-scen-spouse-ss-age.active');
    const spouseSsClaimAge = activeSpouseSsBtn ? parseInt(activeSpouseSsBtn.getAttribute('data-age') || 67) : primarySsClaimAge;

    const selectGrowth = document.getElementById('select-scenario-inline-growth');
    const equityGrowthPreset = selectGrowth?.value || 'moderate';
    const elGuardrails = document.getElementById('scen-input-spending-guardrails');
    const spendingGuardrailMode = elGuardrails?.value || currentScen.spending_guardrail_mode || 'off';

    const curUs = parseAssetRateInput('scen-growth-us-equity', 0.085);
    const curIntl = parseAssetRateInput('scen-growth-intl-equity', 0.070);
    const curBonds = parseAssetRateInput('scen-growth-bonds', 0.045);
    const curCash = parseAssetRateInput('scen-growth-cash', 0.035);
    const curPriv = parseAssetRateInput('scen-growth-private', 0.100);
    const curRe = parseAssetRateInput('scen-growth-real-estate', 0.035);

    const statusEl = document.getElementById('scen-assumptions-status');

    if (statusEl) {
        statusEl.textContent = 'Updating projections in real time...';
        statusEl.style.color = 'var(--accent-orange)';
    }

    if (saveAsPersistentDefault && !isReadOnlyOrDemo()) {
        try {
            await fetch('/api/settings/assumptions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    retirement_age: pRetAge,
                    annual_spending: living,
                    annual_savings: savings,
                    inflation_rate: inflation,
                })
            });
        } catch (e) {
            console.warn('Could not persist default assumptions:', e);
        }
    }

    if (state.cachedMonteCarloByScen && state.selectedScenarioId) {
        delete state.cachedMonteCarloByScen[state.selectedScenarioId];
    }

    await morphScenariosSection({
        scenario_id: state.selectedScenarioId,
        primary_retirement_age: pRetAge,
        spouse_retirement_age: sRetAge,
        annual_living_spend: living,
        annual_savings: savings,
        inflation_rate: inflation,
        primary_ss_claim_age: primarySsClaimAge,
        spouse_ss_claim_age: spouseSsClaimAge,
        ss_claim_age: primarySsClaimAge,
        equity_growth_preset: equityGrowthPreset,
        spending_guardrail_mode: spendingGuardrailMode,
        growth_us_equity: curUs,
        growth_intl_equity: curIntl,
        growth_bonds: curBonds,
        growth_cash: curCash,
        growth_private_investments: curPriv,
        growth_real_estate: curRe,
    });

    const morphedStatus = document.getElementById('scen-assumptions-status');
    if (morphedStatus) {
        morphedStatus.textContent = saveAsPersistentDefault ? '✓ Recalculated and saved as Household Baseline Defaults!' : '✓ Projections updated';
        morphedStatus.style.color = 'var(--status-green)';
        setTimeout(() => { if (morphedStatus) morphedStatus.textContent = ''; }, 2500);
    }
}
