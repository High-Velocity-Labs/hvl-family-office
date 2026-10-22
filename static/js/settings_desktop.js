/**
 * Settings & Tenant Management - Offline Local Desktop Vault Controls
 * Handles local PIN/passphrase rotation, recovery key export, .fovault restore, and server lifecycle.
 */

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
        if (!statusEl) return;
        statusEl.textContent = msg;
        if (color) statusEl.style.color = color;
    };

    const togglePanel = (panel) => {
        if (!panel) return;
        panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
    };

    if (btnHelp && helpPanel) {
        btnHelp.onclick = () => togglePanel(helpPanel);
    }

    if (btnRecoveryKey) {
        btnRecoveryKey.onclick = async () => {
            btnRecoveryKey.disabled = true;
            try {
                const resp = await fetch('/api/desktop/recovery-key');
                const data = await resp.json();
                if (data && data.success && data.recovery_key) {
                    if (navigator.clipboard && navigator.clipboard.writeText) {
                        await navigator.clipboard.writeText(data.recovery_key);
                    }
                    setStatus('✓ 44-character Local Recovery Key copied to clipboard. Save it in your password manager!', 'var(--status-green)');
                } else {
                    setStatus((data && data.error) || 'Could not retrieve Recovery Key', 'var(--status-red)');
                }
            } catch (err) {
                setStatus('Error: ' + err.message, 'var(--status-red)');
            } finally {
                btnRecoveryKey.disabled = false;
            }
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
            if (!confirmed) {
                inputRestoreFile.value = '';
                return;
            }

            btnRestore.disabled = true;
            if (typeof window.showProcessingModal === 'function') {
                window.showProcessingModal('Restoring Vault Backup...', 'Uploading and verifying archive...');
            }
            setStatus('Restoring .fovault backup...', 'var(--accent-blue)');

            try {
                const fd = new FormData();
                fd.append('file', file);
                fd.append('backup_file', file);
                fd.append('vault_file', file);
                const resp = await fetch('/api/desktop/restore_async', { method: 'POST', body: fd });
                let data = await resp.json();
                if (resp.ok && data && data.job_id && data.status === 'processing') {
                    let polls = 60;
                    while (polls-- > 0) {
                        await new Promise(r => setTimeout(r, 600));
                        const pResp = await fetch(`/api/jobs/${encodeURIComponent(data.job_id)}`);
                        if (pResp.ok) {
                            const pData = await pResp.json();
                            if (pData.status === 'completed' || pData.status === 'done') {
                                data = pData;
                                break;
                            }
                            if (pData.status === 'failed' || pData.error) {
                                data = { success: false, error: pData.error || 'Restore failed.' };
                                break;
                            }
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
                    if (typeof window.showModalAlert === 'function') {
                        await window.showModalAlert('Vault Restore Failed: ' + errMsg, { title: 'Restore Error', type: 'error' });
                    }
                }
            } catch (err) {
                if (typeof window.hideProcessingModal === 'function') window.hideProcessingModal();
                setStatus('Restore error: ' + err.message, 'var(--status-red)');
                if (typeof window.showModalAlert === 'function') {
                    await window.showModalAlert('Vault Restore Failed: ' + err.message, { title: 'Restore Error', type: 'error' });
                }
            } finally {
                if (typeof window.hideProcessingModal === 'function') window.hideProcessingModal();
                btnRestore.disabled = false;
                inputRestoreFile.value = '';
            }
        };
    }

    if (btnChangePin && changePinPanel) {
        btnChangePin.onclick = () => togglePanel(changePinPanel);
    }

    if (btnSaveNewPin && inputNewPin) {
        btnSaveNewPin.onclick = async () => {
            const newPin = (inputNewPin.value || '').trim();
            if (newPin.length < 4) {
                setStatus('New PIN / Passphrase must be at least 4 characters.', 'var(--status-red)');
                return;
            }
            btnSaveNewPin.disabled = true;
            try {
                const resp = await fetch('/api/desktop/change-passphrase', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ new_passphrase: newPin })
                });
                const data = await resp.json();
                setStatus(
                    data && data.success ? '✓ Master Passphrase / PIN updated.' : ((data && data.error) || 'Failed to update PIN'),
                    data && data.success ? 'var(--status-green)' : 'var(--status-red)'
                );
                if (data && data.success) {
                    inputNewPin.value = '';
                    if (changePinPanel) changePinPanel.style.display = 'none';
                }
            } catch (err) {
                setStatus('Error: ' + err.message, 'var(--status-red)');
            } finally {
                btnSaveNewPin.disabled = false;
            }
        };
    }

    if (btnOpenBrowser) {
        btnOpenBrowser.onclick = async () => {
            try {
                const data = await (await fetch('/api/desktop/open-browser', { method: 'POST' })).json();
                setStatus(data && data.success ? `✓ Opened ${data.url} in browser` : (data.error || 'Could not open browser'), data && data.success ? 'var(--status-green)' : 'var(--status-red)');
            } catch (err) {
                setStatus('Error: ' + err.message, 'var(--status-red)');
            }
        };
    }

    if (btnReveal) {
        btnReveal.onclick = async () => {
            const orig = btnReveal.textContent;
            btnReveal.textContent = 'Opening...';
            btnReveal.disabled = true;
            try {
                const data = await (await fetch('/api/desktop/reveal-folder', { method: 'POST' })).json();
                setStatus(data && data.success ? `✓ Opened ${data.data_dir}` : (data.error || 'Could not open folder'), data && data.success ? 'var(--status-green)' : 'var(--status-red)');
            } catch (err) {
                setStatus('Error: ' + err.message, 'var(--status-red)');
            } finally {
                btnReveal.textContent = orig;
                btnReveal.disabled = false;
            }
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
                    } else {
                        setStatus(`✓ Up to date (v${data.current_version})`, 'var(--status-green)');
                    }
                }
            } catch (err) {
                setStatus('Error checking updates: ' + err.message, 'var(--status-red)');
            } finally {
                btnCheckUpdate.disabled = false;
            }
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
                if (data && data.success) {
                    window.location.href = data.redirect || '/login';
                } else {
                    alert((data && data.error) || 'Failed to reset local vault');
                    btnResetVault.disabled = false;
                }
            } catch (err) {
                alert('Reset error: ' + err.message);
                btnResetVault.disabled = false;
            }
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
            } catch (err) {
                setStatus('Server stopped.');
            }
        };
    }
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        bindLocalDesktopControls
    });
}
