// =========================================================
// EDUCATION, 529 & TUITION PLANNING (SSR + HTMX MORPHING)
// =========================================================

function getCollegeState() {
    const sec = document.getElementById('section-college');
    const toggle = document.getElementById('toggle-529-k12');
    return {
        horizon: (sec && sec.dataset.horizon) || 'current',
        enable_529_k12: toggle ? toggle.checked : (!sec || sec.dataset.enable529K12 !== 'false'),
    };
}

async function morphCollegeSection(overrides = {}) {
    const cur = getCollegeState();
    const horizon = overrides.horizon !== undefined ? overrides.horizon : cur.horizon;
    const enable_529_k12 = overrides.enable_529_k12 !== undefined ? overrides.enable_529_k12 : cur.enable_529_k12;

    const params = new URLSearchParams({
        horizon: String(horizon || 'current'),
        enable_529_k12: enable_529_k12 ? 'true' : 'false',
    });
    const url = `/fragments/college?${params.toString()}`;
    await window.htmx.ajax('GET', url, { target: '#section-college', swap: 'morph' });
}

async function loadCollegeData() {
    initCollegeControls();
}

function openTuitionForm(data = null) {
    const card = document.getElementById('tuition-form-card');
    const title = document.getElementById('tuition-form-title');
    const yrEl = document.getElementById('input-tuition-year');
    const notesEl = document.getElementById('input-tuition-notes');
    const statusEl = document.getElementById('tuition-form-status');

    if (!card) return;
    if (statusEl) statusEl.innerHTML = '';

    const amtInputs = Array.from(document.querySelectorAll('.input-tuition-child-amt'));
    const gradeInputs = Array.from(document.querySelectorAll('.input-tuition-child-grade'));

    if (data) {
        if (title) title.textContent = `Edit ${data.school_year} Academic Expenses`;
        if (yrEl) yrEl.value = data.school_year || '';
        if (amtInputs[0]) amtInputs[0].value = data.c1_amt || 0;
        if (gradeInputs[0]) gradeInputs[0].value = data.c1_grade || '';
        if (amtInputs[1]) amtInputs[1].value = data.c2_amt || 0;
        if (gradeInputs[1]) gradeInputs[1].value = data.c2_grade || '';
        if (notesEl) notesEl.value = data.notes || '';
    } else {
        if (title) title.textContent = '+ Add Academic Year Expenses';
        if (yrEl) yrEl.value = '';
        amtInputs.forEach(inp => { inp.value = ''; });
        gradeInputs.forEach(inp => { inp.value = ''; });
        if (notesEl) notesEl.value = '';
    }
    card.style.display = 'block';
}

function closeTuitionForm() {
    const card = document.getElementById('tuition-form-card');
    if (card) card.style.display = 'none';
}

function initCollegeControls() {
    if (!document.body || document.body.dataset.collegeDelegated === 'true') return;
    document.body.dataset.collegeDelegated = 'true';

    document.addEventListener('click', async (e) => {
        const horizonBtn = e.target.closest('#college-horizon-tabs .pill-btn[data-horizon]');
        if (horizonBtn) {
            const h = horizonBtn.getAttribute('data-horizon');
            if (h) await morphCollegeSection({ horizon: h });
            return;
        }

        const toggleBtn = e.target.closest('#btn-toggle-tuition-form');
        if (toggleBtn) {
            const card = document.getElementById('tuition-form-card');
            if (card && card.style.display !== 'none') {
                closeTuitionForm();
            } else {
                openTuitionForm(null);
            }
            return;
        }

        const closeBtn = e.target.closest('#btn-close-tuition-form, #btn-cancel-tuition-form');
        if (closeBtn) {
            closeTuitionForm();
            return;
        }

        const editBtn = e.target.closest('.btn-edit-tuition');
        if (editBtn) {
            openTuitionForm({
                school_year: editBtn.getAttribute('data-year'),
                c1_amt: editBtn.getAttribute('data-c1-amt'),
                c1_grade: editBtn.getAttribute('data-c1-grade'),
                c2_amt: editBtn.getAttribute('data-c2-amt'),
                c2_grade: editBtn.getAttribute('data-c2-grade'),
                notes: editBtn.getAttribute('data-notes'),
            });
            return;
        }

        const delBtn = e.target.closest('.btn-del-tuition');
        if (delBtn) {
            const yr = delBtn.getAttribute('data-year');
            if (!yr) return;
            if (!(await window.showConfirmModal(`Remove ${yr} education expense record?`, { title: 'Delete Tuition Record', confirmText: 'Delete', danger: true }))) {
                return;
            }
            try {
                const res = await fetch('/api/education/tuition/delete', {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ school_year: yr }),
                });
                const json = await res.json();
                if (!res.ok || !json.success) {
                    await window.showModalAlert(json.error || 'Failed to delete tuition record.', { title: 'Error', type: 'error' });
                } else if (!window.__DOMAIN_VERSIONS__) {
                    await morphCollegeSection();
                }
            } catch (err) {
                console.error('Failed to delete tuition record:', err);
                await window.showModalAlert(err.message || 'Failed to delete tuition record.', { title: 'Error', type: 'error' });
            }
        }
    });

    document.addEventListener('change', async (e) => {
        const k12Toggle = e.target.closest('#toggle-529-k12');
        if (k12Toggle) {
            await morphCollegeSection({ enable_529_k12: k12Toggle.checked });
        }
    });

    document.addEventListener('submit', async (e) => {
        const form = e.target.closest('#form-tuition');
        if (!form) return;
        e.preventDefault();

        const yr = (document.getElementById('input-tuition-year')?.value || '').trim();
        const notes = (document.getElementById('input-tuition-notes')?.value || '').trim();
        if (!yr) return;

        const payload = {
            school_year: yr,
            notes,
        };

        document.querySelectorAll('.input-tuition-child-amt').forEach(inp => {
            const key = inp.getAttribute('data-child-key');
            if (key) payload[key] = Number(inp.value || 0);
        });
        document.querySelectorAll('.input-tuition-child-grade').forEach(inp => {
            const key = inp.getAttribute('data-child-key');
            if (key) payload[`${key}_grade`] = (inp.value || '').trim();
        });

        try {
            const res = await fetch('/api/education/tuition/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const json = await res.json();
            if (!res.ok || !json.success) {
                await window.showModalAlert(json.error || 'Failed to save tuition record.', { title: 'Error', type: 'error' });
            } else {
                closeTuitionForm();
                if (!window.__DOMAIN_VERSIONS__) {
                    await morphCollegeSection();
                }
            }
        } catch (err) {
            console.error('Error saving tuition record:', err);
            await window.showModalAlert(err.message || 'Failed to save tuition record.', { title: 'Error', type: 'error' });
        }
    });
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        loadCollegeData,
        fetchCollegeData: loadCollegeData,
        morphCollegeSection,
        openTuitionForm,
        closeTuitionForm,
        initCollegeControls,
    });
    if (typeof window.registerSectionHydrator === 'function') {
        window.registerSectionHydrator('section-college', loadCollegeData, {
            morphFn: () => morphCollegeSection()
        });
    }
}
