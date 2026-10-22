/**
 * Overview & Scenarios Household Widget Drag-and-Drop Reorder Helpers
 * Manages live DOM card swapping, mouse drag events, and touch reordering.
 */

var draggedWidgetCard = null;
var lastWidgetSwapTs = 0;
var dragInitialWidgetOrder = '';

function liveReorderOnDrag(clientY, targetEl) {
    const grid = draggedWidgetCard && draggedWidgetCard.parentElement;
    if (!grid || Date.now() - lastWidgetSwapTs < 75) return;

    const cards = Array.from(grid.querySelectorAll('.household-widget-card[data-widget-id]'));
    if (!cards.length) return;

    const firstCard = cards[0];
    const firstRect = firstCard.getBoundingClientRect();
    if (clientY < firstRect.top + firstRect.height * 0.42) {
        if (firstCard !== draggedWidgetCard) {
            grid.insertBefore(draggedWidgetCard, firstCard);
            lastWidgetSwapTs = Date.now();
        }
        return;
    }

    const hovered = targetEl && targetEl.closest
        ? targetEl.closest('.household-widget-card[data-widget-id]')
        : null;
    if (!hovered || hovered === draggedWidgetCard || hovered.parentElement !== grid) return;

    const rect = hovered.getBoundingClientRect();
    const relY = clientY - rect.top;
    if (relY < rect.height * 0.42 && hovered.previousElementSibling !== draggedWidgetCard) {
        grid.insertBefore(draggedWidgetCard, hovered);
        lastWidgetSwapTs = Date.now();
    } else if (relY > rect.height * 0.58 && hovered.nextElementSibling !== draggedWidgetCard) {
        grid.insertBefore(draggedWidgetCard, hovered.nextSibling);
        lastWidgetSwapTs = Date.now();
    }
}

function startCardDrag(card) {
    draggedWidgetCard = card;
    lastWidgetSwapTs = 0;
    const grid = card.parentElement;
    dragInitialWidgetOrder = grid
        ? Array.from(grid.querySelectorAll('.household-widget-card[data-widget-id]'))
            .map(el => el.getAttribute('data-widget-id'))
            .join(',')
        : '';
    card.style.opacity = '0.6';
    card.style.outline = '2px solid #3B82F6';
}

function finishWidgetDrag() {
    if (!draggedWidgetCard) return;

    const card = draggedWidgetCard;
    const grid = card.parentElement;
    draggedWidgetCard = null;
    card.style.opacity = '';
    if (!grid) return;

    const page = grid.id === 'overview-widgets-grid' ? 'overview' : 'scenarios';
    applyWidgetEditModeUI(page);

    const nextIds = Array.from(grid.querySelectorAll('.household-widget-card[data-widget-id]'))
        .map(el => el.getAttribute('data-widget-id'))
        .filter(Boolean);
    if (nextIds.join(',') !== dragInitialWidgetOrder) {
        saveHouseholdWidgetPreferences(page, nextIds, false, { reorderOnly: true });
    }
}

function bindWidgetDragAndTouchEvents() {
    document.addEventListener('dragstart', (e) => {
        const card = e.target.closest('.household-widget-card[data-widget-id]');
        if (!card) return;

        const page = card.parentElement && card.parentElement.id === 'overview-widgets-grid'
            ? 'overview'
            : 'scenarios';
        if (!widgetEditModeByPage[page]) {
            e.preventDefault();
            return;
        }

        startCardDrag(card);
        if (e.dataTransfer) {
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', card.getAttribute('data-widget-id') || '');
        }
    });

    document.addEventListener('dragover', (e) => {
        if (!draggedWidgetCard) return;
        e.preventDefault();
        if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
        liveReorderOnDrag(e.clientY, e.target);
    });

    document.addEventListener('drop', (e) => {
        if (!draggedWidgetCard) return;
        e.preventDefault();
        finishWidgetDrag();
    });

    document.addEventListener('dragend', finishWidgetDrag);

    document.addEventListener('touchstart', (e) => {
        const handle = e.target.closest('.widget-drag-handle');
        const card = handle && handle.closest('.household-widget-card[data-widget-id]');
        if (!card || !widgetEditModeByPage[handle.getAttribute('data-page')]) return;
        if (e.cancelable) e.preventDefault();
        startCardDrag(card);
    }, { passive: false });

    document.addEventListener('touchmove', (e) => {
        const t = draggedWidgetCard && e.touches && e.touches[0];
        if (!t) return;
        if (e.cancelable) e.preventDefault();

        if (typeof window.scrollBy === 'function') {
            const hdr = document.querySelector('.top-header');
            const topEdge = (hdr ? Math.max(0, hdr.getBoundingClientRect().bottom) : 0) + 55;
            if (t.clientY < topEdge) {
                window.scrollBy(0, -16);
            } else if (t.clientY > window.innerHeight - 85) {
                window.scrollBy(0, 16);
            }
        }

        const hitEl = typeof document.elementFromPoint === 'function'
            ? document.elementFromPoint(t.clientX, t.clientY)
            : null;
        liveReorderOnDrag(t.clientY, hitEl);
    }, { passive: false });

    document.addEventListener('touchend', () => {
        if (draggedWidgetCard) finishWidgetDrag();
    });

    document.addEventListener('touchcancel', () => {
        if (draggedWidgetCard) finishWidgetDrag();
    });
}
