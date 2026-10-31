/**
 * Accounts & Holdings & Balance Sheet Buckets Module
 * Server-rendered via /fragments/accounts and morphed via HTMX + Idiomorph.
 */

function _todayIsoDate() {
    return new Date().toISOString().slice(0, 10);
}

async function _notifyAccountError(errMsg, title, msgEl) {
    if (msgEl) {
        msgEl.style.color = 'var(--status-red)';
        msgEl.textContent = errMsg;
    }
    if (typeof window.showModalAlert === 'function') {
        await window.showModalAlert(errMsg, { title: title || 'Notice', type: 'error' });
    } else if (window.showToast) {
        window.showToast(errMsg, 'error');
    }
}

function bindAccountToggles() {
    if (document.body && !document.body.dataset.accountsDelegated) {
        document.body.dataset.accountsDelegated = 'true';
        document.addEventListener('change', async (e) => {
            const checkbox = e.target.closest('.toggle-acc-nw');
            if (!checkbox) return;
            const accId = checkbox.getAttribute('data-acc-id');
            const included = checkbox.checked;
            try {
                const resp = await fetch('/api/accounts/toggle_net_worth', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ account_id: accId, include_in_net_worth: included })
                });
                const res = await resp.json();
                if (!res.success) {
                    await _notifyAccountError('Error toggling account: ' + res.error, 'Notice');
                }
            } catch (err) {
                await _notifyAccountError('Failed: ' + err.message, 'Notice');
            }
        });
    }
}

function openManualAccountForm(accData) {
    const card = document.getElementById('manual-account-form-card');
    if (!card) return;
    const [idEl, nameEl, roleEl, instEl, balEl, dateEl, titleEl, msgEl] = [
        'manual-acc-id', 'manual-acc-name', 'manual-acc-role', 'manual-acc-institution',
        'manual-acc-balance', 'manual-acc-date', 'manual-acc-form-title', 'manual-acc-status-msg'
    ].map(id => document.getElementById(id));
    if (msgEl) msgEl.textContent = '';
    const isEdit = Boolean(accData && accData.id);
    if (titleEl) titleEl.textContent = isEdit ? 'Edit Manual Account' : 'Add Manual Account';
    if (idEl) idEl.value = isEdit ? accData.id : '';
    if (nameEl) nameEl.value = (isEdit && accData.name) || '';
    if (roleEl) roleEl.value = (isEdit && accData.role) || 'public_brokerage';
    if (instEl) instEl.value = (isEdit && accData.institution) || 'Manual Entry';
    if (balEl) balEl.value = (isEdit && accData.balance !== undefined) ? accData.balance : '';
    if (dateEl) dateEl.value = (isEdit && accData.as_of_date) || _todayIsoDate();
    card.style.display = 'block';
    if (nameEl) nameEl.focus();
}

function closeManualAccountForm() {
    const card = document.getElementById('manual-account-form-card');
    if (card) card.style.display = 'none';
}

function editManualAccount(accId) {
    const row = document.querySelector(`tr[data-manual-acc-id="${accId}"]`);
    if (!row) return;
    openManualAccountForm({
        id: accId,
        name: row.getAttribute('data-manual-acc-name') || '',
        role: row.getAttribute('data-manual-acc-role') || 'public_brokerage',
        institution: row.getAttribute('data-manual-acc-inst') || 'Manual Entry',
        balance: row.getAttribute('data-manual-acc-balance') || '0',
    });
}

async function saveManualAccount() {
    const idEl = document.getElementById('manual-acc-id');
    const nameEl = document.getElementById('manual-acc-name');
    const roleEl = document.getElementById('manual-acc-role');
    const instEl = document.getElementById('manual-acc-institution');
    const balEl = document.getElementById('manual-acc-balance');
    const dateEl = document.getElementById('manual-acc-date');
    const msgEl = document.getElementById('manual-acc-status-msg');

    const name = (nameEl ? nameEl.value : '').trim();
    const role = roleEl ? roleEl.value : 'public_brokerage';
    const institution = (instEl ? instEl.value : 'Manual Entry').trim() || 'Manual Entry';
    const balance = parseFloat(balEl && balEl.value ? balEl.value : '0');
    const asOfDate = (dateEl ? dateEl.value : '').trim();

    if (!name) {
        if (msgEl) {
            msgEl.style.color = 'var(--status-red)';
            msgEl.textContent = 'Account Name is required.';
        }
        return;
    }

    const roleToType = {
        cash_liquid: 'depository',
        public_brokerage: 'brokerage',
        retirement: 'retirement',
        real_estate: 'real_estate',
        mortgages: 'mortgage',
        credit_cards: 'credit',
        education_529: 'education',
        other_assets: 'other',
    };

    try {
        const resp = await fetch('/api/accounts/manual', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                account_id: idEl && idEl.value ? idEl.value : undefined,
                name: name,
                role: role,
                account_type: roleToType[role] || 'brokerage',
                institution: institution,
                balance: isNaN(balance) ? 0 : balance,
                as_of_date: asOfDate || undefined,
                include_in_net_worth: role !== 'education_529',
            }),
        });
        const res = await resp.json();
        if (resp.ok && res.success) {
            closeManualAccountForm();
        } else {
            await _notifyAccountError(res.error || 'Failed to save manual account.', 'Unable to Save Account', msgEl);
        }
    } catch (err) {
        await _notifyAccountError('Request failed: ' + err.message, 'Unable to Save Account', msgEl);
    }
}

