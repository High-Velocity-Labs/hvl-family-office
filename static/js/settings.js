/**
 * Settings & Tenant Management Module (Editor-Only, SSR + Idiomorph Controller)
 * Orchestrates Household Members, Financial Assumptions, Account Roles, Integrations, and Security.
 */

let _escapeSettingsbound = false;

function getActiveSettingsTab() {
    const activeBtn = document.querySelector('#settings-modal .settings-tab-btn.active');
    if (!activeBtn) return 'members';
    const dataTab = activeBtn.getAttribute('data-tab');
    if (dataTab) return dataTab;
    return activeBtn.id.replace('tab-btn-', '') || 'members';
}

async function morphSettingsModal(params = {}) {
    const modal = document.getElementById('settings-modal');
    if (!modal) return false;

    const wasOpen = modal.style.display !== 'none';
    const activeTab = params.tab || getActiveSettingsTab();
    const searchInput = document.getElementById('settings-advisor-search');
    const pageSelect = document.getElementById('settings-advisor-filter-page');
    const pinnedBtn = document.getElementById('btn-settings-filter-pinned');

    const rawSearch = searchInput ? searchInput.value.trim() : '';
    const cleanDomSearch = (rawSearch.startsWith('{{') && rawSearch.endsWith('}}')) ? '' : rawSearch;
    const advSearch = params.adv_search !== undefined ? params.adv_search : cleanDomSearch;
    const advPage = params.adv_page !== undefined ? params.adv_page : (pageSelect ? pageSelect.value.trim() : '');
    const advPinned = params.adv_pinned_only !== undefined
        ? params.adv_pinned_only
        : (pinnedBtn && pinnedBtn.classList.contains('active') ? '1' : '');

    const qs = new URLSearchParams();
    if (activeTab) qs.set('tab', activeTab);
    if (advSearch) qs.set('adv_search', advSearch);
    if (advPage) qs.set('adv_page', advPage);
    if (advPinned) qs.set('adv_pinned_only', String(advPinned));

    const url = `/fragments/settings?${qs.toString()}`;
    try {
        const resp = await fetch(url);
        if (!resp || !resp.ok || typeof resp.text !== 'function') return false;
        let html = await resp.text();
        if (!html || !html.includes('settings-modal')) return false;

        if (wasOpen) {
            html = html.replace(/(id=["']settings-modal["'][^>]*style=["'])display:\s*none;?/i, '$1display: flex;');
        }

        window.Idiomorph.morph(modal, html);
        if (typeof window !== 'undefined' && window.BugReporter && typeof window.BugReporter.ensurePaneTriggers === 'function') {
            window.BugReporter.ensurePaneTriggers();
        }

        const updatedModal = document.getElementById('settings-modal');
        if (updatedModal && wasOpen) {
            updatedModal.style.display = 'flex';
        }
        bindSettingsModalControls();
        return true;
    } catch (e) {
        return false;
    }
}

function initSettingsListeners() {
    const btnOpenHeader = document.getElementById('btn-open-settings');
    const btnOpenSidebar = document.getElementById('btn-sidebar-settings');

    if (btnOpenHeader) btnOpenHeader.onclick = () => openSettingsModal();
    if (btnOpenSidebar) btnOpenSidebar.onclick = () => openSettingsModal();

    if (!_escapeSettingsbound) {
        _escapeSettingsbound = true;
        document.addEventListener('keydown', (e) => {
            const modal = document.getElementById('settings-modal');
            if (e.key === 'Escape' && modal && modal.style.display !== 'none') {
                closeSettingsModal();
            }
        });
    }

    bindSettingsModalControls();
    try {
        const params = new URLSearchParams(window.location.search || '');
        const reqSettingsTab = params.get('settings');
        if (reqSettingsTab) {
            openSettingsModal();
            switchSettingsTab(reqSettingsTab);
        }
    } catch (_) {}
}

function closeSettingsModal() {
    const modal = document.getElementById('settings-modal');
    if (modal) modal.style.display = 'none';

    const banner = document.getElementById('settings-onboarding-return-banner');
    if (banner) banner.style.display = 'none';

    if (window._returnToOnboardingStep) {
        const step = window._returnToOnboardingStep;
        window._returnToOnboardingStep = null;
        if (typeof window.openOnboardingWizard === 'function') {
            window.openOnboardingWizard(step);
        }
    }
}

async function openSettingsModal() {
    const modal = document.getElementById('settings-modal');
    if (!modal) return;
    modal.style.display = 'flex';

    const banner = document.getElementById('settings-onboarding-return-banner');
    if (banner) {
        banner.style.display = window._returnToOnboardingStep ? 'flex' : 'none';
    }

    const modalBody = modal.querySelector('.settings-modal-body');
    if (modalBody) modalBody.scrollTop = 0;

    bindSettingsModalControls();
}

