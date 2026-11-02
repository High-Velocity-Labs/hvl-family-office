/**
 * Stochastic Monte Carlo Lens & Probability Stress Cards
 */
import {
    state, fmtCurrency, fmtShortCurrency, getMonteCarloForScenario, getGraphScenarioId, setGraphScenarioId,
    getPlanStartYear
} from '../state.js';
import { renderGraphScenarioToggles, updateChartWindowContinuous } from './common.js';
import { loadChartToggles, loadChartCaption } from './chart_chrome.js';
import { h } from './dom.js';
import { getTimelineRange } from '../scrubber.js';

let monteCarloFetchToken = 0;
let mcSubMode = 'stochastic'; // 'stochastic' | 'historical'
export function getMcSubMode() { return mcSubMode; }
export function setMcSubMode(mode) { mcSubMode = (mode === 'historical') ? 'historical' : 'stochastic'; }

export async function renderMonteCarloLens(ctx, togglesContainer, captionEl, smooth = false) {
    if (!state.scenariosData) return;
    const scenId = getGraphScenarioId('montecarlo');
    const thisToken = ++monteCarloFetchToken;
    const isHist = (mcSubMode === 'historical');

    if (captionEl) {
        loadChartCaption(captionEl, { lens: 'montecarlo', mode: mcSubMode });
    }

    if (togglesContainer) {
        togglesContainer.replaceChildren();
        renderGraphScenarioToggles(togglesContainer, {
            graphKey: 'montecarlo',
            selectedScenarioId: scenId,
            onSelect: (selectedId) => {
                setGraphScenarioId('montecarlo', selectedId);
                renderMonteCarloLens(ctx, togglesContainer, captionEl, true);
            }
        });

        loadChartToggles(togglesContainer, {
            lens: 'montecarlo',
            mode: mcSubMode,
            modeAttr: 'data-mc-mode',
            onMode: (m) => {
                mcSubMode = m || 'stochastic';
                renderMonteCarloLens(ctx, togglesContainer, captionEl, false);
            }
        });
    }

    const loaderId = ctx?.canvas?.id === 'chart-scen_chart_montecarlo' ? 'montecarlo-chart-loading' : 'scenarios-chart-loading';
    let data = getMonteCarloForScenario(scenId);
    if (!data || (isHist && !data.historical_cohorts)) {
        const loader = document.getElementById(loaderId) || document.getElementById('scenarios-chart-loading');
        if (loader) {
            loader.classList.remove('hidden');
            loader.hidden = false;
        }
        try {
            const resp = await fetch(`/api/scenarios/monte-carlo?scenario_id=${encodeURIComponent(scenId)}&trials=1000`);
            if (resp.ok) {
                data = await resp.json();
                if (data && data.success) {
                    state.cachedMonteCarloByScen[scenId] = data;
                    state.cachedMonteCarloData = data;
                    state.cachedMonteCarloScenId = scenId;
                }
            }
        } catch (e) {
            console.error('Error fetching Monte Carlo data:', e);
        }
    } else {
        state.cachedMonteCarloData = data;
        state.cachedMonteCarloScenId = scenId;
    }

    if (thisToken !== monteCarloFetchToken) return;

    const loader = document.getElementById(loaderId) || document.getElementById('scenarios-chart-loading');
    if (loader) {
        loader.classList.add('hidden');
        loader.hidden = true;
    }

    if (!data || !data.percentiles_timeline) return;

    const histData = data.historical_cohorts || null;
    const timeline = (isHist && histData && Array.isArray(histData.percentiles_timeline) && histData.percentiles_timeline.length)
        ? histData.percentiles_timeline
        : data.percentiles_timeline;
    const { minYear, maxYear } = getTimelineRange();
    const labels = timeline.map(p => p.year);

    const p90 = timeline.map(p => p.p90);
    const p75 = timeline.map(p => p.p75);
    const p50 = timeline.map(p => p.p50);
    const p25 = timeline.map(p => p.p25);
    const p10 = timeline.map(p => p.p10);

    const yearYBounds = new Map();
    timeline.forEach((pt, idx) => {
        let yMin = 0;
        let yMax = 0;
        [p90[idx], p75[idx], p50[idx], p25[idx], p10[idx]].forEach(v => {
            if (typeof v === 'number' && Number.isFinite(v)) {
                if (v < yMin) yMin = v;
                if (v > yMax) yMax = v;
            }
        });
        yearYBounds.set(pt.year, { min: yMin, max: yMax });
    });

    renderMonteCarloCards(data);

    const canvas = ctx?.canvas;
    const isSharedCanvas = canvas?.id === 'chart-scenarios-comparison';
    let mcChart = isSharedCanvas ? state.scenarioComparisonChart : state.monteCarloChart;
    if (mcChart && (mcChart.canvas !== canvas || !document.body.contains(mcChart.canvas) || mcChart.config.type !== 'line' || !mcChart._mcTimeline)) {
        mcChart.destroy();
        mcChart = null;
        if (isSharedCanvas) state.scenarioComparisonChart = null;
        else state.monteCarloChart = null;
    }

    if (mcChart && mcChart.config.type === 'line' && mcChart.data.datasets?.length === 5) {
        mcChart.data.labels = labels;
        mcChart._mcTimeline = timeline;
        mcChart._yearYBounds = yearYBounds;
        mcChart._minDataYear = timeline.length ? timeline[0].year : getPlanStartYear();
        mcChart._maxDataYear = timeline.length ? timeline[timeline.length - 1].year : 2060;
        mcChart.data.datasets[0].data = p90;
        mcChart.data.datasets[1].data = p75;
        mcChart.data.datasets[2].data = p50;
        mcChart.data.datasets[3].data = p25;
        mcChart.data.datasets[4].data = p10;
        updateChartWindowContinuous(mcChart, minYear, maxYear, smooth);
        mcChart.update(smooth ? 'none' : undefined);
        return;
    }

    const theme = window.CHART_THEME;
    const mc = theme.monteCarlo;

    mcChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label: '90th Percentile (Boom)',
                    data: p90,
                    borderColor: mc.p95, // Cerulean
                    backgroundColor: theme.alpha(theme.cerulean, 0.06),
                    borderWidth: 1,
                    borderDash: [2, 2],
                    pointRadius: 0,
                    fill: '+1',
                    tension: 0.3
                },
                {
                    label: '75th Percentile (Strong Bull)',
                    data: p75,
                    borderColor: mc.p75, // Deep Cerulean
                    backgroundColor: theme.alpha(theme.cerulean, 0.14),
                    borderWidth: 1.5,
                    pointRadius: 0,
                    fill: '+1',
                    tension: 0.3
                },
                {
                    label: '50th Percentile (Median)',
                    data: p50,
                    borderColor: mc.p50, // Sapphire
                    backgroundColor: theme.alpha(theme.sapphire, 0.18),
                    borderWidth: 3,
                    pointRadius: 0,
                    fill: '+1',
                    tension: 0.3
                },
                {
                    label: '25th Percentile (Below Average)',
                    data: p25,
                    borderColor: mc.p25, // Amber Ochre
                    backgroundColor: theme.alpha(theme.ruby, 0.08),
                    borderWidth: 1.5,
                    pointRadius: 0,
                    fill: '+1',
                    tension: 0.3
                },
                {
                    label: '10th Percentile (Bear Floor)',
                    data: p10,
                    borderColor: mc.p10, // HVL Muted Rose
                    borderWidth: 2,
                    borderDash: [4, 4],
                    pointRadius: 0,
                    fill: false,
                    tension: 0.3
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        title: (items) => {
                            if (!items || !items.length) return '';
                            const pt = (mcChart?._mcTimeline || timeline)[items[0].dataIndex];
                            return pt ? `Year ${pt.year} (Age ${pt.age})` : '';
                        },
                        label: (ctx) => `${ctx.dataset.label}: ${fmtShortCurrency(ctx.raw)}`,
                    }
                }
            },
            scales: {
                x: {
                    ticks: { maxRotation: 0 }
                },
                y: {
                    ticks: {
                        callback: (v) => fmtShortCurrency(v)
                    }
                }
            }
        }
    });
    if (isSharedCanvas) state.scenarioComparisonChart = mcChart;
    else state.monteCarloChart = mcChart;
    mcChart._mcTimeline = timeline;
    mcChart._yearYBounds = yearYBounds;
    mcChart._minDataYear = timeline.length ? timeline[0].year : getPlanStartYear();
    mcChart._maxDataYear = timeline.length ? timeline[timeline.length - 1].year : 2060;
    updateChartWindowContinuous(mcChart, minYear, maxYear, false);
    mcChart.update('none');
}

