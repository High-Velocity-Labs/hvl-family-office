/**
 * static/js/scenarios/event_modals_syncers.js
 * Specialized field synchronization handlers for scenario life event categories.
 */

import { getPlanStartYear } from './state.js';
import { optionOf } from './event_modals_inputs.js';
import { setSelectedEventIcon } from './event_modals_presets.js';

export function syncCapitalOutflowFields(purpose = 'large_gift') {
    const nameInput = document.getElementById('input-event-name');
    const amtInput = document.getElementById('input-event-amount');
    const purposeMap = {
        'wedding': { name: 'Family Wedding & Celebration', amt: 150000, icon: 'evt-wedding' },
        'child_home_gift': { name: 'Child First-Home Down Payment Gift', amt: 250000, icon: 'evt-house-key' },
        'vehicle_purchase': { name: 'Luxury / Electric Vehicle Purchase', amt: 120000, icon: 'evt-car' },
        'yacht_vessel': { name: 'Yacht / Vessel / Aircraft Purchase', amt: 500000, icon: 'evt-yacht' },
        'new_child': { name: 'New Child / Adoption / Childcare Setup', amt: 65000, icon: 'evt-baby' },
        'large_gift': { name: 'One-Time Family Wealth Transfer Gift', amt: 500000, icon: 'evt-gifting' },
        'angel_investment': { name: 'Angel / Seed Venture Investment', amt: 100000, icon: 'evt-rocket' },
        'medical_expense': { name: 'Major Medical / Healthcare Procedure', amt: 75000, icon: 'evt-medical' },
        'solar_energy': { name: 'Solar & Home Energy Infrastructure', amt: 60000, icon: 'evt-solar' },
        'major_purchase': { name: 'Art / Watch / Collector Asset Purchase', amt: 150000, icon: 'evt-art' },
        'tax_legal': { name: 'Tax Assessment / Legal Settlement', amt: 150000, icon: 'evt-tax-legal' },
        'charitable': { name: 'Foundation / Major Charitable Gift', amt: 250000, icon: 'evt-philanthropy' },
        'other_outflow': { name: 'Major One-Time Capital Outflow', amt: 100000, icon: 'evt-capital-outflow' },
    };
    const conf = purposeMap[purpose] || purposeMap['large_gift'];
    if (nameInput) nameInput.value = conf.name;
    if (amtInput) amtInput.value = conf.amt;
    setSelectedEventIcon(conf.icon, false);
}

export function syncCapitalInflowFields(inType = 'windfall_bonus') {
    const nameInput = document.getElementById('input-event-name');
    const amtInput = document.getElementById('input-event-amount');
    const startYearEl = document.getElementById('input-event-year');
    const endYearEl = document.getElementById('input-event-end-year');
    const typeMap = {
        'windfall_bonus': { name: 'Executive Bonus Windfall', amt: 250000, icon: 'evt-trophy', isStream: false },
        'asset_sale': { name: 'Private Asset / Business Sale Proceeds', amt: 500000, icon: 'evt-business-sale', isStream: false },
        'inheritance': { name: 'Family Inheritance / Estate Distribution', amt: 500000, icon: 'evt-inheritance', isStream: false },
        'rental_income': { name: 'Net Rental Property Income Stream', amt: 60000, icon: 'evt-rental-income', isStream: true },
        'deferred_comp': { name: 'Deferred Compensation / Pension Stream', amt: 120000, icon: 'evt-pension', isStream: true },
        'legal_royalty': { name: 'Licensing Royalty / Legal Payout', amt: 200000, icon: 'evt-tax-legal', isStream: false },
        'other_inflow': { name: 'One-Time Capital Windfall', amt: 250000, icon: 'evt-capital-inflow', isStream: false },
    };
    const conf = typeMap[inType] || typeMap['windfall_bonus'];
    if (nameInput) nameInput.value = conf.name;
    if (amtInput) amtInput.value = conf.amt;
    if (startYearEl && endYearEl) {
        const sYr = parseInt(startYearEl.value) || getPlanStartYear() + 1;
        endYearEl.value = conf.isStream ? (sYr + 9) : sYr;
    }
    setSelectedEventIcon(conf.icon, false);
}

