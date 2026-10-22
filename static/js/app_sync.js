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
    return [];
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
    syncButtons.forEach(btn => { btn.disabled = true; btn.classList.add('is-syncing'); });

    try {
        const resp = await fetch('/api/sync', { method: 'POST' });
        let res = await resp.json();
        const syncJobId = res.job_id || res.sync_job_id;
        const isProcessing = (res.status === 'processing' || res.sync_status === 'processing');
        if (res.success && isProcessing && syncJobId) {
            res = await pollMonarchSyncStatus(syncJobId, 150, 600);
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
            if (window.showModalAlert) {
                await window.showModalAlert(res.message || `Account sync successful! Updated ${res.accounts_count || 0} accounts.`, { title: 'Sync Complete' });
            }
        } else if (window.showModalAlert) {
            await window.showModalAlert(`Sync Issue: ${res.error || 'Check account connection credentials'}`, { title: 'Sync Failed' });
        }
    } catch (err) {
        if (window.showModalAlert) {
            await window.showModalAlert(`Sync Failed: ${err.message}`, { title: 'Sync Error' });
        }
    } finally {
        const isDemo = typeof window.isDemoSession === 'function' ? window.isDemoSession() : false;
        syncTexts.forEach(el => {
            el.textContent = isDemo ? 'Sync (Demo)' : 'Sync Accounts';
        });
        if (btnSettingsSync) btnSettingsSync.textContent = '↻ Sync Accounts Now';
        syncButtons.forEach(btn => { btn.disabled = false; btn.classList.remove('is-syncing'); });
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
