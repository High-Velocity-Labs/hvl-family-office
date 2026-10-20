/**
 * Settings & Tenant Management - Account Classifications & Roles Module
 * Handles mapping Monarch/SimpleFIN accounts to balance sheet roles and beneficiary owners.
 */

function bindSettingsRolesTable() {
    const tbody = document.getElementById('settings-roles-tbody');
    if (tbody) {
        tbody.querySelectorAll('tr').forEach(tr => {
            const btnSave = tr.querySelector('.btn-save-acc-role');
            const selRole = tr.querySelector('.select-acc-role');
            const selBen = tr.querySelector('.select-acc-ben');
            const chkHide = tr.querySelector('.check-acc-hide-fo');
            const accId = (btnSave && btnSave.getAttribute('data-id')) || tr.getAttribute('data-acc-id');

            if (selRole && chkHide) {
                selRole.onchange = () => {
                    const r = selRole.value;
                    if (['company_equity_nso', 'tax_liability', 'hidden_from_family_office', 'manual_tax_offset'].includes(r)) {
                        chkHide.checked = true;
                    }
                };
            }

            if (btnSave && selRole && selBen && chkHide && accId) {
                btnSave.onclick = async () => {
                    btnSave.textContent = '...';
                    try {
                        const postResp = await fetch('/api/settings/account_roles', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                account_id: accId,
                                role: selRole.value,
                                beneficiary_user_id: selBen.value || null,
                                is_hidden_from_family_office: chkHide.checked
                            })
                        });
                        const postRes = await postResp.json();
                        if (postRes.success) {
                            if (typeof morphSettingsModal === 'function') {
                                await morphSettingsModal({ tab: 'roles' });
                            }
                        } else {
                            if (typeof window.showModalAlert === 'function') {
                                await window.showModalAlert(`Error: ${postRes.error}`, { title: 'Save Role Error', type: 'error' });
                            } else {
                                alert(`Error: ${postRes.error}`);
                            }
                            btnSave.textContent = 'Save';
                        }
                    } catch (err) {
                        if (typeof window.showModalAlert === 'function') {
                            await window.showModalAlert(`Error: ${err.message}`, { title: 'Save Role Error', type: 'error' });
                        } else {
                            alert(`Error: ${err.message}`);
                        }
                        btnSave.textContent = 'Save';
                    }
                };
            }
        });
    }

    const btnConfirmAll = document.getElementById('btn-confirm-all-roles');
    const statusConfirmAll = document.getElementById('confirm-all-roles-status');
    if (btnConfirmAll) {
        btnConfirmAll.onclick = async () => {
            if (statusConfirmAll) {
                statusConfirmAll.textContent = 'Locking all accounts...';
                statusConfirmAll.style.color = 'var(--accent-orange)';
            }
            try {
                const resp = await fetch('/api/settings/confirm_all_roles', { method: 'POST' });
                const res = await resp.json();
                if (res.success) {
                    if (typeof morphSettingsModal === 'function') {
                        await morphSettingsModal({ tab: 'roles' });
                    }
                    const updatedStatus = document.getElementById('confirm-all-roles-status');
                    if (updatedStatus) {
                        updatedStatus.textContent = `✓ ${res.message}`;
                        updatedStatus.style.color = 'var(--status-green)';
                        setTimeout(() => { if (updatedStatus) updatedStatus.textContent = ''; }, 2500);
                    }
                } else if (statusConfirmAll) {
                    statusConfirmAll.textContent = `Error: ${res.error}`;
                    statusConfirmAll.style.color = 'var(--status-red)';
                }
            } catch (e) {
                if (statusConfirmAll) {
                    statusConfirmAll.textContent = `Error: ${e.message}`;
                    statusConfirmAll.style.color = 'var(--status-red)';
                }
            }
        };
    }
}

if (typeof window !== 'undefined') {
    window.bindSettingsRolesTable = bindSettingsRolesTable;
}