export function syncRealEstateActionFields(reAction = 'buy_vacation') {
    const nameInput = document.getElementById('input-event-name');
    const priceInput = document.getElementById('input-re-price');
    const amtInput = document.getElementById('input-event-amount');
    const labelPrice = document.getElementById('label-re-price');
    const downGroup = document.getElementById('input-re-down-pct')?.parentElement;
    const finRow = document.getElementById('group-re-financing-row');
    const rateRow = document.getElementById('group-re-mortgage-rates');
    const badge = document.getElementById('badge-re-mortgage-label');

    if (reAction === 'downsize') {
        if (labelPrice) labelPrice.textContent = 'NET SALE PROCEEDS ($)';
        if (downGroup) {
            downGroup.hidden = true;
            downGroup.classList.add('hidden');
        }
        if (finRow) {
            finRow.hidden = true;
            finRow.classList.add('hidden');
        }
        if (rateRow) {
            rateRow.hidden = true;
            rateRow.classList.add('hidden');
        }
        if (badge) {
            badge.textContent = 'Home Sale / Downsize';
            badge.className = 'badge badge-green';
        }
        if (nameInput) nameInput.value = 'Sell / Downsize Residence';
        if (priceInput && !priceInput.value) priceInput.value = '1200000';
        if (amtInput) amtInput.value = priceInput.value;
        setSelectedEventIcon('evt-home-sale', false);
    } else {
        if (labelPrice) labelPrice.textContent = 'PURCHASE PRICE ($)';
        if (downGroup) {
            downGroup.hidden = false;
            downGroup.classList.remove('hidden');
        }
        if (finRow) {
            finRow.hidden = false;
            finRow.classList.remove('hidden');
        }
        if (rateRow) {
            rateRow.hidden = false;
            rateRow.classList.remove('hidden');
        }
        if (badge) {
            badge.textContent = reAction === 'buy_primary' ? 'Primary Residence' : 'Vacation Property';
            badge.className = 'badge badge-orange';
        }
        if (reAction === 'buy_primary') {
            if (nameInput) nameInput.value = 'Upgrade Primary Residence';
            if (priceInput) priceInput.value = '2500000';
            if (amtInput) amtInput.value = '2500000';
            setSelectedEventIcon('evt-real-estate', false);
        } else {
            if (nameInput) nameInput.value = 'Purchase Vacation Property';
            if (priceInput) priceInput.value = '1500000';
            if (amtInput) amtInput.value = '1500000';
            setSelectedEventIcon('evt-vacation-home', false);
        }
    }
}

export function syncRenovationFields(scope = 'kitchen_bath') {
    const nameInput = document.getElementById('input-event-name');
    const amtInput = document.getElementById('input-event-amount');
    const retInput = document.getElementById('input-renovation-retention');
    const scopeMap = {
        'kitchen_bath': { name: 'Kitchen & Bath Remodel', amt: 150000, ret: 65 },
        'major_remodel': { name: 'Whole-Home Architectural Remodel', amt: 250000, ret: 60 },
        'adu_addition': { name: 'ADU / Guest House Addition', amt: 450000, ret: 75 },
    };
    const conf = scopeMap[scope];
    if (conf) {
        if (nameInput) nameInput.value = conf.name;
        if (amtInput) amtInput.value = conf.amt;
        if (retInput) retInput.value = conf.ret;
    }
    setSelectedEventIcon('evt-renovation', false);
}

export function syncSabbaticalFields(mode = 'sabbatical') {
    const nameInput = document.getElementById('input-event-name');
    const amtInput = document.getElementById('input-event-amount');
    const multInput = document.getElementById('input-sabbatical-mult');
    const modeMap = {
        'sabbatical': { name: 'Career Sabbatical & Recharge Year', mult: 0, amt: 50000 },
        'part_time': { name: 'Coast / Part-Time Career Pivot (50% Income)', mult: 50, amt: 0 },
        'consulting': { name: 'Advisory & Board Consulting Pivot', mult: 35, amt: 0 },
    };
    const conf = modeMap[mode] || modeMap['sabbatical'];
    if (nameInput) nameInput.value = conf.name;
    if (multInput) multInput.value = conf.mult;
    if (amtInput) amtInput.value = conf.amt;
    setSelectedEventIcon('evt-briefcase', false);
}

export function syncGradSchoolFields(program = 'mba') {
    const nameInput = document.getElementById('input-event-name');
    const amtInput = document.getElementById('input-event-amount');
    const startYearEl = document.getElementById('input-event-year');
    const endYearEl = document.getElementById('input-event-end-year');
    // Name, annual cost and length come from the server-rendered option (custom carries none).
    const conf = optionOf('select-grad-program', program)?.dataset;
    if (conf?.annualCost) {
        if (nameInput) nameInput.value = conf.eventName;
        if (amtInput) amtInput.value = conf.annualCost;
        if (startYearEl && endYearEl) {
            const sYr = parseInt(startYearEl.value) || getPlanStartYear() + 3;
            endYearEl.value = sYr + Number(conf.years) - 1;
        }
    }
    setSelectedEventIcon('evt-grad-school', false);
}

export function syncPhilanthropyDafFields(structure = 'frontload') {
    const nameInput = document.getElementById('input-event-name');
    const amtInput = document.getElementById('input-event-amount');
    const structMap = {
        'frontload': { name: 'Donor-Advised Fund (DAF) Front-Load', amt: 250000 },
        'annual': { name: 'Annual Charitable DAF Granting', amt: 50000 },
        'endowment': { name: 'Family Foundation Seed Endowment', amt: 500000 },
    };
    const conf = structMap[structure] || structMap['frontload'];
    if (nameInput) nameInput.value = conf.name;
    if (amtInput) amtInput.value = conf.amt;
    setSelectedEventIcon('evt-philanthropy', false);
}