export function renderMonteCarloCards(data) {
    const summaryContainer = document.getElementById('mc-summary-cards');
    const stressContainer = document.getElementById('mc-stress-cards');
    const histSection = document.getElementById('mc-historical-cohorts-section');
    if (!summaryContainer || !stressContainer) return;

    const isHist = (mcSubMode === 'historical');
    const hc = data.historical_cohorts || null;
    const rate100 = (isHist && hc) ? (hc.survival_rate_age_100 ?? 0) : (data.success_rate_age_100 ?? null);
    const medTerm = (isHist && hc) ? (hc.median_terminal_wealth ?? data.median_terminal_wealth) : data.median_terminal_wealth;
    const p10Term = (isHist && hc) ? (hc.p10_terminal_wealth ?? data.p10_terminal_wealth) : data.p10_terminal_wealth;

    const rateKnown = rate100 !== null;
    const rate100Text = rateKnown ? `${rate100}%` : 'n/a';
    let rateBadge = 'badge-red';
    let rateText = 'Actionable Vulnerability';
    if (!rateKnown) {
        rateBadge = 'badge-orange';
        rateText = 'Projection ends before age 100';
    } else if (rate100 >= 95) {
        rateBadge = 'badge-green';
        rateText = 'Extremely Resilient';
    } else if (rate100 >= 80) {
        rateBadge = 'badge-orange';
        rateText = 'Manageable Risk';
    }
    const portVol = (data.portfolio_stats?.volatility * 100).toFixed(1);
    const expRet = (data.portfolio_stats?.expected_return * 100).toFixed(1);
    const hcSurvStr = hc ? `${hc.survived_cohorts}/${hc.total_cohorts} Eras (${hc.survival_rate_age_100}%)` : `σ = ${portVol}% / yr`;
    const hcSubStr = hc
        ? (hc.failed_start_years && hc.failed_start_years.length
            ? `Depleted in: ${hc.failed_start_years.slice(0, 5).join(', ')}${hc.failed_start_years.length > 5 ? '…' : ''}`
            : `Survived all 98 cohorts (1928–2025) · σ=${portVol}%`)
        : `Weighted expected return: +${expRet}%/yr`;

    const statCard = (label, value, valueClass, note) => h('div', { class: 'mc-card' },
        h('div', { class: 'mc-stat-label', text: label }),
        h('div', { class: `mc-stat-value ${valueClass}`, text: value }),
        note);
    const note = (text) => h('div', { class: 'mc-note', text });

    summaryContainer.replaceChildren(
        statCard(isHist ? 'Historical Survival (Age 100)' : 'Plan Solvency Rate (Age 100)', rate100Text, '',
            h('span', { class: `badge ${rateBadge}`, text: rateText })),
        statCard('Median Terminal Wealth (Age 100)', fmtShortCurrency(medTerm), 'mc-stat-value--positive',
            note(isHist ? '50th percentile (1928–2025 cohorts)' : '50th percentile outcome')),
        statCard('Downside Floor (10th Percentile)', fmtShortCurrency(p10Term),
            p10Term > 0 ? '' : 'mc-stat-value--negative',
            note(isHist ? 'Bottom decile historical cohort' : 'Unlucky 1-in-10 market sequence')),
        statCard('1928–2025 Cohort Backtest', hcSurvStr, 'mc-stat-value--compact', note(hcSubStr))
    );

    if (histSection) {
        const worstList = (hc && Array.isArray(hc.worst_cohorts)) ? hc.worst_cohorts.slice(0, 4) : [];
        if (worstList.length > 0) {
            const cards = worstList.map(c => {
                const ok = c.survived;
                const bTxt = ok ? 'Survived' : (c.depletion_age ? `Depleted Age ${c.depletion_age}` : 'Depleted');
                return h('div', { class: `mc-card mc-card--compact${ok ? '' : ' is-depleted'}` },
                    h('div', { class: 'mc-card-head' },
                        h('strong', { class: 'mc-card-name', text: c.label }),
                        h('span', { class: `badge mc-card-badge ${ok ? 'badge-green' : 'badge-red'}`, text: bTxt })),
                    h('div', { class: 'mc-card-metrics' },
                        h('div', null, 'Max Drawdown: ',
                            h('strong', { class: 'mc-metric-value--loss', text: `${c.max_drawdown_pct}%` })),
                        h('div', null, 'Terminal NW: ',
                            h('strong', { class: 'mc-metric-value', text: fmtShortCurrency(c.terminal_net_worth) }))));
            });
            histSection.replaceChildren(
                h('h4', { class: 'mc-section-title' },
                    h('span', { text: 'Toughest Historical Starting Years (1928–2025 Full-History Backtest)' }),
                    h('span', {
                        class: 'mc-section-sub',
                        text: `— 4 most severe sequence-of-returns cohorts out of ${hc.total_cohorts} rolling market `
                            + `eras`
                    })),
                h('div', { class: 'mc-card-grid' }, cards)
            );
        } else {
            histSection.replaceChildren();
        }
    }

    const stressTests = data.stress_tests || {};
    stressContainer.replaceChildren(...Object.values(stressTests).map(st => {
        const isOk = st.survived;
        const metric = (label, value, valueClass) => h('div', null,
            h('div', { class: 'mc-metric-label', text: label }),
            h('div', { class: `mc-metric-value ${valueClass}`, text: value }));
        return h('div', { class: `mc-card${isOk ? '' : ' is-depleted'}` },
            h('div', { class: 'mc-card-head mc-card-head--top' },
                h('div', { class: 'mc-card-name', text: st.name }),
                h('span', {
                    class: `badge mc-card-badge ${isOk ? 'badge-green' : 'badge-red'}`,
                    text: isOk ? 'Solvency Preserved' : 'Depleted'
                })),
            h('div', { class: 'mc-card-desc', text: st.description }),
            h('div', { class: 'mc-card-metrics mc-card-metrics--ruled' },
                metric('Max Drawdown:', `${st.max_drawdown_pct}%`, 'mc-metric-value--loss'),
                metric('Trough Net Worth:', `${fmtShortCurrency(st.trough_net_worth)} (${st.trough_year})`, '')));
    }));
}

// =========================================================================
// Side-by-Side Scenario Diff Scorecard Table
// =========================================================================
