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
    escapeHtml
} from '../state.js';
import { wrapText } from './common.js';

function renderEventPinHtml(ev, target) {
    const timing = (ev.year === ev.end_year || !ev.end_year) ? `${ev.year}` : `${ev.year}–${ev.end_year}`;
    const catLabel = formatCategoryLabel(ev.category);

    let amtStr = '';
    if (ev.amount) {
        amtStr = `Amount: ${fmtCurrency(ev.amount, 0)} (one-time)`;
    } else if (ev.annual_amount) {
        const dur = (ev.end_year && ev.end_year > ev.year) ? `${ev.end_year - ev.year + 1} years` : 'annual';
        const total = ev.annual_amount * ((ev.end_year && ev.end_year >= ev.year) ? (ev.end_year - ev.year + 1) : 1);
        amtStr = `Annual: ${fmtCurrency(ev.annual_amount, 0)}/yr (${dur})<br>Total: ${fmtCurrency(total, 0)}`;
    }

    return `
        <div style="font-weight: 700; font-size: 0.8125rem; color: #F8FAFC; margin-bottom: 5px; display: flex; align-items: center; gap: 6px;">
            <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #F59E0B; flex-shrink: 0;"></span>
            <span>${escapeHtml(ev.name)} (${timing})</span>
        </div>
        <div style="font-size: 0.71875rem; color: #94A3B8; margin-bottom: 4px;">
            Category: <span style="color: #E2E8F0; font-weight: 500;">${escapeHtml(catLabel)}</span>
        </div>
        ${amtStr ? `<div style="font-size: 0.71875rem; color: #E2E8F0; margin-bottom: 4px; line-height: 1.4;">${amtStr}</div>` : ''}
        ${ev.description ? `<div style="font-size: 0.71875rem; color: #94A3B8; margin-top: 4px; line-height: 1.3;">Note: ${escapeHtml(ev.description)}</div>` : ''}
        ${target.totalEvents > 1 ? `<div style="font-size: 0.6875rem; color: #64748B; margin-top: 6px; padding-top: 4px; border-top: 1px dashed rgba(255,255,255,0.12);">Event ${target.pinIndex + 1} of ${target.totalEvents} in ${target.year}</div>` : ''}
        <div style="font-size: 0.6875rem; color: #60A5FA; margin-top: 6px; font-weight: 600; display: flex; align-items: center; gap: 4px;">
            <span>✎</span> Click to edit event
        </div>
    `;
}

function renderMilestonePinHtml(ms) {
    return `
        <div style="font-weight: 700; font-size: 0.8125rem; color: #F8FAFC; margin-bottom: 5px; display: flex; align-items: center; gap: 6px;">
            <span style="color: #38BDF8; font-size: 0.875rem;">◆</span>
            <span>Milestone: ${escapeHtml(ms.label)} (${ms.year})</span>
        </div>
        ${ms.description ? `<div style="font-size: 0.71875rem; color: #94A3B8; margin-bottom: 4px; line-height: 1.3;">${escapeHtml(ms.description)}</div>` : ''}
        <div style="font-size: 0.71875rem; color: #CBD5E1;">
            Milestone Year: <span style="font-weight: 600; color: #FFFFFF;">${ms.year}</span>
        </div>
    `;
}

