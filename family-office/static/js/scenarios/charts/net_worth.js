/**
 * Lens 1: Multi-Scenario Net Worth Trajectory & Monte Carlo Corridor
 * Includes Chart.js Event Pin Icons plugin and Canvas drawing helpers.
 */
import {
    state,
    fmtShortCurrency,
    getMonteCarloForScenario,
    ensureMonteCarloForScenario,
    getGraphScenarioId,
    setGraphScenarioId,
    categoryTheme,
    getEventCanvasImage,
    getMilestoneCanvasImage,
    getPlanStartYear
} from '../state.js';
import { renderGraphScenarioToggles, updateChartWindowContinuous } from './common.js';
import { getTimelineRange, inspectTimelineYear, updateScrubberNeedle } from '../scrubber.js';
import { applyChartStageHeight } from './cash_flow_sankey.js';
import {
    buildAllPoints,
    buildNetWorthDatasets,
    computeYearYBounds,
    buildNetWorthTooltipCallbacks
} from './net_worth_config.js';
import { customNetWorthTooltip } from './net_worth_tooltip.js';
import { bindScenarioHoverListeners } from './net_worth_highlight.js';

// Chart theme singleton; theme switches refresh its values in place
const chartTheme = window.CHART_THEME;

export function drawPillPath(ctx, x, y, w, h, r) {
    if (typeof ctx.roundRect === 'function') {
        ctx.roundRect(x, y, w, h, r);
        return;
    }
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
}

function drawMilestonePin(ctx, element, y_ms, ms, yr, isHovered, N, shiftDown, chart) {
    if (N > 0 || shiftDown > 0) {
        ctx.beginPath();
        ctx.strokeStyle = chartTheme.alpha(chartTheme.slateLight, 0.4);
        ctx.lineWidth = 1;
        ctx.setLineDash([2, 2]);
        ctx.moveTo(element.x, element.y - 8);
        ctx.lineTo(element.x, y_ms);
        ctx.stroke();
        ctx.setLineDash([]);
    }

    if (isHovered) {
        ctx.beginPath();
        ctx.arc(element.x, y_ms, 17, 0, 2 * Math.PI);
        ctx.fillStyle = chartTheme.alpha(chartTheme.sapphire, 0.3);
        ctx.fill();
    }

    ctx.beginPath();
    ctx.arc(element.x, y_ms, isHovered ? 12 : 10, 0, 2 * Math.PI);
    ctx.fillStyle = isHovered ? chartTheme.surfaceRaised : chartTheme.surface;
    ctx.fill();
    ctx.lineWidth = isHovered ? 2 : 1.5;
    ctx.strokeStyle = chartTheme.sapphire;
    ctx.stroke();

    const msCat = ms.category || (ms.id && ms.id.includes('retire') ? 'retirement' : (ms.id && ms.id.includes('college') ? 'education' : 'life'));
    const msImg = getMilestoneCanvasImage(msCat, isHovered ? chartTheme.onFill : chartTheme.cerulean, 13);
    if (msImg && msImg.complete && msImg.naturalWidth > 0 && !msImg._failed) {
        ctx.drawImage(msImg, Math.round(element.x - 6.5), Math.round(y_ms - 6.5), 13, 13);
    } else if (msImg && !msImg._failed && !msImg._hasHandler) {
        msImg._hasHandler = true;
        msImg.onload = () => chart.draw();
    } else {
        ctx.beginPath();
        ctx.arc(element.x, y_ms, 3, 0, 2 * Math.PI);
        ctx.fillStyle = isHovered ? chartTheme.onFill : chartTheme.cerulean;
        ctx.fill();
    }
}

