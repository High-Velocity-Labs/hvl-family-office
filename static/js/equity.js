/**
 * Equity 409A Share Price Scenario Simulator Module
 * Pure HTMX/Idiomorph fragment morphing + delegated event listeners.
 * Chart rendering and vesting math live in static/js/equity_chart.js.
 * Valuation simulation logic lives in static/js/equity_simulator.js.
 * Grant cards and modals live in static/js/equity_modals.js.
 */

function parseJsonScript(id) {
    const el = document.getElementById(id);
    if (!el) return null;
    try {
        return JSON.parse(el.textContent || 'null');
    } catch (e) {
        return null;
    }
}

function loadSsrEquityDataIfAvailable(force = false) {
    const sec = document.getElementById('section-equity');
    if (sec) {
        if (force || activeEquityCompanyId === null) {
            const cidAttr = sec.dataset.companyId;
            if (cidAttr === 'all') {
                activeEquityCompanyId = 'all';
            } else if (cidAttr) {
                const parsedCid = parseInt(cidAttr, 10);
                if (!isNaN(parsedCid)) activeEquityCompanyId = parsedCid;
            }
        }
        if (force || !currentSimulatedPrice) {
            const pAttr = parseFloat(sec.dataset.sharePrice);
            if (!isNaN(pAttr) && pAttr > 0) currentSimulatedPrice = pAttr;
        }
        if (force && sec.dataset.waTax !== undefined) {
            currentIncludeWaTax = sec.dataset.waTax === 'true';
        }
        if (force && sec.dataset.multiple !== undefined) {
            const mAttr = parseFloat(sec.dataset.multiple);
            if (!isNaN(mAttr) && mAttr > 0) currentPortfolioMultiple = mAttr;
        }
    }

    if (force || !equityGrantsData || equityGrantsData.length === 0) {
        const parsedGrants = parseJsonScript('ssr-equity-grants-data');
        if (Array.isArray(parsedGrants)) equityGrantsData = parsedGrants;
    }
    if (force || !equityCompaniesList || equityCompaniesList.length === 0) {
        const parsedComps = parseJsonScript('ssr-equity-companies-data');
        if (Array.isArray(parsedComps)) equityCompaniesList = parsedComps;
    }
    if (force || !equityFmvHistoryData || equityFmvHistoryData.length === 0) {
        const parsedHist = parseJsonScript('ssr-equity-fmv-history-data');
        if (Array.isArray(parsedHist)) equityFmvHistoryData = parsedHist;
    }
    if (force || !equityProjectionsData || equityProjectionsData.length === 0) {
        const parsedProj = parseJsonScript('ssr-equity-projections-data');
        if (Array.isArray(parsedProj)) equityProjectionsData = parsedProj;
    }
    if (force || !currentEquityData) {
        const parsedState = parseJsonScript('ssr-equity-state-data');
        if (parsedState && typeof parsedState === 'object') currentEquityData = parsedState;
    }
}

async function morphEquitySection(overrides = {}) {
    const sec = document.getElementById('section-equity');
    const cid = overrides.company_id !== undefined
        ? overrides.company_id
        : (activeEquityCompanyId || (sec && sec.dataset.companyId) || 1);
    const isConsolidated = String(cid) === 'all';
    const waTax = overrides.include_wa_tax !== undefined
        ? Boolean(overrides.include_wa_tax)
        : currentIncludeWaTax;
    const mult = overrides.multiple !== undefined
        ? overrides.multiple
        : currentPortfolioMultiple;
    const selGrowth = document.getElementById('select-equity-expected-growth');
    const growthRate = overrides.growth_rate !== undefined
        ? overrides.growth_rate
        : (selGrowth ? selGrowth.value : ((sec && sec.dataset.growthRate) || '0.105'));

    const params = new URLSearchParams();
    params.set('company_id', String(cid));
    params.set('include_wa_tax', waTax ? 'true' : 'false');
    params.set('multiple', String(mult || 1.0));
    params.set('growth_rate', String(growthRate || '0.105'));

    if (!isConsolidated && overrides.share_price !== undefined && overrides.share_price !== null && overrides.share_price !== '') {
        params.set('share_price', String(overrides.share_price));
    } else if (!isConsolidated && overrides.share_price === undefined && currentSimulatedPrice > 0) {
        params.set('share_price', String(currentSimulatedPrice));
    }

    const url = `/fragments/equity?${params.toString()}`;
    await window.htmx.ajax('GET', url, { target: '#section-equity', swap: 'morph' });

    loadSsrEquityDataIfAvailable(true);
    if (typeof syncGraphModeUI === 'function') syncGraphModeUI();
    if (typeof updateGraphHeaderAndStats === 'function') updateGraphHeaderAndStats(currentEquityData, currentSimulatedPrice);
    if (typeof renderEquityStockValueGraph === 'function') renderEquityStockValueGraph(currentSimulatedPrice, currentIncludeWaTax, currentEquityData);
}

function initEquityDelegation() {
    if (typeof initEquitySimulator === 'function') initEquitySimulator();
    if (typeof initEquityModals === 'function') initEquityModals();

    if (document.body.dataset.equityMainDelegated === 'true') return;
    document.body.dataset.equityMainDelegated = 'true';

    document.addEventListener('click', async (e) => {
        const compBtn = e.target.closest('#equity-company-tabs-container [data-cid]');
        if (compBtn) {
            const rawCid = compBtn.getAttribute('data-cid');
            const cid = rawCid === 'all' ? 'all' : parseInt(rawCid, 10);
            activeEquityCompanyId = cid;
            if (cid === 'all') {
                currentPortfolioMultiple = 1.0;
                await morphEquitySection({ company_id: 'all', multiple: 1.0 });
            } else {
                currentSimulatedPrice = 0;
                await morphEquitySection({ company_id: cid, share_price: '' });
            }
        }
    });
}

function renderEquity(data) {
    if (typeof renderEquitySimulator === 'function') {
        renderEquitySimulator(data);
    }
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        parseJsonScript,
        loadSsrEquityDataIfAvailable,
        morphEquitySection,
        initEquityDelegation,
        renderEquity
    });
    if (typeof window.registerSectionHydrator === 'function') {
        window.registerSectionHydrator('section-equity', renderEquity, {
            needsDashboard: true,
            morphFn: () => morphEquitySection()
        });
    }
}
