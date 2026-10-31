/**
 * static/js/scenarios/event_modals_render.js
 * Edit event form pre-fill and dynamic dropdown population.
 */

import { state, getPlanStartYear } from './state.js';
import {
    filterWizardTemplateOptions,
    renderEventIconPickerGrid,
    setSelectedEventIcon,
    TEMPLATE_DEFAULT_ICONS
} from './event_modals_presets.js';
import { getWizardPanels, setAmountBasis } from './event_modals_fields.js';
import { cloneEvent } from './event_modals_catalog.js';
import { prefillCategoryFields } from './event_modals_prefill.js';

// Household-dependent wizard selects and the server fragment kind that fills each (see
// routes/fragments/scenario_wizard_options.py).
const DYNAMIC_SELECTS = [
    ['select-edu-child', 'children'],
    ['select-grad-child', 'children'],
    ['select-superfund-child', 'children'],
    ['select-eldercare-parent', 'parents'],
    ['select-college-child', 'college_children'],
];

function loadWizardOptions(selectId, kind) {
    return window.htmx.ajax('GET', `/fragments/scenario_wizard_options?kind=${kind}`, {
        target: `#${selectId}`, swap: 'innerHTML',
    });
}

export async function populateWizardDynamicDropdowns() {
    const present = DYNAMIC_SELECTS.filter(([id]) => document.getElementById(id));
    await Promise.all(present.map(([id, kind]) => loadWizardOptions(id, kind)));
    const firstCollege = document.getElementById('select-college-child')?.options[0];
    const badge = document.getElementById('badge-college-529-balance');
    if (badge && firstCollege?.dataset.bal && Number(firstCollege.dataset.bal) > 0) {
        badge.textContent = `529 Reserve: $${Math.round(Number(firstCollege.dataset.bal)).toLocaleString()}`;
    }
}

export function openEditEventModal(eventId) {
    const modalEvent = document.getElementById('modal-event');
    if (!modalEvent || !state.scenariosData) return;

    const ev = (state.scenariosData.events_catalog || []).find(e => e.id === eventId);
    if (!ev) return;

    const searchTmplInput = document.getElementById('input-search-wizard-template');
    if (searchTmplInput) searchTmplInput.value = '';
    filterWizardTemplateOptions('');

    const searchIconInput = document.getElementById('input-search-event-icon');
    if (searchIconInput) searchIconInput.value = '';
    renderEventIconPickerGrid('');

    const drawer = document.getElementById('panel-event-icon-picker');
    if (drawer) drawer.style.display = 'none';

    populateWizardDynamicDropdowns().then(() => {
        document.getElementById('modal-event-title').textContent = `Edit Event: ${ev.name}`;
        document.getElementById('input-event-id').value = ev.id;
        document.getElementById('input-event-name').value = ev.name;
        document.getElementById('input-event-year').value = ev.year || getPlanStartYear() + 1;
        document.getElementById('input-event-end-year').value = ev.end_year || ev.year || getPlanStartYear() + 1;
        document.getElementById('input-event-desc').value = ev.description || '';

        if (ev.funding_source) {
            const selSource = document.getElementById('select-event-source');
            if (selSource) selSource.value = ev.funding_source;
        }

        let mappedTemplate = ev.category || 'capital_outflow';
        if (mappedTemplate === 'home_sale') {
            mappedTemplate = 'real_estate';
        } else if (mappedTemplate === 'income_change') {
            mappedTemplate = 'sabbatical';
        } else if (['wedding', 'child_home_gift', 'new_child', 'vehicle_purchase', 'angel_investment', 'medical_expense', 'withdrawal'].includes(mappedTemplate)) {
            mappedTemplate = 'capital_outflow';
        } else if (['rental_income', 'deferred_comp', 'windfall', 'custom_spike'].includes(mappedTemplate)) {
            mappedTemplate = 'capital_inflow';
        }

        const selectTemplate = document.getElementById('select-event-template');
        if (selectTemplate) {
            selectTemplate.value = mappedTemplate;
            const panels = getWizardPanels();
            Object.keys(panels).forEach(k => {
                if (panels[k]) panels[k].style.display = (k === mappedTemplate) ? 'block' : 'none';
            });
        }

        const initialIcon = ev.icon || TEMPLATE_DEFAULT_ICONS[ev.category] || TEMPLATE_DEFAULT_ICONS[mappedTemplate] || 'evt-capital-outflow';
        setSelectedEventIcon(initialIcon, Boolean(ev.icon), !ev.icon);
        prefillCategoryFields(mappedTemplate, ev);
        setAmountBasis(ev.category || mappedTemplate, ev.amount_basis);

        const btnCloneEvt = document.getElementById('modal-btn-clone-event');
        if (btnCloneEvt) {
            btnCloneEvt.style.display = 'inline-flex';
            btnCloneEvt.onclick = () => {
                modalEvent.style.display = 'none';
                cloneEvent(ev.id);
            };
        }

        modalEvent.style.display = 'flex';
    });
}