function drawSingleEventPin(ctx, element, y0, ev, isHovered, chart) {
    ctx.beginPath();
    ctx.strokeStyle = chartTheme.alpha(chartTheme.amber, 0.35);
    ctx.lineWidth = 1.2;
    ctx.moveTo(element.x, element.y - 8);
    ctx.lineTo(element.x, y0 + 10);
    ctx.stroke();

    const evCat = ev.category || 'other';
    const theme = categoryTheme(evCat);
    const pinColor = isHovered ? chartTheme.onFill : theme.border;

    if (isHovered) {
        ctx.beginPath();
        ctx.arc(element.x, y0, 17, 0, 2 * Math.PI);
        ctx.fillStyle = theme.bgSoft;
        ctx.fill();
    }

    ctx.beginPath();
    ctx.arc(element.x, y0, isHovered ? 13 : 11.5, 0, 2 * Math.PI);
    ctx.fillStyle = isHovered ? chartTheme.surfaceRaised : chartTheme.surface;
    ctx.fill();
    ctx.lineWidth = isHovered ? 2.5 : 1.75;
    ctx.strokeStyle = pinColor;
    ctx.stroke();

    const imgSingle = getEventCanvasImage(ev, pinColor, 14);
    if (imgSingle && imgSingle.complete && imgSingle.naturalWidth > 0 && !imgSingle._failed) {
        ctx.drawImage(imgSingle, Math.round(element.x - 7), Math.round(y0 - 7), 14, 14);
    } else if (imgSingle && !imgSingle._failed && !imgSingle._hasHandler) {
        imgSingle._hasHandler = true;
        imgSingle.onload = () => chart.draw();
    } else {
        ctx.beginPath();
        ctx.arc(element.x, y0, 3, 0, 2 * Math.PI);
        ctx.fillStyle = pinColor;
        ctx.fill();
    }
}

function drawCompactClusterPin(ctx, element, y0, ev, N, chart) {
    const evCat = ev.category || 'other';
    const theme = categoryTheme(evCat);

    ctx.beginPath();
    ctx.strokeStyle = chartTheme.alpha(theme.border, 0.38);
    ctx.lineWidth = 1.2;
    ctx.moveTo(element.x, element.y - 8);
    ctx.lineTo(element.x, y0 + 10);
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(element.x - 3, y0 - 3, 10.5, 0, 2 * Math.PI);
    ctx.fillStyle = chartTheme.surfaceRaised;
    ctx.fill();
    ctx.lineWidth = 1;
    ctx.strokeStyle = chartTheme.alpha(theme.border, 0.5);
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(element.x, y0, 11.5, 0, 2 * Math.PI);
    ctx.fillStyle = chartTheme.surface;
    ctx.fill();
    ctx.lineWidth = 1.75;
    ctx.strokeStyle = theme.border;
    ctx.stroke();

    const imgComp = getEventCanvasImage(ev, theme.border, 14);
    if (imgComp && imgComp.complete && imgComp.naturalWidth > 0 && !imgComp._failed) {
        ctx.drawImage(imgComp, Math.round(element.x - 7), Math.round(y0 - 7), 14, 14);
    } else if (imgComp && !imgComp._failed && !imgComp._hasHandler) {
        imgComp._hasHandler = true;
        imgComp.onload = () => chart.draw();
    } else {
        ctx.beginPath();
        ctx.arc(element.x, y0, 3, 0, 2 * Math.PI);
        ctx.fillStyle = theme.border;
        ctx.fill();
    }

    const badgeX = element.x + 10;
    const badgeY = y0 - 8;
    ctx.beginPath();
    ctx.arc(badgeX, badgeY, 7.5, 0, 2 * Math.PI);
    ctx.fillStyle = chartTheme.ruby;
    ctx.fill();
    ctx.strokeStyle = chartTheme.surface;
    ctx.lineWidth = 1.5;
    ctx.stroke();

    ctx.fillStyle = chartTheme.onFill;
    ctx.font = `bold 9px ${chartTheme.fontFamily}`;
    ctx.fillText(`+${N}`, badgeX, badgeY + 0.5);
}

