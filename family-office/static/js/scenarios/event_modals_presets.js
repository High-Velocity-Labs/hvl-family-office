/**
 * static/js/scenarios/event_modals_presets.js
 * Default icons, icon picker grid, and template search keywords.
 */

import { getEventIcon, ICON_PICKER_GROUPS } from './state.js';
import { updateWizardPanels } from './event_modals_fields.js';

export const TEMPLATE_DEFAULT_ICONS = {
    'state_relocation': 'evt-relocation',
    'roth_conversion': 'evt-roth-ladder',
    'superfund_529': 'evt-529-superfund',
    'pe_capital_call': 'evt-j-curve',
    'ltc_insurance': 'evt-ltc-shield',
    'marital_settlement': 'evt-asset-split',
    'capital_outflow': 'evt-capital-outflow',
    'capital_inflow': 'evt-capital-inflow',
    'real_estate': 'evt-vacation-home',
    'home_renovation': 'evt-renovation',
    'home_sale': 'evt-home-sale',
    'sabbatical': 'evt-briefcase',
    'income_change': 'evt-briefcase',
    'college': 'evt-college',
    'grad_school': 'evt-grad-school',
    'education': 'evt-k12',
    'philanthropy_daf': 'evt-philanthropy',
    'company_equity': 'evt-equity',
    'lifestyle': 'evt-travel',
    'eldercare': 'evt-eldercare',
    'gifting': 'evt-gifting',
    'debt_payoff': 'evt-debt',
    'refinance': 'evt-refi',
};

export const TEMPLATE_SEARCH_KEYWORDS = {
    state_relocation: 'relocate relocation move state tax domicile ca ny wa nv tx fl arbitrage',
    roth_conversion: 'roth conversion ladder ira 401k bracket tax free backdoor',
    superfund_529: '529 superfund superfunding 5-year gift tax election front-load college child',
    philanthropy_daf: 'charitable charity daf donor advised fund philanthropy donation tax deduction',
    gifting: 'gift gifting family annual exclusion transfer',
    real_estate: 'real estate buy house home primary residence vacation property sell downsize upgrade',
    home_renovation: 'renovation remodel adu kitchen bath contractor home equity upgrade',
    debt_payoff: 'debt mortgage payoff loan pay off',
    refinance: 'refinance refi mortgage arm fixed rate',
    college: 'college university undergraduate tuition 529 school',
    grad_school: 'grad graduate school mba med medical law jd md masters degree tuition 529',
    education: 'k-12 k12 private school tuition elementary high school',
    eldercare: 'eldercare elder care parent assisted living memory nursing home',
    ltc_insurance: 'ltc long term care insurance hybrid policy shield healthcare',
    marital_settlement: 'marital settlement divorce asset split qdro alimony support Prenup',
    company_equity: 'equity stock option exercise rsu iso nso liquidity tender',
    sabbatical: 'sabbatical career pivot break coast fire part-time consulting pause income',
    pe_capital_call: 'pe private equity vc venture capital call j-curve lp commitment harvest moic tvpi',
    capital_inflow: 'inflow windfall bonus business sale exit inheritance trust rental pension annuity royalty income',
    capital_outflow: 'outflow milestone wedding ring celebration child home down payment gift car vehicle ev boat yacht plane baby adoption angel seed medical solar art watch tax legal',
    lifestyle: 'lifestyle travel surge aviation jet vacation recurring spend',
};

export function setSelectedEventIcon(iconKey, isManual = false, force = false) {
    const iconInput = document.getElementById('input-event-icon');
    const previewEl = document.getElementById('preview-selected-event-icon');
    if (!iconInput) return;

    if (!isManual && !force && iconInput.dataset.manualOverride === 'true') {
        return;
    }
    if (isManual) {
        iconInput.dataset.manualOverride = 'true';
    } else if (force) {
        iconInput.dataset.manualOverride = 'false';
    }

    const resolvedKey = iconKey || 'evt-capital-outflow';
    iconInput.value = resolvedKey;
    if (previewEl) {
        previewEl.replaceChildren(getEventIcon(resolvedKey, 16));
    }

    const grid = document.getElementById('grid-event-icon-picker');
    if (grid) {
        grid.querySelectorAll('.btn-icon-picker-choice').forEach(btn => {
            const active = btn.getAttribute('data-icon-id') === resolvedKey;
            btn.classList.toggle('is-selected', active);
        });
    }
}

