/**
 * static/js/scenarios/cards_scorecard.js
 * Scorecard and spend-down schedule table bindings for scenarios view.
 */

import { state, fmtShortCurrency } from './state.js';
import { inspectTimelineYear } from './scrubber.js';
import { openScenarioModal, cloneScenario } from './modals.js';
import { morphScenariosSection, switchToScenario } from './main.js';
import { closeAllScenarioDropdowns } from './cards_overlays.js';
import { initScenarioDragAndDrop } from './cards_reorder.js';
import { delegate, listenOnce } from './event_delegation.js';

export { initScenarioDragAndDrop };

const showModalAlert = (...args) => window.showModalAlert(...args);
const showModalConfirm = (...args) => window.showModalConfirm(...args);

export function formatScenarioOverrides(overridesObj) {
    if (!overridesObj || typeof overridesObj !== 'object') return { count: 0, text: '', pills: [] };
    const hasCustomEqRate = overridesObj.custom_equity_growth_rate !== null && overridesObj.custom_equity_growth_rate !== undefined;
    const entries = Object.entries(overridesObj).filter(([k, v]) => {
        if (v === null || v === undefined) return false;
        if (typeof v === 'object' && !Array.isArray(v) && Object.keys(v).length === 0) return false;
        if (hasCustomEqRate && k === 'equity_growth_preset' && String(v).trim().toLowerCase() === 'custom') return false;
        return true;
    });
    if (!entries.length) return { count: 0, text: '', pills: [] };
    const labelMap = {
        equity_growth_preset: 'Company 409A Growth',
        equity_growth_presets: 'Per-Holding 409A Growth',
        custom_equity_growth_rate: 'Custom 409A Growth',
        annual_living_spend: 'Living Spend',
        annual_savings: 'Annual Savings',
        inflation_rate: 'Inflation Rate',
        primary_retirement_age: 'Primary Retirement Age',
        spouse_retirement_age: 'Spouse Retirement Age',
        ss_claim_age: 'Social Security Claim Age',
        primary_ss_claim_age: 'Primary SS Claim Age',
        spouse_ss_claim_age: 'Spouse SS Claim Age',
        growth_us_equity: 'US Equities Return',
        growth_intl_equity: 'Intl Equities Return',
        growth_bonds: 'Bonds Return',
        growth_cash: 'Cash Yield',
        growth_private_investments: 'Private Funds Return',
        growth_real_estate: 'Real Estate Appreciation',
        spending_guardrail_mode: 'Spending Guardrails'
    };
    const eqPresetMap = {
        aggressive: 'Aggressive (14.0%/yr)',
        baseline_curve: 'Baseline Curve (10.5%/yr)',
        moderate: 'Moderate (8.0%/yr)',
        conservative: 'Conservative (5.0%/yr)',
        flat: 'Flat (0.0%/yr)',
        custom: 'Custom Rate'
    };
    const pills = entries.map(([k, v]) => {
        const lbl = labelMap[k] || k;
        let valStr = String(v);
        if (k === 'equity_growth_preset') {
            valStr = eqPresetMap[String(v).trim().toLowerCase()] || String(v);
        } else if (k === 'equity_growth_presets' && typeof v === 'object' && v !== null) {
            valStr = Object.values(v).map(pv => eqPresetMap[String(pv).trim().toLowerCase()] || String(pv)).join(', ');
        } else if (k === 'annual_living_spend' || k === 'annual_savings') valStr = fmtShortCurrency(v) + '/yr';
        else if (k.includes('rate') || k.startsWith('growth_')) valStr = `${(parseFloat(v) * 100).toFixed(1)}%`;
        else if (k.includes('age')) valStr = `Age ${v}`;
        else if (k === 'spending_guardrail_mode') {
            const map = { off: 'Off', moderate: 'Moderate (-15%)', aggressive: 'Aggressive (-25%)' };
            valStr = map[v] || String(v);
        }
        return { key: k, label: lbl, valStr, text: `${lbl}: ${valStr}` };
    });
    return {
        count: entries.length,
        text: pills.map(p => p.text).join(' • '),
        pills
    };
}

export function isShowingArchivedScenarios() {
    try {
        return localStorage.getItem('scenarios_show_archived') === 'true';
    } catch {
        return false;
    }
}

export function setShowingArchivedScenarios(val) {
    try {
        localStorage.setItem('scenarios_show_archived', val ? 'true' : 'false');
    } catch {
        // ignore
    }
}

export function applyArchivedVisibility(showArchived) {
    const isShow = (showArchived !== undefined) ? Boolean(showArchived) : isShowingArchivedScenarios();
    const toggleBtn = document.getElementById('btn-toggle-archived-scenarios');
    if (toggleBtn) {
        const count = parseInt(toggleBtn.getAttribute('data-archived-count') || '0', 10);
        toggleBtn.textContent = isShow ? `Hide Archived (${count})` : `Show Archived (${count})`;
        toggleBtn.classList.toggle('active', isShow);
        if (count > 0) {
            toggleBtn.style.display = 'inline-flex';
        }
    }

    document.querySelectorAll('.scen-pill-archived').forEach(pill => {
        const isSelected = pill.classList.contains('active');
        pill.style.display = (isShow || isSelected) ? 'inline-flex' : 'none';
    });

    document.querySelectorAll('.scorecard-row-archived').forEach(row => {
        const isCurrent = row.classList.contains('active');
        row.style.display = (isShow || isCurrent) ? '' : 'none';
    });
}

