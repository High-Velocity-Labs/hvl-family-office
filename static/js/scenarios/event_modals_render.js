/**
 * static/js/scenarios/event_modals_render.js
 * Edit event form pre-fill and dynamic dropdown population.
 */

import { state } from './state.js';
import {
    filterWizardTemplateOptions,
    renderEventIconPickerGrid,
    setSelectedEventIcon,
    TEMPLATE_DEFAULT_ICONS
} from './event_modals_presets.js';
import {
    getWizardPanels,
    setCollegeSourceMode,
    setEduSourceMode,
    syncRealEstateActionFields,
    syncRefinanceFields
} from './event_modals_fields.js';
import { cloneEvent } from './event_modals_catalog.js';

let cachedFamilyMembers = [];
let cachedGrants = [];

export async function populateWizardDynamicDropdowns() {
    try {
        if (!cachedGrants || !cachedGrants.length) {
            const resp = await fetch('/api/equity/grants');
            const data = await resp.json();
            if (data.success && data.grants) cachedGrants = data.grants;
        }
        const selGrant = document.getElementById('select-equity-grant');
        if (selGrant && cachedGrants) {
            selGrant.innerHTML = '<option value="ALL">All Available Vested Grants</option>';
            cachedGrants.forEach(g => {
                const label = `${g.grant_label || g.nickname} (Vested: ${(g.unexercised_vested || 0).toLocaleString()} @ $${g.strike_price})`;
                const opt = document.createElement('option');
                opt.value = g.grant_id || g.grant_label;
                opt.textContent = label;
                selGrant.appendChild(opt);
            });
        }

        if (!cachedFamilyMembers || !cachedFamilyMembers.length) {
            const resp = await fetch('/api/family');
            const data = await resp.json();
            if (data.success && data.members) cachedFamilyMembers = data.members;
        }

        const selChild = document.getElementById('select-edu-child');
        const selGradChild = document.getElementById('select-grad-child');
        const selSuperfundChild = document.getElementById('select-superfund-child');
        if ((selChild || selGradChild || selSuperfundChild) && cachedFamilyMembers) {
            const children = cachedFamilyMembers.filter(m => m.relationship === 'child');
            [selChild, selGradChild, selSuperfundChild].forEach(sel => {
                if (!sel) return;
                sel.innerHTML = '';
                if (children.length) {
                    children.forEach(c => {
                        const opt = document.createElement('option');
                        opt.value = c.id || c.name;
                        opt.textContent = `${c.name} (Born ${c.birthdate || 'N/A'})`;
                        sel.appendChild(opt);
                    });
                } else {
                    sel.innerHTML = '<option value="child_1">Child Beneficiary</option>';
                }
            });
        }

        const selParent = document.getElementById('select-eldercare-parent');
        if (selParent && cachedFamilyMembers) {
            selParent.innerHTML = '';
            const parents = cachedFamilyMembers.filter(m => ['parent', 'dependent', 'relative'].includes(m.relationship));
            if (parents.length) {
                parents.forEach(p => {
                    const opt = document.createElement('option');
                    opt.value = p.id || p.name;
                    opt.textContent = `${p.name} (${p.relationship})`;
                    selParent.appendChild(opt);
                });
            } else {
                selParent.innerHTML = '<option value="parent_1">Parent / Dependent</option>';
            }
        }

        const selCollegeChild = document.getElementById('select-college-child');
        if (selCollegeChild) {
            try {
                const resp = await fetch('/api/college');
                const colData = await resp.json();
                if (colData && colData.children && colData.children.length) {
                    selCollegeChild.innerHTML = '';
                    colData.children.forEach(c => {
                        const opt = document.createElement('option');
                        opt.value = c.user_id;
                        opt.dataset.matr = c.college_matriculation_year || (c.birthdate ? (parseInt(c.birthdate.split('-')[0]) + 18) : 2029);
                        opt.dataset.bal = c.current_529_balance || 0;
                        opt.textContent = `${c.name} (College: ${opt.dataset.matr}, 529: $${Math.round((c.current_529_balance || 0)/1000)}k)`;
                        selCollegeChild.appendChild(opt);
                    });
                    const firstOpt = selCollegeChild.options[0];
                    const b529 = document.getElementById('badge-college-529-balance');
                    if (b529 && firstOpt && firstOpt.dataset.bal) {
                        b529.textContent = `529 Reserve: $${Math.round(parseFloat(firstOpt.dataset.bal)).toLocaleString()}`;
                    }
                }
            } catch (e) {
                console.warn('Could not load college children data:', e);
            }
        }
    } catch (e) {
        console.warn('Could not populate dynamic wizard selectors:', e);
    }
}