function drawExpandedClusterStack(ctx, element, eventsStarting, N, yr, shiftDown, hoverTarget, chart) {
    const topY = (element.y - 20 - (N - 1) * 28) + shiftDown;
    let hoveredPill = null;

    ctx.beginPath();
    ctx.strokeStyle = chartTheme.alpha(chartTheme.amber, 0.5);
    ctx.lineWidth = 1.5;
    ctx.setLineDash([3, 3]);
    ctx.moveTo(element.x, element.y - 8);
    ctx.lineTo(element.x, topY);
    ctx.stroke();
    ctx.setLineDash([]);

    for (let k = 0; k < N; k++) {
        const y_k = (element.y - 20 - k * 28) + shiftDown;
        const ev = eventsStarting[k];
        const isPinHovered = (hoverTarget?.type === 'event_pin' && hoverTarget.year === yr && hoverTarget.pinIndex === k);
        const evCat = ev.category || 'other';
        const theme = categoryTheme(evCat);
        const pinColor = isPinHovered ? chartTheme.onFill : theme.border;

        if (isPinHovered) {
            ctx.beginPath();
            ctx.arc(element.x, y_k, 18, 0, 2 * Math.PI);
            ctx.fillStyle = theme.bgSoft;
            ctx.fill();
        }

        ctx.beginPath();
        ctx.arc(element.x, y_k, isPinHovered ? 13.5 : 11.5, 0, 2 * Math.PI);
        ctx.fillStyle = isPinHovered ? chartTheme.surfaceRaised : chartTheme.surface;
        ctx.fill();
        ctx.lineWidth = isPinHovered ? 2.5 : 1.5;
        ctx.strokeStyle = pinColor;
        ctx.stroke();

        const imgK = getEventCanvasImage(ev, pinColor, 14);
        if (imgK && imgK.complete && imgK.naturalWidth > 0 && !imgK._failed) {
            ctx.drawImage(imgK, Math.round(element.x - 7), Math.round(y_k - 7), 14, 14);
        } else if (imgK && !imgK._failed && !imgK._hasHandler) {
            imgK._hasHandler = true;
            imgK.onload = () => chart.draw();
        } else {
            ctx.beginPath();
            ctx.arc(element.x, y_k, 3, 0, 2 * Math.PI);
            ctx.fillStyle = pinColor;
            ctx.fill();
        }

        if (isPinHovered) {
            hoveredPill = {
                name: ev.name,
                x: element.x,
                y: y_k,
                isRightSide: (element.x + 160 <= chart.chartArea.right)
            };
        }
    }
    return hoveredPill;
}

export const eventPinIconsPlugin = {
    id: 'eventPinIconsPlugin',
    afterDatasetsDraw(chart) {
        const { ctx, chartArea } = chart;
        if (!ctx || !chartArea || !state.scenariosData) return;
        const curScen = (state.scenariosData.scenarios || []).find(s => s.id === getGraphScenarioId('networth')) || {};
        const curEvts = (state.scenariosData.events_catalog || []).filter(e => (curScen.event_ids || []).includes(e.id));
        const msList = state.scenariosData.milestones || [];

        const dsIdx = chart.data.datasets.findIndex(d => !d.isMonteCarlo && ((d.scenarioId && d.scenarioId === curScen.id) || d.label === curScen.name));
        if (dsIdx === -1) return;
        const meta = chart.getDatasetMeta(dsIdx);
        if (!meta || !meta.data) return;

        const pts = chart._allPoints || [];
        const hoveredClusterYr = chart._hoveredClusterYear;
        const hoverTarget = chart._hoverTarget;
        let activeHoveredPill = null;

        ctx.save();
        ctx.beginPath();
        ctx.rect(chartArea.left, chartArea.top, chartArea.right - chartArea.left, chartArea.bottom - chartArea.top);
        ctx.clip();

        pts.forEach((p, idx) => {
            if (p.is_historical) return;
            const yr = p.year;
            const element = meta.data[idx];
            if (!element || element.skip || isNaN(element.x) || isNaN(element.y)) return;
            if (element.x < chartArea.left - 24 || element.x > chartArea.right + 24) return;

            const eventsStarting = curEvts.filter(e => (e.year || getPlanStartYear()) === yr);
            const ms = msList.find(m => m.year === yr);
            const N = eventsStarting.length;
            if (N === 0 && !ms) return;

            const maxAllowedY = chartArea.top + 20;
            const totalPins = N + (ms ? 1 : 0);
            const rawTopY = element.y - 20 - (totalPins > 1 ? (totalPins - 1) * 28 : 0);
            const shiftDown = rawTopY < maxAllowedY ? (maxAllowedY - rawTopY) : 0;
            const isClusterExpanded = (N > 1 && hoveredClusterYr === yr);

            ctx.save();

            if (ms) {
                const y_ms = element.y - 20 - (N > 0 ? (N * 28) : 0) + shiftDown;
                const isHovered = (hoverTarget?.type === 'milestone_pin' && hoverTarget.year === yr);
                drawMilestonePin(ctx, element, y_ms, ms, yr, isHovered, N, shiftDown, chart);
            }

            if (N === 1) {
                const y0 = (element.y - 20) + shiftDown;
                const isHovered = (hoverTarget?.type === 'event_pin' && hoverTarget.year === yr);
                drawSingleEventPin(ctx, element, y0, eventsStarting[0], isHovered, chart);
            } else if (N > 1 && !isClusterExpanded) {
                const y0 = (element.y - 20) + shiftDown;
                drawCompactClusterPin(ctx, element, y0, eventsStarting[0], N, chart);
            } else if (N > 1 && isClusterExpanded) {
                const pill = drawExpandedClusterStack(ctx, element, eventsStarting, N, yr, shiftDown, hoverTarget, chart);
                if (pill) activeHoveredPill = pill;
            }

            ctx.restore();
        });

        if (activeHoveredPill) {
            ctx.save();
            const labelText = activeHoveredPill.name;
            ctx.font = `600 11px ${chartTheme.fontFamily}`;
            const textWidth = ctx.measureText(labelText).width;
            const pillPadX = 7;
            const pillH = 20;
            const pillW = textWidth + pillPadX * 2;

            const pillX = activeHoveredPill.isRightSide
                ? (activeHoveredPill.x + 18)
                : (activeHoveredPill.x - 18 - pillW);
            const pillY = activeHoveredPill.y - pillH / 2;

            ctx.shadowColor = chartTheme.shadow;
            ctx.shadowBlur = 6;
            ctx.shadowOffsetX = 0;
            ctx.shadowOffsetY = 2;

            ctx.beginPath();
            drawPillPath(ctx, pillX, pillY, pillW, pillH, 6);
            ctx.fillStyle = chartTheme.surface;
            ctx.fill();
            ctx.lineWidth = 1.5;
            ctx.strokeStyle = chartTheme.amber;
            ctx.stroke();

            ctx.shadowColor = 'transparent';
            ctx.shadowBlur = 0;

            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = chartTheme.amber;
            ctx.fillText(labelText, pillX + pillPadX, activeHoveredPill.y);
            ctx.restore();
        }
        ctx.restore();
    }
};

