/**
 * HVL Family Office - Navigation & Routing Controller
 * Handles client routing, desktop & mobile navigation, hash changes, and ScrollSpy.
 */

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

function initNavigation() {
    const brandOverviewBtn = document.getElementById('btn-brand-overview');
    if (brandOverviewBtn) {
        brandOverviewBtn.addEventListener('click', (e) => {
            e.preventDefault();
            const overviewLink = document.querySelector('.nav-link[data-target="section-overview"]');
            if (overviewLink) {
                overviewLink.click();
            } else {
                currentSectionId = 'section-overview';
                if (history.pushState) {
                    history.pushState(null, null, appendSessionQuery('/'));
                }
                if (typeof applyViewMode === 'function') applyViewMode();
            }
        });
    }

    const navLinks = document.querySelectorAll('.nav-link');
    navLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const targetId = link.getAttribute('data-target');
            if (!targetId) return;

            navLinks.forEach(l => l.classList.remove('active'));
            link.classList.add('active');

            currentSectionId = targetId;

            const cleanPath = SECTION_TO_PATH[targetId] || link.getAttribute('href') || '/';
            if (history.pushState) {
                history.pushState(null, null, appendSessionQuery(cleanPath));
            }

            if (currentViewMode === 'focused') {
                if (typeof applyViewMode === 'function') applyViewMode();
            } else {
                const targetEl = document.getElementById(targetId);
                if (targetEl) {
                    targetEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            }
        });
    });

    const mobileNavSelect = document.getElementById('mobile-nav-select');
    if (mobileNavSelect) {
        mobileNavSelect.addEventListener('change', (e) => {
            const targetId = e.target.value;
            if (!targetId) return;

            currentSectionId = targetId;

            navLinks.forEach(l => {
                if (l.getAttribute('data-target') === targetId) l.classList.add('active');
                else l.classList.remove('active');
            });

            const cleanPath = SECTION_TO_PATH[targetId] || '/';
            if (history.pushState) {
                history.pushState(null, null, appendSessionQuery(cleanPath));
            }

            if (currentViewMode === 'focused') {
                if (typeof applyViewMode === 'function') applyViewMode();
            } else {
                const targetEl = document.getElementById(targetId);
                if (targetEl) {
                    targetEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            }
        });
    }

    const btnTabs = document.getElementById('btn-view-tabs');
    const btnAll = document.getElementById('btn-view-all');
    if (btnTabs) {
        btnTabs.addEventListener('click', () => {
            currentViewMode = 'focused';
            if (typeof applyViewMode === 'function') applyViewMode();
        });
    }
    if (btnAll) {
        btnAll.addEventListener('click', () => {
            currentViewMode = 'all';
            if (typeof applyViewMode === 'function') applyViewMode();
        });
    }

    window.addEventListener('hashchange', handleUrlHash);
    window.addEventListener('popstate', handlePopState);

    if (window.location.hash && HASH_TO_SECTION[window.location.hash.toLowerCase()]) {
        handleUrlHash();
    } else {
        const pathLower = window.location.pathname.toLowerCase();
        const secFromPath = (pathLower && pathLower !== '/') ? PATH_TO_SECTION[pathLower] : null;
        if (secFromPath) {
            currentSectionId = secFromPath;
        } else if (window.INITIAL_ACTIVE_SECTION) {
            currentSectionId = window.INITIAL_ACTIVE_SECTION;
        } else if (PATH_TO_SECTION[pathLower]) {
            currentSectionId = PATH_TO_SECTION[pathLower];
        }
        if (currentSectionId === 'section-settings') {
            currentSectionId = 'section-overview';
            if (typeof window.openSettingsModal === 'function') {
                window.openSettingsModal();
            }
        }
        navLinks.forEach(l => {
            if (l.getAttribute('data-target') === currentSectionId) l.classList.add('active');
            else l.classList.remove('active');
        });
        if (typeof applyViewMode === 'function') applyViewMode(true);
    }
}

function handlePopState() {
    if (window.location.hash && HASH_TO_SECTION[window.location.hash.toLowerCase()]) {
        handleUrlHash();
        return;
    }
    const secId = PATH_TO_SECTION[window.location.pathname.toLowerCase()] || window.INITIAL_ACTIVE_SECTION || 'section-overview';
    currentSectionId = secId;
    const navLinks = document.querySelectorAll('.nav-link');
    navLinks.forEach(l => {
        if (l.getAttribute('data-target') === secId) l.classList.add('active');
        else l.classList.remove('active');
    });
    if (typeof applyViewMode === 'function') applyViewMode();
}

