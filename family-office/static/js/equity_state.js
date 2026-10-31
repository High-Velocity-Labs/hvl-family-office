/**
 * Equity tab state module: the single owner of the 409A simulator, chart and company-selection state.
 * Chart mode is an explicit enum; an unknown mode throws instead of silently selecting no chart.
 */

(function () {
    const GRAPH_MODES = ['fmv', 'trajectory', 'curve'];

    const EquityState = {
        chart: null,
        renderSeq: 0,
        graphMode: 'fmv',
        simulatedPrice: 0,
        includeWaTax: false,
        grants: [],
        projections: [],
        fmvHistory: [],
        data: null,
        debounceTimer: null,
        companyId: null,
        portfolioMultiple: 1.0,
        companies: [],

        setGraphMode(mode) {
            if (!GRAPH_MODES.includes(mode)) throw new Error(`Unknown equity graph mode: ${mode}`);
            this.graphMode = mode;
            return mode;
        },
    };

    window.EquityState = EquityState;
})();
