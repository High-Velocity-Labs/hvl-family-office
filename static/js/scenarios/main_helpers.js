/**
 * static/js/scenarios/main_helpers.js
 * Loading states, CSV export builders, SSR data script parsing, and DOM preservation helpers.
 */

import { state } from './state.js';

export function consumeSsrDataScript(root = document) {
    if (typeof document === 'undefined' || !root) return null;
    const ssrScript = root.querySelector ? root.querySelector('#ssr-scenarios-data') : document.getElementById('ssr-scenarios-data');
    if (!ssrScript) return null;
    try {
        const raw = ssrScript.textContent;
        ssrScript.remove();
        if (raw && raw.trim().length > 0) {
            return JSON.parse(raw);
        }
    } catch (e) {
        console.warn('Failed to parse SSR scenarios data:', e);
    }
    return null;
}

export function setScenarioLoadingState(isLoading, labelText = 'Running forecast...') {
    if (typeof document === 'undefined') return;
    const throbber = document.getElementById('scenario-switch-loading');
    const throbberText = document.getElementById('scenario-switch-loading-text');
    if (throbber) {
        if (throbberText && labelText) {
            throbberText.textContent = labelText;
        }
        throbber.style.display = isLoading ? 'inline-flex' : 'none';
    }
    const loader = document.getElementById('scenarios-chart-loading');
    if (loader) {
        if (isLoading) {
            loader.classList.remove('hidden');
            loader.style.display = 'flex';
        } else {
            loader.classList.add('hidden');
            loader.style.display = 'none';
        }
    }
    const planCard = document.getElementById('selected-scenario-plan-card');
    if (planCard) {
        planCard.style.opacity = isLoading ? '0.65' : '';
        planCard.style.transition = 'opacity 0.15s ease';
    }
}

export function buildForecastCsvExportUrl() {
    const params = {};
    if (state.selectedScenarioId) {
        params.scenario_id = state.selectedScenarioId;
    }
    if (state.scenariosData?.view_mode) {
        params.view_mode = state.scenariosData.view_mode;
    }
    if (typeof document !== 'undefined') {
        const pRet = document.getElementById('scen-input-primary-retire-age')?.value;
        const sRet = document.getElementById('scen-input-spouse-retire-age')?.value;
        const spend = document.getElementById('scen-input-living-spend')?.value;
        const sav = document.getElementById('scen-input-annual-savings')?.value;
        const inf = document.getElementById('scen-input-inflation-rate')?.value;
        if (pRet) params.primary_retirement_age = pRet;
        if (sRet) params.spouse_retirement_age = sRet;
        if (spend) params.annual_living_spend = spend;
        if (sav) params.annual_savings = sav;
        if (inf) {
            const infNum = parseFloat(inf);
            if (!isNaN(infNum)) {
                params.inflation_rate = infNum > 1 ? String(infNum / 100) : String(infNum);
            }
        }
    }
    const qs = new URLSearchParams(params).toString();
    return `/api/scenarios/export_csv${qs ? `?${qs}` : ''}`;
}

export function syncExportCsvLink() {
    if (typeof document === 'undefined') return;
    const btn = document.getElementById('btn-export-forecast-csv');
    if (btn) {
        btn.setAttribute('href', buildForecastCsvExportUrl());
    }
}

export function exportForecastCsv(event) {
    const url = buildForecastCsvExportUrl();
    if (typeof document !== 'undefined') {
        const btn = document.getElementById('btn-export-forecast-csv');
        if (btn) {
            btn.setAttribute('href', url);
        }
    }
    if (!event && typeof window !== 'undefined' && window.location) {
        window.location.href = url;
    }
    return true;
}

export function preserveInteractiveExpansionStates(newSection, { scorecardOpen, scheduleOpen, topEventsOpen, planDetailsOpen, assetGrowthOpen }) {
    if (!newSection) return;

    const newScorecard = newSection.querySelector('#container-side-by-side-scorecard');
    const newScorecardBtn = newSection.querySelector('#btn-toggle-scorecard-table');
    if (newScorecard && scorecardOpen) {
        newScorecard.style.display = 'block';
        if (newScorecardBtn) {
            newScorecardBtn.innerHTML = '▲ Collapse Comparison';
            newScorecardBtn.classList.add('active');
        }
    }

    const newSched = newSection.querySelector('#scen-schedule-container');
    const newSchedBtn = newSection.querySelector('#btn-toggle-scen-schedule');
    if (newSched && scheduleOpen) {
        newSched.style.display = 'block';
        if (newSchedBtn) {
            newSchedBtn.textContent = 'Hide Schedule ▲';
        }
    }

    const newTopEvents = newSection.querySelector('#selected-scen-events-expanded');
    const newTopChev = newSection.querySelector('.scen-evt-top-chevron');
    if (newTopEvents && topEventsOpen) {
        newTopEvents.style.display = 'flex';
        if (newTopChev) newTopChev.textContent = '▼';
    }

    const newPlanBody = newSection.querySelector('#current-plan-collapsible-body');
    const newPlanBtn = newSection.querySelector('#btn-toggle-current-plan');
    const newPlanTxt = newSection.querySelector('#txt-toggle-current-plan');
    if (newPlanBody && planDetailsOpen) {
        newPlanBody.style.display = 'block';
        if (newPlanTxt) newPlanTxt.textContent = '▲ Plan Details';
        if (newPlanBtn) newPlanBtn.classList.add('active');
    }

    const newAssetBody = newSection.querySelector('#asset-growth-body');
    const newAssetBtn = newSection.querySelector('#btn-toggle-asset-growth');
    const newAssetTxt = newSection.querySelector('#txt-toggle-asset-growth');
    if (newAssetBody && assetGrowthOpen) {
        newAssetBody.style.display = 'block';
        if (newAssetTxt) newAssetTxt.textContent = '▲ Advanced Levers';
        if (newAssetBtn) newAssetBtn.classList.add('active');
    }
}

