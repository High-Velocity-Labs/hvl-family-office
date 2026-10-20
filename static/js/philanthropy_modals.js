/**
 * Philanthropy Modals & Forms (Grants & Budget CRUD)
 * Extracted from static/js/philanthropy.js for modular separation.
 */

function initPhilanthropyModals() {
    if (!document.body || document.body.dataset.philanthropyModalsDelegated === 'true') return;
    document.body.dataset.philanthropyModalsDelegated = 'true';

    document.addEventListener('click', async (e) => {
        const getState = () => (typeof window.getPhilanthropyState === 'function' ? window.getPhilanthropyState() : { year: '2026', budgetRaw: 150000 });

        const showAddGrantBtn = e.target.closest('#btn-show-add-grant');
        if (showAddGrantBtn) {
            const cardAdd = document.getElementById('card-add-grant-form');
            const cardBudget = document.getElementById('card-edit-daf-budget-form');
            const cardEdit = document.getElementById('card-edit-grant-form');
            if (cardBudget) cardBudget.style.display = 'none';
            if (cardEdit) cardEdit.style.display = 'none';
            if (cardAdd) {
                const isHidden = cardAdd.style.display === 'none' || !cardAdd.style.display;
                cardAdd.style.display = isHidden ? 'block' : 'none';
                const yrInput = document.getElementById('input-grant-year');
                if (yrInput) yrInput.value = getState().year;
            }
            return;
        }

        const cancelAddGrantBtn = e.target.closest('#btn-cancel-add-grant');
        if (cancelAddGrantBtn) {
            const cardAdd = document.getElementById('card-add-grant-form');
            if (cardAdd) cardAdd.style.display = 'none';
            return;
        }

        const showEditBudgetBtn = e.target.closest('#btn-show-edit-daf-budget');
        if (showEditBudgetBtn) {
            const cardBudget = document.getElementById('card-edit-daf-budget-form');
            const cardAdd = document.getElementById('card-add-grant-form');
            const cardEdit = document.getElementById('card-edit-grant-form');
            if (cardAdd) cardAdd.style.display = 'none';
            if (cardEdit) cardEdit.style.display = 'none';
            if (cardBudget) {
                const isHidden = cardBudget.style.display === 'none' || !cardBudget.style.display;
                cardBudget.style.display = isHidden ? 'block' : 'none';
                const state = getState();
                const yrInput = document.getElementById('input-daf-budget-year');
                const amtInput = document.getElementById('input-daf-budget-amount');
                if (yrInput) yrInput.value = state.year;
                if (amtInput) amtInput.value = state.budgetRaw;
            }
            return;
        }

        const cancelEditBudgetBtn = e.target.closest('#btn-cancel-edit-daf-budget');
        if (cancelEditBudgetBtn) {
            const cardBudget = document.getElementById('card-edit-daf-budget-form');
            if (cardBudget) cardBudget.style.display = 'none';
            return;
        }

        const editGrantBtn = e.target.closest('.btn-edit-grant');
        if (editGrantBtn) {
            const cardEdit = document.getElementById('card-edit-grant-form');
            const cardAdd = document.getElementById('card-add-grant-form');
            const cardBudget = document.getElementById('card-edit-daf-budget-form');
            if (cardAdd) cardAdd.style.display = 'none';
            if (cardBudget) cardBudget.style.display = 'none';
            if (cardEdit) {
                cardEdit.style.display = 'block';
                const idxInput = document.getElementById('edit-grant-index');
                const yrInput = document.getElementById('edit-grant-year');
                const orgInput = document.getElementById('edit-grant-org');
                const amtInput = document.getElementById('edit-grant-amount');
                const dateInput = document.getElementById('edit-grant-date');
                const descInput = document.getElementById('edit-grant-desc');
                if (idxInput) idxInput.value = editGrantBtn.getAttribute('data-index') || '0';
                if (yrInput) yrInput.value = editGrantBtn.getAttribute('data-year') || getState().year;
                if (orgInput) orgInput.value = editGrantBtn.getAttribute('data-org') || '';
                if (amtInput) amtInput.value = editGrantBtn.getAttribute('data-amount') || '';
                if (dateInput) dateInput.value = editGrantBtn.getAttribute('data-date') || '';
                if (descInput) descInput.value = editGrantBtn.getAttribute('data-desc') || '';
                if (amtInput) amtInput.focus();
            }
            return;
        }

        const cancelEditGrantBtn = e.target.closest('#btn-cancel-edit-grant');
        if (cancelEditGrantBtn) {
            const cardEdit = document.getElementById('card-edit-grant-form');
            if (cardEdit) cardEdit.style.display = 'none';
            return;
        }

        const delGrantBtn = e.target.closest('.btn-delete-grant');
        if (delGrantBtn) {
            const yr = delGrantBtn.getAttribute('data-year') || getState().year;
            const idx = parseInt(delGrantBtn.getAttribute('data-index') || '0', 10);
            if (!(await window.showConfirmModal(`Remove this charitable grant from ${yr}?`, { title: 'Remove Charitable Grant', confirmText: 'Remove Grant', danger: true }))) {
                return;
            }
            try {
                const sec = document.getElementById('section-philanthropy');
                if (sec && yr) sec.dataset.activeYear = String(yr);
                const res = await fetch('/api/philanthropy/grant', {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ year: yr, index: idx }),
                });
                const json = await res.json();
                if (!res.ok || !json.success) {
                    await window.showModalAlert(json.error || 'Failed to delete charitable grant.', { title: 'Error', type: 'error' });
                } else if (!window.__DOMAIN_VERSIONS__) {
                    if (window.loadPhilanthropyData) await window.loadPhilanthropyData();
                    if (window.morphPhilanthropySection) await window.morphPhilanthropySection({ year: yr });
                }
            } catch (err) {
                console.error('Error deleting grant:', err);
                await window.showModalAlert(err.message || 'Failed to delete charitable grant.', { title: 'Error', type: 'error' });
            }
        }
    });

    document.addEventListener('submit', async (e) => {
        const getState = () => (typeof window.getPhilanthropyState === 'function' ? window.getPhilanthropyState() : { year: '2026', budgetRaw: 150000 });

        const addForm = e.target.closest('#form-add-grant');
        if (addForm) {
            e.preventDefault();
            const year = (document.getElementById('input-grant-year')?.value || getState().year).trim();
            const organization = (document.getElementById('input-grant-org')?.value || '').trim();
            const amount = parseFloat(document.getElementById('input-grant-amount')?.value || '0') || 0;
            const date = (document.getElementById('input-grant-date')?.value || '').trim();
            const description = (document.getElementById('input-grant-desc')?.value || '').trim();

            try {
                const sec = document.getElementById('section-philanthropy');
                if (sec && year) sec.dataset.activeYear = String(year);
                const res = await fetch('/api/philanthropy/grant', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ year, organization, amount, date, description }),
                });
                const json = await res.json();
                if (!res.ok || !json.success) {
                    await window.showModalAlert(json.error || 'Failed to add charitable grant.', { title: 'Error', type: 'error' });
                } else {
                    addForm.reset();
                    const cardAdd = document.getElementById('card-add-grant-form');
                    if (cardAdd) cardAdd.style.display = 'none';
                    if (!window.__DOMAIN_VERSIONS__) {
                        if (window.loadPhilanthropyData) await window.loadPhilanthropyData();
                        if (window.morphPhilanthropySection) await window.morphPhilanthropySection({ year });
                    }
                }
            } catch (err) {
                console.error('Error saving grant:', err);
                await window.showModalAlert(err.message || 'Failed to add charitable grant.', { title: 'Error', type: 'error' });
            }
            return;
        }

        const editForm = e.target.closest('#form-edit-grant');
        if (editForm) {
            e.preventDefault();
            const index = parseInt(document.getElementById('edit-grant-index')?.value || '0', 10);
            const year = (document.getElementById('edit-grant-year')?.value || getState().year).trim();
            const organization = (document.getElementById('edit-grant-org')?.value || '').trim();
            const amount = parseFloat(document.getElementById('edit-grant-amount')?.value || '0') || 0;
            const date = (document.getElementById('edit-grant-date')?.value || '').trim();
            const description = (document.getElementById('edit-grant-desc')?.value || '').trim();

            try {
                const sec = document.getElementById('section-philanthropy');
                if (sec && year) sec.dataset.activeYear = String(year);
                const res = await fetch('/api/philanthropy/grant', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ year, index, organization, amount, date, description }),
                });
                const json = await res.json();
                if (!res.ok || !json.success) {
                    await window.showModalAlert(json.error || 'Failed to update charitable grant.', { title: 'Error', type: 'error' });
                } else {
                    const cardEdit = document.getElementById('card-edit-grant-form');
                    if (cardEdit) cardEdit.style.display = 'none';
                    if (!window.__DOMAIN_VERSIONS__) {
                        if (window.loadPhilanthropyData) await window.loadPhilanthropyData();
                        if (window.morphPhilanthropySection) await window.morphPhilanthropySection({ year });
                    }
                }
            } catch (err) {
                console.error('Error updating grant:', err);
                await window.showModalAlert(err.message || 'Failed to update charitable grant.', { title: 'Error', type: 'error' });
            }
            return;
        }

        const budgetForm = e.target.closest('#form-edit-daf-budget');
        if (budgetForm) {
            e.preventDefault();
            const year = (document.getElementById('input-daf-budget-year')?.value || getState().year).trim();
            const budget = parseFloat(document.getElementById('input-daf-budget-amount')?.value || '0') || 0;

            try {
                const sec = document.getElementById('section-philanthropy');
                if (sec && year) sec.dataset.activeYear = String(year);
                const res = await fetch('/api/philanthropy/budget', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ year, budget }),
                });
                const json = await res.json();
                if (!res.ok || !json.success) {
                    await window.showModalAlert(json.error || 'Failed to save philanthropy budget.', { title: 'Error', type: 'error' });
                } else {
                    const cardBudget = document.getElementById('card-edit-daf-budget-form');
                    if (cardBudget) cardBudget.style.display = 'none';
                    if (!window.__DOMAIN_VERSIONS__) {
                        if (window.loadPhilanthropyData) await window.loadPhilanthropyData();
                        if (window.morphPhilanthropySection) await window.morphPhilanthropySection({ year });
                    }
                }
            } catch (err) {
                console.error('Error saving philanthropy budget:', err);
                await window.showModalAlert(err.message || 'Failed to save philanthropy budget.', { title: 'Error', type: 'error' });
            }
        }
    });
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        initPhilanthropyModals,
    });
}
