/**
 * Scenario Plan Edit Modal
 * Handles opening and populating the scenario edit modal dialog.
 */
import { state, fmtCurrency } from './state.js';
import {
    setModalScenarioObj, setModalSelectedEventIds,
    setModalEventsSearchQuery, updateModalEventsCountBadge,
    setModalScenarioTab
} from './modals_plan_state.js';

const THEME_COLOR_PALETTE = ['#1D4ED8', '#059669', '#0284C7', '#D97706', '#0D9488', '#C75D6E', '#64748B'];
const LEGACY_COLOR_ALIASES = {
    '#0265E8': '#1D4ED8',
    '#3B82F6': '#1D4ED8',
    '#10B981': '#059669',
    '#F59E0B': '#D97706',
    '#14B8A6': '#0D9488',
    '#EF4444': '#C75D6E',
    '#F43F5E': '#C75D6E',
};

export function normalizeScenarioThemeColor(rawColor) {
    const up = String(rawColor || '').trim().toUpperCase();
    return LEGACY_COLOR_ALIASES[up] || up;
}

export function pickUnusedScenarioColor(scenarios = []) {
    const used = new Set();
    (scenarios || []).forEach(s => {
        const norm = normalizeScenarioThemeColor(s?.color);
        if (norm) used.add(norm);
    });
    for (const c of THEME_COLOR_PALETTE) {
        if (!used.has(c)) return c;
    }
    return THEME_COLOR_PALETTE[(scenarios || []).length % THEME_COLOR_PALETTE.length];
}

export function syncScenarioColorSwatches(selectedColor) {
    const colorInput = document.getElementById('input-scenario-color');
    const normSelected = normalizeScenarioThemeColor(selectedColor || colorInput?.value || '#1D4ED8');
    if (colorInput && selectedColor) {
        colorInput.value = selectedColor;
    }
    const container = document.getElementById('scenario-color-swatches');
    if (!container) return;

    container.querySelectorAll('.scenario-color-swatch').forEach(swatch => {
        const swatchColor = String(swatch.getAttribute('data-color') || '').trim().toUpperCase();
        const isActive = swatchColor === normSelected;
        swatch.classList.toggle('active', isActive);
        swatch.style.borderColor = isActive ? 'var(--text-primary, #FFFFFF)' : 'transparent';
        swatch.style.boxShadow = isActive ? '0 0 0 2px var(--accent-blue, #3B82F6)' : 'none';
        swatch.onclick = () => {
            if (colorInput) colorInput.value = swatchColor;
            syncScenarioColorSwatches(swatchColor);
        };
    });

    if (colorInput && !colorInput.dataset.swatchWired) {
        colorInput.dataset.swatchWired = 'true';
        colorInput.addEventListener('input', () => syncScenarioColorSwatches(colorInput.value));
        colorInput.addEventListener('change', () => syncScenarioColorSwatches(colorInput.value));
    }
}

function setFieldOverride(id, isOverridden, val, inheritedText, defaultPlaceholder) {
    const el = document.getElementById(id);
    if (!el) return;
    if (!isOverridden) {
        el.value = '';
        el.placeholder = inheritedText;
    } else {
        el.value = (val !== undefined && val !== null) ? val : '';
        el.placeholder = defaultPlaceholder;
    }
}

