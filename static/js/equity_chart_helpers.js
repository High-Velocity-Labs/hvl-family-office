/**
 * Equity Chart Helpers & Sensitivity / Trajectory Chart Renderers
 * Extracted from static/js/equity_chart.js for modular separation.
 */

var equityStockChart = null;
var equityGraphMode = 'fmv'; // 'fmv' (default), 'trajectory', or 'curve'
var currentSimulatedPrice = 0;
var currentIncludeWaTax = false;
var equityGrantsData = [];
var equityProjectionsData = [];
var equityFmvHistoryData = [];
var currentEquityData = null;
var debounceScenarioTimer = null;
var activeEquityCompanyId = null;
var currentPortfolioMultiple = 1.0;
var equityCompaniesList = [];

var DEFAULT_FMV_HISTORY = [];

function setStat(labelEl, labelText, valEl, valText, color, subEl, subText) {
    if (labelEl) labelEl.textContent = labelText;
    if (valEl) {
        valEl.textContent = valText;
        if (color) valEl.style.color = color;
    }
    if (subEl) subEl.textContent = subText;
}

function getVestedUnitsAsOfDate(dateStr, grants) {
    if (!grants || grants.length === 0) return 0;
    const targetTime = new Date(dateStr).getTime();
    if (isNaN(targetTime)) return 0;
    let totalUnits = 0;

    grants.forEach(g => {
        if (!g.grant_date) return;
        const gTime = new Date(g.grant_date).getTime();
        if (isNaN(gTime) || targetTime < gTime) return;

        let vTime;
        if (g.fully_vested_date) {
            vTime = new Date(g.fully_vested_date).getTime();
        } else {
            const d = new Date(g.grant_date);
            d.setFullYear(d.getFullYear() + 4);
            vTime = d.getTime();
        }

        const vestedOptions = Number(g.unexercised_options || g.unexercised_vested || 0);
        const ownedShares = Number(g.owned_shares || g.owned_exercised || 0);
        const unvestedOptions = Number(g.unvested_options || g.unvested || 0);
        const activeGrantUnits = vestedOptions + ownedShares + unvestedOptions;

        if (targetTime >= vTime) {
            totalUnits += (vestedOptions + ownedShares);
        } else {
            const totalDuration = Math.max(1, vTime - gTime);
            const elapsed = Math.max(0, targetTime - gTime);
            const vestFraction = Math.min(1.0, elapsed / totalDuration);
            totalUnits += Math.round(vestFraction * activeGrantUnits);
        }
    });

    return totalUnits;
}

