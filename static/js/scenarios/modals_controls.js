/**
 * Scenario Plan Modal Controls & Event Handlers
 * Wires DOM listeners for scenario creation, editing form submissions, preset loading, cloning, and deletion.
 */
import { state, EVENT_CATEGORY_GROUPS } from './state.js';
import { morphScenariosSection } from './main.js';
import { openCreateEventModal, renderCatalogModalList } from './event_modals.js';
import {
    openNewScenarioModal, openNewChildScenarioModal, openEditScenarioModal, cloneScenario
} from './modals_plan.js';
import {
    getModalSelectedEventIds, setModalSelectedEventIds,
    setModalEventsSearchQuery, getModalExpandedCategoryGroups,
    setModalExpandedCategoryGroups, updateModalEventsCountBadge,
    setModalScenarioTab, renderModalScenarioEventsList
} from './modals_plan_state.js';

const fetchScenariosData = (...args) => (
    typeof morphScenariosSection === 'function'
        ? morphScenariosSection(...args)
        : (typeof window !== 'undefined' && window.fetchScenariosData ? window.fetchScenariosData(...args) : Promise.resolve())
);
const showModalConfirm = (...args) => (typeof window !== 'undefined' && window.showModalConfirm ? window.showModalConfirm(...args) : Promise.resolve(true));
const showModalAlert = (...args) => (typeof window !== 'undefined' && window.showModalAlert ? window.showModalAlert(...args) : (typeof alert === 'function' ? Promise.resolve(alert(args[0])) : Promise.resolve()));

