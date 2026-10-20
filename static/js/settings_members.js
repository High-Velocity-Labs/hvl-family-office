/**
 * Settings & Tenant Management - Household Members & Tax Profile Module
 * Handles household members CRUD, legal assumptions, and magic invite links.
 */

async function _showMemberAlert(msg, title = 'Error') {
    if (typeof window.showModalAlert === 'function') {
        await window.showModalAlert(msg, { title, type: 'error' });
    } else {
        alert(msg);
    }
}

function bindSettingsMembersTable() {
    const tbody = document.getElementById('settings-members-tbody');
    if (!tbody) return;

    tbody.querySelectorAll('.btn-edit-member').forEach(btn => {
        btn.onclick = () => {
            const uid = parseInt(btn.getAttribute('data-id'), 10);
            const member = {
                user_id: uid,
                name: btn.getAttribute('data-name') || '',
                email: btn.getAttribute('data-email') || '',
                birthdate: btn.getAttribute('data-birthdate') || '',
                relationship: btn.getAttribute('data-rel') || 'child',
                role: btn.getAttribute('data-role') || 'viewer',
            };

            const cardAddMember = document.getElementById('add-member-card');
            const cardEditMember = document.getElementById('edit-member-card');
            if (cardAddMember) cardAddMember.style.display = 'none';
            if (cardEditMember) {
                document.getElementById('input-edit-member-id').value = member.user_id;
                document.getElementById('input-edit-member-name').value = member.name || '';
                document.getElementById('input-edit-member-email').value = member.email || '';
                document.getElementById('input-edit-member-birthdate').value = member.birthdate || '';
                const selRel = document.getElementById('select-edit-member-rel');
                if (selRel && member.relationship) selRel.value = member.relationship;
                const selRole = document.getElementById('select-edit-member-role');
                if (selRole && member.role) selRole.value = member.role;

                cardEditMember.style.display = 'block';
                cardEditMember.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
        };
    });

    tbody.querySelectorAll('.btn-del-member').forEach(btn => {
        btn.onclick = async () => {
            const uid = btn.getAttribute('data-id');
            if (!await showModalConfirm('Delete family member?', { title: 'Delete Family Member', confirmText: 'Delete Member', confirmVariant: 'danger' })) return;
            try {
                const delResp = await fetch(`/api/family/members/${uid}`, { method: 'DELETE' });
                const delRes = await delResp.json();
                if (delRes.success) {
                    if (typeof morphSettingsModal === 'function') await morphSettingsModal({ tab: 'members' });
                } else {
                    await _showMemberAlert(`Error: ${delRes.error}`, 'Delete Error');
                }
            } catch (e) {
                await _showMemberAlert(`Error: ${e.message}`, 'Delete Error');
            }
        };
    });
}

function bindMagicInviteControls() {
    const btnToggle = document.getElementById('btn-create-invite-toggle');
    const cardCreate = document.getElementById('create-invite-card');
    const btnCancel = document.getElementById('btn-cancel-create-invite');
    const formCreate = document.getElementById('form-create-invite');
    const selType = document.getElementById('select-invite-type');
    const selRole = document.getElementById('select-invite-role');

    if (btnToggle && cardCreate) {
        btnToggle.onclick = () => {
            cardCreate.style.display = cardCreate.style.display === 'none' ? 'block' : 'none';
        };
    }
    if (btnCancel && cardCreate) {
        btnCancel.onclick = () => { cardCreate.style.display = 'none'; };
    }
    if (selType && selRole) {
        selType.onchange = () => {
            if (selType.value === 'new_household') {
                selRole.value = 'editor';
                selRole.disabled = true;
            } else {
                selRole.disabled = false;
            }
        };
        if (selType.value === 'new_household') {
            selRole.value = 'editor';
            selRole.disabled = true;
        }
    }

    if (formCreate) {
        formCreate.onsubmit = async (e) => {
            e.preventDefault();
            const inviteType = selType ? selType.value : 'new_household';
            const targetRole = selRole ? selRole.value : 'editor';
            const labelEl = document.getElementById('input-invite-label');
            const maxUsesEl = document.getElementById('input-invite-max-uses');
            const daysEl = document.getElementById('input-invite-expires-days');

            try {
                const resp = await fetch('/api/family/invites', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        invite_type: inviteType,
                        target_role: targetRole,
                        label: labelEl ? labelEl.value.trim() : '',
                        max_uses: maxUsesEl ? parseInt(maxUsesEl.value, 10) || 1 : 1,
                        expires_days: daysEl ? parseInt(daysEl.value, 10) || 14 : 14,
                    }),
                });
                const res = await resp.json();
                if (resp.ok && res.success) {
                    if (typeof morphSettingsModal === 'function') {
                        await morphSettingsModal({ tab: 'members' });
                    }
                } else {
                    await _showMemberAlert(res.error || 'Unknown error', 'Unable to Create Invite');
                }
            } catch (err) {
                await _showMemberAlert(`Error creating invite: ${err.message}`, 'Unable to Create Invite');
            }
        };
    }

    const tbody = document.getElementById('settings-invites-tbody');
    if (tbody) {
        tbody.querySelectorAll('.btn-copy-invite').forEach(btn => {
            btn.onclick = async () => {
                const code = btn.getAttribute('data-code') || '';
                if (!code) return;
                const url = `${window.location.origin}/invite/${code}`;
                try {
                    if (navigator.clipboard && navigator.clipboard.writeText) {
                        await navigator.clipboard.writeText(url);
                    }
                    const orig = btn.textContent;
                    btn.textContent = '✓ Copied!';
                    setTimeout(() => { btn.textContent = orig; }, 1800);
                } catch (e) {}
            };
        });

        tbody.querySelectorAll('.btn-revoke-invite').forEach(btn => {
            btn.onclick = async () => {
                const code = btn.getAttribute('data-code') || '';
                if (!code) return;
                const confirmed = typeof window.showModalConfirm === 'function'
                    ? await window.showModalConfirm(`Revoke invite link ${code}? Anyone with this link will no longer be able to redeem it.`, {
                        title: 'Revoke Magic Invite', confirmText: 'Revoke Invite', confirmVariant: 'danger',
                    })
                    : confirm(`Revoke invite link ${code}?`);
                if (!confirmed) return;

                try {
                    const resp = await fetch(`/api/family/invites/${encodeURIComponent(code)}`, { method: 'DELETE' });
                    const res = await resp.json();
                    if (resp.ok && res.success) {
                        if (typeof morphSettingsModal === 'function') {
                            await morphSettingsModal({ tab: 'members' });
                        }
                    } else {
                        alert(`Error revoking invite: ${res.error || 'Unknown error'}`);
                    }
                } catch (err) {
                    alert(`Error revoking invite: ${err.message}`);
                }
            };
        });
    }
}

