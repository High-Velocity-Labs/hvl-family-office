/**
 * static/js/scenarios/event_modals_fields.js
 * Panel visibility toggling and field synchronizers for the Event Wizard dialog.
 */

import { setSelectedEventIcon, TEMPLATE_DEFAULT_ICONS } from './event_modals_presets.js';
import { numberFrom, tierCost } from './event_modals_inputs.js';
import {
    syncCapitalOutflowFields,
    syncCapitalInflowFields,
    syncRealEstateActionFields,
    syncRenovationFields,
    syncSabbaticalFields,
    syncGradSchoolFields,
    syncPhilanthropyDafFields,
    syncStateRelocationFields,
    syncRothConversionFields,
    syncSuperfund529Fields,
    syncPeCapitalCallFields,
    syncLtcInsuranceFields,
    syncMaritalSettlementFields
} from './event_modals_syncers.js';

export {
    syncCapitalOutflowFields,
    syncCapitalInflowFields,
    syncRealEstateActionFields,
    syncRenovationFields,
    syncSabbaticalFields,
    syncGradSchoolFields,
    syncPhilanthropyDafFields,
    syncStateRelocationFields,
    syncRothConversionFields,
    syncSuperfund529Fields,
    syncPeCapitalCallFields,
    syncLtcInsuranceFields,
    syncMaritalSettlementFields
};

/** Swaps the term select's options for the server-rendered `<template>` of the product ('fixed' or 'arm'). */
function setTermOptions(select, product) {
    const tmpl = document.getElementById(`tmpl-refinance-terms-${product}`);
    select.replaceChildren(...tmpl.content.cloneNode(true).children);
}

export function syncRefinanceFields(refType = 'fixed', termVal = null, resetVal = null) {
    const termSelect = document.getElementById('select-refinance-term');
    const labelTerm = document.getElementById('label-refinance-term');
    const armResetRow = document.getElementById('row-refinance-arm-reset');
    const inputArmReset = document.getElementById('input-refinance-arm-reset');
    const inputRate = document.getElementById('input-refinance-rate');
    const inputFees = document.getElementById('input-refinance-fees');
    const inputName = document.getElementById('input-event-name');

    if (!termSelect) return;

    if (refType === 'arm') {
        if (labelTerm) labelTerm.textContent = 'Initial Fixed Period (ARM)';
        if (armResetRow) {
            armResetRow.hidden = false;
            armResetRow.classList.remove('hidden');
        }
        setTermOptions(termSelect, 'arm');
        termSelect.value = termVal ? String(termVal) : '7';
        if (inputArmReset && resetVal !== null) inputArmReset.value = resetVal;
        else if (inputArmReset) inputArmReset.value = '0.055';
        if (inputRate && !inputRate.dataset.userEdited) inputRate.value = '0.055';
        if (inputFees && !inputFees.dataset.userEdited) inputFees.value = '7500';
        if (inputName && (!inputName.value || inputName.value.startsWith('Refinance Mortgage'))) {
            inputName.value = `Refinance Mortgage (${termSelect.value}/1 ARM)`;
        }
    } else {
        if (labelTerm) labelTerm.textContent = 'New Loan Term (Fixed)';
        if (armResetRow) {
            armResetRow.hidden = true;
            armResetRow.classList.add('hidden');
        }
        setTermOptions(termSelect, 'fixed');
        termSelect.value = termVal ? String(termVal) : '30';
        if (inputRate && !inputRate.dataset.userEdited) inputRate.value = '0.060';
        if (inputFees && !inputFees.dataset.userEdited) inputFees.value = '8000';
        if (inputName && (!inputName.value || inputName.value.startsWith('Refinance Mortgage'))) {
            inputName.value = `Refinance Mortgage (${termSelect.value}-Yr Fixed)`;
        }
    }
}

export function setCollegeSourceMode(mode) {
    const btnSync = document.getElementById('btn-college-mode-sync');
    const btnOvr = document.getElementById('btn-college-mode-override');
    const panelSync = document.getElementById('panel-college-sync-details');
    const panelOvr = document.getElementById('panel-college-override-details');
    const hiddenInput = document.getElementById('input-college-sync-with-ledger');

    if (!btnSync || !btnOvr) return;

    if (mode === 'sync') {
        btnSync.classList.add('active', 'is-active-blue');
        btnOvr.classList.remove('active', 'is-active-blue');
        if (panelSync) {
            panelSync.hidden = false;
            panelSync.classList.remove('hidden');
        }
        if (panelOvr) {
            panelOvr.hidden = true;
            panelOvr.classList.add('hidden');
        }
        if (hiddenInput) hiddenInput.value = 'true';

        const selC = document.getElementById('select-college-child');
        const opt = selC?.options[selC.selectedIndex];
        if (opt) {
            const childName = opt.text.split('(')[0].trim();
            const nameInput = document.getElementById('input-event-name');
            if (nameInput) nameInput.value = `${childName}'s College Tuition (4-Yr 529 Draw)`;
            if (opt.dataset.matr) {
                const sYr = parseInt(opt.dataset.matr);
                document.getElementById('input-event-year').value = sYr;
                document.getElementById('input-event-end-year').value = sYr + 3;
            }
        }
    } else {
        btnOvr.classList.add('active', 'is-active-blue');
        btnSync.classList.remove('active', 'is-active-blue');
        if (panelSync) {
            panelSync.hidden = true;
            panelSync.classList.add('hidden');
        }
        if (panelOvr) {
            panelOvr.hidden = false;
            panelOvr.classList.remove('hidden');
        }
        if (hiddenInput) hiddenInput.value = 'false';
    }
}

