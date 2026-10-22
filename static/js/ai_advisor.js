/**
 * AI Financial Advisor Module - Main Controller
 * Modular architecture orchestrating UI drawer, thread persistence, and chat submission.
 */

var advisorIsOpen = false;
var advisorChatHistory = [];
var currentAdvisorTab = 'section-overview';
var activeConversationId = null;
var activeConversationTitle = 'New Conversation';
var activeConversationPinned = false;
var savedConversations = [];
var conversationsPanelOpen = false;
var activeConvFilter = 'all';

// Safe escape helper scoped to AI advisor module to prevent global const redeclaration collision
const _escapeAdvisorHtml = (str) => window.escapeHtml(str);
if (typeof window !== 'undefined') {
    window._escapeAdvisorHtml = _escapeAdvisorHtml;
}

async function openConversation(convId) {
    if (!convId) return;

    activeConversationId = convId;
    const container = document.getElementById('ai-advisor-messages');
    const prevContent = container ? container.innerHTML : '';
    if (container) {
        container.innerHTML = `
            <div style="padding: 40px 20px; text-align: center; color: var(--text-muted); font-size: 0.8125rem;">
                <div style="margin: 0 auto 12px auto; width: 26px; height: 26px; border: 3px solid var(--border-color); border-top-color: var(--accent-purple, #8B5CF6); border-radius: 50%; animation: spin 0.8s linear infinite;"></div>
                <span>Loading conversation...</span>
            </div>
        `;
    }

    try {
        const resp = await fetch(`/api/ai-advisor/conversations/${encodeURIComponent(convId)}`);
        const data = await resp.json();
        if (data.success && data.conversation) {
            const conv = data.conversation;
            activeConversationId = conv.conversation_id;
            activeConversationTitle = conv.title;
            activeConversationPinned = Boolean(conv.is_pinned);

            if (typeof updateThreadBarUI === 'function') updateThreadBarUI();

            if (container) {
                container.innerHTML = '';
                advisorChatHistory = [];

                if (conv.messages && conv.messages.length > 0) {
                    conv.messages.forEach(m => {
                        appendAdvisorMessage(m.role === 'user' ? 'user' : 'bot', m.content);
                        advisorChatHistory.push({ role: m.role, content: m.content });
                    });
                } else {
                    container.innerHTML = `
                        <div class="advisor-msg advisor-msg-bot" id="advisor-welcome-msg">
                            <div class="advisor-msg-avatar"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg></div>
                            <div class="advisor-msg-body" id="advisor-welcome-body">
                                ${getWelcomeMessageForTab(conv.page_section || currentAdvisorTab)}
                            </div>
                        </div>
                    `;
                }
                setTimeout(() => { container.scrollTop = container.scrollHeight; }, 50);
            }

            if (conv.page_section && conv.page_section !== currentAdvisorTab && typeof updateAdvisorContext === 'function') {
                updateAdvisorContext(conv.page_section);
            }

            if (typeof toggleConversationsPanel === 'function') toggleConversationsPanel(false);
            if (typeof renderConversationsList === 'function') renderConversationsList();
        } else {
            console.error('Failed to open conversation:', data.error);
            if (container) container.innerHTML = prevContent;
            if (typeof window.showModalAlert === 'function') {
                await window.showModalAlert(data.error || 'Conversation not found.', { title: 'Error Loading Conversation', type: 'error' });
            }
        }
    } catch (err) {
        console.error('Failed to open conversation:', err);
        if (container) container.innerHTML = prevContent;
        if (typeof window.showModalAlert === 'function') {
            await window.showModalAlert('Network error while opening conversation. Please try again.', { title: 'Network Error', type: 'error' });
        }
    }
}

function initAiAdvisor() {
    const btnOpen = document.getElementById('btn-open-ai-advisor');
    const btnClose = document.getElementById('btn-close-ai-advisor');
    const btnNew = document.getElementById('btn-new-ai-advisor');
    const btnToggleConv = document.getElementById('btn-toggle-conversations');
    const btnPin = document.getElementById('btn-pin-active-conversation');
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
        if (!advisorIsOpen) return;
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
    if (btnRename) btnRename.onclick = () => renameActiveConversation();
    if (btnDeleteActive) btnDeleteActive.onclick = () => deleteActiveConversation();
    if (btnClosePanel) btnClosePanel.onclick = () => toggleConversationsPanel(false);

    if (btnConvPanelNew) {
        btnConvPanelNew.onclick = () => {
            startNewConversation();
            toggleConversationsPanel(false);
        };
    }

    if (convSearchInput) convSearchInput.oninput = () => renderConversationsList();

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
            activeConvFilter = pill.getAttribute('data-filter') || 'all';
            renderConversationsList();
        };
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            if (conversationsPanelOpen) toggleConversationsPanel(false);
            else if (advisorIsOpen) toggleAiAdvisorDrawer(false);
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
window.openAdvisorConversation = openConversation;
window.refreshAdvisorConversations = fetchSavedConversations;
window.submitAiAdvisorMessage = submitAiAdvisorMessage;

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { initAiAdvisor(); });
} else {
    initAiAdvisor();
}