async function deleteManualAccount(accId) {
    if (!accId || !accId.startsWith('manual_')) return;
    const confirmMsg = 'Remove this manual account from your household balance sheet?';
    const confirmed = typeof window.showModalConfirm === 'function'
        ? await window.showModalConfirm(confirmMsg, { title: 'Delete Manual Account', confirmText: 'Delete', confirmVariant: 'danger', danger: true })
        : confirm(confirmMsg);
    if (!confirmed) return;
    try {
        const resp = await fetch('/api/accounts/manual/' + encodeURIComponent(accId), {
            method: 'DELETE',
        });
        const res = await resp.json();
        if (!res.success) {
            await _notifyAccountError('Error deleting manual account: ' + (res.error || 'Unknown error'), 'Delete Failed');
        }
    } catch (err) {
        await _notifyAccountError('Failed: ' + err.message, 'Delete Failed');
    }
}

function toggleBalanceHistoryPanel(forceShow) {
    const card = document.getElementById('balance-history-card');
    if (!card) return;
    const isHidden = card.style.display === 'none' || !card.style.display;
    const show = typeof forceShow === 'boolean' ? forceShow : isHidden;
    card.style.display = show ? 'block' : 'none';
    if (show) {
        const dateEl = document.getElementById('hist-snap-date');
        if (dateEl && !dateEl.value) {
            dateEl.value = _todayIsoDate();
        }
    }
}

function editBalanceSnapshot(btnOrAccId, accIdArg, dateArg) {
    if (!btnOrAccId) return;
    let row = null;
    if (typeof btnOrAccId === 'object' && typeof btnOrAccId.closest === 'function') {
        row = btnOrAccId.closest('tr');
    } else if (typeof btnOrAccId === 'string') {
        const lookupDate = accIdArg || dateArg || '';
        row = document.querySelector(`tr[data-snap-acc-id="${CSS.escape(btnOrAccId)}"][data-snap-date="${CSS.escape(lookupDate)}"]`)
            || document.querySelector(`tr[data-snap-acc-id="${CSS.escape(btnOrAccId)}"]`);
    }
    if (!row && accIdArg) {
        row = document.querySelector(`tr[data-snap-acc-id="${CSS.escape(accIdArg)}"][data-snap-date="${CSS.escape(dateArg || '')}"]`);
    }
    if (!row) return;
    toggleBalanceHistoryPanel(true);
    const accIdEl = document.getElementById('hist-snap-acc-id');
    const nameEl = document.getElementById('hist-snap-acc-name');
    const roleEl = document.getElementById('hist-snap-role');
    const instEl = document.getElementById('hist-snap-institution');
    const dateEl = document.getElementById('hist-snap-date');
    const balEl = document.getElementById('hist-snap-balance');

    if (accIdEl) accIdEl.value = row.getAttribute('data-snap-acc-id') || '';
    if (nameEl) nameEl.value = row.getAttribute('data-snap-acc-name') || '';
    if (roleEl) roleEl.value = row.getAttribute('data-snap-role') || 'public_brokerage';
    if (instEl) instEl.value = row.getAttribute('data-snap-inst') || 'Manual Entry';
    if (dateEl) dateEl.value = row.getAttribute('data-snap-date') || _todayIsoDate();
    if (balEl) {
        balEl.value = row.getAttribute('data-snap-balance') || '';
        balEl.focus();
    }
}

async function saveBalanceSnapshot() {
    const accIdEl = document.getElementById('hist-snap-acc-id');
    const nameEl = document.getElementById('hist-snap-acc-name');
    const roleEl = document.getElementById('hist-snap-role');
    const instEl = document.getElementById('hist-snap-institution');
    const dateEl = document.getElementById('hist-snap-date');
    const balEl = document.getElementById('hist-snap-balance');
    const msgEl = document.getElementById('balance-history-status-msg');

    const accountName = (nameEl ? nameEl.value : '').trim();
    const role = roleEl ? roleEl.value : 'public_brokerage';
    const institution = (instEl ? instEl.value : 'Manual Entry').trim() || 'Manual Entry';
    const asOfDate = (dateEl ? dateEl.value : '').trim() || _todayIsoDate();
    const balance = parseFloat(balEl && balEl.value ? balEl.value : 'NaN');

    if (!accountName) {
        if (msgEl) {
            msgEl.style.color = 'var(--status-red)';
            msgEl.textContent = 'Account Name is required.';
        }
        return;
    }
    if (isNaN(balance)) {
        if (msgEl) {
            msgEl.style.color = 'var(--status-red)';
            msgEl.textContent = 'Valid numeric balance is required.';
        }
        return;
    }

    try {
        const resp = await fetch('/api/accounts/history', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                account_id: accIdEl && accIdEl.value ? accIdEl.value : undefined,
                account_name: accountName,
                role: role,
                institution: institution,
                as_of_date: asOfDate,
                balance: balance,
                source: 'manual',
            }),
        });
        const res = await resp.json();
        if (resp.ok && res.success) {
            if (accIdEl) accIdEl.value = '';
            toggleBalanceHistoryPanel(true);
            const updatedMsgEl = document.getElementById('balance-history-status-msg');
            if (updatedMsgEl) {
                updatedMsgEl.style.color = 'var(--accent-emerald)';
                updatedMsgEl.textContent = `Saved snapshot for ${accountName} (${asOfDate}).`;
            }
        } else {
            const errMsg = res.error || 'Failed to save balance snapshot.';
            if (msgEl) {
                msgEl.style.color = 'var(--status-red)';
                msgEl.textContent = errMsg;
            }
        }
    } catch (err) {
        if (msgEl) {
            msgEl.style.color = 'var(--status-red)';
            msgEl.textContent = 'Request failed: ' + err.message;
        }
    }
}

