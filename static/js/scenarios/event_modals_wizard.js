/**
 * static/js/scenarios/event_modals_wizard.js
 * Life-Event Wizard controls initialization and DOM event bindings.
 */

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

function bindWizardIconAndSearchControls() {
    const searchTmplInput = document.getElementById('input-search-wizard-template');
    if (searchTmplInput && !searchTmplInput.dataset.wired) {
        searchTmplInput.dataset.wired = 'true';
        searchTmplInput.addEventListener('input', (e) => {
            filterWizardTemplateOptions(e.target.value);
        });
    }

    const searchIconInput = document.getElementById('input-search-event-icon');
    if (searchIconInput && !searchIconInput.dataset.wired) {
        searchIconInput.dataset.wired = 'true';
        searchIconInput.addEventListener('input', (e) => {
            renderEventIconPickerGrid(e.target.value);
        });
    }

    const btnToggleIconPicker = document.getElementById('btn-toggle-event-icon-picker');
    if (btnToggleIconPicker && !btnToggleIconPicker.dataset.wired) {
        btnToggleIconPicker.dataset.wired = 'true';
        btnToggleIconPicker.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            renderEventIconPickerGrid();
            const drawer = document.getElementById('panel-event-icon-picker');
            if (drawer) {
                const isOpening = (drawer.style.display === 'none' || !drawer.style.display);
                drawer.style.display = isOpening ? 'block' : 'none';
                if (isOpening) {
                    document.getElementById('input-search-event-icon')?.focus();
                }
            }
        });
    }
}

function bindWizardDropdownSyncers() {
    const selRefType = document.getElementById('select-refinance-type');
    if (selRefType && !selRefType.dataset.wired) {
        selRefType.dataset.wired = 'true';
        selRefType.addEventListener('change', (e) => {
            syncRefinanceFields(e.target.value);
        });
    }

    const selRefTerm = document.getElementById('select-refinance-term');
    if (selRefTerm && !selRefTerm.dataset.wired) {
        selRefTerm.dataset.wired = 'true';
        selRefTerm.addEventListener('change', () => {
            const refType = document.getElementById('select-refinance-type')?.value || 'fixed';
            const nameInput = document.getElementById('input-event-name');
            if (nameInput && nameInput.value.startsWith('Refinance Mortgage')) {
                nameInput.value = refType === 'arm'
                    ? `Refinance Mortgage (${selRefTerm.value}/1 ARM)`
                    : `Refinance Mortgage (${selRefTerm.value}-Yr Fixed)`;
            }
        });
    }

    const selCollegeChild = document.getElementById('select-college-child');
    if (selCollegeChild && !selCollegeChild.dataset.wired) {
        selCollegeChild.dataset.wired = 'true';
        selCollegeChild.addEventListener('change', () => {
            const opt = selCollegeChild.options[selCollegeChild.selectedIndex];
            if (opt) {
                const childName = opt.text.split('(')[0].trim();
                const nameInput = document.getElementById('input-event-name');
                if (nameInput) nameInput.value = `${childName}'s College Tuition (4-Yr 529 Draw)`;
                if (opt.dataset.matr) {
                    const sYr = parseInt(opt.dataset.matr);
                    document.getElementById('input-event-year').value = sYr;
                    document.getElementById('input-event-end-year').value = sYr + 3;
                }
                const b529 = document.getElementById('badge-college-529-balance');
                if (b529 && opt.dataset.bal) {
                    b529.textContent = `529 Reserve: $${Math.round(parseFloat(opt.dataset.bal)).toLocaleString()}`;
                }
            }
        });
    }

    const selCollegeTier = document.getElementById('select-college-tier');
    if (selCollegeTier && !selCollegeTier.dataset.wired) {
        selCollegeTier.dataset.wired = 'true';
        selCollegeTier.addEventListener('change', () => {
            const val = selCollegeTier.value;
            const amtInput = document.getElementById('input-event-amount');
            if (val !== 'custom' && amtInput) {
                amtInput.value = val;
            }
        });
    }

    const selOutflowPurpose = document.getElementById('select-outflow-purpose');
    if (selOutflowPurpose && !selOutflowPurpose.dataset.wired) {
        selOutflowPurpose.dataset.wired = 'true';
        selOutflowPurpose.addEventListener('change', (e) => syncCapitalOutflowFields(e.target.value));
    }

    const selInflowType = document.getElementById('select-inflow-source-type');
    if (selInflowType && !selInflowType.dataset.wired) {
        selInflowType.dataset.wired = 'true';
        selInflowType.addEventListener('change', (e) => syncCapitalInflowFields(e.target.value));
    }

    const selReAction = document.getElementById('select-re-action');
    if (selReAction && !selReAction.dataset.wired) {
        selReAction.dataset.wired = 'true';
        selReAction.addEventListener('change', (e) => syncRealEstateActionFields(e.target.value));
    }

    const selRenovScope = document.getElementById('select-renovation-scope');
    if (selRenovScope && !selRenovScope.dataset.wired) {
        selRenovScope.dataset.wired = 'true';
        selRenovScope.addEventListener('change', (e) => syncRenovationFields(e.target.value));
    }

    const selSabMode = document.getElementById('select-sabbatical-mode');
    if (selSabMode && !selSabMode.dataset.wired) {
        selSabMode.dataset.wired = 'true';
        selSabMode.addEventListener('change', (e) => syncSabbaticalFields(e.target.value));
    }

    const selGradProg = document.getElementById('select-grad-program');
    if (selGradProg && !selGradProg.dataset.wired) {
        selGradProg.dataset.wired = 'true';
        selGradProg.addEventListener('change', (e) => syncGradSchoolFields(e.target.value));
    }

    const selDafStruct = document.getElementById('select-daf-structure');
    if (selDafStruct && !selDafStruct.dataset.wired) {
        selDafStruct.dataset.wired = 'true';
        selDafStruct.addEventListener('change', (e) => syncPhilanthropyDafFields(e.target.value));
    }

    const selRelocFrom = document.getElementById('select-reloc-from');
    if (selRelocFrom && !selRelocFrom.dataset.wired) {
        selRelocFrom.dataset.wired = 'true';
        selRelocFrom.addEventListener('change', () => syncStateRelocationFields());
    }
    const selRelocTo = document.getElementById('select-reloc-to');
    if (selRelocTo && !selRelocTo.dataset.wired) {
        selRelocTo.dataset.wired = 'true';
        selRelocTo.addEventListener('change', () => syncStateRelocationFields());
    }

    const selRothPreset = document.getElementById('select-roth-preset');
    if (selRothPreset && !selRothPreset.dataset.wired) {
        selRothPreset.dataset.wired = 'true';
        selRothPreset.addEventListener('change', (e) => syncRothConversionFields(e.target.value));
    }

    const selSuperfundChild = document.getElementById('select-superfund-child');
    if (selSuperfundChild && !selSuperfundChild.dataset.wired) {
        selSuperfundChild.dataset.wired = 'true';
        selSuperfundChild.addEventListener('change', () => syncSuperfund529Fields());
    }
    const selSuperfundTier = document.getElementById('select-superfund-tier');
    if (selSuperfundTier && !selSuperfundTier.dataset.wired) {
        selSuperfundTier.dataset.wired = 'true';
        selSuperfundTier.addEventListener('change', (e) => syncSuperfund529Fields(e.target.value));
    }

    const selectTemplate = document.getElementById('select-event-template');
    if (selectTemplate && !selectTemplate.dataset.wired) {
        selectTemplate.dataset.wired = 'true';
        selectTemplate.addEventListener('change', (e) => {
            updateWizardPanels(e.target.value);
        });
    }

    const btnColSync = document.getElementById('btn-college-mode-sync');
    if (btnColSync && !btnColSync.dataset.wired) {
        btnColSync.dataset.wired = 'true';
        btnColSync.addEventListener('click', () => setCollegeSourceMode('sync'));
    }
    const btnColOvr = document.getElementById('btn-college-mode-override');
    if (btnColOvr && !btnColOvr.dataset.wired) {
        btnColOvr.dataset.wired = 'true';
        btnColOvr.addEventListener('click', () => setCollegeSourceMode('override'));
    }

    const btnEduSync = document.getElementById('btn-edu-mode-sync');
    if (btnEduSync && !btnEduSync.dataset.wired) {
        btnEduSync.dataset.wired = 'true';
        btnEduSync.addEventListener('click', () => setEduSourceMode('sync'));
    }
    const btnEduOvr = document.getElementById('btn-edu-mode-override');
    if (btnEduOvr && !btnEduOvr.dataset.wired) {
        btnEduOvr.dataset.wired = 'true';
        btnEduOvr.addEventListener('click', () => setEduSourceMode('override'));
    }
}