export async function toggleScenarioArchived(scenId, targetArchived = null) {
    if (!scenId) return;
    try {
        const payload = targetArchived !== null ? { archived: Boolean(targetArchived) } : {};
        const resp = await fetch(`/api/scenarios/${encodeURIComponent(scenId)}/archive`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const res = await resp.json();
        if (resp.ok && res.success) {
            await morphScenariosSection({ scenario_id: state.selectedScenarioId });
        } else {
            await showModalAlert(res.error || 'Failed to update plan archival status', {
                title: 'Archive Error',
                type: 'error'
            });
        }
    } catch (err) {
        console.error('Failed to toggle scenario archive:', err);
        await showModalAlert('Failed to update plan archival status: ' + err.message, {
            title: 'Archive Error',
            type: 'error'
        });
    }
}

const UPDATE_ERROR = { title: 'Unable to Update Scenario', type: 'error' };
const SCORECARD = '#tbody-scenarios-scorecard';
const ROW_INTERACTIVE = 'button, a, input, select, .scorecard-parent-link, .event-icon-chip, .row-drag-grip, '
    + '.scorecard-more-dropdown-menu';

const scenIdOf = (el) => el.getAttribute('data-scen-id') || el.getAttribute('data-id');
const liveScenarios = () => (state.scenariosData && state.scenariosData.scenarios) || [];

function closeAllRowMoreMenus(exceptMenu = null) {
    closeAllScenarioDropdowns(exceptMenu);
}

function toggleMoreActions(btn) {
    const wrap = btn.closest('.scorecard-row-menu-wrap');
    const menu = wrap ? wrap.querySelector('.scorecard-more-dropdown-menu') : null;
    if (!menu) return;
    const isOpen = menu.style.display !== 'none' && menu.style.display !== '';
    closeAllRowMoreMenus(menu);
    if (isOpen) {
        menu.style.display = 'none';
        btn.setAttribute('aria-expanded', 'false');
        return;
    }
    menu.style.position = 'fixed';
    menu.style.display = 'block';
    btn.setAttribute('aria-expanded', 'true');
    const btnRect = btn.getBoundingClientRect();
    const menuRect = menu.getBoundingClientRect();
    const vw = window.innerWidth || document.documentElement.clientWidth || 1024;
    const vh = window.innerHeight || document.documentElement.clientHeight || 768;
    const menuWidth = menuRect.width || 165;
    const menuHeight = menuRect.height || 180;
    let top = btnRect.bottom + 4;
    if (top + menuHeight > vh - 12 && btnRect.top - menuHeight - 4 >= 12) {
        top = btnRect.top - menuHeight - 4;
    }
    let left = btnRect.right - menuWidth;
    if (left < 12) left = 12;
    if (left + menuWidth > vw - 12) left = Math.max(12, vw - menuWidth - 12);
    menu.style.top = `${top}px`;
    menu.style.left = `${left}px`;
    menu.style.right = 'auto';
    menu.style.marginTop = '0';
}

function toggleRowEvents(scenId) {
    const expDiv = document.getElementById(`scen-events-exp-${scenId}`);
    const iconsDiv = document.getElementById(`scen-events-icons-${scenId}`);
    const chev = document.querySelector(`${SCORECARD} .scen-evt-chevron[data-id="${scenId}"]`);
    if (!expDiv) return;
    const isHidden = expDiv.style.display === 'none' || !expDiv.style.display;
    expDiv.style.display = isHidden ? 'flex' : 'none';
    if (iconsDiv) iconsDiv.style.display = isHidden ? 'none' : 'inline-flex';
    if (chev) chev.textContent = isHidden ? '▼' : '▶';
}

async function removeEventFromScenario(btn) {
    const evtId = btn.getAttribute('data-event-id');
    const scenObj = liveScenarios().find(s => s.id === btn.getAttribute('data-scen-id'));
    if (!scenObj || !evtId) return;
    const payload = { ...scenObj, event_ids: (scenObj.event_ids || []).filter(id => id !== evtId) };
    delete payload.added_event_ids;
    delete payload.excluded_event_ids;
    try {
        const resp = await fetch('/api/scenarios', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
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

async function deleteScenario(btn) {
    const scenId = scenIdOf(btn);
    if (!scenId) return;
    const confirmed = await showModalConfirm('Delete this scenario?', {
        title: 'Delete Scenario',
        confirmText: 'Delete Plan',
        confirmVariant: 'danger'
    });
    if (!confirmed) return;
    try {
        await fetch(`/api/scenarios/${scenId}`, { method: 'DELETE' });
        const nextId = (state.selectedScenarioId === scenId) ? 'scen_baseline' : state.selectedScenarioId;
        state.selectedScenarioId = nextId;
        await morphScenariosSection({ scenario_id: nextId });
    } catch (e) {
        console.error('Failed to delete scenario:', e);
    }
}

// Scenario row actions: `selector -> (scenario, id)`; they only run for a scenario still in the live data.
const SCEN_ACTIONS = {
    '.btn-edit-scenario, .btn-edit-scen': (scen) => openScenarioModal(scen),
    '.btn-clone-scenario, .btn-clone-scen': (scen) => cloneScenario(scen),
    '.btn-branch-child-scenario, .btn-child-scen': (_, id) => openScenarioModal(null, id),
    '.btn-manage-scen-events': (scen) => {
        openScenarioModal(scen);
        setTimeout(() => {
            const evSection = document.getElementById('scenario-events-checklist');
            if (evSection) evSection.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 100);
    }
};

const scorecardClicks = () => {
    const handlers = {
        '#btn-toggle-archived-scenarios': () => {
            const next = !isShowingArchivedScenarios();
            setShowingArchivedScenarios(next);
            applyArchivedVisibility(next);
        },
        [`${SCORECARD} .scorecard-parent-link`]: (el) => {
            const pid = el.getAttribute('data-parent-id');
            if (pid) switchToScenario(pid);
        },
        [`${SCORECARD} .scorecard-scen-title, ${SCORECARD} .btn-view-scenario, ${SCORECARD} .btn-select-scen`]:
            (el) => {
                const scenId = scenIdOf(el);
                if (scenId) switchToScenario(scenId);
            },
        [`${SCORECARD} .scorecard-row`]: (row, e) => {
            if (e.target.closest(ROW_INTERACTIVE)) return;
            const scenId = scenIdOf(row);
            if (scenId) switchToScenario(scenId);
        },
        [`${SCORECARD} .btn-scorecard-more-actions`]: toggleMoreActions,
        [`${SCORECARD} .scorecard-more-dropdown-menu .scorecard-menu-item`]: () => closeAllRowMoreMenus(),
        [`${SCORECARD} .btn-toggle-scen-events, ${SCORECARD} .event-icon-chip`]: (el) => toggleRowEvents(scenIdOf(el)),
        [`${SCORECARD} .btn-remove-scen-event`]: removeEventFromScenario,
        [`${SCORECARD} .btn-set-active-scenario, ${SCORECARD} .btn-SetActive-scen`]: (el) => {
            const scenId = scenIdOf(el);
            if (scenId) switchToScenario(scenId);
        },
        [`${SCORECARD} .btn-archive-scenario, ${SCORECARD} .btn-unarchive-scenario`]: (el) => (
            toggleScenarioArchived(scenIdOf(el), el.classList.contains('btn-archive-scenario'))
        ),
        '#btn-archive-current-plan, #btn-unarchive-current-plan': (el) => (
            toggleScenarioArchived(el.getAttribute('data-scen-id') || state.selectedScenarioId,
                el.id === 'btn-archive-current-plan')
        ),
        [['.btn-delete-scenario', '.btn-del-scen', '.btn-delete-scen'].map(sel => `${SCORECARD} ${sel}`).join(', ')]:
            deleteScenario,
        '#tbody-retirement-schedule tr, #scen-schedule-tbody tr': (tr) => {
            const firstCell = tr.cells && tr.cells[0] ? tr.cells[0].textContent : '';
            const yr = parseInt(tr.getAttribute('data-year') || firstCell, 10);
            if (!isNaN(yr)) inspectTimelineYear(yr);
        }
    };
    Object.entries(SCEN_ACTIONS).forEach(([selector, action]) => {
        handlers[selector.split(', ').map(sel => `${SCORECARD} ${sel}`).join(', ')] = (el) => {
            const scenId = scenIdOf(el);
            const scen = liveScenarios().find(s => s.id === scenId);
            if (scen) action(scen, scenId);
        };
    });
    return handlers;
};

/** Document-level listeners for the scorecard table, row menus and schedule; installed once, immune to morphs. */
export function installScorecardDelegation() {
    listenOnce(document, 'scorecard-menus', 'click', (e) => {
        if (!e.target.closest('.scorecard-row-menu-wrap')) closeAllRowMoreMenus();
    });
    listenOnce(document, 'scorecard-menus', 'keydown', (e) => {
        if (e.key === 'Escape') closeAllRowMoreMenus();
    });
    delegate(document, 'scorecard', () => ({ click: scorecardClicks() }));
}

export function bindScorecardTable(tbody, data) {
    if (!tbody || !data) return;
    installScorecardDelegation();
    applyArchivedVisibility();
    initScenarioDragAndDrop();
}

export function bindScheduleTable(schedTbody) {
    if (!schedTbody) return;
    installScorecardDelegation();
    schedTbody.querySelectorAll('tr').forEach(tr => { tr.style.cursor = 'pointer'; });
}
