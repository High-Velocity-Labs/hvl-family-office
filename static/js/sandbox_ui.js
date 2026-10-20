// =========================================================================
// Ephemeral Sandbox Lifecycle, Toast Delegation & Processing Modal Controls
// Extracted from static/js/app.js for <400L modularity.
// =========================================================================

function parseExpiresAt(val) {
    if (!val) return 0;
    const num = Number(val);
    if (!isNaN(num) && num > 0) {
        return num > 1e11 ? Math.floor(num / 1000) : Math.floor(num);
    }
    const d = Date.parse(val);
    return isNaN(d) ? 0 : Math.floor(d / 1000);
}

function formatCountdown(diffSec) {
    if (diffSec <= 0) return 'Expired';
    const days = Math.floor(diffSec / 86400);
    const hours = Math.floor((diffSec % 86400) / 3600);
    const mins = Math.floor((diffSec % 3600) / 60);
    const secs = Math.floor(diffSec % 60);
    if (days > 0) {
        return `${days}d ${hours}h ${mins}m`;
    }
    if (hours > 0) {
        return `${hours}h ${mins < 10 ? '0' : ''}${mins}m ${secs < 10 ? '0' : ''}${secs}s`;
    }
    return `${mins}m ${secs < 10 ? '0' : ''}${secs}s`;
}

function updateSandboxCountdown() {
    const banner = document.getElementById('sandbox-ephemeral-banner');
    const countdownEl = document.getElementById('sandbox-expiry-countdown');
    const rawExpiry = (countdownEl && countdownEl.getAttribute('data-expires-at')) || (banner && banner.getAttribute('data-expires-at'));
    const expiresAt = parseExpiresAt(rawExpiry);
    if (!expiresAt) return;
    const nowSec = Math.floor(Date.now() / 1000);
    const diff = Math.max(0, expiresAt - nowSec);
    const text = formatCountdown(diff);
    if (countdownEl) countdownEl.textContent = text;
    document.querySelectorAll('.sandbox-countdown-display').forEach(el => {
        el.textContent = text;
    });
}

const showSandboxToast = (message, variant = 'info') => {
    const fn = window.hvlShowToast || window.showToast;
    if (typeof fn === 'function') fn(message, variant, 3500);
};

function showProcessingModal(title = 'Processing...', message = 'Please wait while your request completes.') {
    let backdrop = document.getElementById('fo-processing-modal-backdrop');
    if (!backdrop) {
        backdrop = document.createElement('div');
        backdrop.id = 'fo-processing-modal-backdrop';
        backdrop.setAttribute('role', 'status');
        backdrop.setAttribute('aria-live', 'polite');
        backdrop.style.cssText = 'position: fixed; inset: 0; z-index: var(--z-modal-nested, 10050); background: var(--modal-dialog-backdrop, rgba(6, 9, 15, 0.72)); backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px); display: flex; align-items: center; justify-content: center; padding: 20px;';
        const card = document.createElement('div');
        card.style.cssText = 'background: var(--bg-surface); border: 1px solid var(--border-bright); border-radius: 14px; max-width: 380px; width: 100%; padding: 28px 24px; box-shadow: var(--shadow-lg); display: flex; flex-direction: column; align-items: center; text-align: center; gap: 14px;';
        const spinner = document.createElement('div');
        spinner.className = 'chart-spinner';
        spinner.style.cssText = 'width: 38px; height: 38px; border-width: 3.5px; margin-bottom: 2px;';
        const titleEl = document.createElement('h3');
        titleEl.id = 'fo-processing-modal-title';
        titleEl.style.cssText = 'margin: 0; font-size: 1.05rem; font-weight: 700; color: var(--text-primary); letter-spacing: -0.01em;';
        const msgEl = document.createElement('p');
        msgEl.id = 'fo-processing-modal-msg';
        msgEl.style.cssText = 'margin: 0; font-size: 0.85rem; line-height: 1.5; color: var(--text-secondary);';
        card.appendChild(spinner);
        card.appendChild(titleEl);
        card.appendChild(msgEl);
        backdrop.appendChild(card);
        document.body.appendChild(backdrop);
    }
    const tEl = document.getElementById('fo-processing-modal-title');
    const mEl = document.getElementById('fo-processing-modal-msg');
    if (tEl) tEl.textContent = title;
    if (mEl) mEl.textContent = message;
    backdrop.style.display = 'flex';
}

function hideProcessingModal() {
    const backdrop = document.getElementById('fo-processing-modal-backdrop');
    if (backdrop && backdrop.parentElement) {
        backdrop.parentElement.removeChild(backdrop);
    }
}
window.showProcessingModal = showProcessingModal;
window.hideProcessingModal = hideProcessingModal;
window.showSandboxToast = showSandboxToast;

