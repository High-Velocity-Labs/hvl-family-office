/**
 * Scenario Plan Modal Creation & Lifecycle
 * Handlers for opening new scenario modal dialogs, scenario routing, and cloning.
 */
import {
    state, escapeHtml, fmtCurrency, fmtShortCurrency
} from './state.js';
import { morphScenariosSection } from './main.js';
import {
    getModalScenarioObj, setModalScenarioObj,
    getModalSelectedEventIds, setModalSelectedEventIds,
    setModalEventsSearchQuery, updateModalEventsCountBadge,
    setModalScenarioTab, renderModalScenarioEventsList
} from './modals_plan_state.js';
import { openEditScenarioModal } from './modals_plan_edit.js';

export { openEditScenarioModal };

const fetchScenariosData = (...args) => (
    typeof morphScenariosSection === 'function'
        ? morphScenariosSection(...args)
        : (typeof window !== 'undefined' && window.fetchScenariosData ? window.fetchScenariosData(...args) : Promise.resolve())
);
const showModalAlert = (...args) => (
    typeof window !== 'undefined' && window.showModalAlert
        ? window.showModalAlert(...args)
        : (typeof alert === 'function' ? Promise.resolve(alert(args[0])) : Promise.resolve())
);

export function openNewChildScenarioModal(parentScenId = null) {
    const parentId = parentScenId || state.selectedScenarioId || state.scenariosData?.active_scenario_id || 'scen_baseline';
    openNewScenarioModal('assumptions', parentId, true);
}

