/**
 * Settings & Tenant Management - AI Advisor History Module
 * Handles searching, filtering, bulk deletion, and pinning of saved AI conversations within Settings.
 */

async function loadSettingsAdvisorConversations() {
    const tbody = document.getElementById('settings-advisor-conversations-tbody');
    const badge = document.getElementById('settings-advisor-total-badge');
    const searchInput = document.getElementById('settings-advisor-search');
    const pageSelect = document.getElementById('settings-advisor-filter-page');
    const pinnedBtn = document.getElementById('btn-settings-filter-pinned');

    const rawSearchVal = (searchInput ? searchInput.value : '').trim();
    const searchVal = (rawSearchVal.startsWith('{{') && rawSearchVal.endsWith('}}')) ? '' : rawSearchVal;
    const pageVal = (pageSelect ? pageSelect.value : '').trim();
    const isPinnedOnly = Boolean(pinnedBtn && pinnedBtn.classList.contains('active'));

    if (tbody) {
        const rows = Array.from(tbody.querySelectorAll('.settings-conv-row'));
        if (rows.length > 0) {
            let visibleCount = 0;
            const q = searchVal.toLowerCase();
            rows.forEach(row => {
                const rowSearch = (row.getAttribute('data-search') || row.textContent || '').toLowerCase();
                const rowPage = row.getAttribute('data-page') || '';
                const pinBtn = row.querySelector('.btn-toggle-pin-conv');
                const rowPinned = (row.getAttribute('data-pinned') || (pinBtn && pinBtn.getAttribute('data-pinned')) || '0') === '1';

                const matchSearch = !q || rowSearch.includes(q);
                const matchPage = !pageVal || rowPage === pageVal;
                const matchPin = !isPinnedOnly || rowPinned;
                const show = matchSearch && matchPage && matchPin;
                row.style.display = show ? '' : 'none';
                if (show) visibleCount += 1;
            });
            if (badge) {
                badge.textContent = `${visibleCount} thread${visibleCount === 1 ? '' : 's'}`;
            }
        }
    }

    if (typeof morphSettingsModal === 'function') {
        await morphSettingsModal({
            tab: 'advisor-history',
            adv_search: searchVal,
            adv_page: pageVal,
            adv_pinned_only: isPinnedOnly ? '1' : '',
        });
    }

    const selectAll = document.getElementById('settings-conv-select-all');
    if (selectAll) selectAll.checked = false;
    updateSelectedConversationCount();
}

function bindSettingsAdvisorConversationsTable() {
    const tbody = document.getElementById('settings-advisor-conversations-tbody');
    if (!tbody) return;

    tbody.querySelectorAll('.settings-conv-checkbox').forEach(cb => {
        cb.onchange = () => updateSelectedConversationCount();
    });

    tbody.querySelectorAll('.btn-toggle-pin-conv').forEach(btn => {
        btn.onclick = async (e) => {
            e.stopPropagation();
            const cid = btn.getAttribute('data-conv-id');
            const currentPin = btn.getAttribute('data-pinned') === '1';
            await toggleConversationPinFromSettings(cid, !currentPin);
        };
    });

    tbody.querySelectorAll('.btn-open-advisor-from-settings').forEach(btn => {
        btn.onclick = (e) => {
            e.stopPropagation();
            const cid = btn.getAttribute('data-conv-id');
            const pageSec = btn.getAttribute('data-page') || 'section-overview';
            openConversationFromSettings(cid, pageSec);
        };
    });

    tbody.querySelectorAll('.btn-delete-conv-from-settings').forEach(btn => {
        btn.onclick = async (e) => {
            e.stopPropagation();
            const cid = btn.getAttribute('data-conv-id');
            const title = btn.getAttribute('data-title') || 'this conversation';
            const confirmed = typeof window.showModalConfirm === 'function'
                ? await window.showModalConfirm(`Delete conversation "${title}" and all its messages? This action cannot be undone.`, {
                    title: 'Delete Conversation',
                    confirmText: 'Delete',
                    confirmVariant: 'danger'
                })
                : confirm(`Delete conversation "${title}" and all its messages?`);
            if (confirmed) {
                await deleteConversationFromSettings(cid);
            }
        };
    });

    tbody.querySelectorAll('.settings-conv-row').forEach(row => {
        row.onclick = (e) => {
            if (e.target.closest('.settings-conv-checkbox') ||
                e.target.closest('.btn-toggle-pin-conv') ||
                e.target.closest('.btn-delete-conv-from-settings')) {
                return;
            }
            const cid = row.getAttribute('data-conv-id');
            const pageSec = row.getAttribute('data-page') || 'section-overview';
            openConversationFromSettings(cid, pageSec);
        };
    });
}

function updateSelectedConversationCount() {
    const checkboxes = document.querySelectorAll('.settings-conv-checkbox:checked');
    const count = checkboxes.length;
    const countEl = document.getElementById('settings-selected-conv-count');
    const deleteBtn = document.getElementById('btn-settings-bulk-delete-conversations');
    if (countEl) countEl.textContent = count;
    if (deleteBtn) deleteBtn.disabled = (count === 0);
}

async function toggleConversationPinFromSettings(convId, newPin) {
    try {
        const resp = await fetch(`/api/ai-advisor/conversations/${encodeURIComponent(convId)}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_pinned: newPin })
        });
        const data = await resp.json();
        if (data.success) {
            await loadSettingsAdvisorConversations();
            if (typeof window.refreshAdvisorConversations === 'function') {
                window.refreshAdvisorConversations();
            }
        }
    } catch (e) {
        console.error('Error toggling pin:', e);
    }
}

async function deleteConversationFromSettings(convId) {
    try {
        const resp = await fetch(`/api/ai-advisor/conversations/${encodeURIComponent(convId)}`, {
            method: 'DELETE'
        });
        const data = await resp.json();
        if (data.success) {
            await loadSettingsAdvisorConversations();
            if (typeof window.refreshAdvisorConversations === 'function') {
                window.refreshAdvisorConversations();
            }
        }
    } catch (e) {
        console.error('Error deleting conversation:', e);
    }
}

function openConversationFromSettings(convId, pageSection) {
    const modal = document.getElementById('settings-modal');
    if (modal) modal.style.display = 'none';

    if (typeof window.toggleAiAdvisorDrawer === 'function') {
        window.toggleAiAdvisorDrawer(true, convId);
    } else if (typeof window.openAdvisorConversation === 'function') {
        window.openAdvisorConversation(convId);
    }

    const pageToHash = {
        'section-overview': '#overview', 'section-equity': '#company-equity',
        'section-scenarios': '#forecasting', 'section-holdings': '#holdings',
        'section-arbitrage': '#arbitrage', 'section-withholding': '#withholding',
        'section-philanthropy': '#philanthropy', 'section-gifting': '#gifting',
        'section-college': '#college', 'section-transcripts': '#transcripts',
        'section-compensation': '#compensation', 'section-accounts': '#accounts',
        'section-estate': '#estate',
    };
    const targetHash = pageToHash[pageSection] || '#overview';
    if (window.location.hash !== targetHash) {
        window.location.hash = targetHash;
    }
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        loadSettingsAdvisorConversations,
        bindSettingsAdvisorConversationsTable,
        updateSelectedConversationCount,
        toggleConversationPinFromSettings,
        deleteConversationFromSettings,
        openConversationFromSettings
    });
}
