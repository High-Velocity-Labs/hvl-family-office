/**
 * HVL Family Office - App Sync & Session Management
 * Reactive signals, X-Domain-Versions header bridge, and version pill are provided by
 * shared `hvl_common/ui/static/reactive-signals.js` and `version_pill.js`.
 */

function inferDomainsFromMutationUrl(url) {
    const path = String(url || '').toLowerCase();
    if (!path.includes('/api/')) return [];
    if (path.includes('/api/accounts/toggle_net_worth') || path.includes('/api/settings/account_roles') || path.includes('/api/settings/confirm_all_roles')) {
        return ['accounts', 'balance_sheet', 'college', 'estate'];
    }
    if (path.includes('/api/accounts') || path.includes('/api/sync') || path.includes('/api/settings/simplefin') || path.includes('/api/settings/monarch')) {
        return ['accounts', 'balance_sheet', 'holdings', 'onboarding.checklist'];
    }
    if (path.includes('/api/holdings')) return ['holdings', 'holdings.policy'];
    if (path.includes('/api/equity')) return ['equity', 'balance_sheet', 'onboarding.checklist'];
    if (path.includes('/api/settings/assumptions') || path.includes('/api/tax')) return ['tax_profile', 'scenarios', 'balance_sheet', 'household.identity'];
    if (path.includes('/api/scenarios') || path.includes('/api/events')) return ['scenarios'];
    if (path.includes('/api/compensation') || path.includes('/api/transcripts')) return ['compensation', 'tax_profile', 'onboarding.checklist'];
    if (path.includes('/api/philanthropy')) return ['philanthropy'];
    if (path.includes('/api/gifting')) return ['gifting', 'estate'];
    if (path.includes('/api/estate')) return ['estate', 'onboarding.checklist'];
    if (path.includes('/api/education') || path.includes('/api/college')) return ['college'];
    if (path.includes('/api/family/invites')) return ['settings.invites'];
    if (path.includes('/api/family/members')) return ['household.members', 'college', 'estate', 'gifting', 'onboarding.checklist'];
    if (path.includes('/api/family')) return ['household.identity', 'household.members', 'tax_profile', 'onboarding.checklist'];
    if (path.includes('/api/onboarding')) return ['onboarding.checklist'];
    if (path.includes('/api/notifications')) return ['notifications'];
    return [];
}

function handleNotificationDeepLink(rawUrl) {
    try {
        const parsed = new URL(String(rawUrl || '/'), window.location.origin);
        const settingsTab = parsed.searchParams.get('settings');
        if (settingsTab && typeof window.openSettingsModal === 'function') {
            window.openSettingsModal();
            if (typeof window.switchSettingsTab === 'function') {
                window.switchSettingsTab(settingsTab);
            }
            return true;
        }
        const tabParam = (parsed.searchParams.get('tab') || '').toLowerCase();
        const pathKey = parsed.pathname.toLowerCase();
        const tabMap = {
            'overview': 'section-overview', 'equity': 'section-equity', 'company-equity': 'section-equity',
            'scenarios': 'section-scenarios', 'forecasting': 'section-scenarios', 'holdings': 'section-holdings',
            'arbitrage': 'section-arbitrage', 'tax': 'section-compensation', 'compensation': 'section-compensation',
            'transcripts': 'section-compensation', 'philanthropy': 'section-philanthropy', 'gifting': 'section-gifting',
            'estate': 'section-estate', 'college': 'section-college', 'education': 'section-college', 'accounts': 'section-accounts',
        };
        const targetSec = tabMap[tabParam] || (window.PATH_TO_SECTION && window.PATH_TO_SECTION[pathKey]);
        if (targetSec) {
            const navLink = document.querySelector(`.nav-link[data-target="${targetSec}"]`);
            if (navLink) {
                navLink.click();
                return true;
            }
        }
    } catch (_) {}
    return false;
}

