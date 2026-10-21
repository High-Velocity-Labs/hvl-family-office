/**
 * static/js/scenarios/controls_sliders.js
 * Quick assumption presets, sliders, asset growth inputs, and save-button state.
 */

import { state } from './state.js';
import { applyQuickAssumptions } from './controls_events.js';

let currentPlanSavedAssumptions = null;

export function parseAssetRateInput(id, fallback = 0.05) {
    const el = document.getElementById(id);
    if (!el || el.value === '' || el.value === null) return fallback;
    const val = parseFloat(el.value);
    if (isNaN(val)) return fallback;
    return val > 1.0 ? val / 100.0 : val;
}

export function bindScenSpendPresetButtons() {
    document.querySelectorAll('.btn-scen-spend-preset').forEach(btn => {
        btn.onclick = () => {
            document.querySelectorAll('.btn-scen-spend-preset').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const spend = btn.getAttribute('data-spend');
            const spendInput = document.getElementById('scen-input-living-spend');
            if (spendInput) spendInput.value = spend;
            updateSaveButtonState();
            applyQuickAssumptions(false);
        };
    });
}

export function bindScenSavingsPresetButtons() {
    document.querySelectorAll('.btn-scen-savings-preset').forEach(btn => {
        btn.onclick = () => {
            document.querySelectorAll('.btn-scen-savings-preset').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const savings = btn.getAttribute('data-savings');
            const savingsInput = document.getElementById('scen-input-annual-savings');
            if (savingsInput) savingsInput.value = savings;
            updateSaveButtonState();
            applyQuickAssumptions(false);
        };
    });
}

export function updateSaveButtonState() {
    const btnSave = document.getElementById('btn-save-to-plan');
    if (!btnSave) return;
    const elPri = document.getElementById('scen-input-primary-ret-age');
    const elSpouse = document.getElementById('scen-input-spouse-ret-age');
    const elSpend = document.getElementById('scen-input-living-spend');
    const elSavings = document.getElementById('scen-input-annual-savings');
    const elInflation = document.getElementById('scen-input-inflation');

    const curPri = parseInt(elPri?.value || 0);
    const curSpouse = parseInt(elSpouse?.value || 0);
    const curSpend = parseFloat(elSpend?.value || 0);
    const curSavings = parseFloat(elSavings?.value || 0);
    const curInflation = parseFloat(elInflation?.value || 0);

    const activePriSsBtn = document.querySelector('.btn-scen-primary-ss-age.active') || document.querySelector('.btn-scen-ss-age.active');
    const curPriSsAge = activePriSsBtn ? parseInt(activePriSsBtn.getAttribute('data-age') || 67) : 67;

    const activeSpouseSsBtn = document.querySelector('.btn-scen-spouse-ss-age.active');
    const curSpouseSsAge = activeSpouseSsBtn ? parseInt(activeSpouseSsBtn.getAttribute('data-age') || 67) : curPriSsAge;

    const selectGrowth = document.getElementById('select-scenario-inline-growth');
    const curGrowth = selectGrowth?.value || 'moderate';

    const curUs = parseAssetRateInput('scen-growth-us-equity', 0.085);
    const curIntl = parseAssetRateInput('scen-growth-intl-equity', 0.070);
    const curBonds = parseAssetRateInput('scen-growth-bonds', 0.045);
    const curCash = parseAssetRateInput('scen-growth-cash', 0.035);
    const curPriv = parseAssetRateInput('scen-growth-private', 0.100);
    const curRe = parseAssetRateInput('scen-growth-real-estate', 0.035);

    const elGuardrails = document.getElementById('scen-input-spending-guardrails');
    const curGuardrails = elGuardrails?.value || 'off';

    const hasChanged = Boolean(
        currentPlanSavedAssumptions && (
            curPri !== currentPlanSavedAssumptions.primary_ret_age ||
            curSpouse !== currentPlanSavedAssumptions.spouse_ret_age ||
            curSpend !== currentPlanSavedAssumptions.living_spend ||
            curSavings !== currentPlanSavedAssumptions.annual_savings ||
            Math.abs(curInflation - currentPlanSavedAssumptions.inflation) > 0.0001 ||
            curPriSsAge !== (currentPlanSavedAssumptions.primary_ss_claim_age ?? currentPlanSavedAssumptions.ss_claim_age) ||
            curSpouseSsAge !== (currentPlanSavedAssumptions.spouse_ss_claim_age ?? currentPlanSavedAssumptions.ss_claim_age) ||
            curGrowth !== currentPlanSavedAssumptions.equity_growth_preset ||
            curGuardrails !== (currentPlanSavedAssumptions.spending_guardrail_mode ?? 'off') ||
            Math.abs(curUs - (currentPlanSavedAssumptions.growth_us_equity ?? 0.085)) > 0.0001 ||
            Math.abs(curIntl - (currentPlanSavedAssumptions.growth_intl_equity ?? 0.070)) > 0.0001 ||
            Math.abs(curBonds - (currentPlanSavedAssumptions.growth_bonds ?? 0.045)) > 0.0001 ||
            Math.abs(curCash - (currentPlanSavedAssumptions.growth_cash ?? 0.035)) > 0.0001 ||
            Math.abs(curPriv - (currentPlanSavedAssumptions.growth_private_investments ?? 0.100)) > 0.0001 ||
            Math.abs(curRe - (currentPlanSavedAssumptions.growth_real_estate ?? 0.035)) > 0.0001
        )
    );

    btnSave.disabled = !hasChanged;
    if (hasChanged) {
        btnSave.style.opacity = '1';
        btnSave.style.cursor = 'pointer';
        btnSave.title = 'Save modifications to the selected plan';
    } else {
        btnSave.style.opacity = '0.5';
        btnSave.style.cursor = 'not-allowed';
        btnSave.title = 'No changes to save';
    }
}

