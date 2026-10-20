/**
 * HVL Family Office - App Hydration & Declarative Section Subscriber Controller
 * Binds SSR section fragments (data-depends="...") and client-side hydrators
 * (registerSectionHydrator) to domain version signals.
 */

var currentViewMode = (typeof window !== 'undefined' && window.currentViewMode) ? window.currentViewMode : 'focused';
var currentSectionId = (typeof window !== 'undefined' && (window.currentSectionId || window.INITIAL_ACTIVE_SECTION)) || 'section-overview';
var globalDashboardData = (typeof window !== 'undefined' && window.globalDashboardData) ? window.globalDashboardData : null;
var globalSnapshot = (typeof window !== 'undefined' && window.globalSnapshot) ? window.globalSnapshot : null;
var globalProjections = (typeof window !== 'undefined' && window.globalProjections) ? window.globalProjections : null;

const DEFAULT_SECTION_DEPENDS = (typeof window !== 'undefined' && window.__SECTION_DEPENDS__) ? window.__SECTION_DEPENDS__ : {
    'section-overview': ['balance_sheet', 'accounts', 'equity', 'scenarios', 'household.identity', 'household.members', 'onboarding.checklist'],
    'section-equity': ['equity', 'balance_sheet', 'tax_profile'],
    'section-scenarios': ['balance_sheet', 'accounts', 'holdings', 'equity', 'tax_profile', 'compensation', 'household.members', 'household.identity', 'college', 'philanthropy', 'gifting', 'estate'],
    'section-holdings': ['holdings', 'holdings.policy', 'accounts', 'balance_sheet'],
    'section-arbitrage': ['tax_profile', 'compensation', 'equity', 'household.identity'],
    'section-compensation': ['compensation', 'tax_profile', 'household.members'],
    'section-philanthropy': ['philanthropy', 'tax_profile'],
    'section-gifting': ['gifting', 'household.members'],
    'section-estate': ['estate', 'balance_sheet', 'gifting', 'household.members', 'household.identity'],
    'section-college': ['college', 'accounts', 'household.members'],
    'section-accounts': ['accounts', 'holdings', 'balance_sheet']
};

const DASHBOARD_DOMAINS = new Set([
    'balance_sheet', 'accounts', 'holdings', 'holdings.policy',
    'equity', 'scenarios', 'onboarding.checklist'
]);

const dashboardDataSignal = createSignal(0);
const sectionHydrators = new Map();
const sectionHydratedSig = new Map();
const inFlightSectionMorphs = new Map();

function getSectionDomains(secElOrId) {
    const secEl = typeof secElOrId === 'string' ? document.getElementById(secElOrId) : secElOrId;
    const secId = typeof secElOrId === 'string' ? secElOrId : (secEl ? secEl.id : '');
    const rawAttr = secEl && secEl.dataset && secEl.dataset.depends;
    if (rawAttr) {
        return rawAttr.split(',').map(s => s.trim()).filter(Boolean);
    }
    const secMap = (typeof window !== 'undefined' && window.__SECTION_DEPENDS__) ? window.__SECTION_DEPENDS__ : DEFAULT_SECTION_DEPENDS;
    return secMap[secId] || DEFAULT_SECTION_DEPENDS[secId] || [];
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
    if (!sectionId || typeof hydrateFn !== 'function') return;
    sectionHydrators.set(sectionId, {
        hydrateFn,
        morphFn: typeof options.morphFn === 'function' ? options.morphFn : null,
        needsDashboard: Boolean(options.needsDashboard),
        onInvalidate: typeof options.onInvalidate === 'function' ? options.onInvalidate : null
    });
}

