/**
 * Life-Event Wizard Modals and Master Event Catalog Modal
 * Extracted from static/js/scenarios/modals.js for modular separation of life-event wizard and catalog dialog logic.
 */

import {
    setSelectedEventIcon,
    renderEventIconPickerGrid,
    filterWizardTemplateOptions,
    TEMPLATE_DEFAULT_ICONS,
    TEMPLATE_SEARCH_KEYWORDS
} from './event_modals_presets.js';
import {
    syncRefinanceFields,
    setCollegeSourceMode,
    setEduSourceMode,
    getWizardPanels,
    updateWizardPanels
} from './event_modals_fields.js';
import {
    syncCapitalOutflowFields,
    syncCapitalInflowFields,
    syncRealEstateActionFields,
    syncRenovationFields,
    syncSabbaticalFields,
    syncGradSchoolFields,
    syncPhilanthropyDafFields,
    syncStateRelocationFields,
    syncRothConversionFields,
    syncSuperfund529Fields,
    syncPeCapitalCallFields,
    syncLtcInsuranceFields,
    syncMaritalSettlementFields
} from './event_modals_syncers.js';
import { buildEventPayload, submitSaveEvent } from './event_modals_save.js';
import { populateWizardDynamicDropdowns, openEditEventModal } from './event_modals_render.js';
import { cloneEvent, renderCatalogModalList, initCatalogModalControls } from './event_modals_catalog.js';
import { initEventWizardControls } from './event_modals_wizard.js';

export {
    setSelectedEventIcon,
    renderEventIconPickerGrid,
    filterWizardTemplateOptions,
    TEMPLATE_DEFAULT_ICONS,
    TEMPLATE_SEARCH_KEYWORDS,
    syncRefinanceFields,
    setCollegeSourceMode,
    setEduSourceMode,
    getWizardPanels,
    updateWizardPanels,
    syncCapitalOutflowFields,
    syncCapitalInflowFields,
    syncRealEstateActionFields,
    syncRenovationFields,
    syncSabbaticalFields,
    syncGradSchoolFields,
    syncPhilanthropyDafFields,
    syncStateRelocationFields,
    syncRothConversionFields,
    syncSuperfund529Fields,
    syncPeCapitalCallFields,
    syncLtcInsuranceFields,
    syncMaritalSettlementFields,
    buildEventPayload,
    submitSaveEvent,
    populateWizardDynamicDropdowns,
    openEditEventModal,
    cloneEvent,
    renderCatalogModalList,
    initCatalogModalControls,
    initEventWizardControls
};

export async function openCreateEventModal(initialTemplate = 'capital_outflow') {
    const modalEvt = document.getElementById('modal-event');
    if (!modalEvt) return;

    const tpl = (typeof initialTemplate === 'string' && initialTemplate.trim()) ? initialTemplate.trim() : 'capital_outflow';
    const newId = `evt_${Date.now()}`;
    document.getElementById('modal-event-title').textContent = 'Add Life Event';
    document.getElementById('input-event-id').value = newId;
    document.getElementById('input-event-name').value = '';
    document.getElementById('input-event-year').value = 2027;
    document.getElementById('input-event-end-year').value = 2027;
    document.getElementById('input-event-desc').value = '';
    const amtEl = document.getElementById('input-event-amount');
    if (amtEl) amtEl.value = 50000;

    const btnCloneEvt = document.getElementById('modal-btn-clone-event');
    if (btnCloneEvt) btnCloneEvt.style.display = 'none';

    await populateWizardDynamicDropdowns();

    setSelectedEventIcon(TEMPLATE_DEFAULT_ICONS[tpl] || 'evt-capital-outflow', false, true);
    const selectTemplate = document.getElementById('select-event-template');
    if (selectTemplate) {
        selectTemplate.value = tpl;
        updateWizardPanels(tpl);
    }

    modalEvt.style.display = 'flex';
}

if (typeof window !== 'undefined') {
    window.openCreateEventModal = openCreateEventModal;
    window.cloneEvent = cloneEvent;
    window.openEditEventModal = openEditEventModal;
    window.renderCatalogModalList = renderCatalogModalList;
}
