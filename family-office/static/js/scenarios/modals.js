/**
 * Scenario Plan Configuration Dialog, Events Tab, and Event Checklist
 * Orchestrator module re-exporting life-event and scenario modal sub-modules.
 */
import {
    openCreateEventModal, openEditEventModal, cloneEvent,
    renderCatalogModalList, initEventWizardControls, initCatalogModalControls,
    populateWizardDynamicDropdowns, setCollegeSourceMode, setEduSourceMode,
    syncRefinanceFields
} from './event_modals.js';
import {
    setModalScenarioTab,
    updateModalEventsCountBadge,
    renderModalScenarioEventsList
} from './modals_plan_state.js';
import {
    openNewChildScenarioModal,
    openNewScenarioModal,
    openScenarioModal,
    cloneScenario
} from './modals_plan.js';
import { openEditScenarioModal } from './modals_plan_edit.js';
import { renderEventChecklistAndCatalog } from './modals_checklist.js';
import { initScenarioModalControls } from './modals_controls.js';

export {
    // Event modals re-exports
    openCreateEventModal, openEditEventModal, cloneEvent,
    renderCatalogModalList, initEventWizardControls, initCatalogModalControls,
    populateWizardDynamicDropdowns, setCollegeSourceMode, setEduSourceMode,
    syncRefinanceFields,
    // Scenario plan modal state & tabs
    setModalScenarioTab, updateModalEventsCountBadge, renderModalScenarioEventsList,
    // Scenario plan dialogs
    openNewChildScenarioModal, openNewScenarioModal, openEditScenarioModal,
    openScenarioModal, cloneScenario,
    // Scenario page checklist
    renderEventChecklistAndCatalog,
    // Modal controls wiring
    initScenarioModalControls
};

if (typeof window !== 'undefined') {
    window.openNewChildScenarioModal = openNewChildScenarioModal;
    window.openNewScenarioModal = openNewScenarioModal;
    window.openEditScenarioModal = openEditScenarioModal;
    window.cloneEvent = cloneEvent;
    window.cloneScenario = cloneScenario;
    window.openEditEventModal = openEditEventModal;
    window.renderCatalogModalList = renderCatalogModalList;
}