export function renderEventIconPickerGrid(filterQuery = null) {
    const grid = document.getElementById('grid-event-icon-picker');
    if (!grid) return;

    const searchInput = document.getElementById('input-search-event-icon');
    const q = (filterQuery !== null ? String(filterQuery) : (searchInput?.value || '')).toLowerCase().trim();

    if (grid.dataset.rendered === 'true' && grid.dataset.lastQuery === q) {
        return;
    }
    grid.dataset.rendered = 'true';
    grid.dataset.lastQuery = q;
    grid.replaceChildren();

    const currentKey = document.getElementById('input-event-icon')?.value || 'evt-capital-outflow';
    let totalMatched = 0;

    ICON_PICKER_GROUPS.forEach(groupObj => {
        const matchingIcons = q
            ? groupObj.icons.filter(item => (`${item.label} ${item.id} ${groupObj.group}`).toLowerCase().includes(q))
            : groupObj.icons;

        if (matchingIcons.length === 0) return;
        totalMatched += matchingIcons.length;

        const sec = document.createElement('div');
        const header = document.createElement('div');
        header.className = 'wizard-icon-group-header';
        header.textContent = groupObj.group;
        sec.appendChild(header);

        const row = document.createElement('div');
        row.className = 'wizard-icon-group-row';

        matchingIcons.forEach(item => {
            const btn = document.createElement('button');
            btn.type = 'button';
            const active = item.id === currentKey;
            btn.className = `btn-icon-picker-choice${active ? ' is-selected' : ''}`;
            btn.setAttribute('data-icon-id', item.id);
            btn.setAttribute('data-tooltip', item.label);
            btn.title = item.label;
            btn.appendChild(getEventIcon(item.id, 16));
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                setSelectedEventIcon(item.id, true);
                const drawer = document.getElementById('panel-event-icon-picker') || document.getElementById('drawer-event-icon-picker');
                if (drawer) {
                    drawer.hidden = true;
                    drawer.classList.add('hidden');
                }
            });
            row.appendChild(btn);
        });

        sec.appendChild(row);
        grid.appendChild(sec);
    });

    if (totalMatched === 0) {
        grid.appendChild(document.getElementById('tmpl-icon-picker-empty').content.cloneNode(true));
    }
}

export function filterWizardTemplateOptions(query = '') {
    const selectTemplate = document.getElementById('select-event-template');
    if (!selectTemplate) return;
    const q = String(query || '').toLowerCase().trim();

    let firstVisibleOpt = null;
    const optgroups = selectTemplate.querySelectorAll('optgroup');
    if (optgroups.length > 0) {
        optgroups.forEach(grp => {
            const grpLabel = (grp.getAttribute('label') || '').toLowerCase();
            let visibleInGroup = 0;
            grp.querySelectorAll('option').forEach(opt => {
                const extraKw = TEMPLATE_SEARCH_KEYWORDS[opt.value] || '';
                const hay = `${opt.textContent} ${opt.value} ${grpLabel} ${extraKw}`.toLowerCase();
                const matches = !q || hay.includes(q);
                opt.hidden = !matches;
                if (matches) {
                    visibleInGroup++;
                    if (!firstVisibleOpt) firstVisibleOpt = opt;
                }
            });
            grp.hidden = (visibleInGroup === 0);
        });
    } else {
        selectTemplate.querySelectorAll('option').forEach(opt => {
            const extraKw = TEMPLATE_SEARCH_KEYWORDS[opt.value] || '';
            const hay = `${opt.textContent} ${opt.value} ${extraKw}`.toLowerCase();
            const matches = !q || hay.includes(q);
            opt.hidden = !matches;
            if (matches && !firstVisibleOpt) firstVisibleOpt = opt;
        });
    }

    if (q && firstVisibleOpt) {
        selectTemplate.value = firstVisibleOpt.value;
        updateWizardPanels(firstVisibleOpt.value);
    }
}
