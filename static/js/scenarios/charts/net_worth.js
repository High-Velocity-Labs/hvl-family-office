/**
 * Lens 1: Multi-Scenario Net Worth Trajectory & Monte Carlo Corridor
 */
import {
    state,
    fmtShortCurrency,
    getMonteCarloForScenario,
    ensureMonteCarloForScenario
} from '../state.js';
import { renderGraphScenarioToggles, updateChartWindowContinuous } from './common.js';
import { getTimelineRange, inspectTimelineYear, updateScrubberNeedle } from '../scrubber.js';
import { eventPinIconsPlugin } from './net_worth_helpers.js';
import { applyChartStageHeight } from './cash_flow_sankey.js';
import {
    buildAllPoints,
    buildNetWorthDatasets,
    computeYearYBounds,
    buildNetWorthTooltipCallbacks
} from './net_worth_config.js';
import { customNetWorthTooltip } from './net_worth_tooltip.js';
import { bindScenarioHoverListeners } from './net_worth_highlight.js';

const openEditEventModal = (...args) => (
    typeof window !== 'undefined' && window.openEditEventModal
        ? window.openEditEventModal(...args)
        : null
);

function setupNetWorthToggles(togglesContainer, ctx, captionEl, scenarios) {
    if (!togglesContainer) return;
    togglesContainer.innerHTML = '';
    renderGraphScenarioToggles(togglesContainer);

    togglesContainer.querySelectorAll('.scenario-graph-toggle-pill').forEach((pill, idx) => {
        if (scenarios[idx]) pill.dataset.scenId = scenarios[idx].id;
    });

    if (scenarios.length > 0) {
        const btnMcToggle = document.createElement('button');
        btnMcToggle.type = 'button';
        btnMcToggle.className = `btn btn-sm ${state.showMonteCarloCorridor ? 'btn-primary' : 'btn-secondary'}`;
        btnMcToggle.style.cssText = 'font-size: 0.71875rem; padding: 2px 9px; margin-left: 10px; font-weight: 600; border-radius: 6px; cursor: pointer;';
        btnMcToggle.innerHTML = `Monte Carlo Band: ${state.showMonteCarloCorridor ? 'ON' : 'OFF'}`;
        btnMcToggle.title = 'Toggle 10th to 90th percentile stochastic Monte Carlo uncertainty corridor';
        btnMcToggle.onclick = () => {
            state.showMonteCarloCorridor = !state.showMonteCarloCorridor;
            try { localStorage.setItem('scen_show_mc_corridor', state.showMonteCarloCorridor ? 'true' : 'false'); } catch (e) {}
            renderNetWorthLens(ctx, togglesContainer, captionEl, false);
        };
        togglesContainer.appendChild(btnMcToggle);
    }
}

function handleChartClick(event, elements, chart) {
    if (window._suppressChartClick) return;
    const target = chart._hoverTarget;
    if (target?.type === 'event_pin' && target.event) {
        openEditEventModal(target.event.id);
        return;
    }
    if (target?.type === 'milestone_pin') {
        const yr = target.year;
        state.inspectedYear = yr;
        const scrubber = document.getElementById('timeline-scrubber');
        if (scrubber) scrubber.value = yr;
        updateScrubberNeedle(yr);
        inspectTimelineYear(yr);
        return;
    }
    if (target?.type === 'main_circle' || (elements && elements.length > 0)) {
        const idx = target?.index ?? elements[0].index;
        const pts = chart._allPoints || [];
        const pt = pts[idx];
        if (pt) {
            const yr = pt.year;
            state.inspectedYear = yr;
            const scrubber = document.getElementById('timeline-scrubber');
            if (scrubber) scrubber.value = yr;
            updateScrubberNeedle(yr);
            inspectTimelineYear(yr);
        }
    }
}