function handleUrlHash() {
    let hash = (window.location.hash || '').toLowerCase();
    if (!hash) return;
    if (hash === '#withholding' || hash === '#section-withholding' || hash === '#safeharbor') {
        setTimeout(() => {
            if (typeof switchCompensationSubtab === 'function') switchCompensationSubtab('comp-subtab-safeharbor');
        }, 30);
    }
    if (hash === '#transcripts' || hash === '#section-transcripts') {
        setTimeout(() => {
            if (typeof switchCompensationSubtab === 'function') switchCompensationSubtab('comp-subtab-transcripts');
        }, 30);
    }
    const targetId = HASH_TO_SECTION[hash];
    if (targetId) {
        currentSectionId = targetId;
        const navLinks = document.querySelectorAll('.nav-link');
        navLinks.forEach(l => {
            if (l.getAttribute('data-target') === targetId) l.classList.add('active');
            else l.classList.remove('active');
        });
        if (typeof applyViewMode === 'function') applyViewMode();
    }
}

function navigateToSection(targetId) {
    if (targetId === 'section-withholding') {
        if (typeof switchCompensationSubtab === 'function') switchCompensationSubtab('comp-subtab-safeharbor');
        targetId = 'section-compensation';
    } else if (targetId === 'section-transcripts') {
        if (typeof switchCompensationSubtab === 'function') switchCompensationSubtab('comp-subtab-transcripts');
        targetId = 'section-compensation';
    }
    const link = document.querySelector(`.nav-link[data-target="${targetId}"]`);
    if (link) {
        link.click();
        return;
    }
    const secEl = document.getElementById(targetId);
    if (secEl) {
        currentSectionId = targetId;
        if (typeof applyViewMode === 'function') applyViewMode();
    }
}

let isScrollTicking = false;

function initScrollSpy() {
    window.addEventListener('scroll', onWindowScroll, { passive: true });
}

function onWindowScroll() {
    if (currentViewMode !== 'all') return;
    if (!isScrollTicking) {
        window.requestAnimationFrame(() => {
            updateActiveSectionFromScroll();
            isScrollTicking = false;
        });
        isScrollTicking = true;
    }
}

function updateActiveSectionFromScroll() {
    if (currentViewMode !== 'all') return;

    const sections = Array.from(document.querySelectorAll('.page-section')).filter(s => {
        return s.offsetParent !== null && s.style.display !== 'none';
    });
    if (!sections.length) return;

    const scrollPos = window.scrollY || window.pageYOffset || 0;
    const windowHeight = window.innerHeight;
    const docHeight = document.documentElement.scrollHeight || (document.body ? document.body.scrollHeight : 0);
    if (scrollPos + windowHeight >= docHeight - 60) {
        const lastSection = sections[sections.length - 1];
        if (lastSection) {
            syncActiveSectionHeader(lastSection.id);
            return;
        }
    }

    const topHeader = document.querySelector('.top-header');
    const headerBottom = topHeader ? topHeader.getBoundingClientRect().bottom : 80;
    const spyLine = headerBottom + 30;

    let activeSec = sections.find(sec => {
        const rect = sec.getBoundingClientRect();
        return rect.top <= spyLine && rect.bottom > spyLine;
    });

    if (!activeSec) {
        if (sections[0] && sections[0].getBoundingClientRect().top > spyLine) {
            activeSec = sections[0];
        } else {
            const preceding = sections.filter(sec => sec.getBoundingClientRect().top <= spyLine);
            activeSec = preceding.length > 0 ? preceding[preceding.length - 1] : sections[0];
        }
    }

    if (activeSec) {
        syncActiveSectionHeader(activeSec.id);
    }
}

function syncActiveSectionHeader(sectionId) {
    if (sectionId === currentSectionId) return;
    currentSectionId = sectionId;

    const mobileNavSelect = document.getElementById('mobile-nav-select');
    if (mobileNavSelect && mobileNavSelect.value !== sectionId) {
        mobileNavSelect.value = sectionId;
    }

    const headerTitle = document.getElementById('page-header-title');
    if (headerTitle && currentViewMode === 'all') {
        const title = SECTION_TITLES[sectionId] || 'Overview & Net Worth';
        headerTitle.textContent = `${title} (Scroll View)`;
    }

    const navLinks = document.querySelectorAll('.nav-link');
    navLinks.forEach(l => {
        if (l.getAttribute('data-target') === sectionId) l.classList.add('active');
        else l.classList.remove('active');
    });

    const matchingLink = document.querySelector(`.nav-link[data-target="${sectionId}"]`);
    if (matchingLink) {
        const href = matchingLink.getAttribute('href');
        if (href && history.replaceState) {
            history.replaceState(null, null, href);
        }
    }
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        SECTION_TITLES,
        SECTION_TO_PATH,
        PATH_TO_SECTION,
        HASH_TO_SECTION,
        initNavigation,
        handlePopState,
        handleUrlHash,
        navigateToSection,
        initScrollSpy,
        onWindowScroll,
        updateActiveSectionFromScroll,
        syncActiveSectionHeader
    });
}
