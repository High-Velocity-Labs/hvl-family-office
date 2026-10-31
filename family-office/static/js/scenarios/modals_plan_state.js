/**
 * Scenario Plan Modal State and Events Tab
 * Manages modal-level scenario object state; the event checklist itself is the server fragment
 * /fragments/scenario_event_checklist, morphed into #modal-scenario-event-checklist.
 */
import { state } from './state.js';
import { delegate } from './event_delegation.js';

let modalScenarioObj = null;
let modalSelectedEventIds = new Set();
let modalEventsSearchQuery = '';

export function getModalScenarioObj() { return modalScenarioObj; }
export function setModalScenarioObj(val) { modalScenarioObj = val; }
export function getModalSelectedEventIds() { return modalSelectedEventIds; }
export function setModalSelectedEventIds(val) { modalSelectedEventIds = val; }
export function getModalEventsSearchQuery() { return modalEventsSearchQuery; }
export function setModalEventsSearchQuery(val) { modalEventsSearchQuery = val; }
export function getModalSpendingGuardrailMode() { return modalScenarioObj?.spending_guardrail_mode || 'off'; }
export function setModalSpendingGuardrailMode(val) { if (modalScenarioObj) modalScenarioObj.spending_guardrail_mode = val; }

export function setModalScenarioTab(tabName) {
    const tabAssumptions = document.getElementById('tab-modal-scen-assumptions');
    const tabEvents = document.getElementById('tab-modal-scen-events');
    const panelAssumptions = document.getElementById('modal-scen-panel-assumptions');
    const panelEvents = document.getElementById('modal-scen-panel-events');
    if (!tabAssumptions || !tabEvents || !panelAssumptions || !panelEvents) return;

    if (tabName === 'events') {
        tabAssumptions.classList.remove('active');
        tabEvents.classList.add('active');
        panelAssumptions.style.display = 'none';
        panelEvents.style.display = 'block';
        renderModalScenarioEventsList(state.scenariosData);
    } else {
        tabEvents.classList.remove('active');
        tabAssumptions.classList.add('active');
        panelEvents.style.display = 'none';
        panelAssumptions.style.display = 'block';
    }
}

export function updateModalEventsCountBadge() {
    const badge = document.getElementById('modal-scen-events-count');
    if (badge) {
        badge.textContent = String(modalSelectedEventIds.size);
    }
}

const CHECKLIST_ID = 'modal-scenario-event-checklist';

/** Parent plan the draft inherits from, or null for the baseline / an independent root plan. */
function currentParentId() {
    const obj = modalScenarioObj;
    const isBaseline = obj?.id === 'scen_baseline' || obj?.id === 'baseline'
        || (state.selectedScenarioId === 'scen_baseline' && !obj?.id);
    if (isBaseline) return null;
    if (obj && obj.id) return (obj.parent_id && obj.parent_id !== obj.id) ? obj.parent_id : null;
    const domVal = document.getElementById('select-scenario-parent')?.value;
    return (domVal && domVal !== obj?.id) ? domVal : null;
}

/** Drops the previous plan's accordion so a newly opened plan starts from the server's default open groups. */
export function resetModalChecklistView() {
    document.getElementById(CHECKLIST_ID)?.replaceChildren();
}

function installChecklistDelegation() {
    delegate(document, 'plan-event-checklist', () => ({
        change: {
            [`#${CHECKLIST_ID} input[type="checkbox"][data-event-id]`]: (chk) => {
                if (chk.checked) modalSelectedEventIds.add(chk.dataset.eventId);
                else modalSelectedEventIds.delete(chk.dataset.eventId);
                updateModalEventsCountBadge();
                renderModalScenarioEventsList();
            }
        }
    }));
}

export function renderModalScenarioEventsList(data = state.scenariosData) {
    const container = document.getElementById(CHECKLIST_ID);
    if (!container || !data) return Promise.resolve();
    installChecklistDelegation();

    const parentId = currentParentId();
    const params = new URLSearchParams({
        scenario_id: modalScenarioObj?.id || '',
        parent_id: parentId || '',
        overlay: modalScenarioObj?.is_baseline_layer ? '1' : '0',
        selected: Array.from(modalSelectedEventIds).join(','),
        q: modalEventsSearchQuery || '',
    });
    const groups = container.querySelectorAll('details.category-accordion-group');
    if (groups.length) {
        params.set('open', Array.from(groups).filter(d => d.open).map(d => d.dataset.group).join(','));
    }
    return window.htmx.ajax('GET', `/fragments/scenario_event_checklist?${params}`, {
        target: `#${CHECKLIST_ID}`, swap: 'morph:innerHTML',
    });
}

/** Expand All / Collapse All for the accordion; returns the label the toggle button should now show. */
export function toggleAllChecklistGroups() {
    const groups = Array.from(document.querySelectorAll(`#${CHECKLIST_ID} details.category-accordion-group`));
    const expand = !groups.every(d => d.open);
    groups.forEach(d => { d.open = expand; });
    return expand ? 'Collapse All' : 'Expand All';
}
