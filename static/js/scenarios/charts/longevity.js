/**
 * Lens 3: Longevity Portfolio Survival (SSA Actuarial 100% Stacked Area)
 */
import { state, escapeHtml, fmtCurrency, fmtShortCurrency, getMonteCarloForScenario, ensureMonteCarloForScenario } from '../state.js';
import { renderGraphScenarioToggles, applySmoothXScale } from './common.js';
import { getTimelineRange, inspectTimelineYear, updateScrubberNeedle } from '../scrubber.js';

export function renderLongevityStackedAreaLens(ctx, togglesContainer, captionEl, smooth = false) {
    if (!state.scenariosData) return;

    const pName = (state.scenariosData && state.scenariosData.primary_name) || 'Primary';
    const sName = (state.scenariosData && state.scenariosData.spouse_name) || 'Spouse';

    if (captionEl) {
        captionEl.textContent = `Stochastic Longevity & Solvency (SSA Actuarial, 100% Stacked Area): Bottom axis shows calendar Year alongside ages for ${pName} and ${sName}. Powered by 1,000 Monte Carlo market trials combined with SSA joint mortality tables. Tracks probabilities of growing wealth (green), preserving capital (yellow), exhausting funds in bear markets (red), or joint mortality (grey).`;
    }

    const effectiveScenId = state.selectedScenarioId || state.scenariosData.active_scenario_id || 'scen_baseline';
    const mcSource = getMonteCarloForScenario(effectiveScenId);
    if (!mcSource) {
        ensureMonteCarloForScenario(effectiveScenId);
    }
    const series = (mcSource && mcSource.longevity_breakdown)
        ? mcSource.longevity_breakdown
        : ((state.scenariosData.scenario_longevity_breakdowns && state.selectedScenarioId && state.scenariosData.scenario_longevity_breakdowns[state.selectedScenarioId])
            || state.scenariosData.active_longevity_breakdown
            || []);
    const { minYear, maxYear } = getTimelineRange();

    // Bottom axis is calendar Year
    const labels = series.map(s => s.year);

    const growing = series.map(s => s.prob_growing);
    const preserved = series.map(s => s.prob_preserved);
    const broke = series.map(s => s.prob_broke);
    const deceased = series.map(s => s.prob_deceased);

    if (togglesContainer) {
        togglesContainer.innerHTML = '';
        renderGraphScenarioToggles(togglesContainer);

        const sep = document.createElement('span');
        sep.style.cssText = 'border-left: 1px solid var(--border-subtle); margin: 0 4px; height: 16px; align-self: center;';
        togglesContainer.appendChild(sep);

        const survBadges = document.createElement('span');
        survBadges.style.cssText = 'display: inline-flex; gap: 6px; flex-wrap: wrap; align-items: center;';
        survBadges.innerHTML = `
            <span class="badge badge-green" title="Trials where real net worth exceeds initial starting purchasing power">Growing (Wealth > Starting)</span>
            <span class="badge badge-orange" title="Trials where capital remains above $0 but below starting value">Preserved (Wealth > $0)</span>
            <span class="badge badge-red" title="Trials where liquid portfolio depleted in adverse market sequences">Broke (Depleted $0)</span>
            <span class="badge" style="background: rgba(100, 116, 139, 0.2); color: #94A3B8;" title="Actuarial probability both spouses have passed away">Both Deceased (SSA Joint Mortality)</span>
        `;
        togglesContainer.appendChild(survBadges);
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
        lgChart._minDataYear = series.length ? series[0].year : 2026;
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
    const longColors = theme ? theme.longevity : null;

    lgChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label: 'Growing (Wealth > Starting)',
                    data: growing,
                    backgroundColor: theme ? theme.alpha(theme.emerald, 0.85) : 'rgba(5, 150, 105, 0.85)',
                    borderColor: longColors ? longColors.sustainable : '#059669',
                    borderWidth: 1,
                    fill: 'stack',
                    pointRadius: 0,
                    tension: 0.2,
                },
                {
                    label: 'Preserved ($0 < Wealth <= Starting)',
                    data: preserved,
                    backgroundColor: theme ? theme.alpha(theme.amber, 0.85) : 'rgba(217, 119, 6, 0.85)',
                    borderColor: longColors ? longColors.caution : '#D97706',
                    borderWidth: 1,
                    fill: 'stack',
                    pointRadius: 0,
                    tension: 0.2,
                },
                {
                    label: 'Broke (Depleted $0)',
                    data: broke,
                    backgroundColor: theme ? theme.alpha(theme.ruby, 0.90) : 'rgba(225, 29, 72, 0.9)',
                    borderColor: longColors ? longColors.depleted : '#E11D48',
                    borderWidth: 1,
                    fill: 'stack',
                    pointRadius: 0,
                    tension: 0.2,
                },
                {
                    label: 'Both Deceased (Actuarial Joint Mortality)',
                    data: deceased,
                    backgroundColor: theme ? theme.alpha(theme.slate, 0.85) : 'rgba(100, 116, 139, 0.85)',
                    borderColor: longColors ? longColors.baseline : '#64748B',
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
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: '#94A3B8', maxRotation: 0 }
                },
                y: {
                    stacked: true,
                    min: 0,
                    max: 100,
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: {
                        color: '#94A3B8',
                        callback: (v) => `${v}%`
                    }
                }
            }
        }
    });
    if (isSharedCanvas) state.scenarioComparisonChart = lgChart;
    else state.longevityChart = lgChart;
    lgChart._longevitySeries = series;
    lgChart._minDataYear = series.length ? series[0].year : 2026;
    lgChart._maxDataYear = series.length ? series[series.length - 1].year : 2060;
    applySmoothXScale(lgChart, minYear, maxYear);
    lgChart.update('none');
}

// =========================================================================
// Stochastic Monte Carlo & Sequence-of-Returns Crisis Stress Testing
// =========================================================================
let monteCarloFetchToken = 0;