const openEditEventModal = (...args) => (
    typeof window !== 'undefined' && window.openEditEventModal
        ? window.openEditEventModal(...args)
        : null
);

function setupNetWorthToggles(togglesContainer, ctx, captionEl, scenarios) {
    if (!togglesContainer) return;
    togglesContainer.replaceChildren();
    const effectiveScenId = getGraphScenarioId('networth');
    renderGraphScenarioToggles(togglesContainer, {
        graphKey: 'networth',
        selectedScenarioId: effectiveScenId,
        onSelect: (scenId) => {
            setGraphScenarioId('networth', scenId);
            renderNetWorthLens(ctx, togglesContainer, captionEl, true);
        }
    });

    if (scenarios.length > 0) {
        const btnMcToggle = document.createElement('button');
        btnMcToggle.type = 'button';
        btnMcToggle.className = `btn btn-sm ${state.showMonteCarloCorridor ? 'btn-primary' : 'btn-secondary'}`;
        btnMcToggle.style.cssText = 'font-size: 0.71875rem; padding: 2px 9px; margin-left: 10px; font-weight: 600; border-radius: 6px; cursor: pointer;';
        btnMcToggle.textContent = `Monte Carlo Band: ${state.showMonteCarloCorridor ? 'ON' : 'OFF'}`;
        btnMcToggle.title = 'Toggle 10th to 90th percentile stochastic Monte Carlo uncertainty corridor';
        btnMcToggle.onclick = () => {
            state.showMonteCarloCorridor = !state.showMonteCarloCorridor;
            try { localStorage.setItem('scen_show_mc_corridor', state.showMonteCarloCorridor ? 'true' : 'false'); } catch (e) {}
            renderNetWorthLens(ctx, togglesContainer, captionEl, false);
        };
        togglesContainer.appendChild(btnMcToggle);
    }
}

function handleChartClick(event, elements, chart) {
    if (window._suppressChartClick) return;
    const target = chart._hoverTarget;
    if (target?.type === 'event_pin' && target.event) {
        openEditEventModal(target.event.id);
        return;
    }
    if (target?.type === 'milestone_pin') {
        const yr = target.year;
        state.inspectedYear = yr;
        const scrubber = document.getElementById('timeline-scrubber');
        if (scrubber) scrubber.value = yr;
        updateScrubberNeedle(yr);
        inspectTimelineYear(yr);
        return;
    }
    if (target?.type === 'main_circle' || (elements && elements.length > 0)) {
        const idx = target?.index ?? elements[0].index;
        const pts = chart._allPoints || [];
        const pt = pts[idx];
        if (pt) {
            const yr = pt.year;
            state.inspectedYear = yr;
            const scrubber = document.getElementById('timeline-scrubber');
            if (scrubber) scrubber.value = yr;
            updateScrubberNeedle(yr);
            inspectTimelineYear(yr);
        }
    }
}

