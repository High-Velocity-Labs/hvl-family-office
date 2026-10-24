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

// Ensure node_modules from main repository is resolvable in worktrees
const parentNodeModules = path.join(__dirname, '../../../family-office/node_modules');
if (fs.existsSync(parentNodeModules) && (!process.env.NODE_PATH || !process.env.NODE_PATH.includes(parentNodeModules))) {
    process.env.NODE_PATH = (process.env.NODE_PATH ? process.env.NODE_PATH + ':' : '') + parentNodeModules;
    require('node:module').Module._initPaths();
}

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
        assert.strictEqual(typeof window.animateWidgetGridLayout, 'function', 'animateWidgetGridLayout must be exposed');
    });

    it('verifies widget width ViewTransition/FLIP animation, tall chart stage toggle, and collapsed event icon strip toggle', async () => {
        const html = `<!DOCTYPE html><html><head></head><body>
            <div id="scenarios-widgets-grid">
                <div id="scenario-lens-section" class="portal-card household-widget-card" data-widget-id="scen_chart_networth" data-default-wide="true" style="grid-column: 1 / -1;">
                    <button type="button" id="btn-chart-expand-size" class="btn btn-secondary btn-sm">⤢ Tall Chart</button>
                    <div id="scenarios-chart-stage" style="height: 460px;"><canvas id="chart-scenarios-comparison"></canvas></div>
                </div>
                <div id="scenario-scen_chart_cashflow-card" class="portal-card household-widget-card" data-widget-id="scen_chart_cashflow" data-default-wide="true" style="grid-column: 1 / -1;">
                    <button type="button" class="btn-toggle-chart-width" data-chart-id="scen_chart_cashflow">⇔ Half Width</button>
                    <div id="scenarios-cashflow-stage" style="height: 560px;"><canvas id="chart-scen_chart_cashflow"></canvas></div>
                </div>
            </div>
            <div id="selected-scenario-events-strip">
                <button type="button" id="btn-toggle-top-events" class="btn-toggle-scen-events-top" data-id="scen_1">
                    <span id="selected-scen-events-chevron" class="scen-evt-top-chevron">▶</span>
                    <span>SCENARIO EVENTS (1)</span>
                </button>
                <div id="selected-scen-events-collapsed-icons" class="scen-events-collapsed-icons">
                    <span class="event-icon-chip event-icon-chip-top badge badge-blue" data-tooltip="Sabbatical (2028)" title="Sabbatical (2028)"><svg></svg></span>
                </div>
                <div id="selected-scen-events-expanded" style="display: none;"><span>Sabbatical (2028)</span></div>
            </div>
            <table><tbody id="tbody-scenarios-scorecard">
                <tr class="scorecard-row" data-id="scen_1">
                    <td>
                        <button type="button" class="btn-toggle-scen-events" data-id="scen_1" data-scen-id="scen_1">
                            <span class="scen-evt-chevron" data-id="scen_1">▶</span>
                        </button>
                        <div class="scen-events-collapsed-icons" id="scen-events-icons-scen_1">
                            <span class="event-icon-chip badge badge-blue" data-id="scen_1" data-scen-id="scen_1" data-tooltip="Sabbatical (2028)"><svg></svg></span>
                        </div>
                        <div class="scen-events-expanded" id="scen-events-exp-scen_1" style="display: none;"></div>
                    </td>
                    <td>
                        <div class="scorecard-actions-grid">
                            <span class="badge badge-blue scorecard-action-item scorecard-viewing-badge" data-id="scen_1">Viewing</span>
                        </div>
                    </td>
                </tr>
            </tbody></table>
        </body></html>`;

        const domEnv = createTestDomEnvironment({
            html,
            url: 'https://finances.highvelocitylabs.dev/scenarios',
        });
        const window = domEnv.window;
        const document = window.document;
        window.Chart = function () { return { resize: () => {}, destroy: () => {}, update: () => {}, data: { datasets: [] }, config: { type: 'line' }, options: { interaction: {}, plugins: { tooltip: {} } } }; };
        window.Chart.register = function () {};

        const coreSource = fs.readFileSync(path.join(__dirname, '../../static/vendor/bundle-core.min.js'), 'utf8');
        const modulesSource = fs.readFileSync(path.join(__dirname, '../../static/vendor/bundle-modules.min.js'), 'utf8');
        vm.runInContext(coreSource, window);
        vm.runInContext(modulesSource, window);

        let vtCalled = false;
        let seenTransitionName = '';
        document.startViewTransition = (cb) => {
            vtCalled = true;
            const cfCard = document.getElementById('scenario-scen_chart_cashflow-card');
            seenTransitionName = cfCard.style.viewTransitionName;
            cb();
            return { finished: Promise.resolve() };
        };

        const widthBtn = document.querySelector('.btn-toggle-chart-width[data-chart-id="scen_chart_cashflow"]');
        const cfCard = document.getElementById('scenario-scen_chart_cashflow-card');
        widthBtn.click();

        assert.strictEqual(vtCalled, true, 'toggleChartWidth must invoke document.startViewTransition when supported');
        assert.strictEqual(seenTransitionName, 'widget-card-scen_chart_cashflow', 'Card must receive unique viewTransitionName');
        assert.strictEqual(cfCard.style.gridColumn, '', 'Toggling from default wide should switch card to half-width');
        assert.ok(cfCard.classList.contains('widget-half'), 'Card must gain widget-half class');

        // Load ES module cash_flow_sankey + cards + cards_scorecard + cards_reorder behavior in VM
        const stripExports = (src) => src
            .replace(/import\s+[\s\S]*?from\s+['"][^'"]+['"];?/g, '')
            .replace(/export\s+\{[\s\S]*?\}(\s+from\s+['"][^'"]+['"])?;?/g, '')
            .replace(/^export\s+/gm, '');

        let resizeCount = 0;
        window.state = {
            currentLens: 'networth',
            selectedScenarioId: 'scen_1',
            scenariosData: { active_scenario_id: 'scen_1', scenarios: [{ id: 'scen_1', name: 'Base', event_ids: ['e1'] }], events: [{ id: 'e1', name: 'Sabbatical' }] },
            scenarioComparisonChart: { resize: () => { resizeCount += 1; } },
        };
        window.getCfSubMode = () => 'bars';
        window.renderSankeySvg = () => {};
        window.renderActiveLensChart = () => {};
        window.escapeHtml = (s) => String(s || '');
        window.fmtCurrency = (v) => '$' + v;
        window.getScenarioColor = () => '#3B82F6';
        window.getEventCategoryMeta = () => ({ badgeClass: 'badge-blue', borderColor: '#3B82F6' });
        window.renderEventIcon = () => '<svg></svg>';
        window.syncSummaryInputDisplays = () => {};
        window.syncScenarioDependentControls = () => {};
        window.morphScenariosSection = async () => {};

        const sankeySrc = stripExports(fs.readFileSync(path.join(__dirname, '../../static/js/scenarios/charts/cash_flow_sankey.js'), 'utf8'));
        const cardsSrc = stripExports(fs.readFileSync(path.join(__dirname, '../../static/js/scenarios/cards.js'), 'utf8'));
        const scorecardSrc = stripExports(fs.readFileSync(path.join(__dirname, '../../static/js/scenarios/cards_scorecard.js'), 'utf8'));
        const reorderSrc = stripExports(fs.readFileSync(path.join(__dirname, '../../static/js/scenarios/cards_reorder.js'), 'utf8'));
        vm.runInContext(
            `(function(){\n${sankeySrc}\n})();\n`
            + `(function(){\n${reorderSrc}\nwindow.initScenarioDragAndDrop = initScenarioDragAndDrop;\nwindow.applyScenarioOrder = applyScenarioOrder;\nwindow.sendScenarioReorder = sendScenarioReorder;\nwindow.getCurrentScenarioOrder = getCurrentScenarioOrder;\n})();\n`
            + `(function(){\n${scorecardSrc}\nwindow.bindScorecardTable = bindScorecardTable;\nwindow.bindScheduleTable = bindScheduleTable;\nwindow.formatScenarioOverrides = formatScenarioOverrides;\n})();\n`
            + `(function(){\n${cardsSrc}\nwindow.bindSelectedScenarioStrips = bindSelectedScenarioStrips;\n})();`,
            window
        );

        const expandBtn = document.getElementById('btn-chart-expand-size');
        const nwStage = document.getElementById('scenarios-chart-stage');
        const nwCard = document.getElementById('scenario-lens-section');
        expandBtn.click();
        assert.strictEqual(nwStage.style.height, '680px', 'Tall Chart mode must resize #scenarios-chart-stage to 680px');
        assert.ok(nwStage.classList.contains('chart-stage-tall'), '#scenarios-chart-stage must have chart-stage-tall class');
        assert.ok(nwCard.classList.contains('widget-tall'), 'Parent card must have widget-tall class');
        assert.ok(resizeCount >= 1, 'Toggling Tall Chart must resize scenarioComparisonChart');

        expandBtn.click();
        assert.strictEqual(nwStage.style.height, '460px', 'Standard Height mode must restore #scenarios-chart-stage to 460px');
        assert.ok(!nwStage.classList.contains('chart-stage-tall'), 'chart-stage-tall class must be removed in Standard Height');

        // Verify collapsed event icon strip toggles on Current Plan and Scorecard
        window.bindSelectedScenarioStrips(window.state.scenariosData.scenarios[0], window.state.scenariosData);
        window.bindScorecardTable(document.getElementById('tbody-scenarios-scorecard'), window.state.scenariosData);

        const topToggle = document.getElementById('btn-toggle-top-events');
        const topCollapsedIcons = document.getElementById('selected-scen-events-collapsed-icons');
        const topExpanded = document.getElementById('selected-scen-events-expanded');
        topToggle.click();
        assert.strictEqual(topExpanded.style.display, 'flex', 'Expanding top events must show expanded container');
        assert.strictEqual(topCollapsedIcons.style.display, 'none', 'Expanding top events must hide collapsed icon strip');
        topToggle.click();
        assert.strictEqual(topExpanded.style.display, 'none', 'Collapsing top events must hide expanded container');
        assert.strictEqual(topCollapsedIcons.style.display, 'inline-flex', 'Collapsing top events must restore collapsed icon strip');

        const rowToggle = document.querySelector('.btn-toggle-scen-events[data-id="scen_1"]');
        const rowIcons = document.getElementById('scen-events-icons-scen_1');
        const rowExpanded = document.getElementById('scen-events-exp-scen_1');
        rowToggle.click();
        assert.strictEqual(rowExpanded.style.display, 'flex');
        assert.strictEqual(rowIcons.style.display, 'none');
        rowToggle.click();
        assert.strictEqual(rowExpanded.style.display, 'none');
        assert.strictEqual(rowIcons.style.display, 'inline-flex');
    });

    it('verifies ES module import/export graph and importmap completeness across static/js/scenarios', () => {
        const scenRoot = path.join(__dirname, '../../static/js/scenarios');
        const indexHtml = fs.readFileSync(path.join(__dirname, '../../templates/index.html'), 'utf8');

        function listJsFiles(dir) {
            const results = [];
            for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
                const full = path.join(dir, entry.name);
                if (entry.isDirectory()) results.push(...listJsFiles(full));
                else if (entry.isFile() && entry.name.endsWith('.js')) results.push(full);
            }
            return results;
        }

        const jsFiles = listJsFiles(scenRoot);
        assert.ok(jsFiles.length >= 35, 'Expected all decomposed scenarios ES module files');

        function stripJsComments(code) {
            return code.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
        }

        function collectExports(filePath, seen = new Set()) {
            if (seen.has(filePath)) return new Set();
            seen.add(filePath);
            const src = stripJsComments(fs.readFileSync(filePath, 'utf8'));
            const exported = new Set();

            for (const m of src.matchAll(/export\s+(?:async\s+)?function\s+([A-Za-z0-9_$]+)/g)) {
                exported.add(m[1]);
            }
            for (const m of src.matchAll(/export\s+(?:const|let|var|class)\s+([A-Za-z0-9_$]+)/g)) {
                exported.add(m[1]);
            }
            for (const m of src.matchAll(/export\s*\{([^}]+)\}(?:\s*from\s*['"]([^'"]+)['"])?/g)) {
                const names = m[1].split(',').map(s => s.trim()).filter(Boolean);
                for (const spec of names) {
                    const parts = spec.split(/\s+as\s+/);
                    exported.add((parts[1] || parts[0]).trim());
                }
            }
            for (const m of src.matchAll(/export\s*\*\s*from\s*['"]([^'"]+)['"]/g)) {
                const target = path.resolve(path.dirname(filePath), m[1]);
                for (const sym of collectExports(target, seen)) exported.add(sym);
            }
            return exported;
        }

        for (const filePath of jsFiles) {
            const relWebPath = '/static/js/scenarios/' + path.relative(scenRoot, filePath).split(path.sep).join('/');
            assert.ok(
                indexHtml.includes(`"${relWebPath}": "${relWebPath}?v={{ asset_v }}"`),
                `templates/index.html importmap is missing versioned entry for ${relWebPath}`
            );

            const src = stripJsComments(fs.readFileSync(filePath, 'utf8'));
            for (const m of src.matchAll(/import\s*\{([^}]+)\}\s*from\s*['"]([^'"]+)['"]/g)) {
                const importedSpecs = m[1].split(',').map(s => s.trim()).filter(Boolean);
                const specPath = m[2];
                const targetFile = path.resolve(path.dirname(filePath), specPath);
                assert.ok(
                    fs.existsSync(targetFile),
                    `${relWebPath} imports missing file ${specPath}`
                );
                const targetExports = collectExports(targetFile);
                for (const spec of importedSpecs) {
                    const origName = spec.split(/\s+as\s+/)[0].trim();
                    assert.ok(
                        targetExports.has(origName),
                        `${relWebPath} imports '${origName}' from '${specPath}', which does not export '${origName}'`
                    );
                }
            }
        }
    });

    it('verifies baseline overlays tray, merge toggle, and view plans filter dropdown', async () => {
        const html = `<!DOCTYPE html><html><head></head><body>
            <div id="baseline-overlays-tray" class="baseline-overlays-tray">
                <div id="baseline-overlays-chips">
                    <span class="badge">
                        <span>Layer 1</span>
                        <button type="button" class="btn-unmerge-baseline-layer" data-layer-id="scen_layer1">&times;</button>
                    </span>
                </div>
                <div class="add-overlay-dropdown-container">
                    <button type="button" id="btn-add-overlay-dropdown">+ Add Overlay &#9662;</button>
                    <div id="menu-add-overlay" style="display: none;">
                        <button type="button" class="btn-add-baseline-overlay-item" data-scen-id="scen_layer2">Layer 2</button>
                    </div>
                </div>
            </div>
            <button type="button" id="btn-toggle-baseline-layer" data-scen-id="scen_child1" data-is-layer="false">
                <span id="txt-toggle-baseline-layer">+ Merge to Baseline</span>
            </button>
            <div id="scenario-selector-pills">
                <button type="button" class="pill-btn active" data-scen-id="scen_baseline">Baseline</button>
                <button type="button" class="pill-btn" data-scen-id="scen_strat">Strategy</button>
                <button type="button" class="pill-btn scen-pill-layer" data-scen-id="scen_layer1" data-is-layer="true">Layer 1</button>
                <button type="button" class="pill-btn scen-pill-archived" data-scen-id="scen_arch1" data-is-archived="true">Archived</button>
            </div>
            <button type="button" id="btn-view-plans-dropdown">View Plans</button>
            <div id="menu-view-plans" style="display: none;">
                <input type="checkbox" id="chk-filter-strategy-plans" checked>
                <input type="checkbox" id="chk-filter-baseline-overlays" checked>
                <input type="checkbox" id="chk-filter-archived-plans">
            </div>
            <table><tbody id="tbody-scenarios-scorecard">
                <tr class="scorecard-row active" data-id="scen_baseline" data-is-baseline="true"><td>Baseline</td></tr>
                <tr class="scorecard-row" data-id="scen_strat">
                    <td>Strategy</td>
                    <td>
                        <button type="button" class="btn-toggle-overlay-scenario" data-scen-id="scen_strat">Overlay</button>
                    </td>
                </tr>
                <tr class="scorecard-row scorecard-row-layer" data-id="scen_layer1" data-is-layer="true"><td>Layer 1</td></tr>
                <tr class="scorecard-row scorecard-row-archived" data-id="scen_arch1" data-is-archived="true"><td>Archived</td></tr>
            </tbody></table>
        </body></html>`;

        const domEnv = createTestDomEnvironment({ html, url: 'https://finances.highvelocitylabs.dev/scenarios' });
        const window = domEnv.window;
        const document = window.document;

        const stripExports = (src) => src
            .replace(/import\s+[\s\S]*?from\s+['"][^'"]+['"];?/g, '')
            .replace(/export\s+\{[\s\S]*?\}(\s+from\s+['"][^'"]+['"])?;?/g, '')
            .replace(/^export\s+/gm, '');

        window.state = { selectedScenarioId: 'scen_baseline' };
        window.morphScenariosSection = async () => {};
        let toggledLayerId = null;
        window.fetch = async (url) => {
            const m = url.match(/\/api\/scenarios\/([^/]+)\/toggle_baseline_layer/);
            if (m) {
                toggledLayerId = m[1];
                return { ok: true, json: async () => ({ success: true, active_baseline_layers: [m[1]] }) };
            }
            return { ok: false, json: async () => ({ error: 'not found' }) };
        };

        const overlaysSrc = stripExports(fs.readFileSync(path.join(__dirname, '../../static/js/scenarios/cards_overlays.js'), 'utf8'));
        vm.runInContext(`(function(){\n${overlaysSrc}\nwindow.initCardsOverlays = initCardsOverlays;\nwindow.applyPlanFilters = applyPlanFilters;\nwindow.toggleBaselineLayer = toggleBaselineLayer;\nwindow.getFilterSettings = getFilterSettings;\nwindow.setFilterSetting = setFilterSetting;\nwindow.bindViewPlansDropdown = bindViewPlansDropdown;\nwindow.bindBaselineLayerToggles = bindBaselineLayerToggles;\nwindow.bindAddOverlayDropdown = bindAddOverlayDropdown;\n})();`, window);

        window.initCardsOverlays();

        const rowLayer = document.querySelector('.scorecard-row-layer');
        const rowStrat = document.querySelector('tr[data-id="scen_strat"]');
        const rowArch = document.querySelector('.scorecard-row-archived');
        const pillLayer = document.querySelector('.scen-pill-layer');
        const pillArch = document.querySelector('.scen-pill-archived');

        assert.strictEqual(rowLayer.style.display, '', 'Merged overlay row in table must be visible when baseline overlays filter is enabled');
        assert.strictEqual(rowStrat.style.display, '', 'Strategy plan row in table must be visible');
        assert.strictEqual(rowArch.style.display, 'none', 'Archived plan row in table must be hidden by default');
        assert.strictEqual(pillLayer.style.display, 'inline-flex', 'Overlay pill must be visible by default');
        assert.strictEqual(pillArch.style.display, 'none', 'Archived pill must be hidden by default');

        const chkOverlays = document.getElementById('chk-filter-baseline-overlays');
        chkOverlays.checked = false;
        chkOverlays.dispatchEvent(new window.Event('change'));
        assert.strictEqual(pillLayer.style.display, 'none', 'Unchecking baseline overlays must hide overlay pill');
        assert.strictEqual(rowLayer.style.display, 'none', 'Unchecking baseline overlays must hide overlay table row');

        chkOverlays.checked = true;
        chkOverlays.dispatchEvent(new window.Event('change'));
        assert.strictEqual(pillLayer.style.display, 'inline-flex', 'Checking baseline overlays must restore overlay pill');
        assert.strictEqual(rowLayer.style.display, '', 'Checking baseline overlays must restore overlay table row');

        const btnDropdown = document.getElementById('btn-view-plans-dropdown');
        const menuDropdown = document.getElementById('menu-view-plans');
        assert.strictEqual(menuDropdown.style.display, 'none');
        btnDropdown.click();
        assert.strictEqual(menuDropdown.style.display, 'block');
        btnDropdown.click();
        assert.strictEqual(menuDropdown.style.display, 'none');

        const btnAddDropdown = document.getElementById('btn-add-overlay-dropdown');
        const menuAdd = document.getElementById('menu-add-overlay');
        assert.strictEqual(menuAdd.style.display, 'none');
        btnAddDropdown.click();
        assert.strictEqual(menuAdd.style.display, 'block');

        const addItem = document.querySelector('.btn-add-baseline-overlay-item');
        addItem.click();
        assert.strictEqual(toggledLayerId, 'scen_layer2', 'Clicking add overlay item must call toggleBaselineLayer');
        assert.strictEqual(menuAdd.style.display, 'none', 'Clicking add overlay item must close dropdown menu');

        const tableOverlayBtn = document.querySelector('.btn-toggle-overlay-scenario');
        tableOverlayBtn.click();
        assert.strictEqual(toggledLayerId, 'scen_strat', 'Clicking table overlay button must call toggleBaselineLayer');

        const unmergeBtn = document.querySelector('.btn-unmerge-baseline-layer');
        unmergeBtn.click();
        assert.strictEqual(toggledLayerId, 'scen_layer1', 'Clicking unmerge chip must call toggleBaselineLayer');
    });
});
