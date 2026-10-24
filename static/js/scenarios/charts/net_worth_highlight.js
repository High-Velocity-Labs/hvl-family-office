/**
 * static/js/scenarios/charts/net_worth_highlight.js
 * Hover highlight controller for scenario curves, pill/card/scorecard hover listeners,
 * and zero-lag in-place scenario switcher without Chart.js recreation.
 */

import {
    state,
    escapeHtml,
    fmtShortCurrency,
    ensureMonteCarloForScenario
} from '../state.js';
import { distToSegment } from './common.js';
import { renderCashFlowWaterfallLens } from './cash_flow.js';
import { renderLongevityStackedAreaLens } from './longevity.js';
import { renderMonteCarloLens } from './monte_carlo.js';

let currentHighlightedScenId = null;

export function findNearestScenarioCurve(chart, mouseX, mouseY, maxDistance = 22) {
    if (!chart?.data?.datasets || !chart.chartArea) return null;
    const { left, right, top, bottom } = chart.chartArea;
    if (mouseX < left || mouseX > right || mouseY < top || mouseY > bottom) return null;

    let nearestScenId = null;
    let minDistance = maxDistance;

    for (let d = 0; d < chart.data.datasets.length; d++) {
        const ds = chart.data.datasets[d];
        if (ds.isMonteCarlo || ds.scenarioId === 'historical_actuals' || !ds.scenarioId) continue;
        const meta = chart.getDatasetMeta(d);
        if (!meta?.data || meta.hidden) continue;

        const pts = meta.data;
        for (let i = 0; i < pts.length - 1; i++) {
            const p1 = pts[i];
            const p2 = pts[i + 1];
            if (!p1 || !p2 || p1.skip || p2.skip || isNaN(p1.x) || isNaN(p1.y) || isNaN(p2.x) || isNaN(p2.y)) continue;
            const dist = distToSegment(mouseX, mouseY, p1.x, p1.y, p2.x, p2.y);
            if (dist < minDistance) {
                minDistance = dist;
                nearestScenId = ds.scenarioId;
            }
        }
    }
    return nearestScenId;
}

export function highlightScenarioLine(chart, scenId) {
    if (!chart?.data?.datasets || currentHighlightedScenId === scenId) return;
    currentHighlightedScenId = scenId;
    const theme = typeof window !== 'undefined' ? window.CHART_THEME : null;

    chart.data.datasets.forEach(ds => {
        if (ds.isMonteCarlo || ds.scenarioId === 'historical_actuals' || !ds.scenarioId) return;
        if (!ds._origBorderColor) ds._origBorderColor = ds.borderColor;

        const isSelected = (ds.scenarioId === state.selectedScenarioId);
        if (ds.scenarioId === scenId) {
            ds.borderWidth = isSelected ? 4.5 : 3.5;
            ds.borderColor = ds._origBorderColor;
        } else {
            const dimmed = theme && typeof theme.alpha === 'function'
                ? theme.alpha(ds._origBorderColor, 0.25)
                : (ds._origBorderColor + '40');
            ds.borderColor = dimmed;
            ds.borderWidth = isSelected ? 2.5 : 1.25;
        }
    });
    chart.update('none');
}

export function clearScenarioLineHighlight(chart) {
    if (!chart?.data?.datasets || currentHighlightedScenId === null) return;
    currentHighlightedScenId = null;

    chart.data.datasets.forEach(ds => {
        if (ds.isMonteCarlo || ds.scenarioId === 'historical_actuals' || !ds.scenarioId) return;
        const isSelected = (ds.scenarioId === state.selectedScenarioId);
        ds.borderWidth = isSelected ? 3.5 : 1.75;
        if (ds._origBorderColor) ds.borderColor = ds._origBorderColor;
    });
    chart.update('none');
}

