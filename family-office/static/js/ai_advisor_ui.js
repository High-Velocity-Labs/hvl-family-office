/**
 * AI Financial Advisor - Drawer UI, Tab Context & Prompt Suggestions
 * Handles drawer visibility, active page context detection, policy rendering, and suggestions.
 */

function updateWelcomeMessageIfInitial(tabId) {
    if (!AdvisorState.conversationId && AdvisorState.chatHistory.length === 0) {
        AdvisorFragments.refreshWelcomeBody(tabId);
    }
}

function syncAdvisorTabFromLocation() {
    if (typeof window !== 'undefined' && window.currentSectionId && window.currentSectionId !== 'section-overview') {
        updateAdvisorContext(window.currentSectionId);
        return;
    }
    const activeNav = document.querySelector('.nav-link.active[data-target]');
    if (activeNav) {
        const target = activeNav.getAttribute('data-target');
        if (target) {
            updateAdvisorContext(target);
            return;
        }
    }
    const mobileSelect = document.getElementById('mobile-nav-select');
    if (mobileSelect && mobileSelect.value && mobileSelect.value !== 'section-overview') {
        updateAdvisorContext(mobileSelect.value);
        return;
    }

    const path = (window.location.pathname || '').toLowerCase().replace(/\/+$/, '') || '/';
    if (window.PATH_TO_SECTION && window.PATH_TO_SECTION[path]) {
        updateAdvisorContext(window.PATH_TO_SECTION[path]);
        return;
    }

    try {
        const params = new URLSearchParams(window.location.search);
        const tabParam = (params.get('tab') || params.get('section') || '').toLowerCase().replace(/^section-/, '');
        if (tabParam && window.PATH_TO_SECTION && window.PATH_TO_SECTION['/' + tabParam]) {
            updateAdvisorContext(window.PATH_TO_SECTION['/' + tabParam]);
            return;
        }
    } catch (e) {}

    const hash = (window.location.hash || '').toLowerCase();
    if (hash && window.HASH_TO_SECTION && window.HASH_TO_SECTION[hash]) {
        updateAdvisorContext(window.HASH_TO_SECTION[hash]);
        return;
    }

    updateAdvisorContext('section-overview');
}

function toggleAiAdvisorDrawer(open, targetConvId) {
    const wantOpen = (open !== undefined) ? open : !AdvisorState.isOpen;
    if (!wantOpen && AdvisorState.drawer === 'closed') return;
    AdvisorState.setDrawer(wantOpen ? 'open' : 'closing');
    const drawer = document.getElementById('ai-advisor-drawer');
    const backdrop = document.getElementById('ai-advisor-backdrop');

    if (wantOpen) {
        syncAdvisorTabFromLocation();
        if (drawer) {
            drawer.style.display = 'flex';
            setTimeout(() => drawer.classList.add('open'), 10);
        }
        if (backdrop) {
            backdrop.style.display = 'block';
            setTimeout(() => { backdrop.style.opacity = '1'; }, 10);
        }
        fetchAdvisorContext();
        if (typeof fetchSavedConversations === 'function') fetchSavedConversations();

        if (targetConvId && typeof openConversation === 'function') {
            openConversation(targetConvId);
        } else if (!AdvisorState.conversationId && typeof loadRecentConversationForTab === 'function') {
            loadRecentConversationForTab(AdvisorState.tab);
        }

        setTimeout(() => {
            const textarea = document.getElementById('ai-advisor-input');
            if (textarea) {
                textarea.focus();
                if (typeof window.hvlSyncStandaloneViewport === 'function') {
                    window.hvlSyncStandaloneViewport();
                }
            }
        }, 150);
    } else {
        if (drawer) drawer.classList.remove('open');
        if (backdrop) backdrop.style.opacity = '0';
        if (typeof toggleConversationsPanel === 'function') toggleConversationsPanel(false);
        setTimeout(() => {
            if (AdvisorState.drawer !== 'closing') return;
            AdvisorState.setDrawer('closed');
            if (drawer) drawer.style.display = 'none';
            if (backdrop) backdrop.style.display = 'none';
        }, 300);
    }
}

