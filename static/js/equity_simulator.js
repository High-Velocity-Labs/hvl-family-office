/**
 * Equity 409A Scenario Simulator & Valuation Model
 * Handles scenario recalculations, valuation presets, slider events, and 409A FMV updates.
 */

function renderEquitySimulator(data) {
    if (typeof initEquityDelegation === 'function') initEquityDelegation();
    if (typeof loadSsrEquityDataIfAvailable === 'function') loadSsrEquityDataIfAvailable();

    if (data && data.snapshot) {
        const snap = data.snapshot;
        const equity = snap.company_equity || {};

        if (Array.isArray(equity.companies) && equity.companies.length > 0) {
            equityCompaniesList = equity.companies;
        }
        if (activeEquityCompanyId === null) {
            if (equity.company_id !== undefined && equity.company_id !== null) {
                activeEquityCompanyId = equity.company_id;
            } else if (equityCompaniesList.length > 0) {
                activeEquityCompanyId = equityCompaniesList[0].company_id;
            }
        }

        const incomingCid = equity.company_id;
        if (activeEquityCompanyId === 'all') {
            currentEquityData = equity;
            equityGrantsData = equity.grants || equityGrantsData;
            equityProjectionsData = data.multi_year_projections || equityProjectionsData;
            currentIncludeWaTax = Boolean(equity.include_wa_millionaire_tax);
        } else if (activeEquityCompanyId === incomingCid || !currentEquityData || incomingCid === null || incomingCid === undefined) {
            currentEquityData = equity;
            equityGrantsData = equity.grants || equityGrantsData;
            equityProjectionsData = data.multi_year_projections || equityProjectionsData;
            if (Array.isArray(equity.fmv_history) && equity.fmv_history.length > 0) {
                equityFmvHistoryData = equity.fmv_history;
            }
            currentSimulatedPrice = equity.share_price || equity.current_409a_price || currentSimulatedPrice || 0;
            currentIncludeWaTax = Boolean(equity.include_wa_millionaire_tax);
        }
    }

    if (typeof renderEquityStockValueGraph === 'function') {
        renderEquityStockValueGraph(currentSimulatedPrice, currentIncludeWaTax, currentEquityData);
    }
}

function triggerScenarioRecalc(price, waTax, multiple) {
    const isConsolidated = (activeEquityCompanyId === 'all');
    currentIncludeWaTax = Boolean(waTax);

    const readoutLabel = document.getElementById('slider-readout-label');
    const displayPrice = document.getElementById('display-share-price');
    const displayRatio = document.getElementById('display-price-ratio');
    const badgeScenario = document.getElementById('badge-active-scenario');
    const sec = document.getElementById('section-equity');

    let sendPrice;
    let basePrice;

    if (isConsolidated) {
        const mult = (multiple !== undefined && multiple !== null) ? multiple : currentPortfolioMultiple;
        currentPortfolioMultiple = mult;
        if (readoutLabel) readoutLabel.textContent = 'PORTFOLIO VALUATION MULTIPLE:';
        if (displayPrice) displayPrice.textContent = `${mult.toFixed(2)}x`;
        if (displayRatio) displayRatio.textContent = `${mult.toFixed(2)}x Baseline FMVs`;
        if (badgeScenario) badgeScenario.textContent = `Portfolio Multiple: ${mult.toFixed(2)}x Baseline FMVs`;

        const primaryComp = (equityCompaniesList && equityCompaniesList.length > 0) ? equityCompaniesList[0] : null;
        basePrice = primaryComp ? Number(primaryComp.current_fmv || 100) : (parseFloat(sec?.dataset.baseFmv) || 100);
        sendPrice = Math.round(basePrice * mult * 100) / 100;
        currentSimulatedPrice = sendPrice;
    } else {
        const comp = equityCompaniesList.find(c => Number(c.company_id) === Number(activeEquityCompanyId));
        basePrice = comp && comp.current_fmv ? Number(comp.current_fmv) : (parseFloat(sec?.dataset.baseFmv) || (currentEquityData && currentEquityData.share_price) || 100);
        sendPrice = (price !== undefined && price !== null) ? price : (currentSimulatedPrice || basePrice);
        currentSimulatedPrice = sendPrice;

        if (readoutLabel) {
            readoutLabel.textContent = Math.abs(sendPrice - basePrice) < 0.01
                ? 'CURRENT 409A SHARE PRICE:'
                : 'SIMULATED 409A SHARE PRICE:';
        }
        if (displayPrice) displayPrice.textContent = fmtCurrency(sendPrice, 2);
        const ratio = (sendPrice / (basePrice || 1.0)).toFixed(2);
        if (displayRatio) displayRatio.textContent = `${ratio}x Baseline FMV`;
        if (badgeScenario) badgeScenario.textContent = `Simulated 409A: ${fmtCurrency(sendPrice, 2)} / share`;
    }

    if (typeof updateGraphHeaderAndStats === 'function') {
        updateGraphHeaderAndStats(currentEquityData, sendPrice);
    }
    if (typeof renderEquityStockValueGraph === 'function') {
        renderEquityStockValueGraph(sendPrice, currentIncludeWaTax, currentEquityData);
    }

    clearTimeout(debounceScenarioTimer);
    debounceScenarioTimer = setTimeout(() => {
        if (typeof morphEquitySection === 'function') {
            if (isConsolidated) {
                morphEquitySection({
                    company_id: 'all',
                    include_wa_tax: currentIncludeWaTax,
                    multiple: currentPortfolioMultiple
                });
            } else {
                morphEquitySection({
                    company_id: activeEquityCompanyId,
                    share_price: sendPrice,
                    include_wa_tax: currentIncludeWaTax
                });
            }
        }
    }, 150);
}

