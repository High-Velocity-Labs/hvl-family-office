/**
 * Scenario Event Checklist
 * Renders the interactive scenario event checklist and accordion groups on the main page.
 */
import {
    state, escapeHtml, EVENT_CATEGORY_GROUPS,
    formatCategoryLabel, getCategoryBadgeClass, resolveEventIcon
} from './state.js';
import { morphScenariosSection } from './main.js';
import {
    renderCatalogModalList, openEditEventModal, cloneEvent
} from './event_modals.js';
import {
    renderModalScenarioEventsList, updateModalEventsCountBadge
} from './modals_plan_state.js';

let expandedCategoryGroups = null;
let scenarioEventsSearchQuery = '';

const fetchScenariosData = (...args) => (
    typeof morphScenariosSection === 'function'
        ? morphScenariosSection(...args)
        : (typeof window !== 'undefined' && window.fetchScenariosData ? window.fetchScenariosData(...args) : Promise.resolve())
);
const showModalConfirm = (...args) => (typeof window !== 'undefined' && window.showModalConfirm ? window.showModalConfirm(...args) : Promise.resolve(true));
const showModalAlert = (...args) => (typeof window !== 'undefined' && window.showModalAlert ? window.showModalAlert(...args) : (typeof alert === 'function' ? Promise.resolve(alert(args[0])) : Promise.resolve()));

