/**
 * Interactive Single-Year Cash-Flow Sankey View
 * Traces annual income streams into total cash flow and out to living, debt, taxes, and savings.
 */
import { state, escapeHtml } from '../state.js';
import { inspectTimelineYear, updateScrubberNeedle } from '../scrubber.js';
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
        nwStage.style.height = isChartTallMode ? '680px' : '460px';
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
    if (isChartTallMode) {
        stage.style.height = '740px';
        stage.classList.add('chart-stage-tall');
    } else {
        stage.style.height = sankeyActive ? '560px' : '420px';
        stage.classList.remove('chart-stage-tall');
    }
}

export function hideCashFlowSankey() {
    const container = document.getElementById('cashflow-sankey-container');
    if (container) container.style.display = 'none';
    const canvas = getCashFlowCanvas();
    if (canvas) canvas.style.display = 'block';
    applyChartStageHeight(false);
}

function getSeriesAndSched() {
    const rawSeries = (state.scenariosData?.scenario_cash_flows && state.selectedScenarioId && state.scenariosData.scenario_cash_flows[state.selectedScenarioId])
        || state.scenariosData?.active_cash_flow_series || [];
    const hist = state.scenariosData?.historical_cash_flow_series || [];
    const series = [...hist, ...rawSeries];
    const sched = (state.scenariosData?.scenario_schedules && state.selectedScenarioId && state.scenariosData.scenario_schedules[state.selectedScenarioId])
        || state.scenariosData?.active_schedule || [];
    return { series, sched };
}

