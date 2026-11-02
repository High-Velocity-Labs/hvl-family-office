/**
 * static/js/scenarios/charts/net_worth_tooltip.js
 * Custom HTML/DOM columnar tooltip builder, maximum Net Worth bolding,
 * cash flow attribution, event pin and milestone pin formatters.
 */

import {
    state,
    fmtCurrency,
    fmtShortCurrency,
    formatCategoryLabel,
    getGraphScenarioId,
    getPlanStartYear
} from '../state.js';
import { wrapText } from './common.js';
import { planSeries } from '../plan_series.js';
import { h } from './dom.js';

const row = (cls, ...kids) => h('div', { class: `nw-tip-row ${cls}` }, ...kids);
const section = (title, ...kids) => h('div', { class: 'nw-tip-section' },
    h('div', { class: 'nw-tip-section-title', text: title }), ...kids);

function buildEventPinNode(ev, target) {
    const timing = (ev.year === ev.end_year || !ev.end_year) ? `${ev.year}` : `${ev.year}–${ev.end_year}`;
    const catLabel = formatCategoryLabel(ev.category);

    let amountLines = [];
    if (ev.amount) {
        amountLines = [`Amount: ${fmtCurrency(ev.amount, 0)} (one-time)`];
    } else if (ev.annual_amount) {
        const dur = (ev.end_year && ev.end_year > ev.year) ? `${ev.end_year - ev.year + 1} years` : 'annual';
        const total = ev.annual_amount * ((ev.end_year && ev.end_year >= ev.year) ? (ev.end_year - ev.year + 1) : 1);
        amountLines = [`Annual: ${fmtCurrency(ev.annual_amount, 0)}/yr (${dur})`, `Total: ${fmtCurrency(total, 0)}`];
    }
    const amountNode = amountLines.length
        ? h('div', { class: 'nw-tip-line nw-tip-line--amount' },
            amountLines.flatMap((line, i) => (i ? [h('br'), line] : [line])))
        : null;

    return h('div', null,
        h('div', { class: 'nw-tip-title nw-tip-title--pin' },
            h('span', { class: 'nw-tip-event-dot' }),
            h('span', { text: `${ev.name} (${timing})` })),
        h('div', { class: 'nw-tip-line' }, 'Category: ', h('span', { class: 'nw-tip-value', text: catLabel })),
        amountNode,
        ev.description && h('div', { class: 'nw-tip-line nw-tip-line--note', text: `Note: ${ev.description}` }),
        target.totalEvents > 1 && h('div', {
            class: 'nw-tip-count', text: `Event ${target.pinIndex + 1} of ${target.totalEvents} in ${target.year}`
        }),
        h('div', { class: 'nw-tip-action' }, h('span', { text: '✎' }), ' Click to edit event'));
}

function buildMilestonePinNode(ms) {
    return h('div', null,
        h('div', { class: 'nw-tip-title nw-tip-title--pin' },
            h('span', { class: 'nw-tip-milestone-icon', text: '◆' }),
            h('span', { text: `Milestone: ${ms.label} (${ms.year})` })),
        ms.description && h('div', { class: 'nw-tip-line', text: ms.description }),
        h('div', { class: 'nw-tip-line nw-tip-line--year' }, 'Milestone Year: ',
            h('span', { class: 'nw-tip-value--strong', text: String(ms.year) })));
}

function buildColumnarComparisonTable(pt, scenarios) {
    const theme = window.CHART_THEME;
    let maxVal = -Infinity;
    let maxScenId = null;

    scenarios.forEach(scen => {
        const val = pt[scen.id];
        if (typeof val === 'number' && Number.isFinite(val) && val > maxVal) {
            maxVal = val;
            maxScenId = scen.id;
        }
    });

    const effectiveScenId = getGraphScenarioId('networth');
    const rows = scenarios.map((scen, scenIdx) => {
        const val = pt[scen.id];
        if (typeof val !== 'number' || !Number.isFinite(val)) return null;

        const isSelected = (scen.id === effectiveScenId);
        const isMax = (scen.id === maxScenId && scenarios.length > 1);
        const swatch = h('span', { class: 'nw-tip-swatch' });
        swatch.style.setProperty('--swatch', theme.normalizeScenarioColor(scen.color, scenIdx));

        return h('tr', { class: `nw-tip-scen${isMax ? ' is-max' : ''}${isSelected ? ' is-selected' : ''}` },
            h('td', { class: 'nw-tip-scen-name' },
                swatch,
                h('span', { text: scen.name }),
                isSelected && h('span', { class: 'nw-tip-active-tag', text: '★ Active' }),
                isMax && h('span', { class: 'nw-tip-high-tag', text: 'HIGH' })),
            h('td', { class: 'nw-tip-scen-value', text: fmtCurrency(val, 0) }));
    });

    return h('table', { class: 'nw-tip-table' }, h('tbody', null, rows));
}