async function doLogout() {
    if (document.body && document.body.dataset.isSandbox === 'true' && window.SandboxManager && typeof window.SandboxManager.wipeSandboxNow === 'function') {
        await window.SandboxManager.wipeSandboxNow();
        return;
    }
    const isDemo = typeof window.isDemoSession === 'function' ? window.isDemoSession() : false;
    const confirmMsg = isDemo ? 'Exit Demo sandbox and return to login?' : 'Sign out of Family Office portal?';
    const confirmTitle = isDemo ? 'Exit Demo' : 'Sign Out';
    if (window.showModalConfirm && await window.showModalConfirm(confirmMsg, { title: confirmTitle, confirmText: confirmTitle, confirmVariant: 'danger' })) {
        if (isDemo) {
            window.location.href = '/exit-demo';
        } else {
            await fetch('/api/auth/logout', { method: 'POST' });
            window.location.href = '/login';
        }
    }
}

async function pollMonarchSyncStatus(jobId, maxAttempts = 150, intervalMs = 600) {
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
        await new Promise(resolve => setTimeout(resolve, intervalMs));
        const pollResp = await fetch(`/api/sync/status/${encodeURIComponent(jobId)}`);
        const pollData = await pollResp.json();
        if (pollData.status !== 'processing') {
            return pollData;
        }
    }
    return { success: false, status: 'failed', error: 'Account sync timed out while processing.' };
}

async function triggerMonarchSync() {
    const btnSync = document.getElementById('btn-sync');
    const btnMobileSync = document.getElementById('btn-mobile-sync');
    const btnSettingsSync = document.getElementById('btn-settings-test-sync');
    const syncButtons = [btnSync, btnMobileSync, btnSettingsSync].filter(Boolean);

    const syncTexts = document.querySelectorAll('#sync-btn-text, #mobile-sync-btn-text');
    syncTexts.forEach(el => el.textContent = 'Syncing...');
    if (btnSettingsSync) btnSettingsSync.textContent = 'Syncing...';
    syncButtons.forEach(btn => {
        btn.disabled = true;
        btn.classList.add('is-syncing');
    });

    let activeSyncToast = null;

    try {
        const resp = await fetch('/api/sync', { method: 'POST' });
        let res = await resp.json();
        const syncJobId = res.job_id || res.sync_job_id;
        const isProcessing = (res.status === 'processing' || res.sync_status === 'processing');
        if (res.success && isProcessing && syncJobId) {
            if (typeof window.showToast === 'function') {
                activeSyncToast = window.showToast(
                    'Syncing accounts in background — this may take up to a minute if refreshing stale bank connections...',
                    'info',
                    0
                );
            }
            res = await pollMonarchSyncStatus(syncJobId, 150, 600);
        }
        if (activeSyncToast && typeof activeSyncToast.dismiss === 'function') {
            activeSyncToast.dismiss();
            activeSyncToast = null;
        }
        syncButtons.forEach(btn => btn.classList.remove('is-syncing'));
        if (res.success) {
            if (typeof window.morphSettingsModal === 'function' && document.getElementById('settings-modal')?.classList.contains('active')) {
                try {
                    await window.morphSettingsModal({ tab: 'monarch' });
                } catch (e) {
                    console.warn('Post-sync settings modal refresh warning:', e);
                }
            }
            syncTexts.forEach(el => el.textContent = '✓ Synced');
            if (btnSettingsSync) btnSettingsSync.textContent = '✓ Sync Complete';
            if (typeof window.showToast === 'function') {
                window.showToast(
                    res.message || `Account sync successful! Updated ${res.accounts_count || 0} accounts.`,
                    'success',
                    8000
                );
            }
        } else if (typeof window.showToast === 'function') {
            window.showToast(`Sync Issue: ${res.error || 'Check account connection credentials'}`, 'error', 10000);
        }
    } catch (err) {
        if (activeSyncToast && typeof activeSyncToast.dismiss === 'function') {
            activeSyncToast.dismiss();
            activeSyncToast = null;
        }
        if (typeof window.showToast === 'function') {
            window.showToast(`Sync Failed: ${err.message}`, 'error', 10000);
        }
    } finally {
        const isDemo = typeof window.isDemoSession === 'function' ? window.isDemoSession() : false;
        syncTexts.forEach(el => {
            el.textContent = isDemo ? 'Sync (Demo)' : 'Sync Accounts';
        });
        if (btnSettingsSync) btnSettingsSync.textContent = '↻ Sync Accounts Now';
        syncButtons.forEach(btn => {
            btn.disabled = false;
            btn.classList.remove('is-syncing');
        });
    }
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        inferDomainsFromMutationUrl,
        doLogout,
        pollMonarchSyncStatus,
        triggerMonarchSync
    });
}
