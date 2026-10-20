/**
 * Multi-State Tax & True Cost of Living Arbitrage Module (SSR + HTMX/Idiomorph Controller)
 */

let _arbitrageListenersBound = false;

async function morphArbitrageSection(overrides = {}) {
    const selectState = document.getElementById('select-residence-state');
    const inputHome = document.getElementById('input-home-val');
    const inputSpend = document.getElementById('input-annual-spend');
    const btnTax = document.getElementById('btn-arb-mode-tax');
    const btnLiq = document.getElementById('btn-arb-scenario-liquidity');

    const homeState = overrides.home_state !== undefined
        ? overrides.home_state
        : (selectState ? selectState.value : 'WA');
    const homeVal = overrides.home_value !== undefined
        ? overrides.home_value
        : (inputHome && inputHome.value !== '' ? inputHome.value : '');
    const spendVal = overrides.annual_spend !== undefined
        ? overrides.annual_spend
        : (inputSpend && inputSpend.value !== '' ? inputSpend.value : '');
    const mode = overrides.mode !== undefined
        ? overrides.mode
        : (btnTax && btnTax.classList.contains('active') ? 'tax_only' : 'comprehensive');
    const scenario = overrides.scenario !== undefined
        ? overrides.scenario
        : (btnLiq && btnLiq.classList.contains('active') ? 'liquidity' : 'recurring');

    const params = new URLSearchParams();
    if (homeState) params.set('home_state', homeState);
    if (homeVal !== '' && homeVal !== null) params.set('home_value', String(homeVal));
    if (spendVal !== '' && spendVal !== null) params.set('annual_spend', String(spendVal));
    if (mode) params.set('mode', mode);
    if (scenario) params.set('scenario', scenario);

    const url = `/fragments/arbitrage?${params.toString()}`;
    const section = document.getElementById('section-arbitrage');
    if (!section) return;

    await window.htmx.ajax('GET', url, { target: '#section-arbitrage', swap: 'morph' });
    const updated = document.getElementById('section-arbitrage');
    if (updated) updated.style.display = '';
}

function initArbitrageControls() {
    if (_arbitrageListenersBound) return;
    _arbitrageListenersBound = true;

    document.addEventListener('click', (e) => {
        const target = e.target;
        if (!target || typeof target.closest !== 'function') return;

        if (target.closest('#btn-arb-scenario-recurring')) {
            morphArbitrageSection({ scenario: 'recurring' });
            return;
        }
        if (target.closest('#btn-arb-scenario-liquidity')) {
            morphArbitrageSection({ scenario: 'liquidity' });
            return;
        }
        if (target.closest('#btn-arb-mode-comp')) {
            morphArbitrageSection({ mode: 'comprehensive' });
            return;
        }
        if (target.closest('#btn-arb-mode-tax')) {
            morphArbitrageSection({ mode: 'tax_only' });
            return;
        }
        const presetBtn = target.closest('.btn-spend-preset');
        if (presetBtn) {
            const spend = presetBtn.getAttribute('data-spend');
            const inputSpend = document.getElementById('input-annual-spend');
            if (inputSpend && spend) inputSpend.value = spend;
            morphArbitrageSection({ annual_spend: spend });
        }
    });

    document.addEventListener('change', (e) => {
        const target = e.target;
        if (!target) return;
        if (target.id === 'select-residence-state') {
            morphArbitrageSection({ home_state: target.value });
        } else if (target.id === 'input-home-val') {
            morphArbitrageSection({ home_value: target.value });
        } else if (target.id === 'input-annual-spend') {
            morphArbitrageSection({ annual_spend: target.value });
        }
    });

    document.addEventListener('input', (e) => {
        const target = e.target;
        if (target && target.id === 'input-annual-spend') {
            document.querySelectorAll('.btn-spend-preset').forEach(b => b.classList.remove('active'));
        }
    });
}

function renderArbitrage() {
    initArbitrageControls();
}

initArbitrageControls();

window.renderArbitrage = renderArbitrage;
window.morphArbitrageSection = morphArbitrageSection;
if (typeof window !== 'undefined' && typeof window.registerSectionHydrator === 'function') {
    window.registerSectionHydrator('section-arbitrage', renderArbitrage, {
        needsDashboard: true,
        morphFn: () => morphArbitrageSection()
    });
}
