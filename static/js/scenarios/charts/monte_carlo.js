/**
 * Stochastic Monte Carlo Lens & Probability Stress Cards
 */
import { state, escapeHtml, fmtCurrency, fmtShortCurrency, getMonteCarloForScenario } from '../state.js';
import { renderGraphScenarioToggles, updateChartWindowContinuous } from './common.js';
import { getTimelineRange } from '../scrubber.js';

let monteCarloFetchToken = 0;
let mcSubMode = 'stochastic'; // 'stochastic' | 'historical'
export function getMcSubMode() { return mcSubMode; }
export function setMcSubMode(mode) { mcSubMode = (mode === 'historical') ? 'historical' : 'stochastic'; }

export async function renderMonteCarloLens(ctx, togglesContainer, captionEl, smooth = false) {
    if (!state.scenariosData) return;
    const scenId = state.selectedScenarioId || state.scenariosData.active_scenario_id || 'scen_baseline';
    const thisToken = ++monteCarloFetchToken;
    const isHist = (mcSubMode === 'historical');

    if (captionEl) {
        captionEl.innerHTML = isHist
            ? `<strong>1928–2025 Historical Cohort Backtest (98 Rolling Eras):</strong> Replays your exact plan against every historical starting year since 1928 using actual annual S&amp;P 500, 10-Yr Treasury, T-Bill, and CPI inflation returns.`
            : `<strong>1,000-Trial Stochastic Monte Carlo Envelope:</strong> Shaded percentile corridors (10th, 25th, 50th Median, 75th, 90th) illustrating sequence-of-returns dispersion across asset class volatility.`;
    }

    if (togglesContainer) {
        togglesContainer.innerHTML = '';
        renderGraphScenarioToggles(togglesContainer);

        const sep = document.createElement('span');
        sep.style.cssText = 'border-left: 1px solid var(--border-subtle); margin: 0 4px; height: 16px; align-self: center;';
        togglesContainer.appendChild(sep);

        const modeToggle = document.createElement('div');
        modeToggle.className = 'pill-group';
        modeToggle.style.cssText = 'display: inline-flex; gap: 3px; background: var(--bg-surface); padding: 2px; border-radius: 6px; border: 1px solid var(--border-subtle);';
        modeToggle.innerHTML = `
            <button type="button" class="pill-btn ${!isHist ? 'active' : ''}" data-mc-mode="stochastic" style="font-size: 0.6875rem; padding: 2px 8px;">Stochastic (1,000 Trials)</button>
            <button type="button" class="pill-btn ${isHist ? 'active' : ''}" data-mc-mode="historical" style="font-size: 0.6875rem; padding: 2px 8px;">1928–2025 Backtest (98 Cohorts)</button>
        `;
        modeToggle.querySelectorAll('button[data-mc-mode]').forEach(btn => {
            btn.onclick = () => {
                mcSubMode = btn.getAttribute('data-mc-mode') || 'stochastic';
                renderMonteCarloLens(ctx, togglesContainer, captionEl, false);
            };
        });
        togglesContainer.appendChild(modeToggle);
    }

    const loaderId = ctx?.canvas?.id === 'chart-scen_chart_montecarlo' ? 'montecarlo-chart-loading' : 'scenarios-chart-loading';
    let data = getMonteCarloForScenario(scenId);
    if (!data || (isHist && !data.historical_cohorts)) {
        const loader = document.getElementById(loaderId) || document.getElementById('scenarios-chart-loading');
        if (loader) {
            loader.classList.remove('hidden');
            loader.style.display = 'flex';
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
        loader.style.display = 'none';
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
        mcChart._minDataYear = timeline.length ? timeline[0].year : 2026;
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
    const mc = theme ? theme.monteCarlo : null;

    mcChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label: '90th Percentile (Boom)',
                    data: p90,
                    borderColor: mc ? mc.p95 : 'rgba(2, 132, 199, 0.45)', // Cerulean
                    backgroundColor: theme ? theme.alpha(theme.cerulean, 0.06) : 'rgba(2, 132, 199, 0.06)',
                    borderWidth: 1,
                    borderDash: [2, 2],
                    pointRadius: 0,
                    fill: '+1',
                    tension: 0.3
                },
                {
                    label: '75th Percentile (Strong Bull)',
                    data: p75,
                    borderColor: mc ? mc.p75 : 'rgba(2, 132, 199, 0.75)', // Deep Cerulean
                    backgroundColor: theme ? theme.alpha(theme.cerulean, 0.14) : 'rgba(2, 132, 199, 0.14)',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    fill: '+1',
                    tension: 0.3
                },
                {
                    label: '50th Percentile (Median)',
                    data: p50,
                    borderColor: mc ? mc.p50 : '#1D4ED8', // Sapphire
                    backgroundColor: theme ? theme.alpha(theme.sapphire, 0.18) : 'rgba(29, 78, 216, 0.18)',
                    borderWidth: 3,
                    pointRadius: 0,
                    fill: '+1',
                    tension: 0.3
                },
                {
                    label: '25th Percentile (Below Average)',
                    data: p25,
                    borderColor: mc ? mc.p25 : 'rgba(217, 119, 6, 0.85)', // Amber Ochre
                    backgroundColor: theme ? theme.alpha(theme.ruby, 0.08) : 'rgba(199, 93, 110, 0.08)',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    fill: '+1',
                    tension: 0.3
                },
                {
                    label: '10th Percentile (Bear Floor)',
                    data: p10,
                    borderColor: mc ? mc.p10 : '#C75D6E', // HVL Muted Rose
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
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: '#94A3B8', maxRotation: 0 }
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
    if (isSharedCanvas) state.scenarioComparisonChart = mcChart;
    else state.monteCarloChart = mcChart;
    mcChart._mcTimeline = timeline;
    mcChart._yearYBounds = yearYBounds;
    mcChart._minDataYear = timeline.length ? timeline[0].year : 2026;
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
    const rate100 = (isHist && hc) ? (hc.survival_rate_age_100 ?? 0) : (data.success_rate_age_100 || 0);
    const medTerm = (isHist && hc) ? (hc.median_terminal_wealth ?? data.median_terminal_wealth) : data.median_terminal_wealth;
    const p10Term = (isHist && hc) ? (hc.p10_terminal_wealth ?? data.p10_terminal_wealth) : data.p10_terminal_wealth;

    const rateBadge = rate100 >= 95 ? 'badge-green' : (rate100 >= 80 ? 'badge-orange' : 'badge-red');
    const rateText = rate100 >= 95 ? 'Extremely Resilient' : (rate100 >= 80 ? 'Manageable Risk' : 'Actionable Vulnerability');
    const portVol = (data.portfolio_stats?.volatility * 100).toFixed(1);
    const expRet = (data.portfolio_stats?.expected_return * 100).toFixed(1);
    const hcSurvStr = hc ? `${hc.survived_cohorts}/${hc.total_cohorts} Eras (${hc.survival_rate_age_100}%)` : `σ = ${portVol}% / yr`;
    const hcSubStr = hc
        ? (hc.failed_start_years && hc.failed_start_years.length
            ? `Depleted in: ${hc.failed_start_years.slice(0, 5).join(', ')}${hc.failed_start_years.length > 5 ? '…' : ''}`
            : `Survived all 98 cohorts (1928–2025) · σ=${portVol}%`)
        : `Weighted expected return: +${expRet}%/yr`;

    summaryContainer.innerHTML = `
        <div style="background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: 8px; padding: 12px 14px;">
            <div style="font-size: 0.6875rem; text-transform: uppercase; color: var(--text-muted); font-weight: 600;">${isHist ? 'Historical Survival (Age 100)' : 'Plan Solvency Rate (Age 100)'}</div>
            <div style="font-size: 1.5rem; font-weight: 700; color: var(--text-primary); margin: 4px 0;">${rate100}%</div>
            <span class="badge ${rateBadge}">${rateText}</span>
        </div>
        <div style="background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: 8px; padding: 12px 14px;">
            <div style="font-size: 0.6875rem; text-transform: uppercase; color: var(--text-muted); font-weight: 600;">Median Terminal Wealth (Age 100)</div>
            <div style="font-size: 1.5rem; font-weight: 700; color: var(--accent-green); margin: 4px 0;">${fmtShortCurrency(medTerm)}</div>
            <div style="font-size: 0.75rem; color: var(--text-muted);">${isHist ? '50th percentile (1928–2025 cohorts)' : '50th percentile outcome'}</div>
        </div>
        <div style="background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: 8px; padding: 12px 14px;">
            <div style="font-size: 0.6875rem; text-transform: uppercase; color: var(--text-muted); font-weight: 600;">Downside Floor (10th Percentile)</div>
            <div style="font-size: 1.5rem; font-weight: 700; color: ${p10Term > 0 ? 'var(--text-primary)' : 'var(--accent-red)'}; margin: 4px 0;">${fmtShortCurrency(p10Term)}</div>
            <div style="font-size: 0.75rem; color: var(--text-muted);">${isHist ? 'Bottom decile historical cohort' : 'Unlucky 1-in-10 market sequence'}</div>
        </div>
        <div style="background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: 8px; padding: 12px 14px;">
            <div style="font-size: 0.6875rem; text-transform: uppercase; color: var(--text-muted); font-weight: 600;">1928–2025 Cohort Backtest</div>
            <div style="font-size: 1.25rem; font-weight: 700; color: var(--text-primary); margin: 4px 0;">${hcSurvStr}</div>
            <div style="font-size: 0.75rem; color: var(--text-muted);">${escapeHtml(hcSubStr)}</div>
        </div>
    `;

    if (histSection) {
        const worstList = (hc && Array.isArray(hc.worst_cohorts)) ? hc.worst_cohorts.slice(0, 4) : [];
        if (worstList.length > 0) {
            const cardsHtml = worstList.map(c => {
                const ok = c.survived;
                const bCls = ok ? 'badge-green' : 'badge-red';
                const bTxt = ok ? 'Survived' : (c.depletion_age ? `Depleted Age ${c.depletion_age}` : 'Depleted');
                return `
                    <div style="background: var(--bg-surface); border: 1px solid ${ok ? 'var(--border-subtle)' : 'rgba(239, 68, 68, 0.4)'}; border-radius: 8px; padding: 10px 12px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; gap: 6px; margin-bottom: 6px;">
                            <strong style="font-size: 0.78rem; color: var(--text-primary);">${escapeHtml(c.label)}</strong>
                            <span class="badge ${bCls}" style="font-size: 0.65rem;">${escapeHtml(bTxt)}</span>
                        </div>
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; font-size: 0.72rem; color: var(--text-muted);">
                            <div>Max Drawdown: <strong style="color: var(--accent-red);">${c.max_drawdown_pct}%</strong></div>
                            <div>Terminal NW: <strong style="color: var(--text-primary);">${fmtShortCurrency(c.terminal_net_worth)}</strong></div>
                        </div>
                    </div>
                `;
            }).join('');
            histSection.innerHTML = `
                <h4 style="font-size: 0.875rem; font-weight: 600; margin: 0 0 8px 0; color: var(--text-primary); display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
                    <span>Toughest Historical Starting Years (1928–2025 Full-History Backtest)</span>
                    <span style="font-size: 0.75rem; font-weight: normal; color: var(--text-muted);">— 4 most severe sequence-of-returns cohorts out of ${hc.total_cohorts} rolling market eras</span>
                </h4>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px;">${cardsHtml}</div>
            `;
        } else {
            histSection.innerHTML = '';
        }
    }

    const stressTests = data.stress_tests || {};
    stressContainer.innerHTML = Object.values(stressTests).map(st => {
        const isOk = st.survived;
        const badgeClass = isOk ? 'badge-green' : 'badge-red';
        const badgeLabel = isOk ? 'Solvency Preserved' : 'Depleted';
        return `
            <div style="background: var(--bg-surface); border: 1px solid ${isOk ? 'var(--border-subtle)' : 'rgba(239, 68, 68, 0.4)'}; border-radius: 8px; padding: 12px 14px;">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 6px;">
                    <div style="font-size: 0.8125rem; font-weight: 600; color: var(--text-primary); display: flex; align-items: center; gap: 5px;">
                        <span>${escapeHtml(st.name)}</span>
                    </div>
                    <span class="badge ${badgeClass}" style="font-size: 0.6875rem;">${badgeLabel}</span>
                </div>
                <div style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 8px; line-height: 1.35;">${escapeHtml(st.description)}</div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; font-size: 0.75rem; padding-top: 6px; border-top: 1px solid var(--border-subtle);">
                    <div>
                        <div style="color: var(--text-muted); font-size: 0.6875rem;">Max Drawdown:</div>
                        <div style="font-weight: 600; color: var(--accent-red);">${st.max_drawdown_pct}%</div>
                    </div>
                    <div>
                        <div style="color: var(--text-muted); font-size: 0.6875rem;">Trough Net Worth:</div>
                        <div style="font-weight: 600; color: var(--text-primary);">${fmtShortCurrency(st.trough_net_worth)} (${st.trough_year})</div>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

// =========================================================================
// Side-by-Side Scenario Diff Scorecard Table
// =========================================================================
