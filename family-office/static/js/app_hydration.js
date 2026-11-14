/**
 * HVL Family Office - App Hydration & Declarative Section Subscriber Controller
 * Binds SSR section fragments (data-depends="...") and client-side hydrators
 * (registerSectionHydrator) to domain version signals.
 */

// `currentSectionId` is owned by app_navigation.js (loaded first); this module only reads it.
var globalDashboardData = window.globalDashboardData || null;
var globalSnapshot = window.globalSnapshot || null;
var globalProjections = window.globalProjections || null;

const DASHBOARD_DOMAINS = new Set([
    'balance_sheet', 'accounts', 'holdings', 'holdings.policy',
    'equity', 'scenarios', 'onboarding.checklist'
]);

var dashboardDataSignal = createSignal(0);
var sectionHydrators = sectionHydrators || new Map();
var sectionHydratedSig = sectionHydratedSig || new Map();
var inFlightSectionMorphs = inFlightSectionMorphs || new Map();

// Sections with unsaved local edits (e.g. a what-if) register a guard; a server-driven morph never overwrites them.
var unsavedGuards = unsavedGuards || new Map();
var deferredSectionMorphs = deferredSectionMorphs || new Set();

function registerUnsavedGuard(sectionId, isDirtyFn) {
    unsavedGuards.set(sectionId, isDirtyFn);
}

function sectionHasUnsavedEdits(sectionId) {
    const guard = unsavedGuards.get(sectionId);
    return Boolean(guard && guard());
}

registerUnsavedGuard('section-scenarios', () => {
    const saveBtn = document.getElementById('btn-save-to-plan');
    return Boolean(saveBtn && !saveBtn.disabled);
});

async function flushDeferredSectionMorphs() {
    for (const secId of Array.from(deferredSectionMorphs)) {
        if (sectionHasUnsavedEdits(secId)) continue;
        deferredSectionMorphs.delete(secId);
        const sec = document.getElementById(secId);
        if (!sec) continue;
        if (secId === currentSectionId) {
            await morphSectionFragment(sec);
        } else {
            sec.dataset.state = 'stale';
        }
    }
}

['click', 'change'].forEach(evt => document.addEventListener(evt, () => {
    if (deferredSectionMorphs.size > 0) flushDeferredSectionMorphs();
}));

function getSectionDomains(secElOrId) {
    const secEl = typeof secElOrId === 'string' ? document.getElementById(secElOrId) : secElOrId;
    // `data-depends` is rendered by the server from ssr/section_depends.py; the browser keeps no copy.
    const rawAttr = secEl && secEl.dataset && secEl.dataset.depends;
    return rawAttr ? rawAttr.split(',').map(s => s.trim()).filter(Boolean) : [];
}

function getSectionVersionSignature(sectionId, entry) {
    const domains = getSectionDomains(sectionId);
    const parts = domains.map(d => `${d}:${getDomainSignal(d).value}`);
    if (entry && entry.needsDashboard) {
        parts.push(`dash:${dashboardDataSignal.value}`);
    }
    return parts.join('|');
}

function registerSectionHydrator(sectionId, hydrateFn, options = {}) {
    sectionHydrators.set(sectionId, {
        hydrateFn,
        morphFn: options.morphFn || null,
        needsDashboard: Boolean(options.needsDashboard),
        onInvalidate: options.onInvalidate || null
    });
}

var dashboardDataStale = false;

function hydrateSection(sectionId) {
    if (deferredSectionMorphs.has(sectionId)) flushDeferredSectionMorphs();
    const secEl = document.getElementById(sectionId);
    if (secEl && secEl.dataset.state !== 'ready') return;
    const entry = sectionHydrators.get(sectionId);
    if (!entry) return;
    // `/api/dashboard` is fetched only when a section that reads it is shown, never for the overview (its
    // fragment carries its own chart data).
    if (entry.needsDashboard && (dashboardDataStale || !globalDashboardData)) {
        dashboardDataStale = false;
        fetchDashboardData();
        return;
    }
    const sig = getSectionVersionSignature(sectionId, entry);
    if (sectionHydratedSig.get(sectionId) === sig) return;
    sectionHydratedSig.set(sectionId, sig);
    try {
        entry.hydrateFn(entry.needsDashboard ? globalDashboardData : undefined);
    } catch (e) {
        console.error(`Error hydrating ${sectionId}:`, e);
    }
}

function dismissOverviewChartLoaders() {
    const pLoader = document.getElementById('overview-chart-loading');
    if (pLoader) pLoader.classList.add('hidden');
    const aLoader = document.getElementById('overview-alloc-loading');
    if (aLoader) aLoader.classList.add('hidden');
}

async function morphSectionFragment(secEl) {
    if (!secEl) return;
    const secId = secEl.id;
    if (inFlightSectionMorphs.has(secId)) return inFlightSectionMorphs.get(secId);

    const promise = (async () => {
        const savedScrollY = window.scrollY || 0;
        const savedScrollX = window.scrollX || 0;
        const wasVisible = !secEl.hidden;
        const customMorphFn = sectionHydrators.get(secId)?.morphFn;
        if (customMorphFn) {
            await customMorphFn();
            return;
        }
        const fragName = secEl.dataset.fragment || secId.replace('section-', '');
        await window.htmx.ajax('GET', appendSessionQuery(`/fragments/${fragName}`), {
            source: secEl, target: `#${secId}`, swap: 'morph'
        });
        if (secId === 'section-accounts') window.bindAccountToggles();
        if (secId === 'section-overview') window.applyWidgetEditModeUI('overview');
        if (wasVisible && Math.abs((window.scrollY || 0) - savedScrollY) > 2) {
            window.scrollTo(savedScrollX, savedScrollY);
        }
    })();

    inFlightSectionMorphs.set(secId, promise);
    try { return await promise; } finally { inFlightSectionMorphs.delete(secId); }
}

