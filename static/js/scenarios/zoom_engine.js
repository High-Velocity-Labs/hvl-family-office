/**
 * Interactive Chart Physics Engine: Smooth Zooming & Panning with Acceleration & Momentum
 * 
 * Provides continuous 60fps spring interpolation, flick inertia, and exponential acceleration
 * for the Scenarios forecasting canvas graph (#chart-scenarios-comparison).
 * Fully preserves all thematic colors and scenario styling.
 */
import { state } from './state.js';
import { getTimelineRange, scheduleRibbonUpdate } from './scrubber.js';
import { updateChartWindowContinuous } from './charts/common.js';

const MIN_HORIZON_YEAR = 2018;
const MAX_HORIZON_YEAR = 2060;
const MIN_SPAN_YEARS = 3;
const MAX_SPAN_YEARS = 42; // (2060 - 2018)

const FRICTION_PAN = 0.88;          // Inertial decay for panning
const FRICTION_ZOOM = 0.82;         // Smooth decay for wheel zooming
const LERP_FACTOR = 0.28;           // Spring interpolation speed towards target
const VELOCITY_THRESHOLD = 0.002;
const POSITION_THRESHOLD = 0.008;

let curMinYear = 2018;
let curMaxYear = 2060;
let targetMinYear = 2018;
let targetMaxYear = 2060;

let panVelocity = 0;          // floating-point years / frame
let zoomVelocity = 0;         // fractional span change / frame
let focalRatio = 0.5;         // 0.0 to 1.0 along x-axis

let isDragging = false;
let dragStartX = 0;
let dragStartY = 0;
let lastMoveX = 0;
let dragMoved = false;
let recentPointerEvents = []; // [{ x, t }]

let rafId = null;
let lastAppliedMin = 2018;
let lastAppliedMax = 2060;
let lastWheelTime = 0;
let wheelAcceleration = 1.0;

function setChartTooltipSuppressed(suppressed) {
    if (typeof window !== 'undefined') window._chartZoomPanActive = suppressed;
    const chart = state.scenarioComparisonChart;
    if (!chart) return;
    if (suppressed) {
        chart._hoverTarget = null;
        chart._hoveredClusterYear = null;
        chart._lastTargetKey = 'none';
        if (chart.options?.plugins?.tooltip) chart.options.plugins.tooltip.enabled = false;
        if (chart.tooltip?.setActiveElements) chart.tooltip.setActiveElements([], { x: 0, y: 0 });
        if (chart.setActiveElements) chart.setActiveElements([]);
    } else if (chart.options?.plugins?.tooltip) {
        chart.options.plugins.tooltip.enabled = true;
    }
}

function syncRibbonWindowState(minYear, maxYear) {
    minYear = Math.max(2018, Math.min(2057, Math.round(minYear)));
    maxYear = Math.max(minYear + 3, Math.min(2060, Math.round(maxYear)));
    state.currentWindowMinYear = minYear;
    state.currentWindowMaxYear = maxYear;
    state.currentPanStartYear = minYear;
    const span = maxYear - minYear;
    if (minYear <= 2018 && maxYear >= 2060) state.currentZoom = 'lifetime';
    else if (span === 5) state.currentZoom = '5y';
    else if (span === 15) state.currentZoom = '15y';
    else state.currentZoom = 'dynamic';

    [document.getElementById('btn-zoom-5y'), document.getElementById('btn-chart-zoom-5y')].forEach(b => { if (b) b.classList.toggle('active', state.currentZoom === '5y'); });
    [document.getElementById('btn-zoom-15y'), document.getElementById('btn-chart-zoom-15y')].forEach(b => { if (b) b.classList.toggle('active', state.currentZoom === '15y'); });
    [document.getElementById('btn-zoom-lifetime'), document.getElementById('btn-chart-zoom-lifetime')].forEach(b => { if (b) b.classList.toggle('active', state.currentZoom === 'lifetime'); });
    scheduleRibbonUpdate();
}

function syncStateFromActiveWindow() {
    const range = getTimelineRange();
    if (!rafId && !isDragging) {
        curMinYear = range.minYear;
        curMaxYear = range.maxYear;
        targetMinYear = range.minYear;
        targetMaxYear = range.maxYear;
        lastAppliedMin = range.minYear;
        lastAppliedMax = range.maxYear;
    }
}