function initEquitySimulator() {
    if (document.body.dataset.equitySimulatorDelegated === 'true') return;
    document.body.dataset.equitySimulatorDelegated = 'true';

    document.addEventListener('click', (e) => {
        const presetBtn = e.target.closest('.btn-equity-preset');
        if (presetBtn) {
            const mult = parseFloat(presetBtn.getAttribute('data-multiple')) || 1.0;
            const priceAttr = presetBtn.getAttribute('data-price');
            const slider = document.getElementById('slider-share-price');
            const toggleWa = document.getElementById('toggle-wa-tax');
            const waChecked = toggleWa ? toggleWa.checked : currentIncludeWaTax;

            const container = document.getElementById('valuation-presets-container');
            if (container) {
                container.querySelectorAll('.btn-equity-preset').forEach(b => b.classList.remove('active'));
            }
            presetBtn.classList.add('active');

            if (activeEquityCompanyId === 'all') {
                currentPortfolioMultiple = mult;
                if (slider) slider.value = mult;
                triggerScenarioRecalc(null, waChecked, mult);
            } else {
                const sec = document.getElementById('section-equity');
                const baseFmv = parseFloat(sec?.dataset.baseFmv) || 100;
                const price = priceAttr ? parseFloat(priceAttr) : Math.round(baseFmv * mult * 100) / 100;
                if (slider) slider.value = price;
                triggerScenarioRecalc(price, waChecked);
            }
            return;
        }

        if (e.target.closest('#btn-equity-graph-fmv')) {
            if (typeof setGraphMode === 'function') setGraphMode('fmv');
            return;
        }
        if (e.target.closest('#btn-equity-graph-time')) {
            if (typeof setGraphMode === 'function') setGraphMode('trajectory');
            return;
        }
        if (e.target.closest('#btn-equity-graph-curve')) {
            if (typeof setGraphMode === 'function') setGraphMode('curve');
            return;
        }

        if (e.target.closest('#btn-toggle-equity-fmv')) {
            const cardFmv = document.getElementById('equity-fmv-card');
            if (cardFmv) {
                cardFmv.style.display = cardFmv.style.display === 'none' ? 'block' : 'none';
                if (cardFmv.style.display === 'block') {
                    const today = new Date().toISOString().split('T')[0];
                    const inDate = document.getElementById('input-fmv-date');
                    const inPrice = document.getElementById('input-fmv-price');
                    if (inDate && !inDate.value) inDate.value = today;
                    if (inPrice && !inPrice.value) inPrice.value = currentSimulatedPrice || '';
                }
            }
            return;
        }
        if (e.target.closest('#btn-close-equity-fmv') || e.target.closest('#btn-cancel-equity-fmv')) {
            const cardFmv = document.getElementById('equity-fmv-card');
            if (cardFmv) cardFmv.style.display = 'none';
        }
    });

    document.addEventListener('input', (e) => {
        if (e.target && e.target.id === 'slider-share-price') {
            const val = parseFloat(e.target.value);
            const toggleWa = document.getElementById('toggle-wa-tax');
            const waChecked = toggleWa ? toggleWa.checked : currentIncludeWaTax;
            const presetsContainer = document.getElementById('valuation-presets-container');
            if (presetsContainer) {
                presetsContainer.querySelectorAll('.btn-equity-preset').forEach(b => b.classList.remove('active'));
            }
            if (activeEquityCompanyId === 'all') {
                currentPortfolioMultiple = val;
                triggerScenarioRecalc(null, waChecked, val);
            } else {
                triggerScenarioRecalc(val, waChecked);
            }
        }
    });

    document.addEventListener('change', (e) => {
        if (!e.target) return;
        if (e.target.id === 'toggle-wa-tax') {
            const checked = e.target.checked;
            currentIncludeWaTax = checked;
            if (activeEquityCompanyId === 'all') {
                triggerScenarioRecalc(null, checked, currentPortfolioMultiple);
            } else {
                const slider = document.getElementById('slider-share-price');
                const price = slider ? parseFloat(slider.value) : currentSimulatedPrice;
                triggerScenarioRecalc(price, checked);
            }
            return;
        }
        if (e.target.id === 'select-equity-expected-growth') {
            if (typeof morphEquitySection === 'function') {
                morphEquitySection({ growth_rate: e.target.value });
            }
        }
    });

    document.addEventListener('submit', async (e) => {
        if (!e.target || e.target.id !== 'form-equity-fmv') return;
        e.preventDefault();
        const dateVal = document.getElementById('input-fmv-date')?.value;
        const priceVal = parseFloat(document.getElementById('input-fmv-price')?.value);
        const notesVal = (document.getElementById('input-fmv-notes')?.value || '').trim();
        const companyVal = parseInt(document.getElementById('input-fmv-company')?.value, 10) || activeEquityCompanyId || 1;
        const statusFmv = document.getElementById('fmv-form-status');

        if (statusFmv) {
            statusFmv.textContent = 'Saving 409A FMV to encrypted vault...';
            statusFmv.style.color = 'var(--accent-orange)';
        }

        try {
            const resp = await fetch('/api/equity/fmv', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    company_id: companyVal,
                    price: priceVal,
                    effective_date: dateVal,
                    notes: notesVal
                })
            });
            const res = await resp.json();
            if (!resp.ok || !res.success) {
                if (statusFmv) {
                    statusFmv.textContent = `Error: ${res.error || 'Failed to record valuation.'}`;
                    statusFmv.style.color = 'var(--status-red)';
                }
                if (window.showModalAlert) {
                    await window.showModalAlert(res.error || 'Failed to record valuation.', { title: 'Error', type: 'error' });
                }
            } else {
                activeEquityCompanyId = companyVal;
                currentSimulatedPrice = priceVal;
                if (typeof morphEquitySection === 'function') {
                    await morphEquitySection({ company_id: companyVal, share_price: priceVal });
                }
            }
        } catch (err) {
            if (statusFmv) {
                statusFmv.textContent = `Error: ${err.message}`;
                statusFmv.style.color = 'var(--status-red)';
            }
            if (window.showModalAlert) {
                await window.showModalAlert(err.message || 'Failed to record valuation.', { title: 'Error', type: 'error' });
            }
        }
    });
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        renderEquitySimulator,
        triggerScenarioRecalc,
        initEquitySimulator
    });
}