function applyViewMode(isInitial = false) {
    window.currentSectionId = currentSectionId;
    let sections = document.querySelectorAll('.page-section');
    const headerTitle = document.getElementById('page-header-title');
    const mobileNavSelect = document.getElementById('mobile-nav-select');
    const btnTabs = document.getElementById('btn-view-tabs');
    const btnAll = document.getElementById('btn-view-all');

    if (mobileNavSelect) {
        mobileNavSelect.value = currentSectionId;
    }
    if (!isInitial && typeof window.setWidgetEditMode === 'function') {
        if (currentSectionId !== 'section-overview') window.setWidgetEditMode('overview', false);
        if (currentSectionId !== 'section-scenarios') window.setWidgetEditMode('scenarios', false);
    }

    if (currentViewMode === 'focused') {
        if (btnTabs) btnTabs.classList.add('active');
        if (btnAll) btnAll.classList.remove('active');

        const targetSec = document.getElementById(currentSectionId);
        sections.forEach(sec => {
            sec.style.display = (sec.id === currentSectionId) ? 'block' : 'none';
        });

        if (headerTitle && !isInitial) {
            headerTitle.textContent = (window.SECTION_TITLES && window.SECTION_TITLES[currentSectionId]) || 'Overview & Net Worth';
        }
        if (!isInitial) {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
        if (typeof updateAdvisorContext === 'function') {
            updateAdvisorContext(currentSectionId);
        }

        const onTabReady = () => {
            hydrateSection(currentSectionId);
            if (currentSectionId === 'section-philanthropy' && typeof scrollPhilanthropyToCurrentYear === 'function') {
                setTimeout(scrollPhilanthropyToCurrentYear, 60);
            }
            if (currentSectionId === 'section-gifting' && typeof scrollGiftingToCurrentYear === 'function') {
                setTimeout(scrollGiftingToCurrentYear, 60);
            }
            if (currentSectionId === 'section-scenarios' && typeof renderActiveLensChart === 'function') {
                setTimeout(renderActiveLensChart, 50);
            }
        };

        if (targetSec && targetSec.dataset.loaded !== 'true') {
            const fragName = targetSec.dataset.fragment || currentSectionId.replace('section-', '');
            const title = (window.SECTION_TITLES && window.SECTION_TITLES[currentSectionId]) || 'Financial View';
            if (!targetSec.innerHTML.trim()) {
                targetSec.innerHTML = `
                    <div class="fragment-loading-skeleton" style="display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 420px; gap: 16px; color: var(--text-muted); background: var(--bg-surface); border-radius: 12px; border: 1px solid var(--border-subtle); padding: 40px 20px;">
                        <div class="chart-spinner"></div>
                        <span style="font-size: 0.875rem; font-weight: 600; color: var(--text-secondary);">Loading ${escapeHtml(title)}...</span>
                    </div>
                `;
            }
            window.htmx.ajax('GET', appendSessionQuery(`/fragments/${fragName}`), {
                source: targetSec,
                target: targetSec,
                swap: 'morph'
            }).then(() => {
                const updatedSec = document.getElementById(currentSectionId) || targetSec;
                updatedSec.dataset.loaded = 'true';
                updatedSec.style.display = 'block';
                sections = document.querySelectorAll('.page-section');
                onTabReady();
            }).catch(() => {
                targetSec.innerHTML = `
                    <div style="padding: 40px; text-align: center; color: var(--status-red);">
                        <p style="font-weight: 600;">Failed to load ${escapeHtml(title)}.</p>
                        <button type="button" class="btn btn-secondary btn-sm" onclick="navigateToSection('${currentSectionId}')" style="margin-top: 10px;">Retry</button>
                    </div>
                `;
            });
        } else {
            onTabReady();
        }
    } else {
        if (btnTabs) btnTabs.classList.remove('active');
        if (btnAll) btnAll.classList.add('active');

        sections.forEach(sec => {
            sec.style.display = 'block';
            if (sec.dataset.loaded !== 'true') {
                const fragName = sec.dataset.fragment || sec.id.replace('section-', '');
                window.htmx.ajax('GET', appendSessionQuery(`/fragments/${fragName}`), {
                    source: sec,
                    target: sec,
                    swap: 'morph'
                }).then(() => {
                    const updatedSec = document.getElementById(sec.id) || sec;
                    updatedSec.dataset.loaded = 'true';
                    updatedSec.style.display = 'block';
                    sections = document.querySelectorAll('.page-section');
                    hydrateSection(sec.id);
                });
            }
        });

        document.querySelectorAll('.comp-subtab-pane').forEach(pane => {
            pane.style.display = 'block';
        });

        hydrateAllSections();
        if (headerTitle) {
            headerTitle.textContent = 'All Financial Views (Consolidated Portfolio)';
        }
        if (typeof updateActiveSectionFromScroll === 'function') {
            updateActiveSectionFromScroll();
        }
    }
}

var dashboardDataStale = false;

function hydrateSection(sectionId) {
    const secEl = document.getElementById(sectionId);
    if (secEl && secEl.dataset.loaded === 'false') return;
    const entry = sectionHydrators.get(sectionId);
    if (!entry) return;
    if (entry.needsDashboard && dashboardDataStale && typeof fetchDashboardData === 'function') {
        dashboardDataStale = false;
        fetchDashboardData();
        return;
    }
    if (entry.needsDashboard && !globalDashboardData) return;
    const sig = getSectionVersionSignature(sectionId, entry);
    if (sectionHydratedSig.get(sectionId) === sig) return;
    sectionHydratedSig.set(sectionId, sig);
    try {
        if (entry.needsDashboard) {
            entry.hydrateFn(globalDashboardData);
        } else {
            entry.hydrateFn();
        }
    } catch (e) {
        console.error(`Error hydrating ${sectionId}:`, e);
    }
}

function hydrateAllSections() {
    if (window.SECTION_TO_PATH) {
        Object.keys(window.SECTION_TO_PATH).forEach(secId => hydrateSection(secId));
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
        const wasHidden = secEl.style.display === 'none';
        const entry = sectionHydrators.get(secId);
        const customMorphFn = entry && entry.morphFn;
        if (typeof customMorphFn === 'function') {
            await customMorphFn();
            const updated = document.getElementById(secId) || secEl;
            updated.dataset.loaded = 'true';
            if (wasHidden && currentViewMode !== 'all') updated.style.display = 'none';
            return;
        }
        if (typeof window.htmx?.ajax !== 'function') return;
        const fragName = secEl.dataset.fragment || secId.replace('section-', '');
        await window.htmx.ajax('GET', appendSessionQuery(`/fragments/${fragName}`), {
            source: secEl, target: `#${secId}`, swap: 'morph'
        });
        const updated = document.getElementById(secId) || secEl;
        updated.dataset.loaded = 'true';
        updated.style.display = (wasHidden && currentViewMode !== 'all') ? 'none' : 'block';
        if (secId === 'section-accounts' && typeof window.bindAccountToggles === 'function') {
            window.bindAccountToggles();
        }
        if (secId === 'section-overview' && typeof window.applyWidgetEditModeUI === 'function') {
            window.applyWidgetEditModeUI('overview');
        }
    })();

    inFlightSectionMorphs.set(secId, promise);
    try { return await promise; } finally { inFlightSectionMorphs.delete(secId); }
}

