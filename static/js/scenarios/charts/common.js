/**
 * Chart.js Common Helpers, Tooltip Positioners & Interaction Modes
 */
import { state, escapeHtml } from '../state.js';

export function distToSegment(px, py, x1, y1, x2, y2) {
    const dx = x2 - x1;
    const dy = y2 - y1;
    if (dx === 0 && dy === 0) return Math.hypot(px - x1, py - y1);
    const t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)));
    return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}

// Helper: Word-wrap long strings to keep tooltips compact and prevent overlapping icons

export function wrapText(text, maxChars = 35) {
    if (!text) return [];
    const paragraphs = String(text).split('\n');
    const allLines = [];

    paragraphs.forEach(para => {
        const words = para.trim().split(/\s+/);
        let currentLine = '';

        words.forEach(word => {
            if (!word) return;
            if (!currentLine) {
                if (word.length > maxChars) {
                    for (let i = 0; i < word.length; i += maxChars) {
                        allLines.push(word.slice(i, i + maxChars));
                    }
                } else {
                    currentLine = word;
                }
            } else if ((currentLine + ' ' + word).length <= maxChars) {
                currentLine += ' ' + word;
            } else {
                allLines.push(currentLine);
                if (word.length > maxChars) {
                    for (let i = 0; i < word.length; i += maxChars) {
                        allLines.push(word.slice(i, i + maxChars));
                    }
                    currentLine = '';
                } else {
                    currentLine = word;
                }
            }
        });
        if (currentLine) {
            allLines.push(currentLine);
        }
    });

    return allLines;
}

// Register custom event pin tooltip positioner
if (typeof Chart !== 'undefined' && Chart.Tooltip && Chart.Tooltip.positioners) {
    Chart.Tooltip.positioners.eventPinPositioner = function(items, eventPosition) {
        const chart = this.chart;
        const target = chart?._hoverTarget;
        if (chart && target && typeof target.x === 'number' && typeof target.y === 'number') {
            if (target.type === 'event_pin' || target.type === 'milestone_pin') {
                const chartArea = chart.chartArea || { left: 0, right: 600, top: 0, bottom: 400 };
                const spaceLeft = target.x - chartArea.left;
                const spaceRight = chartArea.right - target.x;

                // Prefer placing tooltip to the LEFT of the pin column so icons remain 100% visible
                if (spaceLeft >= 220 || spaceLeft >= spaceRight) {
                    return { x: target.x - 16, y: target.y, xAlign: 'right', yAlign: 'center' };
                } else {
                    // Place tooltip to the RIGHT, offset past icons and any label pills
                    const isExpandedCluster = (target.totalEvents > 1 && chart._hoveredClusterYear === target.year);
                    const offsetRight = isExpandedCluster ? 135 : 18;
                    return { x: target.x + offsetRight, y: target.y, xAlign: 'left', yAlign: 'center' };
                }
            }

            // For main_circle: anchor directly to curve point
            return { x: target.x, y: target.y };
        }
        if (items && items.length) {
            return { x: items[0].element.x, y: items[0].element.y };
        }
        return false;
    };
}

