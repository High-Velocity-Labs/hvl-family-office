/**
 * static/js/scenarios/event_modals_catalog.js
 * Master Event Catalog modal dialog list rendering, filtering, and event cloning.
 */

import { state } from './state.js';
import { morphScenariosSection } from './main.js';
import { openEditEventModal } from './event_modals_render.js';
import { delegate } from './event_delegation.js';

const showModalConfirm = (...args) => window.showModalConfirm(...args);
const showModalAlert = (...args) => window.showModalAlert(...args);

export async function cloneEvent(eventId) {
    if (!eventId || !state.scenariosData) return;
    const catalog = state.scenariosData.events_catalog || [];
    const source = catalog.find(e => e.id === eventId);
    if (!source) {
        await showModalAlert('Event not found in catalog', { title: 'Unable to Clone Event', type: 'error' });
        return;
    }
    const newId = `evt_clone_${Date.now()}`;
    const newName = `${source.name || 'Event'} (Copy)`;
    const newEvt = Object.assign({}, source, {
        id: newId,
        name: newName
    });

    try {
        const resp = await fetch('/api/events', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(newEvt)
        });
        const res = await resp.json();
        if (resp.ok && res.success) {
            const currentScen = (state.scenariosData.scenarios || []).find(s => s.id === state.selectedScenarioId);
            if (currentScen) {
                currentScen.event_ids = [...(currentScen.event_ids || []), newId];
                const scenResp = await fetch('/api/scenarios', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(currentScen)
                });
                const scenRes = await scenResp.json();
                if (!scenResp.ok || !scenRes.success) {
                    await showModalAlert(scenRes.error || 'Failed to attach cloned event to scenario', { title: 'Unable to Update Scenario', type: 'error' });
                }
            }
            await morphScenariosSection();

            openEditEventModal(newId);
            setTimeout(() => {
                const nameInput = document.getElementById('input-event-name');
                if (nameInput) {
                    nameInput.focus();
                    nameInput.select();
                }
            }, 80);
        } else {
            await showModalAlert(res.error || 'Failed to clone event', { title: 'Unable to Clone Event', type: 'error' });
        }
    } catch (err) {
        console.error('Failed to clone event:', err);
        await showModalAlert('Failed to clone event: ' + err.message, { title: 'Unable to Clone Event', type: 'error' });
    }
}

/** Asks the server for the catalog cards matching the modal's search text and category (swapped into the list). */
export function renderCatalogModalList(data) {
    const catalogContainer = document.getElementById('events-catalog-list');
    const countBadge = document.getElementById('badge-catalog-total-count');
    if (!catalogContainer || !data) return Promise.resolve();

    if (countBadge) {
        countBadge.textContent = `${(data.events_catalog || []).length} Events`;
    }
    const params = new URLSearchParams({
        q: document.getElementById('input-search-catalog-modal')?.value || '',
        category: document.getElementById('select-catalog-modal-category')?.value || 'ALL',
    });
    return window.htmx.ajax('GET', `/fragments/scenario_event_catalog?${params}`, {
        target: '#events-catalog-list', swap: 'innerHTML',
    });
}

async function deleteCatalogEvent(btn) {
    const confirmed = await showModalConfirm(
        `Delete event "${btn.dataset.name}" from catalog? This will remove it from all plans.`,
        { title: 'Delete Catalog Event', confirmText: 'Delete Event', confirmVariant: 'danger' }
    );
    if (!confirmed) return;
    await fetch(`/api/events/${btn.dataset.id}`, { method: 'DELETE' });
    await morphScenariosSection();
}

function hideCatalogModal() {
    document.getElementById('modal-events-catalog').style.display = 'none';
}

function refreshCatalogList() {
    if (state.scenariosData) renderCatalogModalList(state.scenariosData);
}

function buildCatalogHandlers() {
    return {
        click: {
            'btn-open-catalog-modal': () => {
                document.getElementById('modal-events-catalog').style.display = 'flex';
                refreshCatalogList();
            },
            'btn-close-modal-catalog': hideCatalogModal,
            'btn-close-modal-catalog-footer': hideCatalogModal,
            'btn-modal-add-event': () => window.openCreateEventModal(),
            '#events-catalog-list .btn-edit-event, #events-catalog-list .btn-name-edit-event':
                (el) => openEditEventModal(el.dataset.id),
            '#events-catalog-list .btn-clone-event': (el) => cloneEvent(el.dataset.id),
            '#events-catalog-list .btn-del-event': deleteCatalogEvent,
            // A click on the backdrop itself (not the dialog inside it) closes the modal.
            'modal-events-catalog': (el, e) => {
                if (e.target === el) hideCatalogModal();
            }
        },
        input: { 'input-search-catalog-modal': refreshCatalogList },
        change: { 'select-catalog-modal-category': refreshCatalogList }
    };
}

export function initCatalogModalControls() {
    delegate(document, 'catalog', buildCatalogHandlers);
}
