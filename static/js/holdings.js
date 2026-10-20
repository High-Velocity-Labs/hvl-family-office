/**
 * Holdings Inspector Module (SSR + HTMX/Idiomorph)
 * Delegates KPIs, execution simulator, IPS policy, private investments, and brokerage positions
 * to Jinja SSR in /fragments/holdings and morphs #section-holdings on state/CRUD changes.
 */

let holdingsAllocChart = null;

function getHoldingsDatasetTotals(data) {
    if (data && data.snapshot && data.snapshot.detailed_asset_allocation && data.snapshot.detailed_asset_allocation.totals) {
        const t = data.snapshot.detailed_asset_allocation.totals;
        const priv = (data.private_investments && data.private_investments.total_value !== undefined)
            ? data.private_investments.total_value
            : (t.private_investments || 0);
        return {
            us_equity: parseFloat(t.us_equity || 0),
            intl_equity: parseFloat(t.intl_equity || 0),
            bonds: parseFloat(t.bonds || 0),
            cash_liquid: parseFloat(t.cash_liquid || 0),
            real_estate_reits: parseFloat(t.real_estate_reits || 0),
            private_value: parseFloat(priv || 0)
        };
    }
    const sec = document.getElementById('section-holdings');
    if (!sec) {
        return { us_equity: 0, intl_equity: 0, bonds: 0, cash_liquid: 0, real_estate_reits: 0, private_value: 0 };
    }
    return {
        us_equity: parseFloat(sec.getAttribute('data-us-equity') || '0'),
        intl_equity: parseFloat(sec.getAttribute('data-intl-equity') || '0'),
        bonds: parseFloat(sec.getAttribute('data-bonds') || '0'),
        cash_liquid: parseFloat(sec.getAttribute('data-cash') || '0'),
        real_estate_reits: parseFloat(sec.getAttribute('data-real-estate') || '0'),
        private_value: parseFloat(sec.getAttribute('data-private') || '0')
    };
}

function getActiveHoldingsParams(overrides = {}) {
    const sec = document.getElementById('section-holdings');
    const preset = overrides.preset !== undefined ? overrides.preset : (sec?.getAttribute('data-preset') || 'core_satellite');
    const horizon = overrides.horizon !== undefined ? overrides.horizon : (sec?.getAttribute('data-horizon') || '10');
    const drift = overrides.drift !== undefined ? overrides.drift : (sec?.getAttribute('data-drift') || '0.05');
    return { preset, horizon, drift };
}

async function morphHoldingsSection(overrides = {}) {
    const { preset, horizon, drift } = getActiveHoldingsParams(overrides);
    const params = new URLSearchParams({
        preset: String(preset),
        horizon: String(horizon),
        drift: String(drift)
    });
    const url = `/fragments/holdings?${params.toString()}`;
    await window.htmx.ajax('GET', url, { target: '#section-holdings', swap: 'morph' });
    const totals = getHoldingsDatasetTotals();
    renderHoldingsAllocationChart(totals, totals.private_value, totals.real_estate_reits);
}

function renderHoldings(data) {
    setupHoldingsDelegation();
    const totals = getHoldingsDatasetTotals(data);
    renderHoldingsAllocationChart(totals, totals.private_value, totals.real_estate_reits);
}

function initHoldingsSection(data) {
    renderHoldings(data);
}

function renderHoldingsAllocationChart(totals = {}, privateValue, realEstateValue) {
    const canvas = document.getElementById('chart-holdings-asset-allocation');
    if (!canvas || typeof Chart === 'undefined') return;
    const ctx = canvas.getContext('2d');
    if (holdingsAllocChart) holdingsAllocChart.destroy();

    const usEquity = totals.us_equity || 0;
    const intlEquity = totals.intl_equity || 0;
    const bonds = totals.bonds || 0;
    const cash = totals.cash_liquid || 0;
    const privateTotal = privateValue !== undefined && privateValue !== null ? privateValue : (totals.private_value || 0);
    const reTotal = realEstateValue !== undefined && realEstateValue !== null ? realEstateValue : (totals.real_estate_reits || 0);
    const totalInvestments = usEquity + intlEquity + bonds + cash + privateTotal + reTotal;

    const badgeTotal = document.getElementById('holdings-pie-total-badge');
    if (badgeTotal) badgeTotal.textContent = `${fmtCurrency(totalInvestments, 0)} Total Portfolio`;

    holdingsAllocChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: [
                'US Equities (Brokerage & 401k)',
                'International Equities',
                'Real Estate & REITs',
                'Private Investments & VC',
                'Bonds & Fixed Income',
                'Cash & Settlement Sweeps'
            ],
            datasets: [{
                data: [usEquity, intlEquity, reTotal, privateTotal, bonds, cash],
                backgroundColor: (window.CHART_THEME) ? [
                    window.CHART_THEME.emerald,
                    window.CHART_THEME.cerulean,
                    window.CHART_THEME.amber,
                    window.CHART_THEME.sapphire,
                    window.CHART_THEME.tanzanite,
                    window.CHART_THEME.slate
                ] : [
                    '#059669',
                    '#0284C7',
                    '#D97706',
                    '#1D4ED8',
                    '#7C3AED',
                    '#64748B'
                ],
                borderColor: '#161B26',
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right',
                    labels: {
                        color: '#94A3B8',
                        font: { family: 'Inter', size: 11 },
                        padding: 12,
                        generateLabels: (chart) => {
                            const data = chart.data;
                            if (data.labels.length && data.datasets.length) {
                                return data.labels.map((label, i) => {
                                    const val = data.datasets[0].data[i];
                                    const pct = totalInvestments > 0 ? ((val / totalInvestments) * 100).toFixed(1) + '%' : '0%';
                                    return {
                                        text: `${label}: ${fmtShortCurrency(val)} (${pct})`,
                                        fillStyle: data.datasets[0].backgroundColor[i],
                                        strokeStyle: '#161B26',
                                        lineWidth: 1,
                                        index: i
                                    };
                                });
                            }
                            return [];
                        }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            const pct = totalInvestments > 0 ? ((ctx.raw / totalInvestments) * 100).toFixed(1) : '0.0';
                            return ` ${ctx.label}: ${fmtCurrency(ctx.raw, 0)} (${pct}%)`;
                        }
                    }
                }
            },
            cutout: '60%'
        }
    });
}

