/**
 * Settings & Tenant Management - Security & Support Escrow
 * Handles support access toggles and 30-day household deletion controls.
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

if (typeof window !== 'undefined') {
    Object.assign(window, {
        updateSupportAccessUi,
        bindSupportAccessToggle,
        bindDeleteHouseholdControls
    });
}