function toggleAiAdvisorExpand(forceMode) {
    const drawer = document.getElementById('ai-advisor-drawer');
    const btn = document.getElementById('btn-expand-ai-advisor');
    const badge = document.getElementById('advisor-expand-label');
    const modeMap = {
        true: 'half', false: 'default',
        '1': 'half', '2': 'full', '0': 'default',
        half: 'half', full: 'full', default: 'default'
    };
    const next = (forceMode !== undefined && modeMap[forceMode]) ? modeMap[forceMode] : AdvisorState.nextSize();
    AdvisorState.setSize(next);
    if (drawer) {
        drawer.classList.toggle('expanded', AdvisorState.isExpanded);
        drawer.classList.toggle('expanded-half', next === 'half');
        drawer.classList.toggle('expanded-full', next === 'full');
        drawer.setAttribute('data-size', next);
    }
    if (btn) {
        const titles = {
            default: 'Expand Advisor (Half Screen)',
            half: 'Expand Advisor (Full Screen)',
            full: 'Restore Default Advisor Width'
        };
        btn.classList.toggle('active', AdvisorState.isExpanded);
        btn.setAttribute('aria-pressed', AdvisorState.isExpanded ? 'true' : 'false');
        btn.setAttribute('data-size', next);
        btn.title = titles[next];
        btn.setAttribute('aria-label', titles[next]);
    }
    if (badge) {
        badge.textContent = next === 'half' ? '50%' : (next === 'full' ? '100%' : '');
        badge.style.display = AdvisorState.isExpanded ? 'inline' : 'none';
    }
    try {
        window.localStorage.setItem('hvl_advisor_expanded', next);
    } catch (e) {}
}

function toggleSuggestionsPanel(forceOpen) {
    const chipsContainer = document.getElementById('advisor-suggestion-chips');
    const arrow = document.getElementById('advisor-suggestions-arrow');
    const toggleBtn = document.getElementById('btn-toggle-suggestions');
    if (!chipsContainer) return;

    const isCurrentlyOpen = chipsContainer.style.display !== 'none';
    const nextOpen = (forceOpen !== undefined) ? forceOpen : !isCurrentlyOpen;

    if (nextOpen) {
        chipsContainer.style.display = 'flex';
        if (arrow) arrow.classList.add('expanded');
        if (toggleBtn) toggleBtn.setAttribute('aria-expanded', 'true');
    } else {
        chipsContainer.style.display = 'none';
        if (arrow) arrow.classList.remove('expanded');
        if (toggleBtn) toggleBtn.setAttribute('aria-expanded', 'false');
    }
}

function updateAdvisorContext(tabId) {
    AdvisorState.tab = tabId || 'section-overview';
    const tabNameMap = {
        'section-overview': 'Overview & Net Worth', 'section-equity': 'Company Equity & RSUs',
        'section-scenarios': 'Forecasting & Longevity', 'section-holdings': 'Investments & IPS',
        'section-arbitrage': 'Multi-State Tax Arbitrage', 'section-withholding': 'Taxes & Withholding',
        'section-philanthropy': 'Philanthropy', 'section-gifting': 'Family Gifting',
        'section-college': 'Education Funding', 'section-transcripts': 'IRS Transcripts',
        'section-compensation': 'Career Compensation', 'section-accounts': 'Accounts & Assets',
        'section-estate': 'Estate Planning'
    };

    const pill = document.getElementById('advisor-context-pill');
    if (pill) {
        pill.textContent = tabNameMap[AdvisorState.tab] || 'Overview';
    }

    updateWelcomeMessageIfInitial(AdvisorState.tab);
    if (AdvisorState.isOpen) {
        fetchAdvisorContext();
    }
}

