/**
 * static/js/scenarios/event_modals_render.js
 * Edit event form pre-fill and dynamic dropdown population.
 */

import { state } from './state.js';
import {
    filterWizardTemplateOptions,
    renderEventIconPickerGrid,
    setSelectedEventIcon,
    TEMPLATE_DEFAULT_ICONS
} from './event_modals_presets.js';
import { getWizardPanels } from './event_modals_fields.js';
import { cloneEvent } from './event_modals_catalog.js';
import { prefillCategoryFields } from './event_modals_prefill.js';

let cachedFamilyMembers = [];
let cachedGrants = [];

export async function populateWizardDynamicDropdowns() {
    try {
        if (!cachedGrants || !cachedGrants.length) {
            const resp = await fetch('/api/equity/grants');
            const data = await resp.json();
            if (data.success && data.grants) cachedGrants = data.grants;
        }

        const selGrant = document.getElementById('select-equity-grant');
        if (selGrant && cachedGrants) {
            selGrant.innerHTML = '<option value="ALL">All Available Vested Grants</option>';
            cachedGrants.forEach(g => {
                const label = `${g.grant_label || g.nickname} (Vested: ${(g.unexercised_vested || 0).toLocaleString()} @ $${g.strike_price})`;
                const opt = document.createElement('option');
                opt.value = g.grant_id || g.grant_label;
                opt.textContent = label;
                selGrant.appendChild(opt);
            });
        }

        if (!cachedFamilyMembers || !cachedFamilyMembers.length) {
            const resp = await fetch('/api/family');
            const data = await resp.json();
            if (data.success && data.members) cachedFamilyMembers = data.members;
        }

        const selChild = document.getElementById('select-edu-child');
        const selGradChild = document.getElementById('select-grad-child');
        const selSuperfundChild = document.getElementById('select-superfund-child');
        if ((selChild || selGradChild || selSuperfundChild) && cachedFamilyMembers) {
            const children = cachedFamilyMembers.filter(m => m.relationship === 'child');
            [selChild, selGradChild, selSuperfundChild].forEach(sel => {
                if (!sel) return;
                sel.innerHTML = '';
                if (children.length) {
                    children.forEach(c => {
                        const opt = document.createElement('option');
                        opt.value = c.id || c.name;
                        opt.textContent = `${c.name} (Born ${c.birthdate || 'N/A'})`;
                        sel.appendChild(opt);
                    });
                } else {
                    sel.innerHTML = '<option value="child_1">Child Beneficiary</option>';
                }
            });
        }

        const selParent = document.getElementById('select-eldercare-parent');
        if (selParent && cachedFamilyMembers) {
            selParent.innerHTML = '';
            const parents = cachedFamilyMembers.filter(m => ['parent', 'dependent', 'relative'].includes(m.relationship));
            if (parents.length) {
                parents.forEach(p => {
                    const opt = document.createElement('option');
                    opt.value = p.id || p.name;
                    opt.textContent = `${p.name} (${p.relationship})`;
                    selParent.appendChild(opt);
                });
            } else {
                selParent.innerHTML = '<option value="parent_1">Parent / Dependent</option>';
            }
        }

        const selCollegeChild = document.getElementById('select-college-child');
        if (selCollegeChild) {
            try {
                const resp = await fetch('/api/college');
                const colData = await resp.json();
                if (colData && colData.children && colData.children.length) {
                    selCollegeChild.innerHTML = '';
                    colData.children.forEach(c => {
                        const opt = document.createElement('option');
                        opt.value = c.user_id;
                        opt.dataset.matr = c.college_matriculation_year || (c.birthdate ? (parseInt(c.birthdate.split('-')[0]) + 18) : 2029);
                        opt.dataset.bal = c.current_529_balance || 0;
                        opt.textContent = `${c.name} (College: ${opt.dataset.matr}, 529: $${Math.round((c.current_529_balance || 0) / 1000)}k)`;
                        selCollegeChild.appendChild(opt);
                    });
                    const firstOpt = selCollegeChild.options[0];
                    const b529 = document.getElementById('badge-college-529-balance');
                    if (b529 && firstOpt && firstOpt.dataset.bal) {
                        b529.textContent = `529 Reserve: $${Math.round(parseFloat(firstOpt.dataset.bal)).toLocaleString()}`;
                    }
                }
            } catch (e) {
                console.warn('Could not load college children data:', e);
            }
        }
    } catch (e) {
        console.warn('Could not populate dynamic wizard selectors:', e);
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
        document.getElementById('input-event-year').value = ev.year || 2027;
        document.getElementById('input-event-end-year').value = ev.end_year || ev.year || 2027;
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
