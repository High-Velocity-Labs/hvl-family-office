/**
 * Overview & True Net Worth Module
 * Manages KPI hero cards, trajectory charts, and granular asset allocation doughnut.
 */

var historicalNetWorthData = null;
var monthlyNetWorthData = null;
var quarterlyNetWorthData = null;
var historicalSavingsData = null;
var recommendedGranularity = 'annual';
var activeHistGranularity = null;
var activeProjGranularity = 'annual';
var overviewChartMode = 'projection';

function getActiveWidgetIdsForPage(page) {
    const drawer = document.getElementById(`widget-customizer-drawer-${page}`);
    if (drawer && drawer.dataset.activeIds !== undefined) {
        return drawer.dataset.activeIds.split(',').map(s => s.trim()).filter(Boolean);
    }
    const grid = document.getElementById(page === 'overview' ? 'overview-widgets-grid' : 'scenarios-widgets-grid');
    if (!grid) return [];
    return Array.from(grid.querySelectorAll('.household-widget-card[data-widget-id]'))
        .map(el => el.getAttribute('data-widget-id'))
        .filter(Boolean);
}

function isDemoOrReadOnlySession() {
    if (typeof window !== 'undefined' && typeof window.isDemoSession === 'function' && window.isDemoSession()) {
        return true;
    }
    if (typeof document !== 'undefined' && document.body && (document.body.dataset.isDemo === 'true' || document.body.dataset.role === 'viewer')) {
        return true;
    }
    return Boolean(typeof window !== 'undefined' && window.location && new URLSearchParams(window.location.search).get('demo') === '1');
}

function applyWidgetEditModeUI(page) {
    if (typeof document === 'undefined') return;
    const isEdit = Boolean(widgetEditModeByPage[page]);
    const drawer = document.getElementById(`widget-customizer-drawer-${page}`);
    if (drawer) {
        drawer.style.display = isEdit ? 'block' : 'none';
    }
    document.querySelectorAll(`.btn-toggle-widget-drawer[data-page="${page}"]`).forEach(btn => {
        if (!drawer || !drawer.contains(btn)) {
            btn.style.display = isEdit ? 'none' : 'inline-flex';
        }
    });
    const grid = document.getElementById(page === 'overview' ? 'overview-widgets-grid' : 'scenarios-widgets-grid');
    if (grid) {
        grid.classList.toggle('widget-edit-mode-active', isEdit);
        grid.querySelectorAll('.household-widget-card[data-widget-id]').forEach(card => {
            card.setAttribute('draggable', isEdit ? 'true' : 'false');
            card.style.outline = isEdit ? '1px dashed rgba(59, 130, 246, 0.5)' : '';
            card.style.outlineOffset = isEdit ? '2px' : '';
            card.style.transition = 'transform 0.15s ease, outline 0.15s ease';
        });
    }
    document.querySelectorAll(`.widget-inline-actions[data-page="${page}"]`).forEach(el => {
        el.style.display = isEdit ? 'inline-flex' : 'none';
    });
}

function setWidgetEditMode(page, enabled) {
    if (!page) return;
    widgetEditModeByPage[page] = Boolean(enabled);
    applyWidgetEditModeUI(page);
}

function renderOverview(data) {
    const projLoader = document.getElementById('overview-chart-loading');
    const allocLoader = document.getElementById('overview-alloc-loading');
    const hideLoaders = (p, a) => {
        if (p && projLoader) {
            projLoader.classList.add('hidden');
            projLoader.style.display = 'none';
        }
        if (a && allocLoader) {
            allocLoader.classList.add('hidden');
            allocLoader.style.display = 'none';
        }
    };
    if (!data || !data.snapshot) {
        hideLoaders(true, true);
        return;
    }
    cachedSnapshot = data.snapshot;
    try {
        const series = (data.multi_year_projections && data.multi_year_projections.length > 0)
            ? buildProjectionSeriesForGranularity(data.multi_year_projections, activeProjGranularity)
            : [];
        renderProjectionChart(series);
    } catch (e) {
        console.error('Error rendering projection chart:', e);
        hideLoaders(true, false);
    }
    try {
        renderGranularAllocationChart(data.snapshot);
    } catch (e) {
        console.error('Error rendering allocation chart:', e);
        hideLoaders(false, true);
    }
    setupOverviewChartToggle();
    setupOverviewAllocToggle();
    applyWidgetEditModeUI('overview');
    if (typeof window !== 'undefined' && typeof window.hydrateWidgetCharts === 'function') {
        window.hydrateWidgetCharts('overview');
    }
}

function setupOverviewAllocToggle() {
    const btnTotal = document.getElementById('btn-alloc-total');
    const btnPublic = document.getElementById('btn-alloc-public');
    if (!btnTotal || !btnPublic) return;
    const setMode = (mode, activeBtn, otherBtn) => {
        overviewAllocMode = mode;
        activeBtn.classList.add('active');
        otherBtn.classList.remove('active');
        if (cachedSnapshot) renderGranularAllocationChart(cachedSnapshot);
    };
    btnTotal.onclick = () => setMode('total', btnTotal, btnPublic);
    btnPublic.onclick = () => setMode('public', btnPublic, btnTotal);
}