export function bindScenarioHoverListeners(chart) {
    if (typeof document === 'undefined' || !chart) return;

    if (chart.canvas && !chart.canvas._hoverHighlightWired) {
        chart.canvas._hoverHighlightWired = true;
        chart.canvas.addEventListener('mousemove', (e) => {
            if (!chart || chart.destroyed || !chart.chartArea) return;
            const rect = chart.canvas.getBoundingClientRect();
            if (chart._hoverTarget && chart._hoverTarget.type !== 'main_circle') {
                clearScenarioLineHighlight(chart);
                return;
            }
            const nearest = findNearestScenarioCurve(chart, e.clientX - rect.left, e.clientY - rect.top, 22);
            nearest
                ? highlightScenarioLine(chart, nearest)
                : clearScenarioLineHighlight(chart);
        });

        chart.canvas.addEventListener('mouseleave', () => clearScenarioLineHighlight(chart));
    }

    if (typeof window !== 'undefined' && !window._scenHighlightDelegationWired) {
        window._scenHighlightDelegationWired = true;
        const HOVER_SEL = '.scenario-graph-toggle-pill, #scenario-selector-pills .pill-btn[data-scen-id], #tbody-scenarios-scorecard .scorecard-row[data-scen-id]';

        document.addEventListener('mouseover', (e) => {
            const chartInstance = state.scenarioComparisonChart;
            if (!chartInstance || chartInstance.destroyed) return;
            const pill = e.target.closest(HOVER_SEL);
            const scenId = pill?.dataset?.scenId || pill?.getAttribute('data-scen-id');
            if (scenId) highlightScenarioLine(chartInstance, scenId);
        });

        document.addEventListener('mouseout', (e) => {
            const chartInstance = state.scenarioComparisonChart;
            if (!chartInstance || chartInstance.destroyed) return;
            const pill = e.target.closest(HOVER_SEL);
            if (pill && !pill.contains(e.relatedTarget)) clearScenarioLineHighlight(chartInstance);
        });
    }
}

function resolvePointStyle(p, isSelected, color, milestones, currentScenEvents) {
    if (p.is_historical) {
        return { radius: 0, hoverRadius: 0, bg: color, border: color, width: 0 };
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
        if (hasEventStart) return { radius: 7.5, hoverRadius: 11, bg: '#F59E0B', border: '#FFFFFF', width: 2.5 };
        if (hasMilestone) return { radius: 6.5, hoverRadius: 10, bg: '#FFFFFF', border: color, width: 2.5 };
        if (hasEventRunning) return { radius: 4.5, hoverRadius: 7.5, bg: color, border: '#FFFFFF', width: 1.5 };
        return { radius: 2.5, hoverRadius: 6, bg: color, border: color, width: 1 };
    }
    return { radius: 1, hoverRadius: 4, bg: color, border: color, width: 1 };
}

export function updateChartScenarioStyles(chart, selectedScenId) {
    if (!chart?.data?.datasets) return;
    const scenarios = state.scenariosData?.scenarios || [];
    const milestones = state.scenariosData?.milestones || [];
    const allEvents = state.scenariosData?.events_catalog || [];
    const allPoints = chart._allPoints || [];

    chart.data.datasets.forEach(ds => {
        if (ds.isMonteCarlo || ds.scenarioId === 'historical_actuals' || !ds.scenarioId) return;
        const scen = scenarios.find(s => s.id === ds.scenarioId);
        if (!scen) return;

        const isSelected = (ds.scenarioId === selectedScenId);
        const color = ds._origBorderColor || ds.borderColor;
        ds._origBorderColor = color;
        ds.borderWidth = isSelected ? 3.5 : 1.75;

        const currentScenEvents = allEvents.filter(e => (scen.event_ids || []).includes(e.id));
        const styles = allPoints.map(p => resolvePointStyle(p, isSelected, color, milestones, currentScenEvents));

        ds.pointRadius = styles.map(s => s.radius);
        ds.pointHoverRadius = styles.map(s => s.hoverRadius);
        ds.pointBackgroundColor = styles.map(s => s.bg);
        ds.pointBorderColor = styles.map(s => s.border);
        ds.pointBorderWidth = styles.map(s => s.width);
    });
}

export function updateMonteCarloCorridorInPlace(chart, selectedScenId) {
    if (!state.showMonteCarloCorridor || !chart?.data?.datasets) return;
    const allPoints = chart._allPoints || [];
    const scenarios = state.scenariosData?.scenarios || [];
    const scenObj = scenarios.find(s => s.id === selectedScenId) || {};
    const scenName = scenObj.name || 'Selected Plan';

    const p90Ds = chart.data.datasets.find(d => d.isMonteCarlo && d.scenarioId?.includes('p90'));
    const p10Ds = chart.data.datasets.find(d => d.isMonteCarlo && d.scenarioId?.includes('p10'));
    if (!p90Ds || !p10Ds) return;

    p90Ds.scenarioId = `mc_${selectedScenId}_p90`;
    p10Ds.scenarioId = `mc_${selectedScenId}_p10`;
    p90Ds.label = `Monte Carlo 10th–90th Range (${scenName}) - Top (90th)`;
    p10Ds.label = `Monte Carlo 10th–90th Range (${scenName})`;

    const applyTimeline = (timeline) => {
        p90Ds.data = allPoints.map(p => p.is_historical ? null : (timeline.find(m => m.year === p.year)?.p90 ?? null));
        p10Ds.data = allPoints.map(p => p.is_historical ? null : (timeline.find(m => m.year === p.year)?.p10 ?? null));
    };

    const cachedMc = state.cachedMonteCarloByScen[selectedScenId];
    if (cachedMc?.percentiles_timeline) {
        applyTimeline(cachedMc.percentiles_timeline);
    } else {
        ensureMonteCarloForScenario(selectedScenId).then(mcData => {
            if (!mcData?.percentiles_timeline || state.selectedScenarioId !== selectedScenId) return;
            const curChart = state.scenarioComparisonChart;
            if (!curChart || curChart.destroyed) return;
            applyTimeline(mcData.percentiles_timeline);
            curChart.update('none');
        }).catch(err => {
            console.warn('Async Monte Carlo fetch caught:', err);
        });
    }
}

