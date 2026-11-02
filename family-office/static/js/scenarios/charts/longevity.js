/**
 * Lens 3: Longevity Portfolio Survival (SSA Actuarial 100% Stacked Area)
 */
import {
    state, fmtCurrency, fmtShortCurrency, getMonteCarloForScenario, ensureMonteCarloForScenario, getGraphScenarioId,
    setGraphScenarioId, getPlanStartYear
} from '../state.js';
import { renderGraphScenarioToggles, applySmoothXScale, setChartLoader } from './common.js';
import { loadChartToggles } from './chart_chrome.js';
import { getTimelineRange, inspectTimelineYear, updateScrubberNeedle } from '../scrubber.js';

export function renderLongevityStackedAreaLens(ctx, togglesContainer, captionEl, smooth = false) {
    if (!state.scenariosData) return;

    const pName = (state.scenariosData && state.scenariosData.primary_name) || 'Primary';
    const sName = (state.scenariosData && state.scenariosData.spouse_name) || 'Spouse';

    if (captionEl) {
        captionEl.textContent = `Stochastic Longevity & Solvency (SSA Actuarial, 100% Stacked Area): Bottom axis shows calendar Year alongside ages for ${pName} and ${sName}. Powered by 1,000 Monte Carlo market trials combined with SSA joint mortality tables. Tracks probabilities of growing wealth (green), preserving capital (yellow), exhausting funds in bear markets (red), or joint mortality (grey).`;
    }

    const effectiveScenId = getGraphScenarioId('longevity');
    const mcSource = getMonteCarloForScenario(effectiveScenId);
    if (!mcSource) {
        ensureMonteCarloForScenario(effectiveScenId);
    }
    // Monte Carlo's breakdown, else the plan's own (on the page for the selected plan); nothing while MC loads.
    const series = (mcSource && mcSource.longevity_breakdown)
        || state.scenariosData.scenario_longevity_breakdowns?.[effectiveScenId]
        || [];
    setChartLoader('longevity-chart-loading', !mcSource && series.length === 0);
    const { minYear, maxYear } = getTimelineRange();

    // Bottom axis is calendar Year
    const labels = series.map(s => s.year);

    const growing = series.map(s => s.prob_growing);
    const preserved = series.map(s => s.prob_preserved);
    const broke = series.map(s => s.prob_broke);
    const deceased = series.map(s => s.prob_deceased);

    if (togglesContainer) {
        togglesContainer.replaceChildren();
        renderGraphScenarioToggles(togglesContainer, {
            graphKey: 'longevity',
            selectedScenarioId: effectiveScenId,
            onSelect: (scenId) => {
                setGraphScenarioId('longevity', scenId);
                renderLongevityStackedAreaLens(ctx, togglesContainer, captionEl, true);
            }
        });

        loadChartToggles(togglesContainer, { lens: 'longevity' });
    }

    const canvas = ctx?.canvas;
    const isSharedCanvas = canvas?.id === 'chart-scenarios-comparison';
    let lgChart = isSharedCanvas ? state.scenarioComparisonChart : state.longevityChart;
    if (lgChart && (lgChart.canvas !== canvas || !document.body.contains(lgChart.canvas) || lgChart.config.type !== 'line' || !lgChart._longevitySeries)) {
        lgChart.destroy();
        lgChart = null;
        if (isSharedCanvas) state.scenarioComparisonChart = null;
        else state.longevityChart = null;
    }

    if (lgChart && lgChart.config.type === 'line' && lgChart.data.datasets?.length === 4) {
        lgChart.data.labels = labels;
        lgChart._longevitySeries = series;
        lgChart._minDataYear = series.length ? series[0].year : getPlanStartYear();
        lgChart._maxDataYear = series.length ? series[series.length - 1].year : 2060;
        lgChart.data.datasets[0].data = growing;
        lgChart.data.datasets[1].data = preserved;
        lgChart.data.datasets[2].data = broke;
        lgChart.data.datasets[3].data = deceased;
        applySmoothXScale(lgChart, minYear, maxYear);
        lgChart.update(smooth ? 'none' : undefined);
        return;
    }

    const theme = window.CHART_THEME;
    const longColors = theme.longevity;

    lgChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label: 'Growing (Wealth > Starting)',
                    data: growing,
                    backgroundColor: theme.alpha(theme.emerald, 0.85),
                    borderColor: longColors.sustainable,
                    borderWidth: 1,
                    fill: 'stack',
                    pointRadius: 0,
                    tension: 0.2,
                },
                {
                    label: 'Preserved ($0 < Wealth <= Starting)',
                    data: preserved,
                    backgroundColor: theme.alpha(theme.amber, 0.85),
                    borderColor: longColors.caution,
                    borderWidth: 1,
                    fill: 'stack',
                    pointRadius: 0,
                    tension: 0.2,
                },
                {
                    label: 'Broke (Depleted $0)',
                    data: broke,
                    backgroundColor: theme.alpha(theme.ruby, 0.90),
                    borderColor: longColors.depleted,
                    borderWidth: 1,
                    fill: 'stack',
                    pointRadius: 0,
                    tension: 0.2,
                },
                {
                    label: 'Both Deceased (Actuarial Joint Mortality)',
                    data: deceased,
                    backgroundColor: theme.alpha(theme.slate, 0.85),
                    borderColor: longColors.baseline,
                    borderWidth: 1,
                    fill: 'stack',
                    pointRadius: 0,
                    tension: 0.2,
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'nearLineOrEvent', intersect: false },
            onClick: (event, elements, chart) => {
                if (window._suppressChartClick) return;
                if (elements && elements.length > 0) {
                    const idx = elements[0].index;
                    const item = (chart._longevitySeries || series)[idx];
                    if (item) {
                        const yr = item.year;
                        state.inspectedYear = yr;
                        const scrubber = document.getElementById('timeline-scrubber');
                        if (scrubber) scrubber.value = yr;
                        updateScrubberNeedle(yr);
                        inspectTimelineYear(yr);
                    }
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        title: (items) => {
                            if (!items || !items.length) return '';
                            const s = (lgChart?._longevitySeries || series)[items[0].dataIndex];
                            if (!s) return '';
                            return `Year ${s.year} — ${pName} (Age ${s.age_primary}) & ${sName} (Age ${s.age_spouse})`;
                        },
                        label: (ctx) => `${ctx.dataset.label}: ${ctx.raw.toFixed(1)}%`,
                        afterBody: (items) => {
                            if (!items || !items.length) return '';
                            const s = (lgChart?._longevitySeries || series)[items[0].dataIndex];
                            if (!s) return '';
                            const pAlive = s.prob_primary_alive !== undefined ? s.prob_primary_alive : (100 - s.prob_deceased).toFixed(1);
                            const sAlive = s.prob_spouse_alive !== undefined ? s.prob_spouse_alive : (100 - s.prob_deceased).toFixed(1);
                            const jAlive = s.prob_joint_alive !== undefined ? s.prob_joint_alive : (100 - s.prob_deceased).toFixed(1);

                            return [
                                `────────────────────────`,
                                `Actuarial Survival (SSA Tables):`,
                                `  • ${pName} Alive (Age ${s.age_primary}): ${pAlive}%`,
                                `  • ${sName} Alive (Age ${s.age_spouse}): ${sAlive}%`,
                                `  • Joint Household Alive (At least one): ${jAlive}%`,
                                `  • Both Spouses Deceased: ${s.prob_deceased.toFixed(1)}%`,
                                `Portfolio Status: ${s.status.toUpperCase()} (${fmtShortCurrency(s.net_worth)})`
                            ].join('\n');
                        }
                    }
                }
            },
            scales: {
                x: {
                    ticks: { maxRotation: 0 }
                },
                y: {
                    stacked: true,
                    min: 0,
                    max: 100,
                    ticks: {
                        callback: (v) => `${v}%`
                    }
                }
            }
        }
    });
    if (isSharedCanvas) state.scenarioComparisonChart = lgChart;
    else state.longevityChart = lgChart;
    lgChart._longevitySeries = series;
    lgChart._minDataYear = series.length ? series[0].year : getPlanStartYear();
    lgChart._maxDataYear = series.length ? series[series.length - 1].year : 2060;
    applySmoothXScale(lgChart, minYear, maxYear);
    lgChart.update('none');
}

// =========================================================================
// Stochastic Monte Carlo & Sequence-of-Returns Crisis Stress Testing
// =========================================================================
let monteCarloFetchToken = 0;
