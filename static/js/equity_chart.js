/**
 * Equity 409A Stock Valuation Chart & Vesting Calculation Module
 * Extracted from static/js/equity.js for modular separation of Chart.js rendering and vesting math.
 */

function syncGraphModeUI() {
    const btnFmv = document.getElementById('btn-equity-graph-fmv');
    const btnTime = document.getElementById('btn-equity-graph-time');
    const btnCurve = document.getElementById('btn-equity-graph-curve');
    if (btnFmv) btnFmv.classList.toggle('active', equityGraphMode === 'fmv');
    if (btnTime) btnTime.classList.toggle('active', equityGraphMode === 'trajectory');
    if (btnCurve) btnCurve.classList.toggle('active', equityGraphMode === 'curve');

    const explainer = document.getElementById('equity-curve-explainer');
    if (explainer) explainer.style.display = equityGraphMode === 'curve' ? 'block' : 'none';
}

function setGraphMode(mode) {
    equityGraphMode = mode;
    syncGraphModeUI();
    updateGraphHeaderAndStats(currentEquityData, currentSimulatedPrice);
    renderEquityStockValueGraph(currentSimulatedPrice, currentIncludeWaTax, currentEquityData);
}

/**
 * Renders the Estimated Stock Value Graph
 * Supports 409A FMV History & Projections mode, 5-Year Trajectory mode,
 * and Valuation Sensitivity Curve mode.
 */
function renderEquityStockValueGraph(currentPrice, includeWaTax, activeEquity) {
    const canvas = document.getElementById('chart-equity-stock-value');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (equityStockChart) equityStockChart.destroy();

    if (equityGraphMode === 'fmv') {
        const historyItems = (equityFmvHistoryData && equityFmvHistoryData.length > 0)
            ? equityFmvHistoryData
            : (activeEquity && activeEquity.fmv_history && activeEquity.fmv_history.length > 0)
                ? activeEquity.fmv_history
                : DEFAULT_FMV_HISTORY;

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

        equityStockChart = new Chart(ctx, {
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
                                    const filteredForUnits = (activeEquityCompanyId && activeEquityCompanyId !== 'all')
                                        ? equityGrantsData.filter(g => Number(g.company_id) === Number(activeEquityCompanyId))
                                        : equityGrantsData;
                                    const vestedUnits = getVestedUnitsAsOfDate(item.date, filteredForUnits);
                                    const grossEst = priceVal * vestedUnits;
                                    const grossLabel = (activeEquityCompanyId === 'all') ? 'Est. Vested Portfolio Gross' : 'Est. Vested Gross';
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

    if (equityGraphMode === 'trajectory' && equityProjectionsData.length > 0) {
        equityStockChart = renderTrajectoryChart(ctx, equityProjectionsData);
        return;
    }

    // Mode 3: Valuation Sensitivity Curve
    const allGrants = (equityGrantsData && equityGrantsData.length > 0)
        ? equityGrantsData
        : ((activeEquity && activeEquity.grants) ? activeEquity.grants : []);
    const grants = (activeEquityCompanyId && activeEquityCompanyId !== 'all')
        ? allGrants.filter(g => Number(g.company_id) === Number(activeEquityCompanyId))
        : allGrants;

    equityStockChart = renderCurveChart(ctx, grants, currentPrice, activeEquity, includeWaTax);
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        syncGraphModeUI,
        setGraphMode,
        renderEquityStockValueGraph,
    });
}
