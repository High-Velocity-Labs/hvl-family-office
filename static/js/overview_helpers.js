/**
 * Overview & Scenarios Household Widget Customizer & Reorder Helpers
 * Manages widget catalog drawer, preference persistence, and keyboard/click delegation.
 */

var widgetEditModeByPage = { overview: false, scenarios: false };
var widgetFetchAbortByPage = { overview: null, scenarios: null };

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
            b.style.display = inactive.length > 0 ? '' : 'none';
        });

        document.querySelectorAll(`.widget-avail-summary[data-page="${page}"]`).forEach(s => {
            if (inactive.length) {
                const preview = inactive.slice(0, 3).map(escapeHtml).join(' • ');
                const extra = inactive.length > 3 ? ` + ${inactive.length - 3} more` : '';
                s.innerHTML = `<span><strong>${inactive.length} additional graph${inactive.length !== 1 ? 's' : ''} &amp; widgets available:</strong> ${preview}${extra}</span>`;
            } else {
                s.innerHTML = `<span>All ${chks.length} widgets are active.</span>`;
            }
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

async function refreshWidgetGridHtmlOnly(page, widgetParam) {
    if (widgetFetchAbortByPage[page]) {
        widgetFetchAbortByPage[page].abort();
    }

    const ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    widgetFetchAbortByPage[page] = ctrl;
    const base = `/fragments/${page}` + (widgetParam ? `?widgets=${encodeURIComponent(widgetParam)}` : '');
    const reqUrl = typeof appendSessionQuery === 'function' ? appendSessionQuery(base) : base;
    const resp = await fetch(reqUrl, ctrl ? { signal: ctrl.signal } : {});
    if (!resp.ok || typeof DOMParser === 'undefined') return;

    const doc = new DOMParser().parseFromString(await resp.text(), 'text/html');
    const newChartScript = doc.getElementById(`ssr-widget-charts-data-${page}`);
    const liveChartScript = document.getElementById(`ssr-widget-charts-data-${page}`);
    if (newChartScript && liveChartScript) {
        liveChartScript.textContent = newChartScript.textContent;
    }

    if (widgetParam === 'default') {
        const newDrawer = doc.getElementById(`widget-customizer-drawer-${page}`);
        if (newDrawer && newDrawer.dataset.activeIds !== undefined) {
            const parsedIds = newDrawer.dataset.activeIds.split(',').map(s => s.trim()).filter(Boolean);
            syncDrawerCatalogOrder(page, parsedIds, true);
        }
    }

    const gridId = page === 'overview' ? 'overview-widgets-grid' : 'scenarios-widgets-grid';
    const newGrid = doc.getElementById(gridId);
    const liveGrid = document.getElementById(gridId);
    if (!newGrid || !liveGrid) return;

    liveGrid.innerHTML = newGrid.innerHTML;
    const latestIds = getActiveWidgetIdsForPage(page);
    if (latestIds.length) {
        liveGrid.querySelectorAll('.household-widget-card[data-widget-id]').forEach(c => {
            if (!latestIds.includes(c.getAttribute('data-widget-id'))) {
                c.remove();
            }
        });
    }

    applyWidgetEditModeUI(page);
    if (page === 'overview' && typeof renderOverview === 'function' && window.globalDashboardData) {
        renderOverview(window.globalDashboardData);
    }
    if (typeof window !== 'undefined' && typeof window.hydrateWidgetCharts === 'function') {
        window.hydrateWidgetCharts(page);
    }
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
            await refreshWidgetGridHtmlOnly(page, widgetParam);
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
            await refreshWidgetGridHtmlOnly(page);
        }
        applyWidgetEditModeUI(page);
    } catch (e) {
        if (e.name !== 'AbortError') {
            console.error('Failed to save widget preferences:', e);
        }
    }
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
            if (typeof window.insertWidgetLoadingPlaceholder === 'function') {
                window.insertWidgetLoadingPlaceholder(rPage, '', 'Default Widgets', true);
            }
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
            if (typeof window.insertWidgetLoadingPlaceholder === 'function') {
                const title = chk.getAttribute('data-widget-title')
                    || (chk.closest('.widget-catalog-item')?.querySelector('strong')?.textContent)
                    || 'Widget';
                window.insertWidgetLoadingPlaceholder(page, wid, title, chk.getAttribute('data-full-width') === 'true');
            }
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
        if (typeof window !== 'undefined' && typeof window.animateWidgetGridLayout === 'function') {
            window.animateWidgetGridLayout(grid, reorderDom, () => handle.focus());
        } else {
            reorderDom();
            handle.focus();
        }
        const ordered = Array.from(grid.querySelectorAll('.household-widget-card[data-widget-id]'))
            .map(c => c.getAttribute('data-widget-id'));
        saveHouseholdWidgetPreferences(page, ordered, false, { reorderOnly: true });
    });

    if (typeof bindWidgetDragAndTouchEvents === 'function') {
        bindWidgetDragAndTouchEvents();
    }
}
