/**
 * static/js/scenarios/cards_reorder.js
 * Drag & Drop reordering controller for scenario selector pills and scorecard table rows.
 * Syncs DOM order across selector pills and comparison table, updates in-memory scenarios order,
 * re-renders the graph toggles/curves immediately, and persists order via POST /api/scenarios/reorder.
 */

import { state } from './state.js';
import { renderActiveLensChart } from './charts/index.js';

let draggedScenId = null;
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
        if (typeof renderActiveLensChart === 'function') {
            renderActiveLensChart();
        } else if (typeof window.renderActiveLensChart === 'function') {
            window.renderActiveLensChart();
        }
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
 * Computes the reordered scenario IDs given sourceId, targetId, and drop position.
 * @param {string} sourceId
 * @param {string} targetId
 * @param {boolean} isBefore
 * @returns {string[] | null}
 */
function computeReorderedIds(sourceId, targetId, isBefore) {
    if (!sourceId || !targetId || sourceId === targetId) return null;
    const current = getCurrentScenarioOrder();
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

/**
 * Initializes drag & drop for selector pills and scorecard table rows.
 */
export function initScenarioDragAndDrop() {
    const pillsContainer = document.getElementById('scenario-selector-pills');
    const scorecardTbody = document.getElementById('tbody-scenarios-scorecard');

    // Intercept clicks if just completed a drag gesture
    if (pillsContainer && !pillsContainer.dataset.reorderCaptureWired) {
        pillsContainer.dataset.reorderCaptureWired = 'true';
        pillsContainer.addEventListener('click', (e) => {
            if (Date.now() < suppressClickUntil) {
                e.stopImmediatePropagation();
                e.preventDefault();
            }
        }, true);
    }

    if (scorecardTbody && !scorecardTbody.dataset.reorderCaptureWired) {
        scorecardTbody.dataset.reorderCaptureWired = 'true';
        scorecardTbody.addEventListener('click', (e) => {
            if (Date.now() < suppressClickUntil) {
                e.stopImmediatePropagation();
                e.preventDefault();
            }
        }, true);
    }

    // 1. Wire selector pills
    if (pillsContainer) {
        pillsContainer.querySelectorAll('.pill-btn[data-scen-id]').forEach(pill => {
            if (pill.dataset.dragWired) return;
            pill.dataset.dragWired = 'true';
            pill.setAttribute('draggable', 'true');

            pill.addEventListener('dragstart', (e) => {
                const scenId = pill.getAttribute('data-scen-id');
                if (!scenId) return;
                draggedScenId = scenId;
                pill.classList.add('is-dragging');
                if (e.dataTransfer) {
                    e.dataTransfer.effectAllowed = 'move';
                    e.dataTransfer.setData('text/plain', scenId);
                }
            });

            pill.addEventListener('dragover', (e) => {
                e.preventDefault();
                if (!draggedScenId) return;
                const targetId = pill.getAttribute('data-scen-id');
                if (!targetId || targetId === draggedScenId) return;

                if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
                const rect = pill.getBoundingClientRect();
                const isLeft = e.clientX < rect.left + rect.width / 2;

                pill.classList.add('drag-over-target');
                pill.classList.toggle('drag-over-left', isLeft);
                pill.classList.toggle('drag-over-right', !isLeft);
            });

            pill.addEventListener('dragleave', () => {
                pill.classList.remove('drag-over-target', 'drag-over-left', 'drag-over-right');
            });

            pill.addEventListener('drop', (e) => {
                e.preventDefault();
                cleanupDragStyles();
                if (!draggedScenId) return;
                const targetId = pill.getAttribute('data-scen-id');
                const rect = pill.getBoundingClientRect();
                const isLeft = e.clientX < rect.left + rect.width / 2;

                const newOrder = computeReorderedIds(draggedScenId, targetId, isLeft);
                if (newOrder) {
                    suppressClickUntil = Date.now() + 250;
                    applyScenarioOrder(newOrder);
                }
                draggedScenId = null;
            });

            pill.addEventListener('dragend', () => {
                cleanupDragStyles();
                suppressClickUntil = Date.now() + 250;
                draggedScenId = null;
            });
        });
    }

    // 2. Wire comparison table rows
    if (scorecardTbody) {
        scorecardTbody.querySelectorAll('.scorecard-row[data-scen-id]').forEach(row => {
            if (row.dataset.dragWired) return;
            row.dataset.dragWired = 'true';
            row.setAttribute('draggable', 'true');

            row.addEventListener('dragstart', (e) => {
                // If interactive action button clicked, cancel row drag
                if (e.target.closest('button, a, input, select, .scorecard-parent-link')) {
                    e.preventDefault();
                    return;
                }
                const scenId = row.getAttribute('data-scen-id');
                if (!scenId) return;
                draggedScenId = scenId;
                row.classList.add('is-dragging');
                if (e.dataTransfer) {
                    e.dataTransfer.effectAllowed = 'move';
                    e.dataTransfer.setData('text/plain', scenId);
                }
            });

            row.addEventListener('dragover', (e) => {
                e.preventDefault();
                if (!draggedScenId) return;
                const targetId = row.getAttribute('data-scen-id');
                if (!targetId || targetId === draggedScenId) return;

                if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
                const rect = row.getBoundingClientRect();
                const isTop = e.clientY < rect.top + rect.height / 2;

                row.classList.add('drag-over-target');
                row.classList.toggle('drag-over-top', isTop);
                row.classList.toggle('drag-over-bottom', !isTop);
            });

            row.addEventListener('dragleave', () => {
                row.classList.remove('drag-over-target', 'drag-over-top', 'drag-over-bottom');
            });

            row.addEventListener('drop', (e) => {
                e.preventDefault();
                cleanupDragStyles();
                if (!draggedScenId) return;
                const targetId = row.getAttribute('data-scen-id');
                const rect = row.getBoundingClientRect();
                const isTop = e.clientY < rect.top + rect.height / 2;

                const newOrder = computeReorderedIds(draggedScenId, targetId, isTop);
                if (newOrder) {
                    suppressClickUntil = Date.now() + 250;
                    applyScenarioOrder(newOrder);
                }
                draggedScenId = null;
            });

            row.addEventListener('dragend', () => {
                cleanupDragStyles();
                suppressClickUntil = Date.now() + 250;
                draggedScenId = null;
            });
        });
    }
}