function buildCashFlowNode(yr, curScen) {
    const currentScenarioName = curScen.name || 'Selected Plan';
    const effectiveScenId = curScen.id || getGraphScenarioId('networth');
    const currentCashFlows = planSeries('scenario_cash_flows', effectiveScenId) || [];
    const cf = currentCashFlows.find(c => c.year === yr);
    if (!cf) return null;

    const flowRow = (cls, label, amount) => row(cls,
        h('span', { text: label }), h('span', { text: fmtShortCurrency(amount) }));
    const netClass = cf.net_cash_flow >= 0 ? 'is-positive' : 'is-negative';

    return section(`Cash Flow (${currentScenarioName}):`,
        cf.total_inflow > 0 && flowRow('nw-tip-row--in', '+ Inflows', cf.total_inflow),
        cf.total_outflow > 0 && flowRow('nw-tip-row--out', '− Outflows', cf.total_outflow),
        row(`nw-tip-row--net ${netClass}`,
            h('span', { text: 'Net Cash Flow' }),
            h('span', { text: `${cf.net_cash_flow >= 0 ? '+' : ''}${fmtShortCurrency(cf.net_cash_flow)}` })));
}

/** Builds the tooltip body for the hovered target as DOM nodes, or null when there is nothing to show. */
export function buildTooltipNode(chart, target, tooltipItem) {
    if (!target) return null;
    if (target.type === 'event_pin' && target.event) return buildEventPinNode(target.event, target);
    if (target.type === 'milestone_pin' && target.milestone) return buildMilestonePinNode(target.milestone);

    const idx = target.index ?? (tooltipItem ? tooltipItem.dataIndex : 0);
    const pts = chart._allPoints || [];
    const pt = pts[idx];
    if (!pt) return null;

    if (pt.is_historical) {
        return h('div', null,
            h('div', { class: 'nw-tip-title', text: `Year ${pt.year} (Historical Actuals)` }),
            h('div', { class: 'nw-tip-historical' },
                h('span', { text: 'Historical Net Worth' }),
                h('span', { class: 'nw-tip-num', text: fmtCurrency(pt.historical_val, 0) })));
    }

    const yr = pt.year;
    const pAge = pt.age_primary || pt.age || (45 + (yr - getPlanStartYear()));
    const ms = (state.scenariosData?.milestones || []).find(m => m.year === yr);
    const scenarios = state.scenariosData?.scenarios || [];
    const effectiveScenId = getGraphScenarioId('networth');
    const curScen = scenarios.find(s => s.id === effectiveScenId) || scenarios[0] || {};
    const curEvts = (state.scenariosData?.events_catalog || []).filter(e => (curScen.event_ids || []).includes(e.id));
    const eventsThisYear = curEvts.filter(e => {
        const s = e.year || getPlanStartYear();
        const en = e.end_year || s;
        return yr >= s && yr <= en;
    });

    const eventsNode = eventsThisYear.length ? section('Timeline Events Active:', eventsThisYear.map(e => {
        const amtBadge = e.amount ? ` (${fmtShortCurrency(e.amount)})` : (e.annual_amount ? ` `
            + `(${fmtShortCurrency(e.annual_amount)}/yr)` : '');
        return row('', h('span', { text: `▸ ${e.name}` }), h('span', { class: 'nw-tip-muted', text: amtBadge }));
    })) : null;

    return h('div', null,
        h('div', { class: 'nw-tip-title nw-tip-title--year' },
            h('span', { text: `Year ${yr} (Age ${pAge})` }),
            ms && h('span', { class: 'nw-tip-milestone-tag', text: `◆ ${ms.label}` })),
        buildColumnarComparisonTable(pt, scenarios),
        eventsNode,
        buildCashFlowNode(yr, curScen));
}

export function customNetWorthTooltip(context) {
    if (typeof document === 'undefined') return;
    const { chart, tooltip } = context;
    if (!chart || !chart.canvas || !chart.canvas.parentNode) return;

    const parent = chart.canvas.parentNode;
    let tooltipEl = parent.querySelector('.chartjs-net-worth-tooltip');
    if (!tooltipEl) {
        tooltipEl = document.createElement('div');
        tooltipEl.className = 'chartjs-net-worth-tooltip';
        parent.appendChild(tooltipEl);
    }

    if (!tooltip || tooltip.opacity === 0 || !chart._hoverTarget) {
        tooltipEl.classList.remove('is-visible');
        return;
    }

    const body = buildTooltipNode(chart, chart._hoverTarget, tooltip.dataPoints?.[0]);
    if (!body) {
        tooltipEl.classList.remove('is-visible');
        return;
    }

    tooltipEl.replaceChildren(body);
    tooltipEl.classList.add('is-visible');

    const target = chart._hoverTarget;
    const targetX = (target && typeof target.x === 'number') ? target.x : (tooltip.caretX ?? 0);
    const targetY = (target && typeof target.y === 'number') ? target.y : (tooltip.caretY ?? 0);

    const canvasLeft = chart.canvas.offsetLeft || 0;
    const canvasTop = chart.canvas.offsetTop || 0;
    const stageWidth = parent.clientWidth || 800;
    const stageHeight = parent.clientHeight || 460;
    const tipWidth = tooltipEl.offsetWidth || 260;
    const tipHeight = tooltipEl.offsetHeight || 160;

    let posX = canvasLeft + targetX;
    let posY = canvasTop + targetY;

    if (target.type === 'event_pin' || target.type === 'milestone_pin') {
        const spaceLeft = targetX;
        const spaceRight = stageWidth - targetX;
        if (spaceLeft >= tipWidth + 20 || spaceLeft >= spaceRight) {
            posX = canvasLeft + targetX - tipWidth - 16;
        } else {
            const isExpandedCluster = (target.totalEvents > 1 && chart._hoveredClusterYear === target.year);
            const offsetRight = isExpandedCluster ? 135 : 20;
            posX = canvasLeft + targetX + offsetRight;
        }
        posY = Math.max(10, Math.min(stageHeight - tipHeight - 10, canvasTop + targetY - tipHeight / 2));
    } else {
        if (targetX + tipWidth + 18 > stageWidth) {
            posX = canvasLeft + targetX - tipWidth - 14;
        } else {
            posX = canvasLeft + targetX + 14;
        }
        posY = Math.max(10, Math.min(stageHeight - tipHeight - 10, canvasTop + targetY - tipHeight / 3));
    }

    posX = Math.max(8, Math.min(stageWidth - tipWidth - 8, posX));
    posY = Math.max(8, Math.min(stageHeight - tipHeight - 8, posY));

    tooltipEl.style.left = `${posX}px`;
    tooltipEl.style.top = `${posY}px`;
}

