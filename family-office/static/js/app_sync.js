/**
 * HVL Family Office - App Sync & Session Management
 * Reactive signals, X-Domain-Versions header bridge, and version pill are provided by
 * shared `hvl_common/ui/static/reactive-signals.js` and `version_pill.js`.
 */

function handleNotificationDeepLink(rawUrl) {
    try {
        const parsed = new URL(String(rawUrl || '/'), window.location.origin);
        const settingsTab = parsed.searchParams.get('settings');
        if (settingsTab) {
            window.openSettingsModal();
            window.switchSettingsTab(settingsTab);
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
    if (document.body.dataset.isSandbox === 'true') {
        await window.SandboxManager.wipeSandboxNow();
        return;
    }
    const isDemo = window.isDemoSession();
    const confirmMsg = isDemo ? 'Exit Demo sandbox and return to login?' : 'Sign out of Family Office portal?';
    const confirmTitle = isDemo ? 'Exit Demo' : 'Sign Out';
    const confirmed = await window.showModalConfirm(confirmMsg, {
        title: confirmTitle, confirmText: confirmTitle, confirmVariant: 'danger'
    });
    if (confirmed) {
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

function updateSyncTimestampDOM(rawIso, allowOlder = false) {
    const timeEl = document.getElementById('sync-timestamp');
    if (!timeEl || !rawIso || rawIso === 'Never') return false;
    const d = new Date(rawIso);
    if (isNaN(d.getTime())) return false;
    const prevIso = timeEl.getAttribute('data-sync-iso');
    if (!allowOlder && prevIso) {
        const prevDate = new Date(prevIso);
        if (!isNaN(prevDate.getTime()) && prevDate.getTime() > d.getTime()) {
            return false;
        }
    }
    const datePart = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    const timePart = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    timeEl.setAttribute('data-sync-iso', d.toISOString());
    timeEl.textContent = `Last Synced: ${datePart}, ${timePart}`;
    return true;
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
            activeSyncToast = window.showToast(
                'Syncing accounts in background — this may take up to a minute if refreshing stale bank connections...',
                'info',
                0
            );
            res = await pollMonarchSyncStatus(syncJobId, 150, 600);
        }
        if (activeSyncToast) {
            activeSyncToast.dismiss();
            activeSyncToast = null;
        }
        syncButtons.forEach(btn => btn.classList.remove('is-syncing'));
        if (res.success) {
            updateSyncTimestampDOM(res.timestamp || new Date().toISOString());
            if (document.getElementById('settings-modal')?.classList.contains('active')) {
                try {
                    await window.morphSettingsModal({ tab: 'monarch' });
                } catch (e) {
                    console.warn('Post-sync settings modal refresh warning:', e);
                }
            }
            syncTexts.forEach(el => el.textContent = '✓ Synced');
            if (btnSettingsSync) btnSettingsSync.textContent = '✓ Sync Complete';
            window.showToast(
                res.message || `Account sync successful! Updated ${res.accounts_count || 0} accounts.`,
                'success',
                8000
            );
        } else {
            window.showToast(`Sync Issue: ${res.error || 'Check account connection credentials'}`, 'error', 10000);
        }
    } catch (err) {
        if (activeSyncToast) {
            activeSyncToast.dismiss();
            activeSyncToast = null;
        }
        window.showToast(`Sync Failed: ${err.message}`, 'error', 10000);
    } finally {
        const isDemo = window.isDemoSession();
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

Object.assign(window, { doLogout, pollMonarchSyncStatus, updateSyncTimestampDOM, triggerMonarchSync });
