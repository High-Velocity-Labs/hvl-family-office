/**
 * static/js/scenarios/event_modals_save.js
 * Payload assembly and API submission for scenario life events.
 */

import { state } from './state.js';
import { morphScenariosSection } from './main.js';
import { applySpecializedEventPayload } from './event_modals_payload.js';
import { numberFrom, percentFrom, assignPresent, tierCost } from './event_modals_inputs.js';

const showModalAlert = (...args) => window.showModalAlert(...args);

export function buildEventPayload(template, id, name, startYear, endYear, source, desc, selectedIcon) {
    const eventPayload = {
        id,
        name,
        category: template,
        icon: selectedIcon,
        year: startYear,
        end_year: endYear,
        funding_source: source,
        description: desc,
        amount_basis: document.getElementById('select-event-amount-basis')?.value,
        event_type: (startYear === endYear) ? 'single_spike' : 'duration',
    };

    if (applySpecializedEventPayload(template, eventPayload, startYear)) {
        return eventPayload;
    }

    if (template === 'college') {
        const selChild = document.getElementById('select-college-child');
        const childId = selChild?.value;
        const childOpt = selChild?.options[selChild.selectedIndex];
        const childName = childOpt ? childOpt.text.split('(')[0].trim() : 'Child';
        const selTier = document.getElementById('select-college-tier');
        const manualAmt = numberFrom('input-event-amount');

        let cost = null;
        let tierLabel = '';
        if (selTier && selTier.value !== 'custom') {
            cost = tierCost('select-college-tier');
            tierLabel = selTier.options[selTier.selectedIndex]?.text || '';
        } else if (manualAmt > 0) {
            cost = manualAmt;
            tierLabel = 'Custom Amount';
        }

        const use529 = document.getElementById('check-college-use-529').checked;
        const isSynced = document.getElementById('input-college-sync-with-ledger')?.value === 'true';

        assignPresent(eventPayload, { annual_amount: cost, amount: cost, override_annual_amount: cost });
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
        const cost = numberFrom('input-event-amount');
        const use529 = document.getElementById('check-grad-use-529')?.checked !== false;

        eventPayload.category = 'grad_school';
        eventPayload.degree_program = document.getElementById('select-grad-program')?.value;
        assignPresent(eventPayload, { annual_amount: cost, amount: cost, override_annual_amount: cost });
        eventPayload.child_user_id = (childId && childId !== 'child_1') ? parseInt(childId) : null;
        eventPayload.child_name = childOpt ? childOpt.text.split('(')[0].trim() : 'Student';
        eventPayload.use_529_reserves = use529;
        eventPayload.funding_source = use529 ? '529_education_reserve' : source;
        eventPayload.is_outflow = true;
    } else if (template === 'home_renovation') {
        const cost = numberFrom('input-event-amount');

        eventPayload.category = 'home_renovation';
        eventPayload.renovation_scope = document.getElementById('select-renovation-scope')?.value;
        assignPresent(eventPayload, {
            amount: cost,
            annual_amount: cost,
            renovation_cost: cost,
            value_retention_pct: percentFrom('input-renovation-retention')
        });
        eventPayload.is_outflow = true;
    } else if (template === 'sabbatical') {
        const stipend = numberFrom('input-event-amount');

        eventPayload.category = 'sabbatical';
        eventPayload.sabbatical_mode = document.getElementById('select-sabbatical-mode')?.value;
        assignPresent(eventPayload, {
            income_multiplier: percentFrom('input-sabbatical-mult'),
            amount: stipend,
            annual_amount: stipend
        });
        eventPayload.is_outflow = true;
    } else if (template === 'philanthropy_daf') {
        const amt = numberFrom('input-event-amount');

        eventPayload.category = 'philanthropy_daf';
        eventPayload.daf_structure = document.getElementById('select-daf-structure')?.value;
        eventPayload.asset_type = document.getElementById('select-daf-asset-type')?.value;
        assignPresent(eventPayload, {
            tax_deduction_rate: percentFrom('input-daf-tax-rate'),
            amount: amt,
            annual_amount: amt
        });
        eventPayload.is_outflow = true;
    } else if (template === 'education') {
        const selChild = document.getElementById('select-edu-child');
        const childId = selChild?.value;
        const childOpt = selChild?.options[selChild.selectedIndex];
        const manualAmt = numberFrom('input-event-amount');
        const use529 = document.getElementById('check-edu-use-529').checked;
        const isSynced = document.getElementById('input-edu-sync-with-ledger')?.value === 'true';

        // The tier's cost comes from the server-rendered option; custom or blank stays the typed amount.
        const cost = tierCost('select-edu-tier') ?? manualAmt;
        assignPresent(eventPayload, { annual_amount: cost, amount: cost, override_annual_amount: cost });
        eventPayload.sync_with_ledger = isSynced;
        eventPayload.ledger_source_type = 'k12';
        eventPayload.child_user_id = (childId && childId !== 'child_1') ? parseInt(childId) : null;
        eventPayload.child_name = childOpt ? childOpt.text.split('(')[0].trim() : 'Child';
        assignPresent(eventPayload, { child1_annual: cost });
        eventPayload.child1_end_year = endYear;
        eventPayload.use_529_k12_election = use529;
        eventPayload.is_outflow = true;
    } else if (template === 'capital_outflow') {
        const manualAmt = numberFrom('input-event-amount');
        eventPayload.category = 'capital_outflow';
        assignPresent(eventPayload, { amount: manualAmt, annual_amount: manualAmt });
        eventPayload.is_outflow = true;
        eventPayload.outflow_purpose = document.getElementById('select-outflow-purpose')?.value;
        eventPayload.funding_source = document.getElementById('select-outflow-source')?.value || source;
    } else if (template === 'capital_inflow' || template === 'custom_spike') {
        const manualAmt = numberFrom('input-event-amount');
        eventPayload.category = 'capital_inflow';
        assignPresent(eventPayload, { amount: manualAmt, annual_amount: manualAmt });
        eventPayload.is_outflow = false;
        eventPayload.inflow_source_type = document.getElementById('select-inflow-source-type')?.value;
        eventPayload.funding_source = document.getElementById('select-inflow-dest')?.value || source;
    } else {
        const manualAmt = numberFrom('input-event-amount');
        assignPresent(eventPayload, { amount: manualAmt, annual_amount: manualAmt });
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
                            await showModalAlert(scenRes.error || 'Failed to attach event to scenario', {
                                title: 'Unable to Update Scenario',
                                type: 'error'
                            });
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