function updateGraphHeaderAndStats(equity, currentPrice) {
    const v = equity || currentEquityData || {};
    const isConsolidated = (activeEquityCompanyId === 'all');
    const comp = !isConsolidated ? equityCompaniesList.find(c => Number(c.company_id) === Number(activeEquityCompanyId)) : null;
    const compName = isConsolidated ? 'Portfolio' : ((comp && comp.company_name) || (v && v.company_name) || 'Company');
    const price = currentPrice || currentSimulatedPrice || (v && v.share_price) || 0;

    const titleEl = document.getElementById('equity-graph-title');
    const subtitleEl = document.getElementById('equity-graph-subtitle');
    const l1 = document.getElementById('graph-stat-label-1');
    const s1 = document.getElementById('graph-stat-gross');
    const sub1 = document.getElementById('graph-stat-sub-1');
    const l2 = document.getElementById('graph-stat-label-2');
    const s2 = document.getElementById('graph-stat-net');
    const sub2 = document.getElementById('graph-stat-sub-2');
    const l3 = document.getElementById('graph-stat-label-3');
    const s3 = document.getElementById('graph-stat-strike');
    const sub3 = document.getElementById('graph-stat-sub-3');
    const l4 = document.getElementById('graph-stat-label-4');
    const sGrowth = document.getElementById('graph-stat-growth');
    const sub4 = document.getElementById('graph-stat-sub-4');
    const l5 = document.getElementById('graph-stat-label-5');
    const s5 = document.getElementById('graph-stat-tax');
    const sub5 = document.getElementById('graph-stat-sub-5');

    const historyItems = (equityFmvHistoryData && equityFmvHistoryData.length > 0)
        ? equityFmvHistoryData
        : ((v && v.fmv_history && v.fmv_history.length > 0) ? v.fmv_history : []);
    const firstFmv = historyItems.length > 0 ? historyItems[0] : null;

    const selExpectedGrowth = document.getElementById('select-equity-expected-growth');
    const growthRate = selExpectedGrowth ? parseFloat(selExpectedGrowth.value) : 0.105;
    const growthPctStr = `+${(growthRate * 100).toFixed(1)}%/yr`;
    const isBaseline = Math.abs(growthRate - 0.105) < 0.001;
    const hasEquityData = price > 0 || (equityCompaniesList && equityCompaniesList.length > 0) || (equityGrantsData && equityGrantsData.length > 0) || historyItems.length > 0;

    const grossVal = isConsolidated ? (v.nominal_gross_equity_value || v.total_gross_equity_value || 0) : (v.company_nominal_gross_equity_value !== undefined ? v.company_nominal_gross_equity_value : (v.company_gross_equity_value || v.total_gross_equity_value || 0));
    const netVal = isConsolidated ? (v.true_net_post_tax_value || 0) : (v.company_true_net_post_tax_value !== undefined ? v.company_true_net_post_tax_value : (v.true_net_post_tax_value || 0));
    const strikeVal = isConsolidated ? (v.total_strike_cost_needed || 0) : (v.company_strike_cost_needed !== undefined ? v.company_strike_cost_needed : (v.total_strike_cost_needed || 0));
    const taxVal = isConsolidated ? (v.total_tax_drag || 0) : (v.company_tax_drag !== undefined ? v.company_tax_drag : (v.total_tax_drag || 0));

    if (equityGraphMode === 'fmv') {
        if (titleEl) titleEl.textContent = `${compName} 409A Fair Market Value (FMV) Over Time & Projections`;
        if (subtitleEl) {
            subtitleEl.textContent = !hasEquityData ? 'Historical 409A valuation path by date with forward compound projections.'
                : (isConsolidated ? `Historical 409A valuation path for primary holdings with forward compound projections @ ${growthPctStr}.`
                : `Historical 409A valuation path for ${compName} with forward compound projections @ ${growthPctStr} (${isBaseline ? 'Forecasting Baseline' : 'Selected Growth'}).`);
        }
        setStat(l1, firstFmv ? `INITIAL 409A (${firstFmv.date || ''}):` : 'INITIAL 409A:', s1, firstFmv ? fmtCurrency(firstFmv.price, 2) : '--', '#3B82F6', sub1, firstFmv ? (firstFmv.notes || 'Initial recorded grant') : 'Historical baseline');
        setStat(l2, isConsolidated ? 'SIMULATED MULTIPLE:' : 'CURRENT 409A FMV:', s2, isConsolidated ? `${currentPortfolioMultiple.toFixed(2)}x` : (price > 0 ? fmtCurrency(price, 2) : '--'), '#10B981', sub2, isConsolidated ? 'Applied across holdings' : 'Verified 409A baseline');
        setStat(l4, 'EXPECTED FUTURE GROWTH:', sGrowth, hasEquityData ? growthPctStr : '--', 'var(--brand-primary, #0265E8)', sub4, hasEquityData ? (isBaseline ? 'Forecasting Baseline' : 'Selected Scenario Rate') : 'No 409A data recorded');
        const proj5yr = price * Math.pow(1 + growthRate, 5);
        const gainPct = ((Math.pow(1 + growthRate, 5) - 1) * 100).toFixed(1);
        setStat(l5, 'PROJECTED 5-YR FMV:', s5, price > 0 ? fmtCurrency(proj5yr, 2) : '--', '#10B981', sub5, price > 0 ? `+${gainPct}% gain @ ${growthPctStr}` : '--');
    } else if (equityGraphMode === 'trajectory') {
        if (titleEl) titleEl.textContent = `${compName} Multi-Year Equity & Tax Trajectory`;
        if (subtitleEl) subtitleEl.textContent = `Projected gross, net post-tax, and unvested option transitions assuming ${growthPctStr} annual growth.`;
        setStat(l1, 'EST. GROSS VALUE:', s1, fmtCurrency(grossVal, 0), '#3B82F6', sub1, 'Vested equity only');
        setStat(l2, 'TRUE NET PROCEEDS:', s2, fmtCurrency(netVal, 0), '#10B981', sub2, 'Take-home liquidity');
        setStat(l3, 'STRIKE CAPITAL REQ:', s3, fmtCurrency(strikeVal, 0), '#F59E0B', sub3, 'Exercise obligation');
        setStat(l4, 'EXPECTED GROWTH MODEL:', sGrowth, hasEquityData ? growthPctStr : '--', 'var(--brand-primary, #0265E8)', sub4, hasEquityData ? (isBaseline ? 'Forecasting Baseline' : 'Selected Growth Preset') : 'No 409A data recorded');
        setStat(l5, 'TAX LIABILITY DRAG:', s5, fmtCurrency(taxVal, 0), '#EF4444', sub5, 'Ordinary + LTCG + State');
    } else { // 'curve'
        if (titleEl) titleEl.textContent = `${compName} Valuation Sensitivity Curve`;
        if (subtitleEl) subtitleEl.textContent = `Net liquidation proceeds vs. total tax liability across potential ${compName} valuation scenarios.`;
        setStat(l1, 'SIMULATED GROSS:', s1, fmtCurrency(grossVal, 0), '#3B82F6', sub1, 'At slider level');
        setStat(l2, 'SIMULATED NET:', s2, fmtCurrency(netVal, 0), '#10B981', sub2, 'Take-home liquidity');
        setStat(l3, 'TOTAL STRIKE COST:', s3, fmtCurrency(strikeVal, 0), '#F59E0B', sub3, 'Exercise obligation');
        setStat(l4, 'BASELINE GROWTH:', sGrowth, hasEquityData ? '+10.5% / yr' : '--', '#8B5CF6', sub4, hasEquityData ? 'Forecasting Baseline' : 'No 409A data recorded');
        setStat(l5, 'TOTAL TAX DRAG:', s5, fmtCurrency(taxVal, 0), '#EF4444', sub5, 'Federal + WA SB 6346');
    }
}

