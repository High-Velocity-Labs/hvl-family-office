/**
 * static/js/scenarios/schedule_table.js
 * The year-by-year schedule table ships with only a loading row. Its rows load from the page's cached forecast
 * (GET /fragments/scenarios/schedule with the page's `plan_detail_query`) whenever the table is open: when it is
 * opened, and after a refresh of the section that leaves it open (the refresh brings back the loading row).
 */

import { state } from './state.js';

export function ensureScheduleRows() {
    const container = document.getElementById('scen-schedule-container');
    const tbody = document.getElementById('scen-schedule-tbody');
    if (!container || !tbody || container.style.display === 'none') return null;
    if (!tbody.querySelector('.scen-schedule-loading-row') || tbody.classList.contains('htmx-request')) return null;
    const query = state.scenariosData?.plan_detail_query;
    return window.htmx.ajax('GET', `/fragments/scenarios/schedule${query ? `?${query}` : ''}`, {
        target: tbody,
        swap: 'innerHTML'
    });
}
