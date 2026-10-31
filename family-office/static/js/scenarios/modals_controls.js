/**
 * Scenario Plan Modal Controls & Event Handlers
 * Wires DOM listeners for scenario creation, editing form submissions, preset loading, cloning, and deletion.
 */
import { state } from './state.js';
import { delegate } from './event_delegation.js';
import { morphScenariosSection } from './main.js';
import { openCreateEventModal, openEditEventModal, renderCatalogModalList } from './event_modals.js';
import {
    openNewScenarioModal, openNewChildScenarioModal, cloneScenario,
    syncScenarioColorSwatches, syncModalFieldInheritanceUI
} from './modals_plan.js';
import {
    getModalSelectedEventIds, setModalSelectedEventIds,
    setModalEventsSearchQuery, toggleAllChecklistGroups, updateModalEventsCountBadge,
    setModalScenarioTab, renderModalScenarioEventsList
} from './modals_plan_state.js';

const fetchScenariosData = morphScenariosSection;
const showModalConfirm = (...args) => window.showModalConfirm(...args);
const showModalAlert = (...args) => window.showModalAlert(...args);

const SAVE_ERROR = { title: 'Unable to Save Scenario', type: 'error' };
const DELETE_ERROR = { title: 'Delete Error', type: 'error' };

const hideScenModal = () => {
    const modalScen = document.getElementById('modal-scenario');
    if (modalScen) modalScen.style.display = 'none';
};

function applyScenarioPreset(select) {
    const val = select.value;
    if (val === 'custom') return;
    const templates = (state.scenariosData && state.scenariosData.scenario_templates) || [];
    const tmpl = templates.find(t => t.id === val);
    if (!tmpl) return;
    const selScenEquity = document.getElementById('select-scenario-equity-preset');
    const groupScenCustomEquity = document.getElementById('group-scenario-custom-equity-growth');
    document.getElementById('input-scenario-name').value = tmpl.name;
    document.getElementById('input-scenario-desc').value = tmpl.description || '';
    const tmplColor = tmpl.color || '#1D4ED8';
    document.getElementById('input-scenario-color').value = tmplColor;
    syncScenarioColorSwatches(tmplColor);
    if (tmpl.annual_living_spend) {
        document.getElementById('input-scenario-spend').value = tmpl.annual_living_spend;
    }
    if (tmpl.equity_growth_preset && selScenEquity) {
        selScenEquity.value = tmpl.equity_growth_preset;
        if (groupScenCustomEquity) {
            groupScenCustomEquity.style.display = (tmpl.equity_growth_preset === 'custom') ? 'block' : 'none';
        }
    }
    if (tmpl.event_ids) {
        setModalSelectedEventIds(new Set(tmpl.event_ids));
        updateModalEventsCountBadge();
        renderModalScenarioEventsList(state.scenariosData);
    }
    syncModalFieldInheritanceUI();
}

function openEventCatalog() {
    const modalCatalog = document.getElementById('modal-events-catalog');
    if (!modalCatalog) return;
    modalCatalog.style.display = 'flex';
    if (state.scenariosData) renderCatalogModalList(state.scenariosData);
}

