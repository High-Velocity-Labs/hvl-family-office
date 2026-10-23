/**
 * 4-Step Guided Onboarding Wizard & Household Setup Checklist Controller
 */

var currentOnboardingStep = 1;

function updateOnboardingStepUI(step) {
    currentOnboardingStep = Math.max(1, Math.min(4, parseInt(step, 10) || 1));
    if (typeof window !== 'undefined') {
        window.currentOnboardingStep = currentOnboardingStep;
    }
    for (let i = 1; i <= 4; i++) {
        const pane = document.getElementById(`onboarding-step-${i}`);
        if (pane) pane.style.display = i === currentOnboardingStep ? 'block' : 'none';
    }
    document.querySelectorAll('.ob-step-pill').forEach((pill) => {
        const s = parseInt(pill.getAttribute('data-step'), 10);
        if (s === currentOnboardingStep) {
            pill.style.borderColor = 'var(--accent-blue, #3B82F6)';
            pill.style.color = 'var(--text-primary)';
        } else {
            pill.style.borderColor = 'var(--border-color)';
            pill.style.color = 'var(--text-muted)';
        }
    });
    const badge = document.getElementById('onboarding-step-badge');
    if (badge) badge.textContent = `STEP ${currentOnboardingStep} OF 4`;

    const prevBtn = document.getElementById('btn-ob-prev');
    if (prevBtn) {
        const showPrev = currentOnboardingStep > 1;
        prevBtn.style.visibility = showPrev ? 'visible' : 'hidden';
        prevBtn.classList.toggle('ob-prev-hidden', !showPrev);
    }

    const nextBtn = document.getElementById('btn-ob-next');
    if (nextBtn) {
        nextBtn.textContent = currentOnboardingStep === 4 ? 'Complete Setup ✓' : 'Save & Continue →';
    }
    const msg = document.getElementById('onboarding-status-msg');
    if (msg) msg.textContent = '';
}

function _inferStateFromTimezone() {
    try {
        if (typeof Intl === 'undefined' || typeof Intl.DateTimeFormat !== 'function') return null;
        const tz = String(Intl.DateTimeFormat().resolvedOptions().timeZone || '');
        const tzMap = {
            'America/New_York': 'NY',
            'America/Detroit': 'NY',
            'America/Indiana/Indianapolis': 'IL',
            'America/Chicago': 'IL',
            'America/Matamoros': 'TX',
            'America/Denver': 'CO',
            'America/Boise': 'CO',
            'America/Phoenix': 'NV',
            'America/Los_Angeles': 'WA',
        };
        return tzMap[tz] || null;
    } catch (_) {
        return null;
    }
}

async function populateOnboardingFields() {
    try {
        const stateEl = document.getElementById('ob-state');
        if (stateEl && stateEl.getAttribute('data-has-saved-state') !== 'true') {
            const inferred = _inferStateFromTimezone();
            if (inferred && Array.from(stateEl.options || []).some(o => o.value === inferred)) {
                stateEl.value = inferred;
            }
        }
        const resp = await fetch('/api/family');
        if (!resp.ok) return;
        const data = await resp.json();
        if (!data.success) return;
        const members = data.members || [];
        const primary = members.find(m => m.relationship === 'primary' && m.name !== 'Household Owner' && m.name !== 'Owner') || members.find(m => m.relationship === 'primary');
        const spouse = members.find(m => m.relationship === 'spouse');
        const pNameEl = document.getElementById('ob-primary-name');
        const pBirthEl = document.getElementById('ob-primary-birthdate');
        const sNameEl = document.getElementById('ob-spouse-name');
        const sEmailEl = document.getElementById('ob-spouse-email');
        const sBirthEl = document.getElementById('ob-spouse-birthdate');
        if (primary && pNameEl && !pNameEl.value && primary.name !== 'Household Owner' && primary.name !== 'Owner') {
            pNameEl.value = primary.name || '';
            if (pBirthEl && primary.birthdate) pBirthEl.value = primary.birthdate;
        }
        if (spouse && sNameEl && !sNameEl.value) {
            sNameEl.value = spouse.name || '';
            if (sEmailEl && spouse.email) sEmailEl.value = spouse.email;
            if (sBirthEl && spouse.birthdate) sBirthEl.value = spouse.birthdate;
        }
    } catch (_) {}
}

function openOnboardingWizard(step) {
    const modal = document.getElementById('onboarding-wizard-modal');
    if (!modal) return;
    updateOnboardingStepUI(step || 1);
    populateOnboardingFields();
    modal.style.display = 'flex';
}

function closeOnboardingWizard() {
    const modal = document.getElementById('onboarding-wizard-modal');
    if (modal) modal.style.display = 'none';
}

function onboardingOpenIntegrations() {
    window._returnToOnboardingStep = currentOnboardingStep || 3;
    closeOnboardingWizard();
    if (typeof window.openSettingsModal === 'function') {
        window.openSettingsModal();
    } else {
        const modal = document.getElementById('settings-modal');
        if (modal) modal.style.display = 'flex';
    }
    if (typeof window.switchSettingsTab === 'function') {
        window.switchSettingsTab('monarch');
    }
}

