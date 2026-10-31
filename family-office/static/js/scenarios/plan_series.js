/**
 * static/js/scenarios/plan_series.js
 * One plan's year-by-year series (schedule, cash flows, longevity breakdown). The page's data carries only the
 * selected plan's; a chart that picks another plan asks for it here, shows its loader, and is redrawn once the series
 * arrives from the page's cached forecast (GET /api/scenarios/plan-series with the page's `plan_detail_query`).
 */

import { state } from './state.js';

const PLAN_SERIES_KEYS = ['scenario_schedules', 'scenario_cash_flows', 'scenario_longevity_breakdowns'];
const loading = new Set();

async function loadPlanSeries(data, scenId) {
    if (loading.has(scenId)) return;
    loading.add(scenId);
    let res = null;
    try {
        const query = data.plan_detail_query ? `${data.plan_detail_query}&` : '';
        const resp = await fetch(`/api/scenarios/plan-series?${query}plan_id=${encodeURIComponent(scenId)}`);
        res = await resp.json();
    } catch (err) {
        console.error('Failed to load plan series:', scenId, err);
    } finally {
        loading.delete(scenId);
    }
    // A refresh that replaced the page's data meanwhile carries its own series; these would be stale.
    if (state.scenariosData !== data) return;
    // An unknown plan or a failed load is stored empty, so its chart stops loading instead of asking again.
    PLAN_SERIES_KEYS.forEach((key) => {
        data[key] = { ...(data[key] || {}), [scenId]: (res && res.success && res[key]) || [] };
    });
    window.renderActiveLensChart();
}

/**
 * Plan `scenId`'s series under `key` (one of PLAN_SERIES_KEYS), or null while it loads; the load starts here.
 * @param {string} key
 * @param {string} scenId
 * @returns {Array|null}
 */
export function planSeries(key, scenId) {
    const data = state.scenariosData;
    const series = data?.[key]?.[scenId];
    if (series) return series;
    if (data && scenId) loadPlanSeries(data, scenId);
    return null;
}