async function saveScenarioForm(form, e) {
    e.preventDefault();
    const id = document.getElementById('input-scenario-id').value;
    const name = document.getElementById('input-scenario-name').value;
    const desc = document.getElementById('input-scenario-desc').value;
    const color = document.getElementById('input-scenario-color').value;
    const spendVal = document.getElementById('input-scenario-spend').value;
    const retAgeVal = document.getElementById('input-scenario-ret-age').value;
    const retSpouseVal = document.getElementById('input-scenario-ret-spouse')?.value;
    const rawGrowthPreset = document.getElementById('select-scenario-equity-preset')?.value;
    const growthPreset = (rawGrowthPreset === 'inherit' || !rawGrowthPreset) ? null : rawGrowthPreset;
    const customGrowthVal = document.getElementById('input-scenario-custom-equity-growth')?.value;

    const savingsVal = document.getElementById('input-scenario-savings')?.value;
    const inflationVal = document.getElementById('input-scenario-inflation')?.value;
    const priSsVal = document.getElementById('input-scenario-primary-ss-age')?.value;
    const spouseSsVal = document.getElementById('input-scenario-spouse-ss-age')?.value;

    const parentIdVal = document.getElementById('select-scenario-parent')?.value || null;
    const parentId = (id === 'scen_baseline') ? null : (parentIdVal || null);
    const selectedSet = getModalSelectedEventIds();
    const finalEventIds = Array.from(selectedSet);
    let excludedEventIds = [];
    let addedEventIds = [];
    if (parentId) {
        const parentScen = (state.scenariosData?.scenarios || []).find(s => s.id === parentId);
        const curScen = (state.scenariosData?.scenarios || []).find(s => s.id === id);
        const isMergedOverlay = Boolean(curScen?.is_baseline_layer && parentId === 'scen_baseline');
        const useRawEvents = isMergedOverlay && Array.isArray(parentScen?.raw_event_ids);
        const parentIds = useRawEvents ? parentScen.raw_event_ids : (parentScen?.event_ids || []);
        const parentEvents = new Set(parentIds);
        excludedEventIds = Array.from(parentEvents).filter(eid => !selectedSet.has(eid));
        addedEventIds = finalEventIds.filter(eid => !parentEvents.has(eid));
    }

    const parseGrowthInput = (elId) => {
        const v = document.getElementById(elId)?.value;
        if (v === '' || v === null || v === undefined) return null;
        const parsed = parseFloat(v);
        if (isNaN(parsed)) return null;
        return parsed > 1.0 ? parsed / 100 : parsed;
    };

    const payload = {
        id,
        name,
        description: desc,
        color,
        parent_id: parentId,
        event_ids: finalEventIds,
        excluded_event_ids: excludedEventIds,
        added_event_ids: addedEventIds,
        annual_living_spend: spendVal ? parseFloat(spendVal) : null,
        annual_savings: savingsVal ? parseFloat(savingsVal) : null,
        inflation_rate: inflationVal ? parseFloat(inflationVal) : null,
        primary_retirement_age: retAgeVal ? parseInt(retAgeVal) : null,
        spouse_retirement_age: retSpouseVal ? parseInt(retSpouseVal) : null,
        primary_ss_claim_age: priSsVal ? parseInt(priSsVal) : null,
        spouse_ss_claim_age: spouseSsVal ? parseInt(spouseSsVal) : null,
        ss_claim_age: priSsVal ? parseInt(priSsVal) : null,
        equity_growth_preset: growthPreset,
        custom_equity_growth_rate: (growthPreset === 'custom' && customGrowthVal) ? parseFloat(customGrowthVal) : null,
        growth_us_equity: parseGrowthInput('input-scenario-growth-us'),
        growth_intl_equity: parseGrowthInput('input-scenario-growth-intl'),
        growth_bonds: parseGrowthInput('input-scenario-growth-bonds'),
        growth_cash: parseGrowthInput('input-scenario-growth-cash'),
        growth_private_investments: parseGrowthInput('input-scenario-growth-private'),
        growth_real_estate: parseGrowthInput('input-scenario-growth-re'),
    };

    try {
        const resp = await fetch('/api/scenarios', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const res = await resp.json();
        if (resp.ok && res.success) {
            hideScenModal();
            await fetchScenariosData();
        } else {
            await showModalAlert(res.error || 'Failed to save scenario', SAVE_ERROR);
        }
    } catch (err) {
        await showModalAlert('Save failed: ' + err.message, SAVE_ERROR);
    }
}

function cloneFromModal() {
    const id = document.getElementById('input-scenario-id')?.value || state.selectedScenarioId;
    if (id) {
        hideScenModal();
        cloneScenario(id);
    }
}

async function deleteScenarioFromModal() {
    const id = document.getElementById('input-scenario-id')?.value || state.selectedScenarioId;
    if (!id || id === 'scen_baseline') return;
    const scenObj = (state.scenariosData && state.scenariosData.scenarios || []).find(s => s.id === id);
    const name = scenObj ? scenObj.name : 'this plan';

    const allScens = (state.scenariosData && state.scenariosData.scenarios) || [];
    const childPlans = allScens.filter(s => s.parent_id === id);
    let confirmMsg = `Permanently delete plan "${name}"?`;
    if (childPlans.length > 0) {
        confirmMsg = `Permanently delete plan "${name}" and its ${childPlans.length} child plan(s)? `
            + 'Deleting a parent plan will also delete all child plans branching from it.';
    }

    const confirmed = await showModalConfirm(confirmMsg, {
        title: 'Delete Plan', confirmText: 'Delete Plan', confirmVariant: 'danger'
    });
    if (confirmed) {
        hideScenModal();
        try {
            const resp = await fetch(`/api/scenarios/${id}`, { method: 'DELETE' });
            const res = await resp.json();
            if (res.success) {
                const deletedSelected = res.deleted_ids && res.deleted_ids.includes(state.selectedScenarioId);
                if (state.selectedScenarioId === id || deletedSelected) {
                    state.selectedScenarioId = 'scen_baseline';
                }
                await fetchScenariosData();
            } else {
                await showModalAlert(`Delete failed: ${res.error || 'Unknown error'}`, DELETE_ERROR);
            }
        } catch (err) {
            console.error('Delete plan error:', err);
            await showModalAlert(`Failed to delete plan: ${err.message}`, { title: 'Delete Error', type: 'error' });
        }
    }
}

/** Document-level listeners for the plan modal and its launch buttons; installed once, immune to morphs. */
export function initScenarioModalControls() {
    delegate(document, 'scenario-modal-controls', () => ({
        click: {
            'btn-create-scenario': () => openNewScenarioModal(),
            'btn-create-child-scenario': () => openNewChildScenarioModal(state.selectedScenarioId),
            'btn-card-create-child': () => openNewChildScenarioModal(state.selectedScenarioId),
            'tab-modal-scen-assumptions': () => setModalScenarioTab('assumptions'),
            'tab-modal-scen-events': () => setModalScenarioTab('events'),
            'modal-btn-open-catalog': openEventCatalog,
            'modal-btn-add-event': () => openCreateEventModal(),
            '#modal-scenario-event-checklist .btn-edit-event, #modal-scenario-event-checklist .btn-name-edit-event':
                (trigger) => openEditEventModal(trigger.dataset.id),
            'modal-btn-toggle-all-accordions': (btn) => { btn.textContent = toggleAllChecklistGroups(); },
            'btn-close-modal-scenario': hideScenModal,
            'btn-cancel-modal-scenario': hideScenModal,
            'modal-btn-clone-scenario': cloneFromModal,
            'modal-btn-delete-scenario': deleteScenarioFromModal
        },
        change: {
            'select-scenario-equity-preset': (el) => {
                const group = document.getElementById('group-scenario-custom-equity-growth');
                if (group) group.style.display = (el.value === 'custom') ? 'block' : 'none';
            },
            'select-scenario-preset': applyScenarioPreset
        },
        input: {
            'modal-input-search-scenario-events': (el) => {
                setModalEventsSearchQuery(el.value);
                renderModalScenarioEventsList(state.scenariosData);
            }
        },
        submit: { 'form-scenario': saveScenarioForm }
    }));
}
