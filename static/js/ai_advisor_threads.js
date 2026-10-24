/**
 * AI Financial Advisor - Conversation Threads & Antigravity Switcher
 * Handles saved threads, list rendering, search filtering, pinning, renaming, and deletion.
 */

async function fetchSavedConversations() {
    try {
        const resp = await fetch('/api/ai-advisor/conversations');
        const data = await resp.json();
        if (data.success) {
            savedConversations = data.conversations || [];
            updateThreadsBadge();
            renderConversationsList();
        }
    } catch (err) {
        console.warn('Could not fetch saved conversations:', err);
    }
}

function updateThreadsBadge() {
    const badge = document.getElementById('advisor-threads-count-badge');
    if (badge) {
        badge.textContent = savedConversations.length;
        badge.style.display = savedConversations.length > 0 ? 'inline-flex' : 'none';
    }
}

async function loadRecentConversationForTab(tabId) {
    try {
        const resp = await fetch(`/api/ai-advisor/conversations?page_section=${encodeURIComponent(tabId)}`);
        const data = await resp.json();
        if (data.success && data.conversations && data.conversations.length > 0) {
            const mostRecent = data.conversations[0];
            await openConversation(mostRecent.conversation_id);
        } else {
            startNewConversation();
        }
    } catch (err) {
        console.warn('Could not load recent conversation:', err);
    }
}

function toggleConversationsPanel(open) {
    const panel = document.getElementById('advisor-conversations-panel');
    if (!panel) return;
    conversationsPanelOpen = (open !== undefined) ? open : !conversationsPanelOpen;

    if (conversationsPanelOpen) {
        panel.style.display = 'flex';
        fetchSavedConversations().then(() => {
            const search = document.getElementById('advisor-conv-search');
            if (search) search.focus();
        });
    } else {
        panel.style.display = 'none';
    }
}

function updateThreadBarUI() {
    const titleEl = document.getElementById('advisor-thread-title-display');
    const pinIcon = document.getElementById('advisor-thread-pin-icon');
    const timeEl = document.getElementById('advisor-thread-time-display');
    const btnPin = document.getElementById('btn-pin-active-conversation');
    const btnRename = document.getElementById('btn-rename-thread');
    const btnDelete = document.getElementById('btn-delete-active-thread');

    if (titleEl) {
        titleEl.textContent = activeConversationTitle || 'New Conversation';
    }
    if (pinIcon) {
        pinIcon.style.display = activeConversationPinned ? 'inline' : 'none';
    }
    if (btnPin) {
        btnPin.innerHTML = activeConversationPinned
            ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg>'
            : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="10" r="3"></circle><path d="M12 2a8 8 0 0 0-8 8c0 5.25 8 12 8 12s8-6.75 8-12a8 8 0 0 0-8-8z"></path></svg>';
        btnPin.title = activeConversationPinned ? 'Unpin Conversation' : 'Pin / Bookmark Conversation';
    }
    if (btnRename) {
        btnRename.style.display = activeConversationId ? 'inline-flex' : 'none';
    }
    if (btnDelete) {
        btnDelete.style.display = activeConversationId ? 'inline-flex' : 'none';
    }
    if (timeEl) {
        if (activeConversationId && advisorChatHistory.length > 8) {
            timeEl.textContent = `${advisorChatHistory.length} msgs (8-turn window)`;
            timeEl.title = 'The most recent 8 messages and full household balance sheet are active in LLM context';
        } else if (activeConversationId) {
            timeEl.textContent = advisorChatHistory.length > 0 ? `${advisorChatHistory.length} msgs` : 'Saved';
            timeEl.title = 'Conversation saved';
        } else {
            timeEl.textContent = 'Current';
            timeEl.title = 'New unsaved thread';
        }
    }
}