function formatPinEventLines(ev, target) {
    const lines = [`Category: ${formatCategoryLabel(ev.category)}`];
    if (ev.amount) {
        lines.push(`Amount: ${fmtCurrency(ev.amount, 0)} (one-time)`);
    } else if (ev.annual_amount) {
        const dur = (ev.end_year && ev.end_year > ev.year) ? `${ev.end_year - ev.year + 1} years` : 'annual';
        lines.push(`Annual: ${fmtCurrency(ev.annual_amount, 0)}/yr (${dur})`);
        const total = ev.annual_amount * ((ev.end_year && ev.end_year >= ev.year) ? (ev.end_year - ev.year + 1) : 1);
        lines.push(`Total: ${fmtCurrency(total, 0)}`);
    }
    if (ev.description) wrapText(`Note: ${ev.description}`, 34).forEach(l => lines.push(l));
    if (target.totalEvents > 1) {
        lines.push(`──────────────────────`);
        lines.push(`Event ${target.pinIndex + 1} of ${target.totalEvents} in ${target.year}`);
    }
    lines.push(`Click to edit event`);
    return lines;
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
                return wrapText(`◆ Milestone: ${target.milestone.label} (${target.milestone.year})`, 32);
            }
            const idx = items[0].dataIndex;
            const pts = chart?._allPoints || [];
            const pt = pts[idx];
            if (pt) {
                if (pt.is_historical) return `${pt.year} (Historical Actuals)`;
                const pAge = pt.age_primary || pt.age || (45 + (pt.year - getPlanStartYear()));
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
                return formatPinEventLines(target.event, target);
            }
            if (target?.type === 'milestone_pin' && target.milestone) {
                const lines = target.milestone.description ? wrapText(target.milestone.description, 34) : [];
                lines.push(`Milestone Year: ${target.milestone.year}`);
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

            const effectiveScenId = getGraphScenarioId('networth');
            const curScen = (state.scenariosData.scenarios || []).find(s => s.id === effectiveScenId) || {};
            const curEvts = (state.scenariosData.events_catalog || []).filter(e => (curScen.event_ids || []).includes(e.id));
            const eventsThisYear = curEvts.filter(e => {
                const s = e.year || getPlanStartYear();
                const en = e.end_year || s;
                return yr >= s && yr <= en;
            });
            if (eventsThisYear.length > 0) {
                lines.push(`Timeline Events Active:`);
                eventsThisYear.forEach(e => {
                    const amtStr = e.amount ? ` (${fmtShortCurrency(e.amount)})` : (e.annual_amount ? ` (${fmtShortCurrency(e.annual_amount)}/yr)` : '');
                    wrapText(`   ▸ ${e.name}${amtStr}`, 36).forEach(l => lines.push(l));
                });
            }

            const currentScenarioName = curScen.name || 'Selected Plan';
            const currentCashFlows = planSeries('scenario_cash_flows', effectiveScenId) || [];
            const cf = currentCashFlows.find(c => c.year === yr);
            if (cf) {
                lines.push(`────────────────────────`);
                lines.push(`Cash Flow (${currentScenarioName}):`);
                if (cf.total_inflow > 0) lines.push(`   +Inflows: ${fmtShortCurrency(cf.total_inflow)}`);
                if (cf.total_outflow > 0) lines.push(`   -Outflows: ${fmtShortCurrency(cf.total_outflow)}`);
                lines.push(`   Net Cash Flow: ${cf.net_cash_flow >= 0 ? '+' : ''}${fmtShortCurrency(cf.net_cash_flow)}`);
            }
            return lines;
        }
    };
}
