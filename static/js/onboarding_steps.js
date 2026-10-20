/**
 * Onboarding Steps Controller & Account Mutations
 * Extracted from static/js/onboarding.js for modular separation.
 */

function goToOnboardingStep(step) {
    if (typeof window.updateOnboardingStepUI === 'function') {
        window.updateOnboardingStepUI(step);
    }
}

function prevOnboardingStep() {
    const curr = window.currentOnboardingStep || 1;
    if (curr > 1) {
        if (typeof window.updateOnboardingStepUI === 'function') {
            window.updateOnboardingStepUI(curr - 1);
        }
    }
}

async function onboardingAddQuickAccount() {
    const nameEl = document.getElementById('ob-manual-acc-name');
    const roleEl = document.getElementById('ob-manual-acc-role');
    const balEl = document.getElementById('ob-manual-acc-balance');
    const listEl = document.getElementById('ob-added-accounts-list');
    const msgEl = document.getElementById('onboarding-status-msg');

    const name = (nameEl ? nameEl.value : '').trim();
    const role = roleEl ? roleEl.value : 'public_brokerage';
    const balance = parseFloat(balEl && balEl.value ? balEl.value : '0');

    if (!name) {
        if (msgEl) {
            msgEl.style.color = 'var(--status-red)';
            msgEl.textContent = 'Enter an account name to add.';
        }
        return;
    }

    try {
        const resp = await fetch('/api/accounts/manual', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                role: role,
                balance: isNaN(balance) ? 0 : balance,
                institution: 'Manual Entry',
            }),
        });
        const res = await resp.json();
        if (resp.ok && res.success) {
            if (window.SandboxManager && typeof window.SandboxManager.markHasData === 'function') {
                window.SandboxManager.markHasData();
            }
            if (nameEl) nameEl.value = '';
            if (balEl) balEl.value = '';
            if (listEl) {
                const pill = document.createElement('div');
                pill.style.marginTop = '4px';
                pill.style.color = 'var(--status-green, #10B981)';
                pill.textContent = `✓ Added ${name}`;
                listEl.appendChild(pill);
            }
            if (msgEl) msgEl.textContent = '';
            return true;
        } else {
            const errMsg = res.error || 'Could not add manual account.';
            if (msgEl) {
                msgEl.style.color = 'var(--status-red)';
                msgEl.textContent = errMsg;
            }
            if (typeof window.showModalAlert === 'function') {
                await window.showModalAlert(errMsg, { title: 'Unable to Add Account', type: 'error' });
            } else {
                (window.showToast ? window.showToast(errMsg, 'error') : window.showModalAlert && window.showModalAlert('Notice', errMsg));
            }
            return false;
        }
    } catch (err) {
        const errMsg = 'Could not add manual account: ' + err.message;
        if (msgEl) {
            msgEl.style.color = 'var(--status-red)';
            msgEl.textContent = errMsg;
        }
        if (typeof window.showModalAlert === 'function') {
            await window.showModalAlert(errMsg, { title: 'Unable to Add Account', type: 'error' });
        } else {
            (window.showToast ? window.showToast(errMsg, 'error') : window.showModalAlert && window.showModalAlert('Notice', errMsg));
        }
        return false;
    }
}

