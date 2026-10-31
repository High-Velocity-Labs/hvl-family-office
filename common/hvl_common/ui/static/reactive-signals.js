/**
 * HVL Shared Reactive Signal & Session Primitives
 * Provides reactive domain-version signals, X-Domain-Versions header bridge,
 * cross-tab BroadcastChannel/localStorage sync, HTMX 502/503 retries, and session URL helpers.
 */
(function () {
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
            peek() { return val; }
        };
    }

    function effect(fn) {
        const runner = () => {
            const prev = _activeEffect;
            _activeEffect = runner;
            try { fn(); } finally { _activeEffect = prev; }
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
            _domainSignals.set(key, createSignal(Number(initialMap[key] || 1)));
        }
        return _domainSignals.get(key);
    }

    function getDomainVersionsSnapshot() {
        const out = Object.assign({}, (typeof window !== 'undefined' && window.__DOMAIN_VERSIONS__) || {});
        _domainSignals.forEach((sig, key) => { out[key] = sig.peek(); });
        return out;
    }

    let _domainBroadcastChannel = null;
    if (typeof window !== 'undefined' && typeof window.BroadcastChannel === 'function') {
        try { _domainBroadcastChannel = new BroadcastChannel(window.__HVL_DOMAIN_CHANNEL__ || 'hvl_fo_domains'); } catch (e) {}
    }

    function broadcastDomainVersions(versions) {
        if (!versions || typeof versions !== 'object') return;
        try { _domainBroadcastChannel?.postMessage({ type: 'domain_versions', versions, timestamp: Date.now() }); } catch (e) {}
        try { window.localStorage?.setItem('fo_LastMutation', JSON.stringify({ versions, timestamp: Date.now() })); } catch (e) {}
    }

    function handleDomainVersionsHeader(rawHeader, isRemote = false) {
        if (!rawHeader || typeof window === 'undefined' || typeof window.applyDomainVersions !== 'function') return false;
        try {
            const parsed = typeof rawHeader === 'string' ? JSON.parse(rawHeader) : rawHeader;
            if (parsed && typeof parsed === 'object') {
                window.applyDomainVersions(parsed);
                if (!isRemote) broadcastDomainVersions(parsed);
                return true;
            }
        } catch (e) {}
        return false;
    }

    function getSessionQuerySuffix() {
        const params = (typeof window !== 'undefined' && window.location) ? new URLSearchParams(window.location.search) : new URLSearchParams();
        const body = typeof document !== 'undefined' ? document.body : null;
        if ((body && (body.dataset.isSandbox === 'true' || body.getAttribute('data-is-sandbox') === 'true')) || params.get('sandbox') === '1') return 'sandbox=1';
        if ((body && (body.dataset.isDemo === 'true' || body.getAttribute('data-is-demo') === 'true')) || params.get('demo') === '1') return 'demo=1';
        if ((body && (body.dataset.isAdmin === 'true' || body.getAttribute('data-is-admin') === 'true')) || params.get('admin') === '1') return 'admin=1';
        return '';
    }

    function appendSessionQuery(path) {
        if (!path || typeof path !== 'string') return path;
        const suffix = getSessionQuerySuffix();
        if (!suffix || path.includes(suffix)) return path;
        const hashIdx = path.indexOf('#');
        const base = hashIdx >= 0 ? path.slice(0, hashIdx) : path;
        return `${base}${base.includes('?') ? '&' : '?'}${suffix}${hashIdx >= 0 ? path.slice(hashIdx) : ''}`;
    }

    function isDemoSession() {
        return typeof document !== 'undefined' && ((document.body && document.body.dataset.isDemo === 'true') || !!document.getElementById('demo-mode-banner'));
    }

    if (typeof window === 'undefined') return;
    Object.assign(window, {
        createSignal, effect, batch, getDomainSignal, getDomainVersionsSnapshot,
        broadcastDomainVersions, handleDomainVersionsHeader, getSessionQuerySuffix,
        appendSessionQuery, isDemoSession
    });

    if (window._hvlReactiveSignalsInitialized) return;
    window._hvlReactiveSignalsInitialized = true;

    const syncLocationSessionQuery = () => {
        const suffix = getSessionQuerySuffix();
        if (suffix && window.location && !(window.location.search || '').includes(suffix)) {
            try { window.history?.replaceState?.(null, '', appendSessionQuery((window.location.pathname || '/') + (window.location.search || '')) + (window.location.hash || '')); } catch (e) {}
        }
    };
    syncLocationSessionQuery();

    if (_domainBroadcastChannel) {
        _domainBroadcastChannel.addEventListener('message', (evt) => {
            const data = evt && evt.data;
            if (data && data.versions && typeof window.applyDomainVersions === 'function') handleDomainVersionsHeader(data.versions, true);
        });
    }

    window.addEventListener('storage', (evt) => {
        if (!evt || evt.key !== 'fo_LastMutation' || !evt.newValue) return;
        try {
            const data = JSON.parse(evt.newValue);
            if (data?.versions && typeof window.applyDomainVersions === 'function') handleDomainVersionsHeader(data.versions, true);
        } catch (e) {}
    });

    if (typeof window.fetch === 'function') {
        const _originalFetch = window.fetch;
        window.fetch = async function (...args) {
            if (typeof args[0] === 'string' && args[0].startsWith('/') && !args[0].startsWith('//')) args[0] = appendSessionQuery(args[0]);
            const response = await _originalFetch.apply(this, args);
            try {
                const reqUrl = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url) || '';
                const reqOpts = args[1] || {};
                let appliedHeader = false;
                if (response?.headers && typeof response.headers.get === 'function') {
                    const v = response.headers.get('X-App-Version');
                    if (v && typeof window.checkAppVersion === 'function') window.checkAppVersion(v);
                    const dv = response.headers.get('X-Domain-Versions');
                    if (dv && reqOpts.skipReactiveMorph) {
                        try {
                            const parsed = JSON.parse(dv);
                            if (parsed && typeof parsed === 'object') {
                                Object.entries(parsed).forEach(([k, val]) => {
                                    const numVal = Number(val), sig = getDomainSignal(k);
                                    if (Number.isFinite(numVal) && numVal > sig.peek()) sig.value = numVal;
                                });
                                window.__DOMAIN_VERSIONS__ = Object.assign({}, window.__DOMAIN_VERSIONS__ || {}, getDomainVersionsSnapshot());
                            }
                        } catch (e) {}
                        appliedHeader = true;
                    } else if (dv) {
                        appliedHeader = handleDomainVersionsHeader(dv);
                    }
                }
                const method = String(reqOpts.method || 'GET').toUpperCase();
                if (!appliedHeader && response?.ok && ['POST', 'PUT', 'DELETE', 'PATCH'].includes(method)) {
                    const inferred = typeof window.inferDomainsFromMutationUrl === 'function' ? window.inferDomainsFromMutationUrl(reqUrl) : [];
                    if (inferred.length > 0 && typeof window.bumpDomains === 'function') window.bumpDomains(inferred);
                }
            } catch (e) {}
            return response;
        };
    }

    if (typeof document !== 'undefined') {
        document.addEventListener('DOMContentLoaded', syncLocationSessionQuery);
        document.addEventListener('htmx:afterOnLoad', function (evt) {
            const xhr = evt.detail && evt.detail.xhr;
            if (!xhr || typeof xhr.getResponseHeader !== 'function') return;
            try {
                const v = xhr.getResponseHeader('X-App-Version');
                if (v && typeof window.checkAppVersion === 'function') window.checkAppVersion(v);
                const dv = xhr.getResponseHeader('X-Domain-Versions');
                if (dv) handleDomainVersionsHeader(dv);
            } catch (e) {}
        });

        document.addEventListener('htmx:responseError', function (evt) {
            const xhr = evt.detail && evt.detail.xhr;
            if (!xhr || (xhr.status !== 502 && xhr.status !== 503)) return;
            const config = evt.detail.requestConfig || {};
            if (config._isRetry) return;
            config._isRetry = true;
            setTimeout(() => {
                const path = (evt.detail.pathInfo && evt.detail.pathInfo.requestPath) || config.path;
                if (path && typeof window.htmx?.ajax === 'function') {
                    window.htmx.ajax((config.verb || 'GET').toUpperCase(), path, {
                        target: evt.detail.target, source: evt.detail.elt || evt.target,
                        headers: config.headers, values: config.parameters
                    });
                }
            }, 2000);
        });
    }
})();
