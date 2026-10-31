/**
 * Scenario Event Catalog Refresh
 * Re-renders the master catalog dialog and the open plan modal's event checklist after scenario data changes.
 * The checklist itself is a server fragment (see modals_plan_state.js).
 */
import { renderCatalogModalList } from './event_modals.js';
import { renderModalScenarioEventsList, updateModalEventsCountBadge } from './modals_plan_state.js';

export function renderEventChecklistAndCatalog(data) {
    renderCatalogModalList(data);

    const modalScen = document.getElementById('modal-scenario');
    if (modalScen && modalScen.style.display !== 'none') {
        renderModalScenarioEventsList(data);
        updateModalEventsCountBadge();
    }
}
