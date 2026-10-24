/**
 * static/js/scenarios/cards_scorecard.js
 * Scorecard and spend-down schedule table bindings for scenarios view.
 */

import { state, fmtShortCurrency } from './state.js';
import { inspectTimelineYear } from './scrubber.js';
import { openScenarioModal, cloneScenario } from './modals.js';
import { morphScenariosSection } from './main.js';

const showModalAlert = (...args) => (
    typeof window !== 'undefined' && window.showModalAlert
        ? window.showModalAlert(...args)
        : Promise.resolve()
);

const showModalConfirm = (...args) => (
    typeof window !== 'undefined' && window.showModalConfirm
        ? window.showModalConfirm(...args)
        : Promise.resolve(true)
);

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

export function bindScorecardTable(tbody, data) {
    if (!tbody || !data) return;

    tbody.querySelectorAll('.scorecard-parent-link').forEach(badge => {
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

    tbody.querySelectorAll('.scorecard-scen-title, .btn-view-scenario, .btn-select-scen').forEach(el => {
        if (!el.dataset.ssrWired) {
            el.dataset.ssrWired = 'true';
            el.addEventListener('click', () => {
                const scenId = el.getAttribute('data-scen-id') || el.getAttribute('data-id');
                if (scenId && typeof window.switchToScenario === 'function') {
                    window.switchToScenario(scenId);
                }
            });
        }
    });

    tbody.querySelectorAll('.btn-manage-scen-events').forEach(btn => {
        if (!btn.dataset.ssrWired) {
            btn.dataset.ssrWired = 'true';
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const scenId = btn.getAttribute('data-scen-id') || btn.getAttribute('data-id');
                const scen = (data.scenarios || []).find(s => s.id === scenId);
                if (scen) {
                    openScenarioModal(scen);
                    setTimeout(() => {
                        const evSection = document.getElementById('scenario-events-checklist');
                        if (evSection) evSection.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    }, 100);
                }
            });
        }
    });

    const toggleRowEvents = (scenId) => {
        const expDiv = document.getElementById(`scen-events-exp-${scenId}`);
        const iconsDiv = document.getElementById(`scen-events-icons-${scenId}`);
        const liveTbody = document.getElementById('tbody-scenarios-scorecard') || tbody;
        const chev = liveTbody ? liveTbody.querySelector(`.scen-evt-chevron[data-id="${scenId}"]`) : null;
        if (!expDiv) return;
        const isHidden = expDiv.style.display === 'none' || !expDiv.style.display;
        expDiv.style.display = isHidden ? 'flex' : 'none';
        if (iconsDiv) iconsDiv.style.display = isHidden ? 'none' : 'inline-flex';
        if (chev) chev.textContent = isHidden ? '▼' : '▶';
    };

    tbody.querySelectorAll('.btn-toggle-scen-events').forEach(btn => {
        btn.onclick = (e) => {
            e.stopPropagation();
            toggleRowEvents(btn.getAttribute('data-scen-id') || btn.getAttribute('data-id'));
        };
    });

    tbody.querySelectorAll('.event-icon-chip').forEach(chip => {
        chip.onclick = (e) => {
            e.stopPropagation();
            toggleRowEvents(chip.getAttribute('data-scen-id') || chip.getAttribute('data-id'));
        };
    });

    tbody.querySelectorAll('.btn-remove-scen-event').forEach(btn => {
        if (!btn.dataset.ssrWired) {
            btn.dataset.ssrWired = 'true';
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const scenId = btn.getAttribute('data-scen-id');
                const evtId = btn.getAttribute('data-event-id');
                const scenObj = (data.scenarios || []).find(s => s.id === scenId);
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
            });
        }
    });

    tbody.querySelectorAll('.btn-edit-scenario, .btn-edit-scen').forEach(btn => {
        if (!btn.dataset.ssrWired) {
            btn.dataset.ssrWired = 'true';
            btn.addEventListener('click', () => {
                const scenId = btn.getAttribute('data-scen-id') || btn.getAttribute('data-id');
                const scen = (data.scenarios || []).find(s => s.id === scenId);
                if (scen) openScenarioModal(scen);
            });
        }
    });

    tbody.querySelectorAll('.btn-clone-scenario, .btn-clone-scen').forEach(btn => {
        if (!btn.dataset.ssrWired) {
            btn.dataset.ssrWired = 'true';
            btn.addEventListener('click', () => {
                const scenId = btn.getAttribute('data-scen-id') || btn.getAttribute('data-id');
                const scen = (data.scenarios || []).find(s => s.id === scenId);
                if (scen) cloneScenario(scen);
            });
        }
    });

    tbody.querySelectorAll('.btn-branch-child-scenario, .btn-child-scen').forEach(btn => {
        if (!btn.dataset.ssrWired) {
            btn.dataset.ssrWired = 'true';
            btn.addEventListener('click', () => {
                const parentId = btn.getAttribute('data-scen-id') || btn.getAttribute('data-id');
                if (parentId) openScenarioModal(null, parentId);
            });
        }
    });

    tbody.querySelectorAll('.btn-set-active-scenario, .btn-SetActive-scen').forEach(btn => {
        if (!btn.dataset.ssrWired) {
            btn.dataset.ssrWired = 'true';
            btn.addEventListener('click', async () => {
                const scenId = btn.getAttribute('data-scen-id') || btn.getAttribute('data-id');
                if (scenId && typeof window.switchToScenario === 'function') {
                    await window.switchToScenario(scenId);
                }
            });
        }
    });

    tbody.querySelectorAll('.btn-delete-scenario, .btn-del-scen, .btn-delete-scen').forEach(btn => {
        if (!btn.dataset.ssrWired) {
            btn.dataset.ssrWired = 'true';
            btn.addEventListener('click', async () => {
                const scenId = btn.getAttribute('data-scen-id') || btn.getAttribute('data-id');
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
            });
        }
    });
}

export function bindScheduleTable(schedTbody) {
    if (!schedTbody) return;
    schedTbody.querySelectorAll('tr').forEach(tr => {
        if (!tr.dataset.ssrWired) {
            tr.dataset.ssrWired = 'true';
            tr.style.cursor = 'pointer';
            tr.addEventListener('click', () => {
                const yrAttr = tr.getAttribute('data-year');
                const yrText = tr.cells && tr.cells[0] ? tr.cells[0].textContent : '';
                const yr = parseInt(yrAttr || yrText, 10);
                if (!isNaN(yr)) {
                    inspectTimelineYear(yr);
                }
            });
        }
    });
}