export function renderNetWorthLens(ctx, togglesContainer, captionEl, smooth = false) {
    applyChartStageHeight(false);
    if (captionEl) {
        captionEl.textContent = 'Multi-Scenario Net Worth Trajectory: Continuous lifetime comparison bridging historical actuals into future milestones. Shaded corridor displays the 10th to 90th percentile stochastic Monte Carlo uncertainty range.';
    }

    if (!state.scenariosData) return;

    const curves = state.scenariosData.comparison_curves || [];
    const historical = state.scenariosData.historical_ribbon || [];
    const scenarios = state.scenariosData.scenarios || [];
    const { minYear, maxYear } = getTimelineRange();

    const allPoints = buildAllPoints(historical, curves);
    const labels = allPoints.map(p => p.year);

    const currentScenObj = (state.scenariosData.scenarios || []).find(s => s.id === state.selectedScenarioId) || {};
    const effectiveScenId = state.selectedScenarioId || state.scenariosData.active_scenario_id || 'scen_baseline';

    const mcSource = getMonteCarloForScenario(effectiveScenId);
    if (state.showMonteCarloCorridor && !mcSource) {
        ensureMonteCarloForScenario(effectiveScenId);
    }
    const mcTimeline = (mcSource && mcSource.percentiles_timeline) || [];

    const datasets = buildNetWorthDatasets(allPoints, scenarios, currentScenObj, effectiveScenId, mcTimeline, state.showMonteCarloCorridor);
    setupNetWorthToggles(togglesContainer, ctx, captionEl, scenarios);
    const yearYBounds = computeYearYBounds(allPoints, datasets);

    // If chart already exists and is line chart, update datasets and bounds in-place
    if (state.scenarioComparisonChart && state.scenarioComparisonChart.config.type === 'line') {
        state.scenarioComparisonChart.options.interaction.mode = 'nearLineOrEvent';
        if (state.scenarioComparisonChart.options.plugins && state.scenarioComparisonChart.options.plugins.tooltip) {
            state.scenarioComparisonChart.options.plugins.tooltip.enabled = false;
            state.scenarioComparisonChart.options.plugins.tooltip.external = customNetWorthTooltip;
            state.scenarioComparisonChart.options.plugins.tooltip.position = 'eventPinPositioner';
        }
        state.scenarioComparisonChart._allPoints = allPoints;
        state.scenarioComparisonChart._yearYBounds = yearYBounds;
        state.scenarioComparisonChart._minDataYear = allPoints.length ? allPoints[0].year : 2018;
        state.scenarioComparisonChart._maxDataYear = allPoints.length ? allPoints[allPoints.length - 1].year : 2060;
        state.scenarioComparisonChart.data.labels = labels;
        state.scenarioComparisonChart.data.datasets = datasets;
        updateChartWindowContinuous(state.scenarioComparisonChart, minYear, maxYear, smooth);
        bindScenarioHoverListeners(state.scenarioComparisonChart);
        state.scenarioComparisonChart.update(smooth ? 'none' : undefined);
        return;
    }

    state.scenarioComparisonChart = new Chart(ctx, {
        type: 'line',
        data: { labels, datasets },
        plugins: [eventPinIconsPlugin],
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'nearLineOrEvent', intersect: false },
            onClick: handleChartClick,
            plugins: {
                legend: { display: false },
                tooltip: {
                    enabled: false,
                    external: customNetWorthTooltip,
                    position: 'eventPinPositioner',
                    padding: 10,
                    cornerRadius: 8,
                    bodySpacing: 4,
                    titleSpacing: 4,
                    displayColors: (tooltipItem) => {
                        const chart = tooltipItem?.chart || state.scenarioComparisonChart;
                        return chart?._hoverTarget?.type === 'main_circle';
                    },
                    callbacks: buildNetWorthTooltipCallbacks()
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: '#94A3B8', maxRotation: 45, maxTicksLimit: 14 }
                },
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: {
                        color: '#94A3B8',
                        callback: (v) => fmtShortCurrency(v)
                    }
                }
            }
        }
    });

    state.scenarioComparisonChart._allPoints = allPoints;
    state.scenarioComparisonChart._yearYBounds = yearYBounds;
    state.scenarioComparisonChart._minDataYear = allPoints.length ? allPoints[0].year : 2018;
    state.scenarioComparisonChart._maxDataYear = allPoints.length ? allPoints[allPoints.length - 1].year : 2060;
    updateChartWindowContinuous(state.scenarioComparisonChart, minYear, maxYear, false);
    bindScenarioHoverListeners(state.scenarioComparisonChart);
    state.scenarioComparisonChart.update('none');
}
