/**
 * static/js/scenarios/event_modals_catalog.js
 * Master Event Catalog modal dialog list rendering, filtering, and event cloning.
 */

import {
    state,
    escapeHtml,
    formatCategoryLabel,
    getCategoryBadgeClass,
    resolveEventIcon
} from './state.js';
import { morphScenariosSection } from './main.js';
import { openEditEventModal } from './event_modals_render.js';

const showModalConfirm = (...args) => (
    typeof window !== 'undefined' && window.showModalConfirm
        ? window.showModalConfirm(...args)
        : Promise.resolve(true)
);

const showModalAlert = (...args) => (
    typeof window !== 'undefined' && window.showModalAlert
        ? window.showModalAlert(...args)
        : Promise.resolve()
);

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

export function renderCatalogModalList(data) {
    const catalogContainer = document.getElementById('events-catalog-list');
    const countBadge = document.getElementById('badge-catalog-total-count');
    const searchInput = document.getElementById('input-search-catalog-modal');
    const catSelect = document.getElementById('select-catalog-modal-category');

    if (!catalogContainer || !data) return;

    const eventsCatalog = data.events_catalog || [];
    const scenarios = data.scenarios || [];

    if (countBadge) {
        countBadge.textContent = `${eventsCatalog.length} Events`;
    }

    const q = (searchInput?.value || '').toLowerCase().trim();
    const selCat = catSelect?.value || 'ALL';

    let filtered = eventsCatalog.slice();

    if (selCat !== 'ALL') {
        if (selCat === 'other') {
            const knownCats = ['education', 'college', 'grad_school', 'superfund_529', 'company_equity', 'equity', 'sabbatical', 'income_change', 'roth_conversion', 'real_estate', 'home_renovation', 'home_sale', 'refinance', 'debt_payoff', 'state_relocation', 'gifting', 'gifting_throughline', 'philanthropy_daf', 'child_home_gift', 'eldercare', 'parent_care', 'ltc_insurance', 'pre65_healthcare', 'new_child', 'medical_expense', 'lifestyle', 'travel_surge', 'wedding', 'vehicle_purchase', 'marital_settlement', 'pe_capital_call'];
            filtered = filtered.filter(ev => !knownCats.includes(ev.category));
        } else if (selCat === 'education') {
            filtered = filtered.filter(ev => ['education', 'college', 'grad_school', 'superfund_529'].includes(ev.category));
        } else if (selCat === 'company_equity') {
            filtered = filtered.filter(ev => ['company_equity', 'equity', 'sabbatical', 'income_change', 'roth_conversion'].includes(ev.category));
        } else if (selCat === 'real_estate') {
            filtered = filtered.filter(ev => ['real_estate', 'home_renovation', 'home_sale', 'refinance', 'debt_payoff', 'state_relocation'].includes(ev.category));
        } else if (selCat === 'gifting') {
            filtered = filtered.filter(ev => ['gifting', 'gifting_throughline', 'philanthropy_daf', 'child_home_gift', 'superfund_529'].includes(ev.category));
        } else if (selCat === 'eldercare') {
            filtered = filtered.filter(ev => ['eldercare', 'parent_care', 'ltc_insurance', 'pre65_healthcare', 'new_child', 'medical_expense'].includes(ev.category));
        } else if (selCat === 'lifestyle') {
            filtered = filtered.filter(ev => ['lifestyle', 'travel_surge', 'wedding', 'vehicle_purchase'].includes(ev.category));
        } else if (selCat === 'capital_outflow') {
            filtered = filtered.filter(ev => ['capital_outflow', 'withdrawal', 'angel_investment', 'pe_capital_call', 'marital_settlement'].includes(ev.category));
        } else if (selCat === 'capital_inflow') {
            filtered = filtered.filter(ev => ['capital_inflow', 'custom_spike', 'windfall', 'rental_income', 'deferred_comp'].includes(ev.category));
        } else {
            filtered = filtered.filter(ev => ev.category === selCat);
        }
    }

    if (q) {
        filtered = filtered.filter(ev => {
            const matchName = (ev.name || '').toLowerCase().includes(q);
            const matchDesc = (ev.description || '').toLowerCase().includes(q);
            const matchCat = formatCategoryLabel(ev.category).toLowerCase().includes(q);
            return matchName || matchDesc || matchCat;
        });
    }

    catalogContainer.innerHTML = '';

    if (filtered.length === 0) {
        catalogContainer.innerHTML = '<div style="text-align: center; padding: 28px; color: var(--text-muted); font-size: 0.8125rem;">No catalog events found matching your search.</div>';
        return;
    }

    filtered.forEach(ev => {
        const card = document.createElement('div');
        card.className = 'portal-card';
        card.style.cssText = 'padding: 12px 16px; border-radius: 8px; border: 1px solid var(--border-subtle); background: var(--bg-canvas); display: flex; flex-direction: column; gap: 8px;';

        const timing = (ev.year === ev.end_year || !ev.end_year) ? `${ev.year}` : `${ev.year}–${ev.end_year}`;
        const catBadge = getCategoryBadgeClass(ev.category);
        const catLabel = formatCategoryLabel(ev.category);
        const icon = resolveEventIcon(ev, 14);

        const activeInScens = scenarios.filter(s => (s.event_ids || []).includes(ev.id));
        let usageHtml = '';
        if (activeInScens.length === 0) {
            usageHtml = '<span class="badge" style="background: rgba(148, 163, 184, 0.12); color: #94A3B8; font-size: 0.6875rem;">Not in any plan</span>';
        } else {
            const scenNames = activeInScens.map(s => s.name || s.id).join(', ');
            usageHtml = `<span class="badge badge-blue" style="font-size: 0.6875rem;" title="${escapeHtml(scenNames)}">Active in ${activeInScens.length} plan${activeInScens.length > 1 ? 's' : ''}</span>`;
        }

        card.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap;">
                <div style="flex: 1; min-width: 220px;">
                    <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                        <span class="badge ${catBadge}" style="font-size: 0.6875rem; display: inline-flex; align-items: center; gap: 4px;">${icon ? `<span style="display: inline-flex; align-items: center;">${icon}</span>` : ''}<span>${catLabel}</span></span>
                        <strong style="font-size: 0.875rem; color: var(--text-primary); cursor: pointer;" class="btn-name-edit-event" title="Click to edit event">${escapeHtml(ev.name)}</strong>
                        ${usageHtml}
                    </div>
                    <p class="text-muted" style="font-size: 0.75rem; margin: 4px 0 0 0;">${escapeHtml(ev.description || '')}</p>
                </div>
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span class="badge badge-orange" style="font-size: 0.75rem; font-weight: 600;">${timing}</span>
                    <button type="button" class="btn btn-secondary btn-sm btn-edit-event" data-id="${ev.id}" style="padding: 4px 6px; display: inline-flex; align-items: center; justify-content: center;" title="Inspect & Edit Event" aria-label="Inspect & Edit Event"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display: block;"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg></button>
                    <button type="button" class="btn btn-secondary btn-sm btn-clone-event" data-id="${ev.id}" style="padding: 3px 8px; font-size: 0.75rem;" title="Clone this event" aria-label="Clone this event">Clone</button>
                    <button type="button" class="btn btn-secondary btn-sm btn-del-event" style="padding: 2px 6px; font-size: 0.75rem; color: var(--status-red); border-color: rgba(239, 68, 68, 0.3);" title="Delete event from catalog" aria-label="Delete event from catalog">✕</button>
                </div>
            </div>
        `;

        card.querySelector('.btn-edit-event')?.addEventListener('click', () => {
            openEditEventModal(ev.id);
        });
        card.querySelector('.btn-name-edit-event')?.addEventListener('click', () => {
            openEditEventModal(ev.id);
        });
        card.querySelector('.btn-clone-event')?.addEventListener('click', () => {
            cloneEvent(ev.id);
        });

        card.querySelector('.btn-del-event')?.addEventListener('click', async () => {
            if (await showModalConfirm(`Delete event "${ev.name}" from catalog? This will remove it from all plans.`, { title: 'Delete Catalog Event', confirmText: 'Delete Event', confirmVariant: 'danger' })) {
                await fetch(`/api/events/${ev.id}`, { method: 'DELETE' });
                await morphScenariosSection();
            }
        });

        catalogContainer.appendChild(card);
    });
}

export function initCatalogModalControls() {
    const modalCatalog = document.getElementById('modal-events-catalog');
    const btnOpenCatalog = document.getElementById('btn-open-catalog-modal');
    const btnCloseCatalog = document.getElementById('btn-close-modal-catalog');
    const btnCloseCatalogFooter = document.getElementById('btn-close-modal-catalog-footer');
    const btnModalAddEvent = document.getElementById('btn-modal-add-event');
    const searchInput = document.getElementById('input-search-catalog-modal');
    const catSelect = document.getElementById('select-catalog-modal-category');

    if (btnOpenCatalog && modalCatalog && !btnOpenCatalog.dataset.wired) {
        btnOpenCatalog.dataset.wired = 'true';
        btnOpenCatalog.addEventListener('click', () => {
            modalCatalog.style.display = 'flex';
            if (state.scenariosData) renderCatalogModalList(state.scenariosData);
        });
    }

    const hideCatalogModal = () => {
        if (modalCatalog) modalCatalog.style.display = 'none';
    };

    if (btnCloseCatalog && !btnCloseCatalog.dataset.wired) {
        btnCloseCatalog.dataset.wired = 'true';
        btnCloseCatalog.addEventListener('click', hideCatalogModal);
    }
    if (btnCloseCatalogFooter && !btnCloseCatalogFooter.dataset.wired) {
        btnCloseCatalogFooter.dataset.wired = 'true';
        btnCloseCatalogFooter.addEventListener('click', hideCatalogModal);
    }

    if (modalCatalog && !modalCatalog.dataset.wired) {
        modalCatalog.dataset.wired = 'true';
        modalCatalog.addEventListener('click', (e) => {
            if (e.target === modalCatalog) hideCatalogModal();
        });
    }

    if (btnModalAddEvent && !btnModalAddEvent.dataset.wired) {
        btnModalAddEvent.dataset.wired = 'true';
        btnModalAddEvent.addEventListener('click', () => {
            if (typeof window.openCreateEventModal === 'function') {
                window.openCreateEventModal();
            }
        });
    }

    if (searchInput && !searchInput.dataset.wired) {
        searchInput.dataset.wired = 'true';
        searchInput.addEventListener('input', () => {
            if (state.scenariosData) renderCatalogModalList(state.scenariosData);
        });
    }

    if (catSelect && !catSelect.dataset.wired) {
        catSelect.dataset.wired = 'true';
        catSelect.addEventListener('change', () => {
            if (state.scenariosData) renderCatalogModalList(state.scenariosData);
        });
    }
}
