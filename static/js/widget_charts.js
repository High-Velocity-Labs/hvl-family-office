/**
 * Client-Side Chart Hydrator & Collapsible Chart Controller for Customizable Widgets.
 * Hydrates Overview charts (Lifetime Forecast, Cash Flow, Monte Carlo, Career Comp)
 * and Scenarios Companion charts (Cash Flow, Monte Carlo, Longevity).
 */
(function () {
    'use strict';
    const widgetCharts = {};
    let ovActiveScenId = null, ovViewMode = 'real';

    function fmtShort(v) {
        if (typeof window.fmtShortCurrency === 'function') return window.fmtShortCurrency(v);
        if (v == null) return '--';
        const num = Number(v);
        if (isNaN(num)) return '--';
        const abs = Math.abs(num), s = num < 0 ? '-' : '';
        if (abs >= 1e9) return `${s}$${(abs / 1e9).toFixed(2)}B`;
        if (abs >= 1e6) return `${s}$${(abs / 1e6).toFixed(2)}M`;
        if (abs >= 1e3) return `${s}$${(abs / 1e3).toFixed(0)}K`;
        return `${s}$${abs.toFixed(0)}`;
    }

    function getChartPayloads(page) {
        const el = document.getElementById(`ssr-widget-charts-data-${page}`);
        if (!el) return null;
        try { return JSON.parse(el.textContent || '{}'); } catch (e) { return null; }
    }

    function getStoredCollapsed() {
        try { const raw = localStorage.getItem('hvl_collapsed_charts'); return raw ? JSON.parse(raw) : []; }
        catch (e) { return []; }
    }

    function getStoredWidths() {
        try { const raw = localStorage.getItem('hvl_chart_widths'); return raw ? JSON.parse(raw) : {}; }
        catch (e) { return {}; }
    }

    function applyCollapsedState() {
        const stored = new Set(getStoredCollapsed());
        document.querySelectorAll('.btn-toggle-chart-collapse').forEach(btn => {
            const cId = btn.getAttribute('data-chart-id');
            const body = cId && document.querySelector(`.collapsible-chart-body[data-chart-body-id="${cId}"]`);
            if (!body) return;
            const isCol = stored.has(cId);
            body.style.display = isCol ? 'none' : '';
            btn.textContent = isCol ? 'Show Graph ▼' : 'Hide Graph ▲';
        });
    }

    function applyChartWidths() {
        const widths = getStoredWidths();
        document.querySelectorAll('.btn-toggle-chart-width').forEach(btn => {
            const cId = btn.getAttribute('data-chart-id');
            const card = cId && document.querySelector(`.household-widget-card[data-widget-id="${cId}"]`);
            if (!card) return;
            const defaultWide = card.getAttribute('data-default-wide') === 'true';
            const isWide = (cId in widths) ? Boolean(widths[cId]) : defaultWide;
            card.style.gridColumn = isWide ? '1 / -1' : '';
            card.classList.toggle('widget-full', isWide);
            card.classList.toggle('widget-half', !isWide);
            btn.textContent = isWide ? '⇔ Half Width' : '⤢ Full Width';
            btn.setAttribute('aria-pressed', isWide ? 'true' : 'false');
        });
    }

    function resizeAllActiveCharts() {
        Object.values(widgetCharts).forEach(ch => {
            if (ch && typeof ch.resize === 'function') {
                ch.resize();
            }
        });
        const st = window.scenariosState;
        if (st) {
            [st.scenarioComparisonChart, st.cashFlowChart, st.longevityChart, st.monteCarloChart].forEach(ch => {
                if (ch && typeof ch.resize === 'function') ch.resize();
            });
        }
    }

    function toggleChartWidth(chartId) {
        if (!chartId) return;
        const card = document.querySelector(`.household-widget-card[data-widget-id="${chartId}"]`);
        const btn = document.querySelector(`.btn-toggle-chart-width[data-chart-id="${chartId}"]`);
        if (!card) return;
        const widths = getStoredWidths();
        const defaultWide = card.getAttribute('data-default-wide') === 'true';
        const curWide = (chartId in widths) ? Boolean(widths[chartId]) : defaultWide;
        const nextWide = !curWide;
        widths[chartId] = nextWide;
        try {
            localStorage.setItem('hvl_chart_widths', JSON.stringify(widths));
        } catch (e) {}
        const mutateWidth = () => {
            card.style.gridColumn = nextWide ? '1 / -1' : '';
            card.classList.toggle('widget-full', nextWide);
            card.classList.toggle('widget-half', !nextWide);
            if (btn) {
                btn.textContent = nextWide ? '⇔ Half Width' : '⤢ Full Width';
                btn.setAttribute('aria-pressed', nextWide ? 'true' : 'false');
            }
        };
        if (typeof window.animateWidgetGridLayout === 'function') {
            window.animateWidgetGridLayout(card, mutateWidth, resizeAllActiveCharts);
        } else {
            mutateWidth();
            resizeAllActiveCharts();
        }
    }

    function toggleChartCollapse(chartId) {
        if (!chartId) return;
        const stored = new Set(getStoredCollapsed());
        const willCol = !stored.has(chartId);
        if (willCol) stored.add(chartId); else stored.delete(chartId);
        const arr = Array.from(stored);
        try {
            localStorage.setItem('hvl_collapsed_charts', JSON.stringify(arr));
            document.cookie = `hvl_collapsed_charts=${encodeURIComponent(arr.join(',') || 'none')}; path=/; max-age=604800; SameSite=Lax`;
        } catch (e) {}

        const body = document.querySelector(`.collapsible-chart-body[data-chart-body-id="${chartId}"]`);
        const btn = document.querySelector(`.btn-toggle-chart-collapse[data-chart-id="${chartId}"]`);
        if (body) body.style.display = willCol ? 'none' : '';
        if (btn) btn.textContent = willCol ? 'Show Graph ▼' : 'Hide Graph ▲';
        if (!willCol) window.hydrateWidgetCharts();

        if (typeof window.sessionIsDemo === 'undefined' || !window.sessionIsDemo) {
            fetch('/api/widgets/collapsed_charts', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ chart_id: chartId, collapsed: willCol })
            }).catch(() => {});
        }
    }

    function getOrCreateChart(canvasId, configBuilder) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return null;
        const body = canvas.closest('.collapsible-chart-body');
        if (body && body.style.display === 'none') return null;
        if (widgetCharts[canvasId]) { widgetCharts[canvasId].destroy(); delete widgetCharts[canvasId]; }
        const ctx = canvas.getContext('2d');
        if (!ctx) return null;
        const cfg = configBuilder(ctx);
        if (!cfg) return null;
        const chart = new Chart(ctx, cfg);
        widgetCharts[canvasId] = chart;
        return chart;
    }

    function baseOpts(extraScales = {}) {
        return {
            responsive: true, maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { position: 'top', labels: { color: '#94A3B8', font: { size: 10 } } },
                tooltip: { callbacks: { label: c => ` ${c.dataset.label}: ${fmtShort(c.raw)}` } }
            },
            scales: {
                x: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94A3B8', maxTicksLimit: 11 } },
                y: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94A3B8', callback: v => fmtShort(v) } },
                ...extraScales
            }
        };
    }

    function renderOvLifetimeForecast(payload) {
        const lf = payload?.lifetime_forecast;
        if (!lf?.years?.length) return;
        const isNom = ovViewMode === 'nominal', target = ovActiveScenId || lf.active_scenario_id;
        getOrCreateChart('chart-ov-lifetime-forecast', () => ({
            type: 'line',
            data: {
                labels: lf.years,
                datasets: (lf.scenarios || []).filter(s => target === 'all' || s.id === target).map(s => {
                    const col = s.color || (s.is_active ? '#3B82F6' : '#94A3B8');
                    return {
                        label: s.name + (isNom ? ' (Nominal)' : ' (Real)'),
                        data: isNom ? (s.net_worth_nominal || []) : (s.net_worth_real || []),
                        borderColor: col, backgroundColor: target !== 'all' ? (col + '1A') : 'transparent',
                        fill: target !== 'all', tension: 0.32, borderWidth: s.is_active ? 2.5 : 1.8, pointRadius: 0
                    };
                })
            },
            options: baseOpts()
        }));
    }

    function makeCfConfig(cf) {
        return {
            type: 'bar',
            data: {
                labels: cf.years,
                datasets: [
                    { label: 'Inflows', data: cf.inflows || [], backgroundColor: '#10B981', order: 2 },
                    { label: 'Living Spend', data: cf.living_spend || [], backgroundColor: 'rgba(239, 68, 68, 0.85)', order: 2 },
                    { label: 'Net Draw', data: cf.net_draw || [], type: 'line', borderColor: '#3B82F6', borderWidth: 2, tension: 0.28, pointRadius: 0, order: 1 }
                ]
            },
            options: baseOpts()
        };
    }

    function makeMcConfig(mc) {
        return {
            type: 'line',
            data: {
                labels: mc.years,
                datasets: [
                    { label: 'P90', data: mc.p90 || [], borderColor: '#10B981', borderDash: [4, 4], pointRadius: 0, borderWidth: 1.5 },
                    { label: 'P75', data: mc.p75 || [], borderColor: '#34D399', borderDash: [2, 2], pointRadius: 0, borderWidth: 1.2 },
                    { label: 'P50 (Median)', data: mc.p50 || [], borderColor: '#3B82F6', borderWidth: 2.5, pointRadius: 0 },
                    { label: 'P25', data: mc.p25 || [], borderColor: '#F59E0B', borderDash: [2, 2], pointRadius: 0, borderWidth: 1.2 },
                    { label: 'P10', data: mc.p10 || [], borderColor: '#EF4444', borderDash: [4, 4], pointRadius: 0, borderWidth: 1.5 }
                ]
            },
            options: baseOpts()
        };
    }

    function bindOverviewControls() {
        document.querySelectorAll('.ov-scen-switch-pill').forEach(btn => {
            btn.onclick = (e) => {
                e.preventDefault();
                document.querySelectorAll('.ov-scen-switch-pill').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                ovActiveScenId = btn.getAttribute('data-scen-id');
                const p = getChartPayloads('overview');
                if (p) renderOvLifetimeForecast(p);
            };
        });
        const rBtn = document.getElementById('btn-ov-lf-real');
        const nBtn = document.getElementById('btn-ov-lf-nominal');
        if (rBtn && nBtn) {
            rBtn.onclick = (e) => {
                e.preventDefault();
                rBtn.classList.add('active');
                nBtn.classList.remove('active');
                ovViewMode = 'real';
                const p = getChartPayloads('overview');
                if (p) renderOvLifetimeForecast(p);
            };
            nBtn.onclick = (e) => {
                e.preventDefault();
                nBtn.classList.add('active');
                rBtn.classList.remove('active');
                ovViewMode = 'nominal';
                const p = getChartPayloads('overview');
                if (p) renderOvLifetimeForecast(p);
            };
        }
    }

    window.insertWidgetLoadingPlaceholder = function (page, wid, title, fullWidth) {
        if (typeof document === 'undefined') return;
        const grid = document.getElementById(page === 'overview' ? 'overview-widgets-grid' : 'scenarios-widgets-grid');
        if (!grid || (wid && grid.querySelector(`.household-widget-card[data-widget-id="${wid}"]`))) return;
        const card = document.createElement('div');
        card.className = 'portal-card household-widget-card widget-loading-placeholder fragment-loading-skeleton';
        if (wid) card.setAttribute('data-widget-id', wid);
        card.setAttribute('role', 'status');
        card.setAttribute('aria-live', 'polite');
        card.style.cssText = `${fullWidth ? 'grid-column: 1 / -1; ' : ''}display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 220px; gap: 14px; color: var(--text-muted); background: var(--bg-surface); border-radius: 12px; border: 1px solid var(--border-subtle); padding: 32px 20px;`;
        const spinner = document.createElement('div');
        spinner.className = 'chart-spinner';
        const label = document.createElement('span');
        label.className = 'chart-loading-text';
        label.style.cssText = 'font-size: 0.875rem; font-weight: 600; color: var(--text-secondary); text-align: center;';
        label.textContent = title ? `Loading ${title}...` : 'Loading widget...';
        card.appendChild(spinner);
        card.appendChild(label);
        grid.appendChild(card);
        if (typeof window.applyWidgetEditModeUI === 'function') window.applyWidgetEditModeUI(page);
    };

    window.hydrateWidgetCharts = function (scopePage) {
        if (typeof Chart === 'undefined') return;
        applyCollapsedState();
        applyChartWidths();
        if (!scopePage || scopePage === 'overview') {
            const ov = getChartPayloads('overview');
            if (ov) {
                renderOvLifetimeForecast(ov);
                if (ov.cash_flow?.years?.length) getOrCreateChart('chart-ov-cashflow', () => makeCfConfig(ov.cash_flow));
                if (ov.monte_carlo?.years?.length) getOrCreateChart('chart-ov-montecarlo', () => makeMcConfig(ov.monte_carlo));
                const compCanvas = document.getElementById('chart-ov-career-comp');
                if (compCanvas) {
                    const compBody = compCanvas.closest('.collapsible-chart-body');
                    const oldEmpty = compBody && compBody.querySelector('.widget-chart-empty-msg');
                    if (oldEmpty) oldEmpty.remove();
                    if (ov.career_comp?.years?.length) {
                        compCanvas.style.display = '';
                        getOrCreateChart('chart-ov-career-comp', () => ({
                            type: 'bar',
                            data: {
                                labels: ov.career_comp.years,
                                datasets: [
                                    { label: 'Base Salary', data: ov.career_comp.base_salary || [], backgroundColor: '#3B82F6', stack: 'comp', order: 2 },
                                    { label: 'Bonus / Incentive', data: ov.career_comp.bonus || [], backgroundColor: '#F59E0B', stack: 'comp', order: 2 },
                                    { label: 'Total Comp', data: ov.career_comp.total_comp || [], type: 'line', borderColor: '#10B981', borderWidth: 2, pointRadius: 2, order: 1 }
                                ]
                            },
                            options: baseOpts()
                        }));
                    } else if (compBody) {
                        compCanvas.style.display = 'none';
                        const msg = document.createElement('div');
                        msg.className = 'widget-chart-empty-msg text-muted';
                        msg.style.cssText = 'display: flex; align-items: center; justify-content: center; height: 100%; font-size: 0.8125rem; text-align: center; padding: 20px;';
                        msg.textContent = 'No W-2 career compensation history on file for this household.';
                        compBody.appendChild(msg);
                    }
                }
                bindOverviewControls();
            }
        }
        if (!scopePage || scopePage === 'scenarios') {
            if (typeof window.renderActiveLensChart === 'function') {
                window.renderActiveLensChart();
            }
        }
    };

    document.addEventListener('click', (e) => {
        const wBtn = e.target.closest('.btn-toggle-chart-width');
        if (wBtn) {
            e.preventDefault();
            toggleChartWidth(wBtn.getAttribute('data-chart-id'));
            return;
        }
        const btn = e.target.closest('.btn-toggle-chart-collapse');
        if (btn) {
            e.preventDefault();
            toggleChartCollapse(btn.getAttribute('data-chart-id'));
        }
    });

    document.addEventListener('DOMContentLoaded', () => window.hydrateWidgetCharts());

    document.body.addEventListener('htmx:afterSettle', (e) => {
        const target = e.detail && e.detail.target;
        if (!target) { window.hydrateWidgetCharts(); return; }
        if (target.id === 'section-overview' || target.querySelector('#section-overview')) window.hydrateWidgetCharts('overview');
        else if (target.id === 'section-scenarios' || target.querySelector('#section-scenarios')) window.hydrateWidgetCharts('scenarios');
        else window.hydrateWidgetCharts();
    });
})();
