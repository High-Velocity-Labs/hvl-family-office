/**
 * static/js/scenarios/cards.js
 * SSR DOM Event Hydration for Scenario Pills, Current Plan Card, Scorecard Table, and Schedule.
 * All markup is rendered server-side via Jinja2 and updated via Idiomorph morphing (/fragments/scenarios).
 */

import { state } from './state.js';
import { openScenarioModal } from './modals.js';
import { applyQuickAssumptions, updateSaveButtonState } from './controls.js';
import { morphScenariosSection } from './main.js';
import {
    bindScorecardTable,
    bindScheduleTable,
    formatScenarioOverrides
} from './cards_scorecard.js';

export { formatScenarioOverrides };

const showModalAlert = (...args) => (
    typeof window !== 'undefined' && window.showModalAlert
        ? window.showModalAlert(...args)
        : Promise.resolve()
);

export function updateActiveScenarioButton(data) {
    const btn = document.getElementById('btn-make-active-scenario');
    if (!btn || !data) return;

    const defaultId = data.default_scenario_id || data.active_scenario_id || 'scen_baseline';
    const selectedId = state.selectedScenarioId || data.selected_scenario_id || defaultId;
    const isActive = selectedId === defaultId;
    btn.style.display = isActive ? 'none' : 'inline-flex';
}

function bindCurrentPlanCard(currentScen, data) {
    // 1. Set as Active Plan button on Current Plan Card
    const btnMakeActive = document.getElementById('btn-make-active-scenario');
    if (btnMakeActive && !btnMakeActive.dataset.ssrWired) {
        btnMakeActive.dataset.ssrWired = 'true';
        btnMakeActive.addEventListener('click', async () => {
            if (!state.selectedScenarioId) return;
            const isDemo = (typeof window !== 'undefined' && (
                (typeof window.isDemoSession === 'function' && window.isDemoSession()) ||
                window.__IS_DEMO__ ||
                (typeof document !== 'undefined' && document.body && (document.body.dataset.isDemo === 'true' || document.body.dataset.role === 'viewer')) ||
                new URLSearchParams(window.location?.search || '').get('demo') === '1'
            ));
            try {
                if (!isDemo) {
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
        });
    }

    // 2. Parent Plan navigation badges/links on Current Plan Card
    const parentId = currentScen.parent_id || data.parent_id;
    const badgeParent = document.getElementById('badge-current-plan-parent');
    if (badgeParent) {
        badgeParent.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            const pid = badgeParent.getAttribute('data-parent-id') || parentId;
            if (pid && typeof window.switchToScenario === 'function') {
                window.switchToScenario(pid);
            }
        };
    }

    const linkParent = document.getElementById('label-plan-parent-link');
    if (linkParent) {
        linkParent.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            const pid = linkParent.getAttribute('data-parent-id') || parentId;
            if (pid && typeof window.switchToScenario === 'function') {
                window.switchToScenario(pid);
            }
        };
    }

    const btnBannerSwitch = document.getElementById('btn-banner-switch-parent');
    if (btnBannerSwitch) {
        btnBannerSwitch.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            const pid = btnBannerSwitch.getAttribute('data-parent-id') || parentId;
            if (pid && typeof window.switchToScenario === 'function') {
                window.switchToScenario(pid);
            }
        };
    }
}