async function fetchAdvisorContext() {
    try {
        const resp = await fetch(`/api/ai-advisor/context?tab=${encodeURIComponent(AdvisorState.tab)}`);
        const data = await resp.json();
        if (data.success) {
            const modelSelect = document.getElementById('advisor-model-select');
            if (modelSelect && data.preferred_model_tier) {
                try {
                    const localTier = window.localStorage.getItem('hvl_gemini_model_tier');
                    if (!localTier && ['lite', 'flash', 'pro', 'auto'].includes(data.preferred_model_tier)) {
                        modelSelect.value = data.preferred_model_tier;
                    }
                } catch (e) {}
            }
            renderAdvisorPolicyInfo(data);
            if (data.demo_mode && typeof applyDemoModeRestrictions === 'function') {
                applyDemoModeRestrictions(data.notice);
            } else {
                renderAdvisorSuggestionChips(data.suggestions || [], 'Recommended Questions');
            }
        }
    } catch (err) {
        console.warn('Could not fetch advisor context:', err);
    }
}

function renderAdvisorPolicyInfo(data) {
    const famEl = document.getElementById('advisor-family-name');
    if (famEl && data.family_name) famEl.textContent = data.family_name;

    const anchorEl = document.getElementById('advisor-policy-anchor');
    const rationaleBox = document.getElementById('advisor-policy-rationale-box');
    const presetNames = {
        'core_satellite': 'Core & Satellite', 'boglehead_80_20': 'Boglehead 80/20',
        'boglehead_90_10': 'Boglehead 90/10', 'boglehead_60_40': 'Boglehead 60/40'
    };

    if (anchorEl) {
        const rawPreset = data.policy_anchor || 'core_satellite';
        anchorEl.textContent = presetNames[rawPreset] || rawPreset.replace('_', ' ');
    }

    if (rationaleBox) {
        if (data.deviations_rationale && data.deviations_rationale.trim()) {
            rationaleBox.textContent = `Deviation note: "${data.deviations_rationale.trim()}"`;
            rationaleBox.style.display = 'block';
        } else {
            rationaleBox.style.display = 'none';
        }
    }

    if (data.ai_limits) {
        const lim = data.ai_limits;
        const maxChars = parseInt(lim.max_input_chars, 10) || 2000;
        const textarea = document.getElementById('ai-advisor-input');
        const charCounter = document.getElementById('advisor-char-counter');
        if (textarea) {
            textarea.maxLength = maxChars;
            if (charCounter) charCounter.textContent = `${textarea.value.length} / ${maxChars}`;
        }
        const tierBar = document.getElementById('advisor-tier-bar');
        const byoLink = document.getElementById('link-advisor-byo-key');
        if (tierBar) {
            if (lim.is_local_mode || lim.tier === 'local') {
                tierBar.style.display = 'none';
            } else {
                tierBar.style.display = 'flex';
                AdvisorFragments.renderQuota(lim.tier, lim.rate_limit_label || '');
            }
        }
        if (byoLink && !byoLink._bound) {
            byoLink._bound = true;
            byoLink.onclick = () => {
                toggleAiAdvisorDrawer(false);
                if (typeof window.openSettingsModal === 'function') {
                    window.openSettingsModal();
                    const tabInt = document.getElementById('tab-btn-integrations');
                    if (tabInt) tabInt.click();
                }
            };
        }
    }
}

function renderAdvisorSuggestionChips(suggestions, labelText) {
    const labelEl = document.getElementById('advisor-suggestions-label');

    if (labelEl && labelText) labelEl.textContent = labelText;

    AdvisorFragments.renderChips(suggestions || []);
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        updateWelcomeMessageIfInitial,
        syncAdvisorTabFromLocation,
        toggleAiAdvisorDrawer,
        toggleAiAdvisorExpand,
        toggleSuggestionsPanel,
        updateAdvisorContext,
        fetchAdvisorContext,
        renderAdvisorPolicyInfo,
        renderAdvisorSuggestionChips
    });
}
