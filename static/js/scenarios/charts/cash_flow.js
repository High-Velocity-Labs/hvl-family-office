/**
 * Lens 2: Annual Cash Flow Waterfall & Layered Stack
 */
import { state, escapeHtml, fmtCurrency, fmtShortCurrency } from '../state.js';
import { renderGraphScenarioToggles, updateChartWindowContinuous } from './common.js';
import { getTimelineRange, inspectTimelineYear, updateScrubberNeedle } from '../scrubber.js';
import { renderCashFlowSankey, hideCashFlowSankey } from './cash_flow_sankey.js';

let cfSubMode = 'sankey'; // 'sankey' (default) | 'timeline'
export function getCfSubMode() { return cfSubMode; }
export function setCfSubMode(mode) { cfSubMode = mode; }

export function renderCashFlowWaterfallLens(ctx, togglesContainer, captionEl, smooth = false) {
    if (captionEl) {
        if (cfSubMode === 'sankey') {
            captionEl.textContent = 'Single-Year Cash Flow Sankey: Tracing annual income streams (earned salary, equity vests, Social Security, event inflows) through total household cash flow into baseline living, mortgage debt service, taxes, education, gifting, and net portfolio savings.';
        } else {
            captionEl.textContent = 'Layered Cash Flow (Inflows vs. Outflows): Green bars show Earned Salary Surplus, Social Security, and Windfalls. Stacked colored bars show Outflow layers (Core Living, Travel Go-Go, Family Gifting, Debt, and Capital Events). The dark navy line tracks Net Annual Cash Flow across historical actuals (2018–2025) and projections.';
        }
    }

    if (!state.scenariosData) return;

    if (togglesContainer) {
        togglesContainer.innerHTML = '';
        renderGraphScenarioToggles(togglesContainer);

        const sep = document.createElement('span');
        sep.style.cssText = 'border-left: 1px solid var(--border-subtle); margin: 0 4px; height: 16px; align-self: center;';
        togglesContainer.appendChild(sep);

        const modeToggle = document.createElement('div');
        modeToggle.className = 'pill-group';
        modeToggle.style.cssText = 'display: inline-flex; align-items: center; gap: 3px; background: var(--bg-surface); padding: 2px; border-radius: 6px; border: 1px solid var(--border-subtle);';
        modeToggle.innerHTML = `
            <button type="button" class="pill-btn ${cfSubMode === 'sankey' ? 'active' : ''}" data-cf-mode="sankey" style="font-size: 0.6875rem; padding: 2px 8px;">Single-Year Sankey</button>
            <button type="button" class="pill-btn ${cfSubMode === 'timeline' ? 'active' : ''}" data-cf-mode="timeline" style="font-size: 0.6875rem; padding: 2px 8px;">Timeline Bars</button>
        `;
        modeToggle.querySelectorAll('[data-cf-mode]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const m = btn.getAttribute('data-cf-mode');
                if (m === cfSubMode) return;
                cfSubMode = m;
                renderCashFlowWaterfallLens(ctx, togglesContainer, captionEl, smooth);
            });
        });
        togglesContainer.appendChild(modeToggle);

        if (cfSubMode === 'timeline') {
            const sep2 = document.createElement('span');
            sep2.style.cssText = 'border-left: 1px solid var(--border-subtle); margin: 0 4px; height: 16px; align-self: center;';
            togglesContainer.appendChild(sep2);

            const flowBadges = document.createElement('span');
            flowBadges.style.cssText = 'display: inline-flex; gap: 6px; flex-wrap: wrap; align-items: center;';
            flowBadges.innerHTML = `
                <span class="badge" style="background: rgba(5, 150, 105, 0.14); color: #059669;">Salary Savings</span>
                <span class="badge" style="background: rgba(13, 148, 136, 0.14); color: #0D9488;">Social Security</span>
                <span class="badge" style="background: rgba(29, 78, 216, 0.14); color: #1D4ED8;">Core Living</span>
                <span class="badge" style="background: rgba(217, 119, 6, 0.14); color: #D97706;">Travel Go-Go</span>
                <span class="badge" style="background: rgba(192, 108, 38, 0.14); color: #C06C26;">Family Gifting</span>
                <span class="badge" style="background: rgba(199, 93, 110, 0.15); color: #C75D6E;">Event Spikes</span>
                <span class="badge" style="background: rgba(2, 132, 199, 0.14); color: #0284C7;">Mortgage Debt</span>
                <span class="badge" style="background: rgba(10, 30, 56, 0.12); color: #0A1E38; border: 1px solid rgba(10, 30, 56, 0.28);">━ Net Cash Flow</span>
            `;
            togglesContainer.appendChild(flowBadges);
        }
    }

    if (cfSubMode === 'sankey') {
        renderCashFlowSankey(ctx, togglesContainer, captionEl);
        return;
    }
    hideCashFlowSankey();

    const rawSeries = (state.scenariosData.scenario_cash_flows && state.selectedScenarioId && state.scenariosData.scenario_cash_flows[state.selectedScenarioId])
        || state.scenariosData.active_cash_flow_series
        || [];
    const hist = state.scenariosData.historical_cash_flow_series || [];
    const series = [...hist, ...rawSeries];
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
    const cf = theme ? theme.cashFlow : null;
    const netFlowColor = (cf && cf.netFlow) || '#0A1E38';

    cfChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [
                // Inflow Bars (Group 1 - Emerald & Teal)
                {
                    label: 'Salary Savings Surplus',
                    data: salaryData,
                    backgroundColor: cf ? cf.salary : '#059669',
                    stack: 'inflows',
                    order: 2,
                },
                {
                    label: 'Social Security',
                    data: ssData,
                    backgroundColor: cf ? cf.socialSecurity : '#047857',
                    stack: 'inflows',
                    order: 2,
                },
                {
                    label: 'Liquidity Windfalls',
                    data: eventInflows,
                    backgroundColor: cf ? cf.windfalls : 'rgba(5, 150, 105, 0.75)',
                    stack: 'inflows',
                    order: 2,
                },
                // Stacked Outflow Layers (Group 2 - HVL Approved Spectrum)
                {
                    label: 'Core Living Baseline',
                    data: livingData,
                    backgroundColor: cf ? cf.living : '#1D4ED8',
                    stack: 'outflows',
                    order: 2,
                },
                {
                    label: 'Travel Go-Go Curve',
                    data: travelData,
                    backgroundColor: cf ? cf.travel : '#D97706',
                    stack: 'outflows',
                    order: 2,
                },
                {
                    label: 'Family Gifting Program',
                    data: giftingData,
                    backgroundColor: cf ? cf.gifting : '#0D9488',
                    stack: 'outflows',
                    order: 2,
                },
                {
                    label: 'Event Outflows & Aviation',
                    data: eventOutflows,
                    backgroundColor: cf ? cf.aviation : '#C75D6E',
                    stack: 'outflows',
                    order: 2,
                },
                {
                    label: 'Mortgage Debt Service',
                    data: mortgageData,
                    backgroundColor: cf ? cf.mortgage : '#0284C7',
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
                    pointBorderColor: '#FFFFFF',
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
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: '#94A3B8', maxRotation: 0 }
                },
                y: {
                    stacked: true,
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: {
                        color: '#94A3B8',
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

