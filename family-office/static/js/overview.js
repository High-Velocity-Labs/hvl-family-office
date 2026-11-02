/**
 * Overview & True Net Worth Module
 * Manages KPI hero cards, trajectory charts, granular asset allocation doughnut,
 * and household widget customizer / reorder delegation.
 */

var historicalNetWorthData = null;
var monthlyNetWorthData = null;
var quarterlyNetWorthData = null;
var historicalSavingsData = null;
var recommendedGranularity = 'annual';
var activeHistGranularity = null;
var activeProjGranularity = 'annual';
var overviewChartMode = 'projection';
var widgetEditModeByPage = { overview: false, scenarios: false };

function syncDrawerCatalogOrder(page, orderedIds, syncCheckboxes = false) {
    const drawer = document.getElementById(`widget-customizer-drawer-${page}`);
    if (drawer && Array.isArray(orderedIds)) {
        drawer.dataset.activeIds = orderedIds.join(',');
        const chks = Array.from(drawer.querySelectorAll('.chk-widget-toggle'));

        if (syncCheckboxes) {
            chks.forEach(chk => {
                if (!chk.disabled) {
                    chk.checked = orderedIds.includes(chk.getAttribute('data-widget-id'));
                }
            });
        }

        const inactive = chks
            .filter(c => !orderedIds.includes(c.getAttribute('data-widget-id')))
            .map(c => c.getAttribute('data-widget-title') || '');

        document.querySelectorAll(`.widget-avail-badge[data-page="${page}"]`).forEach(b => {
            b.textContent = `+${inactive.length}`;
            b.hidden = inactive.length <= 0;
        });

        document.querySelectorAll(`.widget-avail-summary[data-page="${page}"]`).forEach(s => {
            const wrap = document.createElement('span');
            if (inactive.length) {
                const lead = document.createElement('strong');
                const plural = inactive.length !== 1 ? 's' : '';
                lead.textContent = `${inactive.length} additional graph${plural} & widgets available:`;
                const extra = inactive.length > 3 ? ` + ${inactive.length - 3} more` : '';
                wrap.append(lead, ` ${inactive.slice(0, 3).join(' • ')}${extra}`);
            } else {
                wrap.textContent = `All ${chks.length} widgets are active.`;
            }
            s.replaceChildren(wrap);
        });
    }

    if (page === 'scenarios' && Array.isArray(orderedIds)) {
        const lbl = document.getElementById('scenarios-widgets-active-label');
        if (lbl) {
            lbl.textContent = `FORECASTING GRAPHS & WIDGETS (${orderedIds.length} ACTIVE)`;
        }
    }
}

function removeWidgetCardInPlace(page, wid, nextIds) {
    const grid = document.getElementById(page === 'overview' ? 'overview-widgets-grid' : 'scenarios-widgets-grid');
    const card = grid && grid.querySelector(`.household-widget-card[data-widget-id="${wid}"]`);
    if (card) card.remove();
    syncDrawerCatalogOrder(page, nextIds, true);
}

function setDemoWidgetCookie(page, widgetParam) {
    if (typeof document === 'undefined') return;
    try {
        const k = `hvl_widgets_${page}`;
        if (!widgetParam || widgetParam === 'default') {
            document.cookie = `${k}=; path=/; max-age=0; SameSite=Lax`;
        } else {
            document.cookie = `${k}=${encodeURIComponent(widgetParam)}; path=/; max-age=604800; SameSite=Lax`;
        }
    } catch (e) {}
}

async function refreshWidgetSection(page, widgetParam) {
    const base = `/fragments/${page}` + (widgetParam ? `?widgets=${encodeURIComponent(widgetParam)}` : '');
    await window.htmx.ajax('GET', base, { target: `#section-${page}`, swap: 'morph' });

    const latestIds = getActiveWidgetIdsForPage(page);
    const grid = document.getElementById(page === 'overview' ? 'overview-widgets-grid' : 'scenarios-widgets-grid');
    if (grid && latestIds.length) {
        grid.querySelectorAll('.household-widget-card[data-widget-id]').forEach(c => {
            if (!latestIds.includes(c.getAttribute('data-widget-id'))) {
                c.remove();
            }
        });
    }

    applyWidgetEditModeUI(page);
    if (page === 'overview' && window.globalDashboardData) {
        renderOverview(window.globalDashboardData);
    }
    window.hydrateWidgetCharts(page);
}