function switchSettingsTab(tabName) {
    const tabMap = {
        'members': 'tab-btn-members', 'household': 'tab-btn-members',
        'assumptions': 'tab-btn-assumptions', 'tax': 'tab-btn-assumptions', 'legal': 'tab-btn-assumptions',
        'roles': 'tab-btn-roles', 'accounts': 'tab-btn-roles',
        'monarch': 'tab-btn-monarch', 'integrations': 'tab-btn-monarch', 'simplefin': 'tab-btn-monarch',
        'appearance': 'tab-btn-appearance', 'advisor-history': 'tab-btn-advisor-history',
    };
    const key = (tabName || '').toLowerCase().trim();
    const btnId = tabMap[key] || `tab-btn-${key}`;
    const btn = document.getElementById(btnId);
    if (btn) {
        btn.click();
        return true;
    }
    return false;
}

function applyDemoReadOnlyState() {
    const isDemo = Boolean(document.getElementById('demo-settings-badge'));
    if (!isDemo) return;

    const modal = document.getElementById('settings-modal');
    if (!modal) return;

    modal.querySelectorAll('input:not([type="hidden"]), select').forEach(el => {
        if (el.id === 'settings-advisor-search' || el.id === 'settings-advisor-filter-page') return;
        el.disabled = true;
        el.style.opacity = '0.7';
        el.style.cursor = 'not-allowed';
    });

    const btnIds = [
        'btn-save-family-name', 'btn-add-member-toggle', 'btn-create-invite-toggle',
        'btn-submit-create-invite', 'btn-save-assumptions', 'btn-confirm-all-roles',
        'btn-monarch-login-submit', 'btn-settings-test-sync', 'btn-simplefin-connect-submit',
        'btn-settings-simplefin-sync', 'btn-settings-simplefin-disconnect',
        'btn-save-gemini-key', 'btn-clear-gemini-key', 'btn-open-delete-household-modal'
    ];
    btnIds.forEach(id => {
        const btn = document.getElementById(id);
        if (btn) {
            btn.disabled = true;
            btn.style.opacity = '0.5';
            btn.style.cursor = 'not-allowed';
            btn.title = 'Disabled in Demo Sandbox (Read-Only)';
        }
    });

    modal.querySelectorAll('.btn-edit-member, .btn-delete-member, .btn-del-member, .btn-revoke-invite, .btn-save-acc-role').forEach(btn => {
        btn.disabled = true;
        btn.style.opacity = '0.4';
        btn.style.cursor = 'not-allowed';
        btn.title = 'Disabled in Demo Sandbox (Read-Only)';
    });
}

