/**
 * static/js/scenarios/event_modals_save.js
 * Payload assembly and API submission for scenario life events.
 */

import { state } from './state.js';
import { morphScenariosSection } from './main.js';

const showModalAlert = (...args) => (
    typeof window !== 'undefined' && window.showModalAlert
        ? window.showModalAlert(...args)
        : Promise.resolve()
);

export function buildEventPayload(template, id, name, startYear, endYear, source, desc, selectedIcon) {
    let eventPayload = {
        id,
        name,
        category: template,
        icon: selectedIcon,
        year: startYear,
        end_year: endYear,
        funding_source: source,
        description: desc,
        event_type: (startYear === endYear) ? 'single_spike' : 'duration',
    };

    if (template === 'college') {
        const selChild = document.getElementById('select-college-child');
        const childId = selChild?.value;
        const childOpt = selChild?.options[selChild.selectedIndex];
        const childName = childOpt ? childOpt.text.split('(')[0].trim() : 'Child';
        const selTier = document.getElementById('select-college-tier');
        const manualAmt = parseFloat(document.getElementById('input-event-amount').value) || 0;
        let cost = 85000;
        let tierLabel = 'Private University';
        if (selTier && selTier.value !== 'custom') {
            cost = parseFloat(selTier.value) || 85000;
            tierLabel = selTier.options[selTier.selectedIndex]?.text || '';
        } else if (manualAmt > 0) {
            cost = manualAmt;
            tierLabel = 'Custom Amount';
        }
        const use529 = document.getElementById('check-college-use-529').checked;
        const isSynced = document.getElementById('input-college-sync-with-ledger')?.value === 'true';

        eventPayload.annual_amount = cost;
        eventPayload.amount = cost;
        eventPayload.override_annual_amount = cost;
        eventPayload.benchmark_tier = tierLabel;
        eventPayload.sync_with_ledger = isSynced;
        eventPayload.ledger_source_type = 'college';
        eventPayload.child_user_id = (childId && childId !== 'child_1') ? parseInt(childId) : null;
        eventPayload.child_name = childName;
        eventPayload.use_529_reserves = use529;
        eventPayload.funding_source = use529 ? '529_education_reserve' : source;
        eventPayload.is_outflow = true;
    } else if (template === 'grad_school') {
        const selChild = document.getElementById('select-grad-child');
        const childId = selChild?.value;
        const childOpt = selChild?.options[selChild.selectedIndex];
        const cost = parseFloat(document.getElementById('input-event-amount').value) || 95000;
        const use529 = document.getElementById('check-grad-use-529')?.checked !== false;

        eventPayload.category = 'grad_school';
        eventPayload.degree_program = document.getElementById('select-grad-program')?.value || 'mba';
        eventPayload.annual_amount = cost;
        eventPayload.amount = cost;
        eventPayload.override_annual_amount = cost;
        eventPayload.child_user_id = (childId && childId !== 'child_1') ? parseInt(childId) : null;
        eventPayload.child_name = childOpt ? childOpt.text.split('(')[0].trim() : 'Student';
        eventPayload.use_529_reserves = use529;
        eventPayload.funding_source = use529 ? '529_education_reserve' : source;
        eventPayload.is_outflow = true;
    } else if (template === 'home_renovation') {
        const cost = parseFloat(document.getElementById('input-event-amount').value) || 150000;
        const retPct = (parseFloat(document.getElementById('input-renovation-retention')?.value ?? 60)) / 100.0;
        eventPayload.category = 'home_renovation';
        eventPayload.renovation_scope = document.getElementById('select-renovation-scope')?.value || 'kitchen_bath';
        eventPayload.amount = cost;
        eventPayload.annual_amount = cost;
        eventPayload.renovation_cost = cost;
        eventPayload.value_retention_pct = retPct;
        eventPayload.is_outflow = true;
    } else if (template === 'sabbatical') {
        const multPct = parseFloat(document.getElementById('input-sabbatical-mult')?.value ?? 0);
        const stipend = parseFloat(document.getElementById('input-event-amount').value) || 0;
        eventPayload.category = 'sabbatical';
        eventPayload.sabbatical_mode = document.getElementById('select-sabbatical-mode')?.value || 'sabbatical';
        eventPayload.income_multiplier = multPct / 100.0;
        eventPayload.amount = stipend;
        eventPayload.annual_amount = stipend;
        eventPayload.is_outflow = true;
    } else if (template === 'philanthropy_daf') {
        const amt = parseFloat(document.getElementById('input-event-amount').value) || 250000;
        const taxRate = (parseFloat(document.getElementById('input-daf-tax-rate')?.value ?? 35)) / 100.0;
        eventPayload.category = 'philanthropy_daf';
        eventPayload.daf_structure = document.getElementById('select-daf-structure')?.value || 'frontload';
        eventPayload.tax_deduction_rate = taxRate;
        eventPayload.amount = amt;
        eventPayload.annual_amount = amt;
        eventPayload.is_outflow = true;
    } else if (template === 'state_relocation') {
        const fromState = document.getElementById('select-reloc-from')?.value || 'CA';
        const toState = document.getElementById('select-reloc-to')?.value || 'TX';
        const taxSavingsPct = (parseFloat(document.getElementById('input-reloc-tax-savings')?.value ?? 9.5)) / 100.0;
        const colDeltaPct = (parseFloat(document.getElementById('input-reloc-col-delta')?.value ?? -10)) / 100.0;
        const movingCost = parseFloat(document.getElementById('input-event-amount').value) || 25000;
        eventPayload.category = 'state_relocation';
        eventPayload.from_state = fromState;
        eventPayload.to_state = toState;
        eventPayload.state_tax_rate_delta = -Math.abs(taxSavingsPct);
        eventPayload.tax_savings_pct = taxSavingsPct;
        eventPayload.col_delta_pct = colDeltaPct;
        eventPayload.moving_cost = movingCost;
        eventPayload.amount = movingCost;
        eventPayload.annual_amount = movingCost;
        eventPayload.is_outflow = true;
    } else if (template === 'roth_conversion') {
        const convAmt = parseFloat(document.getElementById('input-event-amount').value) || 150000;
        const taxRate = (parseFloat(document.getElementById('input-roth-tax-rate')?.value ?? 24)) / 100.0;
        const taxSource = document.getElementById('select-roth-tax-source')?.value || 'taxable_brokerage';
        const strategyPreset = document.getElementById('select-roth-preset')?.value || 'bracket_24';
        eventPayload.category = 'roth_conversion';
        eventPayload.roth_strategy_preset = strategyPreset;
        eventPayload.conversion_amount = convAmt;
        eventPayload.marginal_tax_rate = taxRate;
        eventPayload.tax_payment_source = taxSource;
        eventPayload.annual_tax_cost = Math.round(convAmt * taxRate);
        eventPayload.amount = convAmt;
        eventPayload.annual_amount = convAmt;
        eventPayload.is_outflow = false;
    } else if (template === 'superfund_529') {
        const selChild = document.getElementById('select-superfund-child');
        const childId = selChild?.value;
        const childOpt = selChild?.options[selChild.selectedIndex];
        const lumpAmt = parseFloat(document.getElementById('input-event-amount').value) || 380000;
        const electionYears = parseInt(document.getElementById('input-superfund-years')?.value) || 5;
        eventPayload.category = 'superfund_529';
        eventPayload.child_user_id = (childId && childId !== 'child_1') ? parseInt(childId) : null;
        eventPayload.child_name = childOpt ? childOpt.text.split('(')[0].trim() : 'Child';
        eventPayload.superfund_tier = document.getElementById('select-superfund-tier')?.value || '380000';
        eventPayload.gift_tax_split_years = electionYears;
        eventPayload.amount = lumpAmt;
        eventPayload.annual_amount = lumpAmt;
        eventPayload.is_outflow = true;
    } else if (template === 'pe_capital_call') {
        const totalCommitment = parseFloat(document.getElementById('input-pe-commitment')?.value) || 400000;
        const annualCall = parseFloat(document.getElementById('input-event-amount').value) || 100000;
        const tvpi = parseFloat(document.getElementById('input-pe-tvpi')?.value) || 2.0;
        const distStartYear = parseInt(document.getElementById('input-pe-dist-year')?.value) || (startYear + 5);
        const distYears = parseInt(document.getElementById('input-pe-dist-duration')?.value) || 4;
        eventPayload.category = 'pe_capital_call';
        eventPayload.total_commitment = totalCommitment;
        eventPayload.annual_call_amount = annualCall;
        eventPayload.target_tvpi = tvpi;
        eventPayload.distribution_start_year = distStartYear;
        eventPayload.distribution_duration_years = distYears;
        eventPayload.amount = annualCall;
        eventPayload.annual_amount = annualCall;
        eventPayload.is_outflow = true;
    } else if (template === 'ltc_insurance') {
        const annualPremium = parseFloat(document.getElementById('input-event-amount').value) || 25000;
        const monthlyBenefit = parseFloat(document.getElementById('input-ltc-monthly-benefit')?.value) || 12000;
        const poolYears = parseInt(document.getElementById('input-ltc-pool-years')?.value) || 6;
        const inflationProtection = document.getElementById('select-ltc-inflation')?.value || '3pct_compound';
        eventPayload.category = 'ltc_insurance';
        eventPayload.annual_premium = annualPremium;
        eventPayload.monthly_benefit_cap = monthlyBenefit;
        eventPayload.benefit_pool_years = poolYears;
        eventPayload.inflation_protection = inflationProtection;
        eventPayload.amount = annualPremium;
        eventPayload.annual_amount = annualPremium;
        eventPayload.is_outflow = true;
    } else if (template === 'pre65_healthcare') {
        const subsidyMode = document.getElementById('select-aca-subsidy-mode')?.value || 'aca_magi';
        const annualPremium = parseFloat(document.getElementById('input-aca-annual-premium')?.value) || parseFloat(document.getElementById('input-event-amount')?.value) || 24000;
        eventPayload.category = 'pre65_healthcare';
        eventPayload.aca_subsidy_mode = subsidyMode;
        eventPayload.annual_premium = annualPremium;
        eventPayload.amount = annualPremium;
        eventPayload.annual_amount = annualPremium;
        eventPayload.parameters = Object.assign({}, eventPayload.parameters || {}, {
            aca_subsidy_mode: subsidyMode,
            annual_premium: annualPremium,
        });
        eventPayload.metadata = Object.assign({}, eventPayload.metadata || {}, {
            aca_subsidy_mode: subsidyMode,
            annual_premium: annualPremium,
        });
        eventPayload.is_outflow = true;
    } else if (template === 'marital_settlement') {
        const splitPct = (parseFloat(document.getElementById('input-settlement-split-pct')?.value ?? 50)) / 100.0;
        const legalFee = parseFloat(document.getElementById('input-settlement-legal-fee')?.value) || 75000;
        const alimonyAnnual = parseFloat(document.getElementById('input-event-amount').value) || 0;
        const alimonyYears = parseInt(document.getElementById('input-settlement-alimony-years')?.value) || 5;
        eventPayload.category = 'marital_settlement';
        eventPayload.asset_split_pct = splitPct;
        eventPayload.legal_settlement_cost = legalFee;
        eventPayload.annual_alimony = alimonyAnnual;
        eventPayload.alimony_duration_years = alimonyYears;
        eventPayload.amount = alimonyAnnual || legalFee;
        eventPayload.annual_amount = alimonyAnnual;
        eventPayload.is_outflow = true;
    } else if (template === 'company_equity') {
        const grantId = document.getElementById('select-equity-grant').value;
        const qtyStr = document.getElementById('input-equity-quantity').value;
        eventPayload.action = document.getElementById('select-equity-action').value;
        eventPayload.grant_id = (grantId === 'ALL') ? null : grantId;
        eventPayload.options_quantity = qtyStr ? parseFloat(qtyStr) : null;
        eventPayload.reinvestment_strategy = document.getElementById('select-equity-reinvest').value;
        eventPayload.include_wa_tax = false;
    } else if (template === 'real_estate') {
        const reAction = document.getElementById('select-re-action')?.value || 'buy_vacation';
        eventPayload.re_action = reAction;
        if (reAction === 'downsize') {
            const netProceeds = parseFloat(document.getElementById('input-re-price').value) || parseFloat(document.getElementById('input-event-amount').value) || 1200000;
            eventPayload.category = 'home_sale';
            eventPayload.sale_proceeds = netProceeds;
            eventPayload.net_proceeds = netProceeds;
            eventPayload.amount = netProceeds;
            eventPayload.annual_amount = netProceeds;
            eventPayload.is_outflow = false;
        } else {
            const price = parseFloat(document.getElementById('input-re-price').value) || 2500000;
            const downPct = (parseFloat(document.getElementById('input-re-down-pct').value) || 20) / 100.0;
            const carry = parseFloat(document.getElementById('input-re-carrying-cost').value) || 45000;
            eventPayload.purchase_price = price;
            eventPayload.down_payment_pct = downPct;
            eventPayload.annual_ongoing_carrying_cost = carry;
        }
    } else if (template === 'lifestyle') {
        const amt = parseFloat(document.getElementById('input-lifestyle-amount').value) || 150000;
        eventPayload.annual_amount = amt;
        eventPayload.is_outflow = true;
        eventPayload.apply_gogo_taper = document.getElementById('select-lifestyle-gogo-taper').value === 'true';
    } else if (template === 'education') {
        const selChild = document.getElementById('select-edu-child');
        const childId = selChild?.value;
        const childOpt = selChild?.options[selChild.selectedIndex];
        const tier = document.getElementById('select-edu-tier').value;
        const manualAmt = parseFloat(document.getElementById('input-event-amount').value) || 0;
        const use529 = document.getElementById('check-edu-use-529').checked;
        const isSynced = document.getElementById('input-edu-sync-with-ledger')?.value === 'true';
        let cost = manualAmt > 0 ? manualAmt : 50000;
        if (tier === 'k12_private') cost = 40000;
        else if (tier === 'in_state') cost = 35000;
        else if (tier === 'out_state') cost = 75000;
        else if (tier === 'private') cost = 90000;
        else if (tier === 'elite') cost = 95000;

        eventPayload.annual_amount = cost;
        eventPayload.amount = cost;
        eventPayload.override_annual_amount = cost;
        eventPayload.sync_with_ledger = isSynced;
        eventPayload.ledger_source_type = 'k12';
        eventPayload.child_user_id = (childId && childId !== 'child_1') ? parseInt(childId) : null;
        eventPayload.child_name = childOpt ? childOpt.text.split('(')[0].trim() : 'Child';
        eventPayload.child1_annual = cost;
        eventPayload.child1_end_year = endYear;
        eventPayload.use_529_k12_election = use529;
        eventPayload.is_outflow = true;
    } else if (template === 'eldercare') {
        const tier = document.getElementById('select-eldercare-tier').value;
        const split = parseFloat(document.getElementById('input-eldercare-split').value) || 50;
        const offset = parseFloat(document.getElementById('input-eldercare-offset').value) || 20000;
        let careCost = 90000;
        if (tier === 'in_home') careCost = 48000;
        else if (tier === 'memory_care') careCost = 144000;
        const netAnnual = Math.max(0, (careCost - offset) * (split / 100.0));
        eventPayload.annual_care_cost = careCost;
        eventPayload.parent_offset_annual = offset;
        eventPayload.sibling_split_pct = split;
        eventPayload.annual_amount = netAnnual;
        eventPayload.is_outflow = true;
    } else if (template === 'gifting') {
        const count = parseInt(document.getElementById('input-gifting-count').value) || 2;
        const amtPer = parseFloat(document.getElementById('input-gifting-amt-per').value) || 38000;
        eventPayload.annual_amount = count * amtPer;
        eventPayload.is_outflow = true;
    } else if (template === 'refinance') {
        const refType = document.getElementById('select-refinance-type')?.value || 'fixed';
        const newRate = parseFloat(document.getElementById('input-refinance-rate').value) || 0.045;
        const termOrArm = parseInt(document.getElementById('select-refinance-term').value) || 30;
        const fees = parseFloat(document.getElementById('input-refinance-fees').value) || 8000;

        eventPayload.refinance_type = refType;
        eventPayload.new_interest_rate = newRate;
        eventPayload.closing_costs = fees;
        eventPayload.amount = fees;
        eventPayload.is_outflow = true;

        if (refType === 'arm') {
            eventPayload.new_term_years = 30;
            eventPayload.arm_fixed_years = termOrArm;
            eventPayload.arm_reset_rate = parseFloat(document.getElementById('input-refinance-arm-reset').value) || 0.055;
        } else {
            eventPayload.new_term_years = termOrArm;
            eventPayload.arm_fixed_years = null;
        }
    } else if (template === 'capital_outflow') {
        const manualAmt = parseFloat(document.getElementById('input-event-amount').value) || 0;
        eventPayload.category = 'capital_outflow';
        eventPayload.amount = manualAmt;
        eventPayload.annual_amount = manualAmt;
        eventPayload.is_outflow = true;
        eventPayload.outflow_purpose = document.getElementById('select-outflow-purpose')?.value || 'other_outflow';
        eventPayload.funding_source = document.getElementById('select-outflow-source')?.value || source;
    } else if (template === 'capital_inflow' || template === 'custom_spike') {
        const manualAmt = parseFloat(document.getElementById('input-event-amount').value) || 0;
        eventPayload.category = 'capital_inflow';
        eventPayload.amount = manualAmt;
        eventPayload.annual_amount = manualAmt;
        eventPayload.is_outflow = false;
        eventPayload.inflow_source_type = document.getElementById('select-inflow-source-type')?.value || 'other_inflow';
        eventPayload.funding_source = document.getElementById('select-inflow-dest')?.value || source;
    } else {
        const manualAmt = parseFloat(document.getElementById('input-event-amount').value) || 0;
        eventPayload.amount = manualAmt;
        eventPayload.annual_amount = manualAmt;
        eventPayload.is_outflow = true;
    }

    return eventPayload;
}

