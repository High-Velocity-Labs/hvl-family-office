const { describe, it, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { createTestDomEnvironment } = require('../../vendor/hvl_common/testing/js/dom_harness.js');

const bugModalRaw = fs.readFileSync(
    path.join(__dirname, '../../templates/components/bug_reporter_modal.html'),
    'utf8'
).replace(/\{\{\s*icon\([^)]*\)\s*\}\}/g, '<svg class="hvl-icon"></svg>');

describe('v0.3.0 Frontend UI Suite (SandboxManager, Cloud .fovault Portability & BugReporter)', () => {
    let dom;
    let window;
    let document;
    let fetchCalls;
    let lastToast;
    let confirmResult;
    let alertCalls;

    const buildHtml = (isSandbox = true) => `
    <!DOCTYPE html>
    <html>
    <head><title>v0.3.0 UI Harness</title></head>
    <body data-is-demo="false" data-is-sandbox="${isSandbox ? 'true' : 'false'}">
        <div id="sandbox-ephemeral-banner" data-expires-at="${Math.floor(Date.now() / 1000) + 7200}">
            <strong id="sandbox-expiry-countdown" data-expires-at="${Math.floor(Date.now() / 1000) + 7200}">--</strong>
            <span class="sandbox-countdown-display" data-expires-at="${Math.floor(Date.now() / 1000) + 7200}">--</span>
            <a href="/sandbox/migrate-to-cloud" id="btn-sandbox-save-cloud">Save to Cloud Vault</a>
            <button type="button" id="btn-sandbox-extend-banner">Save for 7 Days</button>
            <button type="button" id="btn-sandbox-extend-settings">Save for 7 Days</button>
            <button type="button" id="btn-sandbox-download-banner" disabled style="opacity: 0.5;">Download .fovault</button>
            <button type="button" id="btn-sandbox-download-settings" disabled style="opacity: 0.5;">Download Vault (.fovault)</button>
            <input type="file" id="sandbox-fovault-upload-input" accept=".fovault,.db">
        </div>
        <div class="section-header-actions">
            <button type="button" class="btn-guide-trigger" data-section="section-equity">Guide</button>
        </div>
        ${bugModalRaw}
    </body>
    </html>
    `;

    function cleanupDom() {
        if (window && window._sandboxTimerInterval) {
            window.clearInterval(window._sandboxTimerInterval);
            window._sandboxTimerInterval = null;
        }
        if (dom && dom.window) {
            dom.window.close();
        }
    }

    function setupEnv(isSandbox = true) {
        cleanupDom();
        fetchCalls = [];
        lastToast = null;
        confirmResult = true;
        alertCalls = [];

        const env = createTestDomEnvironment({
            html: buildHtml(isSandbox),
            url: 'https://finances.highvelocitylabs.dev/',
            fetchHandlers: [
                {
                    matcher: '/api/sandbox/extend',
                    handler: async () => {
                        fetchCalls.push({ url: '/api/sandbox/extend', method: 'POST' });
                        return {
                            ok: true,
                            status: 200,
                            json: async () => ({
                                success: true,
                                expires_at: Math.floor(Date.now() / 1000) + 7 * 86400
                            })
                        };
                    }
                },
                {
                    matcher: '/api/sandbox/wipe',
                    handler: async () => {
                        fetchCalls.push({ url: '/api/sandbox/wipe', method: 'POST' });
                        return { ok: true, status: 200, json: async () => ({ success: true }) };
                    }
                },
                {
                    matcher: '/api/sandbox/restore_async',
                    handler: async () => {
                        fetchCalls.push({ url: '/api/sandbox/restore_async', method: 'POST' });
                        return { ok: true, status: 202, json: async () => ({ success: true, job_id: 'job-sb-restore-1' }) };
                    }
                },
                {
                    matcher: '/api/vault/restore_async',
                    handler: async () => {
                        fetchCalls.push({ url: '/api/vault/restore_async', method: 'POST' });
                        return { ok: true, status: 202, json: async () => ({ success: true, job_id: 'job-cloud-restore-1' }) };
                    }
                },
                {
                    matcher: (url) => url.includes('/api/jobs/'),
                    handler: async (url) => {
                        fetchCalls.push({ url, method: 'GET' });
                        return {
                            ok: true,
                            status: 200,
                            json: async () => ({
                                status: 'completed',
                                success: true,
                                summary: { summary_text: 'Restored 14 tables and 6 accounts.' }
                            })
                        };
                    }
                },
                {
                    matcher: '/api/accounts/manual',
                    handler: async (_url, opts) => {
                        fetchCalls.push({ url: '/api/accounts/manual', method: (opts && opts.method) || 'GET' });
                        return { ok: true, status: 200, json: async () => ({ success: true }) };
                    }
                },
                {
                    matcher: '/api/bugs/analyze',
                    handler: async (_url, opts) => {
                        const body = JSON.parse((opts && opts.body) || '{}');
                        fetchCalls.push({ url: '/api/bugs/analyze', method: 'POST', body });
                        return {
                            ok: true,
                            status: 200,
                            json: async () => ({
                                success: true,
                                scale_factor: body.scale_factor || 0.55,
                                ai_explanation: 'RSU withholding uses the 22% statutory supplemental federal rate.',
                                scrubbed_description: '[REDACTED_NAME] RSU vest looks 5% lower than expected.',
                                sanitized_snapshot: { total_rsu_value: 110000 }
                            })
                        };
                    }
                },
                {
                    matcher: '/api/bugs/submit',
                    handler: async (_url, opts) => {
                        const body = JSON.parse((opts && opts.body) || '{}');
                        fetchCalls.push({ url: '/api/bugs/submit', method: 'POST', body });
                        return {
                            ok: true,
                            status: 200,
                            json: async () => ({
                                success: true,
                                bug_id: 42,
                                diagnostic_bundle: { bug_id: 42, pane: body.pane, scale_factor: body.scale_factor }
                            })
                        };
                    }
                },
                {
                    matcher: '/api/failing-endpoint',
                    handler: async () => ({ ok: false, status: 500, json: async () => ({ error: 'Simulated 500' }) })
                }
            ]
        });

        dom = env.dom;
        window = env.window;
        document = env.document;

        window.hvlShowToast = (msg, variant) => { lastToast = { msg, variant }; };
        window.showModalConfirm = async (_msg, _opts) => confirmResult;
        window.showModalAlert = async (msg, opts) => { alertCalls.push({ msg, opts }); };

        const loadScript = (relPath) => {
            const scriptEl = document.createElement('script');
            scriptEl.textContent = fs.readFileSync(path.join(__dirname, relPath), 'utf8');
            document.body.appendChild(scriptEl);
        };
        loadScript('../../static/js/sandbox_ui.js');
        loadScript('../../static/js/bug_reporter.js');
        window.SandboxManager.initCountdown();
        document.dispatchEvent(new window.Event('DOMContentLoaded'));
    }

    beforeEach(() => {
        setupEnv(true);
    });

    afterEach(() => {
        cleanupDom();
    });

    it('formats sandbox countdown timer and enables .fovault download after POST mutation', async () => {
        const countdownEl = document.getElementById('sandbox-expiry-countdown');
        assert.ok(countdownEl.textContent.includes('h'), `Expected formatted countdown, got: ${countdownEl.textContent}`);

        const dlBannerBtn = document.getElementById('btn-sandbox-download-banner');
        const dlSettingsBtn = document.getElementById('btn-sandbox-download-settings');
        assert.strictEqual(dlBannerBtn.disabled, true);
        assert.strictEqual(dlSettingsBtn.disabled, true);

        await window.fetch('/api/accounts/manual', { method: 'POST' });
        assert.strictEqual(dlBannerBtn.disabled, false, 'Banner download button should enable after POST mutation');
        assert.strictEqual(dlSettingsBtn.disabled, false, 'Settings download button should enable after POST mutation');
    });

    it('extends sandbox lease to 7 days and updates button state + semantic green border token', async () => {
        await window.SandboxManager.extendSandbox7Days();
        assert.ok(fetchCalls.some(c => c.url === '/api/sandbox/extend' && c.method === 'POST'));

        const btnBanner = document.getElementById('btn-sandbox-extend-banner');
        const btnSettings = document.getElementById('btn-sandbox-extend-settings');
        assert.strictEqual(btnBanner.disabled, true);
        assert.strictEqual(btnBanner.textContent, '✓ Saved (7-Day Lease Active)');
        assert.strictEqual(btnSettings.textContent, '✓ Saved (7-Day Lease Active)');
        assert.strictEqual(btnBanner.style.borderColor, 'var(--status-green)');
        assert.strictEqual(lastToast.variant, 'success');
    });

    it('routes downloadSandboxVault and uploadSandboxVault appropriately for Sandbox vs Cloud Vault modes', async () => {
        let clickedHref = null;
        let clickedDownload = null;
        const origCreateElement = document.createElement.bind(document);
        document.createElement = (tag) => {
            const el = origCreateElement(tag);
            if (tag.toLowerCase() === 'a') {
                el.click = () => {
                    clickedHref = el.getAttribute('href') || el.href;
                    clickedDownload = el.download;
                };
            }
            return el;
        };

        // 1. Anonymous Workspace (data-is-sandbox="true")
        window.SandboxManager.downloadSandboxVault();
        assert.ok(clickedHref.endsWith('/api/desktop/backup?sandbox=1'), `Expected sandbox backup URL, got ${clickedHref}`);
        assert.ok(clickedDownload.startsWith('family_office_sandbox_'));

        const fakeInput = { files: [new window.File(['SQLite format 3'], 'anon_test.fovault')], value: 'anon_test.fovault' };
        await window.SandboxManager.uploadSandboxVault(fakeInput);
        assert.ok(fetchCalls.some(c => c.url === '/api/sandbox/restore_async'));
        assert.ok(fetchCalls.some(c => c.url === '/api/jobs/job-sb-restore-1'));
        assert.strictEqual(alertCalls.length, 1);
        assert.ok(alertCalls[0].msg.includes('Restored 14 tables'));

        // 2. Cloud Vault Mode (data-is-sandbox="false")
        setupEnv(false);
        const origCreate2 = document.createElement.bind(document);
        document.createElement = (tag) => {
            const el = origCreate2(tag);
            if (tag.toLowerCase() === 'a') {
                el.click = () => {
                    clickedHref = el.getAttribute('href') || el.href;
                    clickedDownload = el.download;
                };
            }
            return el;
        };

        window.SandboxManager.downloadSandboxVault();
        assert.ok(clickedHref.endsWith('/api/desktop/backup'), `Expected cloud backup URL, got ${clickedHref}`);
        assert.ok(clickedDownload.startsWith('family_office_vault_'));

        const cloudInput = { files: [new window.File(['SQLite format 3'], 'cloud_test.fovault')], value: 'cloud_test.fovault' };
        await window.SandboxManager.uploadSandboxVault(cloudInput);
        assert.ok(fetchCalls.some(c => c.url === '/api/vault/restore_async'));
        assert.ok(fetchCalls.some(c => c.url === '/api/jobs/job-cloud-restore-1'));
    });

    it('manages BugReporter lifecycle, AI calculation triage, scale factor re-roll, and submission', async () => {
        // Injects Report Issue trigger next to .btn-guide-trigger
        const reportTrigger = document.querySelector('.btn-bug-report-trigger');
        assert.ok(reportTrigger, 'Expected .btn-bug-report-trigger to be injected next to .btn-guide-trigger');
        assert.strictEqual(reportTrigger.getAttribute('data-pane'), 'equity');

        // Record a failed API call into the 3-item diagnostic ring buffer
        await window.fetch('/api/failing-endpoint');
        const ring = window.BugReporter.getErrorRingBuffer();
        assert.strictEqual(ring.length, 1);
        assert.strictEqual(ring[0].path, '/api/failing-endpoint');
        assert.strictEqual(ring[0].status, 500);

        // Open modal for equity pane
        window.BugReporter.open('equity');
        const modal = document.getElementById('bug-reporter-modal');
        assert.strictEqual(modal.style.display, 'flex');
        assert.strictEqual(document.getElementById('bug-modal-pane-badge').textContent, 'Company Equity / RSUs');

        // Enter description and run AI calculation triage (math category -> shows explanation step)
        const descInput = document.getElementById('bug-description-input');
        descInput.value = 'My RSU vest looks 5% lower than expected.';
        descInput.dispatchEvent(new window.Event('input'));
        assert.strictEqual(document.getElementById('bug-description-counter').textContent, '41 / 500 chars');

        await window.BugReporter.analyzeWithAI(false);
        assert.strictEqual(document.getElementById('bug-step-explanation').style.display, 'block');
        assert.ok(document.getElementById('bug-ai-explanation-text').textContent.includes('22% statutory'));

        // Proceed to preview step and re-roll scale factor
        window.BugReporter.showPreviewStep();
        assert.strictEqual(document.getElementById('bug-step-preview').style.display, 'block');
        await window.BugReporter.rerollScaleFactor();
        assert.ok(document.getElementById('bug-preview-scrubbed-desc').textContent.includes('[REDACTED_NAME]'));

        // Submit report -> transitions to success step with ticket #42
        await window.BugReporter.submitReport();
        assert.strictEqual(document.getElementById('bug-step-success').style.display, 'block');
        assert.strictEqual(document.getElementById('bug-submitted-id').textContent, '#42');
    });

    it('reactively invalidates only sections whose data-depends intersect bumped domain signals', async () => {
        const container = document.createElement('div');
        container.innerHTML = `
            <section id="section-overview" class="page-section" data-fragment="overview" data-depends="balance_sheet,accounts,holdings" data-loaded="true" style="display: block;"></section>
            <section id="section-accounts" class="page-section" data-fragment="accounts" data-depends="accounts,holdings,balance_sheet" data-loaded="true" style="display: none;"></section>
            <section id="section-gifting" class="page-section" data-fragment="gifting" data-depends="gifting,household.members" data-loaded="true" style="display: none;"></section>
        `;
        document.body.appendChild(container);
        window.__DOMAIN_VERSIONS__ = { accounts: 1, balance_sheet: 1, holdings: 1, gifting: 1, 'household.members': 1 };
        window.currentSectionId = 'section-overview';
        window.currentViewMode = 'focused';
        window.globalDashboardData = { success: true, snapshot: {}, multi_year_projections: [] };

        const morphedTargets = [];
        window.htmx = {
            ajax: async (_method, url, ctx) => {
                morphedTargets.push({ url, target: ctx && ctx.target });
            }
        };

        for (const rel of ['../../static/js/app_sync.js', '../../static/js/app_hydration.js']) {
            const s = document.createElement('script');
            s.textContent = fs.readFileSync(path.join(__dirname, rel), 'utf8');
            document.body.appendChild(s);
        }

        // 1. Signal + effect + batch coalescing
        const sigA = window.createSignal(1);
        const sigB = window.createSignal(10);
        let effectRuns = 0;
        let observedSum = 0;
        window.effect(() => {
            effectRuns += 1;
            observedSum = sigA.value + sigB.value;
        });
        assert.strictEqual(effectRuns, 1);
        assert.strictEqual(observedSum, 11);

        window.batch(() => {
            sigA.value = 2;
            sigB.value = 20;
        });
        assert.strictEqual(effectRuns, 2, 'batch() should coalesce multiple signal writes into a single effect run');
        assert.strictEqual(observedSum, 22);

        // 2. Register section hydrators and verify declarative invalidation
        let overviewInvalidations = 0;
        let overviewHydrations = 0;
        let giftingInvalidations = 0;
        window.registerSectionHydrator('section-overview', () => { overviewHydrations += 1; }, {
            onInvalidate: () => { overviewInvalidations += 1; }
        });
        window.registerSectionHydrator('section-gifting', () => {}, {
            onInvalidate: () => { giftingInvalidations += 1; }
        });

        window.hydrateSection('section-overview');
        assert.strictEqual(overviewHydrations, 1);
        // Second call with unchanged domain versions is a no-op
        window.hydrateSection('section-overview');
        assert.strictEqual(overviewHydrations, 1);

        // Bump balance_sheet & accounts (via X-Domain-Versions header payload)
        await window.applyDomainVersions({ accounts: 2, balance_sheet: 2, gifting: 1 });

        assert.strictEqual(overviewInvalidations, 1, 'Overview onInvalidate should fire when balance_sheet bumps');
        assert.strictEqual(giftingInvalidations, 0, 'Gifting onInvalidate must NOT fire when only accounts/balance_sheet bumps');
        assert.ok(morphedTargets.some(m => m.url.includes('/fragments/overview')), 'Visible dependent #section-overview should morph immediately');
        assert.strictEqual(document.getElementById('section-accounts').dataset.loaded, 'false', 'Hidden dependent #section-accounts should be marked data-loaded=false');
        assert.strictEqual(document.getElementById('section-gifting').dataset.loaded, 'true', 'Unrelated #section-gifting must remain data-loaded=true');
    });
});