function renderColumnarComparisonTable(pt, scenarios) {
    const theme = typeof window !== 'undefined' ? window.CHART_THEME : null;
    let maxVal = -Infinity;
    let maxScenId = null;

    scenarios.forEach(scen => {
        const val = pt[scen.id];
        if (typeof val === 'number' && Number.isFinite(val) && val > maxVal) {
            maxVal = val;
            maxScenId = scen.id;
        }
    });

    const rowsHtml = scenarios.map((scen, scenIdx) => {
        const val = pt[scen.id];
        if (typeof val !== 'number' || !Number.isFinite(val)) return '';

        const isSelected = (scen.id === state.selectedScenarioId);
        const isMax = (scen.id === maxScenId && scenarios.length > 1);
        const color = theme ? theme.normalizeScenarioColor(scen.color, scenIdx) : (scen.color || '#1D4ED8');

        const rowBg = isMax
            ? 'background: rgba(255, 255, 255, 0.09);'
            : (isSelected ? 'background: rgba(29, 78, 216, 0.12);' : '');
        const fontWeight = isMax ? '700' : (isSelected ? '600' : '400');
        const textColor = isMax ? '#FFFFFF' : (isSelected ? '#F1F5F9' : '#CBD5E1');
        const valColor = isMax ? '#FFFFFF' : '#94A3B8';

        return `
            <tr style="${rowBg} border-radius: 4px;">
                <td style="padding: 3px 6px; font-weight: ${fontWeight}; color: ${textColor}; display: flex; align-items: center; gap: 6px; white-space: nowrap;">
                    <span style="width: 7px; height: 7px; border-radius: 50%; background: ${color}; flex-shrink: 0;"></span>
                    <span>${escapeHtml(scen.name)}</span>
                    ${isSelected ? '<span style="color: #F59E0B; font-size: 0.65625rem; font-weight: 600; margin-left: 2px;">★ Active</span>' : ''}
                    ${isMax ? '<span style="font-size: 0.59375rem; color: #10B981; font-weight: 700; margin-left: auto; padding-left: 6px;">HIGH</span>' : ''}
                </td>
                <td style="padding: 3px 6px; text-align: right; white-space: nowrap; font-weight: ${fontWeight}; color: ${valColor}; font-variant-numeric: tabular-nums;">
                    ${fmtCurrency(val, 0)}
                </td>
            </tr>
        `;
    }).join('');

    return `
        <table style="width: 100%; border-collapse: collapse; font-size: 0.75rem; margin-bottom: 2px;">
            <tbody>${rowsHtml}</tbody>
        </table>
    `;
}

function renderCashFlowHtml(yr, curScen) {
    const currentScenarioName = curScen.name || 'Selected Plan';
    const currentCashFlows = (state.scenariosData?.scenario_cash_flows && state.selectedScenarioId && state.scenariosData.scenario_cash_flows[state.selectedScenarioId])
        || state.scenariosData?.active_cash_flow_series
        || [];
    const cf = currentCashFlows.find(c => c.year === yr);
    if (!cf) return '';

    const inflowRow = cf.total_inflow > 0
        ? `<div style="display: flex; justify-content: space-between; color: #10B981; padding: 1px 0; font-variant-numeric: tabular-nums;"><span>+ Inflows</span><span>${fmtShortCurrency(cf.total_inflow)}</span></div>`
        : '';
    const outflowRow = cf.total_outflow > 0
        ? `<div style="display: flex; justify-content: space-between; color: #F43F5E; padding: 1px 0; font-variant-numeric: tabular-nums;"><span>− Outflows</span><span>${fmtShortCurrency(cf.total_outflow)}</span></div>`
        : '';

    return `
        <div style="margin-top: 6px; padding-top: 6px; border-top: 1px solid rgba(255, 255, 255, 0.1); font-size: 0.71875rem;">
            <div style="font-weight: 600; color: #94A3B8; margin-bottom: 3px;">Cash Flow (${escapeHtml(currentScenarioName)}):</div>
            ${inflowRow}
            ${outflowRow}
            <div style="display: flex; justify-content: space-between; font-weight: 600; color: ${cf.net_cash_flow >= 0 ? '#10B981' : '#F43F5E'}; padding: 2px 0; border-top: 1px dashed rgba(255, 255, 255, 0.08); margin-top: 2px; font-variant-numeric: tabular-nums;">
                <span>Net Cash Flow</span>
                <span>${cf.net_cash_flow >= 0 ? '+' : ''}${fmtShortCurrency(cf.net_cash_flow)}</span>
            </div>
        </div>
    `;
}