function ensurePhysicsLoop() {
    setChartTooltipSuppressed(true);
    if (!rafId) {
        rafId = requestAnimationFrame(stepPhysics);
    }
}

function stepPhysics() {
    // 1. Apply inertial pan momentum
    if (!isDragging && Math.abs(panVelocity) > VELOCITY_THRESHOLD) {
        targetMinYear += panVelocity;
        targetMaxYear += panVelocity;
        panVelocity *= FRICTION_PAN;
    } else if (!isDragging) {
        panVelocity = 0;
    }

    // 2. Apply inertial zoom momentum
    if (Math.abs(zoomVelocity) > VELOCITY_THRESHOLD) {
        const span = targetMaxYear - targetMinYear;
        const newSpan = Math.max(MIN_SPAN_YEARS, Math.min(MAX_SPAN_YEARS, span * (1 + zoomVelocity)));
        const focalYear = targetMinYear + focalRatio * span;
        targetMinYear = focalYear - focalRatio * newSpan;
        targetMaxYear = targetMinYear + newSpan;
        zoomVelocity *= FRICTION_ZOOM;
    } else {
        zoomVelocity = 0;
    }

    // 3. Clamp target window within lifetime boundary
    const targetSpan = Math.max(MIN_SPAN_YEARS, Math.min(MAX_SPAN_YEARS, targetMaxYear - targetMinYear));
    if (targetMinYear < MIN_HORIZON_YEAR) {
        targetMinYear = MIN_HORIZON_YEAR;
        targetMaxYear = MIN_HORIZON_YEAR + targetSpan;
        panVelocity = 0;
    }
    if (targetMaxYear > MAX_HORIZON_YEAR) {
        targetMaxYear = MAX_HORIZON_YEAR;
        targetMinYear = MAX_HORIZON_YEAR - targetSpan;
        panVelocity = 0;
    }

    // 4. Spring interpolate current position towards target
    const stepSpeed = isDragging ? 0.55 : LERP_FACTOR;
    curMinYear += (targetMinYear - curMinYear) * stepSpeed;
    curMaxYear += (targetMaxYear - curMaxYear) * stepSpeed;

    // 5. Continuously update Chart.js linear X-axis and smooth Y-axis at 60fps
    const chart = state.scenarioComparisonChart;
    let hasYMotion = false;
    if (chart) {
        updateChartWindowContinuous(chart, curMinYear, curMaxYear, true);
        if (typeof chart._targetYMax === 'number' && typeof chart._curYMax === 'number') {
            const spanY = Math.max(1, Math.abs(chart._targetYMax - chart._targetYMin));
            hasYMotion = (Math.abs(chart._targetYMin - chart._curYMin) / spanY > 0.0015) ||
                         (Math.abs(chart._targetYMax - chart._curYMax) / spanY > 0.0015);
        }
        chart.update('none');
    }

    // 5b. Sync timeline ribbon when integer year boundary crosses
    const rMin = Math.round(curMinYear);
    const rMax = Math.round(curMaxYear);
    if (rMin !== lastAppliedMin || rMax !== lastAppliedMax) {
        lastAppliedMin = rMin;
        lastAppliedMax = rMax;
        syncRibbonWindowState(rMin, rMax);
    }

    // 6. Check whether motion is still active
    const hasPanMotion = Math.abs(panVelocity) > VELOCITY_THRESHOLD;
    const hasZoomMotion = Math.abs(zoomVelocity) > VELOCITY_THRESHOLD;
    const hasLerpMotion = Math.abs(targetMinYear - curMinYear) > POSITION_THRESHOLD ||
                          Math.abs(targetMaxYear - curMaxYear) > POSITION_THRESHOLD;

    if (isDragging || hasPanMotion || hasZoomMotion || hasLerpMotion || hasYMotion) {
        rafId = requestAnimationFrame(stepPhysics);
    } else {
        curMinYear = targetMinYear;
        curMaxYear = targetMaxYear;
        rafId = null;
        setChartTooltipSuppressed(false);
        if (chart) {
            updateChartWindowContinuous(chart, curMinYear, curMaxYear, false);
            chart.update('none');
        }
        const finalMin = Math.round(targetMinYear);
        const finalMax = Math.round(targetMaxYear);
        if (finalMin !== lastAppliedMin || finalMax !== lastAppliedMax) {
            lastAppliedMin = finalMin;
            lastAppliedMax = finalMax;
            syncRibbonWindowState(finalMin, finalMax);
        }
    }
}

