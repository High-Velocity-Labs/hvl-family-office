/**
 * Shared Level 5 Desktop, Tablet & Mobile Viewport Overflow & Browser Runner (hvl_common)
 * Powered by playwright-core with system Chrome.
 *
 * Configured via process.env.OVERFLOW_CONFIG_JSON:
 * - publicPages: string[]
 * - authPages: string[]
 * - authUrl: string (optional, e.g. '/api/test/auth_session')
 * - unauthUrl: string (optional, e.g. '/api/test/unauth_session')
 * - tabSelectors: string[] (optional selectors to click on '/')
 * - containerSelectors: string (optional CSS selector for card/navbar overflow checks)
 * - viewports: Array<{ name: string, width: number, height: number }>
 */

const { describe, it, before, after } = require('node:test');
const assert = require('node:assert');
const { chromium } = require('playwright-core');

const BASE_URL = process.env.BASE_URL || process.argv[2] || 'http://127.0.0.1:5000';
const RAW_CFG = process.env.OVERFLOW_CONFIG_JSON ? JSON.parse(process.env.OVERFLOW_CONFIG_JSON) : {};

const VIEWPORTS = RAW_CFG.viewports || [
    { name: 'Desktop', width: 1440, height: 900 },
    { name: 'Tablet', width: 768, height: 1024 },
    { name: 'Mobile', width: 390, height: 844 }
];

const PUBLIC_PAGES = RAW_CFG.publicPages || [];
const AUTH_PAGES = RAW_CFG.authPages || [];
const AUTH_URL = RAW_CFG.authUrl || '';
const UNAUTH_URL = RAW_CFG.unauthUrl || '';
const TAB_SELECTORS = RAW_CFG.tabSelectors || [];
const CONTAINER_SELECTORS = RAW_CFG.containerSelectors || '';