function startNewConversation() {
    activeConversationId = null;
    activeConversationTitle = 'New Conversation';
    activeConversationPinned = false;
    advisorChatHistory = [];

    updateThreadBarUI();

    const container = document.getElementById('ai-advisor-messages');
    if (container) {
        container.innerHTML = `
            <div class="advisor-msg advisor-msg-bot" id="advisor-welcome-msg">
                <div class="advisor-msg-avatar"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg></div>
                <div class="advisor-msg-body" id="advisor-welcome-body">
                    ${getWelcomeMessageForTab(currentAdvisorTab)}
                </div>
            </div>
        `;
    }

    if (typeof toggleSuggestionsPanel === 'function') toggleSuggestionsPanel(false);
    if (typeof fetchAdvisorContext === 'function') fetchAdvisorContext();

    const textarea = document.getElementById('ai-advisor-input');
    if (textarea) {
        textarea.value = '';
        textarea.style.height = '';
        textarea.focus();
        if (typeof window.hvlSyncStandaloneViewport === 'function') {
            window.hvlSyncStandaloneViewport();
        }
    }
}

async function togglePinActiveConversation() {
    if (!activeConversationId) {
        if (typeof window.showModalAlert === 'function') {
            await window.showModalAlert('Send your first message in this conversation to save and pin it.', { title: 'Pin Conversation', type: 'info' });
        }
        return;
    }

    const newPinned = !activeConversationPinned;
    try {
        const resp = await fetch(`/api/ai-advisor/conversations/${encodeURIComponent(activeConversationId)}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_pinned: newPinned })
        });
        const data = await resp.json();
        if (resp.ok && data.success) {
            activeConversationPinned = newPinned;
            updateThreadBarUI();
            fetchSavedConversations();
        } else if (typeof window.showModalAlert === 'function') {
            await window.showModalAlert(data.error || 'Failed to update conversation pin.', { title: 'Error', type: 'error' });
        }
    } catch (err) {
        console.error('Failed to toggle pin:', err);
        if (typeof window.showModalAlert === 'function') {
            await window.showModalAlert(err.message || 'Failed to update conversation pin.', { title: 'Error', type: 'error' });
        }
    }
}

async function renameActiveConversation() {
    if (!activeConversationId) return;
    const currentTitle = activeConversationTitle || 'New Conversation';

    const newTitle = await (typeof window.showModalPrompt === 'function'
        ? window.showModalPrompt('Enter new title for this conversation (max 100 characters):', currentTitle, {
            title: 'Rename Conversation',
            placeholder: 'Conversation title...',
            maxLength: 100,
            confirmText: 'Save',
            confirmVariant: 'primary'
        })
        : prompt('Rename this conversation:', currentTitle));

    if (newTitle === null || newTitle === undefined) return;
    const cleaned = String(newTitle).replace(/[\x00-\x1f\x7f]/g, '').trim();
    if (!cleaned) {
        if (typeof window.showModalAlert === 'function') {
            await window.showModalAlert('Conversation title cannot be empty.', { title: 'Invalid Title', type: 'warning' });
        }
        return;
    }
    if (cleaned === currentTitle) return;

    try {
        const resp = await fetch(`/api/ai-advisor/conversations/${encodeURIComponent(activeConversationId)}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: cleaned })
        });
        const data = await resp.json();
        if (resp.ok && data.success) {
            activeConversationTitle = cleaned;
            updateThreadBarUI();
            fetchSavedConversations();
        } else if (typeof window.showModalAlert === 'function') {
            await window.showModalAlert(`Failed to rename: ${data.error || 'Unknown error'}`, { title: 'Rename Error', type: 'error' });
        }
    } catch (err) {
        console.error('Failed to rename conversation:', err);
        if (typeof window.showModalAlert === 'function') {
            await window.showModalAlert(`Network error: ${err.message}`, { title: 'Network Error', type: 'error' });
        }
    }
}

async function deleteActiveConversation() {
    if (!activeConversationId) return;

    const confirmed = typeof window.showModalConfirm === 'function'
        ? await window.showModalConfirm(`Delete conversation "${activeConversationTitle}" and all its messages? This action cannot be undone.`, {
            title: 'Delete Conversation',
            confirmText: 'Delete',
            confirmVariant: 'danger'
        })
        : confirm(`Delete conversation "${activeConversationTitle}" and all its messages?`);

    if (!confirmed) return;

    try {
        const resp = await fetch(`/api/ai-advisor/conversations/${encodeURIComponent(activeConversationId)}`, {
            method: 'DELETE'
        });
        const data = await resp.json();
        if (resp.ok && data.success) {
            startNewConversation();
            fetchSavedConversations();
        } else if (typeof window.showModalAlert === 'function') {
            await window.showModalAlert(`Failed to delete: ${data.error || 'Unknown error'}`, { title: 'Delete Error', type: 'error' });
        }
    } catch (err) {
        console.error('Failed to delete conversation:', err);
        if (typeof window.showModalAlert === 'function') {
            await window.showModalAlert(`Network error: ${err.message}`, { title: 'Network Error', type: 'error' });
        }
    }
}