export async function submitSaveEvent(eventPayload, id, hideEventModal) {
    try {
        const resp = await fetch('/api/events', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(eventPayload)
        });
        const res = await resp.json();
        if (resp.ok && res.success) {
            if (hideEventModal) hideEventModal();
            const isNewEvent = !(state.scenariosData?.events_catalog || []).some(e => e.id === id);
            if (isNewEvent && state.selectedScenarioId && state.scenariosData?.scenarios) {
                const currentScen = state.scenariosData.scenarios.find(s => s.id === state.selectedScenarioId);
                if (currentScen) {
                    if (!currentScen.event_ids) currentScen.event_ids = [];
                    if (!currentScen.event_ids.includes(id)) {
                        currentScen.event_ids.push(id);
                        const scenResp = await fetch('/api/scenarios', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(currentScen)
                        });
                        const scenRes = await scenResp.json();
                        if (!scenResp.ok || !scenRes.success) {
                            await showModalAlert(scenRes.error || 'Failed to attach event to scenario', { title: 'Unable to Update Scenario', type: 'error' });
                        }
                    }
                }
            }
            await morphScenariosSection();
        } else {
            await showModalAlert(res.error || 'Failed to save event', { title: 'Unable to Save Event', type: 'error' });
        }
    } catch (err) {
        await showModalAlert('Save failed: ' + err.message, { title: 'Unable to Save Event', type: 'error' });
    }
}
