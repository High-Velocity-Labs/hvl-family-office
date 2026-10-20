/**
 * static/js/scenarios/charts/net_worth_helpers.js
 * Chart.js Event Pin Icons plugin and Canvas drawing helpers for Net Worth Lens.
 */

import {
    state,
    CATEGORY_THEMES,
    getEventCanvasImage,
    getMilestoneCanvasImage
} from '../state.js';

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
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.4)';
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
        ctx.fillStyle = 'rgba(59, 130, 246, 0.3)';
        ctx.fill();
    }

    ctx.beginPath();
    ctx.arc(element.x, y_ms, isHovered ? 12 : 10, 0, 2 * Math.PI);
    ctx.fillStyle = isHovered ? '#1E293B' : '#0F172A';
    ctx.fill();
    ctx.lineWidth = isHovered ? 2 : 1.5;
    ctx.strokeStyle = '#3B82F6';
    ctx.stroke();

    const msCat = ms.category || (ms.id && ms.id.includes('retire') ? 'retirement' : (ms.id && ms.id.includes('college') ? 'education' : 'life'));
    const msImg = getMilestoneCanvasImage(msCat, isHovered ? '#FFFFFF' : '#60A5FA', 13);
    if (msImg && msImg.complete && msImg.naturalWidth > 0 && !msImg._failed) {
        ctx.drawImage(msImg, Math.round(element.x - 6.5), Math.round(y_ms - 6.5), 13, 13);
    } else if (msImg && !msImg._failed && !msImg._hasHandler) {
        msImg._hasHandler = true;
        msImg.onload = () => chart.draw();
    } else {
        ctx.beginPath();
        ctx.arc(element.x, y_ms, 3, 0, 2 * Math.PI);
        ctx.fillStyle = isHovered ? '#FFFFFF' : '#60A5FA';
        ctx.fill();
    }
}

function drawSingleEventPin(ctx, element, y0, ev, isHovered, chart) {
    ctx.beginPath();
    ctx.strokeStyle = 'rgba(245, 158, 11, 0.35)';
    ctx.lineWidth = 1.2;
    ctx.moveTo(element.x, element.y - 8);
    ctx.lineTo(element.x, y0 + 10);
    ctx.stroke();

    const evCat = ev.category || 'other';
    const theme = CATEGORY_THEMES[evCat] || CATEGORY_THEMES.other;
    const pinColor = isHovered ? '#FFFFFF' : theme.border;

    if (isHovered) {
        ctx.beginPath();
        ctx.arc(element.x, y0, 17, 0, 2 * Math.PI);
        ctx.fillStyle = theme.bg.replace('0.92', '0.35');
        ctx.fill();
    }

    ctx.beginPath();
    ctx.arc(element.x, y0, isHovered ? 13 : 11.5, 0, 2 * Math.PI);
    ctx.fillStyle = isHovered ? '#1E293B' : '#0F172A';
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
    const theme = CATEGORY_THEMES[evCat] || CATEGORY_THEMES.other;

    ctx.beginPath();
    ctx.strokeStyle = theme.border + '60';
    ctx.lineWidth = 1.2;
    ctx.moveTo(element.x, element.y - 8);
    ctx.lineTo(element.x, y0 + 10);
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(element.x - 3, y0 - 3, 10.5, 0, 2 * Math.PI);
    ctx.fillStyle = '#1E293B';
    ctx.fill();
    ctx.lineWidth = 1;
    ctx.strokeStyle = theme.border + '80';
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(element.x, y0, 11.5, 0, 2 * Math.PI);
    ctx.fillStyle = '#0F172A';
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
    ctx.fillStyle = '#EF4444';
    ctx.fill();
    ctx.strokeStyle = '#0F172A';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    ctx.fillStyle = '#FFFFFF';
    ctx.font = 'bold 9px -apple-system, BlinkMacSystemFont, sans-serif';
    ctx.fillText(`+${N}`, badgeX, badgeY + 0.5);
}

function drawExpandedClusterStack(ctx, element, eventsStarting, N, yr, shiftDown, hoverTarget, chart) {
    const topY = (element.y - 20 - (N - 1) * 28) + shiftDown;
    let hoveredPill = null;

    ctx.beginPath();
    ctx.strokeStyle = 'rgba(245, 158, 11, 0.5)';
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
        const theme = CATEGORY_THEMES[evCat] || CATEGORY_THEMES.other;
        const pinColor = isPinHovered ? '#FFFFFF' : theme.border;

        if (isPinHovered) {
            ctx.beginPath();
            ctx.arc(element.x, y_k, 18, 0, 2 * Math.PI);
            ctx.fillStyle = theme.bg.replace('0.92', '0.35');
            ctx.fill();
        }

        ctx.beginPath();
        ctx.arc(element.x, y_k, isPinHovered ? 13.5 : 11.5, 0, 2 * Math.PI);
        ctx.fillStyle = isPinHovered ? '#1E293B' : '#0F172A';
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
        const curScen = (state.scenariosData.scenarios || []).find(s => s.id === state.selectedScenarioId) || {};
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

            const eventsStarting = curEvts.filter(e => (e.year || 2026) === yr);
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
            ctx.font = '600 11px -apple-system, BlinkMacSystemFont, sans-serif';
            const textWidth = ctx.measureText(labelText).width;
            const pillPadX = 7;
            const pillH = 20;
            const pillW = textWidth + pillPadX * 2;

            const pillX = activeHoveredPill.isRightSide
                ? (activeHoveredPill.x + 18)
                : (activeHoveredPill.x - 18 - pillW);
            const pillY = activeHoveredPill.y - pillH / 2;

            ctx.shadowColor = 'rgba(0, 0, 0, 0.5)';
            ctx.shadowBlur = 6;
            ctx.shadowOffsetX = 0;
            ctx.shadowOffsetY = 2;

            ctx.beginPath();
            drawPillPath(ctx, pillX, pillY, pillW, pillH, 6);
            ctx.fillStyle = '#0F172A';
            ctx.fill();
            ctx.lineWidth = 1.5;
            ctx.strokeStyle = '#F59E0B';
            ctx.stroke();

            ctx.shadowColor = 'transparent';
            ctx.shadowBlur = 0;

            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = '#F59E0B';
            ctx.fillText(labelText, pillX + pillPadX, activeHoveredPill.y);
            ctx.restore();
        }
        ctx.restore();
    }
};
