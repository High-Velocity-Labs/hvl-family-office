/**
 * High Velocity Labs / HVL Family Office
 * Central Chart Theme & Palette Token Manager
 * 
 * Single source of truth for all Chart.js visualizations:
 * - Reads CSS custom properties from :root (--chart-*) with rock-solid Velvet Gemstone fallbacks.
 * - Provides semantic color palettes for Net Worth, Asset Allocation, Scenarios, Monte Carlo,
 *   Compensation, Equity Sensitivity, Longevity, and Philanthropy.
 * - Exposes alpha() helper for crisp, gradient-free corridors and shaded areas.
 * - Normalizes legacy database colors into Velvet Gemstone equivalents.
 */

(function (global) {
    'use strict';

    // Reads a theme.css token; an unset token stays unset (no fallback colors)
    function getCssVar(varName) {
        if (typeof document === 'undefined') return undefined;
        return getComputedStyle(document.documentElement).getPropertyValue(varName).trim() || undefined;
    }

    function hexToRgba(hex, alpha) {
        if (!hex) return hex;
        if (hex.startsWith('rgba') || hex.startsWith('rgb')) {
            // Already an rgb/rgba string, replace or inject opacity if needed
            return hex;
        }
        let clean = hex.replace('#', '').trim();
        if (clean.length === 3) {
            clean = clean.split('').map(c => c + c).join('');
        }
        if (clean.length === 6) {
            const num = parseInt(clean, 16);
            const r = (num >> 16) & 255;
            const g = (num >> 8) & 255;
            const b = num & 255;
            return `rgba(${r}, ${g}, ${b}, ${alpha})`;
        }
        return hex;
    }

    function createTheme() {
        // Base HVL Approved Financial Graph Swatches
        const sapphire = getCssVar('--chart-sapphire');
        const emerald = getCssVar('--chart-emerald');
        const cerulean = getCssVar('--chart-cerulean');
        const amber = getCssVar('--chart-amber');
        const tanzanite = getCssVar('--chart-tanzanite');
        const ruby = getCssVar('--chart-ruby');
        const slate = getCssVar('--chart-slate');
        const slateLight = getCssVar('--chart-slate-light');

        // Legacy Color Map (Maps historical/Tailwind database colors to HVL approved palette)
        const legacyColorMap = {
            '#3b82f6': sapphire,
            '#2563eb': sapphire,
            '#1d4ed8': sapphire,
            '#0265e8': sapphire,
            '#10b981': emerald,
            '#22c55e': emerald,
            '#059669': emerald,
            '#047857': emerald,
            '#06b6d4': cerulean,
            '#0ea5e9': cerulean,
            '#38bdf8': cerulean,
            '#0284c7': cerulean,
            '#f59e0b': amber,
            '#fb923c': amber,
            '#facc15': amber,
            '#d97706': amber,
            '#c06c26': amber,
            '#f97316': amber,
            '#8b5cf6': cerulean,
            '#7c3aed': cerulean,
            '#a855f7': tanzanite,
            '#14b8a6': tanzanite,
            '#0d9488': tanzanite,
            '#ec4899': tanzanite,
            '#f472b6': ruby,
            '#f43f5e': ruby,
            '#ef4444': ruby,
            '#dc2626': ruby,
            '#e11d48': emerald,
            '#c75d6e': ruby,
            '#64748b': slate,
            '#94a3b8': slateLight
        };

        const theme = {
            // Raw Swatches
            sapphire,
            emerald,
            cerulean,
            amber,
            tanzanite,
            ruby,
            slate,
            slateLight,

            // Helpers
            alpha: hexToRgba,

            // Normalizes legacy or arbitrary scenario colors into the cohesive palette
            normalizeScenarioColor: function (color, index = 0) {
                if (!color) {
                    return theme.scenarios[index % theme.scenarios.length];
                }
                const lower = color.toLowerCase().trim();
                if (legacyColorMap[lower]) {
                    return legacyColorMap[lower];
                }
                return color;
            },

            // Asset Allocation Doughnuts
            allocation: [
                emerald,    // US Equities & Company Equity
                cerulean,   // Intl Equities
                amber,      // Real Estate
                sapphire,   // Private VC / PE
                tanzanite,  // Bonds & Fixed Income
                slate,      // Cash & Sweeps
                ruby,       // Specialized Assets
                slateLight  // Personal Property & Vehicles
            ],

            allocationByKey: {
                company_equity: emerald,
                us_equity: emerald,
                intl_equity: cerulean,
                real_estate: amber,
                real_estate_reits: amber,
                bonds: tanzanite,
                private_investments: sapphire,
                cash_liquid: cerulean,
                vehicles: slateLight
            },

            // Net Worth Trajectory & Projections
            netWorth: {
                primary: emerald,
                primaryFill: hexToRgba(emerald, 0.15),
                equity: cerulean,
                equityFill: hexToRgba(cerulean, 0.08),
                liquid: sapphire,
                unvested: amber,
                taxDrag: ruby,
                historical: slate,
                historicalFill: hexToRgba(slate, 0.08),
                corridorBorder: hexToRgba(sapphire, 0.45),
                corridorFill: hexToRgba(sapphire, 0.12)
            },

            // Scenario Comparison Curves
            scenarios: [
                slate,      // Baseline
                sapphire,   // Scenario 1 (Primary alternate)
                emerald,    // Scenario 2
                amber,      // Scenario 3
                tanzanite,  // Scenario 4
                cerulean,   // Scenario 5
                ruby        // Scenario 6
            ],

            // Monte Carlo Percentile Ensembles
            monteCarlo: {
                p95: hexToRgba(cerulean, 0.45),
                p75: hexToRgba(cerulean, 0.75),
                p50: sapphire,
                p25: hexToRgba(amber, 0.85),
                p10: ruby
            },

            // Compensation Modules (Base, Bonus, Equity)
            compensation: {
                base: sapphire,
                bonus: amber,
                equity: emerald,
                unvested: tanzanite
            },

            // Equity Sensitivity Curves & Historical 409A
            equity: {
                gross: sapphire,
                grossFill: hexToRgba(sapphire, 0.08),
                net: emerald,
                netFill: hexToRgba(emerald, 0.15),
                unvested: amber,
                taxDrag: ruby,
                historicalFmv: emerald,
                historicalFmvFill: hexToRgba(emerald, 0.12),
                forwardProjection: tanzanite,
                forwardProjectionFill: hexToRgba(tanzanite, 0.08),
                modelGuideline: amber,
                pointHighlight: amber
            },

            // Philanthropy Stacked Giving & Doughnut
            philanthropy: {
                palette: [
                    sapphire,
                    emerald,
                    cerulean,
                    amber,
                    tanzanite,
                    ruby,
                    slate
                ],
                other: slate
            },

            // Cash Flow Lens
            cashFlow: {
                salary: emerald,
                socialSecurity: getCssVar('--chart-emerald-deep'),
                windfalls: hexToRgba(emerald, 0.75),
                living: sapphire,
                travel: amber,
                gifting: tanzanite,
                aviation: ruby,
                mortgage: cerulean,
                netFlow: getCssVar('--text-primary')
            },

            // Longevity Lens
            longevity: {
                sustainable: emerald,
                caution: amber,
                depleted: ruby,
                baseline: slate
            }
        };

        // Chart chrome: text, gridlines, surfaces and marks drawn over fills, all from theme.css tokens
        theme.text = getCssVar('--text-secondary');
        theme.grid = getCssVar('--border-color');
        theme.fontFamily = getCssVar('--font-sans');
        theme.surface = getCssVar('--bg-surface');
        theme.surfaceRaised = getCssVar('--bg-surface-elevated');
        theme.onFill = getCssVar('--chart-on-fill');
        theme.shadow = getCssVar('--chart-shadow');
        theme.teal = getCssVar('--color-emerald');
        theme.rose = getCssVar('--status-red');
        theme.brand = getCssVar('--brand-primary');
        theme.ochre = getCssVar('--accent-amber');

        // Legends: side legends drop below the chart on phones so labels are not cut off
        theme.legend = function (options) {
            const opts = options || {};
            const isSide = opts.position === 'right' || opts.position === 'left';
            const isNarrow = typeof window !== 'undefined' && window.innerWidth <= 640;
            const labels = Object.assign(
                { color: theme.text, font: { size: 12 }, padding: 10 },
                opts.labels
            );
            // Chart.js draws legend text in each item's fontColor, so custom label lists need it set too
            const customLabels = labels.generateLabels;
            if (customLabels) {
                labels.generateLabels = (chart) =>
                    customLabels(chart).map((item) => Object.assign({ fontColor: labels.color }, item));
            }
            return Object.assign({}, opts, {
                position: isSide && isNarrow ? 'bottom' : opts.position || 'top',
                labels: labels
            });
        };

        return theme;
    }

    // Every chart's ticks, legend text, gridlines and font come from Chart.js defaults set from the theme
    function applyChartDefaults(theme) {
        const Chart = global.Chart;
        if (!Chart || !Chart.defaults) return;
        Chart.defaults.color = theme.text;
        Chart.defaults.borderColor = theme.grid;
        Chart.defaults.font.family = theme.fontFamily;
    }

    // Initialize global singleton
    const CHART_THEME = createTheme();
    applyChartDefaults(CHART_THEME);

    // Re-bind when themes or dark mode toggles change
    CHART_THEME.refresh = function () {
        const fresh = createTheme();
        Object.assign(CHART_THEME, fresh);
        applyChartDefaults(CHART_THEME);
        return CHART_THEME;
    };

    if (typeof window !== 'undefined') {
        window.CHART_THEME = CHART_THEME;
        window.addEventListener('themechange', function () {
            CHART_THEME.refresh();
        });
    }

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = CHART_THEME;
    }
})(typeof window !== 'undefined' ? window : globalThis);