async function fetchOnboardingStatus() {
    try {
        const resp = await fetch('/api/onboarding/status');
        if (resp.ok) {
            return await resp.json();
        }
    } catch (e) {}
    return null;
}

async function _readFileAsText(file) {
    if (file && typeof file.text === 'function') {
        return await file.text();
    }
    if (file && typeof file.content === 'string') {
        return file.content;
    }
    return await new Promise((resolve, reject) => {
        if (typeof FileReader === 'undefined') {
            resolve('');
            return;
        }
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ''));
        reader.onerror = () => reject(reader.error || new Error('Could not read CSV file'));
        reader.readAsText(file);
    });
}

async function importOnboardingBalancesCsv() {
    const fileInput = document.getElementById('onboarding-csv-file');
    const statusEl = document.getElementById('onboarding-csv-status-msg');
    if (!fileInput || !fileInput.files || !fileInput.files[0]) {
        if (statusEl) {
            statusEl.style.color = 'var(--status-red)';
            statusEl.textContent = 'Please select a CSV file to import.';
        }
        return false;
    }

    try {
        const csvText = await _readFileAsText(fileInput.files[0]);
        const resp = await fetch('/api/accounts/import_csv', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ csv_text: csvText }),
        });
        const res = await resp.json();
        if (resp.ok && res.success) {
            if (window.SandboxManager && typeof window.SandboxManager.markHasData === 'function') {
                window.SandboxManager.markHasData();
            }
            fileInput.value = '';
            const snapCount = res.imported ?? res.imported_rows ?? 0;
            const accCount = res.accounts_updated ?? res.accounts_created ?? 0;
            if (statusEl) {
                statusEl.style.color = 'var(--status-green, #10B981)';
                statusEl.textContent = `✓ Imported ${snapCount} snapshot(s) across ${accCount} account(s).`;
            }
            await fetchOnboardingStatus();
            return true;
        } else {
            const errMsg = res.error || 'CSV import failed.';
            if (statusEl) {
                statusEl.style.color = 'var(--status-red)';
                statusEl.textContent = errMsg;
            }
            return false;
        }
    } catch (err) {
        if (statusEl) {
            statusEl.style.color = 'var(--status-red)';
            statusEl.textContent = 'Import failed: ' + err.message;
        }
        return false;
    }
}

function downloadSampleBalancesCsv() {
    const sampleCsv = [
        'Date,Account Name,Balance,Role,Institution',
        '2026-01-01,Primary Checking,45000.00,cash_liquid,Household Bank',
        '2026-01-01,Joint Taxable Brokerage,350000.00,public_brokerage,Brokerage Custody',
        '2026-01-01,Retirement 401(k),420000.00,retirement,Retirement Plan',
        '2026-01-01,Primary Residence,950000.00,real_estate,Manual Valuation',
        '2026-01-01,Primary Mortgage,-520000.00,mortgages,Home Loans',
    ].join('\n') + '\n';

    if (typeof document !== 'undefined') {
        const blob = new Blob([sampleCsv], { type: 'text/csv;charset=utf-8;' });
        const url = (typeof URL !== 'undefined' && typeof URL.createObjectURL === 'function')
            ? URL.createObjectURL(blob)
            : 'data:text/csv;charset=utf-8,' + encodeURIComponent(sampleCsv);
        const link = document.createElement('a');
        link.href = url;
        link.setAttribute('download', 'sample_account_balances.csv');
        link.style.display = 'none';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        if (typeof URL !== 'undefined' && typeof URL.revokeObjectURL === 'function' && url.startsWith('blob:')) {
            URL.revokeObjectURL(url);
        }
        const statusEl = document.getElementById('onboarding-csv-status-msg');
        if (statusEl) {
            statusEl.style.color = 'var(--text-secondary)';
            statusEl.textContent = 'Downloaded sample_account_balances.csv template.';
        }
    }
    return sampleCsv;
}

async function dismissOnboardingChecklist() {
    try {
        await fetch('/api/onboarding/complete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dismissed: true }),
        });
        const card = document.getElementById('overview-setup-checklist');
        if (card) card.style.display = 'none';
    } catch (e) {}
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        currentOnboardingStep,
        updateOnboardingStepUI,
        openOnboardingWizard,
        closeOnboardingWizard,
        onboardingOpenIntegrations,
        importOnboardingBalancesCsv,
        downloadSampleBalancesCsv,
        fetchOnboardingStatus,
        dismissOnboardingChecklist,
    });
}

document.addEventListener('DOMContentLoaded', () => {
    try {
        const params = new URLSearchParams(window.location.search);
        const hasExplicitParam = params.get('onboarding') === '1';
        const shouldAutoShow = hasExplicitParam || (window.AUTO_LAUNCH_ONBOARDING && !sessionStorage.getItem('onboarding_auto_shown'));
        if (shouldAutoShow && document.body?.dataset?.isDemo !== 'true') {
            sessionStorage.setItem('onboarding_auto_shown', '1');
            setTimeout(() => openOnboardingWizard(1), 80);
            if (hasExplicitParam) {
                params.delete('onboarding');
                const qs = params.toString();
                const cleanUrl = window.location.pathname + (qs ? '?' + qs : '');
                window.history.replaceState({}, document.title, cleanUrl);
            }
        }
    } catch (e) {}
});
