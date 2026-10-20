/**
 * static/js/scenarios/charts/net_worth_config.js
 * Dataset construction, point normalization, and tooltip callbacks for Net Worth Lens.
 */

import {
    state,
    fmtCurrency,
    fmtShortCurrency,
    formatCategoryLabel
} from '../state.js';
import { wrapText } from './common.js';

export function buildAllPoints(historical = [], curves = []) {
    const allPoints = [];
    historical.forEach(h => {
        allPoints.push({
            year: h.year,
            label: `${h.year}`,
            is_historical: true,
            historical_val: h.true_net_worth
        });
    });
    curves.forEach(c => {
        allPoints.push({
            year: c.year,
            label: `${c.year} (Age ${c.age_primary || c.age})`,
            is_historical: false,
            ...c
        });
    });
    return allPoints;
}

export function computeYearYBounds(allPoints, datasets) {
    const yearYBounds = new Map();
    allPoints.forEach((p, idx) => {
        let yMin = 0;
        let yMax = 0;
        datasets.forEach(ds => {
            const v = ds.data ? ds.data[idx] : null;
            if (typeof v === 'number' && Number.isFinite(v)) {
                if (v < yMin) yMin = v;
                if (v > yMax) yMax = v;
            }
        });
        yearYBounds.set(p.year, { min: yMin, max: yMax });
    });
    return yearYBounds;
}