function setupHoldingsDelegation() {
    if (document.body.dataset.holdingsDelegated === 'true') return;
    document.body.dataset.holdingsDelegated = 'true';

    document.addEventListener('click', async (e) => {
        const presetBtn = e.target.closest('.btn-sim-preset');
        if (presetBtn && presetBtn.closest('#section-holdings')) {
            const preset = presetBtn.getAttribute('data-preset') || 'core_satellite';
            await morphHoldingsSection({ preset });
            return;
        }

        const horizonBtn = e.target.closest('.btn-sim-horizon');
        if (horizonBtn && horizonBtn.closest('#section-holdings')) {
            const horizon = horizonBtn.getAttribute('data-horizon') || '10';
            await morphHoldingsSection({ horizon });
            return;
        }

        const savePolicyBtn = e.target.closest('#btn-save-investment-policy');
        if (savePolicyBtn) {
            const anchor = document.getElementById('select-anchor-preset')?.value || 'core_satellite';
            const driftVal = parseFloat(document.getElementById('select-drift-tolerance')?.value || '0.05');
            const rationale = document.getElementById('textarea-ips-deviations')?.value || '';
            const statusEl = document.getElementById('policy-save-status');

            if (statusEl) {
                statusEl.textContent = 'Saving...';
                statusEl.style.color = 'var(--text-muted)';
            }

            try {
                const resp = await fetch('/api/holdings/policy', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        anchor_preset: anchor,
                        drift_tolerance: driftVal,
                        deviations_rationale: rationale
                    })
                });
                const res = await resp.json();
                if (res.success) {
                    const sec = document.getElementById('section-holdings');
                    if (sec) {
                        sec.dataset.preset = anchor;
                        sec.dataset.drift = driftVal.toFixed(2);
                    }
                    if (!window.__DOMAIN_VERSIONS__) {
                        await morphHoldingsSection({ preset: anchor, drift: driftVal.toFixed(2) });
                    }
                    const newStatusEl = document.getElementById('policy-save-status');
                    if (newStatusEl) {
                        newStatusEl.textContent = '✓ Policy Saved';
                        newStatusEl.style.color = 'var(--status-green)';
                        setTimeout(() => { if (newStatusEl) newStatusEl.textContent = ''; }, 3000);
                    }
                } else if (statusEl) {
                    statusEl.textContent = res.error || 'Save failed';
                    statusEl.style.color = 'var(--status-red)';
                }
            } catch (err) {
                if (statusEl) {
                    statusEl.textContent = 'Error saving policy';
                    statusEl.style.color = 'var(--status-red)';
                }
            }
            return;
        }
    });

    document.addEventListener('change', async (e) => {
        const selDrift = e.target.closest('#select-drift-tolerance');
        if (selDrift && selDrift.closest('#section-holdings')) {
            const drift = parseFloat(selDrift.value || '0.05').toFixed(2);
            await morphHoldingsSection({ drift });
        }
    });

    document.addEventListener('input', (e) => {
        if (e.target.id === 'lp-input-total-commitment' || e.target.id === 'lp-input-capital-called') {
            const tot = parseFloat(document.getElementById('lp-input-total-commitment')?.value) || 0;
            const cal = parseFloat(document.getElementById('lp-input-capital-called')?.value) || 0;
            const unfEl = document.getElementById('lp-input-unfunded');
            if (unfEl) {
                unfEl.value = Math.max(0, tot - cal);
            }
        }
    });
}

