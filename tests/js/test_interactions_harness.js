const { describe, it, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { createTestDomEnvironment } = require('../../vendor/hvl_common/testing/js/dom_harness.js');

const bugModalRaw = fs.readFileSync(
    path.join(__dirname, '../../templates/components/bug_reporter_modal.html'),
    'utf8'
).replace(/\{\{\s*icon\([^)]*\)\s*\}\}/g, '<svg class="hvl-icon"></svg>');

describe('Client Interactions Test Harness (Level 4 JSDOM User Event Simulation)', () => {
    let dom;
    let window;
    let document;
    let htmxCalls;
    let morphCalls;

    function cleanupDom() {
        if (window) {
            if (window._escapeSettingsbound !== undefined) window._escapeSettingsbound = false;
        }
        if (dom && dom.window) {
            dom.window.close();
            dom = null;
            window = null;
            document = null;
        }
    }

    function loadScript(relPath) {
        const scriptCode = fs.readFileSync(path.join(__dirname, relPath), 'utf8');
        const scriptEl = document.createElement('script');
        scriptEl.textContent = scriptCode;
        document.body.appendChild(scriptEl);
    }

    function setupEnv(htmlContent) {
        cleanupDom();
        htmxCalls = [];
        morphCalls = [];

        const env = createTestDomEnvironment({
            html: htmlContent,
            url: 'https://finances.highvelocitylabs.dev/',
        });

        dom = env.dom;
        window = env.window;
        document = env.document;

        // Common HVL client mocks
        window.htmx = {
            ajax: async (method, url, opts) => {
                htmxCalls.push({ method, url, opts });
                return true;
            },
        };
        window.Idiomorph = { morph: () => {} };
        window.hvlShowToast = () => {};
        window.showModalAlert = async () => {};
        window.showConfirmModal = async () => true;
    }

    afterEach(() => {
        cleanupDom();
    });

    describe('1. Range Slider Dragging & Scrubbing (<input type="range">)', () => {
        it('Estate Charity Slider: scrubs value, updates linked text immediately, and triggers debounced morph', async () => {
            const html = `
            <!DOCTYPE html>
            <html>
            <body>
                <section id="section-estate">
                    <input type="range" id="range-charity-legacy" min="0" max="30" value="10">
                    <span id="val-charity-legacy">10%</span>
                    <select id="select-estate-state"><option value="WA">WA</option><option value="CA">CA</option></select>
                </section>
            </body>
            </html>
            `;
            setupEnv(html);
            loadScript('../../static/js/estate.js');
            document.dispatchEvent(new window.Event('DOMContentLoaded'));

            const slider = document.getElementById('range-charity-legacy');
            const label = document.getElementById('val-charity-legacy');
            assert.strictEqual(label.textContent, '10%');

            // Simulate user scrubbing range slider
            slider.value = '25';
            slider.dispatchEvent(new window.Event('input', { bubbles: true }));

            // Linked label must update immediately synchronously
            assert.strictEqual(label.textContent, '25%', 'Display label must update immediately upon slider scrubbing');

            // Wait for debounce timer (120ms) to trigger HTMX morph request
            await new Promise((resolve) => setTimeout(resolve, 150));
            assert.strictEqual(htmxCalls.length, 1, 'Debounced morph should execute after slider scrub settles');
            assert.ok(htmxCalls[0].url.includes('charitable_pct=0.25'));
        });

        it('Arbitrage Spend Slider: scrubbing clears preset pills and change event initiates morph', async () => {
            const html = `
            <!DOCTYPE html>
            <html>
            <body>
                <section id="section-arbitrage">
                    <button type="button" class="pill-btn btn-spend-preset active" data-spend="200000">$200k</button>
                    <button type="button" class="pill-btn btn-spend-preset" data-spend="300000">$300k</button>
                    <input type="range" id="input-annual-spend" min="100000" max="600000" value="200000">
                    <select id="select-residence-state"><option value="WA">WA</option><option value="CA">CA</option></select>
                </section>
            </body>
            </html>
            `;
            setupEnv(html);
            loadScript('../../static/js/arbitrage.js');

            const slider = document.getElementById('input-annual-spend');
            const preset200 = document.querySelector('.btn-spend-preset[data-spend="200000"]');
            assert.ok(preset200.classList.contains('active'));

            // Scrubbing slider deselects preset buttons
            slider.value = '350000';
            slider.dispatchEvent(new window.Event('input', { bubbles: true }));
            assert.ok(!preset200.classList.contains('active'), 'Active preset pill must clear when slider is dragged');

            // Releasing slider fires change event which triggers morph
            slider.dispatchEvent(new window.Event('change', { bubbles: true }));
            assert.strictEqual(htmxCalls.length, 1);
            assert.ok(htmxCalls[0].url.includes('annual_spend=350000'));
        });
    });

    describe('2. Subtab & Pill Button Click Switching', () => {
        it('Compensation Subtabs & Taxpayer Pills: clicking subtabs and adult pills toggles state & view', async () => {
            const html = `
            <!DOCTYPE html>
            <html>
            <body>
                <section id="section-compensation" data-active-taxpayer="all" data-active-subtab="comp-subtab-career">
                    <div class="pill-group">
                        <button type="button" class="pill-btn comp-subtab active" data-subtab="comp-subtab-career">Career</button>
                        <button type="button" class="pill-btn comp-subtab" data-subtab="comp-subtab-safeharbor">Safe Harbor</button>
                        <button type="button" class="pill-btn comp-subtab" data-subtab="comp-subtab-transcripts">Transcripts</button>
                    </div>
                    <div class="pill-group" id="comp-adult-pills">
                        <button type="button" class="pill-btn comp-adult-pill active" data-user-id="all">Combined</button>
                        <button type="button" class="pill-btn comp-adult-pill" data-user-id="2">User 2</button>
                    </div>
                    <div id="comp-subtab-career" class="comp-subtab-pane" style="display: block;">Career Content</div>
                    <div id="comp-subtab-safeharbor" class="comp-subtab-pane" style="display: none;">Safe Harbor Content</div>
                    <div id="comp-subtab-transcripts" class="comp-subtab-pane" style="display: none;">Transcripts Content</div>
                </section>
            </body>
            </html>
            `;
            setupEnv(html);
            window.renderCompensationChart = () => {};
            loadScript('../../static/js/compensation_modals.js');
            loadScript('../../static/js/compensation.js');
            window.initCompensationControls();

            const btnSafeHarbor = document.querySelector('.comp-subtab[data-subtab="comp-subtab-safeharbor"]');
            const btnCareer = document.querySelector('.comp-subtab[data-subtab="comp-subtab-career"]');
            const paneSafeHarbor = document.getElementById('comp-subtab-safeharbor');
            const paneCareer = document.getElementById('comp-subtab-career');
            const sec = document.getElementById('section-compensation');

            // Click Safe Harbor subtab
            btnSafeHarbor.click();

            assert.strictEqual(sec.dataset.activeSubtab, 'comp-subtab-safeharbor');
            assert.ok(!btnCareer.classList.contains('active'), 'Career tab button should become inactive');
            assert.ok(btnSafeHarbor.classList.contains('active'), 'Safe Harbor tab button should become active');
            assert.strictEqual(paneSafeHarbor.style.display, 'block');
            assert.strictEqual(paneCareer.style.display, 'none');

            // Click taxpayer pill button
            const pillUser2 = document.querySelector('.comp-adult-pill[data-user-id="2"]');
            pillUser2.click();

            assert.strictEqual(htmxCalls.length, 1);
            assert.ok(htmxCalls[0].url.includes('taxpayer=2'));
            assert.ok(htmxCalls[0].url.includes('subtab=comp-subtab-safeharbor'));
        });

        it('Settings Subtabs: clicking navigation buttons switches active classes and pane display', async () => {
            const html = `
            <!DOCTYPE html>
            <html>
            <body>
                <button id="btn-open-settings">Settings</button>
                <div id="settings-modal" style="display: none;">
                    <button type="button" id="btn-close-settings-modal" class="modal-close-btn">✕</button>
                    <div class="hvl-subnav-links">
                        <button type="button" id="tab-btn-members" data-tab="members" class="settings-tab-btn active">Members</button>
                        <button type="button" id="tab-btn-assumptions" data-tab="assumptions" class="settings-tab-btn">Assumptions</button>
                        <button type="button" id="tab-btn-roles" data-tab="roles" class="settings-tab-btn">Roles</button>
                        <button type="button" id="tab-btn-monarch" data-tab="monarch" class="settings-tab-btn">Monarch</button>
                        <button type="button" id="tab-btn-appearance" data-tab="appearance" class="settings-tab-btn">Appearance</button>
                        <button type="button" id="tab-btn-advisor-history" data-tab="advisor-history" class="settings-tab-btn">Advisor</button>
                    </div>
                    <div class="settings-modal-body">
                        <div id="settings-tab-members" class="settings-tab-content" style="display: block;">Members Pane</div>
                        <div id="settings-tab-assumptions" class="settings-tab-content" style="display: none;">Assumptions Pane</div>
                        <div id="settings-tab-roles" class="settings-tab-content" style="display: none;">Roles Pane</div>
                        <div id="settings-tab-monarch" class="settings-tab-content" style="display: none;">Monarch Pane</div>
                        <div id="settings-tab-appearance" class="settings-tab-content" style="display: none;">Appearance Pane</div>
                        <div id="settings-tab-advisor-history" class="settings-tab-content" style="display: none;">Advisor Pane</div>
                    </div>
                </div>
            </body>
            </html>
            `;
            setupEnv(html);
            window.loadSettingsAdvisorConversations = () => {};
            loadScript('../../static/js/settings.js');
            document.dispatchEvent(new window.Event('DOMContentLoaded'));
            window.openSettingsModal();

            const btnMembers = document.getElementById('tab-btn-members');
            const btnAssump = document.getElementById('tab-btn-assumptions');
            const contentMembers = document.getElementById('settings-tab-members');
            const contentAssump = document.getElementById('settings-tab-assumptions');

            assert.ok(btnMembers.classList.contains('active'));

            // Click Assumptions tab
            btnAssump.click();

            assert.ok(!btnMembers.classList.contains('active'), 'Members tab should lose active state');
            assert.ok(btnAssump.classList.contains('active'), 'Assumptions tab should gain active state');
            assert.strictEqual(contentMembers.style.display, 'none');
            assert.strictEqual(contentAssump.style.display, 'block');
        });
    });

    describe('3. Modal Dismissal via Keyboard (Escape) & Backdrop Click', () => {
        it('Bug Reporter Modal: opens via trigger, closes via Escape key and backdrop click', async () => {
            const html = `
            <!DOCTYPE html>
            <html>
            <body>
                <button type="button" class="btn-bug-report-trigger" data-pane="overview">Report Bug</button>
                ${bugModalRaw}
            </body>
            </html>
            `;
            setupEnv(html);
            loadScript('../../static/js/bug_reporter.js');
            document.dispatchEvent(new window.Event('DOMContentLoaded'));

            const modal = document.getElementById('bug-reporter-modal');
            const trigger = document.querySelector('.btn-bug-report-trigger');
            assert.strictEqual(modal.style.display, 'none');

            // 1. Open modal via trigger click
            trigger.click();
            assert.strictEqual(modal.style.display, 'flex', 'Modal must open on trigger button click');

            // 2. Dismiss via Escape key
            document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
            assert.strictEqual(modal.style.display, 'none', 'Modal must close on Escape key');

            // 3. Re-open and dismiss via backdrop click
            trigger.click();
            assert.strictEqual(modal.style.display, 'flex');

            modal.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
            assert.strictEqual(modal.style.display, 'none', 'Modal must close on direct backdrop click');
        });

        it('Settings Modal: closes cleanly on Escape key', async () => {
            const html = `
            <!DOCTYPE html>
            <html>
            <body>
                <button id="btn-open-settings">Settings</button>
                <div id="settings-modal" style="display: none;">
                    <button type="button" id="btn-close-settings-modal">✕</button>
                </div>
            </body>
            </html>
            `;
            setupEnv(html);
            loadScript('../../static/js/settings.js');
            document.dispatchEvent(new window.Event('DOMContentLoaded'));

            const modal = document.getElementById('settings-modal');
            window.openSettingsModal();
            assert.strictEqual(modal.style.display, 'flex');

            document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
            assert.strictEqual(modal.style.display, 'none', 'Settings modal must close on Escape key');
        });

        it('Sidebar Tooltips: suppressed when sidebar is expanded, shown only when collapsed', async () => {
            const html = `
            <!DOCTYPE html>
            <html>
            <body>
                <div class="app-wrapper">
                    <aside class="sidebar">
                        <ul class="nav-menu">
                            <li><a href="/" id="nav-overview" class="nav-link active" data-tooltip="Overview & Net Worth"><span>Overview & Net Worth</span></a></li>
                        </ul>
                    </aside>
                    <main class="main-content">
                        <div id="timeline-pin" data-tooltip="Timeline Milestone">Pin</div>
                    </main>
                </div>
            </body>
            </html>
            `;
            setupEnv(html);
            const appCode = fs.readFileSync(path.join(__dirname, '../../static/js/app.js'), 'utf8');
            const stateCode = fs.readFileSync(path.join(__dirname, '../../static/js/scenarios/state.js'), 'utf8')
                .replace(/import\s+[\s\S]*?from\s+['"][^'"]+['"];?/g, '')
                .replace(/^export\s+\{[\s\S]*?\};?/gm, '')
                .replace(/^export\s+/gm, '');
            const scriptEl = document.createElement('script');
            scriptEl.textContent = `(function() {\n${appCode}\n})();\n(function() {\n${stateCode}\ninitFastInstantTooltips();\n})();`;
            document.body.appendChild(scriptEl);
            document.dispatchEvent(new window.Event('DOMContentLoaded'));

            const navLink = document.getElementById('nav-overview');
            const pin = document.getElementById('timeline-pin');
            const sidebarTip = document.getElementById('sidebar-floating-tooltip');
            const fastTip = document.getElementById('fast-instant-tooltip');

            // 1. Expanded sidebar: hovering nav link must NOT show either tooltip
            navLink.dispatchEvent(new window.MouseEvent('mouseover', { bubbles: true }));
            assert.ok(!sidebarTip.classList.contains('visible'), 'Sidebar tooltip must stay hidden when expanded');
            assert.ok(!fastTip.classList.contains('visible'), 'Global fast tooltip must ignore sidebar items');

            // 2. Main content element still gets global fast tooltip
            pin.dispatchEvent(new window.MouseEvent('mouseover', { bubbles: true }));
            assert.ok(fastTip.classList.contains('visible'), 'Main content element should display fast tooltip');

            // 3. Collapsed sidebar: hovering nav link shows sidebar-floating-tooltip (not fast-instant-tooltip)
            document.querySelector('.app-wrapper').classList.add('sidebar-collapsed');
            navLink.dispatchEvent(new window.MouseEvent('mouseover', { bubbles: true }));
            assert.ok(sidebarTip.classList.contains('visible'), 'Sidebar tooltip must appear when collapsed');
            assert.ok(!fastTip.classList.contains('visible'), 'Global fast tooltip must remain hidden on sidebar');
        });

        it('Playbook Deep-Link Consumer: consumes ?lens, ?view, ?mc_mode, ?open_event, ?open_guardrails, ?compare, and ?ask_ai', async () => {
            const html = `
            <!DOCTYPE html>
            <html>
            <body>
                <div id="container-side-by-side-scorecard" style="display: none;"></div>
                <button id="btn-toggle-scorecard-table">▼ Compare Plans</button>
                <div id="current-plan-collapsible-body" style="display: none;"></div>
                <button id="btn-toggle-current-plan"><span id="txt-toggle-current-plan">▼ Plan Details</span></button>
                <div id="asset-growth-body" style="display: none;"></div>
                <button id="btn-toggle-asset-growth"><span id="txt-toggle-asset-growth">▼ Advanced Levers</span></button>
                <select id="scen-input-spending-guardrails"><option value="off">Off</option></select>
                <textarea id="ai-advisor-input"></textarea>
                <span id="advisor-char-counter">0 / 2000</span>
            </body>
            </html>
            `;
            cleanupDom();
            const env = createTestDomEnvironment({
                html,
                url: 'https://finances.highvelocitylabs.dev/scenarios?lens=montecarlo&mc_mode=historical&open_event=pre65_healthcare&open_guardrails=1&compare=1&ask_ai=Test%20AI%20Prompt',
            });
            dom = env.dom;
            window = env.window;
            document = env.document;

            const helperCode = fs.readFileSync(path.join(__dirname, '../../static/js/scenarios/main_helpers.js'), 'utf8')
                .replace(/import\s+[\s\S]*?from\s+['"][^'"]+['"];?/g, '')
                .replace(/^export\s+/gm, '');
            const scriptEl = document.createElement('script');
            scriptEl.textContent = `${helperCode}\nwindow.consumeScenarioDeepLinkParams = consumeScenarioDeepLinkParams;`;
            document.body.appendChild(scriptEl);

            let lensSwitched = null;
            let mcModeSet = null;
            let openedEventTpl = null;
            let aiDrawerOpened = false;
            window.toggleAiAdvisorDrawer = (open) => { aiDrawerOpened = open; };

            const handled = window.consumeScenarioDeepLinkParams({
                switchToLens: (l) => { lensSwitched = l; },
                setCfSubMode: () => {},
                setMcSubMode: (m) => { mcModeSet = m; },
                openCreateEventModal: (tpl) => { openedEventTpl = tpl; }
            });

            assert.strictEqual(handled, true);
            assert.strictEqual(lensSwitched, 'montecarlo');
            assert.strictEqual(mcModeSet, 'historical');
            assert.strictEqual(openedEventTpl, 'pre65_healthcare');
            assert.strictEqual(aiDrawerOpened, true);
            assert.strictEqual(document.getElementById('ai-advisor-input').value, 'Test AI Prompt');
            assert.strictEqual(document.getElementById('container-side-by-side-scorecard').style.display, 'block');
            assert.strictEqual(document.getElementById('current-plan-collapsible-body').style.display, 'block');
            assert.strictEqual(document.getElementById('asset-growth-body').style.display, 'block');
            assert.strictEqual(window.location.search, '', 'Deep-link query params should be stripped via history.replaceState after consumption');
        });
    });
});