export function buildNetWorthDatasets(allPoints, scenarios, currentScenObj, effectiveScenId, mcTimeline, showMonteCarloCorridor) {
    const datasets = [];
    const theme = window.CHART_THEME;

    // 1. Historical actuals dataset
    const hasHistorical = allPoints.some(p => p.is_historical);
    const histData = allPoints.map(p => (hasHistorical && p.is_historical) ? p.historical_val : ((hasHistorical && p.year === 2026) ? (p.scen_baseline || p[state.selectedScenarioId]) : null));
    datasets.push({
        scenarioId: 'historical_actuals',
        label: 'Historical Actuals (2018–2025)',
        data: histData,
        borderColor: (theme && theme.netWorth.historical) || '#64748B',
        backgroundColor: (theme && theme.netWorth.historicalFill) || 'rgba(100, 116, 139, 0.08)',
        borderWidth: 2,
        borderDash: [4, 4],
        pointRadius: allPoints.map(p => p.is_historical ? 2 : 0),
        tension: 0.25,
        fill: true,
    });

    // 2. Monte Carlo corridor
    if (showMonteCarloCorridor && mcTimeline.length > 0) {
        const p90Data = allPoints.map(p => {
            if (p.is_historical) return null;
            const pt = mcTimeline.find(m => m.year === p.year);
            return pt ? pt.p90 : null;
        });
        const p10Data = allPoints.map(p => {
            if (p.is_historical) return null;
            const pt = mcTimeline.find(m => m.year === p.year);
            return pt ? pt.p10 : null;
        });

        const corridorLabel = `Monte Carlo 10th–90th Range (${currentScenObj.name || 'Selected Plan'})`;
        const corridorBorder = (theme && theme.netWorth.corridorBorder) || 'rgba(29, 78, 216, 0.45)';
        const corridorFill = (theme && theme.netWorth.corridorFill) || 'rgba(29, 78, 216, 0.12)';

        datasets.push({
            label: `${corridorLabel} - Top (90th)`,
            isMonteCarlo: true,
            scenarioId: `mc_${effectiveScenId}_p90`,
            data: p90Data,
            borderColor: corridorBorder,
            borderWidth: 1.5,
            borderDash: [5, 4],
            pointRadius: 0,
            pointHoverRadius: 0,
            tension: 0.25,
            fill: false,
        });

        datasets.push({
            label: corridorLabel,
            isMonteCarlo: true,
            scenarioId: `mc_${effectiveScenId}_p10`,
            data: p10Data,
            borderColor: corridorBorder,
            borderWidth: 1.5,
            borderDash: [5, 4],
            backgroundColor: corridorFill,
            pointRadius: 0,
            pointHoverRadius: 0,
            tension: 0.25,
            fill: '-1',
        });
    }

    // 3. Scenario lines
    const milestones = state.scenariosData.milestones || [];
    scenarios.forEach((scen, scenIdx) => {
        const isSelected = (scen.id === state.selectedScenarioId);
        const color = theme ? theme.normalizeScenarioColor(scen.color, scenIdx) : (scen.color || '#1D4ED8');
        const data = allPoints.map(p => p.is_historical ? null : p[scen.id]);

        const pointRadii = [];
        const pointHoverRadii = [];
        const pointBgColors = [];
        const pointBorderColors = [];
        const pointBorderWidths = [];

        const currentScenEvents = (state.scenariosData.events_catalog || []).filter(e => (scen.event_ids || []).includes(e.id));

        allPoints.forEach(p => {
            if (p.is_historical) {
                pointRadii.push(0);
                pointHoverRadii.push(0);
                pointBgColors.push(color);
                pointBorderColors.push(color);
                pointBorderWidths.push(0);
                return;
            }
            const yr = p.year;
            const hasMilestone = milestones.some(m => m.year === yr);
            const hasEventStart = currentScenEvents.some(e => (e.year || 2026) === yr);
            const hasEventRunning = currentScenEvents.some(e => {
                const s = e.year || 2026;
                const en = e.end_year || s;
                return yr >= s && yr <= en;
            });

            if (isSelected) {
                if (hasEventStart) {
                    pointRadii.push(7.5);
                    pointHoverRadii.push(11);
                    pointBgColors.push('#F59E0B');
                    pointBorderColors.push('#FFFFFF');
                    pointBorderWidths.push(2.5);
                } else if (hasMilestone) {
                    pointRadii.push(6.5);
                    pointHoverRadii.push(10);
                    pointBgColors.push('#FFFFFF');
                    pointBorderColors.push(color);
                    pointBorderWidths.push(2.5);
                } else if (hasEventRunning) {
                    pointRadii.push(4.5);
                    pointHoverRadii.push(7.5);
                    pointBgColors.push(color);
                    pointBorderColors.push('#FFFFFF');
                    pointBorderWidths.push(1.5);
                } else {
                    pointRadii.push(2.5);
                    pointHoverRadii.push(6);
                    pointBgColors.push(color);
                    pointBorderColors.push(color);
                    pointBorderWidths.push(1);
                }
            } else {
                pointRadii.push(1);
                pointHoverRadii.push(4);
                pointBgColors.push(color);
                pointBorderColors.push(color);
                pointBorderWidths.push(1);
            }
        });

        datasets.push({
            scenarioId: scen.id,
            label: scen.name,
            data: data,
            borderColor: color,
            backgroundColor: (theme ? theme.alpha(color, 0.08) : (color + '15')),
            borderWidth: isSelected ? 3.5 : 1.75,
            pointRadius: pointRadii,
            pointHoverRadius: pointHoverRadii,
            pointBackgroundColor: pointBgColors,
            pointBorderColor: pointBorderColors,
            pointBorderWidth: pointBorderWidths,
            tension: 0.3,
            fill: false,
        });
    });

    return datasets;
}

