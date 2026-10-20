/**
 * Overview Chart Renderers (Granular Allocation Doughnut, 5-Year Projection & Historical Net Worth)
 * Extracted from static/js/overview.js for modular separation.
 */

var allocationChart = null;
var projectionChart = null;
var overviewAllocMode = 'total';
var cachedSnapshot = null;

function renderGranularAllocationChart(snap) {
    const loader = document.getElementById('overview-alloc-loading');
    if (loader) {
        loader.classList.add('hidden');
        loader.style.display = 'none';
    }
    const canvas = document.getElementById('chart-allocation');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (allocationChart) allocationChart.destroy();

    const detailed = (snap && snap.detailed_asset_allocation) || {};
    const totals = detailed.totals || {};
    const titleEl = document.getElementById('overview-alloc-title');
    const subEl = document.getElementById('overview-alloc-sub');

    let labels = [];
    let dataValues = [];
    let backgroundColors = [];
    let isZeroAllocation = false;

    if (overviewAllocMode === 'public') {
        if (titleEl) titleEl.textContent = 'Public Securities Allocation (US, Intl, Bonds, Cash)';
        if (subEl) subEl.textContent = 'Underlying portfolio split across taxable brokerage & retirement accounts (529s excluded)';

        labels = ['US Equities', 'International Equities', 'Bonds & Fixed Income', 'Cash & Settlement Sweeps'];
        dataValues = [totals.us_equity || 0, totals.intl_equity || 0, totals.bonds || 0, totals.cash_liquid || 0];
        const theme = window.CHART_THEME;
        backgroundColors = theme
            ? [theme.emerald, theme.cerulean, theme.tanzanite, theme.slate]
            : ['#059669', '#0284C7', '#7C3AED', '#64748B'];
        const pubSum = dataValues.reduce((a, b) => a + b, 0);
        if (pubSum <= 0) isZeroAllocation = true;
    } else {
        if (titleEl) titleEl.textContent = 'Asset Allocation Breakdown (Total Net Worth)';
        if (subEl) subEl.textContent = 'Underlying security distribution across all assets (Company Equity, Real Estate, US/Intl/Bonds; 529s excluded)';

        const items = detailed.items || [];
        const validItems = items.filter(it => it.value > 0);
        if (validItems.length === 0) {
            isZeroAllocation = true;
        } else {
            labels = validItems.map(it => it.label);
            dataValues = validItems.map(it => it.value);
            const theme = window.CHART_THEME;
            backgroundColors = validItems.map((it, idx) => {
                if (theme && theme.allocationByKey && it.key && theme.allocationByKey[it.key]) {
                    return theme.allocationByKey[it.key];
                }
                if (theme && it.color) return theme.normalizeScenarioColor(it.color, idx);
                return (theme && theme.allocation[idx % theme.allocation.length]) || it.color || '#1D4ED8';
            });
        }
    }

    if (isZeroAllocation) {
        labels = ['No Accounts Connected'];
        dataValues = [1];
        backgroundColors = ['rgba(148, 163, 184, 0.18)'];
    }

    const totalVal = isZeroAllocation ? 0 : dataValues.reduce((a, b) => a + b, 0);

    allocationChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{ data: dataValues, backgroundColor: backgroundColors, borderColor: '#161B26', borderWidth: 2 }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right',
                    labels: {
                        color: '#94A3B8',
                        font: { family: 'Inter', size: 11 },
                        padding: 10,
                        generateLabels: (chart) => {
                            if (isZeroAllocation) {
                                return [{
                                    text: '0% Allocated (No connected accounts)',
                                    fillStyle: 'rgba(148, 163, 184, 0.25)',
                                    strokeStyle: '#161B26',
                                    lineWidth: 1,
                                    hidden: false,
                                    index: 0
                                }];
                            }
                            const data = chart.data;
                            if (data.labels.length && data.datasets.length) {
                                const meta = chart.getDatasetMeta(0);
                                return data.labels.map((label, i) => {
                                    const val = data.datasets[0].data[i];
                                    const pct = totalVal > 0 ? ((val / totalVal) * 100).toFixed(1) + '%' : '0%';
                                    const isHidden = meta && meta.data && meta.data[i] ? meta.data[i].hidden : false;
                                    return {
                                        text: `${label} (${pct})`,
                                        fillStyle: data.datasets[0].backgroundColor[i],
                                        strokeStyle: '#161B26',
                                        lineWidth: 1,
                                        hidden: isNaN(val) || isHidden,
                                        index: i
                                    };
                                });
                            }
                            return [];
                        }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            if (isZeroAllocation) return ' Connect an institution or import CSV in Accounts';
                            return ` ${ctx.label}: ${fmtShortCurrency(ctx.raw)} (${totalVal > 0 ? ((ctx.raw / totalVal) * 100).toFixed(1) : 0}%)`;
                        }
                    }
                }
            },
            cutout: '62%'
        }
    });
}