async function deleteBalanceSnapshot(accountId, asOfDate) {
    if (!accountId || !asOfDate) return;
    const confirmMsg = `Delete balance snapshot for ${asOfDate}?`;
    const confirmed = typeof window.showModalConfirm === 'function'
        ? await window.showModalConfirm(confirmMsg, { title: 'Delete Balance Snapshot', confirmText: 'Delete', confirmVariant: 'danger', danger: true })
        : confirm(confirmMsg);
    if (!confirmed) return;
    const msgEl = document.getElementById('balance-history-status-msg');
    try {
        const resp = await fetch('/api/accounts/history', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ account_id: accountId, as_of_date: asOfDate }),
        });
        const res = await resp.json();
        if (resp.ok && res.success) {
            toggleBalanceHistoryPanel(true);
        } else if (msgEl) {
            msgEl.style.color = 'var(--status-red)';
            msgEl.textContent = res.error || 'Failed to delete snapshot.';
        }
    } catch (err) {
        if (msgEl) {
            msgEl.style.color = 'var(--status-red)';
            msgEl.textContent = 'Delete failed: ' + err.message;
        }
    }
}

async function importBalancesCsv() {
    const fileInput = document.getElementById('csv-balance-file');
    const msgEl = document.getElementById('balance-history-status-msg');
    if (!fileInput || !fileInput.files || !fileInput.files[0]) {
        if (msgEl) {
            msgEl.style.color = 'var(--status-red)';
            msgEl.textContent = 'Please select a CSV file to import.';
        }
        return;
    }

    try {
        const csvText = await fileInput.files[0].text();
        const resp = await fetch('/api/accounts/import_csv', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ csv_text: csvText }),
        });
        const res = await resp.json();
        if (resp.ok && res.success) {
            fileInput.value = '';
            toggleBalanceHistoryPanel(true);
            const updatedMsgEl = document.getElementById('balance-history-status-msg');
            if (updatedMsgEl) {
                updatedMsgEl.style.color = 'var(--accent-emerald)';
                updatedMsgEl.textContent = `Imported ${res.imported || 0} snapshot(s) across ${res.accounts_updated || 0} account(s).`;
            }
        } else if (msgEl) {
            msgEl.style.color = 'var(--status-red)';
            msgEl.textContent = res.error || 'CSV import failed.';
        }
    } catch (err) {
        if (msgEl) {
            msgEl.style.color = 'var(--status-red)';
            msgEl.textContent = 'Import failed: ' + err.message;
        }
    }
}

async function applyCalibratedCoreBurn() {
    const msgEl = document.getElementById('core-burn-status-msg');
    if (msgEl) { msgEl.style.color = 'var(--accent-blue)'; msgEl.textContent = 'Applying...'; }
    try {
        const resp = await fetch('/api/tax/apply_core_burn', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });
        const res = await resp.json();
        if (resp.ok && res.success) {
            if (msgEl) { msgEl.style.color = 'var(--status-green)'; msgEl.textContent = '✓ Applied'; }
            if (typeof window.showToast === 'function') window.showToast(res.message || 'Applied core burn to baseline plan.', 'success');
        } else {
            await _notifyAccountError(res.error || 'Failed to apply core burn.', 'Notice', msgEl);
        }
    } catch (err) {
        await _notifyAccountError('Failed: ' + err.message, 'Notice', msgEl);
    }
}

Object.assign(window, {
    openManualAccountForm, closeManualAccountForm, editManualAccount, saveManualAccount,
    deleteManualAccount, toggleBalanceHistoryPanel, editBalanceSnapshot, saveBalanceSnapshot,
    deleteBalanceSnapshot, importBalancesCsv, applyCalibratedCoreBurn,
    renderAccounts: bindAccountToggles, bindAccountToggles,
});

if (typeof window !== 'undefined' && typeof window.registerSectionHydrator === 'function') {
    window.registerSectionHydrator('section-accounts', bindAccountToggles, { needsDashboard: true });
}

document.addEventListener('DOMContentLoaded', () => {
    bindAccountToggles();
});