function getYearData(yr, series, sched) {
    const cf = series.find(c => c.year === yr) || {};
    let row = sched.find(r => r.year === yr);
    if (!row && yr < 2026) {
        const histRibbon = state.scenariosData?.historical_ribbon || [];
        const hItem = histRibbon.find(h => h.year === yr);
        if (hItem) {
            row = {
                year: yr,
                total_net_worth: hItem.true_net_worth,
                age_primary: 45 - (2026 - yr),
                age_spouse: 45 - (2026 - yr),
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
    canvas.style.display = 'none';
    applyChartStageHeight(true);

    let sankeyContainer = document.getElementById('cashflow-sankey-container');
    if (!sankeyContainer || sankeyContainer.parentElement !== canvas.parentElement) {
        if (sankeyContainer) sankeyContainer.remove();
        sankeyContainer = document.createElement('div');
        sankeyContainer.id = 'cashflow-sankey-container';
        sankeyContainer.style.cssText = 'position: absolute; inset: 0; display: flex; flex-direction: column; background: var(--bg-surface); border-radius: 10px; overflow: hidden; z-index: 5; border: 1px solid var(--border-subtle);';
        canvas.parentElement.appendChild(sankeyContainer);
    }
    sankeyContainer.style.display = 'flex';
    renderSankeyForYear(state.inspectedYear || 2026);
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
    const { series, sched } = getSeriesAndSched();
    if (!series.length) {
        sankeyContainer.innerHTML = '<div style="padding: 24px; text-align: center; color: var(--text-muted);">No cash flow data available.</div>';
        return;
    }

    const minYear = series[0].year;
    const maxYear = series[series.length - 1].year;
    yr = Math.max(minYear, Math.min(maxYear, yr));
    const { cf, row } = getYearData(yr, series, sched);
    const pName = state.scenariosData?.primary_name || 'Primary';
    const sName = state.scenariosData?.spouse_name || 'Spouse';
    const pAge = cf.age_primary ?? row.age_primary ?? row.age ?? (45 + (yr - 2026));
    const sAge = cf.age_spouse ?? row.age_spouse ?? (45 + (yr - 2026));

    const retRow = sched.find(r => r.is_retired || r.is_primary_retired);
    const retYear = retRow
        ? retRow.year
        : (2026 + ((state.scenariosData?.primary_retirement_age || 65) - (state.scenariosData?.primary_current_age || 45)));
    const milestones = (state.scenariosData?.milestones || [])
        .filter(m => m.year >= minYear && m.year <= maxYear && m.year !== 2026 && m.year !== retYear)
        .slice(0, 3);

    let toolbar = sankeyContainer.querySelector('.sankey-toolbar');
    if (!toolbar) {
        toolbar = document.createElement('div');
        toolbar.className = 'sankey-toolbar';
        toolbar.style.cssText = 'display: flex; justify-content: space-between; align-items: center; padding: 10px 16px; border-bottom: 1px solid var(--border-subtle); background: var(--bg-canvas); flex-wrap: wrap; gap: 10px; flex-shrink: 0;';
        sankeyContainer.appendChild(toolbar);
    }

    toolbar.innerHTML = `
        <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap; min-width: 0;">
            <button type="button" class="btn btn-sm btn-secondary" id="sankey-prev-btn" style="padding: 4px 10px; font-size: 0.75rem;" ${yr <= minYear ? 'disabled' : ''} title="Previous Year">◀ Prev</button>
            <select id="sankey-year-select" class="form-input" style="width: auto; font-size: 0.75rem; padding: 4px 10px; font-weight: 600; background: var(--bg-surface); border: 1px solid var(--border-subtle); color: var(--text-primary); border-radius: 6px;">
                ${series.map(s => `<option value="${s.year}" ${s.year === yr ? 'selected' : ''}>Year ${s.year}${s.year === 2026 ? ' (Today)' : (s.year === retYear ? ' (Retire)' : '')}</option>`).join('')}
            </select>
            <button type="button" class="btn btn-sm btn-secondary" id="sankey-next-btn" style="padding: 4px 10px; font-size: 0.75rem;" ${yr >= maxYear ? 'disabled' : ''} title="Next Year">Next ▶</button>
            <span class="badge badge-blue" style="font-size: 0.75rem; padding: 4px 10px; font-weight: 600;">
                Year ${yr} (${escapeHtml(pName)} ${pAge} / ${escapeHtml(sName)} ${sAge})
            </span>
        </div>
        <div class="pill-group" style="display: inline-flex; align-items: center; gap: 4px; flex-wrap: wrap; background: var(--bg-surface); padding: 3px; border-radius: 8px; border: 1px solid var(--border-subtle);">
            <button type="button" class="pill-btn ${yr === 2026 ? 'active' : ''}" data-jump="2026" style="font-size: 0.75rem; padding: 3px 10px;">Today (2026)</button>
            ${retYear && retYear !== 2026 ? `<button type="button" class="pill-btn ${yr === retYear ? 'active' : ''}" data-jump="${retYear}" style="font-size: 0.75rem; padding: 3px 10px;">Retire (${retYear})</button>` : ''}
            ${milestones.map(m => `<button type="button" class="pill-btn ${yr === m.year ? 'active' : ''}" data-jump="${m.year}" style="font-size: 0.75rem; padding: 3px 10px;">${escapeHtml(m.label || 'Event')} (${m.year})</button>`).join('')}
        </div>
    `;

    toolbar.querySelector('#sankey-prev-btn')?.addEventListener('click', () => setSankeyYear(yr - 1));
    toolbar.querySelector('#sankey-next-btn')?.addEventListener('click', () => setSankeyYear(yr + 1));
    toolbar.querySelector('#sankey-year-select')?.addEventListener('change', (e) => setSankeyYear(parseInt(e.target.value, 10)));
    toolbar.querySelectorAll('[data-jump]').forEach(btn => {
        btn.addEventListener('click', () => setSankeyYear(parseInt(btn.getAttribute('data-jump'), 10)));
    });

    let chartArea = sankeyContainer.querySelector('.sankey-chart-area');
    if (!chartArea) {
        chartArea = document.createElement('div');
        chartArea.className = 'sankey-chart-area';
        chartArea.style.cssText = 'flex: 1; position: relative; width: 100%; height: calc(100% - 52px); display: flex; align-items: stretch; justify-content: stretch; padding: 4px 12px;';
        sankeyContainer.appendChild(chartArea);
        if (typeof ResizeObserver !== 'undefined' && !sankeyResizeObserver) {
            sankeyResizeObserver = new ResizeObserver(() => {
                if (sankeyContainer.style.display !== 'none' && getCfSubMode() === 'sankey') {
                    const curYr = state.inspectedYear || 2026;
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
                if (state.scenarioComparisonChart && typeof state.scenarioComparisonChart.resize === 'function') {
                    state.scenarioComparisonChart.resize();
                }
                if (state.cashFlowChart && typeof state.cashFlowChart.resize === 'function') {
                    state.cashFlowChart.resize();
                }
            };
            if (typeof window !== 'undefined' && typeof window.animateWidgetGridLayout === 'function') {
                window.animateWidgetGridLayout(card, () => applyChartStageHeight(isSankey), applyResize);
            } else {
                applyChartStageHeight(isSankey);
                applyResize();
            }
            setTimeout(applyResize, 220);
        }
    });
    document.addEventListener('input', (e) => {
        if (e.target && e.target.id === 'timeline-scrubber') {
            const container = document.getElementById('cashflow-sankey-container');
            if (container && container.style.display !== 'none' && getCfSubMode() === 'sankey') {
                const yr = parseInt(e.target.value, 10);
                if (!isNaN(yr)) renderSankeyForYear(yr);
            }
        }
    });
}
