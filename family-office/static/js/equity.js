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
        if (force || EquityState.companyId === null) {
            const cidAttr = sec.dataset.companyId;
            if (cidAttr === 'all') {
                EquityState.companyId = 'all';
            } else if (cidAttr) {
                const parsedCid = parseInt(cidAttr, 10);
                if (!isNaN(parsedCid)) EquityState.companyId = parsedCid;
            }
        }
        if (force || !EquityState.simulatedPrice) {
            const pAttr = parseFloat(sec.dataset.sharePrice);
            if (!isNaN(pAttr) && pAttr > 0) EquityState.simulatedPrice = pAttr;
        }
        if (force && sec.dataset.waTax !== undefined) {
            EquityState.includeWaTax = sec.dataset.waTax === 'true';
        }
        if (force && sec.dataset.multiple !== undefined) {
            const mAttr = parseFloat(sec.dataset.multiple);
            if (!isNaN(mAttr) && mAttr > 0) EquityState.portfolioMultiple = mAttr;
        }
    }

    if (force || !EquityState.grants || EquityState.grants.length === 0) {
        const parsedGrants = parseJsonScript('ssr-equity-grants-data');
        if (Array.isArray(parsedGrants)) EquityState.grants = parsedGrants;
    }
    if (force || !EquityState.companies || EquityState.companies.length === 0) {
        const parsedComps = parseJsonScript('ssr-equity-companies-data');
        if (Array.isArray(parsedComps)) EquityState.companies = parsedComps;
    }
    if (force || !EquityState.fmvHistory || EquityState.fmvHistory.length === 0) {
        const parsedHist = parseJsonScript('ssr-equity-fmv-history-data');
        if (Array.isArray(parsedHist)) EquityState.fmvHistory = parsedHist;
    }
    if (force || !EquityState.projections || EquityState.projections.length === 0) {
        const parsedProj = parseJsonScript('ssr-equity-projections-data');
        if (Array.isArray(parsedProj)) EquityState.projections = parsedProj;
    }
    if (force || !EquityState.data) {
        const parsedState = parseJsonScript('ssr-equity-state-data');
        if (parsedState && typeof parsedState === 'object') EquityState.data = parsedState;
    }
}

async function morphEquitySection(overrides = {}) {
    const sec = document.getElementById('section-equity');
    const cid = overrides.company_id !== undefined
        ? overrides.company_id
        : (EquityState.companyId || (sec && sec.dataset.companyId) || null);
    const isConsolidated = String(cid) === 'all';
    const waTax = overrides.include_wa_tax !== undefined
        ? Boolean(overrides.include_wa_tax)
        : EquityState.includeWaTax;
    const mult = overrides.multiple !== undefined
        ? overrides.multiple
        : EquityState.portfolioMultiple;
    const selGrowth = document.getElementById('select-equity-expected-growth');
    const growthRate = overrides.growth_rate !== undefined
        ? overrides.growth_rate
        : (selGrowth ? selGrowth.value : ((sec && sec.dataset.growthRate) || '0.105'));

    const params = new URLSearchParams();
    if (cid) params.set('company_id', String(cid));
    params.set('include_wa_tax', waTax ? 'true' : 'false');
    if (mult) params.set('multiple', String(mult));
    if (growthRate) params.set('growth_rate', String(growthRate));

    if (!isConsolidated && overrides.share_price !== undefined && overrides.share_price !== null && overrides.share_price !== '') {
        params.set('share_price', String(overrides.share_price));
    } else if (!isConsolidated && overrides.share_price === undefined && EquityState.simulatedPrice > 0) {
        params.set('share_price', String(EquityState.simulatedPrice));
    }

    const url = `/fragments/equity?${params.toString()}`;
    await window.htmx.ajax('GET', url, { target: '#section-equity', swap: 'morph' });

    loadSsrEquityDataIfAvailable(true);
    if (typeof syncGraphModeUI === 'function') syncGraphModeUI();
    const { data, simulatedPrice, includeWaTax } = EquityState;
    if (typeof updateGraphHeaderAndStats === 'function') updateGraphHeaderAndStats(data, simulatedPrice);
    if (typeof renderEquityStockValueGraph === 'function') {
        renderEquityStockValueGraph(simulatedPrice, includeWaTax, data);
    }
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
            EquityState.companyId = cid;
            if (cid === 'all') {
                EquityState.portfolioMultiple = 1.0;
                await morphEquitySection({ company_id: 'all', multiple: 1.0 });
            } else {
                EquityState.simulatedPrice = 0;
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