export function renderNetWorthLens(ctx, togglesContainer, captionEl, smooth = false) {
    applyChartStageHeight(false);
    if (captionEl) {
        captionEl.textContent = 'Multi-Scenario Net Worth Trajectory: Continuous lifetime comparison bridging historical actuals into future milestones. Shaded corridor displays the 10th to 90th percentile stochastic Monte Carlo uncertainty range.';
    }

    if (!state.scenariosData) return;

    const curves = state.scenariosData.comparison_curves || [];
    const historical = state.scenariosData.historical_ribbon || [];
    const scenarios = state.scenariosData.scenarios || [];
    const { minYear, maxYear } = getTimelineRange();

    const allPoints = buildAllPoints(historical, curves);
    const labels = allPoints.map(p => p.year);

    const effectiveScenId = getGraphScenarioId('networth');
    const currentScenObj = (state.scenariosData.scenarios || []).find(s => s.id === effectiveScenId) || {};

    const mcSource = getMonteCarloForScenario(effectiveScenId);
    if (state.showMonteCarloCorridor && !mcSource) {
        ensureMonteCarloForScenario(effectiveScenId);
    }
    const mcTimeline = (mcSource && mcSource.percentiles_timeline) || [];

    const datasets = buildNetWorthDatasets(allPoints, scenarios, currentScenObj, effectiveScenId, mcTimeline, state.showMonteCarloCorridor);
    setupNetWorthToggles(togglesContainer, ctx, captionEl, scenarios);
    const yearYBounds = computeYearYBounds(allPoints, datasets);

    // If chart already exists and is line chart, update datasets and bounds in-place
    if (state.scenarioComparisonChart && state.scenarioComparisonChart.config.type === 'line') {
        state.scenarioComparisonChart.options.interaction.mode = 'nearLineOrEvent';
        if (state.scenarioComparisonChart.options.plugins && state.scenarioComparisonChart.options.plugins.tooltip) {
            state.scenarioComparisonChart.options.plugins.tooltip.enabled = false;
            state.scenarioComparisonChart.options.plugins.tooltip.external = customNetWorthTooltip;
            state.scenarioComparisonChart.options.plugins.tooltip.position = 'eventPinPositioner';
        }
        state.scenarioComparisonChart._allPoints = allPoints;
        state.scenarioComparisonChart._yearYBounds = yearYBounds;
        state.scenarioComparisonChart._minDataYear = allPoints.length ? allPoints[0].year : 2018;
        state.scenarioComparisonChart._maxDataYear = allPoints.length ? allPoints[allPoints.length - 1].year : 2060;
        state.scenarioComparisonChart.data.labels = labels;
        state.scenarioComparisonChart.data.datasets = datasets;
        updateChartWindowContinuous(state.scenarioComparisonChart, minYear, maxYear, smooth);
        bindScenarioHoverListeners();
        state.scenarioComparisonChart.update('none');
        return;
    }

    state.scenarioComparisonChart = new Chart(ctx, {
        type: 'line',
        data: { labels, datasets },
        plugins: [eventPinIconsPlugin],
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'nearLineOrEvent', intersect: false },
            onClick: handleChartClick,
            plugins: {
                legend: { display: false },
                tooltip: {
                    enabled: false,
                    external: customNetWorthTooltip,
                    position: 'eventPinPositioner',
                    padding: 10,
                    cornerRadius: 8,
                    bodySpacing: 4,
                    titleSpacing: 4,
                    displayColors: (tooltipItem) => {
                        const chart = tooltipItem?.chart || state.scenarioComparisonChart;
                        return chart?._hoverTarget?.type === 'main_circle';
                    },
                    callbacks: buildNetWorthTooltipCallbacks()
                }
            },
            scales: {
                x: {
                    ticks: { maxRotation: 45, maxTicksLimit: 14 }
                },
                y: {
                    ticks: {
                        callback: (v) => fmtShortCurrency(v)
                    }
                }
            }
        }
    });

    state.scenarioComparisonChart._allPoints = allPoints;
    state.scenarioComparisonChart._yearYBounds = yearYBounds;
    state.scenarioComparisonChart._minDataYear = allPoints.length ? allPoints[0].year : 2018;
    state.scenarioComparisonChart._maxDataYear = allPoints.length ? allPoints[allPoints.length - 1].year : 2060;
    updateChartWindowContinuous(state.scenarioComparisonChart, minYear, maxYear, false);
    bindScenarioHoverListeners();
    state.scenarioComparisonChart.update('none');
}
