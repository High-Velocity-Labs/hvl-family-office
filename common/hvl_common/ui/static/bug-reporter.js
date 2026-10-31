/**
 * Shared HVL Bug Report & Calculation Triage Modal Controller (`/common/bug-reporter.js`)
 * Provides privacy-preserving bug reporting, screenshot paste/upload helpers, and
 * global `[data-action="open-bug-report"]` / `.btn-bug-report-trigger` delegation.
 */
(function () {
    'use strict';

    const errorRingBuffer = [];
    if (typeof window !== 'undefined' && typeof window.fetch === 'function' && !window._hvlBugFetchPatched) {
        window._hvlBugFetchPatched = true;
        const origFetch = window.fetch;
        window.fetch = async function (...args) {
            const rawUrl = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url ? args[0].url : '');
            const trackable = rawUrl.includes('/api/') || rawUrl.includes('/fragments/');
            try {
                const response = await origFetch.apply(this, args);
                if (!response.ok && response.status >= 400 && trackable) {
                    errorRingBuffer.push({ path: rawUrl.split('?')[0], status: response.status, ts: Date.now() });
                    if (errorRingBuffer.length > 3) errorRingBuffer.shift();
                }
                return response;
            } catch (err) {
                if (trackable) {
                    errorRingBuffer.push({ path: rawUrl.split('?')[0], status: 0, ts: Date.now() });
                    if (errorRingBuffer.length > 3) errorRingBuffer.shift();
                }
                throw err;
            }
        };
    }

    const DEFAULT_PANE_TITLES = {
        overview: 'Overview & Net Worth',
        equity: 'Company Equity / RSUs',
        scenarios: 'Forecasting & Cash Flow',
        holdings: 'Investments & Holdings',
        arbitrage: 'Tax Arbitrage & Living Budget',
        compensation: 'Compensation & Deductions',
        philanthropy: 'Philanthropy & DAF',
        gifting: 'Family Gifting',
        estate: 'Estate & Generational Wealth',
        college: 'Education Planning',
        accounts: 'Accounts & Connections',
        settings: 'Settings'
    };

    const BUG_ICON_SVG = '<svg class="hvl-icon" aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="8" y="8" width="8" height="11" rx="4" fill="currentColor" fill-opacity="0.10"></rect><path d="M10 8V7a2 2 0 0 1 4 0v1"></path><path d="M5.5 11.5H8"></path><path d="M16 11.5h2.5"></path><path d="M5.5 15.5H8"></path><path d="M16 15.5h2.5"></path></svg>';

    function getRandomScaleFactor() {
        return parseFloat((0.37 + Math.random() * (0.83 - 0.37)).toFixed(2));
    }

    let currentPane = 'overview';
    let currentCategory = 'math';
    let currentScaleFactor = getRandomScaleFactor();
    let currentDiagnosticBundle = null;
    let currentAttachmentDataUrl = null;

    function updateCounter(inputId, counterId, maxLen) {
        const input = document.getElementById(inputId);
        const counter = document.getElementById(counterId);
        if (input && counter) counter.textContent = `${input.value.length} / ${maxLen} chars`;
    }

    function showStep(stepName) {
        ['input', 'explanation', 'preview', 'success'].forEach((name) => {
            const el = document.getElementById(`bug-step-${name}`);
            if (el) el.style.display = (name === stepName) ? 'block' : 'none';
        });
    }

    function setCategory(category) {
        currentCategory = category;
        const container = document.getElementById('bug-category-pills');
        if (container) {
            container.querySelectorAll('.category-pill').forEach((p) => {
                p.classList.toggle('active', p.getAttribute('data-category') === category);
            });
        }
    }

    function attachScreenshotFile(file) {
        if (!file || typeof FileReader === 'undefined') return Promise.resolve(null);
        return new Promise((resolve) => {
            const reader = new FileReader();
            reader.onload = () => {
                currentAttachmentDataUrl = typeof reader.result === 'string' ? reader.result : null;
                const prev = document.getElementById('bug-screenshot-preview');
                if (prev && currentAttachmentDataUrl) {
                    prev.src = currentAttachmentDataUrl;
                    prev.style.display = 'block';
                }
                resolve(currentAttachmentDataUrl);
            };
            reader.onerror = () => resolve(null);
            reader.readAsDataURL(file);
        });
    }

    function openBugReportModal(pane = 'overview') {
        currentPane = pane || 'overview';
        currentCategory = 'math';
        currentScaleFactor = getRandomScaleFactor();
        currentDiagnosticBundle = null;
        currentAttachmentDataUrl = null;

        const modal = document.getElementById('bug-reporter-modal');
        if (!modal) return null;

        const descInput = document.getElementById('bug-description-input');
        if (descInput) {
            descInput.value = '';
            updateCounter('bug-description-input', 'bug-description-counter', 500);
        }
        const followupInput = document.getElementById('bug-followup-input');
        if (followupInput) {
            followupInput.value = '';
            updateCounter('bug-followup-input', 'bug-followup-counter', 400);
        }

        const badge = document.getElementById('bug-modal-pane-badge');
        if (badge) badge.textContent = DEFAULT_PANE_TITLES[currentPane] || currentPane.toUpperCase();

        setCategory('math');
        showStep('input');
        modal.style.display = 'flex';
        if (descInput) setTimeout(() => descInput.focus(), 50);
        return modal;
    }

    function closeBugReportModal() {
        const modal = document.getElementById('bug-reporter-modal');
        if (modal) modal.style.display = 'none';
    }

    function buildClientContext() {
        return {
            client_version: window.__APP_VERSION__ || '',
            recent_errors: [...errorRingBuffer],
            viewport: `${window.innerWidth}x${window.innerHeight}`,
            user_agent: typeof navigator !== 'undefined' ? navigator.userAgent : ''
        };
    }

    async function analyzeWithAI(skipExplanationStep = false) {
        const descInput = document.getElementById('bug-description-input');
        const desc = descInput ? descInput.value.trim() : '';
        if (!desc) {
            if (descInput) descInput.focus();
            return;
        }

        const analyzeBtn = document.getElementById('btn-bug-analyze');
        const analyzeLbl = document.getElementById('btn-bug-analyze-label') || analyzeBtn;
        const previewBtn = document.getElementById('btn-bug-skip-to-preview');
        if (analyzeBtn) {
            analyzeBtn.disabled = true;
            if (analyzeLbl) {
                analyzeLbl.dataset.origText = analyzeLbl.textContent;
                analyzeLbl.textContent = 'Analyzing...';
            }
        }
        if (previewBtn) previewBtn.disabled = true;

        try {
            const resp = await fetch('/api/bugs/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    pane: currentPane,
                    category: currentCategory,
                    description: desc,
                    scale_factor: currentScaleFactor,
                    client_context: buildClientContext()
                })
            });
            const data = resp.ok ? await resp.json() : null;
            if (!data || !data.success) throw new Error((data && data.error) || 'Failed to analyze calculation');
            if (typeof data.scale_factor === 'number') currentScaleFactor = data.scale_factor;

            const explTextEl = document.getElementById('bug-ai-explanation-text');
            if (explTextEl) explTextEl.textContent = data.ai_explanation || 'No calculation discrepancies identified in snapshot.';
            const moduleEl = document.getElementById('bug-ai-suspected-module');
            if (moduleEl) moduleEl.textContent = DEFAULT_PANE_TITLES[currentPane] || 'Calculation Walkthrough';

            const scaleBadge = document.getElementById('bug-preview-scale-badge');
            if (scaleBadge) scaleBadge.textContent = 'Balances scaled (ephemeral multiplier discarded) • Personal identifiers stripped';
            const scrubbedDescEl = document.getElementById('bug-preview-scrubbed-desc');
            if (scrubbedDescEl) scrubbedDescEl.textContent = data.scrubbed_description || desc;
            const previewJsonEl = document.getElementById('bug-preview-json');
            if (previewJsonEl) {
                const previewObj = data.preview_data || data.sanitized_snapshot || {};
                previewJsonEl.textContent = typeof previewObj === 'string' ? previewObj : JSON.stringify(previewObj, null, 2);
            }
            showStep((skipExplanationStep || currentCategory === 'ui' || currentCategory === 'permission') ? 'preview' : 'explanation');
        } catch (_) {
            const scrubbedDescEl = document.getElementById('bug-preview-scrubbed-desc');
            if (scrubbedDescEl) scrubbedDescEl.textContent = desc;
            const previewJsonEl = document.getElementById('bug-preview-json');
            if (previewJsonEl) previewJsonEl.textContent = JSON.stringify({ pane: currentPane, client_context: { recent_errors: errorRingBuffer } }, null, 2);
            showStep('preview');
        } finally {
            if (analyzeBtn) {
                analyzeBtn.disabled = false;
                if (analyzeLbl && analyzeLbl.dataset.origText) analyzeLbl.textContent = analyzeLbl.dataset.origText;
            }
            if (previewBtn) previewBtn.disabled = false;
        }
    }

    async function submitReport() {
        const descInput = document.getElementById('bug-description-input');
        const followupInput = document.getElementById('bug-followup-input');
        const submitBtn = document.getElementById('btn-bug-submit-final');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.dataset.origText = submitBtn.textContent;
            submitBtn.textContent = 'Submitting...';
        }
        try {
            const resp = await fetch('/api/bugs/submit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    pane: currentPane,
                    category: currentCategory,
                    description: descInput ? descInput.value.trim() : '',
                    followup_notes: followupInput ? followupInput.value.trim() : '',
                    scale_factor: currentScaleFactor,
                    screenshot: currentAttachmentDataUrl || undefined,
                    client_context: buildClientContext()
                })
            });
            const data = resp.ok ? await resp.json() : null;
            if (!data || !data.success) throw new Error((data && data.error) || 'Failed to submit bug report');
            const ticketEl = document.getElementById('bug-submitted-id');
            if (ticketEl) ticketEl.textContent = `#${data.bug_id || 'LOGGED'}`;
            currentDiagnosticBundle = data.diagnostic_bundle || { bug_id: data.bug_id, pane: currentPane, category: currentCategory };
            showStep('success');
        } catch (err) {
            const failMsg = err.message || 'Submission failed. Please check network connection.';
            if (typeof window.showToast === 'function') window.showToast(failMsg, 'error');
            else if (typeof window.showModalAlert === 'function') window.showModalAlert(failMsg, 'Notice');
        } finally {
            if (submitBtn) {
                submitBtn.disabled = false;
                if (submitBtn.dataset.origText) submitBtn.textContent = submitBtn.dataset.origText;
            }
        }
    }

    async function copyDiagnosticBundle() {
        if (!currentDiagnosticBundle || !navigator.clipboard) return;
        const str = typeof currentDiagnosticBundle === 'string' ? currentDiagnosticBundle : JSON.stringify(currentDiagnosticBundle, null, 2);
        try {
            await navigator.clipboard.writeText(str);
            const lbl = document.getElementById('btn-bug-copy-bundle-label');
            if (lbl) {
                const orig = lbl.textContent;
                lbl.textContent = 'Copied!';
                setTimeout(() => { lbl.textContent = orig; }, 2000);
            }
        } catch (_) {}
    }

    if (typeof document !== 'undefined') {
        document.addEventListener('click', (e) => {
            const trigger = e.target && e.target.closest ? e.target.closest('.btn-bug-report-trigger, [data-action="open-bug-report"]') : null;
            if (trigger) {
                e.preventDefault();
                openBugReportModal(trigger.getAttribute('data-pane') || 'overview');
            }
        });
        document.addEventListener('paste', (e) => {
            const modal = document.getElementById('bug-reporter-modal');
            if (!modal || modal.style.display === 'none' || !e.clipboardData || !e.clipboardData.files) return;
            const img = Array.from(e.clipboardData.files).find((f) => f.type && f.type.startsWith('image/'));
            if (img) attachScreenshotFile(img);
        });
    }

    window.openBugReportModal = openBugReportModal;
    window.closeBugReportModal = closeBugReportModal;
    window.BugReporter = {
        open: openBugReportModal,
        close: closeBugReportModal,
        setCategory,
        analyzeWithAI,
        showPreviewStep: () => showStep('preview'),
        backToInput: () => showStep('input'),
        rerollScaleFactor: () => { currentScaleFactor = getRandomScaleFactor(); analyzeWithAI(true); },
        submitReport,
        copyDiagnosticBundle,
        attachScreenshotFile,
        BUG_ICON_SVG,
        getErrorRingBuffer: () => [...errorRingBuffer]
    };
})();