export function buildNetWorthTooltipCallbacks() {
    return {
        title: (items) => {
            if (!items || !items.length) return '';
            const chart = state.scenarioComparisonChart;
            const target = chart?._hoverTarget;
            if (target?.type === 'event_pin' && target.event) {
                const ev = target.event;
                const timing = (ev.year === ev.end_year || !ev.end_year) ? `${ev.year}` : `${ev.year}–${ev.end_year}`;
                return wrapText(`● ${ev.name} (${timing})`, 32);
            }
            if (target?.type === 'milestone_pin' && target.milestone) {
                const ms = target.milestone;
                return wrapText(`◆ Milestone: ${ms.label} (${ms.year})`, 32);
            }
            const idx = items[0].dataIndex;
            const pts = chart?._allPoints || [];
            const pt = pts[idx];
            if (pt) {
                if (pt.is_historical) return `${pt.year} (Historical Actuals)`;
                const pAge = 45 + (pt.year - 2026);
                return `Year ${pt.year} (Age ${pAge})`;
            }
            return items[0].label || '';
        },
        label: (ctx) => {
            const chart = state.scenarioComparisonChart;
            const target = chart?._hoverTarget;
            if (target?.type === 'event_pin' || target?.type === 'milestone_pin') {
                return null;
            }
            if (ctx.raw === null || ctx.raw === undefined) return '';
            return `${ctx.dataset.label}: ${fmtShortCurrency(ctx.raw)}`;
        },
        afterBody: (items) => {
            if (!items || !items.length) return '';
            const chart = state.scenarioComparisonChart;
            const target = chart?._hoverTarget;

            if (target?.type === 'event_pin' && target.event) {
                const ev = target.event;
                const lines = [];
                const catLabel = formatCategoryLabel(ev.category);
                lines.push(`Category: ${catLabel}`);

                if (ev.amount) {
                    lines.push(`Amount: ${fmtCurrency(ev.amount, 0)} (one-time)`);
                } else if (ev.annual_amount) {
                    const dur = (ev.end_year && ev.end_year > ev.year) ? `${ev.end_year - ev.year + 1} years` : 'annual';
                    lines.push(`Annual: ${fmtCurrency(ev.annual_amount, 0)}/yr (${dur})`);
                    const total = ev.annual_amount * ((ev.end_year && ev.end_year >= ev.year) ? (ev.end_year - ev.year + 1) : 1);
                    lines.push(`Total: ${fmtCurrency(total, 0)}`);
                }

                if (ev.description) {
                    wrapText(`Note: ${ev.description}`, 34).forEach(l => lines.push(l));
                }

                if (target.totalEvents > 1) {
                    lines.push(`──────────────────────`);
                    lines.push(`Event ${target.pinIndex + 1} of ${target.totalEvents} in ${target.year}`);
                }
                lines.push(`Click to edit event`);
                return lines;
            }

            if (target?.type === 'milestone_pin' && target.milestone) {
                const ms = target.milestone;
                const lines = [];
                if (ms.description) {
                    wrapText(ms.description, 34).forEach(l => lines.push(l));
                }
                lines.push(`Milestone Year: ${ms.year}`);
                return lines;
            }

            const idx = items[0].dataIndex;
            const pts = chart?._allPoints || [];
            const pt = pts[idx];
            if (!pt || pt.is_historical || !state.scenariosData) return '';
            const yr = pt.year;
            const lines = [];

            const ms = (state.scenariosData.milestones || []).find(m => m.year === yr);
            if (ms) lines.push(`Milestone: ${ms.icon ? ms.icon + ' ' : ''}${ms.label}`);

            const curScen = (state.scenariosData.scenarios || []).find(s => s.id === state.selectedScenarioId) || {};
            const curEvts = (state.scenariosData.events_catalog || []).filter(e => (curScen.event_ids || []).includes(e.id));
            const eventsThisYear = curEvts.filter(e => {
                const s = e.year || 2026;
                const en = e.end_year || s;
                return yr >= s && yr <= en;
            });
            if (eventsThisYear.length > 0) {
                lines.push(`Timeline Events Active:`);
                eventsThisYear.forEach(e => {
                    let amtStr = '';
                    if (e.amount) amtStr = ` (${fmtShortCurrency(e.amount)})`;
                    else if (e.annual_amount) amtStr = ` (${fmtShortCurrency(e.annual_amount)}/yr)`;
                    wrapText(`   ▸ ${e.name}${amtStr}`, 36).forEach(l => lines.push(l));
                });
            }

            const currentCashFlows = (state.scenariosData.scenario_cash_flows && state.selectedScenarioId && state.scenariosData.scenario_cash_flows[state.selectedScenarioId])
                || state.scenariosData.active_cash_flow_series
                || [];
            const cf = currentCashFlows.find(c => c.year === yr);
            if (cf) {
                lines.push(`────────────────────────`);
                if (cf.total_inflow > 0) lines.push(`   +Inflows: ${fmtShortCurrency(cf.total_inflow)}`);
                if (cf.total_outflow > 0) lines.push(`   -Outflows: ${fmtShortCurrency(cf.total_outflow)}`);
                lines.push(`   Net Cash Flow: ${cf.net_cash_flow >= 0 ? '+' : ''}${fmtShortCurrency(cf.net_cash_flow)}`);
            }
            lines.push(`Click point to inspect year`);
            return lines;
        }
    };
}