async function saveHouseholdWidgetPreferences(page, activeIds, reset = false, options = {}) {
    const reorderOnly = Boolean(options && options.reorderOnly);
    if (Array.isArray(activeIds)) {
        syncDrawerCatalogOrder(page, activeIds);
    }

    if (isDemoOrReadOnlySession()) {
        const widgetParam = reset ? 'default' : (Array.isArray(activeIds) && activeIds.length ? activeIds.join(',') : 'none');
        if (page === 'scenarios') {
            window.__demoWidgetsScenarios = widgetParam === 'default' ? undefined : widgetParam;
        }
        if (page === 'overview') {
            window.__demoWidgetsOverview = widgetParam === 'default' ? undefined : widgetParam;
        }
        setDemoWidgetCookie(page, widgetParam);
        if (reorderOnly) {
            applyWidgetEditModeUI(page);
            return;
        }
        try {
            await refreshWidgetSection(page, widgetParam);
        } catch (e) {
            if (e.name !== 'AbortError') console.error(e);
        }
        return;
    }

    try {
        const resp = await fetch('/api/widgets/preferences', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ page, active_ids: activeIds, reset: Boolean(reset), reorder_only: true }),
            skipReactiveMorph: true,
        });
        if (!resp.ok) return;

        const res = await resp.json().catch(() => ({}));
        if (reset && Array.isArray(res.active_ids)) {
            syncDrawerCatalogOrder(page, res.active_ids, true);
        }
        if (!reorderOnly) {
            await refreshWidgetSection(page);
        }
        applyWidgetEditModeUI(page);
    } catch (e) {
        if (e.name !== 'AbortError') {
            console.error('Failed to save widget preferences:', e);
        }
    }
}

// Module state, not a node flag: the listeners live on `document`, so they are installed exactly once.
let householdWidgetsDelegated = false;

