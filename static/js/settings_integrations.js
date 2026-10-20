/**
 * Settings & Tenant Management - Financial Integrations Module
 * Handles Monarch Money, SimpleFIN Bridge, and Google Gemini BYO API Key integrations.
 */

function setSettingsStatus(id, text, color) {
    const el = document.getElementById(id);
    if (el) {
        el.textContent = text;
        if (color) el.style.color = color;
    }
}

async function pollSettingsSyncJob(jobId, maxAttempts = 150, intervalMs = 600) {
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
        await new Promise(resolve => setTimeout(resolve, intervalMs));
        const pollResp = await fetch(`/api/sync/status/${encodeURIComponent(jobId)}`);
        const pollData = await pollResp.json();
        if (pollData.status !== 'processing') return pollData;
    }
    return { success: false, status: 'failed', error: 'Account sync timed out while processing.' };
}

function bindSettingsIntegrations() {
    const btnTestSync = document.getElementById('btn-settings-test-sync');
    if (btnTestSync) {
        btnTestSync.onclick = async () => {
            if (typeof window.triggerMonarchSync === 'function') {
                await window.triggerMonarchSync();
                if (typeof morphSettingsModal === 'function') await morphSettingsModal({ tab: 'monarch' });
                return;
            }
            btnTestSync.textContent = 'Syncing...';
            btnTestSync.disabled = true;
            try {
                const resp = await fetch('/api/sync', { method: 'POST' });
                let res = await resp.json();
                if (res.success && res.status === 'processing' && res.job_id) res = await pollSettingsSyncJob(res.job_id);
                if (res.success) {
                    if (typeof morphSettingsModal === 'function') await morphSettingsModal({ tab: 'monarch' });
                } else {
                    alert(`Sync Error: ${res.error}`);
                    btnTestSync.textContent = '↻ Sync Monarch Now';
                    btnTestSync.disabled = false;
                }
            } catch (err) {
                alert(`Sync Error: ${err.message}`);
                btnTestSync.textContent = '↻ Sync Monarch Now';
                btnTestSync.disabled = false;
            }
        };
    }

    const formMonarch = document.getElementById('form-monarch-auth');
    if (formMonarch) {
        formMonarch.onsubmit = async (e) => {
            e.preventDefault();
            const email = document.getElementById('input-monarch-email').value.trim();
            const password = document.getElementById('input-monarch-password').value;
            const mfaKey = document.getElementById('input-monarch-mfa-key').value.trim();
            const btnSubmit = document.getElementById('btn-monarch-login-submit');
            const mfaBox = document.getElementById('monarch-mfa-code-box');

            if (!email || !password) return;
            if (btnSubmit) btnSubmit.textContent = 'Authenticating...';
            setSettingsStatus('monarch-auth-status', 'Connecting to Monarch...', 'var(--accent-orange)');

            try {
                const resp = await fetch('/api/settings/monarch_login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, password, mfa_secret_key: mfaKey })
                });
                let res = await resp.json();
                const syncJobId = res.job_id || res.sync_job_id;
                if (res.success && (res.status === 'processing' || res.sync_status === 'processing') && syncJobId) {
                    res = await pollSettingsSyncJob(syncJobId);
                }

                if (res.success) {
                    if (typeof morphSettingsModal === 'function') await morphSettingsModal({ tab: 'monarch' });
                    setSettingsStatus('monarch-auth-status', `✓ ${res.message || 'Connected successfully!'} (${res.accounts_count || 0} accounts)`, 'var(--status-green)');
                } else if (res.requires_mfa) {
                    setSettingsStatus('monarch-auth-status', res.message, 'var(--accent-blue)');
                    if (mfaBox) mfaBox.style.display = 'block';
                    if (btnSubmit) btnSubmit.textContent = 'Connect Monarch';
                } else {
                    setSettingsStatus('monarch-auth-status', `Error: ${res.error}`, 'var(--status-red)');
                    if (btnSubmit) btnSubmit.textContent = 'Connect Monarch';
                }
            } catch (err) {
                setSettingsStatus('monarch-auth-status', `Error: ${err.message}`, 'var(--status-red)');
                if (btnSubmit) btnSubmit.textContent = 'Connect Monarch';
            }
        };
    }

    const btnSubmitMfa = document.getElementById('btn-submit-2fa-code');
    if (btnSubmitMfa) {
        btnSubmitMfa.onclick = async () => {
            const email = document.getElementById('input-monarch-email').value.trim();
            const password = document.getElementById('input-monarch-password').value;
            const code = document.getElementById('input-monarch-2fa-code').value.trim();
            if (!code) { alert('Please enter your 6-digit 2FA code.'); return; }

            btnSubmitMfa.textContent = 'Verifying...';
            try {
                const resp = await fetch('/api/settings/monarch_mfa', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, password, code })
                });
                let res = await resp.json();
                const syncJobId = res.job_id || res.sync_job_id;
                if (res.success && (res.status === 'processing' || res.sync_status === 'processing') && syncJobId) {
                    res = await pollSettingsSyncJob(syncJobId);
                }

                if (res.success) {
                    if (typeof morphSettingsModal === 'function') await morphSettingsModal({ tab: 'monarch' });
                    setSettingsStatus('monarch-auth-status', `✓ ${res.message || 'Authenticated as trusted device!'}`, 'var(--status-green)');
                } else {
                    setSettingsStatus('monarch-auth-status', `Error: ${res.error}`, 'var(--status-red)');
                    btnSubmitMfa.textContent = 'Verify & Save';
                }
            } catch (err) {
                setSettingsStatus('monarch-auth-status', `Error: ${err.message}`, 'var(--status-red)');
                btnSubmitMfa.textContent = 'Verify & Save';
            }
        };
    }

    const formSimplefin = document.getElementById('form-simplefin-auth');
    if (formSimplefin) {
        formSimplefin.onsubmit = async (e) => {
            e.preventDefault();
            const tokenInput = document.getElementById('input-simplefin-token');
            const token = tokenInput ? tokenInput.value.trim() : '';
            const btnSubmit = document.getElementById('btn-simplefin-connect-submit');
            if (!token) return;
            if (btnSubmit) { btnSubmit.textContent = 'Claiming & Syncing...'; btnSubmit.disabled = true; }
            setSettingsStatus('simplefin-auth-status', 'Connecting to SimpleFIN Bridge...', 'var(--accent-orange)');

            try {
                const resp = await fetch('/api/settings/simplefin_connect', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ setup_token: token })
                });
                let res = await resp.json();
                const syncJobId = res.job_id || res.sync_job_id;
                if (res.success && (res.status === 'processing' || res.sync_status === 'processing') && syncJobId) {
                    res = await pollSettingsSyncJob(syncJobId);
                }

                if (res.success) {
                    if (typeof morphSettingsModal === 'function') await morphSettingsModal({ tab: 'monarch' });
                    setSettingsStatus('simplefin-auth-status', `✓ ${res.message || 'SimpleFIN Bridge connected!'}`, 'var(--status-green)');
                } else {
                    setSettingsStatus('simplefin-auth-status', `Error: ${res.error || 'Failed to connect SimpleFIN'}`, 'var(--status-red)');
                    if (btnSubmit) { btnSubmit.textContent = 'Connect SimpleFIN Bridge'; btnSubmit.disabled = false; }
                }
            } catch (err) {
                setSettingsStatus('simplefin-auth-status', `Error: ${err.message}`, 'var(--status-red)');
                if (btnSubmit) { btnSubmit.textContent = 'Connect SimpleFIN Bridge'; btnSubmit.disabled = false; }
            }
        };
    }

    const btnSimplefinSync = document.getElementById('btn-settings-simplefin-sync');
    if (btnSimplefinSync) {
        btnSimplefinSync.onclick = async () => {
            btnSimplefinSync.textContent = 'Syncing...';
            btnSimplefinSync.disabled = true;
            setSettingsStatus('simplefin-auth-status', 'Syncing accounts from SimpleFIN Bridge...', 'var(--accent-orange)');
            try {
                const resp = await fetch('/api/settings/simplefin_sync', { method: 'POST' });
                let res = await resp.json();
                if (res.success && (res.status === 'processing' || res.sync_status === 'processing') && res.job_id) {
                    res = await pollSettingsSyncJob(res.job_id);
                }
                if (res.success) {
                    if (typeof morphSettingsModal === 'function') await morphSettingsModal({ tab: 'monarch' });
                    setSettingsStatus('simplefin-auth-status', `✓ ${res.message || 'SimpleFIN sync complete!'}`, 'var(--status-green)');
                } else {
                    setSettingsStatus('simplefin-auth-status', `Error: ${res.error || 'SimpleFIN sync failed'}`, 'var(--status-red)');
                    btnSimplefinSync.textContent = '↻ Sync SimpleFIN Now';
                    btnSimplefinSync.disabled = false;
                }
            } catch (err) {
                setSettingsStatus('simplefin-auth-status', `Error: ${err.message}`, 'var(--status-red)');
                btnSimplefinSync.textContent = '↻ Sync SimpleFIN Now';
                btnSimplefinSync.disabled = false;
            }
        };
    }

    const btnSimplefinDisconnect = document.getElementById('btn-settings-simplefin-disconnect');
    if (btnSimplefinDisconnect) {
        btnSimplefinDisconnect.onclick = async () => {
            const confirmed = typeof window.showModalConfirm === 'function'
                ? await window.showModalConfirm(
                    'Disconnect SimpleFIN Bridge and remove synced SimpleFIN accounts from this household? Monarch Money accounts will not be affected.',
                    { title: 'Disconnect SimpleFIN Bridge', confirmText: 'Disconnect', confirmVariant: 'danger' }
                )
                : confirm('Disconnect SimpleFIN Bridge and remove synced SimpleFIN accounts?');
            if (!confirmed) return;

            btnSimplefinDisconnect.textContent = 'Disconnecting...';
            btnSimplefinDisconnect.disabled = true;
            try {
                const resp = await fetch('/api/settings/simplefin_disconnect', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ remove_accounts: true })
                });
                const res = await resp.json();
                if (res.success) {
                    if (typeof morphSettingsModal === 'function') await morphSettingsModal({ tab: 'monarch' });
                } else {
                    alert(`Error: ${res.error || 'Failed to disconnect SimpleFIN'}`);
                    btnSimplefinDisconnect.textContent = 'Disconnect';
                    btnSimplefinDisconnect.disabled = false;
                }
            } catch (err) {
                alert(`Error: ${err.message}`);
                btnSimplefinDisconnect.textContent = 'Disconnect';
                btnSimplefinDisconnect.disabled = false;
            }
        };
    }

    const formGeminiKey = document.getElementById('form-gemini-key');
    if (formGeminiKey) {
        formGeminiKey.onsubmit = async (e) => {
            e.preventDefault();
            const keyInput = document.getElementById('input-settings-gemini-key');
            const keyVal = keyInput ? keyInput.value.trim() : '';
            const btnSave = document.getElementById('btn-save-gemini-key');
            if (!keyVal) return;
            if (btnSave) { btnSave.textContent = 'Saving...'; btnSave.disabled = true; }
            try {
                const resp = await fetch('/api/settings/ai_key', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ gemini_api_key: keyVal }),
                });
                const res = await resp.json();
                if (res.success) {
                    if (typeof morphSettingsModal === 'function') await morphSettingsModal({ tab: 'monarch' });
                    setSettingsStatus('gemini-key-status', `✓ ${res.message || 'Gemini API key saved!'}`, 'var(--status-green)');
                } else {
                    setSettingsStatus('gemini-key-status', `Error: ${res.error || 'Failed to save key'}`, 'var(--status-red)');
                    if (btnSave) { btnSave.textContent = 'Save Key'; btnSave.disabled = false; }
                }
            } catch (err) {
                setSettingsStatus('gemini-key-status', `Error: ${err.message}`, 'var(--status-red)');
                if (btnSave) { btnSave.textContent = 'Save Key'; btnSave.disabled = false; }
            }
        };
    }

    const btnClearGeminiKey = document.getElementById('btn-clear-gemini-key');
    if (btnClearGeminiKey) {
        btnClearGeminiKey.onclick = async () => {
            btnClearGeminiKey.textContent = 'Clearing...';
            btnClearGeminiKey.disabled = true;
            try {
                const resp = await fetch('/api/settings/ai_key', { method: 'DELETE' });
                const res = await resp.json();
                if (res.success && typeof morphSettingsModal === 'function') {
                    await morphSettingsModal({ tab: 'monarch' });
                } else {
                    btnClearGeminiKey.textContent = 'Clear Key';
                    btnClearGeminiKey.disabled = false;
                }
            } catch (err) {
                btnClearGeminiKey.textContent = 'Clear Key';
                btnClearGeminiKey.disabled = false;
            }
        };
    }
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        pollSettingsSyncJob,
        bindSettingsIntegrations
    });
}
