/**
 * Interactive Single-Year Cash-Flow Sankey View
 * Traces annual income streams into total cash flow and out to living, debt, taxes, and savings.
 */
import { h } from './dom.js';
import { state, getGraphScenarioId, getPlanStartYear } from '../state.js';
import { inspectTimelineYear, updateScrubberNeedle } from '../scrubber.js';
import { setChartLoader } from './common.js';
import { planSeries } from '../plan_series.js';
import { getCfSubMode } from './cash_flow.js';
import { renderSankeySvg } from './cash_flow_sankey_svg.js';

let isChartTallMode = false;
let sankeyResizeObserver = null;

function getCashFlowCanvas() {
    return document.getElementById('chart-scen_chart_cashflow') || document.getElementById('chart-scenarios-comparison');
}

export function applyChartStageHeight(sankeyActive) {
    const nwStage = document.getElementById('scenarios-chart-stage');
    if (nwStage) {
        nwStage.classList.toggle('chart-stage-tall', isChartTallMode);
        const nwCard = nwStage.closest('.household-widget-card');
        if (nwCard) nwCard.classList.toggle('widget-tall', isChartTallMode);
    }
    const expandBtn = document.getElementById('btn-chart-expand-size');
    if (expandBtn) {
        expandBtn.textContent = isChartTallMode ? '⤡ Standard Height' : '⤢ Tall Chart';
        expandBtn.classList.toggle('active', isChartTallMode);
        expandBtn.setAttribute('aria-pressed', isChartTallMode ? 'true' : 'false');
    }
    const stage = document.getElementById('scenarios-cashflow-stage') || getCashFlowCanvas()?.parentElement;
    if (!stage || stage === nwStage) return;
    stage.classList.toggle('chart-stage-tall', isChartTallMode);
    stage.classList.toggle('chart-stage-sankey', Boolean(!isChartTallMode && sankeyActive));
}

export function hideCashFlowSankey() {
    const container = document.getElementById('cashflow-sankey-container');
    if (container) {
        container.hidden = true;
        container.classList.add('hidden');
    }
    const canvas = getCashFlowCanvas();
    if (canvas) {
        canvas.hidden = false;
        canvas.classList.remove('hidden');
    }
    applyChartStageHeight(false);
}

function getSeriesAndSched() {
    const effectiveScenId = getGraphScenarioId('cashflow');
    const rawSeries = planSeries('scenario_cash_flows', effectiveScenId);
    const sched = planSeries('scenario_schedules', effectiveScenId);
    const loading = rawSeries === null || sched === null;
    setChartLoader('cashflow-chart-loading', loading);
    const hist = state.scenariosData?.historical_cash_flow_series || [];
    return { series: [...hist, ...(rawSeries || [])], sched: sched || [], loading };
}

function getYearData(yr, series, sched) {
    const cf = series.find(c => c.year === yr) || {};
    let row = sched.find(r => r.year === yr);
    if (!row && yr < getPlanStartYear()) {
        const histRibbon = state.scenariosData?.historical_ribbon || [];
        const hItem = histRibbon.find(h => h.year === yr);
        if (hItem) {
            row = {
                year: yr,
                total_net_worth: hItem.true_net_worth,
                age_primary: 45 - (getPlanStartYear() - yr),
                age_spouse: 45 - (getPlanStartYear() - yr),
                longevity_status: 'historical'
            };
        }
    }
    return { cf, row: row || sched[0] || {} };
}

export function renderCashFlowSankey(ctx, togglesContainer, captionEl) {
    if (captionEl) {
        captionEl.textContent = 'Single-Year Cash Flow Sankey: Tracing annual income streams (earned salary, equity vests, Social Security, event inflows) through total household cash flow into baseline living, mortgage debt service, taxes, education, gifting, and net portfolio savings.';
    }
    const canvas = ctx?.canvas || getCashFlowCanvas();
    if (!canvas || !canvas.parentElement) return;
    canvas.hidden = true;
    canvas.classList.add('hidden');
    applyChartStageHeight(true);

    let sankeyContainer = document.getElementById('cashflow-sankey-container');
    if (!sankeyContainer || sankeyContainer.parentElement !== canvas.parentElement) {
        if (sankeyContainer) sankeyContainer.remove();
        sankeyContainer = document.createElement('div');
        sankeyContainer.id = 'cashflow-sankey-container';
        sankeyContainer.className = 'sankey-container-overlay';
        canvas.parentElement.appendChild(sankeyContainer);
    }
    sankeyContainer.hidden = false;
    sankeyContainer.classList.remove('hidden');
    renderSankeyForYear(state.inspectedYear || getPlanStartYear());
}

function setSankeyYear(newYear) {
    const { series } = getSeriesAndSched();
    const minYear = series.length ? series[0].year : 2018;
    const maxYear = series.length ? series[series.length - 1].year : 2060;
    newYear = Math.max(minYear, Math.min(maxYear, newYear));

    state.inspectedYear = newYear;
    const scrubber = document.getElementById('timeline-scrubber');
    if (scrubber) scrubber.value = newYear;
    updateScrubberNeedle(newYear);
    inspectTimelineYear(newYear);
    renderSankeyForYear(newYear);
}