// Register custom hover interaction mode
if (typeof Chart !== 'undefined' && Chart.Interaction && Chart.Interaction.modes) {
    Chart.Interaction.modes.nearLineOrEvent = function(chart, e, options, useFinalPosition) {
        if (!state.scenariosData || (typeof window !== 'undefined' && window._chartZoomPanActive)) {
            chart._hoverTarget = null;
            chart._hoveredClusterYear = null;
            return [];
        }

        const canvas = chart.canvas;
        const rect = canvas ? canvas.getBoundingClientRect() : { left: 0, top: 0 };
        const mx = typeof e.x === 'number' ? e.x : ((e.native || e).clientX - rect.left);
        const my = typeof e.y === 'number' ? e.y : ((e.native || e).clientY - rect.top);
        if (isNaN(mx) || isNaN(my)) return [];

        const curScen = (state.scenariosData?.scenarios || []).find(s => s.id === state.selectedScenarioId) || {};
        const curEvts = (state.scenariosData?.events_catalog || []).filter(e => (curScen.event_ids || []).includes(e.id));
        const msList = state.scenariosData?.milestones || [];
        const pts = chart._allPoints || [];

        const dsIdx = chart.data.datasets.findIndex(d => !d.isMonteCarlo && ((d.scenarioId && d.scenarioId === curScen.id) || d.label === curScen.name));
        if (dsIdx === -1) return [];
        const meta = chart.getDatasetMeta(dsIdx);
        if (!meta || !meta.data || !meta.data.length) return [];

        const MAIN_CIRCLE_RADIUS = 13;
        const PIN_HIT_RADIUS = 18;
        const isCurrentlyExpandedYr = chart._hoveredClusterYear;

        for (let i = 0; i < meta.data.length; i++) {
            const p = meta.data[i];
            if (!p || p.skip || isNaN(p.x) || isNaN(p.y)) continue;
            if (chart.chartArea && (p.x < chart.chartArea.left - 4 || p.x > chart.chartArea.right + 4)) continue;
            const pt = pts[i];
            if (!pt || pt.is_historical) continue;
            const yr = pt.year;

            const eventsStarting = curEvts.filter(ev => (ev.year || 2026) === yr);
            const ms = msList.find(m => m.year === yr);
            const N = eventsStarting.length;

            const maxAllowedY = chart.chartArea ? (chart.chartArea.top + 20) : 24;
            const totalPins = N + (ms ? 1 : 0);
            const rawTopY = p.y - 20 - (totalPins > 1 ? (totalPins - 1) * 28 : 0);
            const shiftDown = rawTopY < maxAllowedY ? (maxAllowedY - rawTopY) : 0;

            // 1. Check if mouse is hovering over an event circle, text pill, or cluster column
            if (N > 0) {
                let hitK = -1;
                const isThisClusterOpen = (N > 1 && isCurrentlyExpandedYr === yr);

                if (isThisClusterOpen) {
                    // When expanded, check each pin circle and narrow vertical column zone
                    for (let k = 0; k < N; k++) {
                        const y_k = (p.y - 20 - k * 28) + shiftDown;
                        // Circle hit
                        if (Math.hypot(mx - p.x, my - y_k) <= PIN_HIT_RADIUS) { hitK = k; break; }
                        // Narrow vertical column hit around this pin
                        if (Math.abs(mx - p.x) <= 18 && Math.abs(my - y_k) <= 14) { hitK = k; break; }
                    }
                } else {
                    // When collapsed, check primary pin at y_0
                    const y_0 = (p.y - 20) + shiftDown;
                    if (Math.hypot(mx - p.x, my - y_0) <= PIN_HIT_RADIUS + 2) hitK = 0;
                }

                // Check cluster column area (triggers vertical expansion)
                const clusterTop = (p.y - 20 - (N - 1) * 28) + shiftDown - 16;
                const clusterBottom = p.y - 6;
                const inClusterCol = (Math.abs(mx - p.x) <= 20 && my >= clusterTop && my <= clusterBottom);

                if (hitK !== -1 || (N > 1 && inClusterCol)) {
                    const activeK = hitK !== -1 ? hitK : (isThisClusterOpen ? (N - 1) : 0);
                    const activeY = (p.y - 20 - activeK * 28) + shiftDown;

                    chart._hoverTarget = { type: 'event_pin', event: eventsStarting[activeK], year: yr, index: i, pinIndex: activeK, totalEvents: N, x: p.x, y: activeY };
                    chart._hoveredClusterYear = yr;
                    if (canvas) canvas.style.cursor = 'pointer';

                    const targetKey = `event_pin_${yr}_${activeK}`;
                    if (chart._lastTargetKey !== targetKey) {
                        chart._lastTargetKey = targetKey;
                        requestAnimationFrame(() => {
                            if (chart && !chart.destroyed) {
                                chart.draw();
                                if (chart.tooltip) chart.tooltip.update(true);
                            }
                        });
                    }

                    return [{ datasetIndex: dsIdx, index: i, element: p }];
                }
            }

            // 2. Check if hovering a milestone circle
            if (ms) {
                const y_ms = p.y - 20 - (N > 0 ? (N * 28) : 0) + shiftDown;
                if (Math.hypot(mx - p.x, my - y_ms) <= PIN_HIT_RADIUS) {
                    chart._hoverTarget = { type: 'milestone_pin', milestone: ms, year: yr, index: i, x: p.x, y: y_ms };
                    if (canvas) canvas.style.cursor = 'pointer';

                    const targetKey = `milestone_pin_${yr}`;
                    if (chart._lastTargetKey !== targetKey) {
                        chart._lastTargetKey = targetKey;
                        requestAnimationFrame(() => {
                            if (chart && !chart.destroyed) {
                                chart.draw();
                                if (chart.tooltip) chart.tooltip.update(true);
                            }
                        });
                    }

                    return [{ datasetIndex: dsIdx, index: i, element: p }];
                }
            }

            // 3. Check if hovering the main graph circle at (p.x, p.y)
            if (Math.hypot(mx - p.x, my - p.y) <= MAIN_CIRCLE_RADIUS) {
                chart._hoverTarget = { type: 'main_circle', year: yr, index: i, x: p.x, y: p.y };
                chart._hoveredClusterYear = null;
                if (canvas) canvas.style.cursor = 'pointer';

                const targetKey = `main_circle_${yr}`;
                if (chart._lastTargetKey !== targetKey) {
                    chart._lastTargetKey = targetKey;
                    requestAnimationFrame(() => {
                        if (chart && !chart.destroyed) {
                            chart.draw();
                            if (chart.tooltip) chart.tooltip.update(true);
                        }
                    });
                }

                const items = [];
                for (let d = 0; d < chart.data.datasets.length; d++) {
                    if (chart.isDatasetVisible(d)) {
                        const m = chart.getDatasetMeta(d);
                        if (m && m.data && m.data[i]) {
                            items.push({ datasetIndex: d, index: i, element: m.data[i] });
                        }
                    }
                }
                return items.length ? items : [{ datasetIndex: dsIdx, index: i, element: p }];
            }
        }

        // Empty space or away from circles: suppress tooltip completely
        chart._hoverTarget = null;
        chart._hoveredClusterYear = null;
        if (canvas) canvas.style.cursor = 'default';

        if (chart._lastTargetKey !== 'none') {
            chart._lastTargetKey = 'none';
            requestAnimationFrame(() => {
                if (chart && !chart.destroyed) {
                    chart.draw();
                }
            });
        }

        return [];
    };
}