function bindSelectedScenarioStrips(currentScen, data) {
    // 3. Selected Scenario Equity Strip controls
    const btnGoto = document.getElementById('btn-goto-equity-ledger');
    if (btnGoto && !btnGoto.dataset.wired) {
        btnGoto.dataset.wired = 'true';
        btnGoto.addEventListener('click', (e) => {
            e.preventDefault();
            const link = document.querySelector('.nav-link[data-target="section-equity"]');
            if (link) link.click();
            else if (typeof window.navigateToSection === 'function') window.navigateToSection('section-equity');
            else window.location.hash = '#company-equity';
        });
    }

    const selectGrowth = document.getElementById('select-scenario-inline-growth');
    if (selectGrowth && !selectGrowth.dataset.wired) {
        selectGrowth.dataset.wired = 'true';
        selectGrowth.addEventListener('change', () => {
            selectGrowth.dataset.userChanged = 'true';
            updateSaveButtonState();
            applyQuickAssumptions(false);
        });
    }

    // 4. Selected Scenario Events Strip interactive handlers
    const strip = document.getElementById('selected-scenario-events-strip') || document.getElementById('selected-scen-events-strip');
    if (!strip) return;

    const btnManageTop = strip.querySelector('.btn-manage-scen-events-top');
    if (btnManageTop) {
        btnManageTop.onclick = (e) => {
            e.stopPropagation();
            if (currentScen && currentScen.id) {
                openScenarioModal(currentScen);
                setTimeout(() => {
                    const evSection = document.getElementById('scenario-events-checklist');
                    if (evSection) evSection.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }, 100);
            }
        };
    }

    const toggleTopEvents = (e) => {
        e.stopPropagation();
        const liveStrip = document.getElementById('selected-scenario-events-strip') || document.getElementById('selected-scen-events-strip');
        const expDiv = document.getElementById('selected-scen-events-expanded');
        const chev = document.getElementById('selected-scen-events-chevron')
            || (liveStrip ? liveStrip.querySelector('.scen-evt-top-chevron') : null);
        if (!expDiv) return;
        const isHidden = expDiv.style.display === 'none' || !expDiv.style.display;
        expDiv.style.display = isHidden ? 'flex' : 'none';
        if (chev) chev.textContent = isHidden ? '▼' : '▶';
    };

    const btnToggleTop = document.getElementById('btn-toggle-top-events') || strip.querySelector('.btn-toggle-scen-events-top');
    if (btnToggleTop) {
        btnToggleTop.onclick = toggleTopEvents;
    }

    strip.querySelectorAll('.event-icon-chip-top').forEach(chip => {
        chip.onclick = toggleTopEvents;
    });

    strip.querySelectorAll('.btn-remove-selected-scen-event').forEach(btn => {
        btn.onclick = async (e) => {
            e.stopPropagation();
            const evtId = btn.getAttribute('data-event-id');
            const scenObj = (data.scenarios || []).find(s => s.id === state.selectedScenarioId);
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
                    await showModalAlert(res.error || 'Failed to update scenario', { title: 'Unable to Update Scenario', type: 'error' });
                }
            } catch (err) {
                console.error('Failed to remove event from scenario:', err);
                await showModalAlert('Failed to update scenario: ' + err.message, { title: 'Unable to Update Scenario', type: 'error' });
            }
        };
    });
}

function bindScenarioSelectorPills() {
    const pillsContainer = document.getElementById('scenario-selector-pills');
    if (!pillsContainer) return;

    pillsContainer.querySelectorAll('.pill-parent-badge').forEach(badge => {
        if (!badge.dataset.ssrWired) {
            badge.dataset.ssrWired = 'true';
            badge.addEventListener('click', (e) => {
                e.stopPropagation();
                const pid = badge.getAttribute('data-parent-id');
                if (pid && typeof window.switchToScenario === 'function') {
                    window.switchToScenario(pid);
                }
            });
        }
    });
    pillsContainer.querySelectorAll('.pill-btn[data-scen-id]').forEach(btn => {
        if (!btn.dataset.ssrWired) {
            btn.dataset.ssrWired = 'true';
            btn.addEventListener('click', () => {
                const scenId = btn.getAttribute('data-scen-id');
                if (scenId && typeof window.switchToScenario === 'function') {
                    window.switchToScenario(scenId);
                }
            });
        }
    });
}

export function bindSsrScenarioCardsAndTables(data) {
    if (!data) return;
    const scenarios = data.scenarios || [];
    const currentScen = scenarios.find(s => s.id === state.selectedScenarioId)
        || scenarios.find(s => s.id === data.selected_scenario_id)
        || scenarios.find(s => s.id === data.active_scenario_id)
        || scenarios[0] || {};

    updateActiveScenarioButton(data);
    bindCurrentPlanCard(currentScen, data);
    bindSelectedScenarioStrips(currentScen, data);
    bindScenarioSelectorPills();

    const tbody = document.getElementById('tbody-scenarios-scorecard');
    if (tbody) {
        bindScorecardTable(tbody, data);
    }

    const schedTbody = document.getElementById('tbody-retirement-schedule') || document.getElementById('scen-schedule-tbody');
    if (schedTbody) {
        bindScheduleTable(schedTbody);
    }
}

export const bindSsrDomEvents = bindSsrScenarioCardsAndTables;
