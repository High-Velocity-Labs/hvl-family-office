/**
 * HVL Family Office - App Sync, Session Management & Reactive Signal Primitives
 * Provides reactive domain-version signals, X-Domain-Versions header bridge,
 * session URL queries, demo/prod logout, and Monarch/SimpleFIN account sync.
 */

let _activeEffect = null;
let _batchDepth = 0;
const _pendingEffects = new Set();
const _domainSignals = new Map();

function createSignal(initialValue) {
    let val = initialValue;
    const subs = new Set();
    return {
        get value() {
            if (_activeEffect) subs.add(_activeEffect);
            return val;
        },
        set value(next) {
            if (Object.is(val, next)) return;
            val = next;
            subs.forEach(fn => {
                if (_batchDepth > 0) _pendingEffects.add(fn);
                else fn();
            });
        },
        peek() {
            return val;
        }
    };
}

function effect(fn) {
    const runner = () => {
        const prev = _activeEffect;
        _activeEffect = runner;
        try {
            fn();
        } finally {
            _activeEffect = prev;
        }
    };
    runner();
    return runner;
}

function batch(fn) {
    _batchDepth += 1;
    try {
        return fn();
    } finally {
        _batchDepth -= 1;
        if (_batchDepth === 0 && _pendingEffects.size > 0) {
            const effectsToRun = Array.from(_pendingEffects);
            _pendingEffects.clear();
            effectsToRun.forEach(eff => eff());
        }
    }
}

function getDomainSignal(domain) {
    const key = String(domain || '').trim();
    if (!_domainSignals.has(key)) {
        const initialMap = (typeof window !== 'undefined' && window.__DOMAIN_VERSIONS__) || {};
        const initVal = Number(initialMap[key] || 1);
        _domainSignals.set(key, createSignal(initVal));
    }
    return _domainSignals.get(key);
}

function getDomainVersionsSnapshot() {
    const out = Object.assign({}, (typeof window !== 'undefined' && window.__DOMAIN_VERSIONS__) || {});
    _domainSignals.forEach((sig, key) => {
        out[key] = sig.peek();
    });
    return out;
}

function inferDomainsFromMutationUrl(url) {
    const path = String(url || '').toLowerCase();
    if (!path.includes('/api/')) return [];
    if (path.includes('/api/accounts/toggle_net_worth') || path.includes('/api/settings/account_roles') || path.includes('/api/settings/confirm_all_roles')) {
        return ['accounts', 'balance_sheet', 'college', 'estate'];
    }
    if (path.includes('/api/accounts') || path.includes('/api/sync') || path.includes('/api/settings/simplefin') || path.includes('/api/settings/monarch')) {
        return ['accounts', 'balance_sheet', 'holdings', 'onboarding.checklist'];
    }
    if (path.includes('/api/holdings')) return ['holdings', 'holdings.policy'];
    if (path.includes('/api/equity')) return ['equity', 'balance_sheet', 'onboarding.checklist'];
    if (path.includes('/api/settings/assumptions') || path.includes('/api/tax')) return ['tax_profile', 'scenarios', 'balance_sheet', 'household.identity'];
    if (path.includes('/api/scenarios') || path.includes('/api/events')) return ['scenarios'];
    if (path.includes('/api/compensation') || path.includes('/api/transcripts')) return ['compensation', 'tax_profile', 'onboarding.checklist'];
    if (path.includes('/api/philanthropy')) return ['philanthropy'];
    if (path.includes('/api/gifting')) return ['gifting', 'estate'];
    if (path.includes('/api/estate')) return ['estate', 'onboarding.checklist'];
    if (path.includes('/api/education') || path.includes('/api/college')) return ['college'];
    if (path.includes('/api/family/invites')) return ['settings.invites'];
    if (path.includes('/api/family/members')) return ['household.members', 'college', 'estate', 'gifting', 'onboarding.checklist'];
    if (path.includes('/api/family')) return ['household.identity', 'household.members', 'tax_profile', 'onboarding.checklist'];
    if (path.includes('/api/onboarding')) return ['onboarding.checklist'];
    return [];
}

function handleDomainVersionsHeader(rawHeader) {
    if (!rawHeader || typeof window === 'undefined' || typeof window.applyDomainVersions !== 'function') return false;
    try {
        const parsed = typeof rawHeader === 'string' ? JSON.parse(rawHeader) : rawHeader;
        if (parsed && typeof parsed === 'object') {
            window.applyDomainVersions(parsed);
            return true;
        }
    } catch (e) {}
    return false;
}

