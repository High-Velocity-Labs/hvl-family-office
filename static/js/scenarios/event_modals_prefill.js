/**
 * static/js/scenarios/event_modals_prefill.js
 * Category-specific form field population when editing an existing scenario event.
 */

import {
    setCollegeSourceMode,
    setEduSourceMode,
    syncRealEstateActionFields,
    syncRefinanceFields
} from './event_modals_fields.js';

export function prefillCategoryFields(mappedTemplate, ev) {
    if (mappedTemplate === 'capital_outflow') {
        const selPurp = document.getElementById('select-outflow-purpose');
        if (selPurp) {
            selPurp.value = ev.outflow_purpose || (ev.category !== 'capital_outflow' ? ev.category : 'large_gift');
        }
        if (ev.funding_source) {
            const selOutSource = document.getElementById('select-outflow-source');
            if (selOutSource) selOutSource.value = ev.funding_source;
        }
        if (ev.amount || ev.annual_amount) {
            document.getElementById('input-event-amount').value = ev.amount || ev.annual_amount;
        }
        return;
    }

    if (mappedTemplate === 'capital_inflow') {
        const selIn = document.getElementById('select-inflow-source-type');
        if (selIn) {
            selIn.value = ev.inflow_source_type || (ev.category !== 'capital_inflow' ? ev.category : 'windfall_bonus');
        }
        if (ev.funding_source) {
            const selInDest = document.getElementById('select-inflow-dest');
            if (selInDest) selInDest.value = ev.funding_source;
        }
        if (ev.amount || ev.annual_amount) {
            document.getElementById('input-event-amount').value = ev.amount || ev.annual_amount;
        }
        return;
    }

    if (mappedTemplate === 'college') {
        setCollegeSourceMode(ev.sync_with_ledger ? 'sync' : 'override');
        if (ev.child_user_id) {
            const selC = document.getElementById('select-college-child');
            if (selC) selC.value = String(ev.child_user_id);
        }
        const selTier = document.getElementById('select-college-tier');
        const amt = ev.annual_amount || ev.amount || 85000;
        if (selTier) {
            const knownTiers = ['35000', '75000', '85000', '95000'];
            selTier.value = knownTiers.includes(String(Math.round(amt))) ? String(Math.round(amt)) : 'custom';
        }
        const chk529 = document.getElementById('check-college-use-529');
        if (chk529) chk529.checked = (ev.use_529_reserves !== false);
        const amtInput = document.getElementById('input-event-amount');
        if (amtInput) amtInput.value = amt;

        const selC = document.getElementById('select-college-child');
        const opt = selC?.options[selC.selectedIndex];
        const b529 = document.getElementById('badge-college-529-balance');
        if (b529 && opt?.dataset?.bal) {
            b529.textContent = `529 Reserve: $${Math.round(parseFloat(opt.dataset.bal)).toLocaleString()}`;
        }
        return;
    }

    if (mappedTemplate === 'grad_school') {
        if (ev.child_user_id) {
            const selGChild = document.getElementById('select-grad-child');
            if (selGChild) selGChild.value = String(ev.child_user_id);
        }
        const selProg = document.getElementById('select-grad-program');
        if (selProg && ev.degree_program) selProg.value = ev.degree_program;
        const chkGrad529 = document.getElementById('check-grad-use-529');
        if (chkGrad529) chkGrad529.checked = (ev.use_529_reserves !== false);
        if (ev.annual_amount || ev.amount) {
            document.getElementById('input-event-amount').value = ev.annual_amount || ev.amount;
        }
        return;
    }

    if (mappedTemplate === 'home_renovation') {
        const selScope = document.getElementById('select-renovation-scope');
        if (selScope && ev.renovation_scope) selScope.value = ev.renovation_scope;
        const retInput = document.getElementById('input-renovation-retention');
        if (retInput && ev.value_retention_pct !== undefined) {
            retInput.value = Math.round(ev.value_retention_pct * 100);
        }
        document.getElementById('input-event-amount').value = ev.renovation_cost || ev.amount || ev.annual_amount || 150000;
        return;
    }

    if (mappedTemplate === 'sabbatical') {
        const selMode = document.getElementById('select-sabbatical-mode');
        if (selMode && ev.sabbatical_mode) selMode.value = ev.sabbatical_mode;
        const multInput = document.getElementById('input-sabbatical-mult');
        if (multInput && ev.income_multiplier !== undefined) {
            multInput.value = Math.round(ev.income_multiplier * 100);
        }
        document.getElementById('input-event-amount').value = ev.amount || ev.annual_amount || 0;
        return;
    }

    if (mappedTemplate === 'philanthropy_daf') {
        const selStruct = document.getElementById('select-daf-structure');
        if (selStruct && ev.daf_structure) selStruct.value = ev.daf_structure;
        const taxInput = document.getElementById('input-daf-tax-rate');
        if (taxInput && ev.tax_deduction_rate !== undefined) {
            taxInput.value = Math.round(ev.tax_deduction_rate * 100);
        }
        if (ev.amount || ev.annual_amount) {
            document.getElementById('input-event-amount').value = ev.amount || ev.annual_amount;
        }
        return;
    }

    if (mappedTemplate === 'state_relocation') {
        const selFrom = document.getElementById('select-reloc-from');
        if (selFrom && ev.from_state) selFrom.value = ev.from_state;
        const selTo = document.getElementById('select-reloc-to');
        if (selTo && ev.to_state) selTo.value = ev.to_state;
        const taxInput = document.getElementById('input-reloc-tax-savings');
        if (taxInput && ev.tax_savings_pct !== undefined) {
            taxInput.value = Number((ev.tax_savings_pct * 100).toFixed(1));
        }
        const colInput = document.getElementById('input-reloc-col-delta');
        if (colInput && ev.col_delta_pct !== undefined) {
            colInput.value = Math.round(ev.col_delta_pct * 100);
        }
        document.getElementById('input-event-amount').value = ev.moving_cost ?? ev.amount ?? 25000;
        return;
    }

    if (mappedTemplate === 'roth_conversion') {
        const amt = ev.conversion_amount || ev.annual_amount || ev.amount || 150000;
        const selPreset = document.getElementById('select-roth-preset');
        if (selPreset) {
            const knownPresets = ['100000', '150000', '250000'];
            selPreset.value = knownPresets.includes(String(Math.round(amt))) ? String(Math.round(amt)) : 'custom';
        }
        const taxInput = document.getElementById('input-roth-tax-rate');
        if (taxInput && ev.marginal_tax_rate !== undefined) {
            taxInput.value = Math.round(ev.marginal_tax_rate * 100);
        }
        const selTaxSrc = document.getElementById('select-roth-tax-source');
        if (selTaxSrc && ev.tax_payment_source) selTaxSrc.value = ev.tax_payment_source;
        document.getElementById('input-event-amount').value = amt;
        return;
    }

    if (mappedTemplate === 'superfund_529') {
        if (ev.child_user_id) {
            const selSfChild = document.getElementById('select-superfund-child');
            if (selSfChild) selSfChild.value = String(ev.child_user_id);
        }
        const selSfTier = document.getElementById('select-superfund-tier');
        if (selSfTier && ev.superfund_tier) selSfTier.value = ev.superfund_tier;
        const sfYrs = document.getElementById('input-superfund-years');
        if (sfYrs && ev.gift_tax_split_years) sfYrs.value = ev.gift_tax_split_years;
        document.getElementById('input-event-amount').value = ev.amount || ev.annual_amount || 380000;
        return;
    }

    if (mappedTemplate === 'pe_capital_call') {
        const commEl = document.getElementById('input-pe-commitment');
        if (commEl && ev.total_commitment) commEl.value = ev.total_commitment;
        const tvpiEl = document.getElementById('input-pe-tvpi');
        if (tvpiEl && ev.target_tvpi) tvpiEl.value = ev.target_tvpi;
        const distYrEl = document.getElementById('input-pe-dist-year');
        if (distYrEl && ev.distribution_start_year) distYrEl.value = ev.distribution_start_year;
        const distDurEl = document.getElementById('input-pe-dist-duration');
        if (distDurEl && ev.distribution_duration_years) distDurEl.value = ev.distribution_duration_years;
        document.getElementById('input-event-amount').value = ev.annual_call_amount || ev.annual_amount || ev.amount || 100000;
        return;
    }

    if (mappedTemplate === 'ltc_insurance') {
        const benEl = document.getElementById('input-ltc-monthly-benefit');
        if (benEl && ev.monthly_benefit_cap) benEl.value = ev.monthly_benefit_cap;
        const poolEl = document.getElementById('input-ltc-pool-years');
        if (poolEl && ev.benefit_pool_years) poolEl.value = ev.benefit_pool_years;
        const infEl = document.getElementById('select-ltc-inflation');
        if (infEl && ev.inflation_protection) infEl.value = ev.inflation_protection;
        document.getElementById('input-event-amount').value = ev.annual_premium || ev.annual_amount || ev.amount || 25000;
        return;
    }

    if (mappedTemplate === 'marital_settlement') {
        const splitEl = document.getElementById('input-settlement-split-pct');
        if (splitEl && ev.asset_split_pct !== undefined) splitEl.value = Math.round(ev.asset_split_pct * 100);
        const feeEl = document.getElementById('input-settlement-legal-fee');
        if (feeEl && ev.legal_settlement_cost !== undefined) feeEl.value = ev.legal_settlement_cost;
        const alimYrsEl = document.getElementById('input-settlement-alimony-years');
        if (alimYrsEl && ev.alimony_duration_years) alimYrsEl.value = ev.alimony_duration_years;
        document.getElementById('input-event-amount').value = ev.annual_alimony ?? ev.annual_amount ?? ev.amount ?? 75000;
        return;
    }

    if (mappedTemplate === 'education') {
        setEduSourceMode(ev.sync_with_ledger !== false ? 'sync' : 'override');
        if (ev.child_user_id) {
            const selEdu = document.getElementById('select-edu-child');
            if (selEdu) selEdu.value = String(ev.child_user_id);
        }
        const chk529K12 = document.getElementById('check-edu-use-529');
        if (chk529K12) chk529K12.checked = (ev.use_529_k12_election !== false);
        if (ev.annual_amount || ev.amount) {
            document.getElementById('input-event-amount').value = ev.annual_amount || ev.amount;
        }
        return;
    }

    if (mappedTemplate === 'company_equity') {
        if (ev.grant_id) {
            const selG = document.getElementById('select-equity-grant');
            if (selG) selG.value = ev.grant_id;
        }
        if (ev.options_quantity) document.getElementById('input-equity-quantity').value = ev.options_quantity;
        if (ev.action) document.getElementById('select-equity-action').value = ev.action;
        if (ev.reinvestment_strategy) document.getElementById('select-equity-reinvest').value = ev.reinvestment_strategy;
        return;
    }

    if (mappedTemplate === 'real_estate') {
        const reAction = ev.re_action || (ev.category === 'home_sale' ? 'downsize' : 'buy_vacation');
        const selReAct = document.getElementById('select-re-action');
        if (selReAct) selReAct.value = reAction;
        syncRealEstateActionFields(reAction);
        document.getElementById('input-event-name').value = ev.name;
        if (reAction === 'downsize') {
            const proceeds = ev.sale_proceeds || ev.net_proceeds || ev.amount || 1200000;
            document.getElementById('input-re-price').value = proceeds;
            document.getElementById('input-event-amount').value = proceeds;
        } else {
            if (ev.purchase_price) document.getElementById('input-re-price').value = ev.purchase_price;
            if (ev.down_payment_pct) document.getElementById('input-re-down-pct').value = Math.round(ev.down_payment_pct * 100);
            if (ev.annual_ongoing_carrying_cost) {
                document.getElementById('input-re-carrying-cost').value = ev.annual_ongoing_carrying_cost;
            }
        }
        return;
    }

    if (mappedTemplate === 'lifestyle') {
        if (ev.annual_amount) document.getElementById('input-lifestyle-amount').value = ev.annual_amount;
    } else if (mappedTemplate === 'debt_payoff') {
        if (ev.amount) document.getElementById('input-event-amount').value = ev.amount;
    } else if (mappedTemplate === 'gifting') {
        if (ev.annual_amount) document.getElementById('input-gifting-amt-per').value = Math.round(ev.annual_amount / 2);
    } else if (mappedTemplate === 'refinance') {
        const refType = ev.refinance_type || (ev.arm_fixed_years ? 'arm' : 'fixed');
        const selType = document.getElementById('select-refinance-type');
        if (selType) selType.value = refType;
        const termVal = refType === 'arm' ? (ev.arm_fixed_years || 7) : (ev.new_term_years || 30);
        syncRefinanceFields(refType, termVal, ev.arm_reset_rate || 0.055);
        if (ev.new_interest_rate) document.getElementById('input-refinance-rate').value = ev.new_interest_rate;
        if (ev.closing_costs) document.getElementById('input-refinance-fees').value = ev.closing_costs;
    } else if (ev.annual_amount || ev.amount) {
        document.getElementById('input-event-amount').value = ev.annual_amount || ev.amount;
    }
}
