/**
 * static/js/scenarios/event_modals_inputs.js
 * Reading the life-event wizard's inputs. A blank or absent input is null (never an invented number): callers leave
 * the key out of the payload and the server validates or applies its own default.
 */

export function numberFrom(id) {
    const el = document.getElementById(id);
    if (!el || String(el.value).trim() === '') return null;
    const n = parseFloat(el.value);
    return Number.isFinite(n) ? n : null;
}

/** The selected option of a select, or (given `value`) the option with that value. Tier data lives in data-* attrs. */
export function optionOf(id, value = null) {
    const el = document.getElementById(id);
    if (!el) return null;
    return value === null ? (el.selectedOptions[0] || null) : ([...el.options].find(o => o.value === value) || null);
}

/** The server-rendered annual cost (`data-annual-cost`) of a select's selected option; null for "custom". */
export function tierCost(id, value = null) {
    const raw = optionOf(id, value)?.dataset.annualCost;
    const n = parseFloat(raw);
    return raw === undefined || !Number.isFinite(n) ? null : n;
}

export function percentFrom(id) {
    const n = numberFrom(id);
    return n === null ? null : n / 100.0;
}

export function firstNumber(...values) {
    const hit = values.find(v => v !== null && v !== undefined && v !== '' && Number.isFinite(Number(v)));
    return hit === undefined ? '' : Number(hit);
}

export function assignPresent(target, fields) {
    Object.entries(fields).forEach(([key, value]) => {
        if (value !== null && value !== undefined) target[key] = value;
    });
    return target;
}