function prefillCategoryFields(mappedTemplate, ev) {
    if (mappedTemplate === 'capital_outflow') {
        const selPurp = document.getElementById('select-outflow-purpose');
        if (selPurp) selPurp.value = ev.outflow_purpose || (ev.category !== 'capital_outflow' ? ev.category : 'large_gift');
        if (ev.funding_source) {
            const selOutSource = document.getElementById('select-outflow-source');
            if (selOutSource) selOutSource.value = ev.funding_source;
        }
        if (ev.amount || ev.annual_amount) {
            document.getElementById('input-event-amount').value = ev.amount || ev.annual_amount;
        }
    } else if (mappedTemplate === 'capital_inflow') {
        const selIn = document.getElementById('select-inflow-source-type');
        if (selIn) selIn.value = ev.inflow_source_type || (ev.category !== 'capital_inflow' ? ev.category : 'windfall_bonus');
        if (ev.funding_source) {
            const selInDest = document.getElementById('select-inflow-dest');
            if (selInDest) selInDest.value = ev.funding_source;
        }
        if (ev.amount || ev.annual_amount) {
            document.getElementById('input-event-amount').value = ev.amount || ev.annual_amount;
        }
    } else if (mappedTemplate === 'college') {
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
    } else if (mappedTemplate === 'grad_school') {
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
    } else if (mappedTemplate === 'home_renovation') {
        const selScope = document.getElementById('select-renovation-scope');
        if (selScope && ev.renovation_scope) selScope.value = ev.renovation_scope;
        const retInput = document.getElementById('input-renovation-retention');
        if (retInput && ev.value_retention_pct !== undefined) retInput.value = Math.round(ev.value_retention_pct * 100);
        document.getElementById('input-event-amount').value = ev.renovation_cost || ev.amount || ev.annual_amount || 150000;
    } else if (mappedTemplate === 'sabbatical') {
        const selMode = document.getElementById('select-sabbatical-mode');
        if (selMode && ev.sabbatical_mode) selMode.value = ev.sabbatical_mode;
        const multInput = document.getElementById('input-sabbatical-mult');
        if (multInput && ev.income_multiplier !== undefined) multInput.value = Math.round(ev.income_multiplier * 100);
        document.getElementById('input-event-amount').value = ev.amount || ev.annual_amount || 0;
    } else if (mappedTemplate === 'philanthropy_daf') {
        const selStruct = document.getElementById('select-daf-structure');
        if (selStruct && ev.daf_structure) selStruct.value = ev.daf_structure;
        const taxInput = document.getElementById('input-daf-tax-rate');
        if (taxInput && ev.tax_deduction_rate !== undefined) taxInput.value = Math.round(ev.tax_deduction_rate * 100);
        if (ev.amount || ev.annual_amount) document.getElementById('input-event-amount').value = ev.amount || ev.annual_amount;
    } else if (mappedTemplate === 'state_relocation') {
        const selFrom = document.getElementById('select-reloc-from');
        if (selFrom && ev.from_state) selFrom.value = ev.from_state;
        const selTo = document.getElementById('select-reloc-to');
        if (selTo && ev.to_state) selTo.value = ev.to_state;
        const taxInput = document.getElementById('input-reloc-tax-savings');
        if (taxInput && ev.tax_savings_pct !== undefined) taxInput.value = Number((ev.tax_savings_pct * 100).toFixed(1));
        const colInput = document.getElementById('input-reloc-col-delta');
        if (colInput && ev.col_delta_pct !== undefined) colInput.value = Math.round(ev.col_delta_pct * 100);
        document.getElementById('input-event-amount').value = ev.moving_cost ?? ev.amount ?? 25000;
    } else if (mappedTemplate === 'roth_conversion') {
        const amt = ev.conversion_amount || ev.annual_amount || ev.amount || 150000;
        const selPreset = document.getElementById('select-roth-preset');
        if (selPreset) {
            const knownPresets = ['100000', '150000', '250000'];
            selPreset.value = knownPresets.includes(String(Math.round(amt))) ? String(Math.round(amt)) : 'custom';
        }
        const taxInput = document.getElementById('input-roth-tax-rate');
        if (taxInput && ev.marginal_tax_rate !== undefined) taxInput.value = Math.round(ev.marginal_tax_rate * 100);
        const selTaxSrc = document.getElementById('select-roth-tax-source');
        if (selTaxSrc && ev.tax_payment_source) selTaxSrc.value = ev.tax_payment_source;
        document.getElementById('input-event-amount').value = amt;
    } else if (mappedTemplate === 'superfund_529') {
        if (ev.child_user_id) {
            const selSfChild = document.getElementById('select-superfund-child');
            if (selSfChild) selSfChild.value = String(ev.child_user_id);
        }
        const selSfTier = document.getElementById('select-superfund-tier');
        if (selSfTier && ev.superfund_tier) selSfTier.value = ev.superfund_tier;
        const sfYrs = document.getElementById('input-superfund-years');
        if (sfYrs && ev.gift_tax_split_years) sfYrs.value = ev.gift_tax_split_years;
        document.getElementById('input-event-amount').value = ev.amount || ev.annual_amount || 380000;
    } else if (mappedTemplate === 'pe_capital_call') {
        const commEl = document.getElementById('input-pe-commitment');
        if (commEl && ev.total_commitment) commEl.value = ev.total_commitment;
        const tvpiEl = document.getElementById('input-pe-tvpi');
        if (tvpiEl && ev.target_tvpi) tvpiEl.value = ev.target_tvpi;
        const distYrEl = document.getElementById('input-pe-dist-year');
        if (distYrEl && ev.distribution_start_year) distYrEl.value = ev.distribution_start_year;
        const distDurEl = document.getElementById('input-pe-dist-duration');
        if (distDurEl && ev.distribution_duration_years) distDurEl.value = ev.distribution_duration_years;
        document.getElementById('input-event-amount').value = ev.annual_call_amount || ev.annual_amount || ev.amount || 100000;
    } else if (mappedTemplate === 'ltc_insurance') {
        const benEl = document.getElementById('input-ltc-monthly-benefit');
        if (benEl && ev.monthly_benefit_cap) benEl.value = ev.monthly_benefit_cap;
        const poolEl = document.getElementById('input-ltc-pool-years');
        if (poolEl && ev.benefit_pool_years) poolEl.value = ev.benefit_pool_years;
        const infEl = document.getElementById('select-ltc-inflation');
        if (infEl && ev.inflation_protection) infEl.value = ev.inflation_protection;
        document.getElementById('input-event-amount').value = ev.annual_premium || ev.annual_amount || ev.amount || 25000;
    } else if (mappedTemplate === 'marital_settlement') {
        const splitEl = document.getElementById('input-settlement-split-pct');
        if (splitEl && ev.asset_split_pct !== undefined) splitEl.value = Math.round(ev.asset_split_pct * 100);
        const feeEl = document.getElementById('input-settlement-legal-fee');
        if (feeEl && ev.legal_settlement_cost !== undefined) feeEl.value = ev.legal_settlement_cost;
        const alimYrsEl = document.getElementById('input-settlement-alimony-years');
        if (alimYrsEl && ev.alimony_duration_years) alimYrsEl.value = ev.alimony_duration_years;
        document.getElementById('input-event-amount').value = ev.annual_alimony ?? ev.annual_amount ?? ev.amount ?? 75000;
    } else if (mappedTemplate === 'education') {
        setEduSourceMode(ev.sync_with_ledger !== false ? 'sync' : 'override');
        if (ev.child_user_id) {
            const selEdu = document.getElementById('select-edu-child');
            if (selEdu) selEdu.value = String(ev.child_user_id);
        }
        const chk529K12 = document.getElementById('check-edu-use-529');
        if (chk529K12) chk529K12.checked = (ev.use_529_k12_election !== false);
        if (ev.annual_amount || ev.amount) document.getElementById('input-event-amount').value = ev.annual_amount || ev.amount;
    } else if (mappedTemplate === 'company_equity') {
        if (ev.grant_id) {
            const selG = document.getElementById('select-equity-grant');
            if (selG) selG.value = ev.grant_id;
        }
        if (ev.options_quantity) document.getElementById('input-equity-quantity').value = ev.options_quantity;
        if (ev.action) document.getElementById('select-equity-action').value = ev.action;
        if (ev.reinvestment_strategy) document.getElementById('select-equity-reinvest').value = ev.reinvestment_strategy;
    } else if (mappedTemplate === 'real_estate') {
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
            if (ev.annual_ongoing_carrying_cost) document.getElementById('input-re-carrying-cost').value = ev.annual_ongoing_carrying_cost;
        }
    } else if (mappedTemplate === 'lifestyle') {
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
    } else {
        if (ev.annual_amount || ev.amount) {
            document.getElementById('input-event-amount').value = ev.annual_amount || ev.amount;
        }
    }
}

