/**
 * Scenario Plan Modal State and Events Tab
 * Manages modal-level scenario object state and event checklist rendering.
 */
import {
    state, escapeHtml, EVENT_CATEGORY_GROUPS,
    formatCategoryLabel, getCategoryBadgeClass, resolveEventIcon
} from './state.js';
import { openEditEventModal } from './event_modals.js';

let modalScenarioObj = null;
let modalSelectedEventIds = new Set();
let modalEventsSearchQuery = '';
let modalExpandedCategoryGroups = null;

export function getModalScenarioObj() { return modalScenarioObj; }
export function setModalScenarioObj(val) { modalScenarioObj = val; }
export function getModalSelectedEventIds() { return modalSelectedEventIds; }
export function setModalSelectedEventIds(val) { modalSelectedEventIds = val; }
export function getModalEventsSearchQuery() { return modalEventsSearchQuery; }
export function setModalEventsSearchQuery(val) { modalEventsSearchQuery = val; }
export function getModalExpandedCategoryGroups() { return modalExpandedCategoryGroups; }
export function setModalExpandedCategoryGroups(val) { modalExpandedCategoryGroups = val; }
export function getModalSpendingGuardrailMode() { return modalScenarioObj?.spending_guardrail_mode || 'off'; }
export function setModalSpendingGuardrailMode(val) { if (modalScenarioObj) modalScenarioObj.spending_guardrail_mode = val; }

export function setModalScenarioTab(tabName) {
    const tabAssumptions = document.getElementById('tab-modal-scen-assumptions');
    const tabEvents = document.getElementById('tab-modal-scen-events');
    const panelAssumptions = document.getElementById('modal-scen-panel-assumptions');
    const panelEvents = document.getElementById('modal-scen-panel-events');
    if (!tabAssumptions || !tabEvents || !panelAssumptions || !panelEvents) return;

    if (tabName === 'events') {
        tabAssumptions.classList.remove('active');
        tabEvents.classList.add('active');
        panelAssumptions.style.display = 'none';
        panelEvents.style.display = 'block';
        renderModalScenarioEventsList(state.scenariosData);
    } else {
        tabEvents.classList.remove('active');
        tabAssumptions.classList.add('active');
        panelEvents.style.display = 'none';
        panelAssumptions.style.display = 'block';
    }
}

export function updateModalEventsCountBadge() {
    const badge = document.getElementById('modal-scen-events-count');
    if (badge) {
        badge.textContent = String(modalSelectedEventIds.size);
    }
}

