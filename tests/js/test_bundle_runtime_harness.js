/**
 * tests/js/test_bundle_runtime_harness.js
 * Validates that compiled production bundles (static/vendor/bundle-*.min.js)
 * execute cleanly in a DOM environment without runtime syntax errors, ASI bleeding,
 * or module collisions.
 */

const { describe, it } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { createTestDomEnvironment } = require('../../vendor/hvl_common/testing/js/dom_harness.js');

describe('Production Asset Bundle Runtime Verification', () => {
    it('evaluates bundle-core.min.js and bundle-modules.min.js without throwing errors', () => {
        const domEnv = createTestDomEnvironment({
            html: '<!DOCTYPE html><html><head></head><body><div id="app"></div></body></html>',
            url: 'https://finances.highvelocitylabs.dev/',
        });
        const window = domEnv.window;

        // Stub minimal external runtime hooks for headless execution
        window.Chart = function () {};
        window.Chart.register = function () {};

        const corePath = path.join(__dirname, '../../static/vendor/bundle-core.min.js');
        const modulesPath = path.join(__dirname, '../../static/vendor/bundle-modules.min.js');

        assert.ok(fs.existsSync(corePath), 'bundle-core.min.js must exist on disk');
        assert.ok(fs.existsSync(modulesPath), 'bundle-modules.min.js must exist on disk');

        const coreSource = fs.readFileSync(corePath, 'utf8');
        const modulesSource = fs.readFileSync(modulesPath, 'utf8');

        // Evaluate bundles in window context
        assert.doesNotThrow(() => {
            vm.runInContext(coreSource, window);
        }, 'bundle-core.min.js should evaluate cleanly without syntax or runtime exceptions');

        assert.doesNotThrow(() => {
            vm.runInContext(modulesSource, window);
        }, 'bundle-modules.min.js should evaluate cleanly without syntax or runtime exceptions');

        // Assert core hydration & signal functions are registered
        assert.strictEqual(typeof window.registerSectionHydrator, 'function', 'registerSectionHydrator must be exposed');
        assert.strictEqual(typeof window.hydrateSection, 'function', 'hydrateSection must be exposed');
        assert.strictEqual(typeof window.updateSandboxCountdown, 'function', 'updateSandboxCountdown must be exposed');

        // Assert module features are registered
        assert.strictEqual(typeof window.toggleAiAdvisorDrawer, 'function', 'toggleAiAdvisorDrawer must be exposed');
        assert.strictEqual(typeof window.hydrateWidgetCharts, 'function', 'hydrateWidgetCharts must be exposed');
    });
});