function renderProjectionChart(projections) {
    const loader = document.getElementById('overview-chart-loading');
    if (loader) {
        loader.classList.add('hidden');
        loader.style.display = 'none';
    }
    const canvas = document.getElementById('chart-projection');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (projectionChart) projectionChart.destroy();

    if (!projections || projections.length === 0) return;

    const labels = projections.map(p => String(p.label || p.year));
    const totalNetWorthValues = projections.map(p => p.total_true_net_worth || ((p.true_net_equity || 0) + ((p.non_equity_net_worth !== undefined ? p.non_equity_net_worth : 0))));
    const equityNetValues = projections.map(p => p.true_net_equity || 0);
    const nonEquityValues = projections.map(p => p.non_equity_net_worth || 0);
    const unvestedValues = projections.map(p => p.unvested_net_value || 0);

    const compName = (cachedSnapshot && cachedSnapshot.company_equity && cachedSnapshot.company_equity.company_name) || 'Company';
    const hasStrike = (cachedSnapshot && cachedSnapshot.company_equity && (cachedSnapshot.company_equity.total_strike_cost_needed || 0) > 0);
    const hasTaxDrag = (cachedSnapshot && cachedSnapshot.company_equity && (cachedSnapshot.company_equity.total_tax_drag || 0) > 0);
    const hasAdjustment = hasStrike || hasTaxDrag;
    const nwProjChartLabel = hasAdjustment ? 'Net Worth (Post-Tax, Vested Only)' : 'Net Worth';
    const compProjChartLabel = hasAdjustment ? `${compName} Post-Tax Equity (Vested)` : `${compName} Equity`;

    projectionChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: nwProjChartLabel,
                    data: totalNetWorthValues,
                    borderColor: (window.CHART_THEME && window.CHART_THEME.netWorth.primary) || '#059669',
                    backgroundColor: (window.CHART_THEME && window.CHART_THEME.netWorth.primaryFill) || 'rgba(5, 150, 105, 0.15)',
                    fill: true, tension: 0.35, borderWidth: 3, pointRadius: 3, pointHoverRadius: 6,
                },
                {
                    label: compProjChartLabel,
                    data: equityNetValues,
                    borderColor: (window.CHART_THEME && window.CHART_THEME.netWorth.equity) || '#0284C7',
                    backgroundColor: (window.CHART_THEME && window.CHART_THEME.netWorth.equityFill) || 'rgba(2, 132, 199, 0.08)',
                    borderDash: [5, 4], fill: true, tension: 0.35, borderWidth: 2, pointRadius: 2, pointHoverRadius: 5,
                },
                {
                    label: 'Liquid & Other Wealth',
                    data: nonEquityValues,
                    borderColor: (window.CHART_THEME && window.CHART_THEME.netWorth.liquid) || '#1D4ED8',
                    backgroundColor: 'transparent', fill: false, tension: 0.35, borderWidth: 2, pointRadius: 2, pointHoverRadius: 5,
                },
                {
                    label: `Unvested ${compName} Equity (Excluded until Vested)`,
                    data: unvestedValues,
                    borderColor: (window.CHART_THEME && window.CHART_THEME.netWorth.unvested) || '#D97706',
                    backgroundColor: 'transparent', borderDash: [4, 4], fill: false, tension: 0.35, borderWidth: 2, pointRadius: 2, pointHoverRadius: 5,
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { position: 'top', labels: { color: '#94A3B8', font: { family: 'Inter', size: 11 } } },
                tooltip: {
                    callbacks: { label: (ctx) => ` ${ctx.dataset.label}: ${fmtShortCurrency(ctx.raw)} (${fmtCurrency(ctx.raw, 0)})` }
                }
            },
            scales: {
                x: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94A3B8' } },
                y: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94A3B8', callback: (v) => fmtShortCurrency(v) } }
            }
        }
    });
}

