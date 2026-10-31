/**
 * Scenario Plan Edit Modal
 * Handles opening and populating the scenario edit modal dialog.
 */
import { state, fmtCurrency } from './state.js';
import { delegate } from './event_delegation.js';
import {
    setModalScenarioObj, setModalSelectedEventIds,
    setModalEventsSearchQuery, resetModalChecklistView, updateModalEventsCountBadge,
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
    const headerDot = document.getElementById('modal-scenario-header-color-dot');
    if (headerDot) {
        const dotColor = selectedColor || colorInput?.value || '#1D4ED8';
        headerDot.style.background = dotColor;
        headerDot.style.boxShadow = `0 0 0 3px ${dotColor}2E`;
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

    installPlanEditDelegation();
}

const MODAL_INHERITED_SELECT_ID = 'select-scenario-equity-preset';

function resetAllOverrides() {
    MODAL_INHERITABLE_INPUT_IDS.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    const selEq = document.getElementById(MODAL_INHERITED_SELECT_ID);
    if (selEq) {
        selEq.value = 'inherit';
        selEq.dispatchEvent(new Event('change', { bubbles: true }));
    }
    syncModalFieldInheritanceUI();
}

/** Document-level listeners for the plan modal's colour, inheritance and parent controls; installed once. */
function installPlanEditDelegation() {
    delegate(document, 'plan-edit', () => {
        const refresh = () => syncModalFieldInheritanceUI();
        const inheritable = Object.fromEntries(
            [...MODAL_INHERITABLE_INPUT_IDS, MODAL_INHERITED_SELECT_ID].map(id => [id, refresh])
        );
        const color = (el) => syncScenarioColorSwatches(el.value);
        return {
            input: { ...inheritable, 'input-scenario-color': color },
            change: { ...inheritable, 'input-scenario-color': color, 'select-scenario-parent': refresh },
            click: { 'btn-modal-reset-all-overrides': resetAllOverrides }
        };
    });
}

const MODAL_INHERITABLE_INPUT_IDS = [
    'input-scenario-spend',
    'input-scenario-savings',
    'input-scenario-ret-age',
    'input-scenario-ret-spouse',
    'input-scenario-primary-ss-age',
    'input-scenario-spouse-ss-age',
    'input-scenario-inflation',
    'input-scenario-growth-us',
    'input-scenario-growth-intl',
    'input-scenario-growth-bonds',
    'input-scenario-growth-cash',
    'input-scenario-growth-private',
    'input-scenario-growth-re',
];

export function syncModalFieldInheritanceUI() {
    const selParent = document.getElementById('select-scenario-parent');
    const groupParent = document.getElementById('group-scenario-parent-select');
    const isParentVisible = !groupParent || groupParent.style.display !== 'none';
    const hasParent = Boolean(isParentVisible && selParent && selParent.value);

    let overrideCount = 0;

    const applyFieldState = (id, isSelect = false) => {
        const el = document.getElementById(id);
        const pill = document.querySelector(`.scen-state-pill[data-state-for="${id}"]`);
        if (!el) return;

        const rawVal = String(el.value ?? '').trim();
        const isOverridden = isSelect ? (rawVal !== '' && rawVal !== 'inherit') : (rawVal !== '');

        el.classList.remove('is-inherited-field', 'is-overridden-field', 'is-root-field');
        if (!hasParent) {
            el.classList.add('is-root-field');
            if (pill) {
                pill.className = 'scen-state-pill scen-state-pill--root';
                pill.textContent = 'Baseline';
                pill.title = 'Root plan baseline value';
                pill.onclick = null;
            }
        } else if (isOverridden) {
            overrideCount += 1;
            el.classList.add('is-overridden-field');
            if (pill) {
                pill.className = 'scen-state-pill scen-state-pill--overridden';
                pill.textContent = '● Custom ✕';
                pill.title = 'Custom override in this plan (click to reset to parent)';
                pill.onclick = (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    if (isSelect) {
                        el.value = 'inherit';
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    } else {
                        el.value = '';
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                    }
                    syncModalFieldInheritanceUI();
                };
            }
        } else {
            el.classList.add('is-inherited-field');
            if (pill) {
                pill.className = 'scen-state-pill scen-state-pill--inherited';
                pill.textContent = '↳ Inherited';
                pill.title = 'Dynamically inherited from parent plan';
                pill.onclick = null;
            }
        }
    };

    MODAL_INHERITABLE_INPUT_IDS.forEach(id => applyFieldState(id, false));
    applyFieldState('select-scenario-equity-preset', true);

    const summaryBadge = document.getElementById('modal-scen-override-summary-badge');
    const resetAllBtn = document.getElementById('btn-modal-reset-all-overrides');

    if (summaryBadge) {
        if (!hasParent) {
            summaryBadge.className = 'badge badge-blue';
            summaryBadge.textContent = 'Root Plan (Baseline Source)';
        } else if (overrideCount > 0) {
            summaryBadge.className = 'badge badge-orange';
            summaryBadge.textContent = `${overrideCount} Custom Override${overrideCount === 1 ? '' : 's'}`;
        } else {
            summaryBadge.className = 'badge badge-gray';
            summaryBadge.textContent = '100% Inherited from Parent';
        }
    }

    if (resetAllBtn) {
        resetAllBtn.style.display = (hasParent && overrideCount > 0) ? 'inline-flex' : 'none';
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
    resetModalChecklistView();

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
    const inputArchived = document.getElementById('input-scenario-archived');
    const groupArchived = document.getElementById('group-scenario-archived');
    if (inputArchived) {
        inputArchived.checked = Boolean(scen.is_archived);
        const isDisallowed = (scen.id === 'scen_baseline' || scen.id === state.scenariosData?.active_scenario_id);
        inputArchived.disabled = isDisallowed;
        if (groupArchived) {
            groupArchived.title = isDisallowed
                ? (scen.id === 'scen_baseline' ? 'The Baseline Plan cannot be archived.' : 'The active Plan of Record cannot be archived.')
                : '';
        }
    }
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
            const descendantIds = new Set([scen.id]);
            let addedMore = true;
            while (addedMore) {
                addedMore = false;
                for (const s of state.scenariosData?.scenarios || []) {
                    if (s.parent_id && descendantIds.has(s.parent_id) && !descendantIds.has(s.id)) {
                        descendantIds.add(s.id);
                        addedMore = true;
                    }
                }
            }
            Array.from(selParent.options).forEach(opt => {
                const blocked = descendantIds.has(opt.value);
                opt.hidden = blocked;
                opt.disabled = blocked;
            });
            selParent.value = scen.parent_id || '';
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
    syncModalFieldInheritanceUI();
    setModalScenarioTab(defaultTab);
    modalScen.style.display = 'flex';
}
