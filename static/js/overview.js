/**
 * Overview & True Net Worth Module
 * Manages KPI hero cards, trajectory charts, and granular asset allocation doughnut.
 */

var historicalNetWorthData = null, monthlyNetWorthData = null, quarterlyNetWorthData = null, historicalSavingsData = null;
var recommendedGranularity = 'annual', activeHistGranularity = null, activeProjGranularity = 'annual', overviewChartMode = 'projection';
var widgetEditModeByPage = { overview: false, scenarios: false }, widgetFetchAbortByPage = { overview: null, scenarios: null };
var draggedWidgetCard = null, dropTargetCard = null, dropInsertBefore = true;

function renderOverview(data) {
    const projLoader = document.getElementById('overview-chart-loading');
    const allocLoader = document.getElementById('overview-alloc-loading');
    const hideLoaders = (p, a) => {
        if (p && projLoader) { projLoader.classList.add('hidden'); projLoader.style.display = 'none'; }
        if (a && allocLoader) { allocLoader.classList.add('hidden'); allocLoader.style.display = 'none'; }
    };
    if (!data || !data.snapshot) { hideLoaders(true, true); return; }
    cachedSnapshot = data.snapshot;
    try {
        const series = (data.multi_year_projections && data.multi_year_projections.length > 0)
            ? buildProjectionSeriesForGranularity(data.multi_year_projections, activeProjGranularity) : [];
        renderProjectionChart(series);
    } catch (e) { console.error('Error rendering projection chart:', e); hideLoaders(true, false); }
    try { renderGranularAllocationChart(data.snapshot); } catch (e) { console.error('Error rendering allocation chart:', e); hideLoaders(false, true); }
    setupOverviewChartToggle();
    setupOverviewAllocToggle();
    applyWidgetEditModeUI('overview');
    if (typeof window !== 'undefined' && typeof window.hydrateWidgetCharts === 'function') window.hydrateWidgetCharts('overview');
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
    if (granContainer) granContainer.querySelectorAll('[data-granularity]').forEach(btn => btn.classList.toggle('active', btn.getAttribute('data-granularity') === gran));
}

