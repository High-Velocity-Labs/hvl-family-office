/**
 * AI Financial Advisor - Drawer UI, Tab Context & Prompt Suggestions
 * Handles drawer visibility, active page context detection, policy rendering, and suggestions.
 */

const ADVISOR_TAB_GREETINGS = {
    'section-overview': { text: 'I see you\'re currently on the <strong>Overview &amp; Net Worth</strong> dashboard. I have your household balance sheet, equity grants (NSOs &amp; RSUs), and Investment Policy Statement (IPS) loaded and ready.', prompt: 'How can I help you optimize your portfolio, review equity options, or plan your wealth trajectory today?' },
    'section-equity': { text: 'I see you\'re currently analyzing <strong>Company Equity &amp; RSUs</strong>. I am tracking your vested/unvested grants, current 409A valuation, strike exercise capital requirements, and tax withholding considerations.', prompt: 'How can I help you model cashless exercises, AMT exposure, or RSU tax planning today?' },
    'section-scenarios': { text: 'I see you\'re currently in <strong>Forecasting &amp; Longevity</strong>. I have your Monte Carlo engine, spending rate assumptions, and retirement milestones ready to test.', prompt: 'How can I help you stress-test your plan, evaluate sequence of returns risk, or test market crisis replays today?' },
    'section-holdings': { text: 'I see you\'re currently examining <strong>Investments &amp; Asset Allocation</strong>. I am monitoring your portfolio against your Investment Policy Statement (IPS) anchor preset and rebalancing drift tolerance.', prompt: 'How can I help you review asset drift, index tracking, or plan tax-free rebalancing today?' },
    'section-arbitrage': { text: 'I see you\'re currently evaluating <strong>Multi-State Tax Arbitrage</strong>. Using Washington\'s 0% personal income tax baseline, I can help calculate net savings and domicile transition requirements.', prompt: 'How can I help you analyze tax savings across states today?' },
    'section-withholding': { text: 'I see you\'re currently reviewing <strong>Taxes &amp; Safe Harbor Withholding</strong>. I can help evaluate quarterly estimated tax obligations and safe harbor compliance.', prompt: 'How can I help you plan your quarterly tax payments today?' },
    'section-philanthropy': { text: 'I see you\'re currently modeling <strong>Philanthropic Gifting &amp; DAFs</strong>. I can assist with charitable deductions, bunching strategies, and appreciated asset donations.', prompt: 'How can I help you optimize your charitable impact today?' },
    'section-gifting': { text: 'I see you\'re currently viewing <strong>Family Gifting &amp; Annual Exclusion</strong>. I can help track your annual exclusion gifts per recipient and lifetime exemption shields.', prompt: 'How can I help you plan intergenerational wealth transfers today?' },
    'section-college': { text: 'I see you\'re currently planning <strong>Education Funding &amp; 529s</strong>. I can help project 4-year tuition trajectories and tax-free growth.', prompt: 'How can I help you optimize your education savings today?' },
    'section-transcripts': { text: 'I see you\'re currently analyzing <strong>IRS Transcripts &amp; Audit Logs</strong>. I can help verify W-2s, withholding records, and tax year reconciliations.', prompt: 'How can I help you review your IRS records today?' },
    'section-compensation': { text: 'I see you\'re currently reviewing <strong>Career Compensation</strong>. Using your base salary, bonus targets, and career history, I can help you model future earnings and total compensation.', prompt: 'How can I help you analyze career compensation today?' },
    'section-accounts': { text: 'I see you\'re currently viewing <strong>Accounts &amp; Assets</strong>. Using your synced account balances, institutions, and asset classifications, I can help you review liquidity and distribution.', prompt: 'How can I help you review your accounts and assets today?' },
    'section-estate': { text: 'I see you\'re currently reviewing <strong>Estate Planning &amp; Wealth Transfer</strong>. I can help model federal and Washington estate tax liabilities, exemption sunsets, and trust shielding.', prompt: 'How can I help you optimize your estate structure today?' }
};

