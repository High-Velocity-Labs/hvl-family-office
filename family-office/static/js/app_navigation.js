/**
 * HVL Family Office - Section Navigation
 * Navigation is declarative HTMX: every nav link carries hx-get / hx-target / hx-swap="morph" / hx-push-url
 * (templates/components/nav_macros.html) and back/forward is htmx history over `.content-body` (hx-history-elt).
 * This file owns the one section lifecycle (stale -> loading -> ready | error), keeps the active section visible,
 * and reacts to htmx events. It is the single owner of the `currentSectionId` global (app_hydration.js reads it).
 */

var currentSectionId = window.currentSectionId || window.INITIAL_ACTIVE_SECTION || 'section-overview';

var SECTION_TITLES = {
    'section-overview': 'Overview & Net Worth',
    'section-equity': 'Company Equity',
    'section-scenarios': 'Forecasting',
    'section-retirement': 'Forecasting',
    'section-holdings': 'Investments',
    'section-arbitrage': 'Multi-State Arbitrage',
    'section-withholding': 'Compensation & Taxes',
    'section-philanthropy': 'Philanthropy',
    'section-gifting': 'Family Gifting',
    'section-estate': 'Estate & Trusts',
    'section-college': 'Education',
    'section-transcripts': 'Compensation & Taxes',
    'section-compensation': 'Compensation & Taxes',
    'section-accounts': 'Accounts & Holdings'
};

var SECTION_TO_PATH = {
    'section-overview': '/',
    'section-equity': '/company-equity',
    'section-scenarios': '/forecasting',
    'section-holdings': '/holdings',
    'section-arbitrage': '/arbitrage',
    'section-compensation': '/compensation',
    'section-philanthropy': '/philanthropy',
    'section-gifting': '/gifting',
    'section-estate': '/estate',
    'section-college': '/college',
    'section-accounts': '/accounts'
};

var PATH_TO_SECTION = {
    '/': 'section-overview',
    '/overview': 'section-overview',
    '/company-equity': 'section-equity',
    '/equity': 'section-equity',
    '/forecasting': 'section-scenarios',
    '/scenarios': 'section-scenarios',
    '/retirement': 'section-scenarios',
    '/holdings': 'section-holdings',
    '/investments': 'section-holdings',
    '/arbitrage': 'section-arbitrage',
    '/compensation': 'section-compensation',
    '/withholding': 'section-compensation',
    '/transcripts': 'section-compensation',
    '/philanthropy': 'section-philanthropy',
    '/gifting': 'section-gifting',
    '/estate': 'section-estate',
    '/college': 'section-college',
    '/education': 'section-college',
    '/accounts': 'section-accounts'
};

var HASH_TO_SECTION = {
    '#overview': 'section-overview',
    '#company-equity': 'section-equity',
    '#equity': 'section-equity',
    '#forecasting': 'section-scenarios',
    '#scenarios': 'section-scenarios',
    '#retirement': 'section-scenarios',
    '#holdings': 'section-holdings',
    '#investments': 'section-holdings',
    '#arbitrage': 'section-arbitrage',
    '#compensation': 'section-compensation',
    '#withholding': 'section-compensation',
    '#transcripts': 'section-compensation',
    '#safeharbor': 'section-compensation',
    '#philanthropy': 'section-philanthropy',
    '#gifting': 'section-gifting',
    '#estate': 'section-estate',
    '#college': 'section-college',
    '#education': 'section-college',
    '#accounts': 'section-accounts'
};


const SECTION_TRANSITIONS = {
    stale: ['loading'],
    loading: ['ready', 'error'],
    ready: ['stale'],
    error: ['loading', 'stale']
};

// Run when an already-loaded section is shown again (its charts were drawn while it was hidden). A swap that loads
// a section does not run them: the section's own swap hydration draws from the data the swap brought.
const SECTION_SHOWN_HOOKS = {
    'section-scenarios': () => setTimeout(window.renderActiveLensChart, 50)
};

function getSectionState(sec) {
    return sec ? (sec.dataset.state || 'stale') : null;
}

function transitionSection(sec, next) {
    if (!sec) return false;
    const current = getSectionState(sec);
    if (current === next) return true;
    if (!(SECTION_TRANSITIONS[current] || []).includes(next)) {
        console.warn(`Illegal section transition ${sec.id}: ${current} -> ${next}`);
        return false;
    }
    sec.dataset.state = next;
    return true;
}

/**
 * The page section a request loads. Only a request that targets the section itself loads it; a fragment swapped
 * inside a section (a chart's toggle strip, a caption) is not a section load, or every one of them would rerun the
 * section's ready hook, and a hook that renders charts would load those fragments again, forever.
 */
function sectionOf(target) {
    if (!target || !target.classList || !target.classList.contains('page-section')) return null;
    return document.getElementById(target.id) || target;
}

function syncSectionVisibility() {
    document.querySelectorAll('.page-section').forEach(sec => {
        sec.hidden = sec.id !== currentSectionId;
    });
}

function syncNavChrome(sectionId, keepTitle) {
    document.querySelectorAll('.nav-link').forEach(l => {
        const isTarget = l.getAttribute('data-target') === sectionId;
        l.classList.toggle('active', isTarget);
    });
    const mobileNavSelect = document.getElementById('mobile-nav-select');
    if (mobileNavSelect && mobileNavSelect.value !== sectionId) mobileNavSelect.value = sectionId;
    const headerTitle = document.getElementById('page-header-title');
    if (headerTitle && !keepTitle) {
        headerTitle.textContent = SECTION_TITLES[sectionId] || 'Overview & Net Worth';
    }
}