export function setEduSourceMode(mode) {
    const btnSync = document.getElementById('btn-edu-mode-sync');
    const btnOvr = document.getElementById('btn-edu-mode-override');
    const panelSync = document.getElementById('panel-edu-sync-details');
    const panelOvr = document.getElementById('panel-edu-override-details');
    const hiddenInput = document.getElementById('input-edu-sync-with-ledger');

    if (!btnSync || !btnOvr) return;

    if (mode === 'sync') {
        btnSync.classList.add('active', 'is-active-blue');
        btnOvr.classList.remove('active', 'is-active-blue');
        if (panelSync) {
            panelSync.hidden = false;
            panelSync.classList.remove('hidden');
        }
        if (panelOvr) {
            panelOvr.hidden = true;
            panelOvr.classList.add('hidden');
        }
        if (hiddenInput) hiddenInput.value = 'true';

        const selC = document.getElementById('select-edu-child');
        const opt = selC?.options[selC.selectedIndex];
        if (opt) {
            const childName = opt.text.split('(')[0].trim();
            const nameInput = document.getElementById('input-event-name');
            if (nameInput) nameInput.value = `${childName}'s Private K-12 Tuition`;
        }
    } else {
        btnOvr.classList.add('active', 'is-active-blue');
        btnSync.classList.remove('active', 'is-active-blue');
        if (panelSync) {
            panelSync.hidden = true;
            panelSync.classList.add('hidden');
        }
        if (panelOvr) {
            panelOvr.hidden = false;
            panelOvr.classList.remove('hidden');
        }
        if (hiddenInput) hiddenInput.value = 'false';
    }
}

export function getWizardPanels() {
    return {
        'capital_outflow': document.getElementById('fields-capital-outflow'),
        'capital_inflow': document.getElementById('fields-capital-inflow'),
        'college': document.getElementById('fields-college'),
        'grad_school': document.getElementById('fields-grad-school'),
        'company_equity': document.getElementById('fields-company-equity'),
        'real_estate': document.getElementById('fields-real-estate'),
        'home_renovation': document.getElementById('fields-home-renovation'),
        'sabbatical': document.getElementById('fields-sabbatical'),
        'philanthropy_daf': document.getElementById('fields-philanthropy-daf'),
        'lifestyle': document.getElementById('fields-lifestyle'),
        'education': document.getElementById('fields-education'),
        'eldercare': document.getElementById('fields-eldercare'),
        'gifting': document.getElementById('fields-gifting'),
        'debt_payoff': document.getElementById('fields-debt-payoff'),
        'refinance': document.getElementById('fields-refinance'),
        'state_relocation': document.getElementById('fields-state-relocation'),
        'roth_conversion': document.getElementById('fields-roth-conversion'),
        'superfund_529': document.getElementById('fields-superfund-529'),
        'pe_capital_call': document.getElementById('fields-pe-capital-call'),
        'ltc_insurance': document.getElementById('fields-ltc-insurance'),
        'pre65_healthcare': document.getElementById('fields-pre65-healthcare'),
        'marital_settlement': document.getElementById('fields-marital-settlement'),
    };
}

/** Selects the event's amount basis: its saved value, else its category's default (set by the server in data-fixed-categories). */
export function setAmountBasis(category, savedBasis) {
    const select = document.getElementById('select-event-amount-basis');
    if (!select) return;
    const fixedCategories = (select.dataset.fixedCategories || '').split(' ');
    const categoryDefault = fixedCategories.includes(category) ? 'fixed' : 'todays_dollars';
    const saved = [...select.options].some(o => o.value === savedBasis) ? savedBasis : null;
    select.value = saved || categoryDefault;
}

