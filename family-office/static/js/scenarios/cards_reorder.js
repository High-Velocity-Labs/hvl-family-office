/**
 * static/js/scenarios/cards_reorder.js
 * Drag & Drop reordering controller for scenario selector pills, scorecard table rows, and Baseline overlay chips.
 * Pills and rows reorder the plan list: they sync DOM order across selector pills and comparison table, update the
 * in-memory scenarios order, re-render the graph toggles/curves immediately, and persist via
 * POST /api/scenarios/reorder.
 * Overlay chips reorder the Baseline overlay stack (the order merged plans are applied in).
 */

import { state } from './state.js';
import { renderActiveLensChart } from './charts/index.js';
import { delegate, listenOnce } from './event_delegation.js';
import { reorderBaselineLayers } from './cards_overlays.js';

// The item being dragged and which list it belongs to, so a drop only lands within the same list.
let dragged = null;
let suppressClickUntil = 0;

/**
 * Extracts current scenario IDs from the selector pills or comparison table.
 * @returns {string[]}
 */
export function getCurrentScenarioOrder() {
    const pillIds = Array.from(document.querySelectorAll('#scenario-selector-pills .pill-btn[data-scen-id]'))
        .map(el => el.getAttribute('data-scen-id'))
        .filter(Boolean);
    if (pillIds.length > 0) return pillIds;

    return Array.from(document.querySelectorAll('#tbody-scenarios-scorecard .scorecard-row[data-scen-id]'))
        .map(el => el.getAttribute('data-scen-id'))
        .filter(Boolean);
}

/**
 * Persists the reordered scenario list to the backend.
 * @param {string[]} newOrder
 */
export async function sendScenarioReorder(newOrder) {
    if (!Array.isArray(newOrder) || newOrder.length === 0) return;
    try {
        const resp = await fetch('/api/scenarios/reorder', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ order: newOrder })
        });
        if (!resp.ok) {
            const res = await resp.json().catch(() => ({}));
            console.warn('Scenario reorder server response:', res.error || resp.statusText);
        }
    } catch (err) {
        console.error('Failed to persist scenario reorder:', err);
    }
}

/**
 * Rearranges pills and scorecard rows DOM, updates state.scenariosData.scenarios,
 * redraws the active chart lens, and triggers backend persistence.
 * @param {string[]} newOrder
 */
export function applyScenarioOrder(newOrder) {
    if (!Array.isArray(newOrder) || newOrder.length === 0) return;

    // 1. Reorder selector pills in DOM
    const pillsContainer = document.getElementById('scenario-selector-pills');
    if (pillsContainer) {
        const throbber = document.getElementById('scenario-switch-loading');
        const pillMap = new Map();
        pillsContainer.querySelectorAll('.pill-btn[data-scen-id]').forEach(btn => {
            pillMap.set(btn.getAttribute('data-scen-id'), btn);
        });
        newOrder.forEach(id => {
            const btn = pillMap.get(id);
            if (btn) {
                pillsContainer.insertBefore(btn, throbber || null);
            }
        });
    }

    // 2. Reorder scorecard table rows in DOM
    const tbody = document.getElementById('tbody-scenarios-scorecard');
    if (tbody) {
        const rowMap = new Map();
        tbody.querySelectorAll('.scorecard-row[data-scen-id]').forEach(row => {
            rowMap.set(row.getAttribute('data-scen-id'), row);
        });
        newOrder.forEach(id => {
            const row = rowMap.get(id);
            if (row) {
                tbody.appendChild(row);
            }
        });
    }

    // 3. Update state.scenariosData.scenarios in memory
    if (state.scenariosData && Array.isArray(state.scenariosData.scenarios)) {
        const scenMap = new Map(state.scenariosData.scenarios.map(s => [s.id, s]));
        const sortedScenarios = [];
        newOrder.forEach(id => {
            if (scenMap.has(id)) {
                sortedScenarios.push(scenMap.get(id));
                scenMap.delete(id);
            }
        });
        for (const remaining of scenMap.values()) {
            sortedScenarios.push(remaining);
        }
        state.scenariosData.scenarios = sortedScenarios;
    }

    // 4. Redraw chart datasets and toggles immediately
    try {
        renderActiveLensChart();
    } catch (err) {
        console.warn('Failed to redraw chart lens after reorder:', err);
    }

    // 5. Send reorder API call to backend
    sendScenarioReorder(newOrder);
}

/**
 * Removes drag styling classes across all items.
 */
function cleanupDragStyles() {
    document.querySelectorAll('.is-dragging, .drag-over-target, .drag-over-left, .drag-over-right, .drag-over-top, .drag-over-bottom').forEach(el => {
        el.classList.remove(
            'is-dragging',
            'drag-over-target',
            'drag-over-left',
            'drag-over-right',
            'drag-over-top',
            'drag-over-bottom'
        );
    });
}

/**
 * Baseline overlay ids in the tray's current (stack) order.
 * @returns {string[]}
 */
export function getCurrentOverlayOrder() {
    return Array.from(document.querySelectorAll(CHIP))
        .map(el => el.getAttribute('data-layer-id'))
        .filter(Boolean);
}

