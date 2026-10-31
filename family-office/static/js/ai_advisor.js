/**
 * AI Financial Advisor Module - Main Controller
 * Modular architecture orchestrating UI drawer, thread persistence, and chat submission.
 */


async function applyDemoModeRestrictions(noticeText) {
    const textarea = document.getElementById('ai-advisor-input');
    const messagesContainer = document.getElementById('ai-advisor-messages');

    if (textarea) {
        textarea.disabled = false;
        textarea.placeholder = 'Ask a question (Demo Mode: real answers disabled)...';
    }

    await AdvisorFragments.showDemoNotice(noticeText);
    if (messagesContainer) messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

/** Loads a saved transcript from the server-rendered fragment and adopts its state (title, pin, history). */
async function openConversation(convId) {
    if (!convId) return;

    const state = await AdvisorFragments.loadConversation(convId, AdvisorState.tab);
    if (!state) {
        if (typeof window.showModalAlert === 'function') {
            await window.showModalAlert('Conversation not found or could not be loaded.', {
                title: 'Error Loading Conversation',
                type: 'error'
            });
        }
        return;
    }

    AdvisorState.conversationId = state.dataset.convId;
    AdvisorState.conversationTitle = state.dataset.title;
    AdvisorState.conversationPinned = state.dataset.pinned === '1';
    AdvisorState.chatHistory = JSON.parse(state.dataset.history || '[]');
    updateThreadBarUI();

    const container = document.getElementById('ai-advisor-messages');
    if (container) setTimeout(() => { container.scrollTop = container.scrollHeight; }, 50);

    const section = state.dataset.pageSection;
    if (section && section !== AdvisorState.tab) updateAdvisorContext(section);

    toggleConversationsPanel(false);
    renderConversationsList();
}

function initAiAdvisor() {
    const btnOpen = document.getElementById('btn-open-ai-advisor');
    const btnClose = document.getElementById('btn-close-ai-advisor');
    const btnNew = document.getElementById('btn-new-ai-advisor');
    const btnToggleConv = document.getElementById('btn-toggle-conversations');
    const btnPin = document.getElementById('btn-pin-active-conversation');
    const btnExpand = document.getElementById('btn-expand-ai-advisor');
    const btnRename = document.getElementById('btn-rename-thread');
    const btnDeleteActive = document.getElementById('btn-delete-active-thread');
    const btnClosePanel = document.getElementById('btn-close-conversations-panel');
    const btnConvPanelNew = document.getElementById('btn-conv-panel-new');
    const convSearchInput = document.getElementById('advisor-conv-search');
    const linkSettingsHistory = document.getElementById('link-open-settings-history');
    const backdrop = document.getElementById('ai-advisor-backdrop');
    const form = document.getElementById('form-ai-advisor');
    const textarea = document.getElementById('ai-advisor-input');
    const charCounter = document.getElementById('advisor-char-counter');
    const btnSidebar = document.getElementById('btn-sidebar-advisor');
    const mobilePullBar = document.getElementById('advisor-mobile-pull-bar');
    const btnToggleSuggestions = document.getElementById('btn-toggle-suggestions');
    const modelSelect = document.getElementById('advisor-model-select');

    if (modelSelect) {
        try {
            const savedTier = window.localStorage.getItem('hvl_gemini_model_tier');
            if (savedTier && ['lite', 'flash', 'pro', 'auto'].includes(savedTier)) {
                modelSelect.value = savedTier;
            }
        } catch (e) {}
        modelSelect.addEventListener('change', () => {
            try {
                window.localStorage.setItem('hvl_gemini_model_tier', modelSelect.value);
            } catch (e) {}
        });
    }

    if (btnOpen) {
        btnOpen.onclick = (e) => {
            e.preventDefault();
            toggleAiAdvisorDrawer(true);
        };
    }
    if (btnSidebar) {
        btnSidebar.onclick = (e) => {
            e.preventDefault();
            toggleAiAdvisorDrawer(true);
        };
    }
    if (btnClose) btnClose.onclick = () => toggleAiAdvisorDrawer(false);
    if (mobilePullBar) mobilePullBar.onclick = () => toggleAiAdvisorDrawer(false);
    if (backdrop) backdrop.onclick = () => toggleAiAdvisorDrawer(false);

    document.addEventListener('pointerdown', (e) => {
        if (!AdvisorState.isOpen) return;
        const drawer = document.getElementById('ai-advisor-drawer');
        const bOpen = document.getElementById('btn-open-ai-advisor');
        const bSidebar = document.getElementById('btn-sidebar-advisor');
        if (drawer && !drawer.contains(e.target) && (!bOpen || !bOpen.contains(e.target)) && (!bSidebar || !bSidebar.contains(e.target))) {
            toggleAiAdvisorDrawer(false);
        }
    });

    if (btnToggleSuggestions) btnToggleSuggestions.onclick = () => toggleSuggestionsPanel();
    if (btnNew) btnNew.onclick = () => startNewConversation();
    if (btnToggleConv) btnToggleConv.onclick = () => toggleConversationsPanel();
    if (btnPin) btnPin.onclick = () => togglePinActiveConversation();
    if (btnExpand) btnExpand.onclick = () => toggleAiAdvisorExpand();
    try {
        const savedExpand = window.localStorage.getItem('hvl_advisor_expanded');
        if (savedExpand && typeof toggleAiAdvisorExpand === 'function') {
            toggleAiAdvisorExpand(savedExpand);
        }
    } catch (e) {}
    if (btnRename) btnRename.onclick = () => renameActiveConversation();
    if (btnDeleteActive) btnDeleteActive.onclick = () => deleteActiveConversation();
    if (btnClosePanel) btnClosePanel.onclick = () => toggleConversationsPanel(false);

    if (btnConvPanelNew) {
        btnConvPanelNew.onclick = () => {
            startNewConversation();
            toggleConversationsPanel(false);
        };
    }

    if (convSearchInput) {
        let searchTimer = null;
        convSearchInput.oninput = () => {
            clearTimeout(searchTimer);
            searchTimer = setTimeout(renderConversationsList, 150);
        };
    }

    const convList = document.getElementById('advisor-conversations-list');
    if (convList) {
        convList.addEventListener('click', (e) => {
            const card = e.target.closest('.advisor-conv-card');
            if (!card) return;
            e.stopPropagation();
            openConversation(card.getAttribute('data-conv-id'));
        });
    }

    const drawerEl = document.getElementById('ai-advisor-drawer');
    if (drawerEl) {
        drawerEl.addEventListener('click', (e) => {
            const chip = e.target.closest('.advisor-chip-btn');
            if (!chip || !textarea) return;
            textarea.value = chip.textContent;
            submitAiAdvisorMessage();
        });
    }

    if (linkSettingsHistory) {
        linkSettingsHistory.onclick = () => {
            toggleAiAdvisorDrawer(false);
            if (typeof window.openSettingsModal === 'function') {
                window.openSettingsModal();
                const tabAdvisor = document.getElementById('tab-btn-advisor-history');
                if (tabAdvisor) tabAdvisor.click();
            }
        };
    }

    document.querySelectorAll('.advisor-conv-filter-pill').forEach(pill => {
        pill.onclick = () => {
            document.querySelectorAll('.advisor-conv-filter-pill').forEach(p => p.classList.remove('active'));
            pill.classList.add('active');
            AdvisorState.convFilter = pill.getAttribute('data-filter') || 'all';
            renderConversationsList();
        };
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            if (AdvisorState.isPanelVisible) toggleConversationsPanel(false);
            else if (AdvisorState.isOpen) toggleAiAdvisorDrawer(false);
        }
    });

    if (form && textarea) {
        form.onsubmit = (e) => {
            e.preventDefault();
            submitAiAdvisorMessage();
        };
        textarea.onkeydown = (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                submitAiAdvisorMessage();
            }
        };
        textarea.oninput = () => {
            textarea.style.height = 'auto';
            textarea.style.height = Math.min(textarea.scrollHeight, 140) + 'px';
            if (charCounter) {
                const maxLen = textarea.maxLength > 0 ? textarea.maxLength : 2000;
                charCounter.textContent = `${textarea.value.length} / ${maxLen}`;
            }
        };
    }

    window.addEventListener('hashchange', () => { syncAdvisorTabFromLocation(); });
    window.addEventListener('popstate', () => { syncAdvisorTabFromLocation(); });

    document.querySelectorAll('.nav-link, .sidebar-brand a').forEach(link => {
        link.addEventListener('click', () => {
            const target = link.getAttribute('data-target') || 'section-overview';
            updateAdvisorContext(target);
        });
    });

    const mobileSelect = document.getElementById('mobile-nav-select');
    if (mobileSelect) {
        mobileSelect.addEventListener('change', () => {
            if (mobileSelect.value) updateAdvisorContext(mobileSelect.value);
        });
    }

    syncAdvisorTabFromLocation();
    if (typeof fetchSavedConversations === 'function') fetchSavedConversations();
}

window.initAiAdvisor = initAiAdvisor;
window.toggleAiAdvisorDrawer = toggleAiAdvisorDrawer;
window.toggleAiAdvisorExpand = toggleAiAdvisorExpand;
window.applyDemoModeRestrictions = applyDemoModeRestrictions;
window.openAdvisorConversation = openConversation;
window.refreshAdvisorConversations = fetchSavedConversations;
window.submitAiAdvisorMessage = submitAiAdvisorMessage;

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { initAiAdvisor(); });
} else {
    initAiAdvisor();
}
