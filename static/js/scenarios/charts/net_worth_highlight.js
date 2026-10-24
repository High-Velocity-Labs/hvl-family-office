/**
 * static/js/scenarios/charts/net_worth_highlight.js
 * Hover highlight controller for scenario curves, pill/card/scorecard hover listeners,
 * and zero-lag in-place scenario switcher without Chart.js recreation.
 */

import {
    state,
    escapeHtml,
    ensureMonteCarloForScenario
} from '../state.js';
import { distToSegment } from './common.js';

let currentHighlightedScenId = null;

export function findNearestScenarioCurve(chart, mouseX, mouseY, maxDistance = 22) {
    if (!chart || !chart.data || !chart.data.datasets || !chart.chartArea) return null;
    const { left, right, top, bottom } = chart.chartArea;
    if (mouseX < left || mouseX > right || mouseY < top || mouseY > bottom) return null;

    let nearestScenId = null;
    let minDistance = maxDistance;

    const datasets = chart.data.datasets;
    for (let d = 0; d < datasets.length; d++) {
        const ds = datasets[d];
        if (ds.isMonteCarlo || ds.scenarioId === 'historical_actuals' || !ds.scenarioId) continue;
        const meta = chart.getDatasetMeta(d);
        if (!meta || !meta.data || meta.hidden) continue;

        const points = meta.data;
        for (let i = 0; i < points.length - 1; i++) {
            const p1 = points[i];
            const p2 = points[i + 1];
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
    if (!chart || !chart.data || !chart.data.datasets || currentHighlightedScenId === scenId) return;
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
    if (!chart || !chart.data || !chart.data.datasets || currentHighlightedScenId === null) return;
    currentHighlightedScenId = null;

    chart.data.datasets.forEach(ds => {
        if (ds.isMonteCarlo || ds.scenarioId === 'historical_actuals' || !ds.scenarioId) return;
        const isSelected = (ds.scenarioId === state.selectedScenarioId);
        ds.borderWidth = isSelected ? 3.5 : 1.75;
        if (ds._origBorderColor) {
            ds.borderColor = ds._origBorderColor;
        }
    });
    chart.update('none');
}

export function bindScenarioHoverListeners(chart) {
    if (typeof document === 'undefined' || !chart) return;

    // 1. Canvas curve hovering
    if (chart.canvas && !chart.canvas._hoverHighlightWired) {
        chart.canvas._hoverHighlightWired = true;
        chart.canvas.addEventListener('mousemove', (e) => {
            if (!chart || chart.destroyed || !chart.chartArea) return;
            const rect = chart.canvas.getBoundingClientRect();
            const mx = e.clientX - rect.left;
            const my = e.clientY - rect.top;

            // If hovering an event pin or milestone, leave curve highlight neutral
            if (chart._hoverTarget && chart._hoverTarget.type !== 'main_circle') {
                clearScenarioLineHighlight(chart);
                return;
            }

            const nearestScenId = findNearestScenarioCurve(chart, mx, my, 22);
            if (nearestScenId) {
                highlightScenarioLine(chart, nearestScenId);
            } else {
                clearScenarioLineHighlight(chart);
            }
        });

        chart.canvas.addEventListener('mouseleave', () => {
            clearScenarioLineHighlight(chart);
        });
    }

    // 2. Document delegation for scenario toggle pills, selector pills, and scorecard rows
    if (typeof window !== 'undefined' && !window._scenHighlightDelegationWired) {
        window._scenHighlightDelegationWired = true;

        document.addEventListener('mouseover', (e) => {
            const chartInstance = state.scenarioComparisonChart;
            if (!chartInstance || chartInstance.destroyed) return;

            const targetPill = e.target.closest(
                '.scenario-graph-toggle-pill, #scenario-selector-pills .pill-btn[data-scen-id], #tbody-scenarios-scorecard .scorecard-row[data-scen-id]'
            );
            if (!targetPill) return;

            const scenId = targetPill.dataset.scenId || targetPill.getAttribute('data-scen-id');
            if (scenId) {
                highlightScenarioLine(chartInstance, scenId);
            }
        });

        document.addEventListener('mouseout', (e) => {
            const chartInstance = state.scenarioComparisonChart;
            if (!chartInstance || chartInstance.destroyed) return;

            const targetPill = e.target.closest(
                '.scenario-graph-toggle-pill, #scenario-selector-pills .pill-btn[data-scen-id], #tbody-scenarios-scorecard .scorecard-row[data-scen-id]'
            );
            if (!targetPill) return;

            if (!targetPill.contains(e.relatedTarget)) {
                clearScenarioLineHighlight(chartInstance);
            }
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
        if (hasEventStart) {
            return { radius: 7.5, hoverRadius: 11, bg: '#F59E0B', border: '#FFFFFF', width: 2.5 };
        }
        if (hasMilestone) {
            return { radius: 6.5, hoverRadius: 10, bg: '#FFFFFF', border: color, width: 2.5 };
        }
        if (hasEventRunning) {
            return { radius: 4.5, hoverRadius: 7.5, bg: color, border: '#FFFFFF', width: 1.5 };
        }
        return { radius: 2.5, hoverRadius: 6, bg: color, border: color, width: 1 };
    }
    return { radius: 1, hoverRadius: 4, bg: color, border: color, width: 1 };
}

export function updateChartScenarioStyles(chart, selectedScenId) {
    if (!chart || !chart.data || !chart.data.datasets) return;
    const scenarios = (state.scenariosData && state.scenariosData.scenarios) || [];
    const milestones = (state.scenariosData && state.scenariosData.milestones) || [];
    const allEvents = (state.scenariosData && state.scenariosData.events_catalog) || [];
    const allPoints = chart._allPoints || [];

    chart.data.datasets.forEach(ds => {
        if (ds.isMonteCarlo || ds.scenarioId === 'historical_actuals' || !ds.scenarioId) return;
        const scenIdx = scenarios.findIndex(s => s.id === ds.scenarioId);
        const scen = scenarios[scenIdx];
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
    if (!state.showMonteCarloCorridor || !chart || !chart.data || !chart.data.datasets) return;
    const allPoints = chart._allPoints || [];
    const scenarios = (state.scenariosData && state.scenariosData.scenarios) || [];
    const scenObj = scenarios.find(s => s.id === selectedScenId) || {};
    const scenName = scenObj.name || 'Selected Plan';

    const p90Ds = chart.data.datasets.find(d => d.isMonteCarlo && d.scenarioId?.includes('p90'));
    const p10Ds = chart.data.datasets.find(d => d.isMonteCarlo && d.scenarioId?.includes('p10'));
    if (!p90Ds || !p10Ds) return;

    p90Ds.scenarioId = `mc_${selectedScenId}_p90`;
    p10Ds.scenarioId = `mc_${selectedScenId}_p10`;
    p90Ds.label = `Monte Carlo 10th–90th Range (${scenName}) - Top (90th)`;
    p10Ds.label = `Monte Carlo 10th–90th Range (${scenName})`;

    const cachedMc = state.cachedMonteCarloByScen[selectedScenId];
    if (cachedMc && cachedMc.percentiles_timeline) {
        const mcTimeline = cachedMc.percentiles_timeline;
        p90Ds.data = allPoints.map(p => {
            if (p.is_historical) return null;
            const pt = mcTimeline.find(m => m.year === p.year);
            return pt ? pt.p90 : null;
        });
        p10Ds.data = allPoints.map(p => {
            if (p.is_historical) return null;
            const pt = mcTimeline.find(m => m.year === p.year);
            return pt ? pt.p10 : null;
        });
    } else {
        ensureMonteCarloForScenario(selectedScenId).then(mcData => {
            if (!mcData || !mcData.percentiles_timeline) return;
            if (state.selectedScenarioId !== selectedScenId) return;
            const currentChart = state.scenarioComparisonChart;
            if (!currentChart || currentChart.destroyed) return;
            const liveP90 = currentChart.data.datasets.find(d => d.isMonteCarlo && d.scenarioId === `mc_${selectedScenId}_p90`);
            const liveP10 = currentChart.data.datasets.find(d => d.isMonteCarlo && d.scenarioId === `mc_${selectedScenId}_p10`);
            if (liveP90 && liveP10) {
                const liveTimeline = mcData.percentiles_timeline;
                liveP90.data = allPoints.map(p => {
                    if (p.is_historical) return null;
                    const pt = liveTimeline.find(m => m.year === p.year);
                    return pt ? pt.p90 : null;
                });
                liveP10.data = allPoints.map(p => {
                    if (p.is_historical) return null;
                    const pt = liveTimeline.find(m => m.year === p.year);
                    return pt ? pt.p10 : null;
                });
                currentChart.update('none');
            }
        }).catch(err => {
            console.warn('Async Monte Carlo fetch caught:', err);
        });
    }
}

function updateDomPillsAndRows(scenId) {
    if (typeof document === 'undefined') return;

    // 1. Graph toggle pills
    const togglesContainer = document.getElementById('chart-scenarios-toggles');
    if (togglesContainer && state.scenariosData) {
        const pills = togglesContainer.querySelectorAll('.scenario-graph-toggle-pill');
        const scenarios = state.scenariosData.scenarios || [];
        const theme = typeof window !== 'undefined' ? window.CHART_THEME : null;
        pills.forEach((badge, idx) => {
            const scen = scenarios[idx];
            if (!scen) return;
            const isSelected = scen.id === scenId;
            const isActive = scen.id === state.scenariosData.active_scenario_id;
            const scenColor = theme ? theme.normalizeScenarioColor(scen.color, idx) : (scen.color || '#1D4ED8');
            badge.style.border = `1px solid ${isSelected ? scenColor : scenColor + '40'}`;
            badge.style.background = isSelected ? scenColor + '25' : scenColor + '10';
            badge.innerHTML = `<span style="width: 8px; height: 8px; border-radius: 50%; background: ${scenColor};"></span> ${escapeHtml(scen.name)}${isSelected ? ' ★' : ''}${isActive && !isSelected ? ' (Active)' : ''}`;
        });
    }

    // 2. Scenario selector pills
    const pillsContainer = document.getElementById('scenario-selector-pills');
    if (pillsContainer) {
        pillsContainer.querySelectorAll('.pill-btn[data-scen-id]').forEach(btn => {
            btn.classList.toggle('active', btn.getAttribute('data-scen-id') === scenId);
        });
    }

    // 3. Scorecard table rows
    const scorecardTbody = document.getElementById('tbody-scenarios-scorecard');
    if (scorecardTbody) {
        scorecardTbody.querySelectorAll('.scorecard-row').forEach(row => {
            const rId = row.getAttribute('data-scen-id') || row.getAttribute('data-id');
            const isCurrent = rId === scenId;
            row.classList.toggle('active', isCurrent);
            if (isCurrent) {
                row.style.background = 'rgba(59, 130, 246, 0.08)';
            } else {
                row.style.background = row.classList.contains('is-child') ? 'rgba(2, 101, 232, 0.03)' : '';
            }
        });
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

    // 2. Instant in-place Chart update without recreation
    const chart = state.scenarioComparisonChart;
    if (chart && chart.data && chart.data.datasets && chart.config.type === 'line') {
        updateChartScenarioStyles(chart, scenId);
        updateMonteCarloCorridorInPlace(chart, scenId);
        chart.update('none');
    }

    // 3. Background persistence
    const isDemo = (typeof window !== 'undefined' && (
        (typeof window.isDemoSession === 'function' && window.isDemoSession()) ||
        window.__IS_DEMO__ ||
        new URLSearchParams(window.location?.search || '').get('demo') === '1'
    ));
    if (!isDemo) {
        try {
            fetch('/api/scenarios/active', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ scenario_id: scenId })
            }).catch(err => console.error('Failed to set active scenario:', err));
        } catch (err) {
            console.error('Failed to activate scenario in background:', err);
        }
    }

    // 4. Background SSR card updates without locking or redrawing the chart
    if (typeof window !== 'undefined' && typeof window.morphScenariosSection === 'function') {
        window.morphScenariosSection({ scenario_id: scenId, background: true }).catch(err => {
            console.warn('Background scenario card morph caught:', err);
        });
    }
}