export function renderSankeyForYear(yr) {
    const sankeyContainer = document.getElementById('cashflow-sankey-container');
    if (!sankeyContainer) return;
    const { series, sched, loading } = getSeriesAndSched();
    // The diagram sits above the chart's loader; step aside until the plan's series arrives (it redraws then).
    sankeyContainer.hidden = Boolean(loading);
    sankeyContainer.classList.toggle('hidden', Boolean(loading));
    if (loading) return;
    if (!series.length) {
        sankeyContainer.replaceChildren(h('div', {
            class: 'sankey-empty-msg',
            text: 'No cash flow data available.'
        }));
        return;
    }

    const minYear = series[0].year;
    const maxYear = series[series.length - 1].year;
    yr = Math.max(minYear, Math.min(maxYear, yr));
    const { cf, row } = getYearData(yr, series, sched);
    const pName = state.scenariosData?.primary_name || 'Primary';
    const sName = state.scenariosData?.spouse_name || 'Spouse';
    const pAge = cf.age_primary ?? row.age_primary ?? row.age ?? (45 + (yr - getPlanStartYear()));
    const sAge = cf.age_spouse ?? row.age_spouse ?? (45 + (yr - getPlanStartYear()));

    const startYear = getPlanStartYear();
    const retRow = sched.find(r => r.is_retired || r.is_primary_retired);
    const retYear = retRow
        ? retRow.year
        : (getPlanStartYear() + ((state.scenariosData?.primary_retirement_age || 65) - (state.scenariosData?.primary_current_age || 45)));
    const milestones = (state.scenariosData?.milestones || [])
        .filter(m => m.year >= minYear && m.year <= maxYear && m.year !== startYear && m.year !== retYear)
        .slice(0, 3);

    let toolbar = sankeyContainer.querySelector('.sankey-toolbar');
    if (!toolbar) {
        toolbar = document.createElement('div');
        toolbar.className = 'sankey-toolbar';
        sankeyContainer.appendChild(toolbar);
    }

    const jump = (year, label) => h('button', {
        type: 'button',
        class: `pill-btn sankey-jump-btn${yr === year ? ' active' : ''}`,
        'data-jump': year,
        text: label,
        onclick: () => setSankeyYear(year)
    });
    const yearLabel = (y) => `Year ${y}${y === startYear ? ' (Today)' : (y === retYear ? ' (Retire)' : '')}`;
    const yearSelect = h('select', {
        id: 'sankey-year-select',
        class: 'form-input sankey-year-select',
        onchange: (e) => setSankeyYear(parseInt(e.target.value, 10))
    }, series.map(item => h('option', { value: item.year, selected: item.year === yr, text: yearLabel(item.year) })));
    yearSelect.value = String(yr);

    toolbar.replaceChildren(
        h('div', { class: 'sankey-toolbar-left' },
            h('button', {
                type: 'button', class: 'btn btn-sm btn-secondary', id: 'sankey-prev-btn', title: 'Previous Year',
                disabled: yr <= minYear, text: '◀ Prev', onclick: () => setSankeyYear(yr - 1)
            }),
            yearSelect,
            h('button', {
                type: 'button', class: 'btn btn-sm btn-secondary', id: 'sankey-next-btn', title: 'Next Year',
                disabled: yr >= maxYear, text: 'Next ▶', onclick: () => setSankeyYear(yr + 1)
            }),
            h('span', {
                class: 'badge badge-blue sankey-year-badge',
                text: `Year ${yr} (${pName} ${pAge} / ${sName} ${sAge})`
            })),
        h('div', {
            class: 'pill-group sankey-jump-group'
        },
            jump(startYear, `Today (${startYear})`),
            retYear && retYear !== startYear && jump(retYear, `Retire (${retYear})`),
            milestones.map(m => jump(m.year, `${m.label || 'Event'} (${m.year})`)))
    );

    let chartArea = sankeyContainer.querySelector('.sankey-chart-area');
    if (!chartArea) {
        chartArea = document.createElement('div');
        chartArea.className = 'sankey-chart-area';
        sankeyContainer.appendChild(chartArea);
        if (typeof ResizeObserver !== 'undefined' && !sankeyResizeObserver) {
            sankeyResizeObserver = new ResizeObserver(() => {
                if (!sankeyContainer.hidden && !sankeyContainer.classList.contains('hidden') && getCfSubMode() === 'sankey') {
                    const curYr = state.inspectedYear || getPlanStartYear();
                    const { series: sList, sched: scList } = getSeriesAndSched();
                    if (sList.length) {
                        const { cf: cRow, row: rRow } = getYearData(curYr, sList, scList);
                        renderSankeySvg(chartArea, curYr, cRow, rRow);
                    }
                }
            });
            sankeyResizeObserver.observe(chartArea);
        }
    }
    renderSankeySvg(chartArea, yr, cf, row);
}

if (typeof document !== 'undefined' && !document._hasSankeyListeners) {
    document._hasSankeyListeners = true;
    document.addEventListener('click', (e) => {
        const expandBtn = e.target.closest('#btn-chart-expand-size');
        if (expandBtn) {
            isChartTallMode = !isChartTallMode;
            const isSankey = state.currentLens === 'cashflow' && getCfSubMode() === 'sankey';
            const card = expandBtn.closest('.household-widget-card') || document.getElementById('scenario-lens-section');
            const applyResize = () => {
                state.scenarioComparisonChart?.resize();
                state.cashFlowChart?.resize();
            };
            window.animateWidgetGridLayout(card, () => applyChartStageHeight(isSankey), applyResize);
            setTimeout(applyResize, 220);
        }
    });
    document.addEventListener('input', (e) => {
        if (e.target && e.target.id === 'timeline-scrubber') {
            const container = document.getElementById('cashflow-sankey-container');
            if (container && !container.hidden && !container.classList.contains('hidden') && getCfSubMode() === 'sankey') {
                const yr = parseInt(e.target.value, 10);
                if (!isNaN(yr)) renderSankeyForYear(yr);
            }
        }
    });
}
