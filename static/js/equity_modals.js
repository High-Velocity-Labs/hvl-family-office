/**
 * Equity Modals & Grant Management Module
 * Handles grant inspection, add/edit grant modal cards, and grant mutations.
 */

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
            else if (isIso) noteStrike.textContent = 'ISO: AMT preference at exercise; LTCG (23.8%) on qualifying disposition';
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

function showGrantDetail(g) {
    const card = document.getElementById('grant-detail-card');
    const title = document.getElementById('grant-detail-title');
    const content = document.getElementById('grant-detail-content');
    if (!card || !content) return;

    const gtype = String(g.grant_type || '').toLowerCase();
    const isRsu = gtype === 'rsu';
    const isIso = gtype === 'iso';
    const grantTypeLabel = isRsu ? 'Restricted Stock Unit (RSU)' : (isIso ? 'Incentive Stock Option (ISO)' : 'Non-Qualified Stock Option (NSO)');
    const grantTypeBadgeClass = isRsu ? 'badge-blue' : (isIso ? 'badge-green' : 'badge-blue');

    const price = currentSimulatedPrice || (currentEquityData && currentEquityData.share_price) || 0;
    const owned = Number(g.owned_shares || 0);
    const basis = Number(g.cost_basis !== undefined ? g.cost_basis : (g.historical_cost_basis || g.strike_price || 0));
    const ownedGross = owned * price;
    const ownedGain = Math.max(0, ownedGross - (owned * basis));
    const ltcgTax = ownedGain * 0.238;
    const ownedNet = ownedGross - ltcgTax;
    const gid = g.grant_id || g.id || '';

    if (title) title.textContent = `Grant Inspection: ${g.nickname} (${g.grant_date})`;

    content.innerHTML = `
        ${isIso ? `
        <div style="grid-column: 1 / -1; background: var(--bg-canvas); border-left: 3px solid var(--status-green); padding: 8px 12px; border-radius: 4px; font-size: 0.75rem; color: var(--text-secondary); margin-bottom: 6px;">
            <strong>ISO Tax Treatment:</strong> Exercise spread is an AMT preference item (no immediate W-2 ordinary payroll tax). If held for qualifying disposition (≥2 yrs from grant &amp; ≥1 yr from exercise), liquidation proceeds qualify for favorable Long-Term Capital Gains rates (20% + 3.8% NIIT).
        </div>` : ''}
        <div><span class="micro-label">COMPANY:</span><strong>${escapeHtml(g.company_name || 'Primary Company')}</strong></div>
        <div><span class="micro-label">GRANT TYPE:</span><span class="badge ${grantTypeBadgeClass}">${grantTypeLabel}</span></div>
        <div><span class="micro-label">STRIKE PRICE:</span><strong>${isRsu ? '$0.00 (RSU)' : '$' + Number(g.strike_price).toFixed(2)}</strong></div>
        <div><span class="micro-label">VESTED UNITS:</span><strong>${Number(g.unexercised_options || 0).toLocaleString()}</strong></div>
        <div><span class="micro-label">UNVESTED UNITS:</span><strong>${Number(g.unvested_options || 0).toLocaleString()} ${Number(g.unvested_options || 0) > 0 ? '<span style="color: var(--accent-orange); font-size: 0.75rem;">(Excluded from Net Worth until Vested)</span>' : ''}</strong></div>
        <div><span class="micro-label">STRIKE CASH REQUIRED:</span><strong>${isRsu ? '$0' : fmtCurrency(g.strike_cost || 0)}</strong></div>
        <div><span class="micro-label">TAXABLE SPREAD:</span><strong>${fmtCurrency(g.spread || 0)}</strong></div>
        <div><span class="micro-label">${isIso ? 'EST. TAX LIABILITY (LTCG / AMT):' : 'ORDINARY TAX LIABILITY:'}</span><strong style="color: var(--status-red);">${fmtCurrency(g.total_tax_drag || 0)}</strong></div>
        <div><span class="micro-label">VESTED UNITS NET VALUE:</span><strong>${fmtCurrency(g.net_option_value || 0)}</strong></div>
        <div><span class="micro-label">OWNED / EXERCISED SHARES:</span><strong>${owned > 0 ? owned.toLocaleString() + ' shares' : '0 shares'}</strong></div>
        <div><span class="micro-label">OWNED SHARES COST BASIS:</span><strong>${owned > 0 ? fmtCurrency(basis) + '/sh (' + fmtCurrency(owned * basis) + ' total)' : 'N/A'}</strong></div>
        <div><span class="micro-label">OWNED SHARES MARKET VALUE:</span><strong>${owned > 0 ? fmtCurrency(ownedGross) : '$0'}</strong></div>
        <div><span class="micro-label">UNREALIZED CAPITAL GAINS:</span><strong style="color: ${ownedGain > 0 ? 'var(--status-green)' : 'inherit'};">${owned > 0 ? fmtCurrency(ownedGain) : '$0'}</strong></div>
        <div><span class="micro-label">EST. LTCG TAX (23.8%):</span><strong style="color: var(--status-red);">${owned > 0 ? fmtCurrency(ltcgTax) : '$0'}</strong></div>
        <div><span class="micro-label">OWNED SHARES NET VALUE:</span><strong style="color: var(--status-green);">${owned > 0 ? fmtCurrency(ownedNet) : '$0'}</strong></div>
        <div><span class="micro-label">COMBINED TRUE NET VALUE:</span><strong style="color: var(--status-green); font-size: 1.05rem;">${fmtCurrency(g.true_net_value || 0)}</strong></div>
        <div><span class="micro-label">VESTING STATUS:</span><span>${escapeHtml(g.vesting_completion || '100% Vested')}</span></div>
        <div style="grid-column: 1 / -1; display: flex; justify-content: flex-end; gap: 8px; margin-top: 10px; border-top: 1px solid var(--border-color); padding-top: 10px;">
            <button type="button" id="btn-inspect-edit-grant" data-edit-grant-id="${escapeHtml(String(gid))}" class="btn btn-secondary btn-sm" title="Edit Grant" aria-label="Edit Grant" style="padding: 4px 8px; display: inline-flex; align-items: center; justify-content: center;">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display: block;"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
            </button>
            <button type="button" data-del-grant-id="${escapeHtml(String(gid))}" class="btn btn-secondary btn-sm" title="Delete Grant" aria-label="Delete Grant" style="color: var(--status-red); border-color: rgba(239,68,68,0.3); font-size: 0.75rem; line-height: 1.2; padding: 2px 8px;">✕</button>
        </div>
    `;

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
            const grant = equityGrantsData.find(g => String(g.grant_id) === String(gid) || String(g.id) === String(gid));
            if (grant) openEditGrantCard(grant);
            return;
        }

        const inspectDelBtn = e.target.closest('#grant-detail-card [data-del-grant-id]');
        if (inspectDelBtn) {
            const gid = inspectDelBtn.getAttribute('data-del-grant-id');
            if (typeof loadSsrEquityDataIfAvailable === 'function') loadSsrEquityDataIfAvailable();
            const grant = equityGrantsData.find(g => String(g.grant_id) === String(gid) || String(g.id) === String(gid));
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
            const grant = equityGrantsData.find(g => String(g.grant_id) === String(gid) || String(g.id) === String(gid));
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
                    if (noteStrike) noteStrike.textContent = 'ISO: AMT preference at exercise; LTCG (23.8%) on qualifying disposition';
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
                    const targetCid = res.company_id || companyId || activeEquityCompanyId || 1;
                    activeEquityCompanyId = targetCid;
                    currentSimulatedPrice = 0;
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