export function openNewScenarioModal(defaultTab = 'assumptions', targetParentId = null, isExplicitChildCreation = false) {
    const modalScen = document.getElementById('modal-scenario');
    const panelPreset = document.getElementById('panel-scenario-preset-select');
    const selectPreset = document.getElementById('select-scenario-preset');
    const selScenEquity = document.getElementById('select-scenario-equity-preset');
    const groupScenCustomEquity = document.getElementById('group-scenario-custom-equity-growth');
    const inputScenCustomEquity = document.getElementById('input-scenario-custom-equity-growth');
    if (!modalScen) return;

    const allScens = state.scenariosData?.scenarios || [];
    let effectiveParentId = targetParentId;
    if (!effectiveParentId && isExplicitChildCreation) {
        effectiveParentId = state.selectedScenarioId || state.scenariosData?.active_scenario_id || 'scen_baseline';
    }
    const parentScen = effectiveParentId ? allScens.find(s => s.id === effectiveParentId) : null;

    const newScenObj = { id: 'scen_' + Date.now(), name: '', event_ids: [], parent_id: effectiveParentId || null };
    setModalScenarioObj(newScenObj);
    setModalSelectedEventIds(new Set(parentScen ? (parentScen.event_ids || []) : []));
    setModalEventsSearchQuery('');

    const titleEl = document.getElementById('modal-scenario-title');
    const subEl = document.getElementById('modal-scenario-subtitle');
    const nameInput = document.getElementById('input-scenario-name');
    const descInput = document.getElementById('input-scenario-desc');
    const colorInput = document.getElementById('input-scenario-color');

    const colors = ['#1D4ED8', '#059669', '#0284C7', '#D97706', '#64748B', '#0D9488'];
    const chosenColor = colors[allScens.length % colors.length];

    if (isExplicitChildCreation && parentScen) {
        if (titleEl) titleEl.textContent = 'Create Child Plan';
        if (subEl) subEl.textContent = `Branching from "${parentScen.name}". All timeline assumptions and events are dynamically inherited.`;
        if (nameInput) {
            nameInput.value = '';
            nameInput.placeholder = `e.g., ${parentScen.name} (With College)`;
        }
        if (descInput) {
            descInput.value = `Child plan branching from ${parentScen.name}.`;
        }
    } else {
        if (titleEl) titleEl.textContent = 'New Plan';
        if (subEl) subEl.textContent = 'Configure assumptions, spending targets, and financial events for this plan.';
        if (nameInput) {
            nameInput.value = '';
            nameInput.placeholder = 'e.g. Early Retirement, Sabbatical, Relocation';
        }
        if (descInput) {
            descInput.value = '';
        }
    }

    const modalBtnDelete = document.getElementById('modal-btn-delete-scenario');
    if (modalBtnDelete) modalBtnDelete.style.display = 'none';

    document.getElementById('input-scenario-id').value = newScenObj.id;
    if (colorInput) colorInput.value = chosenColor;
    document.getElementById('input-scenario-spend').value = '';
    const inputSavings = document.getElementById('input-scenario-savings');
    if (inputSavings) inputSavings.value = '';
    const inputInflation = document.getElementById('input-scenario-inflation');
    if (inputInflation) inputInflation.value = '';
    document.getElementById('input-scenario-ret-age').value = '';
    const inputRetSpouse = document.getElementById('input-scenario-ret-spouse');
    if (inputRetSpouse) inputRetSpouse.value = '';
    const inputPriSs = document.getElementById('input-scenario-primary-ss-age');
    if (inputPriSs) inputPriSs.value = '';
    const inputSpouseSs = document.getElementById('input-scenario-spouse-ss-age');
    if (inputSpouseSs) inputSpouseSs.value = '';
    const hasParent = Boolean(effectiveParentId || isExplicitChildCreation);
    if (selScenEquity) selScenEquity.value = hasParent ? 'inherit' : 'moderate';
    if (groupScenCustomEquity) groupScenCustomEquity.style.display = 'none';
    if (inputScenCustomEquity) inputScenCustomEquity.value = '';

    const spendInput = document.getElementById('input-scenario-spend');
    if (spendInput) {
        spendInput.value = '';
        spendInput.placeholder = parentScen?.annual_living_spend ? `Inherited: $${Math.round(parentScen.annual_living_spend).toLocaleString()}/yr (blank = inherit)` : 'Blank = inherit parent';
    }

    const assetGrowthPlaceholders = {
        'input-scenario-growth-us': parentScen?.growth_us_equity ? `Inherited: ${(parentScen.growth_us_equity * 100).toFixed(1)}% (blank = inherit)` : 'e.g. 0.085 for 8.5% (blank = inherit)',
        'input-scenario-growth-intl': parentScen?.growth_intl_equity ? `Inherited: ${(parentScen.growth_intl_equity * 100).toFixed(1)}% (blank = inherit)` : 'e.g. 0.070 for 7.0% (blank = inherit)',
        'input-scenario-growth-bonds': parentScen?.growth_bonds ? `Inherited: ${(parentScen.growth_bonds * 100).toFixed(1)}% (blank = inherit)` : 'e.g. 0.045 for 4.5% (blank = inherit)',
        'input-scenario-growth-cash': parentScen?.growth_cash ? `Inherited: ${(parentScen.growth_cash * 100).toFixed(1)}% (blank = inherit)` : 'e.g. 0.035 for 3.5% (blank = inherit)',
        'input-scenario-growth-private': parentScen?.growth_private_investments ? `Inherited: ${(parentScen.growth_private_investments * 100).toFixed(1)}% (blank = inherit)` : 'e.g. 0.100 for 10.0% (blank = inherit)',
        'input-scenario-growth-re': parentScen?.growth_real_estate ? `Inherited: ${(parentScen.growth_real_estate * 100).toFixed(1)}% (blank = inherit)` : 'e.g. 0.035 for 3.5% (blank = inherit)',
    };
    Object.entries(assetGrowthPlaceholders).forEach(([id, ph]) => {
        const el = document.getElementById(id);
        if (el) {
            el.value = '';
            el.placeholder = ph;
        }
    });

    const selParent = document.getElementById('select-scenario-parent');
    const groupParent = document.getElementById('group-scenario-parent-select');
    if (selParent) {
        if (groupParent) groupParent.style.display = 'block';
        selParent.innerHTML = '<option value="">None (Independent Root Plan)</option>';
        allScens.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.id;
            opt.textContent = `${s.name}${s.parent_name ? ' (↳ Child of ' + s.parent_name + ')' : ''}`;
            if (effectiveParentId && s.id === effectiveParentId) {
                opt.selected = true;
            } else if (!effectiveParentId && s.id === 'scen_baseline') {
                opt.selected = true;
            }
            selParent.appendChild(opt);
        });

        if (!selParent.dataset.wiredEvents) {
            selParent.dataset.wiredEvents = 'true';
            selParent.addEventListener('change', () => {
                const mObj = getModalScenarioObj();
                if (mObj) {
                    mObj.parent_id = selParent.value || null;
                    const newParent = (state.scenariosData?.scenarios || []).find(s => s.id === selParent.value);
                    const curSelected = getModalSelectedEventIds();
                    if (newParent && (!curSelected || curSelected.size === 0)) {
                        setModalSelectedEventIds(new Set(newParent.event_ids || []));
                    }
                    renderModalScenarioEventsList(state.scenariosData);
                    updateModalEventsCountBadge();
                }
            });
        }
    }

    const badgeEquity = document.getElementById('modal-scen-equity-company-badge');
    const companies = state.scenariosData?.equity_companies || [];
    if (badgeEquity && companies.length) {
        const comp = companies[0];
        badgeEquity.textContent = `${comp.company_name} (${comp.current_fmv ? fmtCurrency(comp.current_fmv, 2) : 'FMV Pending'})`;
    }

    if (panelPreset) panelPreset.style.display = isExplicitChildCreation ? 'none' : 'block';
    if (selectPreset) {
        selectPreset.value = 'custom';
        const optgroup = document.getElementById('optgroup-scenario-budget-presets');
        if (optgroup && state.scenariosData?.scenario_templates) {
            const budgetTemplates = state.scenariosData.scenario_templates.filter(t => t.id && t.id.startsWith('template_budget_'));
            if (budgetTemplates.length > 0) {
                optgroup.innerHTML = budgetTemplates.map(t => {
                    const cleanName = (t.name || '').replace('Budget Preset: ', '');
                    const spendVal = t.annual_living_spend ? ` (${fmtShortCurrency(t.annual_living_spend)}/yr spend)` : '';
                    return `<option value="${escapeHtml(t.id)}">${escapeHtml(cleanName)}${spendVal}</option>`;
                }).join('');
            }
        }
    }

    updateModalEventsCountBadge();
    setModalScenarioTab(defaultTab);
    modalScen.style.display = 'flex';
}

