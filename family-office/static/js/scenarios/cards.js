/**
 * static/js/scenarios/cards.js
 * SSR DOM Event Hydration for Scenario Pills, Current Plan Card, Scorecard Table, and Schedule.
 * All markup is rendered server-side via Jinja2 and updated via Idiomorph morphing (/fragments/scenarios).
 */

import { state } from './state.js';
import { openScenarioModal } from './modals.js';
import { morphScenariosSection, switchToScenario } from './main.js';
import { delegate } from './event_delegation.js';
import {
    bindScorecardTable,
    bindScheduleTable,
    formatScenarioOverrides
} from './cards_scorecard.js';
import { initCardsOverlays } from './cards_overlays.js';

export { formatScenarioOverrides };

const showModalAlert = (...args) => window.showModalAlert(...args);

export function updateActiveScenarioButton(data) {
    const btn = document.getElementById('btn-make-active-scenario');
    if (!btn || !data) return;

    const defaultId = data.default_scenario_id || data.active_scenario_id || 'scen_baseline';
    const selectedId = state.selectedScenarioId || data.selected_scenario_id || defaultId;
    const isActive = selectedId === defaultId;
    btn.style.display = isActive ? 'none' : 'inline-flex';
}

const UPDATE_ERROR = { title: 'Unable to Update Scenario', type: 'error' };
const STRIP = '#selected-scenario-events-strip, #selected-scen-events-strip';
const inStrip = (...selectors) => STRIP.split(', ').flatMap(root => selectors.map(sel => `${root} ${sel}`)).join(', ');

/** The plan the page is showing, from live state (handlers run long after the data they were installed with). */
function currentScenario() {
    const data = state.scenariosData || {};
    const scenarios = data.scenarios || [];
    return scenarios.find(s => s.id === state.selectedScenarioId)
        || scenarios.find(s => s.id === data.selected_scenario_id)
        || scenarios.find(s => s.id === data.active_scenario_id)
        || scenarios[0] || {};
}

function isReadOnlySession() {
    return window.isDemoSession() || document.body.dataset.role === 'viewer'
        || new URLSearchParams(window.location.search).get('demo') === '1';
}

async function makeSelectedPlanActive() {
    if (!state.selectedScenarioId) return;
    try {
        if (!isReadOnlySession()) {
            await fetch('/api/scenarios/active', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ scenario_id: state.selectedScenarioId })
            });
        }
        await morphScenariosSection({ scenario_id: state.selectedScenarioId });
    } catch (e) {
        console.error('Failed to set active scenario:', e);
    }
}

function switchToParent(el, e) {
    e.preventDefault();
    const data = state.scenariosData || {};
    const pid = el.getAttribute('data-parent-id') || currentScenario().parent_id || data.parent_id;
    if (pid) switchToScenario(pid);
}

function gotoEquityLedger(_el, e) {
    e.preventDefault();
    const link = document.querySelector('.nav-link[data-target="section-equity"]');
    if (link) link.click();
    else window.navigateToSection('section-equity');
}

function manageSelectedPlanEvents() {
    const scen = currentScenario();
    if (!scen.id) return;
    openScenarioModal(scen);
    setTimeout(() => {
        const evSection = document.getElementById('scenario-events-checklist');
        if (evSection) evSection.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 100);
}

function toggleTopEvents() {
    const liveStrip = document.querySelector(STRIP);
    const expDiv = document.getElementById('selected-scen-events-expanded');
    const collapsedIcons = document.getElementById('selected-scen-events-collapsed-icons');
    const chev = document.getElementById('selected-scen-events-chevron')
        || (liveStrip ? liveStrip.querySelector('.scen-evt-top-chevron') : null);
    if (!expDiv) return;
    const isHidden = expDiv.style.display === 'none' || !expDiv.style.display;
    expDiv.style.display = isHidden ? 'flex' : 'none';
    if (collapsedIcons) collapsedIcons.style.display = isHidden ? 'none' : 'inline-flex';
    if (chev) chev.textContent = isHidden ? '▼' : '▶';
}

async function removeEventFromSelectedPlan(btn) {
    const evtId = btn.getAttribute('data-event-id');
    const scenObj = ((state.scenariosData || {}).scenarios || []).find(s => s.id === state.selectedScenarioId);
    if (!scenObj || !evtId) return;
    const updatedIds = (scenObj.event_ids || []).filter(id => id !== evtId);
    try {
        const resp = await fetch('/api/scenarios', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...scenObj, event_ids: updatedIds })
        });
        const res = await resp.json();
        if (resp.ok && res.success) {
            await morphScenariosSection({ scenario_id: state.selectedScenarioId });
        } else {
            await showModalAlert(res.error || 'Failed to update scenario', UPDATE_ERROR);
        }
    } catch (err) {
        console.error('Failed to remove event from scenario:', err);
        await showModalAlert('Failed to update scenario: ' + err.message, UPDATE_ERROR);
    }
}

const switchToPillParent = (el, e) => {
    e.stopPropagation();
    const pid = el.getAttribute('data-parent-id');
    if (pid) switchToScenario(pid);
};

/** Document-level listeners for the current-plan card, its events strip and the plan pills; installed once. */
export function installCurrentPlanDelegation() {
    delegate(document, 'current-plan', () => ({
        click: {
            'btn-make-active-scenario': makeSelectedPlanActive,
            '#badge-current-plan-parent, #label-plan-parent-link, #btn-banner-switch-parent': switchToParent,
            'btn-goto-equity-ledger': gotoEquityLedger,
            [inStrip('.btn-manage-scen-events-top')]: manageSelectedPlanEvents,
            [`#btn-toggle-top-events, ${inStrip('.btn-toggle-scen-events-top', '.event-icon-chip-top')}`]:
                toggleTopEvents,
            [inStrip('.btn-remove-selected-scen-event')]: removeEventFromSelectedPlan,
            '#scenario-selector-pills .pill-parent-badge': switchToPillParent,
            '#scenario-selector-pills .pill-btn[data-scen-id]': (el) => (
                switchToScenario(el.getAttribute('data-scen-id'))
            )
        }
    }));
}

export function bindSsrScenarioCardsAndTables(data) {
    if (!data) return;
    updateActiveScenarioButton(data);
    installCurrentPlanDelegation();

    const tbody = document.getElementById('tbody-scenarios-scorecard');
    if (tbody) {
        bindScorecardTable(tbody, data);
    }
    initCardsOverlays();

    const schedTbody = document.getElementById('tbody-retirement-schedule') || document.getElementById('scen-schedule-tbody');
    if (schedTbody) {
        bindScheduleTable(schedTbody);
    }
}

export const bindSsrDomEvents = bindSsrScenarioCardsAndTables;