export function renderModalScenarioEventsList(data = state.scenariosData) {
    const checklistContainer = document.getElementById('modal-scenario-event-checklist');
    if (!checklistContainer || !data) return;
    checklistContainer.innerHTML = '';

    const eventsCatalog = data.events_catalog || [];
    if (!eventsCatalog.length) {
        checklistContainer.innerHTML = '<p class="text-muted" style="font-size: 0.8125rem; padding: 12px; text-align: center;">No events in catalog. Click "+ Add Event" to create one.</p>';
        return;
    }

    if (modalExpandedCategoryGroups === null) {
        modalExpandedCategoryGroups = new Set();
        EVENT_CATEGORY_GROUPS.forEach(g => {
            const hasActive = eventsCatalog.some(ev => {
                const inGroup = (g.key === 'other')
                    ? !EVENT_CATEGORY_GROUPS.filter(og => og.key !== 'other').flatMap(og => og.categories).includes(ev.category)
                    : g.categories.includes(ev.category);
                return inGroup && modalSelectedEventIds.has(ev.id);
            });
            if (hasActive) {
                modalExpandedCategoryGroups.add(g.key);
            }
        });
    }

    const q = (modalEventsSearchQuery || '').toLowerCase().trim();
    let totalRendered = 0;

    const isBaseline = (modalScenarioObj?.id === 'scen_baseline') || (modalScenarioObj?.id === 'baseline') || (state.selectedScenarioId === 'scen_baseline' && !modalScenarioObj?.id);
    let currentParentId = null;
    if (!isBaseline) {
        if (modalScenarioObj && modalScenarioObj.id) {
            currentParentId = (modalScenarioObj.parent_id && modalScenarioObj.parent_id !== modalScenarioObj.id) ? modalScenarioObj.parent_id : null;
        } else {
            const domVal = document.getElementById('select-scenario-parent')?.value;
            currentParentId = (domVal && domVal !== modalScenarioObj?.id) ? domVal : null;
        }
    }
    const parentScen = (currentParentId && (!modalScenarioObj || currentParentId !== modalScenarioObj.id)) ? (state.scenariosData?.scenarios || []).find(s => s.id === currentParentId) : null;
    const parentEvents = new Set(parentScen ? (parentScen.event_ids || []) : []);

    EVENT_CATEGORY_GROUPS.forEach(group => {
        let groupEvents = eventsCatalog.filter(ev => {
            if (group.key === 'other') {
                const knownCats = EVENT_CATEGORY_GROUPS.filter(g => g.key !== 'other').flatMap(g => g.categories);
                return !knownCats.includes(ev.category);
            }
            return group.categories.includes(ev.category);
        });

        if (!groupEvents.length) return;

        if (q) {
            groupEvents = groupEvents.filter(ev => {
                const matchName = (ev.name || '').toLowerCase().includes(q);
                const matchDesc = (ev.description || '').toLowerCase().includes(q);
                const matchCat = formatCategoryLabel(ev.category).toLowerCase().includes(q);
                return matchName || matchDesc || matchCat;
            });
            if (!groupEvents.length) return;
        }

        totalRendered += groupEvents.length;
        const activeCount = groupEvents.filter(ev => modalSelectedEventIds.has(ev.id)).length;
        const isOpen = q ? true : modalExpandedCategoryGroups.has(group.key);

        const groupCard = document.createElement('div');
        groupCard.className = 'category-accordion-group';
        groupCard.style.cssText = 'border: 1px solid var(--border-subtle); border-radius: 8px; margin-bottom: 6px; overflow: hidden; background: var(--bg-surface);';

        const headerEl = document.createElement('div');
        headerEl.className = 'category-accordion-header';
        headerEl.style.cssText = 'display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; cursor: pointer; user-select: none; background: var(--bg-surface-elevated); transition: background 0.15s ease;';
        headerEl.innerHTML = `
            <div style="display: flex; align-items: center; gap: 8px;">
                <span class="accordion-chevron" style="display: inline-block; width: 14px; font-size: 0.6875rem; color: var(--text-muted);">${isOpen ? '▼' : '▶'}</span>
                <span style="display: inline-flex; align-items: center; color: ${group.color || 'var(--accent-blue)'};">${group.icon}</span>
                <strong style="font-size: 0.8125rem; color: var(--text-primary);">${group.title}</strong>
            </div>
            <div style="display: flex; align-items: center; gap: 8px;">
                <span class="badge ${activeCount > 0 ? 'badge-blue' : ''}" style="${activeCount === 0 ? 'background: rgba(148, 163, 184, 0.15); color: #94A3B8;' : ''} font-size: 0.6875rem;" id="badge-cat-count-${group.key}">
                    ${activeCount} / ${groupEvents.length} Active
                </span>
            </div>
        `;

        const bodyEl = document.createElement('div');
        bodyEl.className = 'category-accordion-body';
        bodyEl.style.cssText = `display: ${isOpen ? 'flex' : 'none'}; flex-direction: column; gap: 6px; padding: 8px 10px; background: var(--bg-surface);`;

        headerEl.addEventListener('click', (e) => {
            if (e.target.closest('button, input')) return;
            const currentlyOpen = bodyEl.style.display !== 'none';
            if (currentlyOpen) {
                bodyEl.style.display = 'none';
                headerEl.querySelector('.accordion-chevron').textContent = '▶';
                modalExpandedCategoryGroups.delete(group.key);
            } else {
                bodyEl.style.display = 'flex';
                headerEl.querySelector('.accordion-chevron').textContent = '▼';
                modalExpandedCategoryGroups.add(group.key);
            }
        });

        groupEvents.forEach(ev => {
            const isChecked = modalSelectedEventIds.has(ev.id);
            const isParentEvent = parentEvents.has(ev.id);
            const item = document.createElement('div');
            item.className = 'portal-card';
            item.style.cssText = 'padding: 8px 12px; display: flex; align-items: center; justify-content: space-between; border-radius: 6px; border: 1px solid var(--border-subtle); background: ' + (isChecked ? 'var(--bg-surface-elevated)' : 'var(--bg-canvas)') + '; transition: background 0.15s ease; gap: 10px;';

            const timing = (ev.year === ev.end_year || !ev.end_year) ? `${ev.year}` : `${ev.year}–${ev.end_year}`;

            function getInheritanceBadgeHtml(checked) {
                if (!parentScen || (modalScenarioObj && parentScen.id === modalScenarioObj.id)) return '';
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
                <div style="display: flex; align-items: center; gap: 10px; min-width: 0; flex: 1;">
                    <input type="checkbox" class="hvl-checkbox" id="modal_chk_${ev.id}" ${isChecked ? 'checked' : ''} style="cursor: pointer; width: 16px; height: 16px; flex-shrink: 0;" title="Include or exclude in this plan">
                    <div style="min-width: 0; flex: 1;">
                        <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
                            <span class="badge ${getCategoryBadgeClass(ev.category)}" style="font-size: 0.625rem;">${formatCategoryLabel(ev.category)}</span>
                            <strong style="font-size: 0.8125rem; color: var(--text-primary); cursor: pointer;" class="btn-name-edit-event" title="Click to inspect event">${escapeHtml(ev.name)}</strong>
                            <span class="modal-event-inheritance-slot">${getInheritanceBadgeHtml(isChecked)}</span>
                            ${badgeSync}
                        </div>
                        <div class="text-muted" style="font-size: 0.71875rem; margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(ev.description || '')}</div>
                    </div>
                </div>
                <div style="display: flex; align-items: center; gap: 6px; flex-shrink: 0; margin-left: 8px;">
                    <span class="badge badge-orange" style="font-size: 0.6875rem;">${timing}</span>
                    <button type="button" class="btn btn-secondary btn-sm btn-edit-event" data-id="${ev.id}" style="padding: 4px 6px; display: inline-flex; align-items: center; justify-content: center;" title="Inspect & Edit Event" aria-label="Inspect & Edit Event"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display: block;"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg></button>
                </div>
            `;

            const chk = item.querySelector(`#modal_chk_${ev.id}`);
            chk.addEventListener('change', (e) => {
                e.stopPropagation();
                if (chk.checked) {
                    modalSelectedEventIds.add(ev.id);
                    item.style.background = 'var(--bg-surface-elevated)';
                } else {
                    modalSelectedEventIds.delete(ev.id);
                    item.style.background = 'var(--bg-canvas)';
                }
                const slot = item.querySelector('.modal-event-inheritance-slot');
                if (slot) slot.innerHTML = getInheritanceBadgeHtml(chk.checked);
                updateModalEventsCountBadge();
                const newActiveCount = groupEvents.filter(ev2 => modalSelectedEventIds.has(ev2.id)).length;
                const catBadge = headerEl.querySelector(`#badge-cat-count-${group.key}`);
                if (catBadge) {
                    catBadge.textContent = `${newActiveCount} / ${groupEvents.length} Active`;
                    catBadge.className = `badge ${newActiveCount > 0 ? 'badge-blue' : ''}`;
                    if (newActiveCount === 0) {
                        catBadge.style.cssText = 'background: rgba(148, 163, 184, 0.15); color: #94A3B8; font-size: 0.6875rem;';
                    }
                }
            });

            item.querySelector('.btn-edit-event')?.addEventListener('click', (e) => {
                e.stopPropagation();
                openEditEventModal(ev.id);
            });
            item.querySelector('.btn-name-edit-event')?.addEventListener('click', (e) => {
                e.stopPropagation();
                openEditEventModal(ev.id);
            });

            bodyEl.appendChild(item);
        });

        groupCard.appendChild(headerEl);
        groupCard.appendChild(bodyEl);
        checklistContainer.appendChild(groupCard);
    });

    if (totalRendered === 0) {
        checklistContainer.innerHTML = '<p class="text-muted" style="font-size: 0.8125rem; padding: 12px; text-align: center;">No events match your search query.</p>';
    }
}