export function openScenarioModal(scen = null, parentId = null) {
    if (scen) {
        openEditScenarioModal(scen);
    } else if (parentId) {
        openNewChildScenarioModal(parentId);
    } else {
        openNewScenarioModal();
    }
}

export async function cloneScenario(sourceOrId) {
    const sourceId = (typeof sourceOrId === 'object' && sourceOrId !== null) ? sourceOrId.id : sourceOrId;
    if (!sourceId) return;
    const statusEl = document.getElementById('scen-assumptions-status');
    if (statusEl) {
        statusEl.textContent = 'Cloning scenario...';
        statusEl.style.color = 'var(--accent-orange)';
    }
    try {
        const resp = await fetch(`/api/scenarios/${encodeURIComponent(sourceId)}/clone`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const res = await resp.json();
        if (resp.ok && res.success && res.scenario) {
            const containerScorecard = document.getElementById('container-side-by-side-scorecard');
            const btnToggleScorecard = document.getElementById('btn-toggle-scorecard-table');
            if (containerScorecard && containerScorecard.style.display === 'none') {
                containerScorecard.style.display = 'block';
                if (btnToggleScorecard) {
                    btnToggleScorecard.classList.add('active');
                }
            }

            await fetchScenariosData();

            if (statusEl) {
                statusEl.textContent = `✓ Created plan "${res.scenario.name}"!`;
                statusEl.style.color = 'var(--accent-green, #10B981)';
                setTimeout(() => { if (statusEl) statusEl.textContent = ''; }, 3500);
            }

            openEditScenarioModal(res.scenario, 'assumptions');
            setTimeout(() => {
                const nameInput = document.getElementById('input-scenario-name');
                if (nameInput) {
                    nameInput.focus();
                    nameInput.select();
                }
            }, 80);
        } else {
            if (statusEl) statusEl.textContent = '';
            await showModalAlert(res.error || 'Failed to clone scenario', { title: 'Unable to Clone Scenario', type: 'error' });
        }
    } catch (err) {
        console.error('Failed to clone scenario:', err);
        if (statusEl) statusEl.textContent = '';
        await showModalAlert('Failed to clone scenario: ' + err.message, { title: 'Unable to Clone Scenario', type: 'error' });
    }
}