export function renderEventChecklistAndCatalog(data) {
    const checklistContainer = document.getElementById('scenario-event-checklist');
    const headingSelected = document.getElementById('heading-selected-scenario-events');

    const scenarios = data.scenarios || [];
    const currentScen = scenarios.find(s => s.id === state.selectedScenarioId) || scenarios[0] || {};
    const eventsCatalog = data.events_catalog || [];
    const includedIds = new Set(currentScen.event_ids || []);
    const parentScen = (currentScen.parent_id && currentScen.parent_id !== currentScen.id) ? scenarios.find(s => s.id === currentScen.parent_id) : null;
    const parentEvents = new Set(parentScen ? (parentScen.event_ids || []) : []);

    if (headingSelected) {
        headingSelected.textContent = `Events in "${currentScen.name || 'Selected Plan'}" (${includedIds.size})`;
    }

    const searchInput = document.getElementById('input-search-scenario-events');
    if (searchInput && !searchInput.dataset.wired) {
        searchInput.dataset.wired = 'true';
        searchInput.addEventListener('input', (e) => {
            scenarioEventsSearchQuery = e.target.value;
            renderEventChecklistAndCatalog(state.scenariosData);
        });
    }

    const toggleAllBtn = document.getElementById('btn-toggle-all-accordions');
    if (toggleAllBtn && !toggleAllBtn.dataset.wired) {
        toggleAllBtn.dataset.wired = 'true';
        toggleAllBtn.addEventListener('click', () => {
            const allKeys = EVENT_CATEGORY_GROUPS.map(g => g.key);
            const allExpanded = allKeys.every(k => expandedCategoryGroups && expandedCategoryGroups.has(k));
            if (!expandedCategoryGroups) expandedCategoryGroups = new Set();
            if (allExpanded) {
                expandedCategoryGroups.clear();
                toggleAllBtn.textContent = 'Expand All';
            } else {
                allKeys.forEach(k => expandedCategoryGroups.add(k));
                toggleAllBtn.textContent = 'Collapse All';
            }
            renderEventChecklistAndCatalog(state.scenariosData);
        });
    }

    if (checklistContainer) {
        checklistContainer.innerHTML = '';
        if (!eventsCatalog.length) {
            checklistContainer.innerHTML = '<p class="text-muted" style="font-size: 0.8125rem;">No events available. Add an event from the catalog.</p>';
        } else {
            if (expandedCategoryGroups === null) {
                expandedCategoryGroups = new Set();
                EVENT_CATEGORY_GROUPS.forEach(g => {
                    const hasActive = eventsCatalog.some(ev => {
                        const inGroup = (g.key === 'other')
                            ? !EVENT_CATEGORY_GROUPS.filter(og => og.key !== 'other').flatMap(og => og.categories).includes(ev.category)
                            : g.categories.includes(ev.category);
                        return inGroup && includedIds.has(ev.id);
                    });
                    if (hasActive) {
                        expandedCategoryGroups.add(g.key);
                    }
                });
            }

            if (toggleAllBtn) {
                const allKeys = EVENT_CATEGORY_GROUPS.map(g => g.key);
                const allExpanded = allKeys.every(k => expandedCategoryGroups.has(k));
                toggleAllBtn.textContent = allExpanded ? 'Collapse All' : 'Expand All';
            }

            const q = (scenarioEventsSearchQuery || '').toLowerCase().trim();
            let totalRenderedEvents = 0;

            EVENT_CATEGORY_GROUPS.forEach(group => {
                let groupEvents = eventsCatalog.filter(ev => {
                    if (group.key === 'other') {
                        const knownCats = EVENT_CATEGORY_GROUPS.filter(g => g.key !== 'other').flatMap(g => g.categories);
                        return !knownCats.includes(ev.category);
                    }
                    return group.categories.includes(ev.category);
                });

                if (groupEvents.length === 0) return;

                if (q) {
                    groupEvents = groupEvents.filter(ev => {
                        const matchName = ev.name.toLowerCase().includes(q);
                        const matchDesc = (ev.description || '').toLowerCase().includes(q);
                        const matchCat = formatCategoryLabel(ev.category).toLowerCase().includes(q);
                        return matchName || matchDesc || matchCat;
                    });
                    if (groupEvents.length === 0) return;
                }

                totalRenderedEvents += groupEvents.length;
                const activeCount = groupEvents.filter(ev => includedIds.has(ev.id)).length;
                const isOpen = q ? true : expandedCategoryGroups.has(group.key);

                const groupCard = document.createElement('div');
                groupCard.className = 'category-accordion-group';
                groupCard.style.cssText = 'border: 1px solid var(--border-subtle); border-radius: 8px; margin-bottom: 8px; overflow: hidden; background: var(--bg-surface);';

                const headerEl = document.createElement('div');
                headerEl.className = 'category-accordion-header';
                headerEl.style.cssText = 'display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; cursor: pointer; user-select: none; background: var(--bg-surface-elevated); transition: background 0.15s ease;';
                headerEl.innerHTML = `
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span class="accordion-chevron" style="display: inline-block; width: 14px; font-size: 0.6875rem; color: var(--text-muted);">${isOpen ? '▼' : '▶'}</span>
                        <span style="display: inline-flex; align-items: center; color: ${group.color || 'var(--accent-blue)'};">${group.icon}</span>
                        <strong style="font-size: 0.8125rem; color: var(--text-primary);">${group.title}</strong>
                    </div>
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span class="badge ${activeCount > 0 ? 'badge-blue' : ''}" style="${activeCount === 0 ? 'background: rgba(148, 163, 184, 0.15); color: #94A3B8;' : ''} font-size: 0.6875rem;">
                            ${activeCount} / ${groupEvents.length} Active
                        </span>
                    </div>
                `;

                const bodyEl = document.createElement('div');
                bodyEl.className = 'category-accordion-body';
                bodyEl.style.cssText = `display: ${isOpen ? 'flex' : 'none'}; flex-direction: column; gap: 8px; padding: 10px 12px; background: var(--bg-surface);`;

                headerEl.addEventListener('click', (e) => {
                    if (e.target.closest('button') || e.target.closest('input')) return;
                    const currentlyOpen = bodyEl.style.display !== 'none';
                    if (currentlyOpen) {
                        bodyEl.style.display = 'none';
                        headerEl.querySelector('.accordion-chevron').textContent = '▶';
                        expandedCategoryGroups.delete(group.key);
                    } else {
                        bodyEl.style.display = 'flex';
                        headerEl.querySelector('.accordion-chevron').textContent = '▼';
                        expandedCategoryGroups.add(group.key);
                    }
                    if (toggleAllBtn) {
                        const allKeys = EVENT_CATEGORY_GROUPS.map(g => g.key);
                        const allExpanded = allKeys.every(k => expandedCategoryGroups.has(k));
                        toggleAllBtn.textContent = allExpanded ? 'Collapse All' : 'Expand All';
                    }
                });

                groupEvents.forEach(ev => {
                    const isChecked = includedIds.has(ev.id);
                    const isParentEvent = parentEvents.has(ev.id);
                    const item = document.createElement('div');
                    item.className = 'portal-card';
                    item.style.cssText = 'padding: 10px 14px; display: flex; align-items: center; justify-content: space-between; border-radius: 8px; border: 1px solid var(--border-subtle); background: ' + (isChecked ? 'var(--bg-surface-elevated)' : 'var(--bg-canvas)') + '; transition: background 0.15s ease; gap: 12px;';

                    const timing = (ev.year === ev.end_year || !ev.end_year) ? `${ev.year}` : `${ev.year}–${ev.end_year}`;
                    const icon = resolveEventIcon(ev, 14);

                    function getChecklistInheritanceBadgeHtml(checked) {
                        if (!parentScen || parentScen.id === currentScen.id) return '';
                        if (checked && isParentEvent) {
                            return `<span class="badge" style="font-size: 0.625rem; background: var(--brand-primary-bg, #EFF6FF); color: var(--brand-primary, #0265E8); border: 1px solid var(--brand-primary-border, #BFDBFE);" title="Inherited from parent plan (${escapeHtml(parentScen.name)})">↳ Inherited</span>`;
                        } else if (!checked && isParentEvent) {
                            return `<span class="badge" style="font-size: 0.625rem; background: rgba(239, 68, 68, 0.15); color: var(--status-red);" title="Unticked / Excluded from parent plan (${escapeHtml(parentScen.name)})">↳ Excluded from Parent</span>`;
                        } else if (checked && !isParentEvent) {
                            return `<span class="badge" style="font-size: 0.625rem; background: rgba(59, 130, 246, 0.15); color: var(--accent-blue);" title="Custom event added to this child plan">↳ Child Override</span>`;
                        }
                        return '';
                    }

                    const badgeSync = (ev.category === 'college' || ev.category === 'education')
                        ? (ev.sync_with_ledger
                            ? `<span class="badge" style="font-size: 0.625rem; background: rgba(16, 185, 129, 0.15); color: var(--status-green);" title="Live synced with verified Education Ledger">Synced</span>`
                            : `<span class="badge" style="font-size: 0.625rem; background: rgba(245, 158, 11, 0.15); color: var(--accent-orange);" title="Speculative what-if override">Speculative</span>`)
                        : '';

                    item.innerHTML = `
                        <div style="display: flex; align-items: center; gap: 12px; min-width: 0; flex: 1;">
                            <input type="checkbox" class="hvl-checkbox" id="chk_${ev.id}" ${isChecked ? 'checked' : ''} style="cursor: pointer; width: 17px; height: 17px; flex-shrink: 0;" title="Include or exclude in selected plan">
                            <div style="min-width: 0; flex: 1;">
                                <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                                    <span class="badge ${getCategoryBadgeClass(ev.category)}" style="font-size: 0.6875rem; display: inline-flex; align-items: center; gap: 4px;">${icon ? `<span style="display: inline-flex; align-items: center;">${icon}</span>` : ''}<span>${formatCategoryLabel(ev.category)}</span></span>
                                    <strong style="font-size: 0.875rem; color: var(--text-primary); cursor: pointer;" class="btn-name-edit-event" title="Click to edit event">${escapeHtml(ev.name)}</strong>
                                    <span class="checklist-event-inheritance-slot">${getChecklistInheritanceBadgeHtml(isChecked)}</span>
                                    ${badgeSync}
                                </div>
                                <div class="text-muted" style="font-size: 0.75rem; margin-top: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(ev.description || '')}</div>
                            </div>
                        </div>
                        <div style="display: flex; align-items: center; gap: 8px; flex-shrink: 0; margin-left: 10px;">
                            <span class="badge badge-orange" style="font-size: 0.75rem;">${timing}</span>
                            <button type="button" class="btn btn-secondary btn-sm btn-edit-event" data-id="${ev.id}" style="padding: 4px 6px; display: inline-flex; align-items: center; justify-content: center;" title="Inspect & Edit Event" aria-label="Inspect & Edit Event"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display: block;"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg></button>
                            <button type="button" class="btn btn-secondary btn-sm btn-clone-event" data-id="${ev.id}" style="padding: 3px 8px; font-size: 0.75rem;" title="Clone this event" aria-label="Clone this event">Clone</button>
                            <button type="button" class="btn btn-secondary btn-sm btn-del-event" data-id="${ev.id}" style="padding: 2px 6px; font-size: 0.75rem; color: var(--status-red); border-color: rgba(239, 68, 68, 0.3);" title="Delete event from catalog" aria-label="Delete event from catalog">✕</button>
                        </div>
                    `;

                    item.querySelector('.btn-edit-event')?.addEventListener('click', (e) => {
                        e.stopPropagation();
                        openEditEventModal(ev.id);
                    });
                    item.querySelector('.btn-name-edit-event')?.addEventListener('click', (e) => {
                        e.stopPropagation();
                        openEditEventModal(ev.id);
                    });
                    item.querySelector('.btn-clone-event')?.addEventListener('click', (e) => {
                        e.stopPropagation();
                        cloneEvent(ev.id);
                    });
                    item.querySelector('.btn-del-event')?.addEventListener('click', async (e) => {
                        e.stopPropagation();
                        if (await showModalConfirm(`Delete event "${ev.name}" from catalog? This will remove it from all plans.`, { title: 'Delete Catalog Event', confirmText: 'Delete Event', confirmVariant: 'danger' })) {
                            await fetch(`/api/events/${ev.id}`, { method: 'DELETE' });
                            await fetchScenariosData();
                        }
                    });

                    const chk = item.querySelector(`#chk_${ev.id}`);
                    chk.addEventListener('change', async (e) => {
                        e.stopPropagation();
                        let newIds = Array.from(includedIds);
                        if (chk.checked) {
                            newIds.push(ev.id);
                        } else {
                            newIds = newIds.filter(id => id !== ev.id);
                        }
                        currentScen.event_ids = newIds;
                        if (currentScen.parent_id) {
                            currentScen.excluded_event_ids = Array.from(parentEvents).filter(id => !newIds.includes(id));
                            currentScen.added_event_ids = newIds.filter(id => !parentEvents.has(id));
                        }
                        try {
                            const resp = await fetch('/api/scenarios', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(currentScen)
                            });
                            const res = await resp.json();
                            if (!resp.ok || !res.success) {
                                await showModalAlert(res.error || 'Failed to update scenario events', { title: 'Unable to Update Scenario', type: 'error' });
                            }
                        } catch (err) {
                            await showModalAlert('Failed to update scenario events: ' + err.message, { title: 'Unable to Update Scenario', type: 'error' });
                        }
                        await fetchScenariosData();
                    });

                    bodyEl.appendChild(item);
                });

                groupCard.appendChild(headerEl);
                groupCard.appendChild(bodyEl);
                checklistContainer.appendChild(groupCard);
            });

            if (totalRenderedEvents === 0) {
                checklistContainer.innerHTML = '<p class="text-muted" style="font-size: 0.8125rem; padding: 12px; text-align: center;">No events match your search query.</p>';
            }
        }
    }

    renderCatalogModalList(data);

    const modalScen = document.getElementById('modal-scenario');
    if (modalScen && modalScen.style.display !== 'none') {
        renderModalScenarioEventsList(data);
        updateModalEventsCountBadge();
    }
}