async function applyDomainVersions(nextVersions, options = {}) {
    if (!nextVersions || typeof nextVersions !== 'object') return [];
    const changed = [];
    batch(() => {
        Object.entries(nextVersions).forEach(([domKey, rawVer]) => {
            const ver = Number(rawVer);
            if (!Number.isFinite(ver)) return;
            const sig = getDomainSignal(domKey);
            if (sig.peek() !== ver) {
                sig.value = ver;
                changed.push(domKey);
            }
        });
    });

    if (typeof window !== 'undefined') {
        window.__DOMAIN_VERSIONS__ = Object.assign({}, window.__DOMAIN_VERSIONS__ || {}, nextVersions);
    }
    if (changed.length === 0 && !options.force) return [];
    if (window.SandboxManager && typeof window.SandboxManager.markHasData === 'function') {
        window.SandboxManager.markHasData();
    }

    const changedSet = new Set(changed);
    const activeId = currentSectionId || 'section-overview';
    const allSections = document.querySelectorAll('.page-section');

    for (const sec of allSections) {
        const deps = getSectionDomains(sec);
        if (!deps.some(d => changedSet.has(d))) continue;
        sectionHydratedSig.delete(sec.id);
        const entry = sectionHydrators.get(sec.id);
        if (entry && typeof entry.onInvalidate === 'function') {
            try { entry.onInvalidate(); } catch (e) {}
        }
        const isVisible = currentViewMode === 'all' || sec.id === activeId;
        if (isVisible) {
            try { await morphSectionFragment(sec); } catch (e) { console.warn(`Reactive fragment morph warning (${sec.id}):`, e); }
        } else {
            sec.dataset.loaded = 'false';
        }
    }

    const dashDomainBumped = changed.some(d => DASHBOARD_DOMAINS.has(d));
    const activeEntry = sectionHydrators.get(activeId);
    const activeNeedsDash = currentViewMode === 'all' || activeId === 'section-overview' || Boolean(activeEntry && activeEntry.needsDashboard);

    if (dashDomainBumped) {
        if (activeNeedsDash && typeof fetchDashboardData === 'function') {
            dashboardDataStale = false;
            await fetchDashboardData();
        } else {
            dashboardDataStale = true;
            hydrateSection(activeId);
        }
    } else if (currentViewMode === 'all') {
        hydrateAllSections();
    } else {
        hydrateSection(activeId);
    }
    return changed;
}

async function bumpDomains(domains) {
    const list = Array.isArray(domains) ? domains : [domains];
    const snap = getDomainVersionsSnapshot();
    const next = {};
    list.forEach(d => { if (d) next[d] = (Number(snap[d]) || 1) + 1; });
    return await applyDomainVersions(next);
}

async function fetchDashboardData() {
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

        const timeEl = document.getElementById('sync-timestamp');
        if (timeEl && globalSnapshot?.last_monarch_sync && globalSnapshot.last_monarch_sync !== 'Never') {
            const d = new Date(globalSnapshot.last_monarch_sync);
            if (!isNaN(d.getTime())) {
                const datePart = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
                const timePart = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                timeEl.textContent = `Last Synced: ${datePart}, ${timePart}`;
            }
        }

        if (currentViewMode === 'all') hydrateAllSections();
        else if (currentSectionId) hydrateSection(currentSectionId);
    } catch (err) {
        console.error('Failed to load dashboard:', err);
        dismissOverviewChartLoaders();
    }
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        getSectionDomains, registerSectionHydrator, applyDomainVersions, bumpDomains,
        applyViewMode, hydrateSection, hydrateAllSections, dismissOverviewChartLoaders,
        morphSectionFragment, fetchDashboardData
    });
}
