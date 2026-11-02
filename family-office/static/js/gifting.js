// =========================================================
// FAMILY GIFTING (ANNUAL EXCLUSION TRACKER — SSR + HTMX MORPHING)
// =========================================================

function getActiveGiftYear() {
    const sec = document.getElementById('section-gifting');
    return sec ? sec.dataset.activeYear : undefined;
}

function scrollActiveGiftYearIntoView() {
    const container = document.getElementById('gifting-year-pills');
    if (!container) return;
    const activeBtn = container.querySelector('.pill-btn.active');
    if (activeBtn && container.clientWidth > 0) {
        container.scrollLeft = Math.max(0, activeBtn.offsetLeft - container.clientWidth / 2 + activeBtn.offsetWidth / 2);
    }
}

async function morphGiftingSection(year, editRecipient) {
    const targetYear = String(year || getActiveGiftYear());
    let url = `/fragments/gifting?year=${encodeURIComponent(targetYear)}`;
    if (editRecipient) url += `&edit=${encodeURIComponent(editRecipient)}`;
    await window.htmx.ajax('GET', url, { target: '#section-gifting', swap: 'morph' });
    scrollActiveGiftYearIntoView();
}

async function loadGiftingData(yearOverride) {
    initGiftingControls();
    if (yearOverride) {
        await morphGiftingSection(yearOverride);
    } else {
        scrollActiveGiftYearIntoView();
    }
}

