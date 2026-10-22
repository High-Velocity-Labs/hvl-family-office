/**
 * static/js/scenarios/event_modals_save.js
 * Payload assembly and API submission for scenario life events.
 */

import { state } from './state.js';
import { morphScenariosSection } from './main.js';
import { applySpecializedEventPayload } from './event_modals_payload.js';

const showModalAlert = (...args) => (
    typeof window !== 'undefined' && window.showModalAlert
        ? window.showModalAlert(...args)
        : Promise.resolve()
);

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