function renderHistoricalChart(history) {
    const loader = document.getElementById('overview-chart-loading');
    if (loader) {
        loader.classList.add('hidden');
    }
    const canvas = document.getElementById('chart-projection');
    if (!canvas || !history) return;
    const ctx = canvas.getContext('2d');
    if (projectionChart) projectionChart.destroy();

    const compName = (cachedSnapshot && cachedSnapshot.company_equity && cachedSnapshot.company_equity.company_name) || 'Company';
    const hasStrike = (cachedSnapshot && cachedSnapshot.company_equity && (cachedSnapshot.company_equity.total_strike_cost_needed || 0) > 0);
    const hasTaxDrag = (cachedSnapshot && cachedSnapshot.company_equity && (cachedSnapshot.company_equity.total_tax_drag || 0) > 0);
    const hasAdjustment = hasStrike || hasTaxDrag;
    const nwHistChartLabel = hasAdjustment ? 'Net Worth (Post-Tax)' : 'Net Worth';
    const compHistChartLabel = hasAdjustment ? `${compName} Post-Tax Equity` : `${compName} Equity`;

    const labels = history.map(h => String(h.period || h.year));
    const netWorthValues = history.map(h => h.true_net_worth);
    const equityValues = history.map(h => h.equity_net || 0);
    const liquidValues = history.map(h => h.liquid_investments);

    projectionChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: nwHistChartLabel,
                    data: netWorthValues,
                    borderColor: (window.CHART_THEME && window.CHART_THEME.netWorth.primary) || '#059669',
                    backgroundColor: (window.CHART_THEME && window.CHART_THEME.netWorth.primaryFill) || 'rgba(5, 150, 105, 0.15)',
                    fill: true, tension: 0.35, borderWidth: 3, pointRadius: 3, pointHoverRadius: 6,
                },
                {
                    label: compHistChartLabel,
                    data: equityValues,
                    borderColor: (window.CHART_THEME && window.CHART_THEME.netWorth.equity) || '#0284C7',
                    backgroundColor: (window.CHART_THEME && window.CHART_THEME.netWorth.equityFill) || 'rgba(2, 132, 199, 0.08)',
                    borderDash: [5, 4], fill: true, tension: 0.35, borderWidth: 2, pointRadius: 2, pointHoverRadius: 5,
                },
                {
                    label: 'Liquid & Public Investments',
                    data: liquidValues,
                    borderColor: (window.CHART_THEME && window.CHART_THEME.netWorth.liquid) || '#1D4ED8',
                    backgroundColor: 'transparent', fill: false, tension: 0.35, borderWidth: 2, pointRadius: 2, pointHoverRadius: 5,
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { position: 'top', labels: { color: '#94A3B8', font: { family: 'Inter', size: 11 } } },
                tooltip: {
                    callbacks: { label: (ctx) => ` ${ctx.dataset.label}: ${fmtShortCurrency(ctx.raw)} (${fmtCurrency(ctx.raw, 0)})` }
                }
            },
            scales: {
                x: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94A3B8' } },
                y: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94A3B8', callback: (v) => fmtShortCurrency(v) } }
            }
        }
    });
}

function buildProjectionSeriesForGranularity(projections, gran) {
    if (!projections || !projections.length || !gran || gran === 'annual') {
        return projections || [];
    }
    const stepsPerYear = gran === 'quarterly' ? 4 : (gran === 'monthly' ? 12 : 1);
    if (stepsPerYear === 1 || projections.length < 2) {
        return projections;
    }
    const result = [];
    for (let i = 0; i < projections.length - 1; i++) {
        const p0 = projections[i];
        const p1 = projections[i + 1];
        const yr = Number(p0.year);
        const nw0 = Number(p0.total_true_net_worth || ((p0.true_net_equity || 0) + (p0.non_equity_net_worth || 0)));
        const nw1 = Number(p1.total_true_net_worth || ((p1.true_net_equity || 0) + (p1.non_equity_net_worth || 0)));
        const eq0 = Number(p0.true_net_equity || 0);
        const eq1 = Number(p1.true_net_equity || 0);
        const ne0 = Number(p0.non_equity_net_worth || 0);
        const ne1 = Number(p1.non_equity_net_worth || 0);
        const uv0 = Number(p0.unvested_net_value || 0);
        const uv1 = Number(p1.unvested_net_value || 0);

        for (let s = 0; s < stepsPerYear; s++) {
            const frac = s / stepsPerYear;
            const label = gran === 'quarterly'
                ? `${yr} Q${s + 1}`
                : `${yr}-${String(s + 1).padStart(2, '0')}`;
            result.push({
                year: yr,
                label: label,
                total_true_net_worth: Math.round(nw0 + (nw1 - nw0) * frac),
                true_net_equity: Math.round(eq0 + (eq1 - eq0) * frac),
                non_equity_net_worth: Math.round(ne0 + (ne1 - ne0) * frac),
                unvested_net_value: Math.round(uv0 + (uv1 - uv0) * frac),
            });
        }
    }
    const last = projections[projections.length - 1];
    const lastYr = Number(last.year);
    const lastLabel = gran === 'quarterly' ? `${lastYr} Q1` : `${lastYr}-01`;
    result.push({
        year: lastYr,
        label: lastLabel,
        total_true_net_worth: Number(last.total_true_net_worth || ((last.true_net_equity || 0) + (last.non_equity_net_worth || 0))),
        true_net_equity: Number(last.true_net_equity || 0),
        non_equity_net_worth: Number(last.non_equity_net_worth || 0),
        unvested_net_value: Number(last.unvested_net_value || 0),
    });
    return result;
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        renderGranularAllocationChart,
        renderProjectionChart,
        renderHistoricalChart,
        buildProjectionSeriesForGranularity,
    });
}
