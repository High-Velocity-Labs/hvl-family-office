/**
 * Equity 409A Stock Valuation Chart & Vesting Calculation Module
 * Extracted from static/js/equity.js for modular separation of Chart.js rendering and vesting math.
 */

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
    const v = equity || EquityState.data || {};
    const isConsolidated = (EquityState.companyId === 'all');
    const comp = !isConsolidated
        ? EquityState.companies.find(c => Number(c.company_id) === Number(EquityState.companyId))
        : null;
    const compName = isConsolidated ? 'Portfolio' : ((comp && comp.company_name) || (v && v.company_name) || 'Company');
    const price = currentPrice || EquityState.simulatedPrice || (v && v.share_price) || 0;

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

    const historyItems = (EquityState.fmvHistory && EquityState.fmvHistory.length > 0)
        ? EquityState.fmvHistory
        : ((v && v.fmv_history && v.fmv_history.length > 0) ? v.fmv_history : []);
    const firstFmv = historyItems.length > 0 ? historyItems[0] : null;

    const selExpectedGrowth = document.getElementById('select-equity-expected-growth');
    const growthRate = selExpectedGrowth ? parseFloat(selExpectedGrowth.value) : 0.105;
    const growthPctStr = `+${(growthRate * 100).toFixed(1)}%/yr`;
    const isBaseline = Math.abs(growthRate - 0.105) < 0.001;
    const hasEquityData = price > 0
        || (EquityState.companies && EquityState.companies.length > 0)
        || (EquityState.grants && EquityState.grants.length > 0)
        || historyItems.length > 0;

    const grossVal = isConsolidated ? (v.nominal_gross_equity_value || v.total_gross_equity_value || 0) : (v.company_nominal_gross_equity_value !== undefined ? v.company_nominal_gross_equity_value : (v.company_gross_equity_value || v.total_gross_equity_value || 0));
    const netVal = isConsolidated ? (v.true_net_post_tax_value || 0) : (v.company_true_net_post_tax_value !== undefined ? v.company_true_net_post_tax_value : (v.true_net_post_tax_value || 0));
    const strikeVal = isConsolidated ? (v.total_strike_cost_needed || 0) : (v.company_strike_cost_needed !== undefined ? v.company_strike_cost_needed : (v.total_strike_cost_needed || 0));
    const taxVal = isConsolidated ? (v.total_tax_drag || 0) : (v.company_tax_drag !== undefined ? v.company_tax_drag : (v.total_tax_drag || 0));

    if (EquityState.graphMode === 'fmv') {
        if (titleEl) titleEl.textContent = `${compName} 409A Fair Market Value (FMV) Over Time & Projections`;
        if (subtitleEl) {
            subtitleEl.textContent = !hasEquityData ? 'Historical 409A valuation path by date with forward compound projections.'
                : (isConsolidated ? `Historical 409A valuation path for primary holdings with forward compound projections @ ${growthPctStr}.`
                : `Historical 409A valuation path for ${compName} with forward compound projections @ ${growthPctStr} (${isBaseline ? 'Forecasting Baseline' : 'Selected Growth'}).`);
        }
        setStat(l1, firstFmv ? `INITIAL 409A (${firstFmv.date || ''}):` : 'INITIAL 409A:', s1, firstFmv ? fmtCurrency(firstFmv.price, 2) : '--', '#3B82F6', sub1, firstFmv ? (firstFmv.notes || 'Initial recorded grant') : 'Historical baseline');
        const fmvText = price > 0 ? fmtCurrency(price, 2) : '--';
        setStat(
            l2, isConsolidated ? 'SIMULATED MULTIPLE:' : 'CURRENT 409A FMV:', s2,
            isConsolidated ? `${EquityState.portfolioMultiple.toFixed(2)}x` : fmvText,
            '#10B981', sub2, isConsolidated ? 'Applied across holdings' : 'Verified 409A baseline',
        );
        setStat(l4, 'EXPECTED FUTURE GROWTH:', sGrowth, hasEquityData ? growthPctStr : '--', 'var(--brand-primary, #0265E8)', sub4, hasEquityData ? (isBaseline ? 'Forecasting Baseline' : 'Selected Scenario Rate') : 'No 409A data recorded');
        const proj5yr = price * Math.pow(1 + growthRate, 5);
        const gainPct = ((Math.pow(1 + growthRate, 5) - 1) * 100).toFixed(1);
        setStat(l5, 'PROJECTED 5-YR FMV:', s5, price > 0 ? fmtCurrency(proj5yr, 2) : '--', '#10B981', sub5, price > 0 ? `+${gainPct}% gain @ ${growthPctStr}` : '--');
    } else if (EquityState.graphMode === 'trajectory') {
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

function renderTrajectoryChart(ctx, projections) {
    const labels = projections.map(p => `Year ${p.year}`);
    const grossData = projections.map(p => p.gross_equity);
    const netData = projections.map(p => p.true_net_equity);
    const taxData = projections.map(p => p.total_tax_drag);
    const unvestedData = projections.map(p => p.unvested_net_value || 0);

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

async function renderCurveChart(ctx, currentPrice, activeEquity, includeWaTax) {
    const basePrice = currentPrice || (activeEquity && activeEquity.share_price);
    if (!(basePrice > 0)) return null;
    const params = new URLSearchParams({
        base_price: String(basePrice),
        include_wa_tax: includeWaTax ? 'true' : 'false',
    });
    const { companyId } = EquityState;
    if (companyId && companyId !== 'all') params.set('company_id', String(companyId));
    const resp = await fetch(`/api/equity/curve?${params.toString()}`);
    const curve = await resp.json();
    if (!resp.ok || !curve.success || !Array.isArray(curve.prices)) return null;
    const samplePrices = curve.prices;
    const grossPoints = curve.gross;
    const netPoints = curve.net;
    const taxPoints = curve.tax;
    const strikePoints = curve.strike;
    const unvestedPoints = curve.unvested_net;

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

function syncGraphModeUI() {
    const btnFmv = document.getElementById('btn-equity-graph-fmv');
    const btnTime = document.getElementById('btn-equity-graph-time');
    const btnCurve = document.getElementById('btn-equity-graph-curve');
    if (btnFmv) btnFmv.classList.toggle('active', EquityState.graphMode === 'fmv');
    if (btnTime) btnTime.classList.toggle('active', EquityState.graphMode === 'trajectory');
    if (btnCurve) btnCurve.classList.toggle('active', EquityState.graphMode === 'curve');

    const explainer = document.getElementById('equity-curve-explainer');
    if (explainer) explainer.style.display = EquityState.graphMode === 'curve' ? 'block' : 'none';
}

function setGraphMode(mode) {
    EquityState.setGraphMode(mode);
    syncGraphModeUI();
    updateGraphHeaderAndStats(EquityState.data, EquityState.simulatedPrice);
    renderEquityStockValueGraph(EquityState.simulatedPrice, EquityState.includeWaTax, EquityState.data);
}

/**
 * Renders the Estimated Stock Value Graph
 * Supports 409A FMV History & Projections mode, 5-Year Trajectory mode,
 * and Valuation Sensitivity Curve mode.
 */
async function renderEquityStockValueGraph(currentPrice, includeWaTax, activeEquity) {
    const canvas = document.getElementById('chart-equity-stock-value');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (EquityState.chart) EquityState.chart.destroy();
    EquityState.chart = null;

    if (EquityState.graphMode === 'fmv') {
        const historyItems = (EquityState.fmvHistory && EquityState.fmvHistory.length > 0)
            ? EquityState.fmvHistory
            : (activeEquity && activeEquity.fmv_history && activeEquity.fmv_history.length > 0)
                ? activeEquity.fmv_history
                : [];

        if (!historyItems || historyItems.length === 0) return;

        let currentIdx = -1;
        for (let i = historyItems.length - 1; i >= 0; i--) {
            if (!historyItems[i].is_projected) {
                currentIdx = i;
                break;
            }
        }
        if (currentIdx === -1) currentIdx = historyItems.length - 1;

        const labels = historyItems.map(item => item.date);

        const actualData = historyItems.map((item, idx) => {
            if (idx < currentIdx) return item.price;
            if (idx === currentIdx) return currentPrice;
            return null;
        });

        const selExpectedGrowth = document.getElementById('select-equity-expected-growth');
        const growthRate = selExpectedGrowth ? parseFloat(selExpectedGrowth.value) : 0.105;
        const growthPctStr = `+${(growthRate * 100).toFixed(1)}%/yr`;
        const isBaseline = Math.abs(growthRate - 0.105) < 0.001;

        const projGrowthData = historyItems.map((item, idx) => {
            if (idx < currentIdx) return null;
            if (idx === currentIdx) return currentPrice;
            const yearsOut = idx - currentIdx;
            return Math.round(currentPrice * Math.pow(1 + growthRate, yearsOut) * 100) / 100;
        });

        const sheetProjData = historyItems.map((item, idx) => {
            if (idx < currentIdx) return null;
            if (idx === currentIdx) return currentPrice;
            return item.price;
        });

        const pointRadii = historyItems.map((item, idx) => {
            if (idx === currentIdx) return 7;
            if (idx < currentIdx) return 4;
            return 0;
        });

        const theme = window.CHART_THEME;
        const pointBgColors = historyItems.map((item, idx) => {
            if (idx === currentIdx) return (theme && theme.amber) || '#D97706';
            return (theme && theme.equity.historicalFmv) || '#059669';
        });

        EquityState.chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Historical 409A FMV (Actual)',
                        data: actualData,
                        borderColor: (theme && theme.equity.historicalFmv) || '#059669',
                        backgroundColor: (theme && theme.equity.historicalFmvFill) || 'rgba(5, 150, 105, 0.12)',
                        fill: true,
                        tension: 0.25,
                        borderWidth: 2.5,
                        pointRadius: pointRadii,
                        pointHoverRadius: 7,
                        pointBackgroundColor: pointBgColors,
                        pointBorderColor: '#FFFFFF',
                        pointBorderWidth: 1.5,
                    },
                    {
                        label: `Forward 409A Projection (${isBaseline ? 'Baseline ' : ''}${growthPctStr} Compounding)`,
                        data: projGrowthData,
                        borderColor: (theme && theme.equity.forwardProjection) || '#7C3AED',
                        backgroundColor: (theme && theme.equity.forwardProjectionFill) || 'rgba(124, 58, 237, 0.08)',
                        fill: true,
                        borderDash: [5, 4],
                        borderWidth: 2,
                        tension: 0.25,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        pointBackgroundColor: (theme && theme.equity.forwardProjection) || '#7C3AED',
                    },
                    {
                        label: 'Historical Model Guideline (2027–2032)',
                        data: sheetProjData,
                        borderColor: (theme && theme.equity.modelGuideline) || '#D97706',
                        backgroundColor: 'transparent',
                        fill: false,
                        borderDash: [3, 3],
                        borderWidth: 2,
                        tension: 0.25,
                        pointRadius: 3,
                        pointHoverRadius: 5,
                        pointBackgroundColor: (theme && theme.equity.forwardProjection) || '#7C3AED',
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: {
                        position: 'top',
                        labels: {
                            color: '#94A3B8',
                            font: { family: 'Inter', size: 11 },
                            padding: 12
                        }
                    },
                    tooltip: {
                        callbacks: {
                            title: (tooltipItems) => {
                                const idx = tooltipItems[0].dataIndex;
                                const item = historyItems[idx];
                                const tag = item.is_projected ? ' [Projected]' : (idx === currentIdx ? ' [Current Baseline]' : '');
                                return `Valuation Date: ${item.date}${tag}`;
                            },
                            label: (c) => {
                                if (c.raw === null || c.raw === undefined) return null;
                                return ` ${c.dataset.label}: ${fmtCurrency(c.raw, 2)}`;
                            },
                            afterBody: (tooltipItems) => {
                                const idx = tooltipItems[0].dataIndex;
                                const item = historyItems[idx];
                                const lines = [];
                                if (item.percentage_increase !== null && item.percentage_increase !== undefined && idx <= currentIdx) {
                                    const sign = item.percentage_increase > 0 ? '+' : '';
                                    lines.push(`YoY Valuation Change: ${sign}${item.percentage_increase}%`);
                                }
                                const priceVal = (idx === currentIdx) ? currentPrice : item.price;
                                if (priceVal > 0) {
                                    const filteredForUnits = (EquityState.companyId && EquityState.companyId !== 'all')
                                        ? EquityState.grants.filter(
                                            g => Number(g.company_id) === Number(EquityState.companyId))
                                        : EquityState.grants;
                                    const vestedUnits = getVestedUnitsAsOfDate(item.date, filteredForUnits);
                                    const grossEst = priceVal * vestedUnits;
                                    const grossLabel = (EquityState.companyId === 'all')
                                        ? 'Est. Vested Portfolio Gross' : 'Est. Vested Gross';
                                    if (vestedUnits > 0) {
                                        lines.push(`${grossLabel} (${vestedUnits.toLocaleString()} units): ${fmtShortCurrency(grossEst)}`);
                                    } else {
                                        lines.push(`${grossLabel}: $0 (0 units vested at this date)`);
                                    }
                                }
                                return lines;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: {
                            color: '#94A3B8',
                            font: { size: 10 },
                            maxRotation: 45,
                            minRotation: 30
                        }
                    },
                    y: {
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: {
                            color: '#94A3B8',
                            callback: (v) => fmtCurrency(v, 0)
                        }
                    }
                }
            }
        });
        return;
    }

    if (EquityState.graphMode === 'trajectory' && EquityState.projections.length > 0) {
        EquityState.chart = renderTrajectoryChart(ctx, EquityState.projections);
        return;
    }

    // Mode 3: Valuation Sensitivity Curve (series computed by the server's equity engine)
    const seq = ++EquityState.renderSeq;
    const curveChart = await renderCurveChart(ctx, currentPrice, activeEquity, includeWaTax);
    if (seq !== EquityState.renderSeq) {
        if (curveChart) curveChart.destroy();
        return;
    }
    EquityState.chart = curveChart;
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        setStat,
        getVestedUnitsAsOfDate,
        updateGraphHeaderAndStats,
        renderTrajectoryChart,
        renderCurveChart,
        syncGraphModeUI,
        setGraphMode,
        renderEquityStockValueGraph,
    });
}