export function openEditEventModal(eventId) {
    const modalEvent = document.getElementById('modal-event');
    if (!modalEvent || !state.scenariosData) return;
    const ev = (state.scenariosData.events_catalog || []).find(e => e.id === eventId);
    if (!ev) return;

    const searchTmplInput = document.getElementById('input-search-wizard-template');
    if (searchTmplInput) searchTmplInput.value = '';
    filterWizardTemplateOptions('');

    const searchIconInput = document.getElementById('input-search-event-icon');
    if (searchIconInput) searchIconInput.value = '';
    renderEventIconPickerGrid('');
    const drawer = document.getElementById('panel-event-icon-picker');
    if (drawer) drawer.style.display = 'none';

    populateWizardDynamicDropdowns().then(() => {
        document.getElementById('modal-event-title').textContent = `Edit Event: ${ev.name}`;
        document.getElementById('input-event-id').value = ev.id;
        document.getElementById('input-event-name').value = ev.name;
        document.getElementById('input-event-year').value = ev.year || 2027;
        document.getElementById('input-event-end-year').value = ev.end_year || ev.year || 2027;
        document.getElementById('input-event-desc').value = ev.description || '';
        if (ev.funding_source) {
            const selSource = document.getElementById('select-event-source');
            if (selSource) selSource.value = ev.funding_source;
        }

        let mappedTemplate = ev.category || 'capital_outflow';
        if (mappedTemplate === 'home_sale') mappedTemplate = 'real_estate';
        else if (mappedTemplate === 'income_change') mappedTemplate = 'sabbatical';
        else if (['wedding', 'child_home_gift', 'new_child', 'vehicle_purchase', 'angel_investment', 'medical_expense', 'withdrawal'].includes(mappedTemplate)) {
            mappedTemplate = 'capital_outflow';
        } else if (['rental_income', 'deferred_comp', 'windfall', 'custom_spike'].includes(mappedTemplate)) {
            mappedTemplate = 'capital_inflow';
        }

        const selectTemplate = document.getElementById('select-event-template');
        if (selectTemplate) {
            selectTemplate.value = mappedTemplate;
            const panels = getWizardPanels();
            Object.keys(panels).forEach(k => {
                if (panels[k]) panels[k].style.display = (k === mappedTemplate) ? 'block' : 'none';
            });
        }

        const initialIcon = ev.icon || TEMPLATE_DEFAULT_ICONS[ev.category] || TEMPLATE_DEFAULT_ICONS[mappedTemplate] || 'evt-capital-outflow';
        setSelectedEventIcon(initialIcon, Boolean(ev.icon), !ev.icon);
        prefillCategoryFields(mappedTemplate, ev);

        const btnCloneEvt = document.getElementById('modal-btn-clone-event');
        if (btnCloneEvt) {
            btnCloneEvt.style.display = 'inline-flex';
            btnCloneEvt.onclick = () => {
                modalEvent.style.display = 'none';
                cloneEvent(ev.id);
            };
        }

        modalEvent.style.display = 'flex';
    });
}