function bindSettingsMembersForms() {
    const btnToggleAdd = document.getElementById('btn-add-member-toggle');
    const cardAddMember = document.getElementById('add-member-card');
    const btnCancelAdd = document.getElementById('btn-cancel-add-member');
    const cardEditMember = document.getElementById('edit-member-card');
    const btnCancelEdit = document.getElementById('btn-cancel-edit-member');
    const btnCloseEdit = document.getElementById('btn-close-edit-member');

    if (btnToggleAdd && cardAddMember) {
        btnToggleAdd.onclick = () => {
            if (cardEditMember) cardEditMember.style.display = 'none';
            cardAddMember.style.display = cardAddMember.style.display === 'none' ? 'block' : 'none';
        };
    }
    if (btnCancelAdd && cardAddMember) {
        btnCancelAdd.onclick = () => { cardAddMember.style.display = 'none'; };
    }
    if (btnCancelEdit && cardEditMember) {
        btnCancelEdit.onclick = () => { cardEditMember.style.display = 'none'; };
    }
    if (btnCloseEdit && cardEditMember) {
        btnCloseEdit.onclick = () => { cardEditMember.style.display = 'none'; };
    }

    const formAddMember = document.getElementById('form-add-member');
    if (formAddMember) {
        formAddMember.onsubmit = async (e) => {
            e.preventDefault();
            const name = document.getElementById('input-new-member-name').value.trim();
            const email = document.getElementById('input-new-member-email').value.trim();
            const birthdate = document.getElementById('input-new-member-birthdate').value;
            const relationship = document.getElementById('select-new-member-rel').value;
            const role = document.getElementById('select-new-member-role').value;

            try {
                const resp = await fetch('/api/family/members', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, email, birthdate, relationship, role })
                });
                const res = await resp.json();
                if (resp.ok && res.success) {
                    if (cardAddMember) cardAddMember.style.display = 'none';
                    formAddMember.reset();
                    if (typeof morphSettingsModal === 'function') await morphSettingsModal({ tab: 'members' });
                } else {
                    await _showMemberAlert(res.error || 'Error adding member', 'Unable to Add Member');
                }
            } catch (err) {
                await _showMemberAlert(`Error adding member: ${err.message}`, 'Unable to Add Member');
            }
        };
    }

    const formEditMember = document.getElementById('form-edit-member');
    if (formEditMember) {
        formEditMember.onsubmit = async (e) => {
            e.preventDefault();
            const userId = document.getElementById('input-edit-member-id').value;
            const name = document.getElementById('input-edit-member-name').value.trim();
            const email = document.getElementById('input-edit-member-email').value.trim();
            const birthdate = document.getElementById('input-edit-member-birthdate').value;
            const relationship = document.getElementById('select-edit-member-rel').value;
            const role = document.getElementById('select-edit-member-role').value;

            try {
                const resp = await fetch(`/api/family/members/${userId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, email, birthdate, relationship, role })
                });
                const res = await resp.json();
                if (resp.ok && res.success) {
                    if (cardEditMember) cardEditMember.style.display = 'none';
                    if (typeof morphSettingsModal === 'function') await morphSettingsModal({ tab: 'members' });
                } else {
                    await _showMemberAlert(res.error || 'Error updating member', 'Unable to Update Member');
                }
            } catch (err) {
                await _showMemberAlert(`Error updating member: ${err.message}`, 'Unable to Update Member');
            }
        };
    }

    const formAssumptions = document.getElementById('form-assumptions');
    if (formAssumptions) {
        formAssumptions.onsubmit = async (e) => {
            e.preventDefault();
            const statusEl = document.getElementById('assumptions-status');
            const state = document.getElementById('setting-state').value;
            const filing_status = document.getElementById('setting-filing-status').value;

            if (statusEl) {
                statusEl.textContent = 'Saving tax & legal profile...';
                statusEl.style.color = 'var(--accent-orange)';
            }

            try {
                const resp = await fetch('/api/settings/assumptions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ state, filing_status })
                });
                const res = await resp.json();
                if (res.success) {
                    if (typeof morphSettingsModal === 'function') await morphSettingsModal({ tab: 'assumptions' });
                    const updatedStatus = document.getElementById('assumptions-status');
                    if (updatedStatus) {
                        updatedStatus.textContent = '✓ Tax & legal profile updated successfully.';
                        updatedStatus.style.color = 'var(--status-green)';
                    }
                    const selArbState = document.getElementById('select-residence-state');
                    if (selArbState) {
                        selArbState.value = state;
                        if (typeof window.morphArbitrageSection === 'function') {
                            window.morphArbitrageSection({ home_state: state });
                        }
                    }
                } else if (statusEl) {
                    statusEl.textContent = `Error: ${res.error}`;
                    statusEl.style.color = 'var(--status-red)';
                }
            } catch (err) {
                if (statusEl) {
                    statusEl.textContent = `Error: ${err.message}`;
                    statusEl.style.color = 'var(--status-red)';
                }
            }
        };
    }

    const btnSaveFam = document.getElementById('btn-save-family-name');
    if (btnSaveFam) {
        btnSaveFam.onclick = async () => {
            const inputFam = document.getElementById('input-settings-family-name');
            const statusFam = document.getElementById('save-family-name-status');
            const newName = inputFam ? inputFam.value.trim() : '';
            if (!newName) return;
            if (statusFam) {
                statusFam.textContent = 'Saving...';
                statusFam.style.color = 'var(--accent-orange)';
            }
            try {
                const resp = await fetch('/api/family', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: newName })
                });
                const res = await resp.json();
                if (res.success) {
                    if (typeof morphSettingsModal === 'function') await morphSettingsModal({ tab: 'members' });
                    const brandTitle = document.getElementById('family-brand-title');
                    if (brandTitle) brandTitle.textContent = newName;
                    document.title = `${newName} | Family Office Portal`;
                    const updatedStatusFam = document.getElementById('save-family-name-status');
                    if (updatedStatusFam) {
                        updatedStatusFam.textContent = '✓ Saved';
                        updatedStatusFam.style.color = 'var(--status-green)';
                        setTimeout(() => { if (updatedStatusFam) updatedStatusFam.textContent = ''; }, 2000);
                    }
                } else if (statusFam) {
                    statusFam.textContent = `Error: ${res.error}`;
                    statusFam.style.color = 'var(--status-red)';
                }
            } catch (e) {
                if (statusFam) {
                    statusFam.textContent = `Error: ${e.message}`;
                    statusFam.style.color = 'var(--status-red)';
                }
            }
        };
    }
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        bindSettingsMembersTable,
        bindMagicInviteControls,
        bindSettingsMembersForms
    });
}
