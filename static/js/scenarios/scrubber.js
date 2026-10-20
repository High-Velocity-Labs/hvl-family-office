/**
 * Forecasting Chart Window Zoom & Pan Controller
 * Manages dynamic year windows (`5Y`, `15Y`, `Full Lifetime`) and panning for `#chart-scenarios-comparison`.
 */
import { state } from './state.js';
import { renderActiveLensChart } from './charts/index.js';

export function getTimelineRange() {
    if (state.currentZoom === '5y') {
        const start = state.currentPanStartYear;
        const end = Math.min(2060, start + 5);
        return { minYear: start, maxYear: end, isWindowed: true };
    } else if (state.currentZoom === '15y') {
        const start = state.currentPanStartYear;
        const end = Math.min(2060, start + 15);
        return { minYear: start, maxYear: end, isWindowed: true };
    } else if (state.currentZoom === 'dynamic') {
        const isWin = (state.currentWindowMinYear > 2018 || state.currentWindowMaxYear < 2060);
        return { minYear: state.currentWindowMinYear, maxYear: state.currentWindowMaxYear, isWindowed: isWin };
    }
    return { minYear: 2018, maxYear: 2060, isWindowed: false };
}

export function filterByZoom(dataArray) {
    if (!dataArray || !dataArray.length) return [];
    const { minYear, maxYear, isWindowed } = getTimelineRange();
    if (isWindowed) {
        return dataArray.filter(r => r.year >= minYear && r.year <= maxYear);
    }
    return dataArray;
}

export function setDynamicWindow(minYear, maxYear, smooth = true) {
    minYear = Math.max(2018, Math.min(2057, Math.round(minYear)));
    maxYear = Math.max(minYear + 3, Math.min(2060, Math.round(maxYear)));

    state.currentWindowMinYear = minYear;
    state.currentWindowMaxYear = maxYear;
    state.currentPanStartYear = minYear;

    const span = maxYear - minYear;
    if (minYear <= 2018 && maxYear >= 2060) {
        state.currentZoom = 'lifetime';
    } else if (span === 5) {
        state.currentZoom = '5y';
    } else if (span === 15) {
        state.currentZoom = '15y';
    } else {
        state.currentZoom = 'dynamic';
    }

    const btn5 = document.getElementById('btn-chart-zoom-5y');
    const btn15 = document.getElementById('btn-chart-zoom-15y');
    const btnLife = document.getElementById('btn-chart-zoom-lifetime');
    if (btn5) btn5.classList.toggle('active', state.currentZoom === '5y');
    if (btn15) btn15.classList.toggle('active', state.currentZoom === '15y');
    if (btnLife) btnLife.classList.toggle('active', state.currentZoom === 'lifetime');

    renderActiveLensChart(smooth);
}

export function panTimeline(dir) {
    const { minYear, maxYear } = getTimelineRange();
    const span = maxYear - minYear;
    let step = 1;
    if (span >= 30) step = 5;
    else if (span >= 15) step = 2;

    let targetMin = minYear + dir * step;
    let targetMax = maxYear + dir * step;

    if (targetMin < 2018) {
        targetMin = 2018;
        targetMax = targetMin + span;
    }
    if (targetMax > 2060) {
        targetMax = 2060;
        targetMin = Math.max(2018, targetMax - span);
    }

    setDynamicWindow(targetMin, targetMax, true);
}

export function inspectTimelineYear(targetYear) {
    state.inspectedYear = targetYear;
}

export function updateScrubberNeedle() {}
export function updateShelfFilterButtons() {}
export function scheduleRibbonUpdate() {}
export function bindSsrContinuousRibbon() {}
export function renderContinuousRibbon() {}
export function renderTimelineContinuous() {}
