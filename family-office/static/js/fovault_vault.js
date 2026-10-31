/**
 * .fovault passphrase prompts + export download. Markup lives in templates/components/fovault_modals.html;
 * this file only reads field values, toggles `hidden`, and calls the SSR endpoints. The passphrase is held in
 * the (cleared-on-close) input elements and the request body only.
 */
(function () {
    const MIN_LEN = 12;

    function byId(id) { return document.getElementById(id); }

    function showPrompt(modalId, fieldIds, errorId, onConfirm) {
        const modal = byId(modalId);
        if (!modal) return Promise.resolve(null);
        return new Promise((resolve) => {
            const errEl = byId(errorId);
            const clear = () => {
                fieldIds.forEach((fid) => {
                    const el = byId(fid);
                    if (el && el.type === 'checkbox') el.checked = false;
                    else if (el) el.value = '';
                });
                if (errEl) errEl.textContent = '';
            };
            const close = (value) => {
                modal.hidden = true;
                modal.removeEventListener('click', onClick);
                clear();
                resolve(value);
            };
            const onClick = (ev) => {
                const btn = ev.target.closest ? ev.target.closest('[data-fovault-action]') : null;
                if (!btn) return;
                if (btn.dataset.fovaultAction === 'cancel') return close(null);
                const result = onConfirm();
                if (result.error) {
                    if (errEl) errEl.textContent = result.error;
                    return;
                }
                close(result.value);
            };
            clear();
            modal.addEventListener('click', onClick);
            modal.hidden = false;
            const first = byId(fieldIds[0]);
            if (first && first.focus) first.focus();
        });
    }

    function promptExport() {
        return showPrompt('fovault-export-modal', ['fovault-export-passphrase', 'fovault-export-confirm'], 'fovault-export-error', () => {
            const passphrase = byId('fovault-export-passphrase').value;
            const confirm = byId('fovault-export-confirm').value;
            if (passphrase.length < MIN_LEN) return { error: `Choose a passphrase of at least ${MIN_LEN} characters.` };
            if (passphrase !== confirm) return { error: 'The passphrase and its confirmation do not match.' };
            return { value: { passphrase, confirm } };
        });
    }

    function promptRestore(fileName) {
        const nameEl = byId('fovault-restore-file');
        if (nameEl) nameEl.textContent = fileName || 'this file';
        return showPrompt('fovault-restore-modal', ['fovault-restore-passphrase', 'fovault-restore-legacy'], 'fovault-restore-error', () => {
            const passphrase = byId('fovault-restore-passphrase').value;
            const allowLegacy = byId('fovault-restore-legacy').checked;
            if (!passphrase && !allowLegacy) return { error: 'Enter the passphrase for this backup.' };
            return { value: { passphrase, allowLegacy } };
        });
    }

    /** Appends the restore credentials to a FormData body (POST body only, never the URL). */
    function appendRestoreFields(formData, creds) {
        formData.append('passphrase', creds.passphrase || '');
        if (creds.allowLegacy) formData.append('allow_legacy', '1');
    }

    /** Prompts for an export passphrase, POSTs it, and saves the returned .fovault. Resolves false if cancelled. */
    async function exportVault(url, filePrefix) {
        const creds = await promptExport();
        if (!creds) return false;
        const resp = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ passphrase: creds.passphrase, passphrase_confirm: creds.confirm })
        });
        if (!resp.ok) {
            const data = await resp.json().catch(() => ({}));
            throw new Error(data.error || 'Backup export failed.');
        }
        const blob = await resp.blob();
        const href = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = href;
        a.download = `${filePrefix}_${new Date().toISOString().slice(0, 10)}.fovault`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(href), 1000);
        return true;
    }

    window.FovaultVault = { promptExport, promptRestore, appendRestoreFields, exportVault };
})();
