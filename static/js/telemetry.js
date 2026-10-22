/**
 * HVL Family Office - Zero-PII Client Interaction & Action Telemetry
 * Tracks user engagement, tab exploration depth, and modal interactions.
 */
(() => {
    'use strict';

    function getCurrentTab() {
        return window.currentActiveTab || window.INITIAL_ACTIVE_SECTION || 'overview';
    }

    window.trackTelemetryAction = function(action, meta = {}) {
        if (!action) return;
        try {
            const payload = JSON.stringify({
                action: String(action).slice(0, 50),
                tab: String(meta.tab || getCurrentTab()).replace('section-', '').slice(0, 50),
                modal: String(meta.modal || '').slice(0, 50),
                feature_key: String(meta.feature_key || action).slice(0, 50),
            });
            const url = typeof window.appendSessionQuery === 'function'
                ? window.appendSessionQuery('/api/telemetry/action')
                : '/api/telemetry/action';
            if (navigator.sendBeacon) {
                const blob = new Blob([payload], { type: 'application/json' });
                navigator.sendBeacon(url, blob);
            } else {
                fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: payload,
                    keepalive: true,
                }).catch(() => {});
            }
        } catch (e) {}
    };

    // Declarative and delegated click tracking for key feature interactions
    document.addEventListener('click', (e) => {
        const actionEl = e.target.closest('[data-telemetry-action]');
        if (actionEl) {
            const act = actionEl.getAttribute('data-telemetry-action');
            const mod = actionEl.getAttribute('data-telemetry-modal') || '';
            const feat = actionEl.getAttribute('data-telemetry-key') || act;
            window.trackTelemetryAction(act, { modal: mod, feature_key: feat });
            return;
        }

        // Auto-detect Monte Carlo and Scenario actions
        if (e.target.closest('#btn-run-simulation, .btn-run-simulation, [data-action="run-monte-carlo"]')) {
            window.trackTelemetryAction('run_monte_carlo', { tab: 'scenarios', feature_key: 'monte_carlo' });
        } else if (e.target.closest('.btn-add-scenario, #btn-add-scenario, [data-action="add-scenario"]')) {
            window.trackTelemetryAction('open_create_scenario', { tab: 'scenarios', modal: 'add_scenario' });
        } else if (e.target.closest('.btn-clone-scenario, [data-action="clone-scenario"]')) {
            window.trackTelemetryAction('clone_scenario', { tab: 'scenarios' });
        } else if (e.target.closest('#btn-download-vault, .btn-export-vault, [data-action="download-vault"]')) {
            window.trackTelemetryAction('download_vault', { tab: 'sandbox', modal: 'export_vault' });
        } else if (e.target.closest('#btn-extend-sandbox, [data-action="extend-sandbox"]')) {
            window.trackTelemetryAction('extend_sandbox', { tab: 'sandbox' });
        }
    }, { passive: true });
})();