function bindSettingsModalControls() {
    const modal = document.getElementById('settings-modal');
    if (!modal) return;

    const btnClose = document.getElementById('btn-close-settings-modal');
    if (btnClose) btnClose.onclick = () => { closeSettingsModal(); };
    modal.onclick = (e) => { if (e.target === modal) closeSettingsModal(); };

    const subnavContainer = document.getElementById('settings-subnav-container');
    if (subnavContainer && typeof window.initScrollableRibbon === 'function') {
        window.initScrollableRibbon(subnavContainer, { scrollSpy: false });
    }

    const tabBtns = [
        { btn: document.getElementById('tab-btn-members'), content: document.getElementById('settings-tab-members') },
        { btn: document.getElementById('tab-btn-assumptions'), content: document.getElementById('settings-tab-assumptions') },
        { btn: document.getElementById('tab-btn-roles'), content: document.getElementById('settings-tab-roles') },
        { btn: document.getElementById('tab-btn-monarch'), content: document.getElementById('settings-tab-monarch') },
        { btn: document.getElementById('tab-btn-appearance'), content: document.getElementById('settings-tab-appearance') },
        { btn: document.getElementById('tab-btn-advisor-history'), content: document.getElementById('settings-tab-advisor-history') },
    ];

    tabBtns.forEach(({ btn, content }) => {
        if (!btn || !content) return;
        btn.onclick = () => {
            tabBtns.forEach(t => {
                if (t.btn) t.btn.classList.remove('active');
                if (t.content) t.content.style.display = 'none';
            });
            btn.classList.add('active');
            content.style.display = 'block';

            if (btn.id === 'tab-btn-advisor-history' && typeof loadSettingsAdvisorConversations === 'function') {
                loadSettingsAdvisorConversations();
            }

            const modalBody = document.querySelector('#settings-modal .settings-modal-body') || content.parentElement;
            if (modalBody) modalBody.scrollTop = 0;
        };
    });

    const advSearch = document.getElementById('settings-advisor-search');
    const advFilterPage = document.getElementById('settings-advisor-filter-page');
    const advFilterPinned = document.getElementById('btn-settings-filter-pinned');
    const advSelectAll = document.getElementById('settings-conv-select-all');
    const advBulkDelete = document.getElementById('btn-settings-bulk-delete-conversations');
    const advRefresh = document.getElementById('btn-settings-refresh-conversations');

    const reloadAdvisorHistory = () => {
        if (typeof loadSettingsAdvisorConversations === 'function') {
            loadSettingsAdvisorConversations();
        }
    };

    if (advSearch) advSearch.oninput = reloadAdvisorHistory;
    if (advFilterPage) advFilterPage.onchange = reloadAdvisorHistory;
    if (advFilterPinned) {
        advFilterPinned.onclick = () => {
            advFilterPinned.classList.toggle('active');
            if (advFilterPinned.classList.contains('active')) {
                advFilterPinned.style.background = 'var(--accent-purple-bg, rgba(139, 92, 246, 0.2))';
                advFilterPinned.style.borderColor = 'var(--accent-purple, #8B5CF6)';
            } else {
                advFilterPinned.style.background = '';
                advFilterPinned.style.borderColor = '';
            }
            reloadAdvisorHistory();
        };
    }
    if (advSelectAll) {
        advSelectAll.onchange = () => {
            const isChecked = advSelectAll.checked;
            document.querySelectorAll('.settings-conv-checkbox').forEach(cb => {
                if (cb.closest('tr') && cb.closest('tr').style.display === 'none') return;
                cb.checked = isChecked;
            });
            if (typeof updateSelectedConversationCount === 'function') updateSelectedConversationCount();
        };
    }
    if (advRefresh) {
        advRefresh.onclick = reloadAdvisorHistory;
    }
    if (advBulkDelete) {
        advBulkDelete.onclick = async () => {
            const checkedBoxes = document.querySelectorAll('.settings-conv-checkbox:checked');
            const ids = Array.from(checkedBoxes).map(cb => cb.value);
            if (!ids.length) return;
            const confirmed = typeof window.showModalConfirm === 'function'
                ? await window.showModalConfirm(`Delete ${ids.length} selected conversation${ids.length === 1 ? '' : 's'}?`, {
                    title: 'Delete Conversations', confirmText: `Delete ${ids.length} Conversations`, confirmVariant: 'danger'
                })
                : confirm(`Delete ${ids.length} conversations?`);
            if (!confirmed) return;

            try {
                const resp = await fetch('/api/ai-advisor/conversations/bulk-delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ conversation_ids: ids })
                });
                const data = await resp.json();
                if (data.success) {
                    await morphSettingsModal({ tab: 'advisor-history' });
                    if (typeof window.refreshAdvisorConversations === 'function') window.refreshAdvisorConversations();
                } else if (typeof window.showModalAlert === 'function') {
                    await window.showModalAlert(`Failed to delete: ${data.error || 'Unknown error'}`, { title: 'Delete Error', type: 'error' });
                }
            } catch (err) {
                if (typeof window.showModalAlert === 'function') {
                    await window.showModalAlert(`Error deleting: ${err.message}`, { title: 'Network Error', type: 'error' });
                }
            }
        };
    }

    try { if (typeof bindSettingsMembersForms === 'function') bindSettingsMembersForms(); } catch (e) {}
    try { if (typeof bindSettingsMembersTable === 'function') bindSettingsMembersTable(); } catch (e) {}
    try { if (typeof bindMagicInviteControls === 'function') bindMagicInviteControls(); } catch (e) {}
    try { if (typeof bindSettingsIntegrations === 'function') bindSettingsIntegrations(); } catch (e) {}
    try { if (typeof bindSettingsRolesTable === 'function') bindSettingsRolesTable(); } catch (e) {}
    try { if (typeof bindSupportAccessToggle === 'function') bindSupportAccessToggle(); } catch (e) {}
    try { if (typeof bindDeleteHouseholdControls === 'function') bindDeleteHouseholdControls(); } catch (e) {}
    try { if (typeof bindLocalDesktopControls === 'function') bindLocalDesktopControls(); } catch (e) {}
    try { if (typeof bindSettingsAdvisorConversationsTable === 'function') bindSettingsAdvisorConversationsTable(); } catch (e) {}
    try { applyDemoReadOnlyState(); } catch (e) {}
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        openSettingsModal,
        closeSettingsModal,
        morphSettingsModal,
        switchSettingsTab,
        initSettingsListeners,
        bindSettingsModalControls
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { initSettingsListeners(); });
} else {
    initSettingsListeners();
}