function updateDomPillsAndRows(scenId) {
    if (typeof document === 'undefined') return;

    // 1. Graph toggle pills
    const toggles = document.getElementById('chart-scenarios-toggles');
    if (toggles && state.scenariosData) {
        const scenarios = state.scenariosData.scenarios || [];
        const theme = typeof window !== 'undefined' ? window.CHART_THEME : null;
        toggles.querySelectorAll('.scenario-graph-toggle-pill').forEach((badge, idx) => {
            const scen = scenarios[idx];
            if (!scen) return;
            const isSelected = scen.id === scenId;
            const isActive = scen.id === state.scenariosData.active_scenario_id;
            const color = theme ? theme.normalizeScenarioColor(scen.color, idx) : (scen.color || '#1D4ED8');
            badge.style.border = `1px solid ${isSelected ? color : color + '40'}`;
            badge.style.background = isSelected ? color + '25' : color + '10';
            badge.innerHTML = `<span style="width: 8px; height: 8px; border-radius: 50%; background: ${color};"></span> ${escapeHtml(scen.name)}${isSelected ? ' ★' : ''}${isActive && !isSelected ? ' (Active)' : ''}`;
        });
    }

    // 2. Scenario selector pills
    document.querySelectorAll('#scenario-selector-pills .pill-btn[data-scen-id]').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-scen-id') === scenId);
    });

    // 3. Scorecard table rows
    document.querySelectorAll('#tbody-scenarios-scorecard .scorecard-row').forEach(row => {
        const rId = row.getAttribute('data-scen-id') || row.getAttribute('data-id');
        const isCurrent = rId === scenId;
        row.classList.toggle('active', isCurrent);
        row.style.background = isCurrent
            ? 'rgba(59, 130, 246, 0.08)'
            : (row.classList.contains('is-child') ? 'rgba(2, 101, 232, 0.03)' : '');
    });
}