function getSessionQuerySuffix() {
    const params = (typeof window !== 'undefined' && window.location) ? new URLSearchParams(window.location.search) : new URLSearchParams();
    const isSandbox = (document.body && (document.body.dataset.isSandbox === 'true' || document.body.getAttribute('data-is-sandbox') === 'true')) || params.get('sandbox') === '1';
    if (isSandbox) return 'sandbox=1';
    const isDemo = (document.body && (document.body.dataset.isDemo === 'true' || document.body.getAttribute('data-is-demo') === 'true')) || params.get('demo') === '1';
    if (isDemo) return 'demo=1';
    const isAdmin = (document.body && (document.body.dataset.isAdmin === 'true' || document.body.getAttribute('data-is-admin') === 'true')) || params.get('admin') === '1';
    if (isAdmin) return 'admin=1';
    return '';
}

function appendSessionQuery(path) {
    const suffix = getSessionQuerySuffix();
    if (!suffix) return path;
    const separator = path.includes('?') ? '&' : '?';
    return `${path}${separator}${suffix}`;
}

function isDemoSession() {
    return (document.body && document.body.dataset.isDemo === 'true') || !!document.getElementById('demo-mode-banner');
}

async function doLogout() {
    if (document.body && document.body.dataset.isSandbox === 'true' && window.SandboxManager && typeof window.SandboxManager.wipeSandboxNow === 'function') {
        await window.SandboxManager.wipeSandboxNow();
        return;
    }
    const isDemo = isDemoSession();
    const confirmMsg = isDemo ? 'Exit Demo sandbox and return to login?' : 'Sign out of Family Office portal?';
    const confirmTitle = isDemo ? 'Exit Demo' : 'Sign Out';
    if (window.showModalConfirm && await window.showModalConfirm(confirmMsg, { title: confirmTitle, confirmText: confirmTitle, confirmVariant: 'danger' })) {
        if (isDemo) {
            window.location.href = '/exit-demo';
        } else {
            await fetch('/api/auth/logout', { method: 'POST' });
            window.location.href = '/login';
        }
    }
}

async function pollMonarchSyncStatus(jobId, maxAttempts = 150, intervalMs = 600) {
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
        await new Promise(resolve => setTimeout(resolve, intervalMs));
        const pollResp = await fetch(`/api/sync/status/${encodeURIComponent(jobId)}`);
        const pollData = await pollResp.json();
        if (pollData.status !== 'processing') {
            return pollData;
        }
    }
    return { success: false, status: 'failed', error: 'Account sync timed out while processing.' };
}

async function triggerMonarchSync() {
    const btnSync = document.getElementById('btn-sync');
    const btnMobileSync = document.getElementById('btn-mobile-sync');
    const btnSettingsSync = document.getElementById('btn-settings-test-sync');
    const syncButtons = [btnSync, btnMobileSync, btnSettingsSync].filter(Boolean);

    const syncTexts = document.querySelectorAll('#sync-btn-text, #mobile-sync-btn-text');
    syncTexts.forEach(el => el.textContent = 'Syncing...');
    if (btnSettingsSync) btnSettingsSync.textContent = 'Syncing...';
    syncButtons.forEach(btn => { btn.disabled = true; btn.classList.add('is-syncing'); });

    try {
        const resp = await fetch('/api/sync', { method: 'POST' });
        let res = await resp.json();
        const syncJobId = res.job_id || res.sync_job_id;
        const isProcessing = (res.status === 'processing' || res.sync_status === 'processing');
        if (res.success && isProcessing && syncJobId) {
            res = await pollMonarchSyncStatus(syncJobId, 150, 600);
        }
        syncButtons.forEach(btn => btn.classList.remove('is-syncing'));
        if (res.success) {
            if (typeof window.morphSettingsModal === 'function' && document.getElementById('settings-modal')?.classList.contains('active')) {
                try {
                    await window.morphSettingsModal({ tab: 'monarch' });
                } catch (e) {
                    console.warn('Post-sync settings modal refresh warning:', e);
                }
            }
            syncTexts.forEach(el => el.textContent = '✓ Synced');
            if (btnSettingsSync) btnSettingsSync.textContent = '✓ Sync Complete';
            if (window.showModalAlert) {
                await window.showModalAlert(res.message || `Account sync successful! Updated ${res.accounts_count || 0} accounts.`, { title: 'Sync Complete' });
            }
        } else if (window.showModalAlert) {
            await window.showModalAlert(`Sync Issue: ${res.error || 'Check account connection credentials'}`, { title: 'Sync Failed' });
        }
    } catch (err) {
        if (window.showModalAlert) {
            await window.showModalAlert(`Sync Failed: ${err.message}`, { title: 'Sync Error' });
        }
    } finally {
        const isDemo = isDemoSession();
        syncTexts.forEach(el => {
            el.textContent = isDemo ? 'Sync (Demo)' : 'Sync Accounts';
        });
        if (btnSettingsSync) btnSettingsSync.textContent = '↻ Sync Accounts Now';
        syncButtons.forEach(btn => { btn.disabled = false; btn.classList.remove('is-syncing'); });
    }
}