export function syncStateRelocationFields() {
    const nameInput = document.getElementById('input-event-name');
    const amtInput = document.getElementById('input-event-amount');
    const endYearEl = document.getElementById('input-event-end-year');
    const fromSt = document.getElementById('select-reloc-from')?.value;
    const toSt = document.getElementById('select-reloc-to')?.value;
    const taxInput = document.getElementById('input-reloc-tax-savings');
    // Top marginal rates (percent) ride on the server-rendered <option data-rate> from state_income_tax_rates().
    const fromRate = parseFloat(optionOf('select-reloc-from', fromSt)?.dataset.rate);
    const toRate = parseFloat(optionOf('select-reloc-to', toSt)?.dataset.rate);
    if (taxInput && Number.isFinite(fromRate) && Number.isFinite(toRate)) {
        taxInput.value = Math.max(0, Number((fromRate - toRate).toFixed(1)));
    }
    if (nameInput) nameInput.value = `Relocate Domicile (${fromSt} → ${toSt})`;
    if (amtInput && !amtInput.value) amtInput.value = '25000';
    if (endYearEl) endYearEl.value = String(getPlanStartYear() + 29);
    setSelectedEventIcon('evt-relocation', false);
}

export function syncRothConversionFields(preset = null) {
    const nameInput = document.getElementById('input-event-name');
    const amtInput = document.getElementById('input-event-amount');
    const startYearEl = document.getElementById('input-event-year');
    const endYearEl = document.getElementById('input-event-end-year');
    const taxRateEl = document.getElementById('input-roth-tax-rate');
    // Every preset's name, amount, rate and ladder length is a data-* attribute of the server-rendered option.
    const conf = optionOf('select-roth-preset', preset)?.dataset;
    if (!conf) return;
    if (nameInput) nameInput.value = conf.eventName;
    if (amtInput && conf.annualCost) amtInput.value = conf.annualCost;
    if (taxRateEl && conf.taxRate) taxRateEl.value = conf.taxRate;
    if (startYearEl && endYearEl) {
        const sYr = parseInt(startYearEl.value) || getPlanStartYear() + 1;
        endYearEl.value = sYr + Number(conf.years) - 1;
    }
    setSelectedEventIcon('evt-roth-ladder', false);
}

export function syncSuperfund529Fields(tier = null) {
    const nameInput = document.getElementById('input-event-name');
    const amtInput = document.getElementById('input-event-amount');
    const startYearEl = document.getElementById('input-event-year');
    const endYearEl = document.getElementById('input-event-end-year');
    const selChild = document.getElementById('select-superfund-child');
    const childOpt = selChild?.options[selChild.selectedIndex];
    const childName = childOpt?.text?.split('(')[0]?.trim() || 'Child';
    const selTier = tier || document.getElementById('select-superfund-tier')?.value;
    if (nameInput) nameInput.value = `${childName}'s 5-Year 529 Superfund`;
    if (amtInput && selTier !== 'custom') amtInput.value = selTier;
    if (startYearEl && endYearEl) {
        endYearEl.value = startYearEl.value || String(getPlanStartYear() + 1);
    }
    setSelectedEventIcon('evt-529-superfund', false);
}

export function syncPeCapitalCallFields() {
    const nameInput = document.getElementById('input-event-name');
    const amtInput = document.getElementById('input-event-amount');
    const startYearEl = document.getElementById('input-event-year');
    const endYearEl = document.getElementById('input-event-end-year');
    const distYearEl = document.getElementById('input-pe-dist-year');
    if (nameInput) nameInput.value = 'Private Equity / VC Fund Commitment (J-Curve)';
    if (amtInput) amtInput.value = '100000';
    if (startYearEl && endYearEl) {
        const sYr = parseInt(startYearEl.value) || getPlanStartYear() + 1;
        endYearEl.value = sYr + 3;
        if (distYearEl) distYearEl.value = sYr + 5;
    }
    setSelectedEventIcon('evt-j-curve', false);
}

export function syncLtcInsuranceFields() {
    const nameInput = document.getElementById('input-event-name');
    const amtInput = document.getElementById('input-event-amount');
    const startYearEl = document.getElementById('input-event-year');
    const endYearEl = document.getElementById('input-event-end-year');
    if (nameInput) nameInput.value = 'Hybrid Long-Term Care (LTC) 10-Pay Policy';
    if (amtInput) amtInput.value = '25000';
    if (startYearEl && endYearEl) {
        const sYr = parseInt(startYearEl.value) || getPlanStartYear() + 1;
        endYearEl.value = sYr + 9;
    }
    setSelectedEventIcon('evt-ltc-shield', false);
}

export function syncMaritalSettlementFields() {
    const nameInput = document.getElementById('input-event-name');
    const amtInput = document.getElementById('input-event-amount');
    const startYearEl = document.getElementById('input-event-year');
    const endYearEl = document.getElementById('input-event-end-year');
    if (nameInput) nameInput.value = 'Marital Asset Division / Settlement';
    if (amtInput) amtInput.value = '75000';
    if (startYearEl && endYearEl) {
        const sYr = parseInt(startYearEl.value) || getPlanStartYear() + 1;
        endYearEl.value = sYr + 4;
    }
    setSelectedEventIcon('evt-asset-split', false);
}