function initGiftingControls() {
    if (!document.body || document.body.dataset.giftingDelegated === 'true') return;
    document.body.dataset.giftingDelegated = 'true';

    document.addEventListener('click', async (e) => {
        const yearPill = e.target.closest('#gifting-year-pills .pill-btn[data-year]');
        if (yearPill) {
            const yr = yearPill.getAttribute('data-year');
            if (yr) await morphGiftingSection(yr);
            return;
        }

        const prevBtn = e.target.closest('#btn-gift-prev-yr');
        if (prevBtn) {
            const prevYr = String(parseInt(getActiveGiftYear(), 10) - 1);
            await morphGiftingSection(prevYr);
            return;
        }

        const nextBtn = e.target.closest('#btn-gift-next-yr');
        if (nextBtn) {
            const nextYr = String(parseInt(getActiveGiftYear(), 10) + 1);
            await morphGiftingSection(nextYr);
            return;
        }

        const showAddBtn = e.target.closest('#btn-show-add-recipient');
        if (showAddBtn) {
            const formCard = document.getElementById('card-add-recipient-form');
            const yrLabel = document.getElementById('label-add-recipient-year');
            if (yrLabel) yrLabel.textContent = getActiveGiftYear();
            if (formCard) {
                const isHidden = formCard.hidden;
                formCard.hidden = !isHidden;
                if (isHidden) {
                    const nameInput = document.getElementById('input-new-recipient-name');
                    if (nameInput) nameInput.focus();
                }
            }
            return;
        }

        const cancelAddBtn = e.target.closest('#btn-cancel-add-recipient');
        if (cancelAddBtn) {
            const formCard = document.getElementById('card-add-recipient-form');
            if (formCard) formCard.hidden = true;
            return;
        }

        const copyBtn = e.target.closest('#btn-copy-prior-gift-budget');
        if (copyBtn) {
            const activeYr = getActiveGiftYear();
            const prevYr = String(parseInt(activeYr, 10) - 1);
            if (!(await window.showConfirmModal(`Copy all recipient gift amounts from ${prevYr} into ${activeYr}?`, { title: 'Copy Previous Year Budget', confirmText: 'Copy Budget' }))) {
                return;
            }
            copyBtn.disabled = true;
            try {
                const res = await fetch('/api/gifting/copy_previous_year', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ to_year: activeYr, from_year: prevYr }),
                });
                const json = await res.json();
                if (!res.ok || !json.success) {
                    await window.showModalAlert(json.error || 'Failed to copy previous year budget.', { title: 'Error', type: 'error' });
                } else if (!window.__DOMAIN_VERSIONS__) {
                    await morphGiftingSection(activeYr);
                }
            } catch (err) {
                console.error('Error copying previous year gifts:', err);
                await window.showModalAlert(err.message || 'Failed to copy previous year budget.', { title: 'Error', type: 'error' });
            } finally {
                copyBtn.disabled = false;
            }
            return;
        }

        const deleteBtn = e.target.closest('#section-gifting .btn-delete-row');
        if (deleteBtn) {
            const tr = deleteBtn.closest('tr');
            const name = tr ? tr.getAttribute('data-recipient') : '';
            const activeYr = getActiveGiftYear();
            if (!name) return;
            const confirmFn = window.showModalConfirm || window.showConfirmModal;
            if (!(await confirmFn(`Remove ${name} from ${activeYr} gifting budget?`, { title: 'Delete Recipient', confirmText: 'Delete', confirmVariant: 'danger', danger: true }))) {
                return;
            }
            deleteBtn.disabled = true;
            try {
                const res = await fetch('/api/gifting/recipient', {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ recipient: name, year: activeYr }),
                });
                const json = await res.json();
                if (!res.ok || !json.success) {
                    await window.showModalAlert(json.error || 'Failed to delete recipient.', { title: 'Error', type: 'error' });
                } else if (!window.__DOMAIN_VERSIONS__) {
                    await morphGiftingSection(activeYr);
                }
            } catch (err) {
                console.error('Failed to delete recipient:', err);
                await window.showModalAlert(err.message || 'Failed to delete recipient.', { title: 'Error', type: 'error' });
            } finally {
                deleteBtn.disabled = false;
            }
            return;
        }

        const editBtn = e.target.closest('#section-gifting .btn-edit-row');
        if (editBtn) {
            const tr = editBtn.closest('tr');
            if (!tr || tr.dataset.editing === 'true') return;
            await morphGiftingSection(getActiveGiftYear(), tr.getAttribute('data-recipient'));
            return;
        }

        const cancelInlineBtn = e.target.closest('#section-gifting .btn-cancel-inline-gift');
        if (cancelInlineBtn) {
            const yr = cancelInlineBtn.getAttribute('data-year') || getActiveGiftYear();
            await morphGiftingSection(yr);
            return;
        }

        const saveInlineBtn = e.target.closest('#section-gifting .btn-save-inline-gift');
        if (saveInlineBtn) {
            const tr = saveInlineBtn.closest('tr');
            if (!tr) return;
            const origName = saveInlineBtn.getAttribute('data-orig-name') || '';
            const yr = saveInlineBtn.getAttribute('data-year') || getActiveGiftYear();
            const newName = (tr.querySelector('.edit-rec-name')?.value || '').trim() || origName;
            const newCount = Math.max(1, parseInt(tr.querySelector('.edit-rec-count')?.value || '1', 10) || 1);
            const newAmt = parseFloat(tr.querySelector('.edit-rec-amount')?.value || '0') || 0;

            saveInlineBtn.disabled = true;
            try {
                const sec = document.getElementById('section-gifting');
                if (sec && yr) sec.dataset.activeYear = String(yr);
                const res = await fetch('/api/gifting/budget', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        year: yr,
                        recipient: newName,
                        old_recipient: origName !== newName ? origName : '',
                        beneficiary_count: newCount,
                        amount: newAmt,
                    }),
                });
                const json = await res.json();
                if (!res.ok || !json.success) {
                    await window.showModalAlert(json.error || 'Failed to save gift budget.', { title: 'Error', type: 'error' });
                } else if (!window.__DOMAIN_VERSIONS__) {
                    await morphGiftingSection(yr);
                }
            } catch (err) {
                console.error('Failed to save gift edit:', err);
                await window.showModalAlert(err.message || 'Failed to save gift budget.', { title: 'Error', type: 'error' });
            } finally {
                saveInlineBtn.disabled = false;
            }
        }
    });

    document.addEventListener('submit', async (e) => {
        const form = e.target.closest('#form-add-recipient');
        if (!form) return;
        e.preventDefault();

        const nameInput = document.getElementById('input-new-recipient-name');
        const countInput = document.getElementById('input-new-recipient-count');
        const relInput = document.getElementById('input-new-recipient-relationship');
        const amtInput = document.getElementById('input-new-recipient-amount');
        const saveBtn = document.getElementById('btn-save-new-recipient');
        const activeYr = getActiveGiftYear();

        const recipientName = nameInput ? nameInput.value.trim() : '';
        const memberCount = countInput ? parseInt(countInput.value, 10) || 1 : 1;
        const relationship = relInput ? relInput.value.trim() : '';
        const initialAmt = amtInput && amtInput.value !== '' ? parseFloat(amtInput.value) || 0 : 0;

        if (!recipientName) return;
        if (saveBtn) saveBtn.disabled = true;

        try {
            const res = await fetch('/api/gifting/recipient', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    recipient: recipientName,
                    num_people: memberCount,
                    relationship,
                    amount: initialAmt,
                    year: activeYr,
                }),
            });
            const json = await res.json();
            if (!res.ok || !json.success) {
                await window.showModalAlert(json.error || 'Failed to add recipient.', { title: 'Error', type: 'error' });
            } else {
                form.reset();
                const formCard = document.getElementById('card-add-recipient-form');
                if (formCard) formCard.hidden = true;
                if (!window.__DOMAIN_VERSIONS__) {
                    await morphGiftingSection(activeYr);
                }
            }
        } catch (err) {
            console.error('Error adding recipient:', err);
            await window.showModalAlert(err.message || 'Failed to add recipient.', { title: 'Error', type: 'error' });
        } finally {
            if (saveBtn) saveBtn.disabled = false;
        }
    });
}

Object.assign(window, {
    loadGiftingData,
    fetchGiftingData: loadGiftingData,
    morphGiftingSection,
    initGiftingControls,
});
if (typeof window !== 'undefined' && typeof window.registerSectionHydrator === 'function') {
    window.registerSectionHydrator('section-gifting', loadGiftingData, {
        morphFn: () => morphGiftingSection()
    });
}
