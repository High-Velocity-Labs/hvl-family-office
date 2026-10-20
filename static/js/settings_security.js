/**
 * Settings & Tenant Management - Security, Support Escrow & Local Vault
 * Handles support access toggles, 30-day household deletion, and offline desktop vault controls.
 */

function updateSupportAccessUi(enabled) {
    const toggle = document.getElementById('toggle-support-access');
    const badge = document.getElementById('support-access-badge');
    if (toggle) toggle.checked = Boolean(enabled);
    if (badge) {
        if (enabled) {
            badge.className = 'badge badge-orange';
            badge.textContent = 'Support Access Enabled';
        } else {
            badge.className = 'badge badge-green';
            badge.textContent = 'Locked (Private)';
        }
    }
}

function bindSupportAccessToggle() {
    const toggle = document.getElementById('toggle-support-access');
    if (!toggle) return;
    toggle.onchange = async () => {
        const statusEl = document.getElementById('support-access-status');
        const desiredState = Boolean(toggle.checked);
        if (statusEl) {
            statusEl.textContent = 'Updating...';
            statusEl.style.color = 'var(--accent-orange)';
        }
        try {
            const resp = await fetch('/api/family/support-access', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: desiredState })
            });
            const res = await resp.json();
            if (resp.ok && res.success) {
                if (typeof morphSettingsModal === 'function') await morphSettingsModal({ tab: 'members' });
                updateSupportAccessUi(Boolean(res.support_access_enabled));
                const updatedStatus = document.getElementById('support-access-status');
                if (updatedStatus) {
                    updatedStatus.textContent = res.support_access_enabled ? '✓ Support access enabled' : '✓ Locked (Private)';
                    updatedStatus.style.color = 'var(--status-green)';
                    setTimeout(() => { if (updatedStatus) updatedStatus.textContent = ''; }, 2500);
                }
            } else {
                updateSupportAccessUi(!desiredState);
                if (statusEl) {
                    statusEl.textContent = `Error: ${res.error || 'Failed to update'}`;
                    statusEl.style.color = 'var(--status-red)';
                }
            }
        } catch (err) {
            updateSupportAccessUi(!desiredState);
            if (statusEl) {
                statusEl.textContent = `Error: ${err.message}`;
                statusEl.style.color = 'var(--status-red)';
            }
        }
    };
}