/**
 * Computes the reordered IDs of `current` given sourceId, targetId, and drop position.
 * @param {string[]} current
 * @param {string} sourceId
 * @param {string} targetId
 * @param {boolean} isBefore
 * @returns {string[] | null}
 */
function computeReorderedIds(current, sourceId, targetId, isBefore) {
    if (!sourceId || !targetId || sourceId === targetId) return null;
    const srcIdx = current.indexOf(sourceId);
    const tgtIdx = current.indexOf(targetId);
    if (srcIdx === -1 || tgtIdx === -1) return null;

    const listWithoutSrc = current.filter(id => id !== sourceId);
    let insertIdx = listWithoutSrc.indexOf(targetId);
    if (!isBefore) {
        insertIdx += 1;
    }
    listWithoutSrc.splice(insertIdx, 0, sourceId);
    return listWithoutSrc;
}

const PILL = '#scenario-selector-pills .pill-btn[data-scen-id]';
const ROW = '#tbody-scenarios-scorecard .scorecard-row[data-scen-id]';
const CHIP = '#baseline-overlays-chips .baseline-layer-chip[data-layer-id]';

const horizontal = {
    before: 'drag-over-left',
    after: 'drag-over-right',
    isBefore: (e, rect) => e.clientX < rect.left + rect.width / 2
};
const vertical = {
    before: 'drag-over-top',
    after: 'drag-over-bottom',
    isBefore: (e, rect) => e.clientY < rect.top + rect.height / 2
};

/**
 * Drag handlers for one kind of draggable, keyed by event type. `list` names the list it reorders (a drag never
 * drops into another list), `idAttr` holds each item's id, `getOrder` reads the list's current order and `apply`
 * persists a new one; `skip` names controls inside an item that must not start a drag.
 * @param {{list: string, idAttr: string, getOrder: () => string[], apply: (ids: string[]) => void, before: string,
 *   after: string, isBefore: (e: DragEvent, rect: DOMRect) => boolean, skip?: string}} kind
 */
function dragHandlers({ list, idAttr, getOrder, apply, before, after, isBefore, skip }) {
    const markers = ['drag-over-target', before, after];
    const isOurs = () => dragged && dragged.list === list;
    return {
        dragstart: (el, e) => {
            if (skip && e.target.closest(skip)) {
                e.preventDefault();
                return;
            }
            const id = el.getAttribute(idAttr);
            if (!id) return;
            dragged = { list, id };
            el.classList.add('is-dragging');
            if (e.dataTransfer) {
                e.dataTransfer.effectAllowed = 'move';
                e.dataTransfer.setData('text/plain', id);
            }
        },
        dragover: (el, e) => {
            if (!isOurs()) return;
            e.preventDefault();
            const targetId = el.getAttribute(idAttr);
            if (!targetId || targetId === dragged.id) return;
            if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
            const first = isBefore(e, el.getBoundingClientRect());
            el.classList.add('drag-over-target');
            el.classList.toggle(before, first);
            el.classList.toggle(after, !first);
        },
        dragleave: (el) => el.classList.remove(...markers),
        drop: (el, e) => {
            if (!isOurs()) return;
            e.preventDefault();
            cleanupDragStyles();
            const newOrder = computeReorderedIds(
                getOrder(), dragged.id, el.getAttribute(idAttr), isBefore(e, el.getBoundingClientRect())
            );
            if (newOrder) {
                suppressClickUntil = Date.now() + 250;
                apply(newOrder);
            }
            dragged = null;
        },
        dragend: () => {
            cleanupDragStyles();
            suppressClickUntil = Date.now() + 250;
            dragged = null;
        }
    };
}

/**
 * Drag & drop for selector pills, scorecard table rows, and overlay chips, as document-level delegation: nothing is
 * bound to a node, so morphs and re-renders never need to re-wire it. Only `draggable` is (idempotently) set per init.
 */
export function initScenarioDragAndDrop() {
    document.querySelectorAll(`${PILL}, ${ROW}, ${CHIP}`).forEach(el => el.setAttribute('draggable', 'true'));

    // A click that ends a drag gesture must not also select the plan.
    listenOnce(document, 'scenario-reorder', 'click', (e) => {
        const inList = e.target.closest('#scenario-selector-pills, #tbody-scenarios-scorecard');
        if (Date.now() < suppressClickUntil && inList) {
            e.stopImmediatePropagation();
            e.preventDefault();
        }
    }, true);

    delegate(document, 'scenario-reorder', () => {
        const plans = {
            list: 'plans', idAttr: 'data-scen-id', getOrder: getCurrentScenarioOrder, apply: applyScenarioOrder
        };
        const pill = dragHandlers({ ...plans, ...horizontal });
        const row = dragHandlers({ ...plans, ...vertical, skip: 'button, a, input, select, .scorecard-parent-link' });
        const chip = dragHandlers({
            list: 'overlays',
            idAttr: 'data-layer-id',
            getOrder: getCurrentOverlayOrder,
            apply: (ids) => reorderBaselineLayers(ids),
            ...horizontal,
            skip: 'button, input, label'
        });
        return Object.fromEntries(
            Object.keys(pill).map(type => [type, { [PILL]: pill[type], [ROW]: row[type], [CHIP]: chip[type] }])
        );
    });
}
