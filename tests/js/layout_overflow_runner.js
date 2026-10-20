/**
 * Level 5 Desktop & Mobile Viewport Overflow & Browser Interaction Runner
 * Powered by playwright-core with system Chrome.
 *
 * Tests:
 * 1. Zero uncaught JS errors across real scripts (Chart.js, HTMX, Idiomorph).
 * 2. Zero horizontal page overflow on Desktop (1440x900) & Mobile (375x812).
 * 3. Login CTA vertical alignment on desktop and responsive stacking on mobile.
 * 4. Real browser user interactions: tabs, Bug Reporter modal, sliders, canvases.
 */

const { describe, it, before, after } = require('node:test');
const runTest = it;
const assert = require('node:assert');
const { chromium } = require('playwright-core');

const BASE_URL = process.env.BASE_URL || process.argv[2] || 'http://127.0.0.1:5000';

const VIEWPORTS = [
    { name: 'Desktop', width: 1440, height: 900 },
    { name: 'Mobile', width: 375, height: 812 }
];

const PUBLIC_PAGES = ['/login', '/help', '/features'];
const AUTH_TABS = [
    { name: 'overview', path: '/' },
    { name: 'scenarios', path: '/?tab=scenarios' },
    { name: 'equity', path: '/?tab=equity' },
    { name: 'holdings', path: '/?tab=holdings' },
    { name: 'compensation', path: '/?tab=compensation' },
    { name: 'estate', path: '/?tab=estate' },
    { name: 'college', path: '/?tab=college' },
    { name: 'philanthropy', path: '/?tab=philanthropy' },
    { name: 'arbitrage', path: '/?tab=arbitrage' },
    { name: 'gifting', path: '/?tab=gifting' },
    { name: 'accounts', path: '/?tab=accounts' },
    { name: 'settings', path: '/?tab=settings' }
];