export function consumeScenarioDeepLinkParams({ switchToLens, setCfSubMode, setMcSubMode, openCreateEventModal } = {}) {
    if (typeof window === 'undefined' || !window.location || !window.location.search) return false;
    const params = new URLSearchParams(window.location.search);
    const lens = params.get('lens');
    const view = params.get('view');
    const mcMode = params.get('mc_mode');
    const openEvent = params.get('open_event');
    const openGuardrails = params.get('open_guardrails') === '1';
    const compare = params.get('compare') === '1';
    const askAi = params.get('ask_ai');

    if (!lens && !view && !mcMode && !openEvent && !openGuardrails && !compare && !askAi) {
        return false;
    }

    ['lens', 'view', 'mc_mode', 'open_event', 'open_guardrails', 'compare', 'ask_ai'].forEach(k => params.delete(k));
    if (window.history && typeof window.history.replaceState === 'function') {
        const rest = params.toString();
        const nextUrl = `${window.location.pathname || '/scenarios'}${rest ? `?${rest}` : ''}${window.location.hash || ''}`;
        try { window.history.replaceState({}, '', nextUrl); } catch (e) {}
    }

    if (view === 'sankey' && typeof setCfSubMode === 'function') {
        setCfSubMode('sankey');
    } else if (view === 'timeline' && typeof setCfSubMode === 'function') {
        setCfSubMode('timeline');
    }

    if ((mcMode === 'historical' || mcMode === 'stochastic') && typeof setMcSubMode === 'function') {
        setMcSubMode(mcMode);
    }

    const targetLens = lens || (view === 'sankey' ? 'cashflow' : (mcMode ? 'montecarlo' : null));
    if (targetLens && ['networth', 'cashflow', 'longevity', 'montecarlo'].includes(targetLens) && typeof switchToLens === 'function') {
        switchToLens(targetLens, true);
    }

    if (compare && typeof document !== 'undefined') {
        const sc = document.getElementById('container-side-by-side-scorecard');
        const scBtn = document.getElementById('btn-toggle-scorecard-table');
        if (sc) sc.style.display = 'block';
        if (scBtn) {
            scBtn.innerHTML = '▲ Collapse Comparison';
            scBtn.classList.add('active');
        }
        const planBody = document.getElementById('current-plan-collapsible-body');
        const planBtn = document.getElementById('btn-toggle-current-plan');
        const planTxt = document.getElementById('txt-toggle-current-plan');
        if (planBody) planBody.style.display = 'block';
        if (planTxt) planTxt.textContent = '▲ Plan Details';
        if (planBtn) planBtn.classList.add('active');
    }

    if (openGuardrails && typeof document !== 'undefined') {
        const planBody = document.getElementById('current-plan-collapsible-body');
        const planBtn = document.getElementById('btn-toggle-current-plan');
        const planTxt = document.getElementById('txt-toggle-current-plan');
        if (planBody) planBody.style.display = 'block';
        if (planTxt) planTxt.textContent = '▲ Plan Details';
        if (planBtn) planBtn.classList.add('active');

        const assetBody = document.getElementById('asset-growth-body');
        const assetBtn = document.getElementById('btn-toggle-asset-growth');
        const assetTxt = document.getElementById('txt-toggle-asset-growth');
        if (assetBody) assetBody.style.display = 'block';
        if (assetTxt) assetTxt.textContent = '▲ Advanced Levers';
        if (assetBtn) assetBtn.classList.add('active');

        const grEl = document.getElementById('scen-input-spending-guardrails');
        if (grEl) {
            if (typeof grEl.scrollIntoView === 'function') {
                grEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
            if (typeof grEl.focus === 'function') grEl.focus();
        }
    }

    if (openEvent && typeof openCreateEventModal === 'function') {
        openCreateEventModal(openEvent);
    }

    if (askAi) {
        if (typeof window.toggleAiAdvisorDrawer === 'function') {
            window.toggleAiAdvisorDrawer(true);
        }
        const aiInput = typeof document !== 'undefined' ? document.getElementById('ai-advisor-input') : null;
        if (aiInput) {
            aiInput.value = askAi;
            const charCounter = document.getElementById('advisor-char-counter');
            if (charCounter) charCounter.textContent = `${askAi.length} / 2000`;
            if (typeof aiInput.focus === 'function') aiInput.focus();
        }
    }

    return true;
}

