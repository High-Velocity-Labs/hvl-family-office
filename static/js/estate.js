/**
 * Estate & Generational Wealth Module
 * Server-rendered via /fragments/estate and morphed via HTMX + Idiomorph.
 */

let currentEstateState = 'WA';
let applyTcjaSunset = false;
let currentCharitablePct = 0.05;
let charityDebounceTimer = null;

function syncEstateControlsFromDom() {
    const selectState = document.getElementById('select-estate-state');
    if (selectState && selectState.value) {
        currentEstateState = selectState.value;
    }
    const btnSunsetRevert = document.getElementById('btn-sunset-revert');
    if (btnSunsetRevert) {
        applyTcjaSunset = btnSunsetRevert.classList.contains('active');
    }
    const rangeCharity = document.getElementById('range-charity-legacy');
    if (rangeCharity && rangeCharity.value !== undefined) {
        currentCharitablePct = parseInt(rangeCharity.value, 10) / 100;
    }
}

async function morphEstateSection(overrides = {}) {
    syncEstateControlsFromDom();
    if (overrides.state !== undefined) currentEstateState = overrides.state;
    if (overrides.apply_tcja_sunset !== undefined) applyTcjaSunset = Boolean(overrides.apply_tcja_sunset);
    if (overrides.charitable_pct !== undefined) currentCharitablePct = Number(overrides.charitable_pct);

    const url = `/fragments/estate?state=${encodeURIComponent(currentEstateState)}&apply_tcja_sunset=${applyTcjaSunset ? 'true' : 'false'}&charitable_pct=${encodeURIComponent(currentCharitablePct)}`;
    const sec = document.getElementById('section-estate');
    if (!sec) return;

    await window.htmx.ajax('GET', url, { target: '#section-estate', swap: 'morph' });
}

async function loadEstateProfile(options = {}) {
    if (Object.keys(options).length > 0) {
        await morphEstateSection(options);
    } else {
        syncEstateControlsFromDom();
    }
}

function setupEstateEventListeners() {
    if (document.body && !document.body.dataset.estateDelegated) {
        document.body.dataset.estateDelegated = 'true';

        document.addEventListener('change', (e) => {
            const selectState = e.target.closest('#select-estate-state');
            if (selectState) {
                currentEstateState = selectState.value;
                morphEstateSection({ state: currentEstateState });
            }
        });

        document.addEventListener('input', (e) => {
            const rangeCharity = e.target.closest('#range-charity-legacy');
            if (rangeCharity) {
                const pct = parseInt(rangeCharity.value, 10) / 100;
                currentCharitablePct = pct;
                const valCharity = document.getElementById('val-charity-legacy');
                if (valCharity) valCharity.textContent = `${rangeCharity.value}%`;
                if (charityDebounceTimer) clearTimeout(charityDebounceTimer);
                charityDebounceTimer = setTimeout(() => {
                    morphEstateSection({ charitable_pct: currentCharitablePct });
                }, 120);
            }
        });

        document.addEventListener('click', async (e) => {
            const btnCurrent = e.target.closest('#btn-sunset-current');
            if (btnCurrent) {
                applyTcjaSunset = false;
                morphEstateSection({ apply_tcja_sunset: false });
                return;
            }

            const btnRevert = e.target.closest('#btn-sunset-revert');
            if (btnRevert) {
                applyTcjaSunset = true;
                morphEstateSection({ apply_tcja_sunset: true });
                return;
            }

            const btnAuditNav = e.target.closest('.btn-audit-nav');
            if (btnAuditNav) {
                const navTarget = (btnAuditNav.getAttribute('data-audit-nav') || '').trim();
                const accId = (btnAuditNav.getAttribute('data-audit-acc-id') || '').trim();
                if (navTarget.startsWith('settings:')) {
                    const tabName = navTarget.split(':')[1] || 'roles';
                    if (typeof window.openSettingsModal === 'function') {
                        await window.openSettingsModal();
                    }
                    if (typeof window.switchSettingsTab === 'function') {
                        window.switchSettingsTab(tabName);
                    }
                    if (accId) {
                        setTimeout(() => {
                            const row = document.querySelector(`#settings-roles-tbody tr[data-acc-id="${CSS.escape(accId)}"]`);
                            if (row) {
                                row.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                row.style.transition = 'background-color 0.4s ease';
                                row.style.backgroundColor = 'rgba(59, 130, 246, 0.16)';
                                setTimeout(() => { row.style.backgroundColor = ''; }, 2400);
                            }
                        }, 180);
                    }
                } else if (navTarget.startsWith('scroll:')) {
                    const sel = navTarget.slice('scroll:'.length);
                    const el = sel ? document.querySelector(sel) : null;
                    if (el) {
                        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    }
                } else if (navTarget.startsWith('section-')) {
                    const link = document.querySelector(`.nav-link[data-target="${navTarget}"]`);
                    if (link) {
                        link.click();
                    }
                }
                return;
            }

            const btnAuditVerify = e.target.closest('.btn-audit-verify');
            if (btnAuditVerify) {
                const findingId = (btnAuditVerify.getAttribute('data-finding-id') || '').trim();
                const isVerified = btnAuditVerify.getAttribute('data-verified') === 'true';
                if (!findingId) return;
                try {
                    btnAuditVerify.disabled = true;
                    const resp = await fetch('/api/estate/audit_verify', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            finding_id: findingId,
                            verified: !isVerified,
                        }),
                    });
                    const res = await resp.json();
                    if (res && res.success) {
                        await morphEstateSection();
                    } else {
                        btnAuditVerify.disabled = false;
                    }
                } catch (err) {
                    console.error('Error toggling audit verification:', err);
                    btnAuditVerify.disabled = false;
                }
                return;
            }

            const btnSave = e.target.closest('#btn-save-estate-settings');
            if (btnSave) {
                syncEstateControlsFromDom();
                try {
                    btnSave.disabled = true;
                    btnSave.innerHTML = `<span>Saving...</span>`;
                    const resp = await fetch('/api/estate/settings', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            apply_tcja_sunset: applyTcjaSunset,
                            charitable_pct: currentCharitablePct,
                        })
                    });
                    const res = await resp.json();
                    if (res.success) {
                        btnSave.innerHTML = `<span>Saved</span>`;
                        setTimeout(() => {
                            btnSave.disabled = false;
                            btnSave.innerHTML = `<span>Save Assumptions</span>`;
                        }, 1500);
                    } else {
                        alert(res.error || 'Failed to save estate preferences.');
                        btnSave.disabled = false;
                        btnSave.innerHTML = `<span>Save Assumptions</span>`;
                    }
                } catch (err) {
                    console.error('Error saving estate settings:', err);
                    btnSave.disabled = false;
                    btnSave.innerHTML = `<span>Save Assumptions</span>`;
                }
            }
        });
    }
}

document.addEventListener('DOMContentLoaded', () => {
    setupEstateEventListeners();
    syncEstateControlsFromDom();
});

window.loadEstateProfile = loadEstateProfile;
window.morphEstateSection = morphEstateSection;
if (typeof window !== 'undefined' && typeof window.registerSectionHydrator === 'function') {
    window.registerSectionHydrator('section-estate', loadEstateProfile, {
        morphFn: () => morphEstateSection()
    });
}

