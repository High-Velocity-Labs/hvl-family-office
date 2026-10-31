/**
 * static/js/scenarios/event_modals_payload.js
 * Category-specific payload builders for tax, housing, private equity, and care events.
 */

import { numberFrom, percentFrom, assignPresent, tierCost } from './event_modals_inputs.js';

const amountInput = () => numberFrom('input-event-amount');
const valueOf = (id) => document.getElementById(id)?.value || null;

export function applySpecializedEventPayload(template, eventPayload, startYear) {
    if (template === 'state_relocation') {
        const taxSavingsPct = percentFrom('input-reloc-tax-savings');
        const movingCost = amountInput();

        eventPayload.category = 'state_relocation';
        assignPresent(eventPayload, {
            from_state: valueOf('select-reloc-from'),
            to_state: valueOf('select-reloc-to'),
            state_tax_rate_delta: taxSavingsPct === null ? null : -Math.abs(taxSavingsPct),
            tax_savings_pct: taxSavingsPct,
            col_delta_pct: percentFrom('input-reloc-col-delta'),
            moving_cost: movingCost,
            amount: movingCost,
            annual_amount: movingCost
        });
        eventPayload.is_outflow = true;
        return true;
    }

    if (template === 'roth_conversion') {
        const convAmt = amountInput();
        const taxRate = percentFrom('input-roth-tax-rate');

        eventPayload.category = 'roth_conversion';
        assignPresent(eventPayload, {
            roth_strategy_preset: valueOf('select-roth-preset'),
            conversion_amount: convAmt,
            marginal_tax_rate: taxRate,
            tax_payment_source: valueOf('select-roth-tax-source'),
            annual_tax_cost: (convAmt === null || taxRate === null) ? null : Math.round(convAmt * taxRate),
            amount: convAmt,
            annual_amount: convAmt
        });
        eventPayload.is_outflow = false;
        return true;
    }

    if (template === 'superfund_529') {
        const selChild = document.getElementById('select-superfund-child');
        const childId = selChild?.value;
        const childOpt = selChild?.options[selChild.selectedIndex];
        const lumpAmt = amountInput();

        eventPayload.category = 'superfund_529';
        eventPayload.child_user_id = (childId && childId !== 'child_1') ? parseInt(childId) : null;
        assignPresent(eventPayload, {
            child_name: childOpt ? childOpt.text.split('(')[0].trim() : null,
            superfund_tier: valueOf('select-superfund-tier'),
            gift_tax_split_years: numberFrom('input-superfund-years'),
            amount: lumpAmt,
            annual_amount: lumpAmt
        });
        eventPayload.is_outflow = true;
        return true;
    }

    if (template === 'pe_capital_call') {
        const annualCall = amountInput();

        eventPayload.category = 'pe_capital_call';
        assignPresent(eventPayload, {
            total_commitment: numberFrom('input-pe-commitment'),
            annual_call_amount: annualCall,
            target_tvpi: numberFrom('input-pe-tvpi'),
            distribution_start_year: numberFrom('input-pe-dist-year'),
            distribution_duration_years: numberFrom('input-pe-dist-duration'),
            amount: annualCall,
            annual_amount: annualCall
        });
        eventPayload.is_outflow = true;
        return true;
    }

    if (template === 'ltc_insurance') {
        const annualPremium = amountInput();

        eventPayload.category = 'ltc_insurance';
        assignPresent(eventPayload, {
            annual_premium: annualPremium,
            monthly_benefit_cap: numberFrom('input-ltc-monthly-benefit'),
            benefit_pool_years: numberFrom('input-ltc-pool-years'),
            inflation_protection: valueOf('select-ltc-inflation'),
            amount: annualPremium,
            annual_amount: annualPremium
        });
        eventPayload.is_outflow = true;
        return true;
    }

    if (template === 'pre65_healthcare') {
        const subsidyMode = valueOf('select-aca-subsidy-mode');
        const annualPremium = numberFrom('input-aca-annual-premium') ?? amountInput();
        const params = assignPresent({}, { aca_subsidy_mode: subsidyMode, annual_premium: annualPremium });

        eventPayload.category = 'pre65_healthcare';
        assignPresent(eventPayload, {
            aca_subsidy_mode: subsidyMode,
            annual_premium: annualPremium,
            amount: annualPremium,
            annual_amount: annualPremium
        });
        eventPayload.parameters = Object.assign({}, eventPayload.parameters || {}, params);
        eventPayload.metadata = Object.assign({}, eventPayload.metadata || {}, params);
        eventPayload.is_outflow = true;
        return true;
    }

    if (template === 'marital_settlement') {
        const legalFee = numberFrom('input-settlement-legal-fee');
        const alimonyAnnual = amountInput();

        eventPayload.category = 'marital_settlement';
        assignPresent(eventPayload, {
            asset_split_pct: percentFrom('input-settlement-split-pct'),
            legal_settlement_cost: legalFee,
            annual_alimony: alimonyAnnual,
            alimony_duration_years: numberFrom('input-settlement-alimony-years'),
            amount: alimonyAnnual || legalFee,
            annual_amount: alimonyAnnual
        });
        eventPayload.is_outflow = true;
        return true;
    }

    if (template === 'company_equity') {
        const grantId = document.getElementById('select-equity-grant').value;
        const qtyStr = document.getElementById('input-equity-quantity').value;

        eventPayload.action = document.getElementById('select-equity-action').value;
        eventPayload.grant_id = (grantId === 'ALL') ? null : grantId;
        eventPayload.options_quantity = qtyStr ? parseFloat(qtyStr) : null;
        eventPayload.reinvestment_strategy = document.getElementById('select-equity-reinvest').value;
        eventPayload.include_wa_tax = false;
        return true;
    }

    if (template === 'real_estate') {
        const reAction = document.getElementById('select-re-action').value;
        eventPayload.re_action = reAction;
        if (reAction === 'downsize') {
            const netProceeds = numberFrom('input-re-price') ?? amountInput();
            eventPayload.category = 'home_sale';
            assignPresent(eventPayload, {
                sale_proceeds: netProceeds,
                net_proceeds: netProceeds,
                amount: netProceeds,
                annual_amount: netProceeds
            });
            eventPayload.is_outflow = false;
        } else {
            assignPresent(eventPayload, {
                purchase_price: numberFrom('input-re-price'),
                down_payment_pct: percentFrom('input-re-down-pct'),
                annual_ongoing_carrying_cost: numberFrom('input-re-carrying-cost')
            });
        }
        return true;
    }

    if (template === 'lifestyle') {
        assignPresent(eventPayload, { annual_amount: numberFrom('input-lifestyle-amount') });
        eventPayload.is_outflow = true;
        eventPayload.apply_gogo_taper = document.getElementById('select-lifestyle-gogo-taper').value === 'true';
        return true;
    }

    if (template === 'eldercare') {
        const split = numberFrom('input-eldercare-split');
        const offset = numberFrom('input-eldercare-offset');
        const careCost = tierCost('select-eldercare-tier');
        assignPresent(eventPayload, {
            annual_care_cost: careCost,
            parent_offset_annual: offset,
            sibling_split_pct: split,
            annual_amount: (careCost === null || offset === null || split === null)
                ? null
                : Math.max(0, (careCost - offset) * (split / 100.0))
        });
        eventPayload.is_outflow = true;
        return true;
    }

    if (template === 'gifting') {
        const count = parseInt(document.getElementById('input-gifting-count').value, 10);
        const amtPer = parseFloat(document.getElementById('input-gifting-amt-per').value);
        eventPayload.annual_amount = (count > 0 && amtPer > 0) ? count * amtPer : 0;
        eventPayload.is_outflow = true;
        return true;
    }

    if (template === 'refinance') {
        const refType = document.getElementById('select-refinance-type').value;
        const termOrArm = numberFrom('select-refinance-term');
        const fees = numberFrom('input-refinance-fees');

        eventPayload.refinance_type = refType;
        assignPresent(eventPayload, {
            new_interest_rate: numberFrom('input-refinance-rate'),
            closing_costs: fees,
            amount: fees
        });
        eventPayload.is_outflow = true;

        if (refType === 'arm') {
            assignPresent(eventPayload, {
                arm_fixed_years: termOrArm,
                arm_reset_rate: numberFrom('input-refinance-arm-reset')
            });
        } else {
            assignPresent(eventPayload, { new_term_years: termOrArm });
            eventPayload.arm_fixed_years = null;
        }
        return true;
    }

    return false;
}