/**
 * Programmatically animate to a preset zoom window with smooth spring interpolation.
 * @param {'5y' | '15y' | 'lifetime' | {minYear: number, maxYear: number}} modeOrRange
 */
export function setSmoothZoom(modeOrRange) {
    syncStateFromActiveWindow();
    let start, end;
    if (modeOrRange === '5y') {
        start = Math.max(2026, Math.min(2055, state.inspectedYear));
        end = start + 5;
    } else if (modeOrRange === '15y') {
        start = Math.max(2026, Math.min(2045, state.inspectedYear));
        end = start + 15;
    } else if (modeOrRange === 'lifetime') {
        start = MIN_HORIZON_YEAR;
        end = MAX_HORIZON_YEAR;
    } else if (typeof modeOrRange === 'object' && modeOrRange.minYear && modeOrRange.maxYear) {
        start = modeOrRange.minYear;
        end = modeOrRange.maxYear;
    } else {
        return;
    }

    targetMinYear = Math.max(MIN_HORIZON_YEAR, Math.min(MAX_HORIZON_YEAR - 3, start));
    targetMaxYear = Math.max(targetMinYear + 3, Math.min(MAX_HORIZON_YEAR, end));
    focalRatio = 0.5;
    panVelocity = 0;
    zoomVelocity = 0;
    ensurePhysicsLoop();
}

/**
 * Programmatically pan with accelerated momentum impulse in a given direction.
 * @param {number} direction -1 for earlier (◀), +1 for later (▶)
 */
export function panSmooth(direction) {
    syncStateFromActiveWindow();
    const span = targetMaxYear - targetMinYear;
    let step = 1;
    if (span >= 30) step = 5;
    else if (span >= 15) step = 2.5;
    else step = 1.2;

    panVelocity += direction * step * 0.35;
    panVelocity = Math.max(-2.5, Math.min(2.5, panVelocity));
    ensurePhysicsLoop();
}

/**
 * Initializes continuous physics listeners (wheel, drag, flick) on the forecasting chart canvas.
 * @param {HTMLCanvasElement} chartCanvas
 */
