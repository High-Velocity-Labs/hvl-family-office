/**
 * Multi-Widget Forecasting Chart Dispatcher & Controller
 * Hydrates standalone customizable Forecasting graph widgets:
 *   - scen_chart_networth (#chart-scenarios-comparison)
 *   - scen_chart_cashflow (#chart-scen_chart_cashflow + Single-Year Sankey)
 *   - scen_chart_longevity (#chart-scen_chart_longevity)
 *   - scen_chart_montecarlo (#chart-scen_chart_montecarlo + #container-monte-carlo-details)
 */
import { state } from '../state.js';
import { renderNetWorthLens } from './net_worth.js';
import { renderCashFlowWaterfallLens } from './cash_flow.js';
import { renderLongevityStackedAreaLens } from './longevity.js';
import { renderMonteCarloLens } from './monte_carlo.js';

let lastRenderedLens = null;

function destroyIfDetached(chartKey, canvas) {
    const ch = state[chartKey];
    const isReset = canvas && (!canvas.getAttribute('style') || !canvas.style.width);
    if (ch && (ch.canvas !== canvas || !document.body.contains(ch.canvas) || isReset)) {
        ch.destroy();
        state[chartKey] = null;
    }
}

export function renderActiveLensChart(smooth = false) {
    const loader = document.getElementById('scenarios-chart-loading');
    if (!state.scenariosData) {
        if (loader) {
            loader.classList.add('hidden');
            loader.style.display = 'none';
        }
        return;
    }

    const nwCanvas = document.getElementById('chart-scenarios-comparison');
    const cfCanvas = document.getElementById('chart-scen_chart_cashflow');
    const lgCanvas = document.getElementById('chart-scen_chart_longevity');
    const mcCanvas = document.getElementById('chart-scen_chart_montecarlo');
    const hasWidgetGrid = Boolean(document.getElementById('scenarios-widgets-grid') || cfCanvas || lgCanvas || mcCanvas);

    if (!hasWidgetGrid && nwCanvas) {
        const ctx = nwCanvas.getContext('2d');
        const togglesContainer = document.getElementById('chart-curve-toggles');
        const captionEl = document.getElementById('chart-lens-caption');
        const mcDetails = document.getElementById('container-monte-carlo-details');
        if (mcDetails) mcDetails.style.display = (state.currentLens === 'montecarlo') ? 'block' : 'none';
        if (state.scenarioComparisonChart && (lastRenderedLens !== state.currentLens || state.scenarioComparisonChart.canvas !== nwCanvas)) {
            state.scenarioComparisonChart.destroy();
            state.scenarioComparisonChart = null;
        }
        lastRenderedLens = state.currentLens;
        if (state.currentLens === 'networth') renderNetWorthLens(ctx, togglesContainer, captionEl, smooth);
        else if (state.currentLens === 'cashflow') renderCashFlowWaterfallLens(ctx, togglesContainer, captionEl, smooth);
        else if (state.currentLens === 'longevity') renderLongevityStackedAreaLens(ctx, togglesContainer, captionEl, smooth);
        else if (state.currentLens === 'montecarlo') renderMonteCarloLens(ctx, togglesContainer, captionEl, smooth);
        if (loader && state.currentLens !== 'montecarlo') {
            loader.classList.add('hidden');
            loader.style.display = 'none';
        }
        return;
    }

    if (nwCanvas) {
        destroyIfDetached('scenarioComparisonChart', nwCanvas);
        renderNetWorthLens(
            nwCanvas.getContext('2d'),
            document.getElementById('chart-curve-toggles'),
            document.getElementById('chart-lens-caption'),
            smooth
        );
        if (state.scenarioComparisonChart?.resize) state.scenarioComparisonChart.resize();
        if (loader) {
            loader.classList.add('hidden');
            loader.style.display = 'none';
        }
    }

    if (cfCanvas) {
        destroyIfDetached('cashFlowChart', cfCanvas);
        renderCashFlowWaterfallLens(
            cfCanvas.getContext('2d'),
            document.getElementById('chart-cashflow-toggles'),
            document.getElementById('chart-cashflow-caption'),
            smooth
        );
        if (state.cashFlowChart?.resize) state.cashFlowChart.resize();
    }

    if (lgCanvas) {
        destroyIfDetached('longevityChart', lgCanvas);
        renderLongevityStackedAreaLens(
            lgCanvas.getContext('2d'),
            document.getElementById('chart-longevity-toggles'),
            document.getElementById('chart-longevity-caption'),
            smooth
        );
        if (state.longevityChart?.resize) state.longevityChart.resize();
    }

    if (mcCanvas) {
        destroyIfDetached('monteCarloChart', mcCanvas);
        renderMonteCarloLens(
            mcCanvas.getContext('2d'),
            document.getElementById('chart-montecarlo-toggles'),
            document.getElementById('chart-montecarlo-caption'),
            smooth
        );
        if (state.monteCarloChart?.resize) state.monteCarloChart.resize();
    }
}

export function switchToLens(lensName, scroll = false) {
    state.currentLens = lensName;
    const widMap = {
        networth: 'scen_chart_networth',
        cashflow: 'scen_chart_cashflow',
        longevity: 'scen_chart_longevity',
        montecarlo: 'scen_chart_montecarlo'
    };
    const wid = widMap[lensName] || 'scen_chart_networth';

    if (scroll && typeof document !== 'undefined' && document.getElementById('scenarios-widgets-grid')) {
        const existingCard = document.querySelector(`.household-widget-card[data-widget-id="${wid}"]`);
        if (!existingCard) {
            const chk = document.querySelector(`.chk-widget-toggle[data-page="scenarios"][data-widget-id="${wid}"]`);
            if (chk && !chk.checked) {
                chk.checked = true;
                chk.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }
    }

    if (!state.scenariosData && typeof window !== 'undefined' && typeof window.fetchScenariosData === 'function') {
        window.fetchScenariosData();
    } else {
        renderActiveLensChart();
    }

    if (scroll && typeof document !== 'undefined') {
        setTimeout(() => {
            const targetEl = document.querySelector(`.household-widget-card[data-widget-id="${wid}"]`)
                || document.getElementById('scenario-lens-section')
                || document.getElementById('chart-scenarios-comparison');
            if (targetEl && typeof targetEl.scrollIntoView === 'function') {
                targetEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        }, 80);
    }
}

if (typeof window !== 'undefined') {
    window.renderActiveLensChart = renderActiveLensChart;
    window.switchToLens = switchToLens;
}
