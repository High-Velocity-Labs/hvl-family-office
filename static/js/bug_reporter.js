/**
 * Bug Reporter & AI Calculation Triage Controller
 * Privacy-preserving, scaled-anonymized pane bug reporting.
 */
(function() {
    'use strict';

    // 3-item ring buffer for recent failed API / fragment requests
    const errorRingBuffer = [];
    (function patchFetchForDiagnostics() {
        if (typeof window.fetch !== 'function') return;
        const origFetch = window.fetch;
        window.fetch = async function(...args) {
            try {
                const response = await origFetch.apply(this, args);
                if (!response.ok && response.status >= 400) {
                    const rawUrl = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url ? args[0].url : '');
                    if (rawUrl.includes('/api/') || rawUrl.includes('/fragments/')) {
                        errorRingBuffer.push({ path: rawUrl.split('?')[0], status: response.status, ts: Date.now() });
                        if (errorRingBuffer.length > 3) errorRingBuffer.shift();
                    }
                }
                return response;
            } catch (err) {
                const rawUrl = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url ? args[0].url : '');
                if (rawUrl.includes('/api/') || rawUrl.includes('/fragments/')) {
                    errorRingBuffer.push({ path: rawUrl.split('?')[0], status: 0, ts: Date.now() });
                    if (errorRingBuffer.length > 3) errorRingBuffer.shift();
                }
                throw err;
            }
        };
    })();

    const PANE_TITLES = {
        overview: 'Overview & Net Worth', equity: 'Company Equity / RSUs', scenarios: 'Forecasting & Cash Flow',
        holdings: 'Investments & Holdings', arbitrage: 'Tax Arbitrage & Living Budget', compensation: 'Compensation & Deductions',
        philanthropy: 'Philanthropy & DAF', gifting: 'Family Gifting', estate: 'Estate & Generational Wealth',
        college: 'Education Planning', accounts: 'Accounts & Connections', settings: 'Family Office Settings'
    };

    function getRandomScaleFactor() {
        return parseFloat((0.37 + Math.random() * (0.83 - 0.37)).toFixed(2));
    }

    let currentPane = 'overview', currentCategory = 'math', currentScaleFactor = getRandomScaleFactor();
    let currentDiagnosticBundle = null, lastAnalysisData = null;

    function updateCounter(inputId, counterId, maxLen) {
        const input = document.getElementById(inputId), counter = document.getElementById(counterId);
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

    function open(pane = 'overview') {
        currentPane = pane;
        currentCategory = 'math';
        currentScaleFactor = getRandomScaleFactor();
        lastAnalysisData = null;
        currentDiagnosticBundle = null;

        const modal = document.getElementById('bug-reporter-modal');
        if (!modal) return;

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
        if (badge) badge.textContent = PANE_TITLES[pane] || pane.toUpperCase();

        setCategory('math');
        showStep('input');
        modal.style.display = 'flex';
        if (descInput) setTimeout(() => descInput.focus(), 50);
    }

    function close() {
        const modal = document.getElementById('bug-reporter-modal');
        if (modal) modal.style.display = 'none';
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

        const payload = {
            pane: currentPane,
            category: currentCategory,
            description: desc,
            scale_factor: currentScaleFactor,
            client_context: {
                client_version: window.__APP_VERSION__ || '',
                recent_errors: [...errorRingBuffer],
                viewport: `${window.innerWidth}x${window.innerHeight}`,
                user_agent: navigator.userAgent
            }
        };

        try {
            const resp = await fetch('/api/bugs/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = resp.ok ? await resp.json() : null;
            if (!data || !data.success) throw new Error((data && data.error) || 'Failed to analyze calculation');

            lastAnalysisData = data;
            if (typeof data.scale_factor === 'number') currentScaleFactor = data.scale_factor;

            const explTextEl = document.getElementById('bug-ai-explanation-text');
            if (explTextEl) explTextEl.textContent = data.ai_explanation || 'No calculation discrepancies identified in snapshot.';
            const moduleEl = document.getElementById('bug-ai-suspected-module');
            if (moduleEl) {
                moduleEl.textContent = PANE_TITLES[currentPane] || 'Calculation Walkthrough';
            }

            const scaleBadge = document.getElementById('bug-preview-scale-badge');
            if (scaleBadge) scaleBadge.textContent = `Balances scaled (ephemeral multiplier discarded) • Personal identifiers stripped`;
            const scrubbedDescEl = document.getElementById('bug-preview-scrubbed-desc');
            if (scrubbedDescEl) scrubbedDescEl.textContent = data.scrubbed_description || desc;
            const previewJsonEl = document.getElementById('bug-preview-json');
            if (previewJsonEl) {
                const previewObj = data.preview_data || data.sanitized_snapshot || {};
                previewJsonEl.textContent = typeof previewObj === 'string' ? previewObj : JSON.stringify(previewObj, null, 2);
            }

            if (skipExplanationStep || currentCategory === 'ui' || currentCategory === 'permission') {
                showStep('preview');
            } else {
                showStep('explanation');
            }
        } catch (err) {
            console.error('Error analyzing bug report:', err);
            const scaleBadge = document.getElementById('bug-preview-scale-badge');
            if (scaleBadge) scaleBadge.textContent = `Balances scaled (ephemeral multiplier discarded) • Personal identifiers stripped`;
            const scrubbedDescEl = document.getElementById('bug-preview-scrubbed-desc');
            if (scrubbedDescEl) scrubbedDescEl.textContent = desc;
            const previewJsonEl = document.getElementById('bug-preview-json');
            if (previewJsonEl) {
                previewJsonEl.textContent = JSON.stringify({
                    pane: currentPane,
                    client_context: { recent_errors: errorRingBuffer }
                }, null, 2);
            }
            showStep('preview');
        } finally {
            if (analyzeBtn) {
                analyzeBtn.disabled = false;
                if (analyzeLbl && analyzeLbl.dataset.origText) analyzeLbl.textContent = analyzeLbl.dataset.origText;
            }
            if (previewBtn) previewBtn.disabled = false;
        }
    }

    function showPreviewStep() { showStep('preview'); }
    function backToInput() { showStep('input'); }
    function rerollScaleFactor() {
        currentScaleFactor = getRandomScaleFactor();
        analyzeWithAI(true);
    }

    async function submitReport() {
        const descInput = document.getElementById('bug-description-input');
        const followupInput = document.getElementById('bug-followup-input');
        const desc = descInput ? descInput.value.trim() : '';
        const followup = followupInput ? followupInput.value.trim() : '';

        const submitBtn = document.getElementById('btn-bug-submit-final');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.dataset.origText = submitBtn.textContent;
            submitBtn.textContent = 'Submitting...';
        }

        const payload = {
            pane: currentPane,
            category: currentCategory,
            description: desc,
            followup_notes: followup,
            scale_factor: currentScaleFactor,
            client_context: {
                client_version: window.__APP_VERSION__ || '',
                recent_errors: [...errorRingBuffer],
                viewport: `${window.innerWidth}x${window.innerHeight}`,
                user_agent: navigator.userAgent
            }
        };

        try {
            const resp = await fetch('/api/bugs/submit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = resp.ok ? await resp.json() : null;
            if (!data || !data.success) throw new Error((data && data.error) || 'Failed to submit bug report');

            const ticketEl = document.getElementById('bug-submitted-id');
            if (ticketEl) ticketEl.textContent = `#${data.bug_id || 'LOGGED'}`;
            currentDiagnosticBundle = data.diagnostic_bundle || {
                bug_id: data.bug_id, pane: currentPane, category: currentCategory,
                submitted_at: new Date().toISOString()
            };
            showStep('success');
        } catch (err) {
            const failMsg = err.message || 'Submission failed. Please check network connection.';
            (window.showToast ? window.showToast(failMsg, 'error') : window.showModalAlert && window.showModalAlert('Notice', failMsg));
        } finally {
            if (submitBtn) {
                submitBtn.disabled = false;
                if (submitBtn.dataset.origText) submitBtn.textContent = submitBtn.dataset.origText;
            }
        }
    }

    async function copyDiagnosticBundle() {
        if (!currentDiagnosticBundle) return;
        const str = typeof currentDiagnosticBundle === 'string'
            ? currentDiagnosticBundle : JSON.stringify(currentDiagnosticBundle, null, 2);
        try {
            await navigator.clipboard.writeText(str);
            const lbl = document.getElementById('btn-bug-copy-bundle-label') || document.querySelector('#bug-step-success button[onclick*="copyDiagnosticBundle"]');
            if (lbl) {
                const orig = lbl.textContent;
                lbl.textContent = 'Copied!';
                setTimeout(() => { lbl.textContent = orig; }, 2000);
            }
        } catch (e) {
            console.error('Failed to copy bundle:', e);
        }
    }

    const BUG_ICON_SVG = '<svg class="hvl-icon" aria-hidden="true" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="8" y="8" width="8" height="11" rx="4" fill="currentColor" fill-opacity="0.10"></rect><path d="M10 8V7a2 2 0 0 1 4 0v1"></path><path d="M5.5 11.5H8"></path><path d="M16 11.5h2.5"></path><path d="M5.5 15.5H8"></path><path d="M16 15.5h2.5"></path></svg>';

    function ensurePaneTriggers() {
        const modal = document.getElementById('bug-reporter-modal');
        if (modal) {
            modal.querySelectorAll('svg use[href*="shared-bug"]').forEach((useEl) => {
                const svgParent = useEl.closest('svg');
                if (svgParent && svgParent.parentElement) {
                    const w = svgParent.getAttribute('width') || '18';
                    const h = svgParent.getAttribute('height') || '18';
                    svgParent.outerHTML = BUG_ICON_SVG.replace('width="13" height="13"', `width="${w}" height="${h}"`);
                }
            });
        }
        if (document.body && document.body.getAttribute('data-is-demo') === 'true') return;
        document.querySelectorAll('.btn-guide-trigger').forEach((guideBtn) => {
            const parent = guideBtn.parentElement;
            if (!parent) return;
            const existing = parent.querySelector('.btn-bug-report-trigger');
            if (existing) {
                const svgEl = existing.querySelector('svg');
                if (!svgEl || svgEl.querySelector('use')) {
                    existing.innerHTML = BUG_ICON_SVG + '<span>Report Issue</span>';
                }
                return;
            }
            const sec = (guideBtn.getAttribute('data-section') || 'section-overview').replace(/^section-/, '');
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn btn-secondary btn-sm btn-bug-report-trigger';
            btn.setAttribute('data-pane', sec);
            btn.title = 'Report an issue or calculation discrepancy on this pane';
            btn.style.cssText = 'display: inline-flex; align-items: center; gap: 6px; font-size: 0.75rem; padding: 4px 10px;';
            btn.innerHTML = BUG_ICON_SVG + '<span>Report Issue</span>';
            guideBtn.insertAdjacentElement('afterend', btn);
        });
    }

    // Event delegation and lifecycle listeners
    document.addEventListener('DOMContentLoaded', () => {
        ensurePaneTriggers();
        document.body.addEventListener('htmx:afterSettle', ensurePaneTriggers);
        const descInput = document.getElementById('bug-description-input');
        if (descInput) descInput.addEventListener('input', () => updateCounter('bug-description-input', 'bug-description-counter', 500));
        const followupInput = document.getElementById('bug-followup-input');
        if (followupInput) followupInput.addEventListener('input', () => updateCounter('bug-followup-input', 'bug-followup-counter', 400));

        const modal = document.getElementById('bug-reporter-modal');
        if (modal) {
            modal.addEventListener('click', (e) => { if (e.target === modal) close(); });
        }

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && modal && modal.style.display !== 'none') close();
        });
    });

    document.addEventListener('click', (e) => {
        const trigger = e.target.closest('.btn-bug-report-trigger');
        if (trigger) {
            e.preventDefault();
            const pane = trigger.getAttribute('data-pane') || 'overview';
            open(pane);
        }
    });

    // Expose controller API on window
    window.BugReporter = {
        open,
        close,
        setCategory,
        analyzeWithAI,
        showPreviewStep,
        backToInput,
        rerollScaleFactor,
        submitReport,
        copyDiagnosticBundle,
        ensurePaneTriggers,
        getErrorRingBuffer: () => [...errorRingBuffer]
    };
})();
