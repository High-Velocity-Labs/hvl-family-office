/**
 * static/js/scenarios/event_modals_syncers.js
 * Specialized field synchronization handlers for scenario life event categories.
 */

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
        const sYr = parseInt(startYearEl.value) || 2027;
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
        if (downGroup) downGroup.style.display = 'none';
        if (finRow) finRow.style.display = 'none';
        if (rateRow) rateRow.style.display = 'none';
        if (badge) {
            badge.textContent = 'Home Sale / Downsize';
            badge.className = 'badge badge-green';
        }
        if (nameInput) nameInput.value = 'Sell / Downsize Residence';
        if (priceInput && !priceInput.value) priceInput.value = '1200000';
        if (amtInput) amtInput.value = priceInput?.value || '1200000';
        setSelectedEventIcon('evt-home-sale', false);
    } else {
        if (labelPrice) labelPrice.textContent = 'PURCHASE PRICE ($)';
        if (downGroup) downGroup.style.display = 'block';
        if (finRow) finRow.style.display = 'grid';
        if (rateRow) rateRow.style.display = 'grid';
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
    const progMap = {
        'mba': { name: 'Graduate MBA Tuition (2-Yr)', amt: 95000, years: 2 },
        'law': { name: 'Law School JD Tuition (3-Yr)', amt: 95000, years: 3 },
        'med': { name: 'Medical School MD Tuition (4-Yr)', amt: 95000, years: 4 },
        'masters': { name: "Master's Degree Tuition (2-Yr)", amt: 75000, years: 2 },
    };
    const conf = progMap[program];
    if (conf) {
        if (nameInput) nameInput.value = conf.name;
        if (amtInput) amtInput.value = conf.amt;
        if (startYearEl && endYearEl) {
            const sYr = parseInt(startYearEl.value) || 2029;
            endYearEl.value = sYr + conf.years - 1;
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
    const fromSt = document.getElementById('select-reloc-from')?.value || 'CA';
    const toSt = document.getElementById('select-reloc-to')?.value || 'TX';
    const taxInput = document.getElementById('input-reloc-tax-savings');
    const stateRates = { 'CA': 10.5, 'NY': 9.8, 'NJ': 8.5, 'MA': 7.5, 'OR': 8.8, 'WA': 1.5, 'TX': 0, 'FL': 0, 'NV': 0, 'NH': 0, 'WY': 0, 'CO': 4.4, 'AZ': 2.5, 'NC': 4.5, 'OTHER': 5.0 };
    const fromRate = stateRates[fromSt] ?? 9.5;
    const toRate = stateRates[toSt] ?? 0.0;
    const delta = Math.max(0, Number((fromRate - toRate).toFixed(1)));
    if (taxInput) taxInput.value = delta;
    if (nameInput) nameInput.value = `Relocate Domicile (${fromSt} → ${toSt})`;
    if (amtInput && !amtInput.value) amtInput.value = '25000';
    if (endYearEl) endYearEl.value = '2055';
    setSelectedEventIcon('evt-relocation', false);
}

export function syncRothConversionFields(preset = null) {
    const nameInput = document.getElementById('input-event-name');
    const amtInput = document.getElementById('input-event-amount');
    const startYearEl = document.getElementById('input-event-year');
    const endYearEl = document.getElementById('input-event-end-year');
    const taxRateEl = document.getElementById('input-roth-tax-rate');
    const selPreset = preset || document.getElementById('select-roth-preset')?.value || 'auto_bracket_24';
    if (selPreset.startsWith('auto_bracket_') || selPreset === 'fill_12' || selPreset === 'fill_22' || selPreset === 'fill_24' || selPreset === 'fill_32') {
        const rate = (selPreset.includes('12')) ? '12' : ((selPreset.includes('22')) ? '22' : ((selPreset.includes('32')) ? '32' : '24'));
        const defaultAmt = rate === '12' ? '90000' : (rate === '22' ? '150000' : (rate === '32' ? '250000' : '200000'));
        if (nameInput) nameInput.value = `Auto-Fill ${rate}% Bracket Roth Conversion Ladder`;
        if (amtInput) amtInput.value = defaultAmt;
        if (taxRateEl) taxRateEl.value = rate;
        if (startYearEl && endYearEl) {
            const sYr = parseInt(startYearEl.value) || 2027;
            endYearEl.value = sYr + 7;
        }
    } else if (selPreset === 'rule_72t_sepp') {
        if (nameInput) nameInput.value = 'Rule 72(t) SEPP Pre-59½ Retirement Bridge';
        if (amtInput) amtInput.value = '120000';
        if (taxRateEl) taxRateEl.value = '22';
        if (startYearEl && endYearEl) {
            const sYr = parseInt(startYearEl.value) || 2027;
            endYearEl.value = Math.max(sYr, sYr + 9);
        }
    } else if (selPreset === 'bracket_32' || selPreset === '250000') {
        if (nameInput) nameInput.value = 'Annual Roth Conversion Ladder (32% Bracket)';
        if (amtInput) amtInput.value = '250000';
        if (taxRateEl) taxRateEl.value = '32';
        if (startYearEl && endYearEl) {
            const sYr = parseInt(startYearEl.value) || 2027;
            endYearEl.value = sYr + 4;
        }
    } else {
        if (nameInput) nameInput.value = 'Annual Roth Conversion Ladder';
        if (amtInput && selPreset !== 'custom') amtInput.value = (selPreset === 'bracket_24') ? '150000' : selPreset;
        if (taxRateEl && selPreset === 'bracket_24') taxRateEl.value = '24';
        if (startYearEl && endYearEl) {
            const sYr = parseInt(startYearEl.value) || 2027;
            endYearEl.value = sYr + 4;
        }
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
    const selTier = tier || document.getElementById('select-superfund-tier')?.value || '380000';
    if (nameInput) nameInput.value = `${childName}'s 5-Year 529 Superfund`;
    if (amtInput && selTier !== 'custom') amtInput.value = selTier;
    if (startYearEl && endYearEl) {
        endYearEl.value = startYearEl.value || '2027';
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
        const sYr = parseInt(startYearEl.value) || 2027;
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
        const sYr = parseInt(startYearEl.value) || 2027;
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
        const sYr = parseInt(startYearEl.value) || 2027;
        endYearEl.value = sYr + 4;
    }
    setSelectedEventIcon('evt-asset-split', false);
}