export function initAssetGrowthControls() {
    const btnToggle = document.getElementById('btn-toggle-asset-growth') || document.getElementById('btn-toggle-advanced-assumptions');
    const body = document.getElementById('asset-growth-body');
    const txtToggle = document.getElementById('txt-toggle-asset-growth') || document.getElementById('txt-toggle-advanced-assumptions');

    if (btnToggle && body) {
        const isExpanded = localStorage.getItem('scen_asset_growth_expanded') === 'true';
        body.style.display = isExpanded ? 'block' : 'none';
        if (txtToggle) txtToggle.textContent = isExpanded ? '▲ Advanced Levers' : '▼ Advanced Levers';
        btnToggle.classList.toggle('active', isExpanded);

        btnToggle.onclick = () => {
            const curBody = document.getElementById('asset-growth-body');
            const curTxt = document.getElementById('txt-toggle-asset-growth') || document.getElementById('txt-toggle-advanced-assumptions');
            if (!curBody) return;
            const hidden = curBody.style.display === 'none';
            curBody.style.display = hidden ? 'block' : 'none';
            if (curTxt) curTxt.textContent = hidden ? '▲ Advanced Levers' : '▼ Advanced Levers';
            btnToggle.classList.toggle('active', hidden);
            localStorage.setItem('scen_asset_growth_expanded', hidden ? 'true' : 'false');
        };
    }

    const elInflation = document.getElementById('scen-input-inflation');
    if (elInflation && !elInflation._wired) {
        elInflation._wired = true;
        elInflation.addEventListener('input', () => {
            const infVal = parseFloat(elInflation.value || 0.025);
            const badgeInf = document.getElementById('badge-adv-inflation');
            if (badgeInf) badgeInf.textContent = `Inflation: ${(infVal * 100).toFixed(1)}%`;
            updateSaveButtonState();
        });
        elInflation.addEventListener('change', () => {
            updateSaveButtonState();
            applyQuickAssumptions(false);
        });
        elInflation.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                elInflation.blur();
            }
        });
    }

    const assetRateIds = [
        'scen-growth-us-equity',
        'scen-growth-intl-equity',
        'scen-growth-bonds',
        'scen-growth-cash',
        'scen-growth-private',
        'scen-growth-real-estate'
    ];

    const marketPresets = {
        baseline: { 'scen-growth-us-equity': '8.5', 'scen-growth-intl-equity': '7.0', 'scen-growth-bonds': '4.5', 'scen-growth-cash': '3.5', 'scen-growth-private': '10.0', 'scen-growth-real-estate': '3.5' },
        conservative: { 'scen-growth-us-equity': '6.5', 'scen-growth-intl-equity': '5.5', 'scen-growth-bonds': '4.0', 'scen-growth-cash': '3.0', 'scen-growth-private': '7.5', 'scen-growth-real-estate': '2.5' },
        aggressive: { 'scen-growth-us-equity': '10.0', 'scen-growth-intl-equity': '8.5', 'scen-growth-bonds': '5.0', 'scen-growth-cash': '4.0', 'scen-growth-private': '12.5', 'scen-growth-real-estate': '4.5' }
    };

    const btnCustomRates = document.getElementById('btn-toggle-custom-asset-rates');
    const groupedContainer = document.getElementById('asset-growth-grouped-container');
    if (btnCustomRates && groupedContainer && !btnCustomRates._wired) {
        btnCustomRates._wired = true;
        btnCustomRates.addEventListener('click', () => {
            const cur = document.getElementById('asset-growth-grouped-container');
            if (!cur) return;
            const isHidden = cur.style.display === 'none';
            cur.style.display = isHidden ? 'grid' : 'none';
            btnCustomRates.innerHTML = isHidden ? 'Hide Individual Asset-Class Returns' : '<svg class="icon icon-sm" aria-hidden="true"><use href="/common/icons.svg#icon-settings"></use></svg> Fine-Tune 6 Asset-Class Returns';
        });
    }

    const selectMktProfile = document.getElementById('select-scen-market-profile');
    if (selectMktProfile && !selectMktProfile._wired) {
        selectMktProfile._wired = true;
        selectMktProfile.addEventListener('change', () => {
            const val = selectMktProfile.value || 'baseline';
            const curGrouped = document.getElementById('asset-growth-grouped-container');
            const curBtn = document.getElementById('btn-toggle-custom-asset-rates');
            if (val === 'custom') {
                if (curGrouped) curGrouped.style.display = 'grid';
                if (curBtn) curBtn.innerHTML = 'Hide Individual Asset-Class Returns';
                return;
            }
            const presetVals = marketPresets[val];
            if (presetVals) {
                Object.entries(presetVals).forEach(([id, rVal]) => {
                    const inputEl = document.getElementById(id);
                    if (inputEl) {
                        inputEl.value = rVal;
                        inputEl.dataset.userChanged = 'true';
                    }
                });
                updateSaveButtonState();
                applyQuickAssumptions(false);
            }
        });
    }

    assetRateIds.forEach(id => {
        const el = document.getElementById(id);
        if (el && !el._wired) {
            el._wired = true;
            el.addEventListener('input', () => {
                el.dataset.userChanged = 'true';
                const selMkt = document.getElementById('select-scen-market-profile');
                if (selMkt) selMkt.value = 'custom';
                updateSaveButtonState();
            });
            el.addEventListener('change', () => {
                el.dataset.userChanged = 'true';
                const selMkt = document.getElementById('select-scen-market-profile');
                if (selMkt) selMkt.value = 'custom';
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

    const selectInline = document.getElementById('select-scenario-inline-growth');
    if (selectInline && !selectInline._wired) {
        selectInline._wired = true;
        selectInline.addEventListener('change', () => {
            selectInline.dataset.userChanged = 'true';
            updateSaveButtonState();
            applyQuickAssumptions();
        });
    }

    const elGuardrails = document.getElementById('scen-input-spending-guardrails');
    if (elGuardrails && !elGuardrails._wired) {
        elGuardrails._wired = true;
        elGuardrails.addEventListener('change', () => {
            elGuardrails.dataset.userChanged = 'true';
            const gVal = elGuardrails.value || 'off';
            const badgeG = document.getElementById('badge-spending-guardrails');
            if (badgeG) {
                const labelMap = { off: 'Off', moderate: 'Moderate (-15%)', aggressive: 'Aggressive (-25%)' };
                badgeG.textContent = `Guardrails: ${labelMap[gVal] || gVal}`;
                badgeG.className = `badge ${gVal === 'off' ? 'badge-blue' : 'badge-orange'}`;
            }
            const currentScen = (state.scenariosData?.scenarios || []).find(s => s.id === state.selectedScenarioId)
                || (state.scenariosData?.scenarios || []).find(s => s.id === state.scenariosData?.active_scenario_id);
            if (currentScen) {
                currentScen.spending_guardrail_mode = gVal;
            }
            updateSaveButtonState();
            applyQuickAssumptions(false);
        });
    }
}

export function syncAssumptionInputs(data) {
    if (!data) return;
    const pName = (data.primary_name || 'Primary').toUpperCase();
    const sName = (data.spouse_name || 'Spouse').toUpperCase();

    const pCurrentAge = data.primary_current_age || 49;
    const sCurrentAge = data.spouse_current_age || 47;

    const scenarios = data.scenarios || [];
    const currentScen = scenarios.find(s => s.id === state.selectedScenarioId)
        || scenarios.find(s => s.id === data.selected_scenario_id)
        || scenarios.find(s => s.id === data.active_scenario_id)
        || scenarios[0] || {};

    const modalLblPri = document.getElementById('modal-label-scen-ret-primary');
    if (modalLblPri) modalLblPri.textContent = `${pName} RETIREMENT AGE`;
    const modalLblSpouse = document.getElementById('modal-label-scen-ret-spouse');
    if (modalLblSpouse) modalLblSpouse.textContent = `${sName} RETIREMENT AGE`;

    const elPri = document.getElementById('scen-input-primary-ret-age');
    if (elPri) elPri.min = pCurrentAge;
    const elSpouse = document.getElementById('scen-input-spouse-ret-age');
    if (elSpouse) elSpouse.min = sCurrentAge;

    const modalElPri = document.getElementById('input-scenario-ret-age');
    if (modalElPri) modalElPri.min = pCurrentAge;
    const modalElSpouse = document.getElementById('input-scenario-ret-spouse');
    if (modalElSpouse) modalElSpouse.min = sCurrentAge;

    bindScenSpendPresetButtons();
    bindScenSavingsPresetButtons();

    const curPriSsAge = parseInt(currentScen.primary_ss_claim_age || currentScen.ss_claim_age || data.primary_ss_claim_age || data.ss_claim_age || 67);
    const curSpouseSsAge = parseInt(currentScen.spouse_ss_claim_age || currentScen.ss_claim_age || data.spouse_ss_claim_age || data.ss_claim_age || 67);
    const curGrowthPreset = currentScen.equity_growth_preset || data.equity_growth_preset || 'moderate';
    const curGuardrails = currentScen.spending_guardrail_mode || data.spending_guardrail_mode || 'off';

    const elSpendAssump = document.getElementById('scen-input-living-spend');
    const elSavingsAssump = document.getElementById('scen-input-annual-savings');
    const elInflationAssump = document.getElementById('scen-input-inflation');

    const elGuardrailsInput = document.getElementById('scen-input-spending-guardrails');
    if (elGuardrailsInput) elGuardrailsInput.value = curGuardrails;
    const badgeG = document.getElementById('badge-spending-guardrails');
    if (badgeG) {
        const labelMap = { off: 'Off', moderate: 'Moderate (-15%)', aggressive: 'Aggressive (-25%)' };
        badgeG.textContent = `Guardrails: ${labelMap[curGuardrails] || curGuardrails}`;
        badgeG.className = `badge ${curGuardrails === 'off' ? 'badge-blue' : 'badge-orange'}`;
    }

    const valUs = (currentScen.growth_us_equity !== undefined && currentScen.growth_us_equity !== null)
        ? currentScen.growth_us_equity : (data.growth_us_equity || 0.085);
    const valIntl = (currentScen.growth_intl_equity !== undefined && currentScen.growth_intl_equity !== null)
        ? currentScen.growth_intl_equity : (data.growth_intl_equity || 0.070);
    const valBonds = (currentScen.growth_bonds !== undefined && currentScen.growth_bonds !== null)
        ? currentScen.growth_bonds : (data.growth_bonds || 0.045);
    const valCash = (currentScen.growth_cash !== undefined && currentScen.growth_cash !== null)
        ? currentScen.growth_cash : (data.growth_cash || 0.035);
    const valPriv = (currentScen.growth_private_investments !== undefined && currentScen.growth_private_investments !== null)
        ? currentScen.growth_private_investments : (data.growth_private_investments || 0.100);
    const valRe = (currentScen.growth_real_estate !== undefined && currentScen.growth_real_estate !== null)
        ? currentScen.growth_real_estate : (data.growth_real_estate || 0.035);

    const basePriAge = currentScen.primary_retirement_age || (data.primary_current_age ? data.primary_current_age + 5 : 65);
    const baseSpouseAge = currentScen.spouse_retirement_age || (data.spouse_current_age ? data.spouse_current_age + 5 : 65);
    const baseLiving = currentScen.annual_living_spend || data.annual_living_spend || 0;
    const baseSavings = currentScen.annual_savings || data.annual_savings || 0;

    if (!currentPlanSavedAssumptions || currentPlanSavedAssumptions.scenario_id !== currentScen.id || (typeof window !== 'undefined' && window._scenForceSyncSavedAssumptions)) {
        if (typeof window !== 'undefined') window._scenForceSyncSavedAssumptions = false;
        currentPlanSavedAssumptions = {
            scenario_id: currentScen.id,
            primary_ret_age: parseInt(elPri ? elPri.value : basePriAge) || basePriAge,
            spouse_ret_age: parseInt(elSpouse ? elSpouse.value : baseSpouseAge) || baseSpouseAge,
            living_spend: parseFloat(elSpendAssump ? elSpendAssump.value : baseLiving) || baseLiving,
            annual_savings: parseFloat(elSavingsAssump ? elSavingsAssump.value : baseSavings) || baseSavings,
            inflation: parseFloat(elInflationAssump ? elInflationAssump.value : 0.025) || 0.025,
            primary_ss_claim_age: curPriSsAge,
            spouse_ss_claim_age: curSpouseSsAge,
            ss_claim_age: curPriSsAge,
            equity_growth_preset: curGrowthPreset,
            spending_guardrail_mode: curGuardrails,
            growth_us_equity: valUs,
            growth_intl_equity: valIntl,
            growth_bonds: valBonds,
            growth_cash: valCash,
            growth_private_investments: valPriv,
            growth_real_estate: valRe,
        };
    }

    updateSaveButtonState();
}