async function applyDomainVersions(nextVersions, options = {}) {
    if (!nextVersions) return [];
    await flushDeferredSectionMorphs();
    const changed = [];
    batch(() => {
        Object.entries(nextVersions).forEach(([domKey, rawVer]) => {
            const ver = Number(rawVer);
            if (!Number.isFinite(ver)) return;
            const sig = getDomainSignal(domKey);
            if (ver > sig.peek() || (options.force && ver !== sig.peek())) {
                sig.value = ver;
                changed.push(domKey);
            }
        });
    });

    window.__DOMAIN_VERSIONS__ = Object.assign({}, window.__DOMAIN_VERSIONS__ || {}, getDomainVersionsSnapshot());
    if (changed.length === 0 && !options.force) return [];
    if (window.SandboxManager) window.SandboxManager.markHasData();

    const changedSet = new Set(changed);
    const activeId = currentSectionId || 'section-overview';
    const allSections = document.querySelectorAll('.page-section');

    for (const sec of allSections) {
        const deps = getSectionDomains(sec);
        if (!deps.some(d => changedSet.has(d))) continue;
        if (sectionHasUnsavedEdits(sec.id)) {
            deferredSectionMorphs.add(sec.id);
            continue;
        }
        sectionHydratedSig.delete(sec.id);
        const entry = sectionHydrators.get(sec.id);
        if (entry && entry.onInvalidate) {
            try { entry.onInvalidate(); } catch (e) {}
        }
        if (sec.id === activeId) {
            try {
                await morphSectionFragment(sec);
            } catch (e) {
                console.warn(`Reactive fragment morph warning (${sec.id}):`, e);
            }
        } else {
            sec.dataset.state = 'stale';
        }
    }

    const dashDomainBumped = changed.some(d => DASHBOARD_DOMAINS.has(d));
    const activeEntry = sectionHydrators.get(activeId);
    const activeNeedsDash = Boolean(activeEntry && activeEntry.needsDashboard);

    if (dashDomainBumped) {
        if (activeNeedsDash) {
            dashboardDataStale = false;
            await fetchDashboardData();
        } else {
            dashboardDataStale = true;
            hydrateSection(activeId);
        }
    } else {
        hydrateSection(activeId);
    }
    return changed;
}

var dashboardFetchInFlight = null;
var dashboardFetchQueued = null;

// One fetch at a time. A call while one runs queues a single follow-up fetch (shared by every caller meanwhile), so
// a fetch that started before a mutation never stands in for the data after it.
function fetchDashboardData() {
    if (!dashboardFetchInFlight) {
        dashboardFetchInFlight = loadDashboardData().finally(() => { dashboardFetchInFlight = null; });
        return dashboardFetchInFlight;
    }
    if (!dashboardFetchQueued) {
        dashboardFetchQueued = dashboardFetchInFlight.then(() => {
            dashboardFetchQueued = null;
            return fetchDashboardData();
        });
    }
    return dashboardFetchQueued;
}

async function loadDashboardData() {
    try {
        const resp = await fetch('/api/dashboard');
        if (resp.status === 401) { window.location.href = '/login'; return; }
        const data = await resp.json();
        if (!data.success) {
            console.error('API Error:', data.error);
            dismissOverviewChartLoaders();
            return;
        }
        globalDashboardData = data;
        globalSnapshot = data.snapshot || {};
        globalProjections = data.multi_year_projections || [];
        dashboardDataSignal.value = dashboardDataSignal.peek() + 1;

        if (Array.isArray(globalSnapshot.all_accounts)) {
            const accCount = globalSnapshot.all_accounts.length;
            const navLabel = document.getElementById('accounts-nav-label');
            if (navLabel) navLabel.textContent = `Accounts (${accCount})`;
            if (window.SECTION_TITLES) window.SECTION_TITLES['section-accounts'] = `Accounts & Holdings (${accCount})`;
            if (currentSectionId === 'section-accounts') {
                const headerTitle = document.getElementById('page-header-title');
                if (headerTitle && window.SECTION_TITLES) headerTitle.textContent = window.SECTION_TITLES['section-accounts'];
            }
        }

        if (globalSnapshot?.last_monarch_sync) {
            window.updateSyncTimestampDOM(globalSnapshot.last_monarch_sync);
        }

        hydrateSection(currentSectionId);
    } catch (err) {
        console.error('Failed to load dashboard:', err);
        dismissOverviewChartLoaders();
    }
}

Object.assign(window, {
    getSectionDomains, registerSectionHydrator, registerUnsavedGuard, flushDeferredSectionMorphs,
    applyDomainVersions, hydrateSection, dismissOverviewChartLoaders, morphSectionFragment, fetchDashboardData
});