function bindDeleteHouseholdControls() {
    const btnOpen = document.getElementById('btn-open-delete-household-modal');
    const delModal = document.getElementById('delete-household-modal');
    const btnClose = document.getElementById('btn-close-delete-household-modal');
    const btnCancel = document.getElementById('btn-cancel-delete-household');
    const formDelete = document.getElementById('form-delete-household');
    const inputConfirm = document.getElementById('input-confirm-delete-family-name');
    const chkImmediate = document.getElementById('checkbox-delete-immediate');
    const btnSubmit = document.getElementById('btn-confirm-delete-household');
    const statusEl = document.getElementById('delete-household-status');
    const expectedNameEl = document.getElementById('delete-modal-expected-name');
    const nameDisplayEl = document.getElementById('delete-modal-family-name-display');

    if (!btnOpen || !delModal) return;

    function getCurrentExpectedName() {
        const inputSettingsName = document.getElementById('input-settings-family-name');
        const fromInput = inputSettingsName ? inputSettingsName.value.trim() : '';
        if (fromInput && !(fromInput.startsWith('{{') && fromInput.endsWith('}}'))) return fromInput;
        const fromAttr = (btnOpen.getAttribute('data-family-name') || '').trim();
        if (fromAttr && !(fromAttr.startsWith('{{') && fromAttr.endsWith('}}'))) return fromAttr;
        const fromSpan = expectedNameEl ? expectedNameEl.textContent.trim() : '';
        return fromSpan || 'Family Office';
    }

    function syncDeleteButtonState() {
        if (!btnSubmit || !inputConfirm) return;
        const expected = getCurrentExpectedName();
        const typed = inputConfirm.value.trim();
        const isMatch = Boolean(expected && typed && typed.toLowerCase() === expected.toLowerCase());
        const isImmediate = Boolean(chkImmediate && chkImmediate.checked);

        btnSubmit.disabled = !isMatch;
        btnSubmit.textContent = isImmediate
            ? 'Permanently Shred Household Now'
            : 'Schedule Household Deletion (30-Day Grace Period)';
    }

    function setDeleteStatus(msg, type = 'red') {
        if (!statusEl) return;
        const conf = {
            orange: ['rgba(245, 158, 11, 0.14)', 'var(--accent-orange)'],
            green: ['rgba(16, 185, 129, 0.14)', 'var(--status-green)'],
            red: ['rgba(239, 68, 68, 0.14)', 'var(--status-red)']
        }[type] || ['rgba(239, 68, 68, 0.14)', 'var(--status-red)'];
        statusEl.style.display = 'block';
        statusEl.style.background = conf[0];
        statusEl.style.border = `1px solid ${conf[1]}`;
        statusEl.style.color = conf[1];
        statusEl.textContent = msg;
    }

    function closeDeleteModal() {
        delModal.style.display = 'none';
        if (inputConfirm) inputConfirm.value = '';
        if (chkImmediate) chkImmediate.checked = false;
        if (statusEl) {
            statusEl.style.display = 'none';
            statusEl.textContent = '';
        }
        syncDeleteButtonState();
    }

    btnOpen.onclick = () => {
        const currentFamName = getCurrentExpectedName();
        if (expectedNameEl) expectedNameEl.textContent = currentFamName;
        if (nameDisplayEl) nameDisplayEl.textContent = currentFamName;
        if (inputConfirm) {
            inputConfirm.value = '';
            inputConfirm.placeholder = currentFamName;
        }
        if (chkImmediate) chkImmediate.checked = false;
        if (statusEl) {
            statusEl.style.display = 'none';
            statusEl.textContent = '';
        }
        syncDeleteButtonState();
        delModal.style.display = 'flex';
        if (inputConfirm) setTimeout(() => { try { inputConfirm.focus(); } catch (e) {} }, 30);
    };

    if (btnClose) btnClose.onclick = () => closeDeleteModal();
    if (btnCancel) btnCancel.onclick = () => closeDeleteModal();
    delModal.onclick = (e) => { if (e.target === delModal) closeDeleteModal(); };

    if (inputConfirm) inputConfirm.oninput = () => syncDeleteButtonState();
    if (chkImmediate) chkImmediate.onchange = () => syncDeleteButtonState();

    if (formDelete) {
        formDelete.onsubmit = async (e) => {
            e.preventDefault();
            if (!inputConfirm || !btnSubmit) return;
            const confirmName = inputConfirm.value.trim();
            const immediate = Boolean(chkImmediate && chkImmediate.checked);
            if (!confirmName) return;

            btnSubmit.disabled = true;
            btnSubmit.textContent = immediate ? 'Shredding Household Vault...' : 'Scheduling 30-Day Deletion...';
            setDeleteStatus(immediate ? 'Permanently unlinking household database and shredding encryption keys...' : 'Freezing household vault and starting 30-day recovery grace period...', 'orange');

            try {
                const resp = await fetch('/api/family/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ confirm_name: confirmName, immediate: immediate })
                });
                const res = await resp.json();
                if (resp.ok && res.success) {
                    setDeleteStatus(immediate ? '✓ Household data permanently deleted. Redirecting...' : '✓ 30-day deletion grace period scheduled. Redirecting...', 'green');
                    window.location.href = res.redirect || (immediate ? '/login?deleted=1' : '/account-recovery');
                } else {
                    setDeleteStatus(res.error || 'Failed to delete household.', 'red');
                    syncDeleteButtonState();
                }
            } catch (err) {
                setDeleteStatus(`Network error: ${err.message}`, 'red');
                syncDeleteButtonState();
            }
        };
    }
}