export function openEditScenarioModal(scen, defaultTab = 'assumptions') {
    const modalScen = document.getElementById('modal-scenario');
    if (!modalScen) return;

    setModalScenarioObj(scen);
    setModalSelectedEventIds(new Set(scen.event_ids || []));
    setModalEventsSearchQuery('');

    document.getElementById('modal-scenario-title').textContent = `Edit Plan: ${scen.name}`;
    const sub = document.getElementById('modal-scenario-subtitle');
    if (sub) sub.textContent = `Configure parameters and manage included events for "${scen.name}".`;

    const modalBtnDelete = document.getElementById('modal-btn-delete-scenario');
    if (modalBtnDelete) {
        modalBtnDelete.style.display = (scen.id === 'scen_baseline') ? 'none' : 'inline-flex';
    }
    document.getElementById('input-scenario-id').value = scen.id;
    document.getElementById('input-scenario-name').value = scen.name;
    document.getElementById('input-scenario-desc').value = scen.description || '';
    const scenColor = scen.color || '#1D4ED8';
    document.getElementById('input-scenario-color').value = scenColor;
    syncScenarioColorSwatches(scenColor);
    const hasParent = Boolean(scen.parent_id);
    const overrides = scen.overrides || {};
    const isOverridden = (key) => overrides[key] !== undefined && overrides[key] !== null;

    setFieldOverride(
        'input-scenario-spend',
        !hasParent || isOverridden('annual_living_spend'),
        scen.annual_living_spend,
        scen.annual_living_spend ? `Inherited: $${Math.round(scen.annual_living_spend).toLocaleString()}/yr (blank = inherit)` : 'Blank = inherit parent',
        'Annual living spend'
    );

    setFieldOverride(
        'input-scenario-savings',
        !hasParent || isOverridden('annual_savings'),
        scen.annual_savings,
        (scen.annual_savings !== undefined && scen.annual_savings !== null) ? `Inherited: $${Math.round(scen.annual_savings).toLocaleString()}/yr (blank = inherit)` : 'e.g. 60000 (blank = inherit)',
        'e.g. 60000'
    );

    setFieldOverride(
        'input-scenario-inflation',
        !hasParent || isOverridden('inflation_rate'),
        scen.inflation_rate,
        (scen.inflation_rate !== undefined && scen.inflation_rate !== null) ? `Inherited: ${(scen.inflation_rate * 100).toFixed(1)}% (blank = inherit)` : 'e.g. 0.025 (blank = inherit)',
        'e.g. 0.025'
    );

    setFieldOverride(
        'input-scenario-ret-age',
        !hasParent || isOverridden('primary_retirement_age'),
        scen.primary_retirement_age,
        scen.primary_retirement_age ? `Inherited: Age ${scen.primary_retirement_age} (blank = inherit)` : 'e.g. 50 (blank = inherit)',
        'e.g. 50'
    );

    setFieldOverride(
        'input-scenario-ret-spouse',
        !hasParent || isOverridden('spouse_retirement_age'),
        scen.spouse_retirement_age,
        scen.spouse_retirement_age ? `Inherited: Age ${scen.spouse_retirement_age} (blank = inherit)` : 'e.g. 52 (blank = inherit)',
        'e.g. 52'
    );

    setFieldOverride(
        'input-scenario-primary-ss-age',
        !hasParent || isOverridden('primary_ss_claim_age') || isOverridden('ss_claim_age'),
        (scen.primary_ss_claim_age !== undefined && scen.primary_ss_claim_age !== null) ? scen.primary_ss_claim_age : (scen.ss_claim_age || ''),
        `Inherited: Age ${scen.primary_ss_claim_age || scen.ss_claim_age || 67} (blank = inherit)`,
        'e.g. 67'
    );

    setFieldOverride(
        'input-scenario-spouse-ss-age',
        !hasParent || isOverridden('spouse_ss_claim_age'),
        scen.spouse_ss_claim_age,
        `Inherited: Age ${scen.spouse_ss_claim_age || 67} (blank = inherit)`,
        'e.g. 67'
    );

    const selParent = document.getElementById('select-scenario-parent');
    const groupParent = document.getElementById('group-scenario-parent-select');
    if (selParent) {
        if (scen.id === 'scen_baseline') {
            if (groupParent) groupParent.style.display = 'none';
            selParent.value = '';
        } else {
            if (groupParent) groupParent.style.display = 'block';
            selParent.innerHTML = '<option value="">None (Independent Root Plan)</option>';
            const allScens = state.scenariosData?.scenarios || [];

            const descendantIds = new Set([scen.id]);
            let addedMore = true;
            while (addedMore) {
                addedMore = false;
                for (const s of allScens) {
                    if (s.parent_id && descendantIds.has(s.parent_id) && !descendantIds.has(s.id)) {
                        descendantIds.add(s.id);
                        addedMore = true;
                    }
                }
            }

            allScens.forEach(s => {
                if (!descendantIds.has(s.id)) {
                    const opt = document.createElement('option');
                    opt.value = s.id;
                    opt.textContent = `${s.name}${s.parent_name ? ' (↳ ' + s.parent_name + ')' : ''}`;
                    if (scen.parent_id === s.id) opt.selected = true;
                    selParent.appendChild(opt);
                }
            });
        }
    }

    const selGrowth = document.getElementById('select-scenario-equity-preset');
    const customGrp = document.getElementById('group-scenario-custom-equity-growth');
    const inputCustom = document.getElementById('input-scenario-custom-equity-growth');
    const badgeEquity = document.getElementById('modal-scen-equity-company-badge');

    const companies = state.scenariosData?.equity_companies || [];
    if (badgeEquity && companies.length) {
        const comp = companies[0];
        badgeEquity.textContent = `${comp.company_name} (${comp.current_fmv ? fmtCurrency(comp.current_fmv, 2) : 'FMV Pending'})`;
    }

    const isEquityOverridden = isOverridden('equity_growth_preset');
    if (selGrowth) {
        selGrowth.value = (hasParent && !isEquityOverridden) ? 'inherit' : (scen.equity_growth_preset || 'moderate');
    }
    if (customGrp) customGrp.style.display = (selGrowth?.value === 'custom') ? 'block' : 'none';
    if (inputCustom) {
        inputCustom.value = (scen.custom_equity_growth_rate !== undefined && scen.custom_equity_growth_rate !== null) ? scen.custom_equity_growth_rate : '';
    }

    const setModalGrowthInput = (id, key, val) => {
        const el = document.getElementById(id);
        if (!el) return;
        if (hasParent && !isOverridden(key)) {
            el.value = '';
            el.placeholder = (val !== undefined && val !== null) ? `Inherited: ${(val * 100).toFixed(1)}% (blank = inherit)` : 'Leave blank to inherit';
        } else {
            el.value = (val !== undefined && val !== null) ? val : '';
            el.placeholder = 'e.g. 0.085';
        }
    };
    setModalGrowthInput('input-scenario-growth-us', 'growth_us_equity', scen.growth_us_equity);
    setModalGrowthInput('input-scenario-growth-intl', 'growth_intl_equity', scen.growth_intl_equity);
    setModalGrowthInput('input-scenario-growth-bonds', 'growth_bonds', scen.growth_bonds);
    setModalGrowthInput('input-scenario-growth-cash', 'growth_cash', scen.growth_cash);
    setModalGrowthInput('input-scenario-growth-private', 'growth_private_investments', scen.growth_private_investments);
    setModalGrowthInput('input-scenario-growth-re', 'growth_real_estate', scen.growth_real_estate);

    const panelPreset = document.getElementById('panel-scenario-preset-select');
    if (panelPreset) panelPreset.style.display = 'none';

    updateModalEventsCountBadge();
    setModalScenarioTab(defaultTab);
    modalScen.style.display = 'flex';
}