export function initScenarioModalControls() {
    const btnCreateScen = document.getElementById('btn-create-scenario');
    const btnEditSelectedScen = document.getElementById('btn-edit-selected-scenario');
    const modalScen = document.getElementById('modal-scenario');
    const btnCloseScen = document.getElementById('btn-close-modal-scenario');
    const btnCancelScen = document.getElementById('btn-cancel-modal-scenario');
    const formScen = document.getElementById('form-scenario');
    const selectPreset = document.getElementById('select-scenario-preset');
    const selScenEquity = document.getElementById('select-scenario-equity-preset');
    const groupScenCustomEquity = document.getElementById('group-scenario-custom-equity-growth');
    const inputScenCustomEquity = document.getElementById('input-scenario-custom-equity-growth');

    if (selScenEquity && groupScenCustomEquity && !selScenEquity.dataset.wired) {
        selScenEquity.dataset.wired = 'true';
        selScenEquity.addEventListener('change', (e) => {
            groupScenCustomEquity.style.display = (e.target.value === 'custom') ? 'block' : 'none';
        });
    }

    const btnCreateChildScen = document.getElementById('btn-create-child-scenario');
    const btnCardCreateChild = document.getElementById('btn-card-create-child');

    if (btnCreateScen && modalScen && !btnCreateScen.dataset.wired) {
        btnCreateScen.dataset.wired = 'true';
        btnCreateScen.addEventListener('click', () => {
            openNewScenarioModal();
        });
    }

    if (btnCreateChildScen && !btnCreateChildScen.dataset.wired) {
        btnCreateChildScen.dataset.wired = 'true';
        btnCreateChildScen.addEventListener('click', () => {
            openNewChildScenarioModal(state.selectedScenarioId);
        });
    }

    if (btnCardCreateChild && !btnCardCreateChild.dataset.wired) {
        btnCardCreateChild.dataset.wired = 'true';
        btnCardCreateChild.addEventListener('click', () => {
            openNewChildScenarioModal(state.selectedScenarioId);
        });
    }

    if (btnEditSelectedScen && !btnEditSelectedScen.dataset.wiredModal) {
        btnEditSelectedScen.dataset.wiredModal = 'true';
        btnEditSelectedScen.addEventListener('click', () => {
            if (!state.selectedScenarioId || !state.scenariosData) return;
            const scen = (state.scenariosData.scenarios || []).find(s => s.id === state.selectedScenarioId);
            if (scen) openEditScenarioModal(scen);
        });
    }

    if (selectPreset && !selectPreset.dataset.wired) {
        selectPreset.dataset.wired = 'true';
        selectPreset.addEventListener('change', (e) => {
            const val = e.target.value;
            if (val === 'custom') return;
            const templates = (state.scenariosData && state.scenariosData.scenario_templates) || [];
            const tmpl = templates.find(t => t.id === val);
            if (tmpl) {
                document.getElementById('input-scenario-name').value = tmpl.name;
                document.getElementById('input-scenario-desc').value = tmpl.description || '';
                document.getElementById('input-scenario-color').value = tmpl.color || '#1D4ED8';
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
            }
        });
    }

    const tabAssumptions = document.getElementById('tab-modal-scen-assumptions');
    const tabEvents = document.getElementById('tab-modal-scen-events');
    if (tabAssumptions && !tabAssumptions.dataset.wired) {
        tabAssumptions.dataset.wired = 'true';
        tabAssumptions.addEventListener('click', () => setModalScenarioTab('assumptions'));
    }
    if (tabEvents && !tabEvents.dataset.wired) {
        tabEvents.dataset.wired = 'true';
        tabEvents.addEventListener('click', () => setModalScenarioTab('events'));
    }

    const modalBtnOpenCat = document.getElementById('modal-btn-open-catalog');
    if (modalBtnOpenCat && !modalBtnOpenCat.dataset.wired) {
        modalBtnOpenCat.dataset.wired = 'true';
        modalBtnOpenCat.addEventListener('click', () => {
            const modalCatalog = document.getElementById('modal-events-catalog');
            if (modalCatalog) {
                modalCatalog.style.display = 'flex';
                if (state.scenariosData) renderCatalogModalList(state.scenariosData);
            }
        });
    }

    const modalBtnAddEv = document.getElementById('modal-btn-add-event');
    if (modalBtnAddEv && !modalBtnAddEv.dataset.wired) {
        modalBtnAddEv.dataset.wired = 'true';
        modalBtnAddEv.addEventListener('click', () => {
            openCreateEventModal();
        });
    }

    const modalSearchInput = document.getElementById('modal-input-search-scenario-events');
    if (modalSearchInput && !modalSearchInput.dataset.wired) {
        modalSearchInput.dataset.wired = 'true';
        modalSearchInput.addEventListener('input', (e) => {
            setModalEventsSearchQuery(e.target.value);
            renderModalScenarioEventsList(state.scenariosData);
        });
    }

    const modalToggleAllBtn = document.getElementById('modal-btn-toggle-all-accordions');
    if (modalToggleAllBtn && !modalToggleAllBtn.dataset.wired) {
        modalToggleAllBtn.dataset.wired = 'true';
        modalToggleAllBtn.addEventListener('click', () => {
            const allKeys = EVENT_CATEGORY_GROUPS.map(g => g.key);
            let groups = getModalExpandedCategoryGroups();
            const allExpanded = allKeys.every(k => groups && groups.has(k));
            if (!groups) groups = new Set();
            if (allExpanded) {
                groups.clear();
                modalToggleAllBtn.textContent = 'Expand All';
            } else {
                allKeys.forEach(k => groups.add(k));
                modalToggleAllBtn.textContent = 'Collapse All';
            }
            setModalExpandedCategoryGroups(groups);
            renderModalScenarioEventsList(state.scenariosData);
        });
    }

    const hideScenModal = () => { if (modalScen) modalScen.style.display = 'none'; };
    if (btnCloseScen && !btnCloseScen.dataset.wired) {
        btnCloseScen.dataset.wired = 'true';
        btnCloseScen.addEventListener('click', hideScenModal);
    }
    if (btnCancelScen && !btnCancelScen.dataset.wired) {
        btnCancelScen.dataset.wired = 'true';
        btnCancelScen.addEventListener('click', hideScenModal);
    }

    if (formScen && !formScen.dataset.wired) {
        formScen.dataset.wired = 'true';
        formScen.addEventListener('submit', async (e) => {
            e.preventDefault();
            const id = document.getElementById('input-scenario-id').value;
            const name = document.getElementById('input-scenario-name').value;
            const desc = document.getElementById('input-scenario-desc').value;
            const color = document.getElementById('input-scenario-color').value;
            const spendVal = document.getElementById('input-scenario-spend').value;
            const retAgeVal = document.getElementById('input-scenario-ret-age').value;
            const retSpouseVal = document.getElementById('input-scenario-ret-spouse')?.value;
            const rawGrowthPreset = selScenEquity?.value;
            const growthPreset = (rawGrowthPreset === 'inherit' || !rawGrowthPreset) ? null : rawGrowthPreset;
            const customGrowthVal = inputScenCustomEquity?.value;

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
                const parentEvents = new Set(parentScen ? (parentScen.event_ids || []) : []);
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
                    await showModalAlert(res.error || 'Failed to save scenario', { title: 'Unable to Save Scenario', type: 'error' });
                }
            } catch (err) {
                await showModalAlert('Save failed: ' + err.message, { title: 'Unable to Save Scenario', type: 'error' });
            }
        });
    }

    const modalBtnClone = document.getElementById('modal-btn-clone-scenario');
    if (modalBtnClone && !modalBtnClone.dataset.wired) {
        modalBtnClone.dataset.wired = 'true';
        modalBtnClone.addEventListener('click', () => {
            const id = document.getElementById('input-scenario-id')?.value || state.selectedScenarioId;
            if (id) {
                hideScenModal();
                cloneScenario(id);
            }
        });
    }

    const modalBtnDelete = document.getElementById('modal-btn-delete-scenario');
    if (modalBtnDelete && !modalBtnDelete.dataset.wired) {
        modalBtnDelete.dataset.wired = 'true';
        modalBtnDelete.addEventListener('click', async () => {
            const id = document.getElementById('input-scenario-id')?.value || state.selectedScenarioId;
            if (!id || id === 'scen_baseline') return;
            const scenObj = (state.scenariosData && state.scenariosData.scenarios || []).find(s => s.id === id);
            const name = scenObj ? scenObj.name : 'this plan';

            const allScens = (state.scenariosData && state.scenariosData.scenarios) || [];
            const childPlans = allScens.filter(s => s.parent_id === id);
            let confirmMsg = `Permanently delete plan "${name}"?`;
            if (childPlans.length > 0) {
                confirmMsg = `Permanently delete plan "${name}" and its ${childPlans.length} child plan(s)? Deleting a parent plan will also delete all child plans branching from it.`;
            }

            if (await showModalConfirm(confirmMsg, { title: 'Delete Plan', confirmText: 'Delete Plan', confirmVariant: 'danger' })) {
                hideScenModal();
                try {
                    const resp = await fetch(`/api/scenarios/${id}`, { method: 'DELETE' });
                    const res = await resp.json();
                    if (res.success) {
                        if (state.selectedScenarioId === id || (res.deleted_ids && res.deleted_ids.includes(state.selectedScenarioId))) {
                            state.selectedScenarioId = 'scen_baseline';
                        }
                        await fetchScenariosData();
                    } else {
                        await showModalAlert(`Delete failed: ${res.error || 'Unknown error'}`, { title: 'Delete Error', type: 'error' });
                    }
                } catch (err) {
                    console.error('Delete plan error:', err);
                    await showModalAlert(`Failed to delete plan: ${err.message}`, { title: 'Delete Error', type: 'error' });
                }
            }
        });
    }
}