function initHouseholdWidgetsDelegation() {
    if (householdWidgetsDelegated) return;
    householdWidgetsDelegated = true;

    document.addEventListener('click', (e) => {
        if (e.target.closest('.nav-link[data-target], .nav-item[data-target]')) {
            if (widgetEditModeByPage.overview) setWidgetEditMode('overview', false);
            if (widgetEditModeByPage.scenarios) setWidgetEditMode('scenarios', false);
            return;
        }

        const toggleBtn = e.target.closest('.btn-toggle-widget-drawer');
        if (toggleBtn) {
            const p = toggleBtn.getAttribute('data-page');
            const next = !widgetEditModeByPage[p];
            setWidgetEditMode(p, next);
            const drw = next && document.getElementById(`widget-customizer-drawer-${p}`);
            if (drw && typeof drw.scrollIntoView === 'function') {
                drw.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
            return;
        }

        const removeBtn = e.target.closest('.btn-widget-remove');
        if (removeBtn) {
            const page = removeBtn.getAttribute('data-page');
            const wid = removeBtn.getAttribute('data-widget-id');
            const nextIds = getActiveWidgetIdsForPage(page).filter(id => id !== wid);
            removeWidgetCardInPlace(page, wid, nextIds);
            saveHouseholdWidgetPreferences(page, nextIds, false, { reorderOnly: true });
            return;
        }

        const resetBtn = e.target.closest('.btn-widget-reset');
        if (resetBtn) {
            const rPage = resetBtn.getAttribute('data-page');
            window.insertWidgetLoadingPlaceholder(rPage, '', 'Default Widgets', true);
            saveHouseholdWidgetPreferences(rPage, null, true);
        }
    });

    document.addEventListener('change', (e) => {
        if (e.target && e.target.id === 'mobile-nav-select') {
            if (widgetEditModeByPage.overview) setWidgetEditMode('overview', false);
            if (widgetEditModeByPage.scenarios) setWidgetEditMode('scenarios', false);
            return;
        }

        const chk = e.target.closest('.chk-widget-toggle');
        if (!chk || chk.disabled || chk.dataset.core === 'true') return;

        const page = chk.getAttribute('data-page');
        const wid = chk.getAttribute('data-widget-id');
        const curIds = getActiveWidgetIdsForPage(page);
        if (!chk.checked) {
            const nextIds = curIds.filter(id => id !== wid);
            removeWidgetCardInPlace(page, wid, nextIds);
            saveHouseholdWidgetPreferences(page, nextIds, false, { reorderOnly: true });
        } else {
            const title = chk.getAttribute('data-widget-title')
                || (chk.closest('.widget-catalog-item')?.querySelector('strong')?.textContent)
                || 'Widget';
            window.insertWidgetLoadingPlaceholder(page, wid, title, chk.getAttribute('data-full-width') === 'true');
            const updatedIds = curIds.includes(wid) ? curIds : [...curIds, wid];
            saveHouseholdWidgetPreferences(page, updatedIds, false, { reorderOnly: false });
        }
    });

    document.addEventListener('keydown', (e) => {
        const handle = e.target.closest('.widget-drag-handle');
        if (!handle || !['ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown'].includes(e.key)) return;
        e.preventDefault();

        const page = handle.getAttribute('data-page');
        if (!widgetEditModeByPage[page]) return;

        const card = handle.closest('.household-widget-card[data-widget-id]');
        const grid = card && card.parentElement;
        if (!card || !grid) return;

        const cards = Array.from(grid.querySelectorAll('.household-widget-card[data-widget-id]'));
        const idx = cards.indexOf(card);
        const dir = (e.key === 'ArrowLeft' || e.key === 'ArrowUp') ? -1 : 1;
        const targetIdx = idx + dir;
        if (targetIdx < 0 || targetIdx >= cards.length) return;

        const reorderDom = () => {
            grid.insertBefore(card, dir < 0 ? cards[targetIdx] : cards[targetIdx].nextSibling);
        };
        window.animateWidgetGridLayout(grid, reorderDom, () => handle.focus());
        const ordered = Array.from(grid.querySelectorAll('.household-widget-card[data-widget-id]'))
            .map(c => c.getAttribute('data-widget-id'));
        saveHouseholdWidgetPreferences(page, ordered, false, { reorderOnly: true });
    });

    bindWidgetDragAndTouchEvents();
}

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
    if (window.isDemoSession()) {
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
        drawer.hidden = !isEdit;
    }
    document.querySelectorAll(`.btn-toggle-widget-drawer[data-page="${page}"]`).forEach(btn => {
        if (!drawer || !drawer.contains(btn)) {
            btn.hidden = isEdit;
        }
    });
    const grid = document.getElementById(page === 'overview' ? 'overview-widgets-grid' : 'scenarios-widgets-grid');
    if (grid) {
        grid.classList.toggle('widget-edit-mode-active', isEdit);
        grid.querySelectorAll('.household-widget-card[data-widget-id]').forEach(card => {
            card.setAttribute('draggable', isEdit ? 'true' : 'false');
        });
    }
    document.querySelectorAll(`.widget-inline-actions[data-page="${page}"]`).forEach(el => {
        el.hidden = !isEdit;
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
        }
        if (a && allocLoader) {
            allocLoader.classList.add('hidden');
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
    window.hydrateWidgetCharts('overview');
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
            const isGran = btn.getAttribute('data-granularity') === gran;
            btn.classList.toggle('active', isGran);
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
        granContainer.hidden = false;
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
        if (granContainer) granContainer.hidden = false;
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
        if (granContainer) granContainer.hidden = false;
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
    window.registerSectionHydrator('section-overview', renderOverview, {
        needsDashboard: true,
        onInvalidate: () => {
            historicalNetWorthData = null;
            monthlyNetWorthData = null;
            quarterlyNetWorthData = null;
            historicalSavingsData = null;
            cachedSnapshot = null;
        }
    });
}
