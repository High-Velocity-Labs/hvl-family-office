/**
 * Shared JSDOM test harness for High Velocity Labs client-side JavaScript testing.
 * Provides a standardized headless browser environment with mocked UI modals,
 * localStorage, and an extensible URL-pattern mock fetch registry.
 */

function getJsdomClass(explicitJsdom) {
    if (explicitJsdom) return explicitJsdom;
    try {
        return require('jsdom').JSDOM;
    } catch {
        try {
            const resolvedPath = require.resolve('jsdom', { paths: [process.cwd(), __dirname] });
            return require(resolvedPath).JSDOM;
        } catch (err) {
            throw new Error(`JSDOM not found. Ensure 'jsdom' is installed in your project: ${err.message}`);
        }
    }
}

function createTestDomEnvironment(options = {}) {
    const JSDOM = getJsdomClass(options.JSDOM);

    const {
        html = '<!DOCTYPE html><html><head></head><body></body></html>',
        url = 'https://highvelocitylabs.dev/',
        storage = {},
        fetchHandlers = [],
    } = options;

    const dom = new JSDOM(html, {
        url,
        runScripts: 'dangerously',
        resources: 'usable',
    });

    const window = dom.window;
    const document = window.document;

    // In-memory localStorage mock
    const localStorageStore = { ...storage };
    window.localStorage = {
        getItem: (k) => (k in localStorageStore ? localStorageStore[k] : null),
        setItem: (k, v) => { localStorageStore[k] = String(v); },
        removeItem: (k) => { delete localStorageStore[k]; },
        clear: () => { Object.keys(localStorageStore).forEach((k) => delete localStorageStore[k]); },
    };

    // UI Dialog mocks
    window.__alerts = [];
    window.alert = (msg) => {
        window.__lastAlert = msg;
        window.__alerts.push(msg);
    };

    window.__confirms = [];
    window.__confirmResponse = true;
    window.confirm = (msg) => {
        window.__lastConfirm = msg;
        window.__confirms.push(msg);
        return window.__confirmResponse;
    };

    window.showModalConfirm = async (msg, opts = {}) => {
        window.__lastConfirm = msg;
        window.__lastConfirmMsg = msg;
        window.__lastConfirmOpts = opts;
        window.__lastConfirmTitle = opts.title;
        return true;
    };

    window.showModalAlert = async (msg, opts = {}) => {
        window.__lastAlert = msg;
        window.__lastAlertMsg = msg;
        window.__lastAlertOpts = opts;
        return true;
    };

    window.showToast = (msg, variant = 'info') => {
        window.__lastToastMsg = String(msg || '');
        window.__lastToastVariant = variant || 'info';
        return { dismiss: () => {} };
    };
    window.hvlShowToast = window.showToast;

    // Extensible Fetch Mock
    const handlers = [...fetchHandlers];

    function registerFetchHandler(matcher, handler) {
        handlers.push({ matcher, handler });
    }

    window.fetch = async (inputUrl, fetchOptions = {}) => {
        const urlStr = typeof inputUrl === 'string' ? inputUrl : (inputUrl && inputUrl.url) || '';
        const method = fetchOptions.method || 'GET';

        for (const { matcher, handler } of handlers) {
            const matches = typeof matcher === 'function' ? matcher(urlStr, fetchOptions) :
                            matcher instanceof RegExp ? matcher.test(urlStr) :
                            urlStr.includes(matcher);

            if (matches) {
                const res = await handler(urlStr, fetchOptions);
                if (res) return res;
            }
        }

        // Default empty 200 response if no handler matched
        return {
            ok: true,
            status: 200,
            json: async () => ({ success: true }),
            text: async () => JSON.stringify({ success: true }),
        };
    };

    return {
        dom,
        window,
        document,
        registerFetchHandler,
        localStorageStore,
    };
}

module.exports = {
    createTestDomEnvironment,
};
