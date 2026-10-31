/**
 * Equity Modals & Grant Management Module
 * Handles grant inspection, add/edit grant modal cards, and grant mutations.
 */

const ISO_STRIKE_NOTE = 'ISO: AMT is estimated at exercise when the shares are held at year end; '
    + 'a qualifying sale is long-term gain (0/15/20% plus 3.8% NIIT)';

function openEditGrantCard(g) {
    const card = document.getElementById('equity-edit-grant-card');
    if (!card) return;

    const elId = document.getElementById('edit-grant-id');
    const selComp = document.getElementById('edit-grant-company');
    const selType = document.getElementById('edit-grant-type');
    const elNick = document.getElementById('edit-grant-nickname');
    const elDate = document.getElementById('edit-grant-date');
    const elVest = document.getElementById('edit-grant-vested-date');
    const elQty = document.getElementById('edit-grant-quantity');
    const elStrike = document.getElementById('edit-grant-strike');
    const noteStrike = document.getElementById('edit-grant-strike-note');
    const elUnvest = document.getElementById('edit-grant-unvested');
    const elOwned = document.getElementById('edit-grant-owned');
    const elBasis = document.getElementById('edit-grant-basis');
    const status = document.getElementById('edit-grant-form-status');

    if (elId) elId.value = g.grant_id || g.id || '';
    if (selComp && g.company_id) selComp.value = g.company_id;
    const gtype = String(g.grant_type || '').toLowerCase();
    const isRsu = gtype === 'rsu';
    const isIso = gtype === 'iso';
    if (selType) {
        selType.value = isRsu ? 'rsu' : (isIso ? 'iso' : 'nso');
        if (elStrike) {
            elStrike.disabled = isRsu;
            elStrike.value = isRsu ? '0.00' : (g.strike_price !== undefined ? g.strike_price : 0);
        }
        if (noteStrike) {
            if (isRsu) noteStrike.textContent = 'RSUs have $0 strike price (100% ordinary spread at vest)';
            else if (isIso) noteStrike.textContent = ISO_STRIKE_NOTE;
            else noteStrike.textContent = 'NSO: W-2 ordinary income tax on spread at exercise';
        }
    }
    if (elNick) elNick.value = g.nickname || '';
    if (elDate) elDate.value = g.grant_date || '';
    if (elVest) elVest.value = g.fully_vested_date || '';
    if (elQty) elQty.value = g.total_granted || 0;
    if (elUnvest) elUnvest.value = g.unvested_options !== undefined ? g.unvested_options : 0;
    if (elOwned) elOwned.value = g.owned_shares !== undefined ? g.owned_shares : 0;
    if (elBasis) elBasis.value = g.cost_basis !== undefined ? g.cost_basis : (g.historical_cost_basis || g.strike_price || 0);

    if (status) status.textContent = '';
    card.style.display = 'block';
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function findGrantById(gid) {
    return EquityState.grants.find(g => String(g.grant_id) === String(gid) || String(g.id) === String(gid));
}

async function showGrantDetail(g) {
    const card = document.getElementById('grant-detail-card');
    if (!card) return;
    const gid = g.grant_id || g.id;
    if (!gid) return;
    const params = new URLSearchParams({ grant_id: String(gid) });
    if (EquityState.simulatedPrice > 0) params.set('share_price', String(EquityState.simulatedPrice));
    if (EquityState.companyId && EquityState.companyId !== 'all') {
        params.set('company_id', String(EquityState.companyId));
    }
    const url = `/fragments/equity_grant_detail?${params.toString()}`;
    await window.htmx.ajax('GET', url, { target: '#grant-detail-card', swap: 'morph' });
    card.style.display = 'block';
}

function initEquityModals() {
    if (document.body.dataset.equityModalsDelegated === 'true') return;
    document.body.dataset.equityModalsDelegated = 'true';

    document.addEventListener('click', async (e) => {
        if (e.target.closest('#btn-toggle-equity-grant')) {
            const cardGrant = document.getElementById('equity-grant-card');
            if (cardGrant) {
                cardGrant.style.display = cardGrant.style.display === 'none' ? 'block' : 'none';
                if (cardGrant.style.display === 'block') {
                    const today = new Date().toISOString().split('T')[0];
                    const inDate = document.getElementById('input-grant-date');
                    if (inDate && !inDate.value) inDate.value = today;
                }
            }
            return;
        }
        if (e.target.closest('#btn-close-equity-grant') || e.target.closest('#btn-cancel-equity-grant')) {
            const cardGrant = document.getElementById('equity-grant-card');
            if (cardGrant) cardGrant.style.display = 'none';
            return;
        }

        if (e.target.closest('#btn-close-edit-equity-grant') || e.target.closest('#btn-cancel-edit-equity-grant')) {
            const cardEditGrant = document.getElementById('equity-edit-grant-card');
            if (cardEditGrant) cardEditGrant.style.display = 'none';
            return;
        }

        if (e.target.closest('#btn-close-grant-detail')) {
            const card = document.getElementById('grant-detail-card');
            if (card) card.style.display = 'none';
            return;
        }

        const inspectEditBtn = e.target.closest('#btn-inspect-edit-grant');
        if (inspectEditBtn) {
            const gid = inspectEditBtn.getAttribute('data-edit-grant-id');
            if (typeof loadSsrEquityDataIfAvailable === 'function') loadSsrEquityDataIfAvailable();
            const grant = findGrantById(gid);
            if (grant) openEditGrantCard(grant);
            return;
        }

        const inspectDelBtn = e.target.closest('#grant-detail-card [data-del-grant-id]');
        if (inspectDelBtn) {
            const gid = inspectDelBtn.getAttribute('data-del-grant-id');
            if (typeof loadSsrEquityDataIfAvailable === 'function') loadSsrEquityDataIfAvailable();
            const grant = findGrantById(gid);
            const label = grant ? grant.nickname : 'this grant';
            if (window.showModalConfirm && !await window.showModalConfirm(`Are you sure you want to delete ${label}?`, { title: 'Delete Equity Grant', confirmText: 'Delete Grant', confirmVariant: 'danger' })) return;
            try {
                const resp = await fetch(`/api/equity/grant/${gid}`, { method: 'DELETE' });
                const res = await resp.json();
                if (!resp.ok || !res.success) {
                    if (window.showModalAlert) await window.showModalAlert(res.error || 'Failed to delete equity grant.', { title: 'Error', type: 'error' });
                } else if (typeof morphEquitySection === 'function') {
                    await morphEquitySection();
                }
            } catch (err) {
                if (window.showModalAlert) await window.showModalAlert(err.message || 'Failed to delete equity grant.', { title: 'Error', type: 'error' });
            }
            return;
        }

        const tr = e.target.closest('#grants-table-body tr[data-grant-id]');
        if (tr) {
            const gid = tr.getAttribute('data-grant-id');
            if (typeof loadSsrEquityDataIfAvailable === 'function') loadSsrEquityDataIfAvailable();
            const grant = findGrantById(gid);
            if (!grant) return;

            if (e.target.closest('.btn-row-edit')) {
                e.stopPropagation();
                openEditGrantCard(grant);
                return;
            }

            if (e.target.closest('.btn-row-del')) {
                e.stopPropagation();
                if (window.showModalConfirm && !await window.showModalConfirm(`Are you sure you want to delete ${grant.nickname}?`, { title: 'Delete Equity Grant', confirmText: 'Delete Grant', confirmVariant: 'danger' })) return;
                try {
                    const resp = await fetch(`/api/equity/grant/${grant.grant_id || grant.id}`, { method: 'DELETE' });
                    const res = await resp.json();
                    if (!resp.ok || !res.success) {
                        if (window.showModalAlert) await window.showModalAlert(res.error || 'Failed to delete equity grant.', { title: 'Error', type: 'error' });
                    } else if (typeof morphEquitySection === 'function') {
                        await morphEquitySection();
                    }
                } catch (err) {
                    if (window.showModalAlert) await window.showModalAlert(err.message || 'Failed to delete equity grant.', { title: 'Error', type: 'error' });
                }
                return;
            }

            showGrantDetail(grant);
        }
    });

    document.addEventListener('change', (e) => {
        if (!e.target) return;
        if (e.target.id === 'input-grant-company') {
            const newFields = document.getElementById('new-company-fields');
            if (newFields) {
                newFields.style.display = e.target.value === '__new__' ? 'block' : 'none';
                if (e.target.value === '__new__') document.getElementById('input-new-company-name')?.focus();
            }
            return;
        }

        if (e.target.id === 'input-grant-type' || e.target.id === 'edit-grant-type') {
            const prefix = e.target.id === 'input-grant-type' ? 'input-grant-' : 'edit-grant-';
            const inputStrike = document.getElementById(`${prefix}strike`);
            const noteStrike = document.getElementById(`${prefix}strike-note`);
            const val = e.target.value;
            if (inputStrike) {
                if (val === 'rsu') {
                    inputStrike.value = '0.00';
                    inputStrike.disabled = true;
                    if (noteStrike) noteStrike.textContent = 'RSUs have $0 strike price (100% ordinary spread at vest)';
                } else if (val === 'iso') {
                    inputStrike.disabled = false;
                    if (noteStrike) noteStrike.textContent = ISO_STRIKE_NOTE;
                } else {
                    inputStrike.disabled = false;
                    if (noteStrike) noteStrike.textContent = 'NSO: W-2 ordinary income tax on spread at exercise';
                }
            }
        }
    });

    document.addEventListener('submit', async (e) => {
        if (!e.target) return;

        if (e.target.id === 'form-equity-grant') {
            e.preventDefault();
            const rawCompanyVal = document.getElementById('input-grant-company')?.value;
            const statusGrant = document.getElementById('grant-form-status');
            let companyId = null;
            let newCompName = '';
            let newCompFmv = 10.0;

            if (rawCompanyVal === '__new__') {
                newCompName = (document.getElementById('input-new-company-name')?.value || '').trim();
                newCompFmv = parseFloat(document.getElementById('input-new-company-fmv')?.value) || 10.0;
                if (!newCompName) {
                    if (statusGrant) {
                        statusGrant.textContent = 'Please enter a name for the new company.';
                        statusGrant.style.color = 'var(--status-red)';
                    }
                    return;
                }
            } else {
                companyId = parseInt(rawCompanyVal, 10) || 1;
            }

            const grantType = document.getElementById('input-grant-type')?.value || 'nso';
            const nick = (document.getElementById('input-grant-nickname')?.value || '').trim();
            const gDate = document.getElementById('input-grant-date')?.value;
            const vDate = document.getElementById('input-grant-vested-date')?.value;
            const qty = parseFloat(document.getElementById('input-grant-quantity')?.value);
            const rawStrike = parseFloat(document.getElementById('input-grant-strike')?.value);
            const strike = (grantType.toLowerCase() === 'rsu') ? 0.0 : (isNaN(rawStrike) ? 0.0 : rawStrike);
            const unvest = parseFloat(document.getElementById('input-grant-unvested')?.value) || 0;

            if (statusGrant) {
                statusGrant.textContent = 'Saving new grant to encrypted vault...';
                statusGrant.style.color = 'var(--accent-orange)';
            }

            try {
                const payload = {
                    nickname: nick, grantDate: gDate, fullyVestedDate: vDate,
                    quantityGranted: qty, strikePrice: strike, unvestedQuantity: unvest,
                    grantType: grantType, companyId: companyId
                };
                if (newCompName) {
                    payload.new_company_name = newCompName;
                    payload.new_company_fmv = newCompFmv;
                }

                const resp = await fetch('/api/equity/grant', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const res = await resp.json();
                if (!resp.ok || !res.success) {
                    if (statusGrant) {
                        statusGrant.textContent = `Error: ${res.error || 'Failed to add equity grant.'}`;
                        statusGrant.style.color = 'var(--status-red)';
                    }
                    if (window.showModalAlert) await window.showModalAlert(res.error || 'Failed to add equity grant.', { title: 'Error', type: 'error' });
                } else {
                    const targetCid = res.company_id || companyId || EquityState.companyId;
                    EquityState.companyId = targetCid;
                    EquityState.simulatedPrice = 0;
                    if (typeof morphEquitySection === 'function') {
                        await morphEquitySection({ company_id: targetCid, share_price: '' });
                    }
                }
            } catch (err) {
                if (statusGrant) {
                    statusGrant.textContent = `Error: ${err.message}`;
                    statusGrant.style.color = 'var(--status-red)';
                }
                if (window.showModalAlert) await window.showModalAlert(err.message || 'Failed to add equity grant.', { title: 'Error', type: 'error' });
            }
            return;
        }

        if (e.target.id === 'form-edit-equity-grant') {
            e.preventDefault();
            const gId = document.getElementById('edit-grant-id')?.value;
            const companyId = parseInt(document.getElementById('edit-grant-company')?.value, 10) || 1;
            const grantType = document.getElementById('edit-grant-type')?.value || 'nso';
            const nick = (document.getElementById('edit-grant-nickname')?.value || '').trim();
            const gDate = document.getElementById('edit-grant-date')?.value;
            const vDate = document.getElementById('edit-grant-vested-date')?.value;
            const qty = parseFloat(document.getElementById('edit-grant-quantity')?.value);
            const rawStrike = parseFloat(document.getElementById('edit-grant-strike')?.value);
            const strike = (grantType.toLowerCase() === 'rsu') ? 0.0 : (isNaN(rawStrike) ? 0.0 : rawStrike);
            const unvest = parseFloat(document.getElementById('edit-grant-unvested')?.value) || 0;
            const owned = parseFloat(document.getElementById('edit-grant-owned')?.value) || 0;
            const basis = parseFloat(document.getElementById('edit-grant-basis')?.value) || 0;
            const statusEditGrant = document.getElementById('edit-grant-form-status');

            if (statusEditGrant) {
                statusEditGrant.textContent = 'Saving changes to encrypted vault...';
                statusEditGrant.style.color = 'var(--accent-orange)';
            }

            try {
                const resp = await fetch(`/api/equity/grant/${gId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        nickname: nick, grantDate: gDate, fullyVestedDate: vDate,
                        quantityGranted: qty, strikePrice: strike, unvestedQuantity: unvest,
                        ownedShares: owned, costBasis: basis, grantType: grantType, companyId: companyId
                    })
                });
                const res = await resp.json();
                if (!resp.ok || !res.success) {
                    if (statusEditGrant) {
                        statusEditGrant.textContent = `Error: ${res.error || 'Failed to update equity grant.'}`;
                        statusEditGrant.style.color = 'var(--status-red)';
                    }
                    if (window.showModalAlert) await window.showModalAlert(res.error || 'Failed to update equity grant.', { title: 'Error', type: 'error' });
                } else if (typeof morphEquitySection === 'function') {
                    await morphEquitySection();
                }
            } catch (err) {
                if (statusEditGrant) {
                    statusEditGrant.textContent = `Error: ${err.message}`;
                    statusEditGrant.style.color = 'var(--status-red)';
                }
                if (window.showModalAlert) await window.showModalAlert(err.message || 'Failed to update equity grant.', { title: 'Error', type: 'error' });
            }
        }
    });
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        openEditGrantCard,
        showGrantDetail,
        initEquityModals
    });
}
