/**
 * AI Advisor fragment client: every piece of advisor markup (bubbles, welcome message, thread cards, chips, quota
 * label, demo notices) is rendered by the server under /fragments/advisor/* and swapped in with htmx.
 * This module only picks the URL and the swap target; it never builds or assigns HTML.
 */

(function () {
    const BASE = '/fragments/advisor';

    function messagesEl() { return document.getElementById('ai-advisor-messages'); }

    /** Runs one htmx request; resolves true when the request completed, false on a transport failure. */
    async function swap(verb, path, target, options = {}) {
        if (!target) return false;
        try {
            await window.htmx.ajax(verb, `${BASE}${path}`, {
                target,
                swap: options.swap || 'innerHTML',
                values: options.values
            });
            return true;
        } catch (err) {
            console.warn(`Advisor fragment ${path} failed:`, err);
            return false;
        }
    }

    /**
     * Appends one chat bubble and returns the element, or null when the request failed. `source` names what the server
     * renders from: { job: jobId } | { demo_for: userText } | { notice: text }; { user: text } clones the drawer's
     * server-rendered #advisor-user-bubble template instead, so the message never travels in a URL. Bot reply text is
     * never sent to the server; it renders from the household's stored job result.
     */
    async function appendMessage(source) {
        const container = messagesEl();
        if (source.user !== undefined) return appendUserBubble(container, source.user);
        const ok = await swap('GET', '/message', container, { swap: 'beforeend', values: source });
        return ok && container ? container.lastElementChild : null;
    }

    /** Clones the server-rendered user bubble and fills its text slot with textContent (line breaks via CSS). */
    function appendUserBubble(container, text) {
        const tpl = document.getElementById('advisor-user-bubble');
        if (!container || !tpl) return null;
        const bubble = tpl.content.firstElementChild.cloneNode(true);
        bubble.querySelector('[data-bubble-text]').textContent = String(text);
        container.appendChild(bubble);
        return bubble;
    }

    function showWelcome(tab) {
        return swap('GET', '/welcome', messagesEl(), { values: { tab } });
    }

    function refreshWelcomeBody(tab) {
        return swap('GET', '/welcome', document.getElementById('advisor-welcome-body'), {
            values: { tab, part: 'body' }
        });
    }

    function refreshThreadList(filter, query, tab, activeId) {
        return swap('GET', '/conversations', document.getElementById('advisor-conversations-list'), {
            values: { filter, q: query, tab, active: activeId || '' }
        });
    }

    /** Loads a saved transcript; resolves with the state element the fragment refreshed, or null on failure. */
    async function loadConversation(convId, tab) {
        const container = messagesEl();
        if (!container) return null;
        container.setAttribute('aria-busy', 'true');
        try {
            await swap('GET', `/conversation/${encodeURIComponent(convId)}`, container, { values: { tab } });
        } finally {
            container.removeAttribute('aria-busy');
        }
        const state = document.getElementById('advisor-conv-state');
        return state && state.dataset.convId === convId ? state : null;
    }

    function renderChips(prompts) {
        return swap('GET', '/chips', document.getElementById('advisor-suggestion-chips'), { values: { s: prompts } });
    }

    function renderQuota(tier, label) {
        return swap('GET', '/quota', document.getElementById('advisor-tier-label'), { values: { tier, label } });
    }

    async function showDemoNotice(notice) {
        const header = document.querySelector('.ai-advisor-header');
        if (header && !document.getElementById('advisor-demo-badge-bar')) {
            await swap('GET', '/demo', header, { swap: 'afterend', values: { part: 'badge' } });
        }
        if (messagesEl() && !document.getElementById('advisor-demo-guard-banner')) {
            await swap('GET', '/demo', messagesEl(), { swap: 'beforeend', values: { notice: notice || '' } });
        }
    }

    window.AdvisorFragments = {
        swap, appendMessage, showWelcome, refreshWelcomeBody, refreshThreadList, loadConversation, renderChips,
        renderQuota, showDemoNotice
    };
})();