function getWelcomeMessageForTab(tabId) {
    const info = ADVISOR_TAB_GREETINGS[tabId] || ADVISOR_TAB_GREETINGS['section-overview'];
    return `
        <p>Hello! I am your <strong>AI Financial Advisor</strong>. ${info.text}</p>
        <p style="margin-bottom: 0;">${info.prompt}</p>
        <div id="advisor-welcome-chips" class="advisor-welcome-chips-row" style="margin-top: 12px; display: flex; flex-wrap: wrap; gap: 6px;"></div>
    `;
}

function updateWelcomeMessageIfInitial(tabId) {
    if (!activeConversationId && advisorChatHistory.length === 0) {
        const welcomeBody = document.getElementById('advisor-welcome-body');
        if (welcomeBody) {
            welcomeBody.innerHTML = getWelcomeMessageForTab(tabId);
        }
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
    advisorIsOpen = (open !== undefined) ? open : !advisorIsOpen;
    const drawer = document.getElementById('ai-advisor-drawer');
    const backdrop = document.getElementById('ai-advisor-backdrop');

    if (advisorIsOpen) {
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
        } else if (!activeConversationId && typeof loadRecentConversationForTab === 'function') {
            loadRecentConversationForTab(currentAdvisorTab);
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
            if (drawer && !advisorIsOpen) drawer.style.display = 'none';
            if (backdrop && !advisorIsOpen) backdrop.style.display = 'none';
        }, 300);
    }
}

function toggleAiAdvisorExpand(forceExpand) {
    const drawer = document.getElementById('ai-advisor-drawer');
    const btn = document.getElementById('btn-expand-ai-advisor');
    const currentlyExpanded = drawer ? drawer.classList.contains('expanded') : Boolean(advisorIsExpanded);
    advisorIsExpanded = (forceExpand !== undefined) ? Boolean(forceExpand) : !currentlyExpanded;
    if (drawer) drawer.classList.toggle('expanded', advisorIsExpanded);
    if (btn) {
        const label = advisorIsExpanded ? 'Collapse Advisor Width' : 'Expand Advisor Width';
        btn.classList.toggle('active', advisorIsExpanded);
        btn.setAttribute('aria-pressed', advisorIsExpanded ? 'true' : 'false');
        btn.title = label;
        btn.setAttribute('aria-label', label);
    }
    try {
        window.localStorage.setItem('hvl_advisor_expanded', advisorIsExpanded ? '1' : '0');
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
    currentAdvisorTab = tabId || 'section-overview';
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
        pill.textContent = tabNameMap[currentAdvisorTab] || 'Overview';
    }

    updateWelcomeMessageIfInitial(currentAdvisorTab);
    if (advisorIsOpen) {
        fetchAdvisorContext();
    }
}

async function fetchAdvisorContext() {
    try {
        const resp = await fetch(`/api/ai-advisor/context?tab=${encodeURIComponent(currentAdvisorTab)}`);
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
            if (data.demo_mode) {
                applyDemoModeRestrictions(data.notice);
            } else {
                renderAdvisorSuggestionChips(data.suggestions || [], 'Recommended Questions');
            }
        }
    } catch (err) {
        console.warn('Could not fetch advisor context:', err);
    }
}

