/**
 * static/js/scenarios/event_delegation.js
 * Event delegation for the scenario modals: one listener per event type on a stable root, dispatching on the id of
 * the element the event came from. HTMX morphs replace the modal markup freely, so nothing is bound to a node.
 */

const installed = new WeakMap();
// Events that do not bubble are caught on the way down instead.
const CAPTURED = new Set(['focus', 'blur', 'mouseenter', 'mouseleave', 'load', 'error', 'scroll']);

/** A bare key is an element id; a key starting with `#`, `.` or `[`, or holding a combinator, is a CSS selector. */
const toSelector = (key) => (/^[#.[]|[\s>:]/.test(key) ? key : `#${key}`);

/**
 * @param {EventTarget} root stable ancestor (the document)
 * @param {string} name which set of handlers this is; installing a name on a root a second time is a no-op
 * @param {() => Record<string, Record<string, (el: Element, e: Event) => unknown>>} buildHandlers
 *        event type -> element id (or CSS selector) -> handler. A function so the table is built when first
 *        installed: the modal modules import each other in a cycle, and a module-level table would be read before
 *        it is initialized. The nearest ancestor matching any key handles the event, and every key it matches runs.
 */
export function delegate(root, name, buildHandlers) {
    const seen = installed.get(root) || new Set();
    if (seen.has(name)) return;
    seen.add(name);
    installed.set(root, seen);
    const handlers = buildHandlers();
    Object.entries(handlers).forEach(([type, byKey]) => {
        const entries = Object.entries(byKey).map(([key, fn]) => [toSelector(key), fn]);
        const selector = entries.map(([sel]) => sel).join(',');
        root.addEventListener(type, (e) => {
            const el = e.target.closest ? e.target.closest(selector) : null;
            if (!el) return;
            entries.forEach(([sel, fn]) => { if (el.matches(sel)) fn(el, e); });
        }, CAPTURED.has(type));
    });
}

/** One document-level listener per (root, name) for events that belong to no element, like click-outside. */
export function listenOnce(root, name, type, handler, capture = false) {
    const seen = installed.get(root) || new Set();
    const key = `${name}:${type}`;
    if (seen.has(key)) return;
    seen.add(key);
    installed.set(root, seen);
    root.addEventListener(type, handler, capture);
}