function showUpdateNotification(newVersion) {
    if (typeof document === 'undefined') return;
    let pill = document.getElementById('app-update-pill');
    if (!pill) {
        pill = document.createElement('button');
        pill.id = 'app-update-pill';
        pill.type = 'button';
        pill.className = 'btn btn-sm btn-update-pill';
        pill.innerHTML = '✨ Update available — <span style="text-decoration: underline; font-weight: 700;">Reload</span>';
        pill.setAttribute('data-tooltip', 'A new version of HVL Family Office was deployed. Click to reload.');
        pill.style.cssText = 'background: rgba(59, 130, 246, 0.12); color: var(--accent-blue, #3b82f6); border: 1px solid var(--accent-blue, #3b82f6); border-radius: var(--radius-badge, 6px); font-weight: 600; font-size: 0.75rem; padding: 4px 10px; cursor: pointer; display: inline-flex; align-items: center; gap: 4px; z-index: 100; transition: all 0.2s ease;';
        pill.onclick = () => window.location.reload();

        const container = document.querySelector('.header-actions') || document.querySelector('.top-header') || document.body;
        if (container.classList && container.classList.contains('header-actions')) {
            container.prepend(pill);
        } else {
            container.appendChild(pill);
        }
    } else {
        pill.style.display = 'inline-flex';
    }
}

function checkAppVersion(serverVersion) {
    if (!serverVersion || typeof window === 'undefined' || !window.__APP_VERSION__) return;
    const cleanServer = String(serverVersion).trim();
    const cleanCurrent = String(window.__APP_VERSION__).trim();
    if (cleanServer && cleanCurrent && cleanServer !== cleanCurrent) {
        showUpdateNotification(cleanServer);
    }
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        createSignal,
        effect,
        batch,
        getDomainSignal,
        getDomainVersionsSnapshot,
        inferDomainsFromMutationUrl,
        handleDomainVersionsHeader,
        getSessionQuerySuffix,
        appendSessionQuery,
        isDemoSession,
        doLogout,
        pollMonarchSyncStatus,
        triggerMonarchSync,
        checkAppVersion,
        showUpdateNotification
    });

    if (typeof window.fetch === 'function') {
        const _originalFetch = window.fetch;
        window.fetch = async function (...args) {
            const response = await _originalFetch.apply(this, args);
            try {
                const reqUrl = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url) || '';
                const reqOpts = args[1] || {};
                let appliedHeader = false;
                if (response && response.headers && typeof response.headers.get === 'function') {
                    const v = response.headers.get('X-App-Version');
                    if (v) checkAppVersion(v);
                    const dv = response.headers.get('X-Domain-Versions');
                    if (dv) {
                        if (reqOpts.skipReactiveMorph) {
                            try {
                                const parsed = JSON.parse(dv);
                                if (parsed && typeof parsed === 'object') {
                                    window.__DOMAIN_VERSIONS__ = Object.assign({}, window.__DOMAIN_VERSIONS__ || {}, parsed);
                                    Object.entries(parsed).forEach(([k, val]) => { getDomainSignal(k).value = Number(val); });
                                }
                            } catch (e) {}
                            appliedHeader = true;
                        } else {
                            appliedHeader = handleDomainVersionsHeader(dv);
                        }
                    }
                }
                const method = String(reqOpts.method || 'GET').toUpperCase();
                if (!appliedHeader && response && response.ok && ['POST', 'PUT', 'DELETE', 'PATCH'].includes(method)) {
                    const inferred = inferDomainsFromMutationUrl(reqUrl);
                    if (inferred.length > 0 && typeof window.bumpDomains === 'function') {
                        window.bumpDomains(inferred);
                    }
                }
            } catch (e) {}
            return response;
        };
    }
}

if (typeof document !== 'undefined') {
    document.addEventListener('htmx:afterOnLoad', function (evt) {
        const xhr = evt.detail && evt.detail.xhr;
        if (xhr && typeof xhr.getResponseHeader === 'function') {
            try {
                const v = xhr.getResponseHeader('X-App-Version');
                if (v) checkAppVersion(v);
                const dv = xhr.getResponseHeader('X-Domain-Versions');
                if (dv) handleDomainVersionsHeader(dv);
            } catch (e) {}
        }
    });

    document.addEventListener('htmx:responseError', function (evt) {
        const xhr = evt.detail && evt.detail.xhr;
        if (!xhr) return;
        const status = xhr.status;
        if (status === 502 || status === 503) {
            const config = evt.detail.requestConfig || {};
            if (!config._isRetry) {
                config._isRetry = true;
                setTimeout(() => {
                    if (typeof window.htmx?.ajax === 'function') {
                        const verb = (config.verb || 'GET').toUpperCase();
                        const path = (evt.detail.pathInfo && evt.detail.pathInfo.requestPath) || config.path;
                        if (path) {
                            window.htmx.ajax(verb, path, {
                                target: evt.detail.target,
                                source: evt.detail.elt || evt.target,
                                headers: config.headers,
                                values: config.parameters
                            });
                        }
                    }
                }, 2000);
            }
        }
    });
}