function getSeriesForGranularity(gran) {
    if (gran === 'monthly' && monthlyNetWorthData && monthlyNetWorthData.length) return monthlyNetWorthData;
    if (gran === 'quarterly' && quarterlyNetWorthData && quarterlyNetWorthData.length) return quarterlyNetWorthData;
    if (historicalNetWorthData && historicalNetWorthData.length) return historicalNetWorthData;
    if (monthlyNetWorthData && monthlyNetWorthData.length) return monthlyNetWorthData;
    return quarterlyNetWorthData || [];
}

function syncGranularityPillUI(gran) {
    const granContainer = document.getElementById('hist-granularity-controls');
    if (granContainer) {
        granContainer.querySelectorAll('[data-granularity]').forEach(btn => {
            btn.classList.toggle('active', btn.getAttribute('data-granularity') === gran);
        });
    }
}

function setupOverviewChartToggle() {
    const btnProj = document.getElementById('btn-chart-proj');
    const btnHist = document.getElementById('btn-chart-hist');
    const granContainer = document.getElementById('hist-granularity-controls');
    const titleEl = document.getElementById('overview-chart-title');
    const subEl = document.getElementById('overview-chart-sub');

    if (granContainer) {
        granContainer.style.display = 'inline-flex';
        granContainer.querySelectorAll('[data-granularity]').forEach(btn => {
            btn.onclick = () => {
                const gran = btn.getAttribute('data-granularity') || 'annual';
                syncGranularityPillUI(gran);
                if (overviewChartMode === 'projection') {
                    activeProjGranularity = gran;
                    if (window.globalProjections) {
                        renderProjectionChart(buildProjectionSeriesForGranularity(window.globalProjections, gran));
                    }
                } else {
                    activeHistGranularity = gran;
                    const series = getSeriesForGranularity(gran);
                    if (series && series.length) renderHistoricalChart(series);
                }
            };
        });
    }
    if (!btnProj || !btnHist) return;
    btnProj.onclick = () => {
        overviewChartMode = 'projection';
        btnProj.classList.add('active');
        btnHist.classList.remove('active');
        if (granContainer) granContainer.style.display = 'inline-flex';
        syncGranularityPillUI(activeProjGranularity || 'annual');
        if (titleEl) titleEl.textContent = '5-Year Net Worth Trajectory';
        if (subEl) {
            subEl.textContent = '5-year trajectory (Vested Net Worth + ongoing grant monthly vesting; unvested excluded until vested)';
        }
        if (window.globalProjections) {
            renderProjectionChart(buildProjectionSeriesForGranularity(window.globalProjections, activeProjGranularity || 'annual'));
        }
    };
    btnHist.onclick = async () => {
        overviewChartMode = 'historical';
        btnHist.classList.add('active');
        btnProj.classList.remove('active');
        if (granContainer) granContainer.style.display = 'inline-flex';
        if (titleEl) titleEl.textContent = 'Historical Net Worth Trajectory';
        if (subEl) {
            const hasAdj = cachedSnapshot && cachedSnapshot.company_equity && (
                (cachedSnapshot.company_equity.total_strike_cost_needed || 0) > 0
                || (cachedSnapshot.company_equity.total_tax_drag || 0) > 0
            );
            subEl.textContent = hasAdj
                ? 'Compound growth: Net Worth, company post-tax equity, and liquid investments'
                : 'Compound growth: Net Worth, company equity, and liquid investments';
        }
        const loader = document.getElementById('overview-chart-loading');
        if (!historicalNetWorthData) {
            if (loader) {
                const textEl = loader.querySelector('.chart-loading-text');
                if (textEl) textEl.textContent = 'Loading Historical Net Worth...';
                loader.classList.remove('hidden');
                loader.style.display = 'flex';
            }
            try {
                const res = await (await fetch('/api/networth/history')).json();
                if (res.success) {
                    historicalNetWorthData = res.historical_net_worth || [];
                    monthlyNetWorthData = res.monthly_net_worth || [];
                    quarterlyNetWorthData = res.quarterly_net_worth || [];
                    recommendedGranularity = res.recommended_granularity || 'annual';
                    historicalSavingsData = res.annual_savings_history || [];
                }
            } catch (e) {
                console.error('History fetch failed:', e);
            }
        }
        if (!activeHistGranularity) activeHistGranularity = recommendedGranularity || 'annual';
        syncGranularityPillUI(activeHistGranularity);
        const activeSeries = getSeriesForGranularity(activeHistGranularity);
        if (activeSeries && activeSeries.length) {
            renderHistoricalChart(activeSeries);
        } else if (loader) {
            loader.classList.add('hidden');
        }
    };
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        renderOverview,
        setupOverviewChartToggle,
        setupOverviewAllocToggle,
        getSeriesForGranularity,
        syncGranularityPillUI,
        saveHouseholdWidgetPreferences,
        setWidgetEditMode,
        applyWidgetEditModeUI
    });
    initHouseholdWidgetsDelegation();
    if (typeof window.registerSectionHydrator === 'function') {
        window.registerSectionHydrator('section-overview', renderOverview, {
            needsDashboard: true,
            onInvalidate: () => {
                historicalNetWorthData = null;
                monthlyNetWorthData = null;
                quarterlyNetWorthData = null;
                historicalSavingsData = null;
                if (typeof cachedSnapshot !== 'undefined') {
                    cachedSnapshot = null;
                }
            }
        });
    }
}
