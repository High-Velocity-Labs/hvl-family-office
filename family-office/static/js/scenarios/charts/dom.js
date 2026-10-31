/**
 * DOM construction for chart chrome that depends on per-interaction client data (tooltips, summary cards, SVG).
 * No HTML strings: every value lands via textContent / setAttribute, so there is nothing to escape.
 */

const SVG_NS = 'http://www.w3.org/2000/svg';

function applyProps(node, props) {
    for (const [key, value] of Object.entries(props || {})) {
        if (value === null || value === undefined || value === false) continue;
        if (key === 'class') node.setAttribute('class', value);
        else if (key === 'text') node.textContent = String(value);
        else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
        else node.setAttribute(key, value === true ? '' : String(value));
    }
}

function appendChildren(node, children) {
    for (const child of children.flat(Infinity)) {
        if (child === null || child === undefined || child === false) continue;
        node.appendChild(child.nodeType ? child : node.ownerDocument.createTextNode(String(child)));
    }
}

/** h('div', {class, style, 'data-x', onclick}, ...children) -> HTMLElement */
export function h(tag, props, ...children) {
    const node = document.createElement(tag);
    applyProps(node, props);
    appendChildren(node, children);
    return node;
}

/** s('path', {d, fill}, ...children) -> SVGElement */
export function s(tag, props, ...children) {
    const node = document.createElementNS(SVG_NS, tag);
    applyProps(node, props);
    appendChildren(node, children);
    return node;
}

/** Replaces all children of `el` with `children`. */
export function mount(el, ...children) {
    el.replaceChildren();
    appendChildren(el, children);
    return el;
}

export function clear(el) {
    el.replaceChildren();
    return el;
}
