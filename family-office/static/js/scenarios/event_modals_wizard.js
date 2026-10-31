/**
 * static/js/scenarios/event_modals_wizard.js
 * Life-Event Wizard controls initialization and DOM event bindings.
 */

import { getPlanStartYear } from './state.js';
import {
    filterWizardTemplateOptions,
    renderEventIconPickerGrid,
    setSelectedEventIcon,
    TEMPLATE_DEFAULT_ICONS
} from './event_modals_presets.js';
import {
    syncRefinanceFields,
    setCollegeSourceMode,
    setEduSourceMode,
    updateWizardPanels
} from './event_modals_fields.js';
import {
    syncCapitalOutflowFields,
    syncCapitalInflowFields,
    syncRealEstateActionFields,
    syncRenovationFields,
    syncSabbaticalFields,
    syncGradSchoolFields,
    syncPhilanthropyDafFields,
    syncStateRelocationFields,
    syncRothConversionFields,
    syncSuperfund529Fields
} from './event_modals_syncers.js';
import { buildEventPayload, submitSaveEvent } from './event_modals_save.js';
import { tierCost } from './event_modals_inputs.js';
import { delegate } from './event_delegation.js';

function byId(id) {
    return document.getElementById(id);
}

function hideEventModal() {
    const m = byId('modal-event');
    if (m) m.style.display = 'none';
}

function toggleIconPicker(e) {
    e.preventDefault();
    e.stopPropagation();
    renderEventIconPickerGrid();
    const drawer = byId('panel-event-icon-picker');
    if (!drawer) return;
    const isOpening = (drawer.style.display === 'none' || !drawer.style.display);
    drawer.style.display = isOpening ? 'block' : 'none';
    if (isOpening) byId('input-search-event-icon')?.focus();
}

function renameRefinanceFromTerm(selTerm) {
    const refType = byId('select-refinance-type').value;
    const nameInput = byId('input-event-name');
    if (nameInput && nameInput.value.startsWith('Refinance Mortgage')) {
        nameInput.value = refType === 'arm'
            ? `Refinance Mortgage (${selTerm.value}/1 ARM)`
            : `Refinance Mortgage (${selTerm.value}-Yr Fixed)`;
    }
}

function applyCollegeChild(sel) {
    const opt = sel.options[sel.selectedIndex];
    if (!opt) return;
    const nameInput = byId('input-event-name');
    if (nameInput) nameInput.value = `${opt.text.split('(')[0].trim()}'s College Tuition (4-Yr 529 Draw)`;
    if (opt.dataset.matr) {
        const sYr = parseInt(opt.dataset.matr);
        byId('input-event-year').value = sYr;
        byId('input-event-end-year').value = sYr + 3;
    }
    const b529 = byId('badge-college-529-balance');
    if (b529 && opt.dataset.bal) {
        b529.textContent = `529 Reserve: $${Math.round(parseFloat(opt.dataset.bal)).toLocaleString()}`;
    }
}

async function submitWizardForm(form) {
    const template = byId('select-event-template').value;
    const id = byId('input-event-id').value;
    const startYear = parseInt(byId('input-event-year').value) || getPlanStartYear() + 1;
    const endYear = parseInt(byId('input-event-end-year').value) || startYear;
    const selectedIcon = byId('input-event-icon')?.value || TEMPLATE_DEFAULT_ICONS[template] || '';
    const eventPayload = buildEventPayload(
        template, id, byId('input-event-name').value, startYear, endYear,
        byId('select-event-source').value, byId('input-event-desc').value, selectedIcon
    );
    await submitSaveEvent(eventPayload, id, hideEventModal);
}

// One listener per event type on the document, dispatching on element id: the wizard's inputs live inside a
// section that HTMX morphs, and delegation needs no per-node bookkeeping to survive that.
function buildWizardHandlers() {
    return {
        input: {
            'input-search-wizard-template': (el) => filterWizardTemplateOptions(el.value),
            'input-search-event-icon': (el) => renderEventIconPickerGrid(el.value)
        },
        change: {
            'select-refinance-type': (el) => syncRefinanceFields(el.value),
            'select-refinance-term': renameRefinanceFromTerm,
            'select-college-child': applyCollegeChild,
            'select-college-tier': (el) => {
                const amtInput = byId('input-event-amount');
                const cost = tierCost('select-college-tier');
                if (cost !== null && amtInput) amtInput.value = cost;
            },
            'select-outflow-purpose': (el) => syncCapitalOutflowFields(el.value),
            'select-inflow-source-type': (el) => syncCapitalInflowFields(el.value),
            'select-re-action': (el) => syncRealEstateActionFields(el.value),
            'select-renovation-scope': (el) => syncRenovationFields(el.value),
            'select-sabbatical-mode': (el) => syncSabbaticalFields(el.value),
            'select-grad-program': (el) => syncGradSchoolFields(el.value),
            'select-daf-structure': (el) => syncPhilanthropyDafFields(el.value),
            'select-reloc-from': () => syncStateRelocationFields(),
            'select-reloc-to': () => syncStateRelocationFields(),
            'select-roth-preset': (el) => syncRothConversionFields(el.value),
            'select-superfund-child': () => syncSuperfund529Fields(),
            'select-superfund-tier': (el) => syncSuperfund529Fields(el.value),
            'select-event-template': (el) => updateWizardPanels(el.value)
        },
        click: {
            'btn-toggle-event-icon-picker': (el, e) => toggleIconPicker(e),
            'btn-college-mode-sync': () => setCollegeSourceMode('sync'),
            'btn-college-mode-override': () => setCollegeSourceMode('override'),
            'btn-edu-mode-sync': () => setEduSourceMode('sync'),
            'btn-edu-mode-override': () => setEduSourceMode('override'),
            'btn-add-catalog-event': () => window.openCreateEventModal(),
            'btn-close-modal-event': hideEventModal,
            'btn-cancel-modal-event': hideEventModal
        },
        submit: {
            'form-event': (form, e) => {
                e.preventDefault();
                return submitWizardForm(form);
            }
        }
    };
}

export function initEventWizardControls() {
    delegate(document, 'wizard', buildWizardHandlers);
    renderEventIconPickerGrid();
    setSelectedEventIcon(byId('input-event-icon')?.value || 'evt-capital-outflow', false, true);
}