export function initEventWizardControls() {
    const btnAddEvent = document.getElementById('btn-add-catalog-event');
    const modalEvent = document.getElementById('modal-event');
    const btnCloseEvent = document.getElementById('btn-close-modal-event');
    const btnCancelEvent = document.getElementById('btn-cancel-modal-event');
    const formEvent = document.getElementById('form-event');
    const selectTemplate = document.getElementById('select-event-template');

    renderEventIconPickerGrid();
    setSelectedEventIcon(document.getElementById('input-event-icon')?.value || 'evt-capital-outflow', false, true);

    bindWizardIconAndSearchControls();
    bindWizardDropdownSyncers();

    if (btnAddEvent && modalEvent && !btnAddEvent.dataset.wired) {
        btnAddEvent.dataset.wired = 'true';
        btnAddEvent.addEventListener('click', () => {
            if (typeof window.openCreateEventModal === 'function') window.openCreateEventModal();
        });
    }

    const hideEventModal = () => {
        const m = document.getElementById('modal-event');
        if (m) m.style.display = 'none';
    };
    if (btnCloseEvent && !btnCloseEvent.dataset.wired) {
        btnCloseEvent.dataset.wired = 'true';
        btnCloseEvent.addEventListener('click', hideEventModal);
    }
    if (btnCancelEvent && !btnCancelEvent.dataset.wired) {
        btnCancelEvent.dataset.wired = 'true';
        btnCancelEvent.addEventListener('click', hideEventModal);
    }

    if (formEvent && !formEvent.dataset.wired) {
        formEvent.dataset.wired = 'true';
        formEvent.addEventListener('submit', async (e) => {
            e.preventDefault();
            const id = document.getElementById('input-event-id').value;
            const template = selectTemplate ? selectTemplate.value : 'lifestyle';
            const name = document.getElementById('input-event-name').value;
            const startYear = parseInt(document.getElementById('input-event-year').value) || 2027;
            const endYear = parseInt(document.getElementById('input-event-end-year').value) || startYear;
            const source = document.getElementById('select-event-source').value;
            const desc = document.getElementById('input-event-desc').value;
            const selectedIcon = document.getElementById('input-event-icon')?.value || TEMPLATE_DEFAULT_ICONS[template] || '';

            const eventPayload = buildEventPayload(template, id, name, startYear, endYear, source, desc, selectedIcon);
            await submitSaveEvent(eventPayload, id, hideEventModal);
        });
    }
}
