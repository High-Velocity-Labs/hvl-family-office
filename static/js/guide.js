/**
 * Page Guide & Tool Documentation Controller
 * Factual, structured reference for each platform tool and section.
 * Explains purpose, core mental models (e.g. Parent & Child plans),
 * step-by-step usage, and underlying calculation engines.
 */

(function() {
    'use strict';

    let guideIsOpen = false;
    const GUIDE_DATA = window.GUIDE_DATA || {};

    function initPageGuide() {
        const btnClose = document.getElementById('btn-close-page-guide');
        const backdrop = document.getElementById('page-guide-backdrop');
        const select = document.getElementById('page-guide-select');

        // Section header trigger buttons (delegated)
        document.addEventListener('click', (e) => {
            const trigger = e.target.closest('.btn-guide-trigger');
            if (trigger) {
                e.preventDefault();
                const secId = trigger.getAttribute('data-section') || window.currentSectionId || 'section-scenarios';
                openPageGuide(secId);
            }
        });

        // Close handlers
        if (btnClose) {
            btnClose.addEventListener('click', () => togglePageGuideDrawer(false));
        }
        if (backdrop) {
            backdrop.addEventListener('click', () => togglePageGuideDrawer(false));
        }

        // Escape key closes drawer
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && guideIsOpen) {
                togglePageGuideDrawer(false);
            }
        });

        // Selector dropdown in drawer header
        if (select) {
            select.addEventListener('change', (e) => {
                renderGuideContent(e.target.value);
            });
        }
    }

    function openPageGuide(sectionId) {
        // Fallback for aliases
        let targetId = sectionId;
        if (targetId === 'section-withholding' || targetId === 'section-transcripts') {
            targetId = 'section-compensation';
        }
        if (!GUIDE_DATA[targetId]) {
            targetId = 'section-scenarios';
        }

        const select = document.getElementById('page-guide-select');
        if (select) {
            select.value = targetId;
        }

        renderGuideContent(targetId);
        togglePageGuideDrawer(true);
    }

    function togglePageGuideDrawer(open) {
        const drawer = document.getElementById('page-guide-drawer');
        const backdrop = document.getElementById('page-guide-backdrop');
        if (!drawer || !backdrop) return;

        guideIsOpen = open;
        if (open) {
            backdrop.style.display = 'block';
            drawer.style.display = 'flex';
            // Force browser reflow before adding .open class for transition
            drawer.offsetHeight;
            drawer.classList.add('open');
            document.body.style.overflow = 'hidden';
        } else {
            drawer.classList.remove('open');
            setTimeout(() => {
                if (!guideIsOpen) {
                    drawer.style.display = 'none';
                    backdrop.style.display = 'none';
                    document.body.style.overflow = '';
                }
            }, 300);
        }
    }

    function renderGuideContent(sectionId) {
        const data = GUIDE_DATA[sectionId] || GUIDE_DATA['section-scenarios'];
        const contentEl = document.getElementById('page-guide-content');
        const headingEl = document.getElementById('page-guide-heading');
        const badgeEl = document.getElementById('page-guide-section-badge');

        if (!data) return;
        if (headingEl) headingEl.textContent = data.title;
        if (badgeEl) badgeEl.textContent = data.badge;

        if (!contentEl) return;

        let stepsHtml = '';
        if (data.steps && data.steps.length > 0) {
            stepsHtml = `<div class="guide-block">
                <div class="guide-block-header">
                    <span class="guide-block-icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"></path><rect x="8" y="2" width="8" height="4" rx="1" ry="1"></rect></svg></span>
                    <h4>How to Use This Tool</h4>
                </div>
                <ul class="guide-step-list">
                    ${data.steps.map((s, idx) => `<li class="guide-step-item"><span class="guide-step-num">${idx + 1}</span><div class="guide-step-text"><strong>${window.escapeHtml(s.title)}:</strong> ${s.text}</div></li>`).join('')}
                </ul>
            </div>`;
        }

        let calcsHtml = '';
        if (data.calculations && data.calculations.length > 0) {
            calcsHtml = `<div class="guide-block">
                <div class="guide-block-header">
                    <span class="guide-block-icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg></span>
                    <h4>Underlying Calculations &amp; Rules</h4>
                </div>
                <ul class="guide-rules-list">
                    ${data.calculations.map(c => `<li>${c}</li>`).join('')}
                </ul>
            </div>`;
        }

        contentEl.innerHTML = `
            <div class="guide-block">
                <div class="guide-block-header">
                    <span class="guide-block-icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><circle cx="12" cy="12" r="6"></circle><circle cx="12" cy="12" r="2"></circle></svg></span>
                    <h4>Purpose &amp; Objective</h4>
                </div>
                <p>${window.escapeHtml(data.purpose)}</p>
            </div>
            <div class="guide-block">
                <div class="guide-block-header">
                    <span class="guide-block-icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a4 4 0 0 0-4 4v1H6a2 2 0 0 0-2 2v3a2 2 0 0 0 2 2h1v4a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2v-4h1a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-2V6a4 4 0 0 0-4-4z"></path></svg></span>
                    <h4>Core Mental Model</h4>
                </div>
                <div class="${data.mentalModel.calloutClass}">
                    <strong style="display: block; margin-bottom: 6px; font-size: 0.875rem;">${data.mentalModel.title}</strong>
                    <div>${data.mentalModel.text}</div>
                </div>
            </div>
            ${stepsHtml}
            ${calcsHtml}
        `;
    }

    // Expose to window
    window.openPageGuide = openPageGuide;
    window.togglePageGuideDrawer = togglePageGuideDrawer;

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initPageGuide);
    } else {
        initPageGuide();
    }
})();