function renderConversationsList() {
    const listContainer = document.getElementById('advisor-conversations-list');
    if (!listContainer) return;

    const searchInput = document.getElementById('advisor-conv-search');
    const searchTerm = (searchInput ? searchInput.value : '').trim().toLowerCase();

    let filtered = savedConversations.slice();

    if (activeConvFilter === 'current-page') {
        filtered = filtered.filter(c => c.page_section === currentAdvisorTab);
    } else if (activeConvFilter === 'pinned') {
        filtered = filtered.filter(c => Boolean(c.is_pinned));
    }

    if (searchTerm) {
        filtered = filtered.filter(c => 
            (c.title && c.title.toLowerCase().includes(searchTerm)) ||
            (c.last_message && c.last_message.toLowerCase().includes(searchTerm)) ||
            (c.page_section && c.page_section.toLowerCase().includes(searchTerm))
        );
    }

    if (filtered.length === 0) {
        listContainer.innerHTML = `
            <div style="padding: 24px 12px; text-align: center; color: var(--text-muted); font-size: 0.75rem;">
                <span style="display: block; margin-bottom: 6px;"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg></span>
                No conversations found.
            </div>
        `;
        return;
    }

    const tabPrettyNames = {
        'section-overview': 'Overview',
        'section-equity': 'Equity',
        'section-scenarios': 'Forecasting',
        'section-holdings': 'Investments',
        'section-arbitrage': 'Tax Arbitrage',
        'section-withholding': 'Withholding',
        'section-philanthropy': 'Philanthropy',
        'section-gifting': 'Gifting',
        'section-college': 'Education',
        'section-transcripts': 'Transcripts',
        'section-compensation': 'Compensation',
        'section-accounts': 'Accounts',
        'section-estate': 'Estate',
    };

    listContainer.innerHTML = filtered.map(c => {
        const isActive = c.conversation_id === activeConversationId;
        const pageLabel = tabPrettyNames[c.page_section] || 'General';
        const timeAgo = formatRelativeTime(c.updated_at);
        const pinBadge = c.is_pinned ? '• ' : '';

        return `
            <div class="advisor-conv-card ${isActive ? 'active' : ''}" data-conv-id="${c.conversation_id}">
                <div class="advisor-conv-card-title">
                    <span>${pinBadge}${_escapeAdvisorHtml(c.title)}</span>
                </div>
                ${c.last_message ? `<div class="advisor-conv-card-snippet">${_escapeAdvisorHtml(c.last_message)}</div>` : ''}
                <div class="advisor-conv-card-meta">
                    <span class="badge badge-blue" style="font-size: 0.625rem; padding: 1px 6px;">${pageLabel}</span>
                    <span>${timeAgo}</span>
                </div>
            </div>
        `;
    }).join('');

    listContainer.querySelectorAll('.advisor-conv-card').forEach(card => {
        card.onclick = (e) => {
            e.stopPropagation();
            const cid = card.getAttribute('data-conv-id');
            if (cid && typeof openConversation === 'function') openConversation(cid);
        };
    });
}

function formatRelativeTime(dateStr) {
    if (typeof window.formatRelativeChatTime === 'function') {
        return window.formatRelativeChatTime(dateStr);
    }
    if (!dateStr) return '';
    try {
        const d = new Date(dateStr.endsWith('Z') ? dateStr : dateStr + 'Z');
        const now = new Date();
        const diffSec = Math.floor((now - d) / 1000);
        if (diffSec < 60) return 'Just now';
        if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
        if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
        if (diffSec < 604800) return `${Math.floor(diffSec / 86400)}d ago`;
        return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    } catch (e) {
        return dateStr;
    }
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        fetchSavedConversations,
        updateThreadsBadge,
        loadRecentConversationForTab,
        toggleConversationsPanel,
        updateThreadBarUI,
        startNewConversation,
        togglePinActiveConversation,
        renameActiveConversation,
        deleteActiveConversation,
        renderConversationsList,
        formatRelativeTime
    });
}
