/**
 * static/js/scenarios/charts/net_worth_config.js
 * Dataset construction, point normalization, and tooltip callbacks for Net Worth Lens.
 */

import { state } from '../state.js';
export { buildNetWorthTooltipCallbacks } from './net_worth_tooltip.js';

export function buildAllPoints(historical = [], curves = []) {
    const allPoints = [];
    historical.forEach(h => {
        allPoints.push({
            year: h.year,
            label: `${h.year}`,
            is_historical: true,
            historical_val: h.true_net_worth
        });
    });
    curves.forEach(c => {
        allPoints.push({
            year: c.year,
            label: `${c.year} (Age ${c.age_primary || c.age})`,
            is_historical: false,
            ...c
        });
    });
    return allPoints;
}

export function computeYearYBounds(allPoints, datasets) {
    const yearYBounds = new Map();
    allPoints.forEach((p, idx) => {
        let yMin = 0;
        let yMax = 0;
        datasets.forEach(ds => {
            const v = ds.data ? ds.data[idx] : null;
            if (typeof v === 'number' && Number.isFinite(v)) {
                if (v < yMin) yMin = v;
                if (v > yMax) yMax = v;
            }
        });
        yearYBounds.set(p.year, { min: yMin, max: yMax });
    });
    return yearYBounds;
}

export function buildNetWorthDatasets(allPoints, scenarios, currentScenObj, effectiveScenId, mcTimeline, showMonteCarloCorridor) {
    const datasets = [];
    const theme = window.CHART_THEME;

    // 1. Historical actuals dataset
    const hasHistorical = allPoints.some(p => p.is_historical);
    const histData = allPoints.map(p => (hasHistorical && p.is_historical) ? p.historical_val : ((hasHistorical && p.year === 2026) ? (p.scen_baseline || p[state.selectedScenarioId]) : null));
    datasets.push({
        scenarioId: 'historical_actuals',
        label: 'Historical Actuals (2018–2025)',
        data: histData,
        borderColor: (theme && theme.netWorth.historical) || '#64748B',
        backgroundColor: (theme && theme.netWorth.historicalFill) || 'rgba(100, 116, 139, 0.08)',
        borderWidth: 2,
        borderDash: [4, 4],
        pointRadius: allPoints.map(p => p.is_historical ? 2 : 0),
        tension: 0.25,
        fill: true,
    });

    // 2. Monte Carlo corridor
    if (showMonteCarloCorridor && mcTimeline.length > 0) {
        const p90Data = allPoints.map(p => {
            if (p.is_historical) return null;
            const pt = mcTimeline.find(m => m.year === p.year);
            return pt ? pt.p90 : null;
        });
        const p10Data = allPoints.map(p => {
            if (p.is_historical) return null;
            const pt = mcTimeline.find(m => m.year === p.year);
            return pt ? pt.p10 : null;
        });

        const corridorLabel = `Monte Carlo 10th–90th Range (${currentScenObj.name || 'Selected Plan'})`;
        const corridorBorder = (theme && theme.netWorth.corridorBorder) || 'rgba(29, 78, 216, 0.45)';
        const corridorFill = (theme && theme.netWorth.corridorFill) || 'rgba(29, 78, 216, 0.12)';

        datasets.push({
            label: `${corridorLabel} - Top (90th)`,
            isMonteCarlo: true,
            scenarioId: `mc_${effectiveScenId}_p90`,
            data: p90Data,
            borderColor: corridorBorder,
            borderWidth: 1.5,
            borderDash: [5, 4],
            pointRadius: 0,
            pointHoverRadius: 0,
            tension: 0.25,
            fill: false,
        });

        datasets.push({
            label: corridorLabel,
            isMonteCarlo: true,
            scenarioId: `mc_${effectiveScenId}_p10`,
            data: p10Data,
            borderColor: corridorBorder,
            borderWidth: 1.5,
            borderDash: [5, 4],
            backgroundColor: corridorFill,
            pointRadius: 0,
            pointHoverRadius: 0,
            tension: 0.25,
            fill: '-1',
        });
    }

    // 3. Scenario lines
    const milestones = state.scenariosData.milestones || [];
    scenarios.forEach((scen, scenIdx) => {
        const isSelected = (scen.id === state.selectedScenarioId);
        const color = theme ? theme.normalizeScenarioColor(scen.color, scenIdx) : (scen.color || '#1D4ED8');
        const data = allPoints.map(p => p.is_historical ? null : p[scen.id]);

        const pointRadii = [];
        const pointHoverRadii = [];
        const pointBgColors = [];
        const pointBorderColors = [];
        const pointBorderWidths = [];

        const currentScenEvents = (state.scenariosData.events_catalog || []).filter(e => (scen.event_ids || []).includes(e.id));

        allPoints.forEach(p => {
            if (p.is_historical) {
                pointRadii.push(0);
                pointHoverRadii.push(0);
                pointBgColors.push(color);
                pointBorderColors.push(color);
                pointBorderWidths.push(0);
                return;
            }
            const yr = p.year;
            const hasMilestone = milestones.some(m => m.year === yr);
            const hasEventStart = currentScenEvents.some(e => (e.year || 2026) === yr);
            const hasEventRunning = currentScenEvents.some(e => {
                const s = e.year || 2026;
                const en = e.end_year || s;
                return yr >= s && yr <= en;
            });

            if (isSelected) {
                if (hasEventStart) {
                    pointRadii.push(7.5);
                    pointHoverRadii.push(11);
                    pointBgColors.push('#F59E0B');
                    pointBorderColors.push('#FFFFFF');
                    pointBorderWidths.push(2.5);
                } else if (hasMilestone) {
                    pointRadii.push(6.5);
                    pointHoverRadii.push(10);
                    pointBgColors.push('#FFFFFF');
                    pointBorderColors.push(color);
                    pointBorderWidths.push(2.5);
                } else if (hasEventRunning) {
                    pointRadii.push(4.5);
                    pointHoverRadii.push(7.5);
                    pointBgColors.push(color);
                    pointBorderColors.push('#FFFFFF');
                    pointBorderWidths.push(1.5);
                } else {
                    pointRadii.push(2.5);
                    pointHoverRadii.push(6);
                    pointBgColors.push(color);
                    pointBorderColors.push(color);
                    pointBorderWidths.push(1);
                }
            } else {
                pointRadii.push(1);
                pointHoverRadii.push(4);
                pointBgColors.push(color);
                pointBorderColors.push(color);
                pointBorderWidths.push(1);
            }
        });

        datasets.push({
            scenarioId: scen.id,
            label: scen.name,
            data: data,
            borderColor: color,
            backgroundColor: (theme ? theme.alpha(color, 0.08) : (color + '15')),
            borderWidth: isSelected ? 3.5 : 1.75,
            pointRadius: pointRadii,
            pointHoverRadius: pointHoverRadii,
            pointBackgroundColor: pointBgColors,
            pointBorderColor: pointBorderColors,
            pointBorderWidth: pointBorderWidths,
            tension: 0.3,
            fill: false,
        });
    });

    return datasets;
}

