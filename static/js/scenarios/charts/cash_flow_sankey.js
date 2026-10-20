/**
 * Interactive Single-Year Cash-Flow Sankey View
 * Traces annual income streams into total cash flow and out to living, debt, taxes, and savings.
 */
import { state, escapeHtml, fmtCurrency, fmtShortCurrency } from '../state.js';
import { getTimelineRange, inspectTimelineYear, updateScrubberNeedle } from '../scrubber.js';
import { getCfSubMode } from './cash_flow.js';

let isChartTallMode = false;
let sankeyResizeObserver = null;

function getCashFlowCanvas() {
    return document.getElementById('chart-scen_chart_cashflow') || document.getElementById('chart-scenarios-comparison');
}

function applyChartStageHeight(sankeyActive) {
    const stage = document.getElementById('scenarios-cashflow-stage') || getCashFlowCanvas()?.parentElement;
    if (!stage) return;
    if (isChartTallMode) {
        stage.style.height = '740px';
    } else {
        stage.style.height = sankeyActive ? '560px' : '420px';
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
            row = { year: yr, total_net_worth: hItem.true_net_worth, age_primary: 45 - (2026 - yr), age_spouse: 45 - (2026 - yr), longevity_status: 'historical' };
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

    const minYear = series[0].year, maxYear = series[series.length - 1].year;
    yr = Math.max(minYear, Math.min(maxYear, yr));
    const { cf, row } = getYearData(yr, series, sched);
    const pName = state.scenariosData?.primary_name || 'Primary', sName = state.scenariosData?.spouse_name || 'Spouse';
    const pAge = cf.age_primary ?? row.age_primary ?? row.age ?? (45 + (yr - 2026));
    const sAge = cf.age_spouse ?? row.age_spouse ?? (45 + (yr - 2026));

    const retRow = sched.find(r => r.is_retired || r.is_primary_retired);
    const retYear = retRow ? retRow.year : (2026 + ((state.scenariosData?.primary_retirement_age || 65) - (state.scenariosData?.primary_current_age || 45)));
    const milestones = (state.scenariosData?.milestones || [])
        .filter(m => m.year >= minYear && m.year <= maxYear && m.year !== 2026 && m.year !== retYear).slice(0, 3);

    let toolbar = sankeyContainer.querySelector('.sankey-toolbar');
    if (!toolbar) {
        toolbar = document.createElement('div');
        toolbar.className = 'sankey-toolbar';
        toolbar.style.cssText = 'display: flex; justify-content: space-between; align-items: center; padding: 10px 16px; border-bottom: 1px solid var(--border-subtle); background: var(--bg-canvas); flex-wrap: wrap; gap: 10px; flex-shrink: 0;';
        sankeyContainer.appendChild(toolbar);
    }

    toolbar.innerHTML = `
        <div style="display: flex; align-items: center; gap: 8px;">
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
    toolbar.querySelectorAll('[data-jump]').forEach(btn => btn.addEventListener('click', () => setSankeyYear(parseInt(btn.getAttribute('data-jump'), 10))));

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

function renderSankeySvg(chartArea, yr, cf, row) {
    let inflow_rsu = Number(cf.inflow_rsu || row.inflow_rsu || 0);
    let inflow_salary = Number(cf.inflow_salary || row.inflow_salary || 0);
    if (!inflow_salary && !inflow_rsu) {
        const gross = Number(cf.gross_compensation || 0), takehome = Number(cf.household_salary || 0);
        if (gross > 0) inflow_salary = gross;
        else if (takehome > 0) inflow_salary = takehome + Number(cf.income_tax_haircut || 0);
        else if (cf.salary_savings > 0) inflow_salary = Number(cf.salary_savings);
    }
    const inflow_ss = Number(cf.inflow_ss ?? (cf.social_security || row.social_security || 0));
    const inflow_events = Number(cf.inflow_events ?? (cf.event_inflows || 0));
    let portfolio_draw = Number(cf.portfolio_draw ?? (row.net_portfolio_draw || 0));

    let living_core = Number(cf.living_core ?? (row.living_spending || 0));
    if (cf.travel_gogo && Number(cf.travel_gogo) > 0) living_core += Number(cf.travel_gogo);
    const mortgage_payment = Number(cf.mortgage_payment ?? (cf.mortgage_debt_service || 0));
    const tax_outflow = Number(cf.tax_outflow ?? (cf.income_tax_haircut || 0));
    let education = Number(cf.education_k12 || 0) + Number(cf.college_tuition || 0);
    let raw_events = Number(cf.outflow_events ?? (cf.events_outflow || 0));

    if (education === 0 && state.scenariosData?.events_catalog) {
        const eduEvents = state.scenariosData.events_catalog.filter(e => {
            const cat = (e.category || '').toLowerCase(), nm = (e.name || '').toLowerCase();
            const start = e.start_year || e.year || 2026, end = e.end_year || start;
            return (cat === 'education' || cat === 'college' || nm.includes('tuition') || nm.includes('college') || nm.includes('school')) && (yr >= start && yr <= end);
        });
        const eduTotal = eduEvents.reduce((acc, e) => acc + Number(e.annual_amount || e.one_time_amount || e.amount || 0), 0);
        if (eduTotal > 0) { education = eduTotal; raw_events = Math.max(0, raw_events - eduTotal); }
    }
    const gifting = Number(cf.gifting || 0), outflow_events = raw_events;
    let net_savings = Number(cf.net_savings ?? (cf.net_cash_flow > 0 ? cf.net_cash_flow : (row.salary_savings > 0 ? row.salary_savings : 0)));

    let totalIn = inflow_salary + inflow_rsu + inflow_ss + inflow_events + portfolio_draw;
    let totalOut = living_core + mortgage_payment + tax_outflow + education + gifting + outflow_events + net_savings;

    if (totalIn > totalOut) { net_savings += (totalIn - totalOut); totalOut = totalIn; }
    else if (totalOut > totalIn) { portfolio_draw += (totalOut - totalIn); totalIn = totalOut; }

    const W = Math.max(760, Math.round(chartArea.clientWidth || 1240));
    const H_svg = Math.max(380, Math.round(chartArea.clientHeight || 500));

    if (totalIn <= 0) {
        chartArea.innerHTML = `<svg viewBox="0 0 ${W} ${H_svg}" style="width:100%;height:100%;"><text x="${Math.round(W / 2)}" y="${Math.round(H_svg / 2)}" text-anchor="middle" font-size="15" fill="var(--text-muted)">No cash flow activity recorded for Year ${yr}</text></svg>`;
        return;
    }

    const sources = [
        { id: 'salary', label: 'Salary / W-2', amount: inflow_salary, color: '#059669' },
        { id: 'rsu', label: 'RSU / Equity Vests', amount: inflow_rsu, color: '#10B981' },
        { id: 'ss', label: 'Social Security', amount: inflow_ss, color: '#0D9488' },
        { id: 'events_in', label: 'Event Inflows', amount: inflow_events, color: '#34D399' },
        { id: 'draw', label: 'Net Portfolio Draw', amount: portfolio_draw, color: '#F59E0B' }
    ].filter(s => s.amount > 0);

    const targets = [
        { id: 'living', label: 'Core Living', amount: living_core, color: '#1D4ED8' },
        { id: 'mortgage', label: 'Mortgage P&I', amount: mortgage_payment, color: '#0284C7' },
        { id: 'taxes', label: 'Taxes', amount: tax_outflow, color: '#DC2626' },
        { id: 'education', label: 'Kids K-12 & College', amount: education, color: '#8B5CF6' },
        { id: 'gifting', label: 'Family Gifting', amount: gifting, color: '#C06C26' },
        { id: 'events_out', label: 'Event Outflows', amount: outflow_events, color: '#C75D6E' },
        { id: 'savings', label: 'Net Savings / Reinvest', amount: net_savings, color: '#059669' }
    ].filter(t => t.amount > 0);

    const topY = 58, bottomY = H_svg - 20, H = bottomY - topY;
    const labelMargin = Math.min(205, Math.max(165, Math.round(W * 0.16)));
    const barW = 20, hubW = 24;
    const xLeftBar = labelMargin;
    const xRightBar = W - labelMargin - barW;
    const xHub = Math.round(W / 2 - hubW / 2);

    const gap_s = sources.length > 1 ? Math.min(20, Math.floor(84 / sources.length)) : 0;
    const availH_s = H - (sources.length - 1) * gap_s;
    sources.forEach(s => s.h = Math.max(18, (s.amount / totalIn) * availH_s));
    const sumH_s = sources.reduce((a, b) => a + b.h, 0);
    if (sumH_s > availH_s) sources.forEach(s => s.h = (s.h / sumH_s) * availH_s);
    let curY = topY + Math.max(0, (availH_s - sumH_s) / 2);
    sources.forEach(s => { s.y0 = curY; s.y1 = curY + s.h; curY += s.h + gap_s; });

    const gap_t = targets.length > 1 ? Math.min(20, Math.floor(84 / targets.length)) : 0;
    const availH_t = H - (targets.length - 1) * gap_t;
    targets.forEach(t => t.h = Math.max(18, (t.amount / totalOut) * availH_t));
    const sumH_t = targets.reduce((a, b) => a + b.h, 0);
    if (sumH_t > availH_t) targets.forEach(t => t.h = (t.h / sumH_t) * availH_t);
    curY = topY + Math.max(0, (availH_t - sumH_t) / 2);
    targets.forEach(t => { t.y0 = curY; t.y1 = curY + t.h; curY += t.h + gap_t; });

    let hubInY = topY;
    sources.forEach(s => {
        const sliceH = (s.amount / totalIn) * H;
        s.ribbon = { x0: xLeftBar + barW, y0_t: s.y0, y0_b: s.y1, x1: xHub, y1_t: hubInY, y1_b: hubInY + sliceH };
        hubInY += sliceH;
    });

    let hubOutY = topY;
    targets.forEach(t => {
        const sliceH = (t.amount / totalOut) * H;
        t.ribbon = { x0: xHub + hubW, y0_t: hubOutY, y0_b: hubOutY + sliceH, x1: xRightBar, y1_t: t.y0, y1_b: t.y1 };
        hubOutY += sliceH;
    });

    const bezPath = r => `M ${r.x0} ${r.y0_t} C ${r.x0 + (r.x1 - r.x0) * 0.46} ${r.y0_t}, ${r.x1 - (r.x1 - r.x0) * 0.46} ${r.y1_t}, ${r.x1} ${r.y1_t} L ${r.x1} ${r.y1_b} C ${r.x1 - (r.x1 - r.x0) * 0.46} ${r.y1_b}, ${r.x0 + (r.x1 - r.x0) * 0.46} ${r.y0_b}, ${r.x0} ${r.y0_b} Z`;
    const midX = Math.round(W / 2);

    chartArea.innerHTML = `
        <svg viewBox="0 0 ${W} ${H_svg}" style="width:100%;height:100%;display:block;">
            <defs>
                ${sources.map(s => `<linearGradient id="grad-s-${s.id}" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stop-color="${s.color}" stop-opacity="0.52"/><stop offset="100%" stop-color="#3B82F6" stop-opacity="0.45"/></linearGradient>`).join('')}
                ${targets.map(t => `<linearGradient id="grad-t-${t.id}" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stop-color="#3B82F6" stop-opacity="0.45"/><stop offset="100%" stop-color="${t.color}" stop-opacity="0.52"/></linearGradient>`).join('')}
            </defs>
            <text x="${xLeftBar + barW}" y="22" text-anchor="end" font-size="11.5" font-weight="700" fill="var(--status-green, #10B981)" letter-spacing="0.8">SOURCES / INFLOWS</text>
            <text x="${midX}" y="20" text-anchor="middle" font-size="11.5" font-weight="700" fill="var(--accent-blue, #3B82F6)" letter-spacing="0.8">TOTAL ANNUAL CASH FLOW</text>
            <text x="${xRightBar}" y="22" text-anchor="start" font-size="11.5" font-weight="700" fill="var(--accent-orange, #F59E0B)" letter-spacing="0.8">USES &amp; REINVESTMENT</text>
            <text x="${midX}" y="42" text-anchor="middle" font-size="14.5" font-weight="800" fill="var(--text-primary)">${fmtCurrency(totalIn)}</text>

            ${sources.map(s => `<path class="sankey-elem" data-label="${escapeHtml(s.label)}" data-amt="${s.amount}" data-pct="${((s.amount / totalIn) * 100).toFixed(1)}" d="${bezPath(s.ribbon)}" fill="url(#grad-s-${s.id})" stroke="${s.color}" stroke-width="0.75" stroke-opacity="0.35" style="cursor:pointer;"/>`).join('')}
            ${targets.map(t => `<path class="sankey-elem" data-label="${escapeHtml(t.label)}" data-amt="${t.amount}" data-pct="${((t.amount / totalOut) * 100).toFixed(1)}" d="${bezPath(t.ribbon)}" fill="url(#grad-t-${t.id})" stroke="${t.color}" stroke-width="0.75" stroke-opacity="0.35" style="cursor:pointer;"/>`).join('')}
            ${sources.map(s => `<rect class="sankey-elem" data-label="${escapeHtml(s.label)}" data-amt="${s.amount}" data-pct="${((s.amount / totalIn) * 100).toFixed(1)}" x="${xLeftBar}" y="${s.y0}" width="${barW}" height="${s.h}" rx="4" fill="${s.color}" style="cursor:pointer;"/>`).join('')}
            <rect class="sankey-elem" data-label="Total Annual Cash Flow" data-amt="${totalIn}" data-pct="100" x="${xHub}" y="${topY}" width="${hubW}" height="${H}" rx="5" fill="#3B82F6" style="cursor:pointer;"/>
            ${targets.map(t => `<rect class="sankey-elem" data-label="${escapeHtml(t.label)}" data-amt="${t.amount}" data-pct="${((t.amount / totalOut) * 100).toFixed(1)}" x="${xRightBar}" y="${t.y0}" width="${barW}" height="${t.h}" rx="4" fill="${t.color}" style="cursor:pointer;"/>`).join('')}

            ${sources.map(s => {
                const pct = ((s.amount / totalIn) * 100).toFixed(1);
                return s.h < 30
                    ? `<text x="${xLeftBar - 10}" y="${s.y0 + s.h / 2 + 4}" text-anchor="end" font-size="12" fill="var(--text-primary)"><tspan font-weight="700">${escapeHtml(s.label)}</tspan> <tspan fill="var(--text-muted)" font-weight="600">${fmtShortCurrency(s.amount)} (${pct}%)</tspan></text>`
                    : `<text x="${xLeftBar - 10}" y="${s.y0 + s.h / 2 - 3}" text-anchor="end" font-size="13" font-weight="700" fill="var(--text-primary)">${escapeHtml(s.label)}</text><text x="${xLeftBar - 10}" y="${s.y0 + s.h / 2 + 13}" text-anchor="end" font-size="11.5" font-weight="600" fill="var(--text-muted)">${fmtShortCurrency(s.amount)} · ${pct}%</text>`;
            }).join('')}
            ${targets.map(t => {
                const pct = ((t.amount / totalOut) * 100).toFixed(1);
                return t.h < 30
                    ? `<text x="${xRightBar + barW + 10}" y="${t.y0 + t.h / 2 + 4}" text-anchor="start" font-size="12" fill="var(--text-primary)"><tspan font-weight="700">${escapeHtml(t.label)}</tspan> <tspan fill="var(--text-muted)" font-weight="600">${fmtShortCurrency(t.amount)} (${pct}%)</tspan></text>`
                    : `<text x="${xRightBar + barW + 10}" y="${t.y0 + t.h / 2 - 3}" text-anchor="start" font-size="13" font-weight="700" fill="var(--text-primary)">${escapeHtml(t.label)}</text><text x="${xRightBar + barW + 10}" y="${t.y0 + t.h / 2 + 13}" text-anchor="start" font-size="11.5" font-weight="600" fill="var(--text-muted)">${fmtShortCurrency(t.amount)} · ${pct}%</text>`;
            }).join('')}
        </svg>
    `;
    bindTooltips(chartArea, chartArea.parentElement);
}

function bindTooltips(chartArea, container) {
    let tip = container.querySelector('.sankey-tooltip');
    if (!tip) {
        tip = document.createElement('div');
        tip.className = 'sankey-tooltip';
        tip.style.cssText = 'position: absolute; display: none; pointer-events: none; background: var(--bg-surface-elevated); border: 1px solid var(--border-subtle); padding: 6px 10px; border-radius: 6px; font-size: 0.75rem; color: var(--text-primary); z-index: 20; box-shadow: 0 4px 12px rgba(0,0,0,0.25); backdrop-filter: blur(8px);';
        container.appendChild(tip);
    }
    chartArea.querySelectorAll('.sankey-elem').forEach(el => {
        el.addEventListener('mouseenter', () => {
            if (el.tagName === 'path') { el.setAttribute('stroke-width', '1.5'); el.setAttribute('stroke-opacity', '0.9'); }
            const label = el.getAttribute('data-label') || '', amt = parseFloat(el.getAttribute('data-amt') || '0'), pct = el.getAttribute('data-pct') || '';
            tip.innerHTML = `<div style="font-weight: 600; margin-bottom: 2px;">${escapeHtml(label)}</div><div style="font-size: 0.8125rem; color: var(--accent-blue);">${fmtCurrency(amt)} <span style="font-size: 0.6875rem; color: var(--text-muted);">(${pct}% of flow)</span></div>`;
            tip.style.display = 'block';
        });
        el.addEventListener('mousemove', (e) => {
            const rect = container.getBoundingClientRect();
            tip.style.left = `${Math.min(rect.width - 180, Math.max(10, e.clientX - rect.left + 12))}px`;
            tip.style.top = `${Math.min(rect.height - 60, Math.max(10, e.clientY - rect.top + 12))}px`;
        });
        el.addEventListener('mouseleave', () => {
            if (el.tagName === 'path') { el.setAttribute('stroke-width', '0.75'); el.setAttribute('stroke-opacity', '0.35'); }
            tip.style.display = 'none';
        });
    });
}

if (typeof document !== 'undefined' && !document._hasSankeyListeners) {
    document._hasSankeyListeners = true;
    document.addEventListener('click', (e) => {
        const expandBtn = e.target.closest('#btn-chart-expand-size');
        if (expandBtn) {
            isChartTallMode = !isChartTallMode;
            expandBtn.textContent = isChartTallMode ? '⤡ Standard Height' : '⤢ Tall Chart';
            expandBtn.classList.toggle('active', isChartTallMode);
            const isSankey = state.currentLens === 'cashflow' && getCfSubMode() === 'sankey';
            applyChartStageHeight(isSankey);
            setTimeout(() => {
                if (state.scenarioComparisonChart && typeof state.scenarioComparisonChart.resize === 'function') {
                    state.scenarioComparisonChart.resize();
                }
            }, 200);
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
