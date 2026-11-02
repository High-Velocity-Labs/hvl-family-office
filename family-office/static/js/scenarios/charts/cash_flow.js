/**
 * Lens 2: Annual Cash Flow Waterfall & Layered Stack
 */
import { state, fmtCurrency, fmtShortCurrency, getGraphScenarioId, setGraphScenarioId } from '../state.js';
import { renderGraphScenarioToggles, updateChartWindowContinuous, setChartLoader } from './common.js';
import { planSeries } from '../plan_series.js';
import { getTimelineRange, inspectTimelineYear, updateScrubberNeedle } from '../scrubber.js';
import { loadChartToggles } from './chart_chrome.js';
import { renderCashFlowSankey, hideCashFlowSankey } from './cash_flow_sankey.js';

let cfSubMode = 'sankey'; // 'sankey' (default) | 'timeline'
export function getCfSubMode() { return cfSubMode; }
export function setCfSubMode(mode) { cfSubMode = mode; }

export function renderCashFlowWaterfallLens(ctx, togglesContainer, captionEl, smooth = false) {
    if (captionEl) {
        if (cfSubMode === 'sankey') {
            captionEl.textContent = 'Single-Year Cash Flow Sankey: Tracing annual income streams (earned salary, equity vests, Social Security, event inflows) through total household cash flow into baseline living, mortgage debt service, taxes, education, gifting, and net portfolio savings.';
        } else {
            captionEl.textContent = 'Layered Cash Flow (Inflows vs. Outflows): Green bars show Earned Salary Surplus, Social Security, and Windfalls. Stacked colored bars show Outflow layers (Core Living, Travel Go-Go, Family Gifting, Debt, and Capital Events). The dark navy line tracks Net Annual Cash Flow across historical actuals and projections.';
        }
    }

    if (!state.scenariosData) return;
    const effectiveScenId = getGraphScenarioId('cashflow');

    if (togglesContainer) {
        togglesContainer.replaceChildren();
        renderGraphScenarioToggles(togglesContainer, {
            graphKey: 'cashflow',
            selectedScenarioId: effectiveScenId,
            onSelect: (scenId) => {
                setGraphScenarioId('cashflow', scenId);
                renderCashFlowWaterfallLens(ctx, togglesContainer, captionEl, true);
            }
        });

        loadChartToggles(togglesContainer, {
            lens: 'cashflow',
            mode: cfSubMode,
            modeAttr: 'data-cf-mode',
            onMode: (m) => {
                if (m === cfSubMode) return;
                cfSubMode = m;
                renderCashFlowWaterfallLens(ctx, togglesContainer, captionEl, smooth);
            }
        });
    }

    if (cfSubMode === 'sankey') {
        renderCashFlowSankey(ctx, togglesContainer, captionEl);
        return;
    }
    hideCashFlowSankey();

    const rawSeries = planSeries('scenario_cash_flows', effectiveScenId);
    setChartLoader('cashflow-chart-loading', rawSeries === null);
    const hist = state.scenariosData.historical_cash_flow_series || [];
    const series = [...hist, ...(rawSeries || [])];
    const { minYear, maxYear } = getTimelineRange();

    const labels = series.map(s => s.year);

    // Stacked Outflow Layers (Negative / Stacking)
    const livingData = series.map(s => s.living_core);
    const travelData = series.map(s => s.travel_gogo);
    const giftingData = series.map(s => s.gifting);
    const eventOutflows = series.map(s => s.events_outflow);
    const mortgageData = series.map(s => s.mortgage_debt_service);

    // Inflow Layers (Positive)
    const salaryData = series.map(s => s.salary_savings);
    const ssData = series.map(s => s.social_security);
    const eventInflows = series.map(s => s.event_inflows);

    // Net Cash Flow Line
    const netFlowData = series.map(s => s.net_cash_flow);

    const yearYBounds = new Map();
    for (let i = 0; i < series.length; i++) {
        const inflowTot = (salaryData[i] || 0) + (ssData[i] || 0) + (eventInflows[i] || 0);
        const outflowTot = (livingData[i] || 0) + (travelData[i] || 0) + (giftingData[i] || 0) + (eventOutflows[i] || 0) + (mortgageData[i] || 0);
        const nf = netFlowData[i] || 0;
        const yrMax = Math.max(inflowTot, outflowTot, nf);
        const yrMin = Math.min(0, nf);
        yearYBounds.set(series[i].year, { min: yrMin, max: yrMax });
    }

    const canvas = ctx?.canvas;
    const isSharedCanvas = canvas?.id === 'chart-scenarios-comparison';
    let cfChart = isSharedCanvas ? state.scenarioComparisonChart : state.cashFlowChart;
    if (cfChart && (cfChart.canvas !== canvas || !document.body.contains(cfChart.canvas) || cfChart.config.type !== 'bar')) {
        cfChart.destroy();
        cfChart = null;
        if (isSharedCanvas) state.scenarioComparisonChart = null;
        else state.cashFlowChart = null;
    }

    if (cfChart && cfChart.config.type === 'bar') {
        cfChart.data.labels = labels;
        if (cfChart.data.datasets && cfChart.data.datasets.length >= 8) {
            cfChart._cashFlowSeries = series;
            cfChart._yearYBounds = yearYBounds;
            cfChart._minDataYear = series.length ? series[0].year : 2018;
            cfChart._maxDataYear = series.length ? series[series.length - 1].year : 2060;
            cfChart.data.datasets[0].data = salaryData;
            cfChart.data.datasets[1].data = ssData;
            cfChart.data.datasets[2].data = eventInflows;
            cfChart.data.datasets[3].data = livingData;
            cfChart.data.datasets[4].data = travelData;
            cfChart.data.datasets[5].data = giftingData;
            cfChart.data.datasets[6].data = eventOutflows;
            cfChart.data.datasets[7].data = mortgageData;
            if (cfChart.data.datasets[8]) cfChart.data.datasets[8].data = netFlowData;
            updateChartWindowContinuous(cfChart, minYear, maxYear, smooth);
            cfChart.update(smooth ? 'none' : undefined);
            return;
        }
    }

    const theme = window.CHART_THEME;
    const cf = theme.cashFlow;
    const netFlowColor = cf.netFlow;

    cfChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [
                // Inflow Bars (Group 1 - Emerald & Teal)
                {
                    label: 'Salary Savings Surplus',
                    data: salaryData,
                    backgroundColor: cf.salary,
                    stack: 'inflows',
                    order: 2,
                },
                {
                    label: 'Social Security',
                    data: ssData,
                    backgroundColor: cf.socialSecurity,
                    stack: 'inflows',
                    order: 2,
                },
                {
                    label: 'Liquidity Windfalls',
                    data: eventInflows,
                    backgroundColor: cf.windfalls,
                    stack: 'inflows',
                    order: 2,
                },
                // Stacked Outflow Layers (Group 2 - HVL Approved Spectrum)
                {
                    label: 'Core Living Baseline',
                    data: livingData,
                    backgroundColor: cf.living,
                    stack: 'outflows',
                    order: 2,
                },
                {
                    label: 'Travel Go-Go Curve',
                    data: travelData,
                    backgroundColor: cf.travel,
                    stack: 'outflows',
                    order: 2,
                },
                {
                    label: 'Family Gifting Program',
                    data: giftingData,
                    backgroundColor: cf.gifting,
                    stack: 'outflows',
                    order: 2,
                },
                {
                    label: 'Event Outflows & Aviation',
                    data: eventOutflows,
                    backgroundColor: cf.aviation,
                    stack: 'outflows',
                    order: 2,
                },
                {
                    label: 'Mortgage Debt Service',
                    data: mortgageData,
                    backgroundColor: cf.mortgage,
                    stack: 'outflows',
                    order: 2,
                },
                // Net Cashflow overlay line (drawn on top of bars via order: 0)
                {
                    type: 'line',
                    label: 'Net Cash Flow',
                    data: netFlowData,
                    borderColor: netFlowColor,
                    backgroundColor: netFlowColor,
                    pointBackgroundColor: netFlowColor,
                    pointBorderColor: theme.onFill,
                    pointBorderWidth: 1.5,
                    borderWidth: 3,
                    pointRadius: 3,
                    pointHoverRadius: 5,
                    fill: false,
                    tension: 0.2,
                    order: 0,
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            onClick: (event, elements, chart) => {
                if (window._suppressChartClick) return;
                if (elements && elements.length > 0) {
                    const idx = elements[0].index;
                    const item = (chart._cashFlowSeries || series)[idx];
                    if (item && !item.is_historical) {
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
                            const s = (cfChart?._cashFlowSeries || series)[items[0].dataIndex];
                            if (!s) return '';
                            const pName = (state.scenariosData && state.scenariosData.primary_name) || 'Primary';
                            const sName = (state.scenariosData && state.scenariosData.spouse_name) || 'Spouse';
                            if (s.is_historical) {
                                return `Year ${s.year} (Historical Actuals) — ${pName} (Age ${s.age_primary}) & ${sName} (Age ${s.age_spouse})`;
                            }
                            return `Year ${s.year} — ${pName} (Age ${s.age_primary}) & ${sName} (Age ${s.age_spouse})`;
                        },
                        label: (ctx) => `${ctx.dataset.label}: ${fmtShortCurrency(ctx.raw)}`,
                        afterBody: (items) => {
                            if (!items || !items.length) return '';
                            const s = (cfChart?._cashFlowSeries || series)[items[0].dataIndex];
                            if (!s) return '';
                            const lines = [
                                `────────────────────────`,
                                ...(s.gross_compensation && s.income_tax_haircut ? [`Gross Comp:     ${fmtShortCurrency(s.gross_compensation)} (Tax: -${fmtShortCurrency(s.income_tax_haircut)})`] : []),
                                `Total Inflows:  +${fmtShortCurrency(s.total_inflow)}`,
                                `Total Outflows: -${fmtShortCurrency(s.total_outflow)}`,
                                `Net Cash Flow:  ${s.net_cash_flow >= 0 ? '+' : ''}${fmtShortCurrency(s.net_cash_flow)}`
                            ];
                            if (s.is_historical) {
                                lines.push(`(Historical actual compensation & living spending)`);
                            }
                            return lines.join('\n');
                        }
                    }
                }
            },
            scales: {
                x: {
                    stacked: true,
                    ticks: { maxRotation: 0 }
                },
                y: {
                    stacked: true,
                    ticks: {
                        callback: (v) => fmtShortCurrency(v)
                    }
                }
            }
        }
    });
    if (isSharedCanvas) state.scenarioComparisonChart = cfChart;
    else state.cashFlowChart = cfChart;
    cfChart._cashFlowSeries = series;
    cfChart._yearYBounds = yearYBounds;
    cfChart._minDataYear = series.length ? series[0].year : 2018;
    cfChart._maxDataYear = series.length ? series[series.length - 1].year : 2060;
    updateChartWindowContinuous(cfChart, minYear, maxYear, false);
    cfChart.update('none');
}

export { renderCashFlowWaterfallLens as renderCashFlowLens };