const SandboxManager = {
    initCountdown: () => {
        const banner = document.getElementById('sandbox-ephemeral-banner');
        const countdownEl = document.getElementById('sandbox-expiry-countdown');
        if (!banner && !countdownEl) return;
        updateSandboxCountdown();
        if (!window._sandboxTimerInterval) {
            window._sandboxTimerInterval = setInterval(updateSandboxCountdown, 1000);
            if (window._sandboxTimerInterval && typeof window._sandboxTimerInterval.unref === 'function') {
                window._sandboxTimerInterval.unref();
            }
        }
        if (document.body && document.body.dataset.isSandbox === 'true' && !window._sandboxFetchHooked && typeof window.fetch === 'function') {
            window._sandboxFetchHooked = true;
            const origFetch = window.fetch.bind(window);
            window.fetch = async (...args) => {
                const resp = await origFetch(...args);
                try {
                    const url = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url ? args[0].url : '');
                    const opts = args[1] || {};
                    const method = String(opts.method || 'GET').toUpperCase();
                    if (resp && resp.ok && (method === 'POST' || method === 'PUT') && url.includes('/api/') && !url.includes('/api/sandbox/wipe') && !url.includes('/api/auth/logout')) {
                        SandboxManager.markHasData();
                        if (url.includes('monarch_login') || url.includes('monarch_mfa') || url.includes('simplefin_connect')) {
                            const btnSync = document.getElementById('btn-sync');
                            const syncTime = document.getElementById('sync-timestamp');
                            const btnMobSync = document.getElementById('btn-mobile-sync');
                            if (btnSync) {
                                btnSync.hidden = false;
                                btnSync.classList.remove('provider-hidden');
                                btnSync.style.display = 'flex';
                            }
                            if (syncTime) {
                                syncTime.hidden = false;
                                syncTime.classList.remove('provider-hidden');
                                syncTime.style.display = 'block';
                            }
                            if (btnMobSync) {
                                btnMobSync.hidden = false;
                                btnMobSync.classList.remove('provider-hidden');
                                btnMobSync.style.display = '';
                            }
                            if (url.includes('monarch_login') || url.includes('monarch_mfa')) {
                                const btnSideMon = document.getElementById('btn-sidebar-monarch');
                                const btnTopMon = document.getElementById('top-open-monarch');
                                if (btnSideMon) {
                                    btnSideMon.hidden = false;
                                    btnSideMon.classList.remove('provider-hidden');
                                    btnSideMon.style.display = 'flex';
                                }
                                if (btnTopMon) {
                                    btnTopMon.hidden = false;
                                    btnTopMon.classList.remove('provider-hidden');
                                    btnTopMon.style.display = '';
                                }
                            }
                        }
                    }
                } catch (_) {}
                return resp;
            };
        }
    },
    updateCountdown: updateSandboxCountdown,
    markHasData: () => {
        document.querySelectorAll('#btn-sandbox-download-banner, #btn-sandbox-download-settings').forEach(btn => {
            btn.disabled = false;
            btn.style.opacity = '';
            btn.style.cursor = '';
            btn.setAttribute('title', 'Download encrypted .fovault backup');
        });
    },
    extendSandbox7Days: async () => {
        const btn = document.getElementById('btn-sandbox-extend-banner');
        if (btn) btn.disabled = true;
        try {
            let resp = await fetch('/api/sandbox/extend', { method: 'POST' });
            if (resp.status === 404) {
                resp = await fetch('/api/sandbox/retain', { method: 'POST' });
            }
            const data = await resp.json();
            if (!resp.ok || data.success === false) {
                throw new Error(data.error || 'Failed to extend sandbox session.');
            }
            if (data.expires_at) {
                const banner = document.getElementById('sandbox-ephemeral-banner');
                const countdown = document.getElementById('sandbox-expiry-countdown');
                if (banner) banner.setAttribute('data-expires-at', String(data.expires_at));
                if (countdown) countdown.setAttribute('data-expires-at', String(data.expires_at));
                document.querySelectorAll('.sandbox-countdown-display').forEach(el => {
                    el.setAttribute('data-expires-at', String(data.expires_at));
                });
                updateSandboxCountdown();
            }
            const extendBtns = document.querySelectorAll('#btn-sandbox-extend-banner, #btn-sandbox-extend-settings');
            extendBtns.forEach(b => {
                b.disabled = true;
                b.textContent = '✓ Saved (7-Day Lease Active)';
                b.classList.remove('btn-primary');
                b.classList.add('btn-secondary');
                b.style.background = 'var(--bg-surface-elevated)';
                b.style.borderColor = 'var(--status-green)';
                b.style.color = 'var(--text-primary)';
                b.style.opacity = '1';
                b.style.cursor = 'default';
            });
            showSandboxToast('Sandbox extended for 7 days. Your key remains strictly in your browser cookie.', 'success');
        } catch (err) {
            if (btn) btn.disabled = false;
            showSandboxToast(err.message, 'error');
        }
    },
    wipeSandboxNow: async () => {
        const confirmed = typeof window.showModalConfirm === 'function'
            ? await window.showModalConfirm('Permanently shred this sandbox database and exit Sandbox Mode? All accounts, scenarios, and settings will be destroyed unless you downloaded a .fovault backup.', {
                title: 'Wipe & Exit Sandbox',
                confirmText: 'Wipe & Exit',
                confirmVariant: 'danger',
                danger: true
            })
            : confirm('Permanently shred this sandbox database and exit Sandbox Mode? All data will be destroyed.');
        if (!confirmed) return;

        try {
            const resp = await fetch('/api/sandbox/wipe', { method: 'POST' });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok && data.error) {
                throw new Error(data.error);
            }
            window.location.href = '/login?sandbox_wiped=1';
        } catch (err) {
            showSandboxToast('Wipe failed: ' + err.message, 'error');
        }
    },
    downloadSandboxVault: () => {
        const isSandboxMode = Boolean(document.body && document.body.dataset.isSandbox === 'true');
        const url = isSandboxMode ? '/api/desktop/backup?sandbox=1' : '/api/desktop/backup';
        const prefix = isSandboxMode ? 'family_office_sandbox' : 'family_office_vault';
        const a = document.createElement('a');
        a.href = url;
        a.download = `${prefix}_${new Date().toISOString().slice(0, 10)}.fovault`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        showSandboxToast('Downloading encrypted .fovault backup...', 'info');
    },
    uploadSandboxVault: async (fileInput) => {
        if (!fileInput || !fileInput.files || !fileInput.files[0]) return;
        const file = fileInput.files[0];
        const isSandboxMode = Boolean(document.body && document.body.dataset.isSandbox === 'true');
        const confirmMsg = isSandboxMode
            ? `Restore "${file.name}" into this Anonymous Workspace? Current workspace records will be replaced.`
            : `Restore "${file.name}" into your active household vault? Current household financial records will be replaced and re-encrypted with your active vault key.`;
        const confirmed = typeof window.showModalConfirm === 'function'
            ? await window.showModalConfirm(confirmMsg, {
                title: 'Restore Vault Backup (.fovault)',
                confirmText: 'Restore Vault',
                confirmVariant: isSandboxMode ? 'danger' : 'primary'
            })
            : confirm(confirmMsg);
        if (!confirmed) {
            fileInput.value = '';
            return;
        }

        if (typeof window.closeOnboardingWizard === 'function') {
            window.closeOnboardingWizard();
        }
        showProcessingModal('Restoring Vault Backup...', 'Uploading archive, remapping household tables, and verifying schema...');
        const formData = new FormData();
        formData.append('file', file);
        formData.append('backup_file', file);
        formData.append('vault_file', file);

        try {
            const primaryUrl = isSandboxMode ? '/api/sandbox/restore_async' : '/api/vault/restore_async';
            let resp = await fetch(primaryUrl, { method: 'POST', body: formData });
            if (resp.status === 404) {
                resp = await fetch(isSandboxMode ? '/api/sandbox/restore' : '/api/desktop/restore', { method: 'POST', body: formData });
            }
            const data = await resp.json();
            if (!resp.ok || (data.success === false && data.error)) {
                throw new Error(data.error || 'Restore failed.');
            }

            let finalData = data;
            const jobId = data.job_id || data.sync_job_id;
            if (jobId) {
                let maxPolls = 60;
                let completed = false;
                while (maxPolls > 0 && !completed) {
                    await new Promise(r => setTimeout(r, 800));
                    maxPolls--;
                    let pResp = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`);
                    if (pResp.status === 404) {
                        pResp = await fetch(`/api/sync/status/${encodeURIComponent(jobId)}`);
                    }
                    if (pResp.ok) {
                        const pData = await pResp.json();
                        if (pData.status === 'completed' || pData.status === 'done' || (pData.status !== 'processing' && pData.success)) {
                            finalData = pData;
                            completed = true;
                        } else if (pData.status === 'failed' || pData.error) {
                            throw new Error(pData.error || 'Background restore failed.');
                        }
                    }
                }
            }

            hideProcessingModal();
            const summaryText = (finalData && finalData.summary && finalData.summary.summary_text)
                || (finalData && finalData.message)
                || 'Vault backup restored successfully.';
            if (typeof window.showModalAlert === 'function') {
                await window.showModalAlert(summaryText, {
                    title: 'Vault Backup Restored',
                    type: 'success',
                    confirmText: 'Continue to Dashboard'
                });
            } else {
                alert(summaryText);
            }
            const targetUrl = typeof window.appendSessionQuery === 'function' ? window.appendSessionQuery('/') : '/';
            window.location.href = targetUrl;
        } catch (err) {
            hideProcessingModal();
            if (typeof window.showModalAlert === 'function') {
                await window.showModalAlert('Vault Restore Failed: ' + err.message, { title: 'Restore Error', type: 'error' });
            } else {
                alert('Vault Restore Failed: ' + err.message);
            }
        } finally {
            hideProcessingModal();
            fileInput.value = '';
        }
    },
    showToast: (msg) => { if (typeof window.showToast === 'function') window.showToast(msg, 'info'); }
};
window.SandboxManager = SandboxManager;