export function updateWizardPanels(val) {
    setAmountBasis(val);
    const panels = getWizardPanels();
    Object.keys(panels).forEach(k => {
        if (panels[k]) {
            const isMatch = k === val;
            panels[k].hidden = !isMatch;
            panels[k].classList.toggle('hidden', !isMatch);
        }
    });

    const nameInput = document.getElementById('input-event-name');
    const amtInput = document.getElementById('input-event-amount');

    if (TEMPLATE_DEFAULT_ICONS[val]) {
        setSelectedEventIcon(TEMPLATE_DEFAULT_ICONS[val], false);
    }

    if (val === 'capital_outflow') {
        const purpose = document.getElementById('select-outflow-purpose')?.value || 'large_gift';
        syncCapitalOutflowFields(purpose);
    } else if (val === 'capital_inflow' || val === 'custom_spike') {
        const inType = document.getElementById('select-inflow-source-type')?.value || 'windfall_bonus';
        syncCapitalInflowFields(inType);
    } else if (val === 'college') {
        const selChild = document.getElementById('select-college-child');
        const childOpt = selChild?.options[selChild.selectedIndex];
        const childName = childOpt?.text?.split('(')[0]?.trim() || 'Student';
        const selTier = document.getElementById('select-college-tier');
        const tierAmt = selTier ? tierCost('select-college-tier') : null;
        if (nameInput) nameInput.value = `${childName}'s College Tuition (4-Yr 529 Draw)`;
        if (amtInput && tierAmt !== null) amtInput.value = tierAmt;
        if (childOpt && childOpt.dataset.matr) {
            const sYr = parseInt(childOpt.dataset.matr);
            document.getElementById('input-event-year').value = sYr;
            document.getElementById('input-event-end-year').value = sYr + 3;
        }
        const b529 = document.getElementById('badge-college-529-balance');
        if (b529 && childOpt && childOpt.dataset.bal) {
            b529.textContent = `529 Reserve: $${Math.round(parseFloat(childOpt.dataset.bal)).toLocaleString()}`;
        }
    } else if (val === 'grad_school') {
        const prog = document.getElementById('select-grad-program')?.value || 'mba';
        syncGradSchoolFields(prog);
    } else if (val === 'home_renovation') {
        const scope = document.getElementById('select-renovation-scope')?.value || 'kitchen_bath';
        syncRenovationFields(scope);
    } else if (val === 'sabbatical') {
        const mode = document.getElementById('select-sabbatical-mode')?.value || 'sabbatical';
        syncSabbaticalFields(mode);
    } else if (val === 'philanthropy_daf') {
        const struct = document.getElementById('select-daf-structure')?.value || 'frontload';
        syncPhilanthropyDafFields(struct);
    } else if (val === 'state_relocation') {
        syncStateRelocationFields();
    } else if (val === 'roth_conversion') {
        syncRothConversionFields();
    } else if (val === 'superfund_529') {
        syncSuperfund529Fields();
    } else if (val === 'pe_capital_call') {
        syncPeCapitalCallFields();
    } else if (val === 'ltc_insurance') {
        syncLtcInsuranceFields();
    } else if (val === 'marital_settlement') {
        syncMaritalSettlementFields();
    } else if (val === 'company_equity') {
        if (nameInput) nameInput.value = 'Stock Options Cashless Repurchase';
    } else if (val === 'real_estate') {
        const reAction = document.getElementById('select-re-action')?.value || 'buy_vacation';
        syncRealEstateActionFields(reAction);
    } else if (val === 'lifestyle') {
        if (nameInput) nameInput.value = 'Fractional Aviation Membership';
        if (amtInput) amtInput.value = '150000';
    } else if (val === 'education') {
        if (nameInput) nameInput.value = 'K-12 Private School Tuition';
        if (amtInput && tierCost('select-edu-tier') !== null) amtInput.value = tierCost('select-edu-tier');
    } else if (val === 'eldercare') {
        if (nameInput) nameInput.value = 'Elderly Parent Assisted Living Support';
        if (amtInput) amtInput.value = '35000';
    } else if (val === 'gifting') {
        if (nameInput) nameInput.value = 'Annual Family Gifting Program';
        if (amtInput) amtInput.value = '76000';
    } else if (val === 'debt_payoff') {
        if (nameInput) nameInput.value = 'Pay Off Primary Mortgage';
        if (amtInput) amtInput.value = '500000';
    } else if (val === 'refinance') {
        const refType = document.getElementById('select-refinance-type')?.value || 'fixed';
        syncRefinanceFields(refType);
        if (amtInput) amtInput.value = '8000';
    } else if (val === 'pre65_healthcare') {
        setSelectedEventIcon('evt-ltc-shield', false);
        if (nameInput) nameInput.value = 'Pre-65 Healthcare / ACA Bridge';
        const currentScen = (state.scenariosData?.scenarios || []).find(s => s.id === state.selectedScenarioId) || {};
        const pCurrentAge = state.scenariosData?.primary_current_age || 0;
        const pRetAge = currentScen.primary_retirement_age || Math.max(65, pCurrentAge);
        const curYr = state.scenariosData?.current_year || new Date().getFullYear();
        const retYear = pCurrentAge ? curYr + Math.max(0, pRetAge - pCurrentAge) : curYr;
        const age65Year = curYr + Math.max(0, 65 - pCurrentAge);
        const startYr = Math.min(retYear, age65Year);
        const endYr = Math.max(startYr, age65Year);
        const yrInput = document.getElementById('input-event-year');
        const endYrInput = document.getElementById('input-event-end-year');
        if (yrInput) yrInput.value = startYr;
        if (endYrInput) endYrInput.value = endYr;
        const premAmt = numberFrom('input-aca-annual-premium');
        if (amtInput && premAmt !== null) amtInput.value = premAmt;
    }
}