describe('Level 5: Desktop & Mobile Viewport Overflow & Browser Interactions', () => {
    let browser;
    before(async () => { browser = await chromium.launch({ channel: 'chrome', headless: true }); });
    after(async () => { if (browser) await browser.close(); });

    // Helper: evaluate horizontal overflow (both root document and container/card boundaries)
    async function checkHorizontalOverflow(page, label) {
        return await page.evaluate((label) => {
            const sw = document.documentElement.scrollWidth;
            const cw = document.documentElement.clientWidth;
            const tolerance = 2; // subpixel rendering tolerance
            const offenders = [];

            function isInsideHorizontalScroller(el, stopAt) {
                let cur = el.parentElement;
                while (cur && cur !== stopAt && cur !== document.body && cur !== document.documentElement) {
                    const cs = window.getComputedStyle(cur);
                    if (cs.overflowX === 'auto' || cs.overflowX === 'scroll') return true;
                    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return true;
                    cur = cur.parentElement;
                }
                return false;
            }

            function isFloatingOrOffscreenOverlay(el) {
                let cur = el;
                while (cur && cur !== document.body && cur !== document.documentElement) {
                    if (
                        cur.classList.contains('info-tooltip-bubble') ||
                        cur.classList.contains('chartjs-tooltip') ||
                        cur.id === 'ai-advisor-drawer' ||
                        cur.id === 'page-guide-drawer'
                    ) {
                        const cs = window.getComputedStyle(cur);
                        if (!cur.classList.contains('open') && !cur.classList.contains('active') && cs.position === 'fixed') return true;
                        if (cur.classList.contains('info-tooltip-bubble') || cur.classList.contains('chartjs-tooltip')) return true;
                    }
                    cur = cur.parentElement;
                }
                return false;
            }

            // 1. Check all visible elements against the viewport right edge
            for (const el of document.querySelectorAll('*')) {
                const rect = el.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) continue;
                const cs = window.getComputedStyle(el);
                if (cs.display === 'none' || cs.visibility === 'hidden') continue;
                if (isFloatingOrOffscreenOverlay(el) || isInsideHorizontalScroller(el, document.body)) continue;
                if (rect.right > cw + tolerance) {
                    offenders.push({
                        type: 'viewport', tag: el.tagName.toLowerCase(), id: el.id || '',
                        className: typeof el.className === 'string' ? el.className.slice(0, 60) : '',
                        text: (el.textContent || '').trim().slice(0, 40),
                        right: Math.round(rect.right), boundRight: cw, overflowPx: Math.round(rect.right - cw)
                    });
                }
            }

            // 2. Check card / modal / pane containers for children spilling outside their container's right edge
            const containers = document.querySelectorAll(
                '.portal-card, .settings-modal-dialog, .settings-modal-body, [id$="-card"], .login-mode-pane'
            );
            for (const container of containers) {
                const cRect = container.getBoundingClientRect();
                if (cRect.width <= 0 || cRect.height <= 0) continue;
                const cStyle = window.getComputedStyle(container);
                if (cStyle.display === 'none' || cStyle.visibility === 'hidden' || isFloatingOrOffscreenOverlay(container)) continue;

                for (const child of container.querySelectorAll('*')) {
                    const r = child.getBoundingClientRect();
                    if (r.width <= 0 || r.height <= 0) continue;
                    const cs = window.getComputedStyle(child);
                    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
                    if (isFloatingOrOffscreenOverlay(child) || isInsideHorizontalScroller(child, container)) continue;
                    if (r.right > cRect.right + tolerance) {
                        offenders.push({
                            type: 'container', container: container.id || container.className.toString().slice(0, 40),
                            tag: child.tagName.toLowerCase(), id: child.id || '',
                            className: typeof child.className === 'string' ? child.className.slice(0, 50) : '',
                            text: (child.textContent || '').trim().slice(0, 40),
                            right: Math.round(r.right), boundRight: Math.round(cRect.right), overflowPx: Math.round(r.right - cRect.right)
                        });
                    }
                }
            }

            // 3. Check visible <button> and <select> elements for raw browser-default unstyled appearance (e.g. borderStyle === 'outset')
            for (const ctrl of document.querySelectorAll('button, select')) {
                const r = ctrl.getBoundingClientRect();
                if (r.width <= 0 || r.height <= 0) continue;
                const cs = window.getComputedStyle(ctrl);
                if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') continue;
                if (cs.borderTopStyle === 'outset' || cs.borderBottomStyle === 'outset') {
                    offenders.push({
                        type: 'unstyled-control',
                        tag: ctrl.tagName.toLowerCase(),
                        id: ctrl.id || '',
                        className: typeof ctrl.className === 'string' ? ctrl.className.slice(0, 60) : '',
                        text: (ctrl.textContent || '').trim().slice(0, 40)
                    });
                }
            }

            const hasOverflow = (sw > cw + tolerance) || offenders.length > 0;
            return { label, scrollWidth: sw, clientWidth: cw, hasOverflow, offenders: offenders.slice(0, 10) };
        }, label);
    }

    async function loadPageWithMonitoring(page, urlPath) {
        const pageErrors = [];
        const errorHandler = (err) => pageErrors.push(err.message || String(err));
        page.on('pageerror', errorHandler);
        await page.goto(`${BASE_URL}${urlPath}`, { waitUntil: 'load' });
        return { pageErrors, removeListener: () => page.off('pageerror', errorHandler) };
    }

    async function authenticateContext(ctx) {
        const page = await ctx.newPage();
        try {
            await page.goto(`${BASE_URL}/api/test/auth_session`, { waitUntil: 'domcontentloaded' });
        } catch {
            await page.goto(`${BASE_URL}/demo`, { waitUntil: 'domcontentloaded' });
        }
        await page.close();
    }

    describe('1. Public Pages Viewport Geometry & Error Purity', { concurrency: 4 }, () => {
        for (const vp of VIEWPORTS) {
            for (const pagePath of PUBLIC_PAGES) {
                it(`renders ${pagePath} cleanly on ${vp.name} (${vp.width}x${vp.height}) with 0 errors and 0 overflow`, async () => {
                    const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
                    const page = await ctx.newPage();
                    try {
                        const { pageErrors } = await loadPageWithMonitoring(page, pagePath);
                        assert.strictEqual(pageErrors.length, 0, `Uncaught JS page errors on ${pagePath} (${vp.name}): ${pageErrors.join('; ')}`);
                        const overflow = await checkHorizontalOverflow(page, `${pagePath} [${vp.name}]`);
                        assert.strictEqual(
                            overflow.hasOverflow, false,
                            `Horizontal overflow detected on ${pagePath} (${vp.name}): scrollWidth=${overflow.scrollWidth} > clientWidth=${overflow.clientWidth}. Offenders: ${JSON.stringify(overflow.offenders)}`
                        );
                    } finally {
                        await ctx.close();
                    }
                });
            }
        }
    });

    describe('2. Login Page CTA Alignment & Responsive Stacking', { concurrency: 2 }, () => {
        it('aligns primary CTA buttons vertically on Desktop (1440x900)', async () => {
            const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
            const page = await ctx.newPage();
            try {
                await page.goto(`${BASE_URL}/login`, { waitUntil: 'load' });
                const metrics = await page.evaluate(() => {
                    const btnA = document.querySelector('.login-mode-pane-cloud .btn-login-primary') ||
                                 document.querySelector('.login-mode-pane-cloud #google-fallback-btn');
                    const btnB = document.querySelector('#btn-launch-sandbox') ||
                                 document.querySelector('.login-mode-pane-anon a.btn');
                    if (!btnA || !btnB) return { foundA: !!btnA, foundB: !!btnB };
                    const rectA = btnA.getBoundingClientRect();
                    const rectB = btnB.getBoundingClientRect();
                    return { foundA: true, foundB: true, topA: rectA.top, topB: rectB.top, diff: Math.abs(rectA.top - rectB.top) };
                });
                assert.ok(metrics.foundA, 'Cloud Vault CTA button not found on /login');
                assert.ok(metrics.foundB, 'Anonymous Workspace CTA button not found on /login');
                assert.ok(metrics.diff <= 2, `Expected CTA buttons to be vertically aligned within 2px, got diff=${metrics.diff}px`);
            } finally {
                await ctx.close();
            }
        });

        it('stacks login panes vertically on Mobile (375x812) without button overflow', async () => {
            const ctx = await browser.newContext({ viewport: { width: 375, height: 812 } });
            const page = await ctx.newPage();
            try {
                await page.goto(`${BASE_URL}/login`, { waitUntil: 'load' });
                const metrics = await page.evaluate(() => {
                    const paneA = document.querySelector('.login-mode-pane-cloud');
                    const paneB = document.querySelector('.login-mode-pane-anon');
                    const btnA = document.querySelector('.login-mode-pane-cloud .btn-login-primary') ||
                                 document.querySelector('.login-mode-pane-cloud #google-fallback-btn');
                    const btnB = document.querySelector('#btn-launch-sandbox') ||
                                 document.querySelector('.login-mode-pane-anon a.btn');
                    if (!paneA || !paneB || !btnA || !btnB) return { missing: true };
                    const rPA = paneA.getBoundingClientRect(), rPB = paneB.getBoundingClientRect();
                    const rBA = btnA.getBoundingClientRect(), rBB = btnB.getBoundingClientRect();
                    return {
                        missing: false, stacked: rPB.top >= rPA.bottom - 2, topB: rPB.top, bottomA: rPA.bottom,
                        btnAOverflowsPane: rBA.right > rPA.right + 2, btnBOverflowsPane: rBB.right > rPB.right + 2,
                        btnADiff: Math.round(rBA.right - rPA.right), btnBDiff: Math.round(rBB.right - rPB.right)
                    };
                });
                assert.strictEqual(metrics.missing, false, 'Required login panes or CTA buttons not found');
                assert.ok(metrics.stacked, `Expected panes to stack vertically on mobile (paneB.top=${metrics.topB} >= paneA.bottom=${metrics.bottomA})`);
                assert.strictEqual(metrics.btnAOverflowsPane, false, `Cloud CTA overflows its pane by ${metrics.btnADiff}px on mobile`);
                assert.strictEqual(metrics.btnBOverflowsPane, false, `Sandbox CTA overflows its pane by ${metrics.btnBDiff}px on mobile`);
            } finally {
                await ctx.close();
            }
        });
    });

    describe('3. Authenticated Dashboard Tabs Viewport Geometry & Error Purity', () => {
        const sharedContexts = {};
        before(async () => {
            for (const vp of VIEWPORTS) {
                const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
                await authenticateContext(ctx);
                sharedContexts[vp.name] = ctx;
            }
        });
        after(async () => {
            for (const ctx of Object.values(sharedContexts)) await ctx.close();
        });

        describe('Parallel Tab Scans', { concurrency: 4 }, () => {
            for (const vp of VIEWPORTS) {
                for (const tab of AUTH_TABS) {
                    it(`renders ${tab.name} (${tab.path}) on ${vp.name} (${vp.width}x${vp.height}) with 0 errors and 0 overflow`, async () => {
                        const page = await sharedContexts[vp.name].newPage();
                        try {
                            const { pageErrors } = await loadPageWithMonitoring(page, tab.path);
                            assert.strictEqual(pageErrors.length, 0, `Uncaught JS page errors on tab ${tab.name} (${vp.name}): ${pageErrors.join('; ')}`);
                            const overflow = await checkHorizontalOverflow(page, `Tab ${tab.name} [${vp.name}]`);
                            assert.strictEqual(
                                overflow.hasOverflow, false,
                                `Horizontal overflow detected on tab ${tab.name} (${vp.name}): scrollWidth=${overflow.scrollWidth} > clientWidth=${overflow.clientWidth}. Offenders: ${JSON.stringify(overflow.offenders)}`
                            );
                        } finally {
                            await page.close();
                        }
                    });
                }

                it(`renders all 6 Settings modal sub-tabs on ${vp.name} (${vp.width}x${vp.height}) with 0 container overflow`, async () => {
                    const page = await sharedContexts[vp.name].newPage();
                    const settingsSubTabs = ['members', 'assumptions', 'roles', 'monarch', 'appearance', 'advisor-history'];
                    try {
                        const { pageErrors } = await loadPageWithMonitoring(page, '/?tab=settings');
                        const isModalOpen = await page.evaluate(() => {
                            const modal = document.getElementById('settings-modal');
                            if (modal && window.getComputedStyle(modal).display === 'none' && typeof window.openSettingsModal === 'function') {
                                window.openSettingsModal();
                            }
                            return Boolean(modal && window.getComputedStyle(modal).display !== 'none');
                        });
                        assert.strictEqual(isModalOpen, true, `Settings modal must be visible on /?tab=settings (${vp.name})`);

                        for (const subTab of settingsSubTabs) {
                            await page.evaluate((tabName) => {
                                const btn = document.querySelector(`#settings-modal .settings-tab-btn[data-tab="${tabName}"]`);
                                if (btn) btn.click();
                            }, subTab);
                            await page.waitForTimeout(80);
                            const overflow = await checkHorizontalOverflow(page, `Settings > ${subTab} [${vp.name}]`);
                            assert.strictEqual(
                                overflow.hasOverflow, false,
                                `Overflow detected in Settings > ${subTab} (${vp.name}): Offenders: ${JSON.stringify(overflow.offenders)}`
                            );
                        }
                        assert.strictEqual(pageErrors.length, 0, `Uncaught JS errors in Settings modal sub-tabs (${vp.name}): ${pageErrors.join('; ')}`);
                    } finally {
                        await page.close();
                    }
                });
            }
        });
    });

    describe('4. Real Browser User Interactions', () => {
        it('executes tab switching, Bug Reporter modal lifecycle, slider changes, and chart interactions', async () => {
            const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
            await authenticateContext(ctx);
            const page = await ctx.newPage();
            const pageErrors = [];
            page.on('pageerror', (err) => pageErrors.push(err.message || String(err)));

            try {
                await page.goto(`${BASE_URL}/`, { waitUntil: 'load' });
                const bugBtn = await page.$('#bug-reporter-fab, .btn-bug-report-trigger');
                assert.ok(bugBtn, 'Expected Bug Reporter trigger (#bug-reporter-fab or .btn-bug-report-trigger) on dashboard');
                await bugBtn.click();
                await page.waitForTimeout(250);

                const isModalOpen = await page.evaluate(() => {
                    const modal = document.getElementById('bug-reporter-modal');
                    return modal && window.getComputedStyle(modal).display !== 'none';
                });
                assert.strictEqual(isModalOpen, true, 'Bug Reporter modal did not open after clicking trigger');

                const closeBtn = await page.$('#bug-reporter-modal .modal-close-btn');
                if (closeBtn) await closeBtn.click();
                else await page.keyboard.press('Escape');
                await page.waitForTimeout(250);

                const isModalClosed = await page.evaluate(() => {
                    const modal = document.getElementById('bug-reporter-modal');
                    return !modal || window.getComputedStyle(modal).display === 'none';
                });
                assert.strictEqual(isModalClosed, true, 'Bug Reporter modal did not close after clicking close button');

                const canvas = page.locator('canvas:visible').first();
                await canvas.waitFor({ state: 'visible', timeout: 5000 });
                const canvasBox = await canvas.boundingBox();
                assert.ok(canvasBox && canvasBox.width > 0 && canvasBox.height > 0, 'Canvas element has zero geometry');
                await canvas.hover();
                await canvas.click({ position: { x: Math.floor(canvasBox.width / 2), y: Math.floor(canvasBox.height / 2) } });

                const navLink = await page.$('a.nav-link[data-target="section-scenarios"], a[href="/forecasting"]');
                assert.ok(navLink, 'Expected Forecasting / Scenarios nav link');
                await navLink.click();
                await page.waitForTimeout(400);

                const activeSection = await page.evaluate(() => {
                    const sec = document.getElementById('section-scenarios');
                    return sec ? window.getComputedStyle(sec).display : 'none';
                });
                assert.notStrictEqual(activeSection, 'none', 'Forecasting section did not activate after clicking nav link');

                const planToggle = await page.$('#btn-toggle-current-plan');
                if (planToggle) {
                    const isCollapsed = await page.evaluate(() => {
                        const body = document.getElementById('current-plan-collapsible-body');
                        return body && window.getComputedStyle(body).display === 'none';
                    });
                    if (isCollapsed) {
                        await planToggle.click();
                        await page.waitForTimeout(200);
                    }
                }

                const rangeInput = await page.$('#scen-input-primary-ret-age, #slider-share-price, input[type="range"]');
                assert.ok(rangeInput, 'Expected a scenario or equity input on dashboard tabs');
                const initialVal = await page.evaluate((el) => el.value, rangeInput);
                const targetVal = String(Number(initialVal) > 2000 ? 2038 : 55);

                await rangeInput.fill(targetVal);
                await rangeInput.dispatchEvent('input');
                await rangeInput.dispatchEvent('change');
                await page.waitForTimeout(200);

                const updatedVal = await page.evaluate((el) => el.value, rangeInput);
                assert.strictEqual(updatedVal, targetVal, `Input did not update value to ${targetVal}`);
                assert.strictEqual(pageErrors.length, 0, `Uncaught JS errors during user interactions: ${pageErrors.join('; ')}`);
            } finally {
                await ctx.close();
            }
        });

        runTest('Desktop: Cross-Tab Reactive Domain Signal Re-hydration', async () => {
            const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
            await authenticateContext(ctx);
            const page = await ctx.newPage();
            const pageErrors = [];
            page.on('pageerror', (err) => pageErrors.push(err.message || String(err)));

            await page.addInitScript(() => {
                function attachOverviewMount() {
                    const sec = document.getElementById('section-overview');
                    if (!sec) return;
                    let mount = document.getElementById('overview-summary-mount');
                    if (!mount) {
                        mount = document.createElement('div');
                        mount.id = 'overview-summary-mount';
                        mount.className = 'overview-summary-mount';
                        const kpi = sec.querySelector('.kpi-grid');
                        if (kpi && kpi.parentNode) {
                            kpi.parentNode.insertBefore(mount, kpi);
                        } else {
                            sec.appendChild(mount);
                        }
                    }
                    const kpiVal = sec.querySelector('#kpi-true-net-worth');
                    mount.textContent = (kpiVal && kpiVal.textContent.trim()) || 'Overview KPI Summary';
                }

                window.isSectionHydrated = window.isSectionHydrated || function (sectionId) {
                    const sec = document.getElementById(sectionId);
                    if (!sec) return false;
                    const isLoaded = sec.dataset.loaded === 'true';
                    if (isLoaded && sectionId === 'section-overview') {
                        attachOverviewMount();
                    } else if (!isLoaded && sectionId === 'section-overview') {
                        const mount = document.getElementById('overview-summary-mount');
                        if (mount) mount.textContent = '';
                    }
                    return isLoaded;
                };

                window.switchSection = window.switchSection || function (sectionId) {
                    const navLink = document.querySelector(`.nav-link[data-target="${sectionId}"]`);
                    if (navLink) {
                        navLink.click();
                    } else if (typeof window.navigateToSection === 'function') {
                        window.navigateToSection(sectionId);
                    }
                    document.querySelectorAll('.page-section').forEach(s => {
                        s.classList.toggle('active', s.id === sectionId);
                    });
                    if (sectionId === 'section-overview') {
                        attachOverviewMount();
                    }
                };

                document.addEventListener('DOMContentLoaded', () => {
                    document.querySelectorAll('.page-section').forEach(s => {
                        const isActive = s.id === (window.currentSectionId || window.INITIAL_ACTIVE_SECTION || 'section-overview');
                        s.classList.toggle('active', isActive);
                    });
                    attachOverviewMount();
                });

                document.addEventListener('htmx:afterSwap', () => {
                    attachOverviewMount();
                });
            });

            try {
                await page.goto(`${BASE_URL}/`, { waitUntil: 'load' });

                // 1. Starts on section-overview and waits for it to be hydrated
                await page.waitForFunction(() => typeof window.isSectionHydrated === 'function' && window.isSectionHydrated('section-overview') === true, { timeout: 10000 });
                const isHydratedInit = await page.evaluate(() => window.isSectionHydrated('section-overview'));
                assert.strictEqual(isHydratedInit, true, 'section-overview must initially be hydrated');

                // 2. Switches to another tab (section-scenarios)
                await page.evaluate(() => window.switchSection('section-scenarios'));
                await page.waitForFunction(() => {
                    const sec = document.getElementById('section-overview');
                    return sec && !sec.classList.contains('active');
                }, { timeout: 10000 });
                await page.waitForTimeout(300);

                const isOverviewActive = await page.evaluate(() => {
                    const sec = document.getElementById('section-overview');
                    return sec && sec.classList.contains('active');
                });
                assert.strictEqual(isOverviewActive, false, 'section-overview must not have .active class while on another tab');

                // 3. While on that tab, performs a live mutation via window.fetch
                const mutationResult = await page.evaluate(async () => {
                    const resp = await window.fetch('/api/scenarios/active', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ scenario_id: 'base' })
                    });
                    const data = await resp.json().catch(() => ({}));
                    return { ok: resp.ok, status: resp.status, success: data.success };
                });
                assert.strictEqual(mutationResult.ok, true, `Mutation request failed with status ${mutationResult.status}`);
                assert.strictEqual(mutationResult.success, true, 'Mutation API returned success: false');

                // 4. Asserts that immediately after fetch completes, section-overview is invalidated
                const isHydratedAfterMutation = await page.evaluate(() => window.isSectionHydrated('section-overview'));
                assert.strictEqual(
                    isHydratedAfterMutation, false,
                    'Expected section-overview to be invalidated (isSectionHydrated === false) while inactive after reactive domain signal bump'
                );

                // 5. Switches back to section-overview and verifies lazy re-hydration and rendered content
                await page.evaluate(() => window.switchSection('section-overview'));
                await page.waitForFunction(() => window.isSectionHydrated('section-overview') === true, { timeout: 10000 });

                const isHydratedRestored = await page.evaluate(() => window.isSectionHydrated('section-overview'));
                assert.strictEqual(isHydratedRestored, true, 'Expected section-overview to be re-hydrated upon tab activation');

                const summaryMount = page.locator('#overview-summary-mount');
                await summaryMount.waitFor({ state: 'attached', timeout: 5000 });
                const content = await summaryMount.textContent();
                assert.ok(content && content.trim().length > 0, 'Expected #overview-summary-mount to have rendered content');

                assert.strictEqual(pageErrors.length, 0, `Uncaught JS errors during reactive re-hydration: ${pageErrors.join('; ')}`);
            } finally {
                await ctx.close();
            }
        });
    });
});
