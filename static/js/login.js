const urlParams = new URLSearchParams(window.location.search);
const authError = urlParams.get('auth_error');
const wasDeleted = urlParams.get('deleted') === '1';
const wasSandboxWiped = urlParams.get('sandbox_wiped') === '1';

if (authError) {
    showAuthError(decodeURIComponent(authError));
} else if (wasSandboxWiped) {
    const banner = document.getElementById('auth-error-banner');
    if (banner) {
        banner.style.display = 'block';
        banner.style.background = 'var(--bg-surface-elevated)';
        banner.style.borderColor = 'var(--status-green)';
        banner.style.color = 'var(--text-primary)';
        banner.textContent = 'Your ephemeral sandbox database and encryption key have been permanently wiped from the server.';
    }
} else if (wasDeleted) {
    const banner = document.getElementById('auth-error-banner');
    if (banner) {
        banner.style.display = 'block';
        banner.style.background = 'var(--bg-surface-elevated)';
        banner.style.borderColor = 'var(--status-green)';
        banner.style.color = 'var(--text-primary)';
        banner.textContent = 'Your household database and encryption keys have been permanently deleted from our servers.';
    }
}

function showAuthError(msg) {
    const banner = document.getElementById('auth-error-banner');
    if (banner) {
        banner.style.display = 'block';
        const safeMsg = typeof escapeHtml === 'function' ? escapeHtml(msg) : String(msg || '');
        banner.innerHTML = '<div style="font-weight: 700; margin-bottom: 4px;">Sign-In Notice</div><div>' + safeMsg + '</div><div style="margin-top: 8px; font-size: 0.8125rem; display: flex; flex-wrap: wrap; justify-content: center; gap: 10px;"><a href="/sandbox" style="color: var(--accent-blue); text-decoration: underline; font-weight: 600;">Launch Zero-Retention Sandbox →</a><a href="/demo/jones" style="color: var(--accent-blue); text-decoration: underline; font-weight: 600;">Explore Demo Profiles →</a><a href="/features#download" style="color: var(--status-green); text-decoration: underline; font-weight: 600;">Download Desktop App →</a></div>';
        try {
            banner.scrollIntoView({ behavior: 'smooth', block: 'center' });
        } catch (e) {}
    }
    try {
        if (window.google && window.google.accounts && window.google.accounts.id) {
            window.google.accounts.id.cancel();
        }
    } catch (e) {}
    initGIS();
}

async function handleCredentialResponse(response) {
    const banner = document.getElementById('auth-error-banner');
    if (banner) banner.style.display = 'none';

    try {
        const resp = await fetch('/auth/google/verify_credential', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ credential: response.credential })
        });

        let data = null;
        try {
            data = await resp.json();
        } catch (jsonErr) {
            data = { success: false, error: 'Server authentication returned unexpected response (HTTP ' + resp.status + ')' };
        }

        if (data && data.success) {
            window.location.href = data.redirect || '/';
        } else {
            showAuthError(data ? data.error : 'Access denied for this Google account.');
        }
    } catch (err) {
        showAuthError('Sign-in error: ' + err.message);
    }
}

function initGIS() {
    fetch('/auth/google/config')
        .then(r => r.json())
        .then(cfg => {
            if (cfg && cfg.client_id && window.google && window.google.accounts && window.google.accounts.id) {
                google.accounts.id.initialize({
                    client_id: cfg.client_id,
                    callback: handleCredentialResponse,
                    auto_select: false,
                    cancel_on_tap_outside: true,
                });
            }
        })
        .catch(e => console.warn('GIS config load:', e));
}

if (window.google && window.google.accounts) {
    initGIS();
} else {
    window.addEventListener('load', () => setTimeout(initGIS, 250));
}

const localSetupForm = document.getElementById('local-setup-form');
if (localSetupForm) {
    localSetupForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const nameEl = document.getElementById('local-setup-name');
        const hhEl = document.getElementById('local-setup-household');
        const passEl = document.getElementById('local-setup-passphrase');
        const btn = document.getElementById('local-setup-submit-btn');
        if (btn) btn.disabled = true;
        try {
            const resp = await fetch('/api/desktop/local-setup', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    owner_name: nameEl ? nameEl.value : '',
                    household_name: hhEl ? hhEl.value : '',
                    passphrase: passEl ? passEl.value : ''
                })
            });
            const data = await resp.json();
            if (data && data.success) {
                window.location.href = data.redirect || '/?onboarding=1';
            } else {
                showAuthError(data && data.error ? data.error : 'Failed to initialize local vault.');
                if (btn) btn.disabled = false;
            }
        } catch (err) {
            showAuthError('Local setup error: ' + err.message);
            if (btn) btn.disabled = false;
        }
    });
}

const localLoginForm = document.getElementById('local-login-form');
if (localLoginForm) {
    localLoginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const passEl = document.getElementById('local-login-passphrase');
        const btn = document.getElementById('local-login-submit-btn');
        if (btn) btn.disabled = true;
        try {
            const resp = await fetch('/api/desktop/local-login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    passphrase: passEl ? passEl.value : ''
                })
            });
            const data = await resp.json();
            if (data && data.success) {
                window.location.href = data.redirect || '/';
            } else {
                showAuthError(data && data.error ? data.error : 'Invalid Master Passphrase or PIN.');
                if (btn) btn.disabled = false;
            }
        } catch (err) {
            showAuthError('Local login error: ' + err.message);
            if (btn) btn.disabled = false;
        }
    });
}

const btnToggleForgotPin = document.getElementById('btn-toggle-forgot-pin');
const resetPinPanel = document.getElementById('local-reset-pin-panel');
if (btnToggleForgotPin && resetPinPanel) {
    btnToggleForgotPin.addEventListener('click', () => {
        resetPinPanel.style.display = resetPinPanel.style.display === 'none' ? 'block' : 'none';
    });
}

const btnResetPinSubmit = document.getElementById('local-reset-submit-btn');
if (btnResetPinSubmit) {
    btnResetPinSubmit.addEventListener('click', async () => {
        const recoveryKey = (document.getElementById('local-reset-recovery-key')?.value || '').trim();
        const newPin = (document.getElementById('local-reset-new-passphrase')?.value || '').trim();
        if (!recoveryKey) {
            showAuthError('Please paste your 44-character Local Recovery Key (.secret.key).');
            return;
        }
        if (newPin.length < 4) {
            showAuthError('New Master Passphrase or PIN must be at least 4 characters.');
            return;
        }
        btnResetPinSubmit.disabled = true;
        try {
            const resp = await fetch('/api/desktop/reset-passphrase', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ recovery_key: recoveryKey, new_passphrase: newPin })
            });
            const data = await resp.json();
            if (data && data.success) {
                window.location.href = data.redirect || '/';
            } else {
                showAuthError((data && data.error) || 'Could not reset PIN.');
                btnResetPinSubmit.disabled = false;
            }
        } catch (err) {
            showAuthError('PIN reset error: ' + err.message);
            btnResetPinSubmit.disabled = false;
        }
    });
}

const btnLoginOpenBrowser = document.getElementById('btn-login-open-browser');
if (btnLoginOpenBrowser) {
    btnLoginOpenBrowser.addEventListener('click', async () => {
        try {
            await fetch('/api/desktop/open-browser', { method: 'POST' });
            btnLoginOpenBrowser.textContent = '✓ Opened in your default web browser';
        } catch (e) {}
    });
}