describe('Level 5: HVL Shared Viewport Overflow & Error Purity Suite', () => {
    let browser;
    before(async () => { browser = await chromium.launch({ channel: 'chrome', headless: true }); });
    after(async () => { if (browser) await browser.close(); });

    async function checkHorizontalOverflow(page, label) {
        return await page.evaluate(({ label, containerSelectors }) => {
            const sw = document.documentElement.scrollWidth;
            const cw = document.documentElement.clientWidth;
            const tolerance = 2;
            const offenders = [];

            function isInsideHorizontalScroller(el, stopAt) {
                let cur = el.parentElement;
                while (cur && cur !== stopAt && cur !== document.body && cur !== document.documentElement) {
                    const cs = window.getComputedStyle(cur);
                    if (cs.overflowX === 'auto' || cs.overflowX === 'scroll' || cs.overflowX === 'hidden') return true;
                    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return true;
                    cur = cur.parentElement;
                }
                return false;
            }

            function isFloatingOrOffscreenOverlay(el) {
                let cur = el;
                while (cur && cur !== document.body && cur !== document.documentElement) {
                    if (cur.hasAttribute && cur.hasAttribute('popover') && !cur.matches(':popover-open')) return true;
                    const cs = window.getComputedStyle(cur);
                    if (cs.position === 'fixed' && !cur.classList.contains('open') && !cur.classList.contains('active') && (cur.id.includes('drawer') || cur.classList.contains('drawer') || cur.classList.contains('modal'))) {
                        return true;
                    }
                    cur = cur.parentElement;
                }
                return false;
            }

            for (const el of document.querySelectorAll('*')) {
                const rect = el.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) continue;
                const cs = window.getComputedStyle(el);
                if (cs.display === 'none' || cs.visibility === 'hidden') continue;
                if (isFloatingOrOffscreenOverlay(el) || isInsideHorizontalScroller(el, document.body)) continue;
                if (rect.right > cw + tolerance) {
                    offenders.push({
                        type: 'viewport',
                        tag: el.tagName.toLowerCase(),
                        id: el.id || '',
                        className: typeof el.className === 'string' ? el.className.slice(0, 60) : '',
                        text: (el.textContent || '').trim().slice(0, 40),
                        right: Math.round(rect.right),
                        boundRight: cw,
                        overflowPx: Math.round(rect.right - cw)
                    });
                }
            }

            if (containerSelectors) {
                for (const container of document.querySelectorAll(containerSelectors)) {
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
                                type: 'container',
                                container: container.id || container.className.toString().slice(0, 40),
                                tag: child.tagName.toLowerCase(),
                                id: child.id || '',
                                className: typeof child.className === 'string' ? child.className.slice(0, 50) : '',
                                text: (child.textContent || '').trim().slice(0, 40),
                                right: Math.round(r.right),
                                boundRight: Math.round(cRect.right),
                                overflowPx: Math.round(r.right - cRect.right)
                            });
                        }
                    }
                }
            }

            const hasOverflow = (sw > cw + tolerance) || offenders.length > 0;
            return { label, scrollWidth: sw, clientWidth: cw, hasOverflow, offenders: offenders.slice(0, 10) };
        }, { label, containerSelectors: CONTAINER_SELECTORS });
    }

    async function loadPageWithMonitoring(page, urlPath) {
        const pageErrors = [];
        const errorHandler = (err) => pageErrors.push(err.message || String(err));
        page.on('pageerror', errorHandler);
        await page.goto(`${BASE_URL}${urlPath}`, { waitUntil: 'load' });
        return { pageErrors, removeListener: () => page.off('pageerror', errorHandler) };
    }

    if (PUBLIC_PAGES.length > 0) {
        describe('1. Public Pages Viewport Geometry & Error Purity', () => {
            for (const vp of VIEWPORTS) {
                for (const pagePath of PUBLIC_PAGES) {
                    it(`renders ${pagePath} cleanly on ${vp.name} (${vp.width}x${vp.height})`, async () => {
                        const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
                        try {
                            if (UNAUTH_URL) {
                                const p = await ctx.newPage();
                                await p.goto(`${BASE_URL}${UNAUTH_URL}`, { waitUntil: 'domcontentloaded' });
                                await p.close();
                            }
                            const page = await ctx.newPage();
                            const { pageErrors } = await loadPageWithMonitoring(page, pagePath);
                            assert.strictEqual(pageErrors.length, 0, `Uncaught JS page errors on ${pagePath} (${vp.name}): ${pageErrors.join('; ')}`);
                            const overflow = await checkHorizontalOverflow(page, `${pagePath} [${vp.name}]`);
                            assert.strictEqual(
                                overflow.hasOverflow, false,
                                `Horizontal overflow on ${pagePath} (${vp.name}): scrollWidth=${overflow.scrollWidth} > clientWidth=${overflow.clientWidth}. Offenders: ${JSON.stringify(overflow.offenders)}`
                            );
                        } finally {
                            await ctx.close();
                        }
                    });
                }
            }
        });
    }

    if (AUTH_PAGES.length > 0) {
        describe('2. Authenticated Pages & Tabs Viewport Geometry & Error Purity', () => {
            for (const vp of VIEWPORTS) {
                for (const pagePath of AUTH_PAGES) {
                    it(`renders authenticated ${pagePath} cleanly on ${vp.name} (${vp.width}x${vp.height})`, async () => {
                        const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
                        try {
                            if (AUTH_URL) {
                                const p = await ctx.newPage();
                                await p.goto(`${BASE_URL}${AUTH_URL}`, { waitUntil: 'domcontentloaded' });
                                await p.close();
                            }
                            const page = await ctx.newPage();
                            const { pageErrors } = await loadPageWithMonitoring(page, pagePath);
                            assert.strictEqual(pageErrors.length, 0, `Uncaught JS page errors on ${pagePath} (${vp.name}): ${pageErrors.join('; ')}`);
                            const overflow = await checkHorizontalOverflow(page, `auth:${pagePath} [${vp.name}]`);
                            assert.strictEqual(
                                overflow.hasOverflow, false,
                                `Horizontal overflow on authenticated ${pagePath} (${vp.name}): scrollWidth=${overflow.scrollWidth} > clientWidth=${overflow.clientWidth}. Offenders: ${JSON.stringify(overflow.offenders)}`
                            );

                            if (pagePath === '/' && TAB_SELECTORS.length > 0) {
                                for (const sel of TAB_SELECTORS) {
                                    const el = await page.$(sel);
                                    if (el) {
                                        await el.click();
                                        const tabOverflow = await checkHorizontalOverflow(page, `tab:${sel} [${vp.name}]`);
                                        assert.strictEqual(
                                            tabOverflow.hasOverflow, false,
                                            `Horizontal overflow on tab ${sel} (${vp.name}): Offenders: ${JSON.stringify(tabOverflow.offenders)}`
                                        );
                                    }
                                }
                            }
                        } finally {
                            await ctx.close();
                        }
                    });
                }
            }
        });
    }
});
