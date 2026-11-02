/**
 * AI Financial Advisor - Conversation Threads & Antigravity Switcher
 * Handles saved threads (server-rendered list), pinning, renaming, and deletion.
 */

function fetchSavedConversations() {
    return renderConversationsList();
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
    AdvisorState.setPanel(((open !== undefined) ? open : !AdvisorState.isPanelVisible) ? 'visible' : 'hidden');

    if (AdvisorState.isPanelVisible) {
        panel.hidden = false;
        fetchSavedConversations().then(() => {
            const search = document.getElementById('advisor-conv-search');
            if (search) search.focus();
        });
    } else {
        panel.hidden = true;
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
        titleEl.textContent = AdvisorState.conversationTitle || 'New Conversation';
    }
    if (pinIcon) {
        pinIcon.hidden = !AdvisorState.conversationPinned;
    }
    if (btnPin) {
        const pinOn = btnPin.querySelector('.advisor-pin-on');
        const pinOff = btnPin.querySelector('.advisor-pin-off');
        if (pinOn) pinOn.hidden = !AdvisorState.conversationPinned;
        if (pinOff) pinOff.hidden = AdvisorState.conversationPinned;
        btnPin.title = AdvisorState.conversationPinned ? 'Unpin Conversation' : 'Pin / Bookmark Conversation';
    }
    if (btnRename) {
        btnRename.hidden = !AdvisorState.conversationId;
    }
    if (btnDelete) {
        btnDelete.hidden = !AdvisorState.conversationId;
    }
    if (timeEl) {
        if (AdvisorState.conversationId && AdvisorState.chatHistory.length > 8) {
            timeEl.textContent = `${AdvisorState.chatHistory.length} msgs (8-turn window)`;
            timeEl.title = 'The most recent 8 messages and full household balance sheet are active in LLM context';
        } else if (AdvisorState.conversationId) {
            const msgCount = AdvisorState.chatHistory.length;
            timeEl.textContent = msgCount > 0 ? `${msgCount} msgs` : 'Saved';
            timeEl.title = 'Conversation saved';
        } else {
            timeEl.textContent = 'Current';
            timeEl.title = 'New unsaved thread';
        }
    }
}

function startNewConversation() {
    AdvisorState.conversationId = null;
    AdvisorState.conversationTitle = 'New Conversation';
    AdvisorState.conversationPinned = false;
    AdvisorState.chatHistory = [];

    updateThreadBarUI();

    AdvisorFragments.showWelcome(AdvisorState.tab);

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
    if (!AdvisorState.conversationId) {
        if (typeof window.showModalAlert === 'function') {
            await window.showModalAlert('Send your first message in this conversation to save and pin it.', { title: 'Pin Conversation', type: 'info' });
        }
        return;
    }

    const newPinned = !AdvisorState.conversationPinned;
    try {
        const resp = await fetch(`/api/ai-advisor/conversations/${encodeURIComponent(AdvisorState.conversationId)}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_pinned: newPinned })
        });
        const data = await resp.json();
        if (resp.ok && data.success) {
            AdvisorState.conversationPinned = newPinned;
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
    if (!AdvisorState.conversationId) return;
    const currentTitle = AdvisorState.conversationTitle || 'New Conversation';

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
        const resp = await fetch(`/api/ai-advisor/conversations/${encodeURIComponent(AdvisorState.conversationId)}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: cleaned })
        });
        const data = await resp.json();
        if (resp.ok && data.success) {
            AdvisorState.conversationTitle = cleaned;
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
    if (!AdvisorState.conversationId) return;

    const confirmed = typeof window.showModalConfirm === 'function'
        ? await window.showModalConfirm(
            `Delete conversation "${AdvisorState.conversationTitle}" and all its messages? `
            + 'This action cannot be undone.',
            { title: 'Delete Conversation', confirmText: 'Delete', confirmVariant: 'danger' },
        )
        : confirm(`Delete conversation "${AdvisorState.conversationTitle}" and all its messages?`);

    if (!confirmed) return;

    try {
        const resp = await fetch(`/api/ai-advisor/conversations/${encodeURIComponent(AdvisorState.conversationId)}`, {
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

/** Re-renders the thread cards on the server for the active filter, search term, page and open thread. */
function renderConversationsList() {
    const searchInput = document.getElementById('advisor-conv-search');
    return AdvisorFragments.refreshThreadList(
        AdvisorState.convFilter,
        (searchInput ? searchInput.value : '').trim(),
        AdvisorState.tab,
        AdvisorState.conversationId
    );
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        fetchSavedConversations,
        loadRecentConversationForTab,
        toggleConversationsPanel,
        updateThreadBarUI,
        startNewConversation,
        togglePinActiveConversation,
        renameActiveConversation,
        deleteActiveConversation,
        renderConversationsList
    });
}