function renderTrajectoryChart(ctx, equityProjectionsData) {
    const labels = equityProjectionsData.map(p => `Year ${p.year}`);
    const grossData = equityProjectionsData.map(p => p.gross_equity);
    const netData = equityProjectionsData.map(p => p.true_net_equity);
    const taxData = equityProjectionsData.map(p => p.total_tax_drag);
    const unvestedData = equityProjectionsData.map(p => p.unvested_net_value || 0);

    const theme = window.CHART_THEME;
    return new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Gross Stock & Option Value',
                    data: grossData,
                    borderColor: (theme && theme.equity.gross) || '#1D4ED8',
                    backgroundColor: (theme && theme.equity.grossFill) || 'rgba(29, 78, 216, 0.1)',
                    fill: true,
                    tension: 0.3,
                    borderWidth: 2,
                },
                {
                    label: 'True Net Post-Tax Proceeds (Vested)',
                    data: netData,
                    borderColor: (theme && theme.equity.net) || '#059669',
                    backgroundColor: (theme && theme.equity.netFill) || 'rgba(5, 150, 105, 0.15)',
                    fill: true,
                    tension: 0.3,
                    borderWidth: 3,
                },
                {
                    label: 'Unvested Options Value (Excluded until Vested)',
                    data: unvestedData,
                    borderColor: (theme && theme.equity.unvested) || '#D97706',
                    backgroundColor: (theme && theme.alpha(theme.amber, 0.08)) || 'rgba(217, 119, 6, 0.08)',
                    borderDash: [5, 4],
                    fill: false,
                    tension: 0.3,
                    borderWidth: 2,
                },
                {
                    label: 'Tax Drag',
                    data: taxData,
                    borderColor: (theme && theme.equity.taxDrag) || '#E11D48',
                    borderDash: [5, 5],
                    borderWidth: 2,
                    tension: 0.3,
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'top', labels: { color: '#94A3B8', font: { family: 'Inter', size: 11 } } },
                tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${fmtShortCurrency(c.raw)}` } }
            },
            scales: {
                x: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94A3B8' } },
                y: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94A3B8', callback: (v) => fmtShortCurrency(v) } }
            }
        }
    });
}

function renderCurveChart(ctx, grants, currentPrice, activeEquity, includeWaTax) {
    let totalOptions = 0.0;
    let ownedShares = 0.0;
    let strikeCost = 0.0;
    let ownedCostBasisTotal = 0.0;
    let unvestedOptions = 0.0;
    let unvestedStrikeCost = 0.0;
    grants.forEach(g => {
        const vested = Number(g.unexercised_vested || g.unexercised_options || 0);
        const owned = Number(g.owned_exercised || g.owned_shares || 0);
        const unv = Number(g.unvested || g.unvested_options || 0);
        const strike = Number(g.strike_price || 0);
        const basis = Number(g.historical_cost_basis || (strike > 0 ? strike : 0));
        totalOptions += vested;
        ownedShares += owned;
        strikeCost += (vested * strike);
        ownedCostBasisTotal += (owned * basis);
        unvestedOptions += unv;
        unvestedStrikeCost += (unv * strike);
    });

    const totalShares = totalOptions + ownedShares;
    const baseP = currentPrice || (activeEquity && activeEquity.share_price) || 2500;
    const samplePrices = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0].map(m => Math.round(baseP * m));

    const grossPoints = [];
    const netPoints = [];
    const taxPoints = [];
    const strikePoints = [];
    const unvestedPoints = [];
    samplePrices.forEach(p => {
        const gross = (totalShares * p);
        const spread = Math.max(0, (totalOptions * p) - strikeCost);
        const ownedGain = Math.max(0, (ownedShares * p) - ownedCostBasisTotal);
        const fedRate = 0.3935;
        const waRate = includeWaTax ? 0.099 : (spread > 1000000 ? 0.07 : 0.0);
        const optTax = spread * (fedRate + waRate);
        const stockTax = ownedGain * 0.238;
        const totalTax = optTax + stockTax;
        const net = (spread - optTax) + (ownedShares * p - stockTax);

        const uSpread = Math.max(0, (unvestedOptions * p) - unvestedStrikeCost);
        const uWaRate = includeWaTax ? 0.099 : (uSpread > 1000000 ? 0.07 : 0.0);
        const uTax = uSpread * (fedRate + uWaRate);
        const uNet = Math.max(0, uSpread - uTax);

        grossPoints.push(Math.round(gross));
        netPoints.push(Math.round(net));
        taxPoints.push(Math.round(totalTax));
        strikePoints.push(Math.round(strikeCost));
        unvestedPoints.push(Math.round(uNet));
    });

    const labels = samplePrices.map(p => `$${p.toLocaleString()}`);
    const theme = window.CHART_THEME;
    const grossColor = (theme && theme.equity.gross) || '#1D4ED8';
    const grossFill = (theme && theme.equity.grossFill) || 'rgba(29, 78, 216, 0.08)';
    const netColor = (theme && theme.equity.net) || '#059669';
    const netFill = (theme && theme.equity.netFill) || 'rgba(5, 150, 105, 0.12)';
    const unvestedColor = (theme && theme.equity.unvested) || '#D97706';
    const taxColor = (theme && theme.equity.taxDrag) || '#E11D48';
    const highlightColor = (theme && theme.equity.pointHighlight) || '#D97706';

    return new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Gross Stock Value ($M)',
                    data: grossPoints,
                    borderColor: grossColor,
                    backgroundColor: grossFill,
                    fill: true,
                    tension: 0.25,
                    borderWidth: 2,
                    pointRadius: samplePrices.map(p => Math.abs(p - currentPrice) < 150 ? 7 : 3),
                    pointBackgroundColor: samplePrices.map(p => Math.abs(p - currentPrice) < 150 ? highlightColor : grossColor),
                },
                {
                    label: 'True Net Post-Tax Proceeds (Vested)',
                    data: netPoints,
                    borderColor: netColor,
                    backgroundColor: netFill,
                    fill: true,
                    tension: 0.25,
                    borderWidth: 3,
                    pointRadius: samplePrices.map(p => Math.abs(p - currentPrice) < 150 ? 8 : 4),
                    pointBackgroundColor: samplePrices.map(p => Math.abs(p - currentPrice) < 150 ? highlightColor : netColor),
                },
                {
                    label: 'Unvested Options Net Value (Excluded from NW)',
                    data: unvestedPoints,
                    borderColor: unvestedColor,
                    borderDash: [5, 4],
                    borderWidth: 2,
                    tension: 0.25,
                    pointRadius: 2,
                },
                {
                    label: 'Total Tax Liability Drag',
                    data: taxPoints,
                    borderColor: taxColor,
                    borderDash: [4, 4],
                    borderWidth: 2,
                    tension: 0.25,
                    pointRadius: 2,
                },
                {
                    label: 'Strike Obligation',
                    data: strikePoints,
                    borderColor: unvestedColor,
                    borderDash: [6, 4],
                    borderWidth: 2,
                    tension: 0,
                    pointRadius: 0,
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { position: 'top', labels: { color: '#94A3B8', font: { family: 'Inter', size: 11 }, padding: 12 } },
                tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${fmtShortCurrency(c.raw)}` } }
            },
            scales: {
                x: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94A3B8', font: { size: 10 } } },
                y: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94A3B8', callback: (v) => fmtShortCurrency(v) } }
            }
        }
    });
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        setStat,
        getVestedUnitsAsOfDate,
        updateGraphHeaderAndStats,
        renderTrajectoryChart,
        renderCurveChart,
        DEFAULT_FMV_HISTORY,
    });
}