export function initChartZoomAndPan(chartCanvas) {
    if (!chartCanvas || chartCanvas.dataset.zoomEngineBound === 'true') return;
    chartCanvas.dataset.zoomEngineBound = 'true';

    chartCanvas.addEventListener('contextmenu', (e) => {
        e.preventDefault();
    });

    // 1. Wheel Zooming & Trackpad Gesture Scrolling with Acceleration
    chartCanvas.addEventListener('wheel', (e) => {
        e.preventDefault();
        const now = performance.now();
        const timeSinceLastWheel = now - lastWheelTime;
        lastWheelTime = now;

        // Dynamic acceleration multiplier for rapid wheel spinning
        if (timeSinceLastWheel < 180) {
            wheelAcceleration = Math.min(3.2, wheelAcceleration + 0.32);
        } else {
            wheelAcceleration = 1.0;
        }

        syncStateFromActiveWindow();

        // Detect horizontal two-finger trackpad swipe or Shift+Wheel
        if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY) * 1.2) {
            const delta = e.deltaX !== 0 ? e.deltaX : e.deltaY;
            const chartWidth = chartCanvas.clientWidth || 600;
            const currentSpan = targetMaxYear - targetMinYear;
            const pxPerYear = Math.max(8, chartWidth / currentSpan);
            const step = (delta / pxPerYear) * 0.45 * wheelAcceleration;
            panVelocity += step;
            panVelocity = Math.max(-2.5, Math.min(2.5, panVelocity));
        } else {
            // Vertical wheel or pinch-to-zoom
            const rect = chartCanvas.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const chart = state.scenarioComparisonChart;
            let ratio = 0.5;
            if (chart && chart.chartArea) {
                const chartLeft = chart.chartArea.left;
                const chartRight = chart.chartArea.right;
                const chartWidth = Math.max(1, chartRight - chartLeft);
                ratio = Math.max(0, Math.min(1, (mouseX - chartLeft) / chartWidth));
            }
            focalRatio = ratio;

            const normDelta = Math.sign(e.deltaY) * Math.min(1.8, Math.abs(e.deltaY) / 50);
            const zoomImpulse = normDelta * 0.05 * wheelAcceleration;
            zoomVelocity += zoomImpulse;
            zoomVelocity = Math.max(-0.25, Math.min(0.25, zoomVelocity));
        }

        ensurePhysicsLoop();
    }, { passive: false });

    // 2. Drag & Flick Interaction (Left or Right Click Drag)
    chartCanvas.addEventListener('mousedown', (e) => {
        if (e.button !== 0 && e.button !== 2) return;

        syncStateFromActiveWindow();
        isDragging = true;
        dragStartX = e.clientX;
        dragStartY = e.clientY;
        lastMoveX = e.clientX;
        dragMoved = false;
        panVelocity = 0;
        zoomVelocity = 0;
        recentPointerEvents = [{ x: e.clientX, t: performance.now() }];

        if (e.button === 2) {
            e.preventDefault();
            chartCanvas.style.cursor = 'grabbing';
        }
        document.body.style.userSelect = 'none';
    });

    window.addEventListener('mousemove', (e) => {
        if (!isDragging) return;

        const dx = e.clientX - lastMoveX;
        lastMoveX = e.clientX;

        const totalDist = Math.hypot(e.clientX - dragStartX, e.clientY - dragStartY);
        if (totalDist > 4) {
            dragMoved = true;
            chartCanvas.style.cursor = 'grabbing';
        }

        if (dragMoved) {
            e.preventDefault();
            const chartWidth = chartCanvas.clientWidth || 600;
            const currentSpan = Math.max(MIN_SPAN_YEARS, targetMaxYear - targetMinYear);
            const pxPerYear = Math.max(6, chartWidth / currentSpan);
            const deltaYears = - (dx / pxPerYear);

            targetMinYear += deltaYears;
            targetMaxYear += deltaYears;

            const now = performance.now();
            recentPointerEvents.push({ x: e.clientX, t: now });
            recentPointerEvents = recentPointerEvents.filter(p => (now - p.t) <= 90);

            ensurePhysicsLoop();
        }
    });

    window.addEventListener('mouseup', (e) => {
        if (!isDragging) return;
        isDragging = false;
        chartCanvas.style.cursor = '';
        document.body.style.userSelect = '';

        if (dragMoved) {
            // Suppress accidental point click on graph release
            window._suppressChartClick = true;
            setTimeout(() => {
                window._suppressChartClick = false;
            }, 120);

            // Compute flick velocity for momentum coasting
            const now = performance.now();
            recentPointerEvents.push({ x: e.clientX, t: now });
            if (recentPointerEvents.length >= 2) {
                const oldest = recentPointerEvents[0];
                const newest = recentPointerEvents[recentPointerEvents.length - 1];
                const dt = newest.t - oldest.t;
                if (dt > 15 && dt < 120) {
                    const dx = newest.x - oldest.x;
                    const chartWidth = chartCanvas.clientWidth || 600;
                    const currentSpan = Math.max(MIN_SPAN_YEARS, targetMaxYear - targetMinYear);
                    const pxPerYear = Math.max(6, chartWidth / currentSpan);
                    const vx = dx / dt; // px / ms
                    const flickVel = - (vx * 16) / pxPerYear;
                    panVelocity = Math.max(-2.5, Math.min(2.5, flickVel * 1.15));
                }
            }
            ensurePhysicsLoop();
        }
    });

    chartCanvas.addEventListener('mouseleave', () => {
        if (state.scenarioComparisonChart) {
            state.scenarioComparisonChart._hoverTarget = null;
            state.scenarioComparisonChart._hoveredClusterYear = null;
            state.scenarioComparisonChart._lastTargetKey = 'none';
            state.scenarioComparisonChart.draw();
        }
    });
}
