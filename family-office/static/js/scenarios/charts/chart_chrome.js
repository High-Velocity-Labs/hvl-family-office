/**
 * Loads the server-rendered chrome around a forecasting chart (mode toggles, legend badges, captions) with htmx.
 * The fragments hold no plan data; the controllers here only choose the lens and sub-mode to ask for.
 */
import { h } from './dom.js';

const withSession = (path) => window.appendSessionQuery(path);

function swapInto(target, path) {
    return window.htmx.ajax('GET', withSession(path), { target, swap: 'innerHTML' });
}

/**
 * Appends a slot to `container` and fills it with the toggle strip for `lens`.
 * `modeAttr` names the data attribute carried by the mode buttons; `onMode(value)` fires when one is clicked.
 * The slot is its own click boundary, so re-rendering the container never stacks listeners.
 */
export function loadChartToggles(container, { lens, mode, modeAttr, onMode }) {
    const slot = h('span', { class: 'chart-chrome-slot' });
    if (modeAttr && onMode) {
        slot.addEventListener('click', (e) => {
            const btn = e.target.closest(`[${modeAttr}]`);
            if (!btn) return;
            e.preventDefault();
            onMode(btn.getAttribute(modeAttr));
        });
    }
    container.appendChild(slot);
    const query = mode ? `?mode=${encodeURIComponent(mode)}` : '';
    return swapInto(slot, `/fragments/chart_toggles/${lens}${query}`);
}

export function loadChartCaption(captionEl, { lens, mode }) {
    return swapInto(captionEl, `/fragments/chart_caption/${lens}?mode=${encodeURIComponent(mode)}`);
}