export function cleanSmoothYScaleTicks(scale) {
    if (!scale || !Array.isArray(scale.ticks) || scale.ticks.length < 4) return;
    const step = Math.abs(scale.ticks[2].value - scale.ticks[1].value);
    if (step <= 0) return;
    scale.ticks = scale.ticks.filter((t, idx) => {
        if (idx > 0 && idx < scale.ticks.length - 1) return true;
        if (Math.abs(t.value) < 1e-6) return true;
        const rem = Math.abs(t.value % step);
        return rem < step * 0.02 || Math.abs(rem - step) < step * 0.02;
    });
}

export function stabilizeYScaleWidth(scale) {
    if (scale && scale.width < 60) {
        scale.width = 60;
    }
}

export function buildCleanXScaleTicks(scale) {
    if (!scale) return;
    const min = Number.isFinite(scale.min) ? scale.min : 2018;
    const max = Number.isFinite(scale.max) ? scale.max : 2060;
    const span = Math.max(1, max - min);
    const step = span <= 12 ? 1 : (span <= 24 ? 2 : 5);
    const first = Math.ceil((min - 1e-6) / step) * step;
    const last = Math.floor(max + 1e-6);
    const ticks = [];
    for (let yr = first; yr <= last; yr += step) {
        ticks.push({ value: yr });
    }
    scale.ticks = ticks;
}

export function applySmoothXScale(chart, minYear, maxYear) {
    if (!chart?.options?.scales?.x) return;
    const minDomain = chart._minDataYear ?? 2018;
    const maxDomain = chart._maxDataYear ?? 2060;
    const effMin = Math.max(minDomain, Math.min(maxDomain - 3, minYear));
    const effMax = Math.max(effMin + 3, Math.min(maxDomain, maxYear));
    const pad = chart.config?.type === 'bar' ? 0.45 : 0;
    const sx = chart.options.scales.x;
    sx.type = 'linear';
    sx.offset = false;
    sx.min = effMin - pad;
    sx.max = effMax + pad;
    sx.afterBuildTicks = buildCleanXScaleTicks;
    sx.ticks = { ...(sx.ticks || {}), autoSkip: false, minRotation: 0, maxRotation: 0, callback: (v) => `${Math.round(v)}` };
    chart._curXMin = effMin;
    chart._curXMax = effMax;
}