function bindLocalDesktopControls() {
    const btnOpenBrowser = document.getElementById('btn-desktop-open-browser');
    const btnChangePin = document.getElementById('btn-desktop-change-pin');
    const changePinPanel = document.getElementById('desktop-change-pin-panel');
    const inputNewPin = document.getElementById('input-desktop-new-pin');
    const btnSaveNewPin = document.getElementById('btn-save-desktop-new-pin');
    const btnRecoveryKey = document.getElementById('btn-desktop-recovery-key');
    const btnRestore = document.getElementById('btn-desktop-restore');
    const inputRestoreFile = document.getElementById('input-desktop-restore-file');
    const btnHelp = document.getElementById('btn-desktop-help');
    const helpPanel = document.getElementById('desktop-help-panel');
    const btnReveal = document.getElementById('btn-desktop-reveal-folder');
    const btnCheckUpdate = document.getElementById('btn-desktop-check-update');
    const btnShutdown = document.getElementById('btn-desktop-shutdown');
    const statusEl = document.getElementById('desktop-controls-status');

    const setStatus = (msg, color) => {
        if (statusEl) { statusEl.textContent = msg; if (color) statusEl.style.color = color; }
    };

    if (btnHelp && helpPanel) {
        btnHelp.onclick = () => { helpPanel.style.display = helpPanel.style.display === 'none' ? 'block' : 'none'; };
    }

    if (btnRecoveryKey) {
        btnRecoveryKey.onclick = async () => {
            btnRecoveryKey.disabled = true;
            try {
                const resp = await fetch('/api/desktop/recovery-key');
                const data = await resp.json();
                if (data && data.success && data.recovery_key) {
                    if (navigator.clipboard && navigator.clipboard.writeText) await navigator.clipboard.writeText(data.recovery_key);
                    setStatus('✓ 44-character Local Recovery Key copied to clipboard. Save it in your password manager!', 'var(--status-green)');
                } else setStatus((data && data.error) || 'Could not retrieve Recovery Key', 'var(--status-red)');
            } catch (err) { setStatus('Error: ' + err.message, 'var(--status-red)'); }
            finally { btnRecoveryKey.disabled = false; }
        };
    }

    if (btnRestore && inputRestoreFile) {
        btnRestore.onclick = () => inputRestoreFile.click();
        inputRestoreFile.onchange = async () => {
            const file = inputRestoreFile.files && inputRestoreFile.files[0];
            if (!file) return;
            const confirmed = typeof window.showModalConfirm === 'function'
                ? await window.showModalConfirm(`Restore household vault from "${file.name}"? A safety backup will be created first.`, { title: 'Restore Vault Backup', confirmText: 'Restore Vault', confirmVariant: 'primary' })
                : confirm(`Restore household vault from "${file.name}"?`);
            if (!confirmed) { inputRestoreFile.value = ''; return; }

            btnRestore.disabled = true;
            if (typeof window.showProcessingModal === 'function') window.showProcessingModal('Restoring Vault Backup...', 'Uploading and verifying archive...');
            setStatus('Restoring .fovault backup...', 'var(--accent-blue)');

            try {
                const fd = new FormData();
                fd.append('file', file); fd.append('backup_file', file); fd.append('vault_file', file);
                const resp = await fetch('/api/desktop/restore_async', { method: 'POST', body: fd });
                let data = await resp.json();
                if (resp.ok && data && data.job_id && data.status === 'processing') {
                    let polls = 60;
                    while (polls-- > 0) {
                        await new Promise(r => setTimeout(r, 600));
                        const pResp = await fetch(`/api/jobs/${encodeURIComponent(data.job_id)}`);
                        if (pResp.ok) {
                            const pData = await pResp.json();
                            if (pData.status === 'completed' || pData.status === 'done') { data = pData; break; }
                            if (pData.status === 'failed' || pData.error) { data = { success: false, error: pData.error || 'Restore failed.' }; break; }
                        }
                    }
                }
                if (typeof window.hideProcessingModal === 'function') window.hideProcessingModal();
                if (resp.ok && data && data.success) {
                    setStatus('✓ Vault restored!', 'var(--status-green)');
                    if (typeof window.showModalAlert === 'function') {
                        await window.showModalAlert(data.summary?.summary_text || data.message || 'Vault backup restored successfully.', { title: 'Vault Backup Restored', type: 'success' });
                    }
                    window.location.reload();
                } else {
                    const errMsg = (data && data.error) || 'Failed to restore .fovault backup';
                    setStatus(errMsg, 'var(--status-red)');
                    if (typeof window.showModalAlert === 'function') await window.showModalAlert('Vault Restore Failed: ' + errMsg, { title: 'Restore Error', type: 'error' });
                }
            } catch (err) {
                if (typeof window.hideProcessingModal === 'function') window.hideProcessingModal();
                setStatus('Restore error: ' + err.message, 'var(--status-red)');
                if (typeof window.showModalAlert === 'function') await window.showModalAlert('Vault Restore Failed: ' + err.message, { title: 'Restore Error', type: 'error' });
            } finally {
                if (typeof window.hideProcessingModal === 'function') window.hideProcessingModal();
                btnRestore.disabled = false;
                inputRestoreFile.value = '';
            }
        };
    }

    if (btnChangePin && changePinPanel) {
        btnChangePin.onclick = () => { changePinPanel.style.display = changePinPanel.style.display === 'none' ? 'block' : 'none'; };
    }

    if (btnSaveNewPin && inputNewPin) {
        btnSaveNewPin.onclick = async () => {
            const newPin = (inputNewPin.value || '').trim();
            if (newPin.length < 4) { setStatus('New PIN / Passphrase must be at least 4 characters.', 'var(--status-red)'); return; }
            btnSaveNewPin.disabled = true;
            try {
                const resp = await fetch('/api/desktop/change-passphrase', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ new_passphrase: newPin })
                });
                const data = await resp.json();
                setStatus(data && data.success ? '✓ Master Passphrase / PIN updated.' : ((data && data.error) || 'Failed to update PIN'), data && data.success ? 'var(--status-green)' : 'var(--status-red)');
                if (data && data.success) { inputNewPin.value = ''; if (changePinPanel) changePinPanel.style.display = 'none'; }
            } catch (err) { setStatus('Error: ' + err.message, 'var(--status-red)'); }
            finally { btnSaveNewPin.disabled = false; }
        };
    }

    if (btnOpenBrowser) {
        btnOpenBrowser.onclick = async () => {
            try {
                const data = await (await fetch('/api/desktop/open-browser', { method: 'POST' })).json();
                setStatus(data && data.success ? `✓ Opened ${data.url} in browser` : (data.error || 'Could not open browser'), data && data.success ? 'var(--status-green)' : 'var(--status-red)');
            } catch (err) { setStatus('Error: ' + err.message, 'var(--status-red)'); }
        };
    }

    if (btnReveal) {
        btnReveal.onclick = async () => {
            const orig = btnReveal.textContent;
            btnReveal.textContent = 'Opening...'; btnReveal.disabled = true;
            try {
                const data = await (await fetch('/api/desktop/reveal-folder', { method: 'POST' })).json();
                setStatus(data && data.success ? `✓ Opened ${data.data_dir}` : (data.error || 'Could not open folder'), data && data.success ? 'var(--status-green)' : 'var(--status-red)');
            } catch (err) { setStatus('Error: ' + err.message, 'var(--status-red)'); }
            finally { btnReveal.textContent = orig; btnReveal.disabled = false; }
        };
    }

    if (btnCheckUpdate) {
        btnCheckUpdate.onclick = async () => {
            btnCheckUpdate.disabled = true;
            try {
                const data = await (await fetch('/api/desktop/check-update')).json();
                if (data && data.success) {
                    if (data.update_available) {
                        setStatus(`Update available: v${data.latest_version} (running v${data.current_version}). Opening GitHub Releases...`, 'var(--accent-blue)');
                        if (data.release_url) window.open(data.release_url, '_blank', 'noopener,noreferrer');
                    } else setStatus(`✓ Up to date (v${data.current_version})`, 'var(--status-green)');
                }
            } catch (err) { setStatus('Error checking updates: ' + err.message, 'var(--status-red)'); }
            finally { btnCheckUpdate.disabled = false; }
        };
    }

    const btnResetVault = document.getElementById('btn-desktop-reset-vault');
    if (btnResetVault) {
        btnResetVault.onclick = async () => {
            const confirmed = typeof window.showModalConfirm === 'function'
                ? await window.showModalConfirm('Permanently wipe your local database files and start fresh?', { title: 'Reset Local Vault', confirmText: 'Wipe & Start Fresh', confirmVariant: 'danger' })
                : confirm('Permanently wipe your local database files and start fresh?');
            if (!confirmed) return;
            btnResetVault.disabled = true;
            try {
                const resp = await fetch('/api/desktop/reset-vault', { method: 'POST' });
                const data = await resp.json();
                if (data && data.success) window.location.href = data.redirect || '/login';
                else { alert((data && data.error) || 'Failed to reset local vault'); btnResetVault.disabled = false; }
            } catch (err) { alert('Reset error: ' + err.message); btnResetVault.disabled = false; }
        };
    }

    if (btnShutdown) {
        btnShutdown.onclick = async () => {
            const confirmed = typeof window.showModalConfirm === 'function'
                ? await window.showModalConfirm('Lock your local household vault and shut down the background server?', { title: 'Shut Down Local Server', confirmText: 'Lock & Shut Down', confirmVariant: 'danger' })
                : confirm('Shut down the local background server?');
            if (!confirmed) return;
            try {
                await fetch('/api/desktop/shutdown', { method: 'POST' });
                document.body.innerHTML = '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;text-align:center;padding:24px;"><h2>Local HVL Family Office Server Stopped</h2><p style="color:#94A3B8;max-width:460px;">Your encrypted vault is locked. You can close this browser tab.</p></div>';
            } catch (err) { setStatus('Server stopped.'); }
        };
    }
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        updateSupportAccessUi,
        bindSupportAccessToggle,
        bindDeleteHouseholdControls,
        bindLocalDesktopControls
    });
}
