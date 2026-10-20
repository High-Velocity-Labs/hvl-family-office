// =========================================================
// COMPENSATION MODALS, FORMS & RECORD MUTATIONS
// =========================================================

function openCompForm(data = null) {
    const card = document.getElementById('comp-form-card');
    const title = document.getElementById('comp-form-title');
    const yrEl = document.getElementById('input-comp-year');
    const userEl = document.getElementById('input-comp-user-id');
    const compEl = document.getElementById('input-comp-company');
    const salEl = document.getElementById('input-comp-salary');
    const bonEl = document.getElementById('input-comp-bonus');
    const srcEl = document.getElementById('input-comp-source');
    const statusEl = document.getElementById('comp-form-status');

    if (!card) return;
    if (statusEl) statusEl.innerHTML = '';

    const activeTp = typeof window.getActiveCompTaxpayer === 'function' ? window.getActiveCompTaxpayer() : 'all';
    if (data) {
        if (title) title.textContent = `Edit ${data.year} Compensation Record`;
        if (yrEl) yrEl.value = data.year;
        if (userEl) userEl.value = String(data.user_id || (activeTp !== 'all' ? activeTp : 1));
        if (compEl) compEl.value = data.company || '';
        if (salEl) salEl.value = data.salary || 0;
        if (bonEl) bonEl.value = data.bonus || 0;
        if (srcEl) srcEl.value = data.source || '';
    } else {
        if (title) title.textContent = '+ Add New Compensation Record';
        if (yrEl) yrEl.value = new Date().getFullYear();
        if (userEl) userEl.value = activeTp !== 'all' ? String(activeTp) : '1';
        if (compEl) compEl.value = window.PRIMARY_COMPANY_NAME || 'Employer';
        if (salEl) salEl.value = '';
        if (bonEl) bonEl.value = '0';
        if (srcEl) srcEl.value = 'Form W-2 / Payroll';
    }
    card.style.display = 'block';
}

function closeCompForm() {
    const card = document.getElementById('comp-form-card');
    if (card) card.style.display = 'none';
}

function initCompensationModals() {
    if (!document.body || document.body.dataset.compModalsDelegated === 'true') return;
    document.body.dataset.compModalsDelegated = 'true';

    document.addEventListener('click', async (e) => {
        const toggleBtn = e.target.closest('#btn-toggle-comp-form');
        if (toggleBtn) {
            const card = document.getElementById('comp-form-card');
            if (card && card.style.display !== 'none') {
                closeCompForm();
            } else {
                openCompForm(null);
            }
            return;
        }

        const closeBtn = e.target.closest('#btn-close-comp-form, #btn-cancel-comp-form');
        if (closeBtn) {
            closeCompForm();
            return;
        }

        const editBtn = e.target.closest('.btn-edit-comp');
        if (editBtn) {
            openCompForm({
                year: editBtn.getAttribute('data-year'),
                user_id: editBtn.getAttribute('data-user-id'),
                company: editBtn.getAttribute('data-company'),
                salary: editBtn.getAttribute('data-salary'),
                bonus: editBtn.getAttribute('data-bonus'),
                source: editBtn.getAttribute('data-source'),
            });
            return;
        }

        const delBtn = e.target.closest('.btn-del-comp');
        if (delBtn) {
            const yr = delBtn.getAttribute('data-year');
            const comp = delBtn.getAttribute('data-company');
            const uid = delBtn.getAttribute('data-user-id') || '1';
            if (!(await window.showConfirmModal(`Remove ${yr} (${comp}) compensation record?`, { title: 'Delete Compensation Record', confirmText: 'Delete', danger: true }))) {
                return;
            }
            try {
                const res = await fetch('/api/compensation/delete', {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ year: Number(yr), company: comp, user_id: Number(uid) }),
                });
                const json = await res.json();
                if (!res.ok || !json.success) {
                    await window.showModalAlert(json.error || 'Failed to delete compensation record.', { title: 'Error', type: 'error' });
                } else if (!window.__DOMAIN_VERSIONS__) {
                    if (window.loadCompensationData) await window.loadCompensationData();
                    if (window.morphCompensationSection) await window.morphCompensationSection();
                }
            } catch (err) {
                console.error('Failed to delete compensation record:', err);
                await window.showModalAlert(err.message || 'Failed to delete compensation record.', { title: 'Error', type: 'error' });
            }
            return;
        }
    });

    document.addEventListener('submit', async (e) => {
        const form = e.target.closest('#form-compensation');
        if (!form) return;
        e.preventDefault();

        const yr = document.getElementById('input-comp-year')?.value;
        const userId = document.getElementById('input-comp-user-id')?.value || 1;
        const comp = document.getElementById('input-comp-company')?.value;
        const sal = document.getElementById('input-comp-salary')?.value;
        const bon = document.getElementById('input-comp-bonus')?.value || 0;
        const src = document.getElementById('input-comp-source')?.value || 'Form W-2 / Manual Entry';

        try {
            const res = await fetch('/api/compensation/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    year: Number(yr),
                    user_id: Number(userId),
                    company: comp,
                    salary: Number(sal),
                    bonus: Number(bon),
                    source: src,
                }),
            });
            const json = await res.json();
            if (!res.ok || !json.success) {
                await window.showModalAlert(json.error || 'Failed to save compensation record.', { title: 'Error', type: 'error' });
            } else {
                closeCompForm();
                if (!window.__DOMAIN_VERSIONS__) {
                    if (window.loadCompensationData) await window.loadCompensationData();
                    if (window.morphCompensationSection) await window.morphCompensationSection();
                }
            }
        } catch (err) {
            console.error('Error saving compensation record:', err);
            await window.showModalAlert(err.message || 'Failed to save compensation record.', { title: 'Error', type: 'error' });
        }
    });
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        openCompForm,
        closeCompForm,
        initCompensationModals,
    });
}