export function renderTooltipHtml(chart, target, tooltipItem) {
    if (!target) return '';
    if (target.type === 'event_pin' && target.event) return renderEventPinHtml(target.event, target);
    if (target.type === 'milestone_pin' && target.milestone) return renderMilestonePinHtml(target.milestone);

    const idx = target.index ?? (tooltipItem ? tooltipItem.dataIndex : 0);
    const pts = chart._allPoints || [];
    const pt = pts[idx];
    if (!pt) return '';

    if (pt.is_historical) {
        return `
            <div style="font-weight: 700; font-size: 0.8125rem; color: #F8FAFC; margin-bottom: 6px;">Year ${pt.year} (Historical Actuals)</div>
            <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.75rem; padding: 4px 6px; background: rgba(255,255,255,0.06); border-radius: 4px; font-weight: 700; color: #FFFFFF;">
                <span>Historical Net Worth</span>
                <span style="font-variant-numeric: tabular-nums;">${fmtCurrency(pt.historical_val, 0)}</span>
            </div>
        `;
    }

    const yr = pt.year;
    const pAge = pt.age_primary || pt.age || (45 + (yr - 2026));
    const ms = (state.scenariosData?.milestones || []).find(m => m.year === yr);
    const scenarios = state.scenariosData?.scenarios || [];
    const curScen = scenarios.find(s => s.id === state.selectedScenarioId) || scenarios[0] || {};
    const curEvts = (state.scenariosData?.events_catalog || []).filter(e => (curScen.event_ids || []).includes(e.id));
    const eventsThisYear = curEvts.filter(e => {
        const s = e.year || 2026;
        const en = e.end_year || s;
        return yr >= s && yr <= en;
    });

    let eventsHtml = '';
    if (eventsThisYear.length > 0) {
        const rows = eventsThisYear.map(e => {
            const amtBadge = e.amount ? ` (${fmtShortCurrency(e.amount)})` : (e.annual_amount ? ` (${fmtShortCurrency(e.annual_amount)}/yr)` : '');
            return `<div style="display: flex; justify-content: space-between; color: #E2E8F0; padding: 1px 0;"><span>▸ ${escapeHtml(e.name)}</span><span style="color: #94A3B8;">${amtBadge}</span></div>`;
        }).join('');
        eventsHtml = `
            <div style="margin-top: 6px; padding-top: 6px; border-top: 1px solid rgba(255, 255, 255, 0.1); font-size: 0.71875rem;">
                <div style="font-weight: 600; color: #94A3B8; margin-bottom: 3px;">Timeline Events Active:</div>
                ${rows}
            </div>
        `;
    }

    return `
        <div style="font-weight: 700; font-size: 0.8125rem; color: #F8FAFC; margin-bottom: 6px; padding-bottom: 5px; border-bottom: 1px solid rgba(255,255,255,0.1); display: flex; justify-content: space-between; align-items: center;">
            <span>Year ${yr} (Age ${pAge})</span>
            ${ms ? `<span style="font-size: 0.65625rem; color: #38BDF8; font-weight: 500;">◆ ${escapeHtml(ms.label)}</span>` : ''}
        </div>
        ${renderColumnarComparisonTable(pt, scenarios)}
        ${eventsHtml}
        ${renderCashFlowHtml(yr, curScen)}
    `;
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
        tooltipEl.style.cssText = 'position: absolute; background: rgba(15, 23, 42, 0.96); backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px); border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 8px; padding: 10px 12px; color: #F8FAFC; pointer-events: none; z-index: 100; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.5); font-size: 0.78125rem; font-family: system-ui, -apple-system, sans-serif; min-width: 220px; maxWidth: 340px; transition: opacity 0.1s ease;';
        parent.appendChild(tooltipEl);
    }

    if (!tooltip || tooltip.opacity === 0 || !chart._hoverTarget) {
        tooltipEl.style.opacity = '0';
        tooltipEl.style.display = 'none';
        return;
    }

    const html = renderTooltipHtml(chart, chart._hoverTarget, tooltip.dataPoints?.[0]);
    if (!html) {
        tooltipEl.style.opacity = '0';
        tooltipEl.style.display = 'none';
        return;
    }

    tooltipEl.innerHTML = html;
    tooltipEl.style.display = 'block';

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
    tooltipEl.style.opacity = '1';
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
                const pAge = pt.age_primary || pt.age || (45 + (pt.year - 2026));
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
                    const amtStr = e.amount ? ` (${fmtShortCurrency(e.amount)})` : (e.annual_amount ? ` (${fmtShortCurrency(e.annual_amount)}/yr)` : '');
                    wrapText(`   ▸ ${e.name}${amtStr}`, 36).forEach(l => lines.push(l));
                });
            }

            const currentScenarioName = curScen.name || 'Selected Plan';
            const currentCashFlows = (state.scenariosData.scenario_cash_flows && state.selectedScenarioId && state.scenariosData.scenario_cash_flows[state.selectedScenarioId])
                || state.scenariosData.active_cash_flow_series
                || [];
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