function openLpCommitmentModal(item = null) {
    const modal = document.getElementById('modal-lp-commitment');
    if (!modal) return;
    const title = document.getElementById('modal-lp-title');
    const delBtn = document.getElementById('btn-delete-lp');

    document.getElementById('lp-input-id').value = item?.id || '';
    document.getElementById('lp-input-account-id').value = item?.account_id || '';
    document.getElementById('lp-input-fund-name').value = item?.fund_name || '';
    document.getElementById('lp-input-fund-type').value = item?.fund_type || 'Private Equity';
    document.getElementById('lp-input-vintage-year').value = item?.vintage_year || 2022;
    document.getElementById('lp-input-total-commitment').value = item?.total_commitment || '';
    document.getElementById('lp-input-capital-called').value = item?.capital_called !== undefined ? item.capital_called : '';
    document.getElementById('lp-input-unfunded').value = item?.unfunded_commitment !== undefined ? item.unfunded_commitment : '';
    document.getElementById('lp-input-horizon').value = item?.expected_call_horizon_years || 3;
    document.getElementById('lp-input-current-nav').value = item?.current_nav !== undefined ? item.current_nav : '';
    document.getElementById('lp-input-distributions').value = item?.distributions_received !== undefined ? item.distributions_received : '';
    document.getElementById('lp-input-last-mark-date').value = item?.last_mark_date || '';
    document.getElementById('lp-input-k1-status').value = item?.k1_status || 'Expected';
    document.getElementById('lp-input-notes').value = item?.notes || '';

    if (title) title.textContent = item ? `Edit LP Commitment: ${item.fund_name || ''}` : 'Annotate Private Investment / LP Commitment';
    if (delBtn) delBtn.style.display = item && item.id && !String(item.id).startsWith('lp_demo_') ? 'inline-block' : 'none';

    modal.style.display = 'flex';
}

function closeLpCommitmentModal() {
    const modal = document.getElementById('modal-lp-commitment');
    if (modal) modal.style.display = 'none';
}

async function saveLpCommitment() {
    const totalC = parseFloat(document.getElementById('lp-input-total-commitment')?.value) || 0;
    const calledC = parseFloat(document.getElementById('lp-input-capital-called')?.value) || 0;
    const unfundedVal = document.getElementById('lp-input-unfunded')?.value;
    const unfundedC = unfundedVal !== '' && !isNaN(parseFloat(unfundedVal)) ? parseFloat(unfundedVal) : Math.max(0, totalC - calledC);

    const payload = {
        id: document.getElementById('lp-input-id')?.value || '',
        account_id: document.getElementById('lp-input-account-id')?.value || '',
        fund_name: document.getElementById('lp-input-fund-name')?.value || 'Private Fund',
        fund_type: document.getElementById('lp-input-fund-type')?.value || 'Private Equity',
        vintage_year: parseInt(document.getElementById('lp-input-vintage-year')?.value) || 2022,
        total_commitment: totalC,
        capital_called: calledC,
        unfunded_commitment: unfundedC,
        expected_call_horizon_years: parseInt(document.getElementById('lp-input-horizon')?.value) || 3,
        current_nav: parseFloat(document.getElementById('lp-input-current-nav')?.value) || 0,
        distributions_received: parseFloat(document.getElementById('lp-input-distributions')?.value) || 0,
        last_mark_date: document.getElementById('lp-input-last-mark-date')?.value || '',
        k1_status: document.getElementById('lp-input-k1-status')?.value || 'Expected',
        notes: document.getElementById('lp-input-notes')?.value || '',
    };

    const saveBtn = document.getElementById('btn-save-lp');
    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving...'; }

    try {
        const resp = await fetch('/api/holdings/lp_commitments', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const res = await resp.json();
        if (res.success) {
            closeLpCommitmentModal();
            await morphHoldingsSection();
        } else {
            alert(res.error || 'Failed to save LP commitment');
        }
    } catch (err) {
        alert('Network error saving LP commitment');
    } finally {
        if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save Commitment'; }
    }
}

async function deleteActiveLpCommitment() {
    const id = document.getElementById('lp-input-id')?.value;
    if (!id || !confirm('Are you sure you want to delete this LP commitment annotation?')) return;
    try {
        const resp = await fetch(`/api/holdings/lp_commitments/${encodeURIComponent(id)}`, { method: 'DELETE' });
        const res = await resp.json();
        if (res.success) {
            closeLpCommitmentModal();
            await morphHoldingsSection();
        } else {
            alert(res.error || 'Failed to delete LP commitment');
        }
    } catch (err) {
        alert('Network error deleting LP commitment');
    }
}

setupHoldingsDelegation();

if (typeof window !== 'undefined') {
    Object.assign(window, {
        renderHoldings,
        initHoldingsSection,
        morphHoldingsSection,
        renderHoldingsAllocationChart,
        openLpCommitmentModal,
        closeLpCommitmentModal,
        saveLpCommitment,
        deleteActiveLpCommitment
    });
    if (typeof window.registerSectionHydrator === 'function') {
        window.registerSectionHydrator('section-holdings', renderHoldings, {
            needsDashboard: true,
            morphFn: () => morphHoldingsSection()
        });
    }
}