async function nextOnboardingStep() {
    const msgEl = document.getElementById('onboarding-status-msg');
    if (msgEl) msgEl.textContent = '';

    const step = window.currentOnboardingStep || 1;
    try {
        if (step === 1) {
            const famName = (document.getElementById('ob-family-name')?.value || '').trim();
            const state = document.getElementById('ob-state')?.value || 'WA';
            const filing = document.getElementById('ob-filing-status')?.value || 'MFJ';
            if (famName) {
                await fetch('/api/family', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: famName }),
                });
            }
            await fetch('/api/settings/assumptions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ state: state, filing_status: filing }),
            });
            if (window.SandboxManager && typeof window.SandboxManager.markHasData === 'function') {
                window.SandboxManager.markHasData();
            }
            if (typeof window.updateOnboardingStepUI === 'function') {
                window.updateOnboardingStepUI(2);
            }
            return;
        }

        if (step === 2) {
            const pName = (document.getElementById('ob-primary-name')?.value || '').trim();
            const pBirth = (document.getElementById('ob-primary-birthdate')?.value || '').trim();
            const sName = (document.getElementById('ob-spouse-name')?.value || '').trim();
            const sEmail = (document.getElementById('ob-spouse-email')?.value || '').trim();
            const sBirth = (document.getElementById('ob-spouse-birthdate')?.value || '').trim();

            if (pName) {
                const resp = await fetch('/api/family/members', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: pName,
                        birthdate: pBirth,
                        relationship: 'primary',
                        role: 'editor',
                    }),
                });
                const res = await resp.json();
                if (!resp.ok || !res.success) {
                    const errMsg = res.error || 'Could not add household member.';
                    if (msgEl) {
                        msgEl.style.color = 'var(--status-red)';
                        msgEl.textContent = errMsg;
                    }
                    if (typeof window.showModalAlert === 'function') {
                        await window.showModalAlert(errMsg, { title: 'Unable to Add Member', type: 'error' });
                    } else {
                        (window.showToast ? window.showToast(errMsg, 'error') : window.showModalAlert && window.showModalAlert('Notice', errMsg));
                    }
                    return;
                }
            }
            if (sName) {
                const resp = await fetch('/api/family/members', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: sName,
                        email: sEmail,
                        birthdate: sBirth,
                        relationship: 'spouse',
                        role: 'editor',
                    }),
                });
                const res = await resp.json();
                if (!resp.ok || !res.success) {
                    const errMsg = res.error || 'Could not add spouse.';
                    if (msgEl) {
                        msgEl.style.color = 'var(--status-red)';
                        msgEl.textContent = errMsg;
                    }
                    if (typeof window.showModalAlert === 'function') {
                        await window.showModalAlert(errMsg, { title: 'Unable to Add Member', type: 'error' });
                    } else {
                        (window.showToast ? window.showToast(errMsg, 'error') : window.showModalAlert && window.showModalAlert('Notice', errMsg));
                    }
                    return;
                }
            }
            if (typeof window.updateOnboardingStepUI === 'function') {
                window.updateOnboardingStepUI(3);
            }
            return;
        }

        if (step === 3) {
            const pendingName = (document.getElementById('ob-manual-acc-name')?.value || '').trim();
            if (pendingName) {
                const ok = await onboardingAddQuickAccount();
                if (ok === false) return;
            }
            if (typeof window.updateOnboardingStepUI === 'function') {
                window.updateOnboardingStepUI(4);
            }
            return;
        }

        if (step === 4) {
            const salary = parseFloat(document.getElementById('ob-base-salary')?.value || '0') || 0;
            const bonus = parseFloat(document.getElementById('ob-annual-bonus')?.value || '0') || 0;
            const spending = parseFloat(document.getElementById('ob-annual-spending')?.value || '0') || 0;
            const retAge = parseInt(document.getElementById('ob-retirement-age')?.value || '65', 10) || 65;
            const state = document.getElementById('ob-state')?.value || 'WA';
            const filing = document.getElementById('ob-filing-status')?.value || 'MFJ';

            await fetch('/api/settings/assumptions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    state: state,
                    filing_status: filing,
                    annual_spending: spending,
                    retirement_age: retAge,
                }),
            });

            if (salary > 0 || bonus > 0) {
                const compResp = await fetch('/api/compensation', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        tax_year: 2026,
                        employer: 'Primary Household Income',
                        base_salary: salary,
                        annual_bonus: bonus,
                        income_source_type: 'w2',
                    }),
                });
                const compRes = await compResp.json();
                if (!compResp.ok || !compRes.success) {
                    const errMsg = compRes.error || 'Could not save compensation.';
                    if (msgEl) {
                        msgEl.style.color = 'var(--status-red)';
                        msgEl.textContent = errMsg;
                    }
                    if (typeof window.showModalAlert === 'function') {
                        await window.showModalAlert(errMsg, { title: 'Unable to Save Compensation', type: 'error' });
                    } else {
                        (window.showToast ? window.showToast(errMsg, 'error') : window.showModalAlert && window.showModalAlert('Notice', errMsg));
                    }
                    return;
                }
            }

            const geminiKey = (document.getElementById('onboarding-gemini-key')?.value || '').trim();
            if (geminiKey) {
                await fetch('/api/settings/ai_key', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ gemini_api_key: geminiKey }),
                });
            }

            await fetch('/api/onboarding/complete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ completed: true }),
            });

            if (typeof window.closeOnboardingWizard === 'function') {
                window.closeOnboardingWizard();
            }
        }
    } catch (err) {
        const errMsg = 'Error saving step: ' + err.message;
        if (msgEl) {
            msgEl.style.color = 'var(--status-red)';
            msgEl.textContent = errMsg;
        }
        if (typeof window.showModalAlert === 'function') {
            await window.showModalAlert(errMsg, { title: 'Onboarding Error', type: 'error' });
        } else {
            (window.showToast ? window.showToast(errMsg, 'error') : window.showModalAlert && window.showModalAlert('Notice', errMsg));
        }
    }
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        goToOnboardingStep,
        prevOnboardingStep,
        nextOnboardingStep,
        onboardingAddQuickAccount,
    });
}