function setupOverviewChartToggle() {
    const btnProj = document.getElementById('btn-chart-proj'), btnHist = document.getElementById('btn-chart-hist');
    const granContainer = document.getElementById('hist-granularity-controls');
    const titleEl = document.getElementById('overview-chart-title'), subEl = document.getElementById('overview-chart-sub');

    if (granContainer) {
        granContainer.style.display = 'inline-flex';
        granContainer.querySelectorAll('[data-granularity]').forEach(btn => {
            btn.onclick = () => {
                const gran = btn.getAttribute('data-granularity') || 'annual';
                syncGranularityPillUI(gran);
                if (overviewChartMode === 'projection') {
                    activeProjGranularity = gran;
                    if (window.globalProjections) renderProjectionChart(buildProjectionSeriesForGranularity(window.globalProjections, gran));
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
        btnProj.classList.add('active'); btnHist.classList.remove('active');
        if (granContainer) granContainer.style.display = 'inline-flex';
        syncGranularityPillUI(activeProjGranularity || 'annual');
        if (titleEl) titleEl.textContent = '5-Year Net Worth Trajectory';
        if (subEl) subEl.textContent = '5-year trajectory (Vested Net Worth + ongoing grant monthly vesting; unvested excluded until vested)';
        if (window.globalProjections) renderProjectionChart(buildProjectionSeriesForGranularity(window.globalProjections, activeProjGranularity || 'annual'));
    };
    btnHist.onclick = async () => {
        overviewChartMode = 'historical';
        btnHist.classList.add('active'); btnProj.classList.remove('active');
        if (granContainer) granContainer.style.display = 'inline-flex';
        if (titleEl) titleEl.textContent = 'Historical Net Worth Trajectory';
        if (subEl) {
            const hasAdj = cachedSnapshot && cachedSnapshot.company_equity && ((cachedSnapshot.company_equity.total_strike_cost_needed || 0) > 0 || (cachedSnapshot.company_equity.total_tax_drag || 0) > 0);
            subEl.textContent = hasAdj ? 'Compound growth: Net Worth, company post-tax equity, and liquid investments' : 'Compound growth: Net Worth, company equity, and liquid investments';
        }
        const loader = document.getElementById('overview-chart-loading');
        if (!historicalNetWorthData) {
            if (loader) {
                const textEl = loader.querySelector('.chart-loading-text');
                if (textEl) textEl.textContent = 'Loading Historical Net Worth...';
                loader.classList.remove('hidden'); loader.style.display = 'flex';
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
            } catch (e) { console.error('History fetch failed:', e); }
        }
        if (!activeHistGranularity) activeHistGranularity = recommendedGranularity || 'annual';
        syncGranularityPillUI(activeHistGranularity);
        const activeSeries = getSeriesForGranularity(activeHistGranularity);
        if (activeSeries && activeSeries.length) renderHistoricalChart(activeSeries);
        else if (loader) loader.classList.add('hidden');
    };
}

function getActiveWidgetIdsForPage(page) {
    const drawer = document.getElementById(`widget-customizer-drawer-${page}`);
    if (drawer && drawer.dataset.activeIds !== undefined) {
        return drawer.dataset.activeIds.split(',').map(s => s.trim()).filter(Boolean);
    }
    const grid = document.getElementById(page === 'overview' ? 'overview-widgets-grid' : 'scenarios-widgets-grid');
    return grid ? Array.from(grid.querySelectorAll('.household-widget-card[data-widget-id]')).map(el => el.getAttribute('data-widget-id')).filter(Boolean) : [];
}

function isDemoOrReadOnlySession() {
    if (typeof window !== 'undefined' && typeof window.isDemoSession === 'function' && window.isDemoSession()) return true;
    if (typeof document !== 'undefined' && document.body && (document.body.dataset.isDemo === 'true' || document.body.dataset.role === 'viewer')) return true;
    return Boolean(typeof window !== 'undefined' && window.location && new URLSearchParams(window.location.search).get('demo') === '1');
}

function applyWidgetEditModeUI(page) {
    if (typeof document === 'undefined') return;
    const isEdit = Boolean(widgetEditModeByPage[page]), drawer = document.getElementById(`widget-customizer-drawer-${page}`);
    if (drawer) drawer.style.display = isEdit ? 'block' : 'none';
    document.querySelectorAll(`.btn-toggle-widget-drawer[data-page="${page}"]`).forEach(btn => { if (!drawer || !drawer.contains(btn)) btn.style.display = isEdit ? 'none' : 'inline-flex'; });
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
    document.querySelectorAll(`.widget-inline-actions[data-page="${page}"]`).forEach(el => { el.style.display = isEdit ? 'inline-flex' : 'none'; });
}

function setWidgetEditMode(page, enabled) {
    if (!page) return;
    widgetEditModeByPage[page] = Boolean(enabled);
    applyWidgetEditModeUI(page);
}

function syncDrawerCatalogOrder(page, orderedIds, syncCheckboxes = false) {
    const drawer = document.getElementById(`widget-customizer-drawer-${page}`);
    if (drawer && Array.isArray(orderedIds)) {
        drawer.dataset.activeIds = orderedIds.join(',');
        const chks = Array.from(drawer.querySelectorAll('.chk-widget-toggle'));
        if (syncCheckboxes) chks.forEach(chk => { if (!chk.disabled) chk.checked = orderedIds.includes(chk.getAttribute('data-widget-id')); });
        const inactive = chks.filter(c => !orderedIds.includes(c.getAttribute('data-widget-id'))).map(c => c.getAttribute('data-widget-title') || '');
        document.querySelectorAll(`.widget-avail-badge[data-page="${page}"]`).forEach(b => { b.textContent = `+${inactive.length}`; b.style.display = inactive.length > 0 ? '' : 'none'; });
        document.querySelectorAll(`.widget-avail-summary[data-page="${page}"]`).forEach(s => {
            s.innerHTML = inactive.length ? `<span><strong>${inactive.length} additional graph${inactive.length !== 1 ? 's' : ''} &amp; widgets available:</strong> ${inactive.slice(0, 3).map(escapeHtml).join(' • ')}${inactive.length > 3 ? ` + ${inactive.length - 3} more` : ''}</span>` : `<span>All ${chks.length} widgets are active.</span>`;
        });
    }
    if (page === 'scenarios' && Array.isArray(orderedIds)) {
        const lbl = document.getElementById('scenarios-widgets-active-label');
        if (lbl) lbl.textContent = `FORECASTING GRAPHS & WIDGETS (${orderedIds.length} ACTIVE)`;
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
        document.cookie = (!widgetParam || widgetParam === 'default') ? `${k}=; path=/; max-age=0; SameSite=Lax` : `${k}=${encodeURIComponent(widgetParam)}; path=/; max-age=604800; SameSite=Lax`;
    } catch (e) {}
}

async function refreshWidgetGridHtmlOnly(page, widgetParam) {
    if (widgetFetchAbortByPage[page]) widgetFetchAbortByPage[page].abort();
    const ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    widgetFetchAbortByPage[page] = ctrl;
    const base = `/fragments/${page}` + (widgetParam ? `?widgets=${encodeURIComponent(widgetParam)}` : '');
    const resp = await fetch(typeof appendSessionQuery === 'function' ? appendSessionQuery(base) : base, ctrl ? { signal: ctrl.signal } : {});
    if (!resp.ok || typeof DOMParser === 'undefined') return;
    const doc = new DOMParser().parseFromString(await resp.text(), 'text/html');
    const newChartScript = doc.getElementById(`ssr-widget-charts-data-${page}`), liveChartScript = document.getElementById(`ssr-widget-charts-data-${page}`);
    if (newChartScript && liveChartScript) liveChartScript.textContent = newChartScript.textContent;
    if (widgetParam === 'default') {
        const newDrawer = doc.getElementById(`widget-customizer-drawer-${page}`);
        if (newDrawer && newDrawer.dataset.activeIds !== undefined) syncDrawerCatalogOrder(page, newDrawer.dataset.activeIds.split(',').map(s => s.trim()).filter(Boolean), true);
    }
    const gridId = page === 'overview' ? 'overview-widgets-grid' : 'scenarios-widgets-grid';
    const newGrid = doc.getElementById(gridId), liveGrid = document.getElementById(gridId);
    if (!newGrid || !liveGrid) return;
    liveGrid.innerHTML = newGrid.innerHTML;
    const latestIds = getActiveWidgetIdsForPage(page);
    if (latestIds.length) liveGrid.querySelectorAll('.household-widget-card[data-widget-id]').forEach(c => { if (!latestIds.includes(c.getAttribute('data-widget-id'))) c.remove(); });
    applyWidgetEditModeUI(page);
    if (page === 'overview' && typeof renderOverview === 'function' && window.globalDashboardData) renderOverview(window.globalDashboardData);
    if (typeof window !== 'undefined' && typeof window.hydrateWidgetCharts === 'function') window.hydrateWidgetCharts(page);
}

async function saveHouseholdWidgetPreferences(page, activeIds, reset = false, options = {}) {
    const reorderOnly = Boolean(options && options.reorderOnly);
    if (Array.isArray(activeIds)) syncDrawerCatalogOrder(page, activeIds);
    if (isDemoOrReadOnlySession()) {
        const widgetParam = reset ? 'default' : (Array.isArray(activeIds) && activeIds.length ? activeIds.join(',') : 'none');
        if (page === 'scenarios') window.__demoWidgetsScenarios = widgetParam === 'default' ? undefined : widgetParam;
        if (page === 'overview') window.__demoWidgetsOverview = widgetParam === 'default' ? undefined : widgetParam;
        setDemoWidgetCookie(page, widgetParam);
        if (reorderOnly) { applyWidgetEditModeUI(page); return; }
        try { await refreshWidgetGridHtmlOnly(page, widgetParam); } catch (e) { if (e.name !== 'AbortError') console.error(e); }
        return;
    }
    try {
        const resp = await fetch('/api/widgets/preferences', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ page, active_ids: activeIds, reset: Boolean(reset), reorder_only: true }),
            skipReactiveMorph: true,
        });
        if (!resp.ok) return;
        const res = await resp.json().catch(() => ({}));
        if (reset && Array.isArray(res.active_ids)) syncDrawerCatalogOrder(page, res.active_ids, true);
        if (!reorderOnly) await refreshWidgetGridHtmlOnly(page);
        applyWidgetEditModeUI(page);
    } catch (e) { if (e.name !== 'AbortError') console.error('Failed to save widget preferences:', e); }
}

function initHouseholdWidgetsDelegation() {
    if (typeof document === 'undefined' || document._householdWidgetsWired) return;
    document._householdWidgetsWired = true;

    document.addEventListener('click', (e) => {
        if (e.target.closest('.nav-link[data-target], .nav-item[data-target]')) {
            if (widgetEditModeByPage.overview) setWidgetEditMode('overview', false);
            if (widgetEditModeByPage.scenarios) setWidgetEditMode('scenarios', false);
            return;
        }
        const toggleBtn = e.target.closest('.btn-toggle-widget-drawer');
        if (toggleBtn) {
            const p = toggleBtn.getAttribute('data-page'), next = !widgetEditModeByPage[p];
            setWidgetEditMode(p, next);
            const drw = next && document.getElementById(`widget-customizer-drawer-${p}`);
            if (drw && typeof drw.scrollIntoView === 'function') drw.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            return;
        }
        const removeBtn = e.target.closest('.btn-widget-remove');
        if (removeBtn) {
            const page = removeBtn.getAttribute('data-page'), wid = removeBtn.getAttribute('data-widget-id');
            const nextIds = getActiveWidgetIdsForPage(page).filter(id => id !== wid);
            removeWidgetCardInPlace(page, wid, nextIds);
            saveHouseholdWidgetPreferences(page, nextIds, false, { reorderOnly: true });
            return;
        }
        const resetBtn = e.target.closest('.btn-widget-reset');
        if (resetBtn) {
            const rPage = resetBtn.getAttribute('data-page');
            if (typeof window.insertWidgetLoadingPlaceholder === 'function') window.insertWidgetLoadingPlaceholder(rPage, '', 'Default Widgets', true);
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
        const page = chk.getAttribute('data-page'), wid = chk.getAttribute('data-widget-id'), curIds = getActiveWidgetIdsForPage(page);
        if (!chk.checked) {
            const nextIds = curIds.filter(id => id !== wid);
            removeWidgetCardInPlace(page, wid, nextIds);
            saveHouseholdWidgetPreferences(page, nextIds, false, { reorderOnly: true });
        } else {
            if (typeof window.insertWidgetLoadingPlaceholder === 'function') {
                const title = chk.getAttribute('data-widget-title') || (chk.closest('.widget-catalog-item')?.querySelector('strong')?.textContent) || 'Widget';
                window.insertWidgetLoadingPlaceholder(page, wid, title, chk.getAttribute('data-full-width') === 'true');
            }
            saveHouseholdWidgetPreferences(page, curIds.includes(wid) ? curIds : [...curIds, wid], false, { reorderOnly: false });
        }
    });

    document.addEventListener('keydown', (e) => {
        const handle = e.target.closest('.widget-drag-handle');
        if (!handle || !['ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown'].includes(e.key)) return;
        e.preventDefault();
        const page = handle.getAttribute('data-page');
        if (!widgetEditModeByPage[page]) return;
        const card = handle.closest('.household-widget-card[data-widget-id]'), grid = card && card.parentElement;
        if (!card || !grid) return;
        const cards = Array.from(grid.querySelectorAll('.household-widget-card[data-widget-id]')), idx = cards.indexOf(card);
        const dir = (e.key === 'ArrowLeft' || e.key === 'ArrowUp') ? -1 : 1, targetIdx = idx + dir;
        if (targetIdx < 0 || targetIdx >= cards.length) return;
        grid.insertBefore(card, dir < 0 ? cards[targetIdx] : cards[targetIdx].nextSibling);
        handle.focus();
        saveHouseholdWidgetPreferences(page, Array.from(grid.querySelectorAll('.household-widget-card[data-widget-id]')).map(c => c.getAttribute('data-widget-id')), false, { reorderOnly: true });
    });

    let lastSwapTs = 0, dragInitialOrder = '';
    const liveReorderOnDrag = (clientY, targetEl) => {
        const grid = draggedWidgetCard && draggedWidgetCard.parentElement;
        if (!grid || Date.now() - lastSwapTs < 75) return;
        const cards = Array.from(grid.querySelectorAll('.household-widget-card[data-widget-id]'));
        if (!cards.length) return;
        const firstCard = cards[0], firstRect = firstCard.getBoundingClientRect();
        if (clientY < firstRect.top + firstRect.height * 0.42) {
            if (firstCard !== draggedWidgetCard) { grid.insertBefore(draggedWidgetCard, firstCard); lastSwapTs = Date.now(); }
            return;
        }
        const hovered = targetEl && targetEl.closest ? targetEl.closest('.household-widget-card[data-widget-id]') : null;
        if (!hovered || hovered === draggedWidgetCard || hovered.parentElement !== grid) return;
        const rect = hovered.getBoundingClientRect(), relY = clientY - rect.top;
        if (relY < rect.height * 0.42 && hovered.previousElementSibling !== draggedWidgetCard) {
            grid.insertBefore(draggedWidgetCard, hovered); lastSwapTs = Date.now();
        } else if (relY > rect.height * 0.58 && hovered.nextElementSibling !== draggedWidgetCard) {
            grid.insertBefore(draggedWidgetCard, hovered.nextSibling); lastSwapTs = Date.now();
        }
    };

    const startCardDrag = (card) => {
        draggedWidgetCard = card; lastSwapTs = 0;
        const grid = card.parentElement;
        dragInitialOrder = grid ? Array.from(grid.querySelectorAll('.household-widget-card[data-widget-id]')).map(el => el.getAttribute('data-widget-id')).join(',') : '';
        card.style.opacity = '0.6'; card.style.outline = '2px solid #3B82F6';
    };

    const finishWidgetDrag = () => {
        if (!draggedWidgetCard) return;
        const card = draggedWidgetCard, grid = card.parentElement;
        draggedWidgetCard = null; card.style.opacity = '';
        if (!grid) return;
        const page = grid.id === 'overview-widgets-grid' ? 'overview' : 'scenarios';
        applyWidgetEditModeUI(page);
        const nextIds = Array.from(grid.querySelectorAll('.household-widget-card[data-widget-id]')).map(el => el.getAttribute('data-widget-id')).filter(Boolean);
        if (nextIds.join(',') !== dragInitialOrder) saveHouseholdWidgetPreferences(page, nextIds, false, { reorderOnly: true });
    };

    document.addEventListener('dragstart', (e) => {
        const card = e.target.closest('.household-widget-card[data-widget-id]');
        if (!card) return;
        const page = card.parentElement && card.parentElement.id === 'overview-widgets-grid' ? 'overview' : 'scenarios';
        if (!widgetEditModeByPage[page]) { e.preventDefault(); return; }
        startCardDrag(card);
        if (e.dataTransfer) { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', card.getAttribute('data-widget-id') || ''); }
    });
    document.addEventListener('dragover', (e) => { if (draggedWidgetCard) { e.preventDefault(); if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'; liveReorderOnDrag(e.clientY, e.target); } });
    document.addEventListener('drop', (e) => { if (draggedWidgetCard) { e.preventDefault(); finishWidgetDrag(); } });
    document.addEventListener('dragend', finishWidgetDrag);
    document.addEventListener('touchstart', (e) => {
        const handle = e.target.closest('.widget-drag-handle'), card = handle && handle.closest('.household-widget-card[data-widget-id]');
        if (!card || !widgetEditModeByPage[handle.getAttribute('data-page')]) return;
        if (e.cancelable) e.preventDefault();
        startCardDrag(card);
    }, { passive: false });
    document.addEventListener('touchmove', (e) => {
        const t = draggedWidgetCard && e.touches && e.touches[0];
        if (!t) return;
        if (e.cancelable) e.preventDefault();
        if (typeof window.scrollBy === 'function') {
            const hdr = document.querySelector('.top-header'), topEdge = (hdr ? Math.max(0, hdr.getBoundingClientRect().bottom) : 0) + 55;
            if (t.clientY < topEdge) window.scrollBy(0, -16); else if (t.clientY > window.innerHeight - 85) window.scrollBy(0, 16);
        }
        liveReorderOnDrag(t.clientY, typeof document.elementFromPoint === 'function' ? document.elementFromPoint(t.clientX, t.clientY) : null);
    }, { passive: false });
    document.addEventListener('touchend', () => { if (draggedWidgetCard) finishWidgetDrag(); });
    document.addEventListener('touchcancel', () => { if (draggedWidgetCard) finishWidgetDrag(); });
}

if (typeof window !== 'undefined') {
    Object.assign(window, { renderOverview, setupOverviewChartToggle, setupOverviewAllocToggle, getSeriesForGranularity, syncGranularityPillUI, saveHouseholdWidgetPreferences, setWidgetEditMode, applyWidgetEditModeUI });
    initHouseholdWidgetsDelegation();
    if (typeof window.registerSectionHydrator === 'function') {
        window.registerSectionHydrator('section-overview', renderOverview, {
            needsDashboard: true,
            onInvalidate: () => { historicalNetWorthData = null; monthlyNetWorthData = null; quarterlyNetWorthData = null; historicalSavingsData = null; if (typeof cachedSnapshot !== 'undefined') cachedSnapshot = null; }
        });
    }
}