function applyDemoModeRestrictions(noticeText) {
    const textarea = document.getElementById('ai-advisor-input');
    const messagesContainer = document.getElementById('ai-advisor-messages');
    const drawerHeader = document.querySelector('.ai-advisor-header');

    if (textarea) {
        textarea.disabled = false;
        textarea.placeholder = 'Ask a question (Demo Mode: real answers disabled)...';
    }

    if (drawerHeader && !document.getElementById('advisor-demo-badge-bar')) {
        const badgeBar = document.createElement('div');
        badgeBar.id = 'advisor-demo-badge-bar';
        badgeBar.style.cssText = 'background: rgba(249, 115, 22, 0.15); border-bottom: 1px solid rgba(249, 115, 22, 0.3); padding: 6px 14px; font-size: 0.75rem; color: #FDBA74; display: flex; align-items: center; justify-content: space-between; font-weight: 600;';
        badgeBar.innerHTML = `
            <span>Demo Mode: AI Advisor Inactive</span>
            <span class="badge badge-orange" style="font-size: 0.625rem;">No Real Answers</span>
        `;
        drawerHeader.insertAdjacentElement('afterend', badgeBar);
    }

    if (messagesContainer && !document.getElementById('advisor-demo-guard-banner')) {
        const banner = document.createElement('div');
        banner.id = 'advisor-demo-guard-banner';
        banner.className = 'advisor-msg advisor-msg-bot';
        banner.innerHTML = `
            <div class="advisor-msg-avatar" style="background: rgba(249, 115, 22, 0.2); color: #F97316; border: 1px solid rgba(249, 115, 22, 0.4);"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg></div>
            <div class="advisor-msg-body" style="border: 1px solid rgba(249, 115, 22, 0.3); background: rgba(249, 115, 22, 0.08);">
                <p style="font-weight: 700; color: #FDBA74; margin-bottom: 4px;">Demo Sandbox Mode Active</p>
                <p style="margin-bottom: 0; font-size: 0.8125rem; color: var(--text-secondary); line-height: 1.45;">
                    ${_escapeAdvisorHtml(noticeText || 'To protect API quotas, the AI Advisor is in demo mode and will not give you real financial answers. Sign in with an authorized household account for personalized guidance.')}
                </p>
            </div>
        `;
        messagesContainer.appendChild(banner);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
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
        const tierLabel = document.getElementById('advisor-tier-label');
        const byoLink = document.getElementById('link-advisor-byo-key');
        if (tierBar) {
            if (lim.is_local_mode || lim.tier === 'local') {
                tierBar.style.display = 'none';
            } else {
                tierBar.style.display = 'flex';
                if (lim.tier === 'byo') {
                    if (tierLabel) tierLabel.innerHTML = `Quota Tier: <strong style="color: var(--status-green);">BYO Key Active</strong> (${_escapeAdvisorHtml(lim.rate_limit_label || '30/min · 300/hr')})`;
                    if (byoLink) byoLink.textContent = 'Manage Key →';
                } else {
                    if (tierLabel) tierLabel.innerHTML = `Quota Tier: <strong>Shared Key</strong> (${_escapeAdvisorHtml(lim.rate_limit_label || '5/min · 30/hr')})`;
                    if (byoLink) byoLink.textContent = 'BYO Key for higher limits →';
                }
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
    const container = document.getElementById('advisor-suggestion-chips');
    const welcomeChips = document.getElementById('advisor-welcome-chips');
    const labelEl = document.getElementById('advisor-suggestions-label');

    if (labelEl && labelText) labelEl.textContent = labelText;

    if (!suggestions || suggestions.length === 0) {
        if (container) container.innerHTML = '<span class="text-muted" style="font-size: 0.75rem;">No suggested prompts.</span>';
        if (welcomeChips) welcomeChips.innerHTML = '';
        return;
    }

    const html = suggestions.map(q => 
        `<button type="button" class="advisor-chip-btn">${_escapeAdvisorHtml(q)}</button>`
    ).join('');

    const bindChipClicks = (parentEl) => {
        if (!parentEl) return;
        parentEl.innerHTML = html;
        parentEl.querySelectorAll('.advisor-chip-btn').forEach(btn => {
            btn.onclick = () => {
                const promptText = btn.textContent;
                const textarea = document.getElementById('ai-advisor-input');
                if (textarea) {
                    textarea.value = promptText;
                    if (typeof submitAiAdvisorMessage === 'function') submitAiAdvisorMessage();
                }
            };
        });
    };

    bindChipClicks(container);
    bindChipClicks(welcomeChips);
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        ADVISOR_TAB_GREETINGS,
        getWelcomeMessageForTab,
        updateWelcomeMessageIfInitial,
        syncAdvisorTabFromLocation,
        toggleAiAdvisorDrawer,
        toggleAiAdvisorExpand,
        toggleSuggestionsPanel,
        updateAdvisorContext,
        fetchAdvisorContext,
        applyDemoModeRestrictions,
        renderAdvisorPolicyInfo,
        renderAdvisorSuggestionChips
    });
}