export function updateCurrentPlanCardInPlace(scenId) {
    if (typeof document === 'undefined') return;
    const scenarios = state.scenariosData?.scenarios || [];
    const scorecard = state.scenariosData?.scorecard || [];
    const scen = scenarios.find(s => s.id === scenId)
        || scorecard.find(s => s.id === scenId)
        || {};
    const card = scorecard.find(s => s.id === scenId) || scen;
    const theme = typeof window !== 'undefined' ? window.CHART_THEME : null;
    const scenIdx = scenarios.findIndex(s => s.id === scenId);
    const scenColor = theme
        ? theme.normalizeScenarioColor(scen.color || card.color, scenIdx)
        : (scen.color || card.color || '#3B82F6');
    const isActive = (scenId === state.scenariosData?.active_scenario_id || scen.is_active);

    const setTxt = (id, txt) => {
        const el = document.getElementById(id);
        if (el) el.textContent = txt;
    };
    const setDisplay = (id, show, disp = 'inline-block') => {
        const el = document.getElementById(id);
        if (el) el.style.display = show ? disp : 'none';
    };

    const dotEl = document.getElementById('current-plan-color-dot');
    if (dotEl) dotEl.style.background = scenColor;
    setTxt('label-current-plan-name', scen.name || 'Selected Plan');
    setDisplay('badge-current-plan-active', isActive);

    const btnMakeActive = document.getElementById('btn-make-active-scenario');
    if (btnMakeActive) {
        btnMakeActive.style.display = isActive ? 'none' : 'inline-flex';
        btnMakeActive.setAttribute('data-scen-id', scenId);
    }

    const parentId = scen.parent_id || card.parent_id;
    setDisplay('badge-current-plan-parent', Boolean(parentId), 'inline-flex');
    if (parentId) {
        document.getElementById('badge-current-plan-parent')?.setAttribute('data-parent-id', parentId);
        const pScen = scenarios.find(s => s.id === parentId);
        setTxt('txt-current-plan-parent-name', scen.parent_name || pScen?.name || 'Parent Plan');
    }

    const row = document.querySelector(`#tbody-scenarios-scorecard .scorecard-row[data-scen-id="${scenId}"]`);
    const tds = row?.querySelectorAll('td');

    const syncBadgeCell = (cell, valId, subId) => {
        const valEl = document.getElementById(valId);
        const b = cell?.querySelector('.badge');
        if (valEl) {
            const cls = b?.className.replace('badge', '').trim() || 'badge-blue';
            valEl.innerHTML = b
                ? `<span class="badge ${cls}" style="font-size: 0.75rem;">${escapeHtml(b.textContent)}</span>`
                : '--';
        }
        if (subId) setTxt(subId, cell?.querySelector('.text-muted')?.textContent || '--');
    };

    syncBadgeCell(tds?.[1], 'val-current-plan-primary-ret', 'sub-current-plan-primary-ret');
    syncBadgeCell(tds?.[2], 'val-current-plan-spouse-ret', 'sub-current-plan-spouse-ret');

    [65, 85, 95].forEach((age, idx) => {
        const fallback = fmtShortCurrency(card[`net_worth_${age}`] ?? scen[`net_worth_${age}`]);
        setTxt(`val-current-plan-nw${age}`, tds?.[3 + idx]?.textContent?.trim() || fallback);
    });

    const solBadge = tds?.[6]?.querySelector('.badge');
    const elSolv = document.getElementById('val-current-plan-solvency');
    if (elSolv) {
        const mc = card.monte_carlo_solvency;
        let cls = 'badge-green';
        let txt = 'Solvent @ 100';
        if (solBadge) {
            cls = solBadge.className.replace('badge', '').trim() || 'badge-green';
            txt = solBadge.textContent;
        } else if (mc != null) {
            cls = mc >= 90 ? 'badge-green' : (mc >= 75 ? 'badge-orange' : 'badge-red');
            txt = `${Math.round(mc)}% Solvency (MC)`;
        } else if (card.is_depleted) {
            cls = 'badge-red';
            txt = 'Depleted';
        }
        elSolv.innerHTML = `<span class="badge ${cls}" style="font-size: 0.75rem; cursor: pointer;" onclick="switchToLens('montecarlo', true);">${escapeHtml(txt)}</span>`;
    }

    const defaultLiving = state.scenariosData?.annual_living_spend || 0;
    const spendNum = card.annual_living_spend ?? scen.annual_living_spend ?? defaultLiving;
    const evIds = card.events_included || card.events_details || scen.event_ids || [];
    setTxt('val-current-plan-spend', `${evIds.length} Events • ${fmtShortCurrency(spendNum)}/yr`);
}

function updateCompanionChartsInPlace() {
    if (typeof document === 'undefined') return;
    const upd = (id, tId, cId, fn) => {
        const el = document.getElementById(id);
        if (el && fn) fn(el.getContext('2d'), document.getElementById(tId), document.getElementById(cId), true);
    };
    upd('chart-scen_chart_cashflow', 'chart-cashflow-toggles', 'chart-cashflow-caption', renderCashFlowWaterfallLens);
    upd('chart-scen_chart_longevity', 'chart-longevity-toggles', 'chart-longevity-caption', renderLongevityStackedAreaLens);
    upd('chart-scen_chart_montecarlo', 'chart-montecarlo-toggles', 'chart-montecarlo-caption', renderMonteCarloLens);

    if (!document.getElementById('scenarios-widgets-grid')) {
        const singleLensFn = {
            cashflow: renderCashFlowWaterfallLens,
            longevity: renderLongevityStackedAreaLens,
            montecarlo: renderMonteCarloLens
        }[state.currentLens];
        upd('chart-scenarios-comparison', 'chart-curve-toggles', 'chart-lens-caption', singleLensFn);
    }
}

export async function switchScenarioInPlace(scenId) {
    if (!scenId) return;
    state.selectedScenarioId = scenId;
    if (typeof localStorage !== 'undefined') {
        try { localStorage.setItem('scen_selected_id', scenId); } catch (e) {}
    }

    // 1. Instant DOM active state sync
    updateDomPillsAndRows(scenId);
    updateCurrentPlanCardInPlace(scenId);

    // 2. Instant in-place Chart update without recreation
    const chart = state.scenarioComparisonChart;
    if (chart?.data?.datasets && chart.config.type === 'line' && !chart._longevitySeries && !chart._mcTimeline) {
        updateChartScenarioStyles(chart, scenId);
        updateMonteCarloCorridorInPlace(chart, scenId);
        chart.update('none');
    }

    // 3. In-place companion chart updates without touching net worth chart
    updateCompanionChartsInPlace();
}
