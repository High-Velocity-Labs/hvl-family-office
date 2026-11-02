/**
 * Page Guide & Tool Documentation Controller
 * Factual, structured reference for each platform tool and section.
 * Explains purpose, core mental models (e.g. Parent & Child plans),
 * step-by-step usage, and underlying calculation engines.
 */

(function() {
    'use strict';

    let guideIsOpen = false;

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
                loadGuideContent(e.target.value);
            });
        }
    }

    async function openPageGuide(sectionId) {
        togglePageGuideDrawer(true);
        await loadGuideContent(sectionId || window.currentSectionId || 'section-scenarios');
    }

    function togglePageGuideDrawer(open) {
        const drawer = document.getElementById('page-guide-drawer');
        const backdrop = document.getElementById('page-guide-backdrop');
        if (!drawer || !backdrop) return;

        guideIsOpen = open;
        if (open) {
            backdrop.hidden = false;
            drawer.hidden = false;
            // Force browser reflow before adding .open class for transition
            drawer.offsetHeight;
            drawer.classList.add('open');
            document.body.classList.add('body-scroll-locked');
        } else {
            drawer.classList.remove('open');
            setTimeout(() => {
                if (!guideIsOpen) {
                    drawer.hidden = true;
                    backdrop.hidden = true;
                    document.body.classList.remove('body-scroll-locked');
                }
            }, 300);
        }
    }

    /** The server resolves aliases and unknown sections, renders the body, and swaps title and badge out of band. */
    async function loadGuideContent(sectionId) {
        const contentEl = document.getElementById('page-guide-content');
        if (!contentEl) return;
        await window.htmx.ajax('GET', `/fragments/guide/${encodeURIComponent(sectionId)}`, {
            target: contentEl,
            swap: 'innerHTML'
        });
        const select = document.getElementById('page-guide-select');
        const shown = contentEl.querySelector('[data-section]');
        if (select && shown) select.value = shown.getAttribute('data-section');
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