export function applySmoothYScale(chart, rawMin, rawMax, smooth = false) {
    if (!chart || !chart.options || !chart.options.scales || !chart.options.scales.y) return;
    const safeMin = Number.isFinite(rawMin) ? rawMin : 0;
    const safeMax = Number.isFinite(rawMax) ? rawMax : 100000;
    const targetMin = safeMin < 0 ? safeMin * 1.08 : 0;
    const targetMax = Math.max(safeMax * 1.08, targetMin + 1000);

    chart._targetYMin = targetMin;
    chart._targetYMax = targetMax;

    if (!smooth || typeof chart._curYMax !== 'number' || typeof chart._curYMin !== 'number') {
        chart._curYMin = targetMin;
        chart._curYMax = targetMax;
    } else {
        chart._curYMin += (targetMin - chart._curYMin) * 0.22;
        chart._curYMax += (targetMax - chart._curYMax) * 0.22;
    }

    chart.options.scales.y.min = chart._curYMin;
    chart.options.scales.y.max = chart._curYMax;
    chart.options.scales.y.afterBuildTicks = cleanSmoothYScaleTicks;
    chart.options.scales.y.afterFit = stabilizeYScaleWidth;
}

export function updateChartWindowContinuous(chart, minYear, maxYear, smooth = false) {
    if (!chart) return;
    applySmoothXScale(chart, minYear, maxYear);
    if (chart._longevitySeries || state.currentLens === 'longevity') return;
    const effMin = chart._curXMin ?? minYear;
    const effMax = chart._curXMax ?? maxYear;
    const boundsMap = chart._yearYBounds;
    let rawMin = 0;
    let rawMax = 0;
    if (boundsMap && typeof boundsMap.get === 'function') {
        const evalAt = (yFloat) => {
            const y0 = Math.floor(yFloat);
            const y1 = Math.ceil(yFloat);
            const b0 = boundsMap.get(y0);
            const b1 = boundsMap.get(y1);
            if (b0 && b1) {
                const t = yFloat - y0;
                rawMin = Math.min(rawMin, b0.min + (b1.min - b0.min) * t);
                rawMax = Math.max(rawMax, b0.max + (b1.max - b0.max) * t);
            } else if (b0 || b1) {
                const b = b0 || b1;
                rawMin = Math.min(rawMin, b.min);
                rawMax = Math.max(rawMax, b.max);
            }
        };
        evalAt(effMin);
        evalAt(effMax);
        for (let yr = Math.ceil(effMin); yr <= Math.floor(effMax); yr++) {
            const b = boundsMap.get(yr);
            if (b) {
                if (b.min < rawMin) rawMin = b.min;
                if (b.max > rawMax) rawMax = b.max;
            }
        }
    }
    applySmoothYScale(chart, rawMin, rawMax, smooth);
}

export function renderGraphScenarioToggles(togglesContainer) {
    if (!togglesContainer || !state.scenariosData) return;
    const scenarios = state.scenariosData.scenarios || [];
    const theme = typeof window !== 'undefined' ? window.CHART_THEME : null;
    scenarios.forEach((scen, idx) => {
        const isSelected = scen.id === state.selectedScenarioId;
        const isActive = scen.id === state.scenariosData.active_scenario_id;
        const scenColor = theme ? theme.normalizeScenarioColor(scen.color, idx) : (scen.color || '#1D4ED8');
        const badge = document.createElement('span');
        badge.className = 'scenario-graph-toggle-pill';
        badge.style.cssText = `display: inline-flex; align-items: center; gap: 5px; padding: 3px 10px; border-radius: 6px; font-weight: 600; cursor: pointer; border: 1px solid ${isSelected ? scenColor : scenColor + '40'}; background: ${isSelected ? scenColor + '25' : scenColor + '10'}; color: ${scenColor}; font-size: 0.75rem; transition: all 0.15s ease; user-select: none;`;
        badge.title = `Click to select and activate ${scen.name}`;
        badge.innerHTML = `<span style="width: 8px; height: 8px; border-radius: 50%; background: ${scenColor};"></span> ${escapeHtml(scen.name)}${isSelected ? ' ★' : ''}${isActive && !isSelected ? ' (Active)' : ''}`;
        badge.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (typeof window.switchToScenario === 'function') {
                window.switchToScenario(scen.id);
            }
        };
        togglesContainer.appendChild(badge);
    });
}