function onSectionShown(sectionId) {
    hydrateSection(sectionId);
    const hook = SECTION_SHOWN_HOOKS[sectionId];
    if (hook) hook();
}

function setActiveSection(sectionId, options = {}) {
    currentSectionId = sectionId;
    window.currentSectionId = sectionId;
    syncSectionVisibility();
    syncNavChrome(sectionId, options.keepTitle);
    if (!options.quiet) {
        if (sectionId !== 'section-overview') window.setWidgetEditMode('overview', false);
        if (sectionId !== 'section-scenarios') window.setWidgetEditMode('scenarios', false);
    }
    updateAdvisorContext(sectionId);
    if (!options.quiet) window.scrollTo({ top: 0, behavior: 'smooth' });
    if (getSectionState(document.getElementById(sectionId)) === 'ready') onSectionShown(sectionId);
}

function sectionIdFromLocation() {
    const fromPath = PATH_TO_SECTION[window.location.pathname.toLowerCase()];
    return fromPath || window.INITIAL_ACTIVE_SECTION || 'section-overview';
}

function wireSectionEvents() {
    document.addEventListener('htmx:configRequest', (e) => {
        const d = e.detail;
        if (d.path.startsWith('/')) d.path = appendSessionQuery(d.path);
        const sec = sectionOf(d.target);
        if (!sec) return;
        // Retry re-issues the request that failed (its query string included), never a bare /fragments/<name>.
        if (d.elt.classList.contains('section-retry')) {
            if (sec.dataset.retryQuery) d.path = appendSessionQuery(`${d.path.split('?')[0]}${sec.dataset.retryQuery}`);
        } else {
            sec.dataset.retryQuery = new URL(d.path, window.location.origin).search;
        }
    });
    document.addEventListener('htmx:beforeHistoryUpdate', (e) => {
        const h = e.detail && e.detail.history;
        if (!h) return;
        h.path = appendSessionQuery(h.path);
    });
    document.addEventListener('htmx:beforeRequest', (e) => {
        const { elt, target } = e.detail;
        const navTarget = elt && elt.dataset ? elt.dataset.target : '';
        if (navTarget && navTarget.startsWith('section-')) setActiveSection(navTarget);
        const sec = sectionOf(target);
        if (sec && ['stale', 'error'].includes(getSectionState(sec))) transitionSection(sec, 'loading');
    });
    document.addEventListener('htmx:afterSwap', (e) => {
        const sec = sectionOf(e.detail.target);
        if (!sec) return;
        transitionSection(sec, 'ready');
        syncSectionVisibility();
        if (sec.id === currentSectionId) hydrateSection(sec.id);
    });
    ['htmx:responseError', 'htmx:sendError', 'htmx:timeout'].forEach(name => {
        document.addEventListener(name, (e) => {
            const sec = sectionOf(e.detail.target || (e.detail.requestConfig && e.detail.requestConfig.target));
            if (sec && getSectionState(sec) === 'loading') transitionSection(sec, 'error');
        });
    });
    document.addEventListener('htmx:historyRestore', () => {
        sectionHydratedSig.clear();
        setActiveSection(sectionIdFromLocation(), { quiet: true, keepTitle: false });
    });
}

function initNavigation() {
    wireSectionEvents();
    const mobileNavSelect = document.getElementById('mobile-nav-select');
    if (mobileNavSelect) {
        mobileNavSelect.addEventListener('change', (e) => navigateToSection(e.target.value));
    }

    window.addEventListener('hashchange', handleUrlHash);

    let initialId = window.INITIAL_ACTIVE_SECTION || sectionIdFromLocation();
    if (initialId === 'section-settings') {
        initialId = 'section-overview';
        window.openSettingsModal();
    }
    setActiveSection(initialId, { quiet: true, keepTitle: true });
    if (getSectionState(document.getElementById(initialId)) === 'stale') {
        const retry = document.querySelector(`#${initialId} .section-retry`);
        if (retry) {
            retry.closest('.page-section').dataset.retryQuery = window.location.search;
            window.htmx.trigger(retry, 'click');
        }
    }
    handleUrlHash();
}

function handleUrlHash() {
    const hash = (window.location.hash || '').toLowerCase();
    if (!hash) return;
    if (hash === '#withholding' || hash === '#section-withholding' || hash === '#safeharbor') {
        setTimeout(() => switchCompensationSubtab('comp-subtab-safeharbor'), 30);
    }
    if (hash === '#transcripts' || hash === '#section-transcripts') {
        setTimeout(() => switchCompensationSubtab('comp-subtab-transcripts'), 30);
    }
    const targetId = HASH_TO_SECTION[hash];
    if (targetId && targetId !== currentSectionId) navigateToSection(targetId);
}

function navigateToSection(targetId) {
    if (targetId === 'section-withholding') {
        switchCompensationSubtab('comp-subtab-safeharbor');
        targetId = 'section-compensation';
    } else if (targetId === 'section-transcripts') {
        switchCompensationSubtab('comp-subtab-transcripts');
        targetId = 'section-compensation';
    }
    const link = document.querySelector(`.nav-link[data-target="${targetId}"]`);
    if (link) {
        link.click();
    } else if (document.getElementById(targetId)) {
        setActiveSection(targetId);
    }
}

Object.assign(window, {
    SECTION_TITLES,
    SECTION_TO_PATH,
    PATH_TO_SECTION,
    HASH_TO_SECTION,
    initNavigation,
    handleUrlHash,
    setActiveSection,
    transitionSection,
    getSectionState,
    navigateToSection
});
