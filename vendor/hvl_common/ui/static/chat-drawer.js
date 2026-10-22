/**
 * High Velocity Labs Shared AI Chat Drawer Core Engine (hvl_common)
 * File: /common/chat-drawer.js
 *
 * Unified clientside orchestration for Gemini AI chat drawers & panels:
 * - Markdown rendering + XSS sanitization
 * - Relative time formatting
 * - Animated typing indicator lifecycle
 * - Deterministic top-aligned scroll geometry
 * - Background async job polling with 429 backoff
 * - Thread history CRUD & search/pin filtering
 *
 * UMD: Works in browser window, Node.js (JSDOM), and ES/CJS modules.
 */
(function (root, factory) {
  const lib = factory();
  if (typeof exports === 'object' && typeof module !== 'undefined') {
    module.exports = lib;
  }
  const target = (typeof window !== 'undefined') ? window : root;
  if (target) {
    target.hvlChatDrawer = lib;
    target.renderChatMarkdown = lib.renderChatMarkdown;
    target.hydrateChatMarkdown = lib.hydrateChatMarkdown;
    target.appendAssistantChatTurn = lib.appendAssistantChatTurn;
    target.sanitizeChatHtml = lib.sanitizeChatHtml;
    target.formatRelativeChatTime = lib.formatRelativeChatTime;
    target.scrollChatToElement = lib.scrollChatToElement;
    target.scrollChatToBottom = lib.scrollChatToBottom;
    target.createTypingIndicator = lib.createTypingIndicator;
    target.pollChatJob = lib.pollChatJob;
    target.createChatDrawerController = lib.createChatDrawerController;
  }
}(typeof globalThis !== 'undefined' ? globalThis : typeof window !== 'undefined' ? window : this, function () {
  'use strict';

  /**
   * Escape HTML entities to protect against XSS.
   */
  function escapeHtml(str) {
    if (typeof window !== 'undefined' && typeof window.escapeHtml === 'function') {
      return window.escapeHtml(str);
    }
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /**
   * Sanitize rendered HTML string by removing scripts, iframes, and onerror/onload attributes.
   */
  function sanitizeChatHtml(html) {
    if (!html) return '';
    return String(html)
      .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
      .replace(/<iframe\b[^<]*(?:(?!<\/iframe>)<[^<]*)*<\/iframe>/gi, '')
      .replace(/<object\b[^<]*(?:(?!<\/object>)<[^<]*)*<\/object>/gi, '')
      .replace(/\s+on\w+\s*=\s*(?:'[^']*'|"[^"]*"|[^\s>]+)/gi, '')
      .replace(/javascript:/gi, 'blocked:')
      .replace(/<a\s+(?![^>]*\btarget=)([^>]*href=["']https?:\/\/[^>]*)>/gi, '<a target="_blank" rel="noopener noreferrer" $1>');
  }

  /**
   * Parse markdown text into safe HTML using marked if present, or deterministic fallback.
   */
  function renderChatMarkdown(text) {
    if (!text) return '';
    if (typeof window !== 'undefined' && window.marked && typeof window.marked.parse === 'function') {
      try {
        const rawHtml = window.marked.parse(text, { breaks: true, gfm: true });
        return `<div class="hvl-chat-markdown">${sanitizeChatHtml(rawHtml)}</div>`;
      } catch (err) {
        console.warn('[hvlChatDrawer] marked.parse failed, falling back to simple parser:', err);
      }
    }

    // Fallback lightweight parser
    let html = escapeHtml(text);
    html = html.replace(/```([\s\S]*?)```/g, '<pre><code class="font-mono">$1</code></pre>');
    html = html.replace(/`([^`]+)`/g, '<code class="font-mono">$1</code>');
    html = html.replace(/^#{1,4}\s+(.+)$/gm, (_m, h) => `<strong class="ff-text-strong">${h.replace(/^\*\*|\*\*$/g, '')}</strong>`);
    html = html.replace(/^[ \t]*[*-]\s+/gm, '• ');
    html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong class="ff-text-strong">$1</strong>');
    html = html.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>');
    html = html.replace(/\n\n+/g, '</p><p>');
    html = html.replace(/\n/g, '<br>');
    return `<div class="hvl-chat-markdown"><p>${html}</p></div>`;
  }

  const DEFAULT_MARKDOWN_SELECTOR = '.asst-msg-bubble.assistant .asst-msg-text, .ai-advisor-msg-assistant .ai-advisor-msg-body, .ff-chat-bubble-bot .ff-chat-bubble-content, [data-chat-markdown]';

  /** Hydrates assistant message bubbles into rendered markdown and upgrades SSR fallback HTML when marked is loaded. */
  function hydrateChatMarkdown(rootEl, selector = DEFAULT_MARKDOWN_SELECTOR) {
    const scope = rootEl || (typeof document !== 'undefined' ? document : null);
    if (!scope || typeof scope.querySelectorAll !== 'function') return;
    const hasMarked = typeof window !== 'undefined' && window.marked && typeof window.marked.parse === 'function';
    const nodes = (typeof scope.matches === 'function' && scope.matches(selector)) ? [scope] : [];
    scope.querySelectorAll(selector).forEach((n) => nodes.push(n));
    nodes.forEach((el) => {
      const existingMd = el.querySelector('.hvl-chat-markdown');
      if (existingMd && (!hasMarked || el.getAttribute('data-marked-hydrated') === '1')) return;
      const raw = el.getAttribute('data-raw-markdown') || (!existingMd ? (el.textContent || '') : '');
      if (!raw.trim()) return;
      el.setAttribute('data-raw-markdown', raw);
      if (hasMarked) el.setAttribute('data-marked-hydrated', '1');
      el.innerHTML = renderChatMarkdown(raw);
    });
  }

  /** Appends a rendered assistant message bubble (markdown + optional document link + model badge). */
  function appendAssistantChatTurn(chatLog, data = {}, options = {}) {
    if (!chatLog || typeof document === 'undefined') return null;
    const bubble = Object.assign(document.createElement('div'), { className: options.bubbleClass || 'asst-msg-bubble assistant' });
    const spk = Object.assign(document.createElement('div'), { className: options.speakerClass || 'asst-msg-speaker', textContent: options.speakerLabel || 'Assistant' });
    spk.style.color = options.speakerColor || 'var(--status-green)';
    const rawReply = (data && (data.reply || data.error)) || 'Done.';
    const textEl = Object.assign(document.createElement('div'), { className: options.textClass || 'asst-msg-text' });
    textEl.setAttribute('data-raw-markdown', rawReply);
    if (typeof window !== 'undefined' && window.marked && typeof window.marked.parse === 'function') textEl.setAttribute('data-marked-hydrated', '1');
    textEl.innerHTML = renderChatMarkdown(rawReply);
    bubble.append(spk, textEl);
    const openUrl = String((data && (data.open_url || (data.data && data.data.open_url))) || '').trim();
    if (openUrl && (/^https?:\/\//i.test(openUrl) || openUrl.startsWith('/'))) {
      const link = Object.assign(document.createElement('a'), { href: openUrl, target: '_blank', rel: 'noopener noreferrer', className: options.docBtnClass || 'asst-secondary-btn', innerHTML: 'Open Document &nearr;' });
      link.style.cssText = 'display:inline-flex; margin-top:6px;';
      bubble.appendChild(link);
    }
    const badgeText = data && (data.model_badge || data.model_used);
    if (badgeText) bubble.appendChild(Object.assign(document.createElement('div'), { className: options.badgeClass || 'asst-model-badge', textContent: badgeText }));
    chatLog.appendChild(bubble);
    return bubble;
  }

  if (typeof document !== 'undefined' && typeof window !== 'undefined') {
    const runAutoHydrate = (root) => hydrateChatMarkdown(root || document);
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => runAutoHydrate(document));
    else setTimeout(() => runAutoHydrate(document), 0);
    document.addEventListener('htmx:afterSettle', (e) => runAutoHydrate(e.detail && e.detail.elt));
    if (typeof MutationObserver === 'function') {
      let rafPending = false;
      const obs = new MutationObserver(() => {
        if (rafPending) return;
        rafPending = true;
        const schedule = typeof requestAnimationFrame === 'function' ? requestAnimationFrame : (fn) => setTimeout(fn, 16);
        schedule(() => {
          rafPending = false;
          runAutoHydrate(document);
        });
      });
      const attach = () => {
        if (document.body) obs.observe(document.body, { childList: true, subtree: true });
      };
      if (document.body) attach();
      else document.addEventListener('DOMContentLoaded', attach);
    }
  }

  /**
   * Format ISO date string into human friendly relative time (e.g. "Just now", "5m ago").
   */
  function formatRelativeChatTime(isoStr) {
    if (!isoStr) return '';
    try {
      const d = new Date(isoStr.endsWith('Z') ? isoStr : isoStr + 'Z');
      const now = new Date();
      const diffSec = Math.floor((now.getTime() - d.getTime()) / 1000);
      if (isNaN(diffSec) || diffSec < 0) return 'Just now';
      if (diffSec < 60) return 'Just now';
      const diffMin = Math.floor(diffSec / 60);
      if (diffMin < 60) return `${diffMin}m ago`;
      const diffHr = Math.floor(diffMin / 60);
      if (diffHr < 24) return `${diffHr}h ago`;
      const diffDays = Math.floor(diffHr / 24);
      if (diffDays < 7) return `${diffDays}d ago`;
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    } catch {
      return isoStr;
    }
  }

  /**
   * Deterministically scroll a scroll container to align with an element's top edge (with padding).
   */
  function scrollChatToElement(scrollBox, element, topOffset = 12) {
    if (!scrollBox || !element) return;
    try {
      const scrollRect = scrollBox.getBoundingClientRect();
      const elemRect = element.getBoundingClientRect();
      const targetTop = Math.max(0, (elemRect.top - scrollRect.top) + scrollBox.scrollTop - topOffset);
      if (typeof scrollBox.scrollTo === 'function') {
        scrollBox.scrollTo({ top: targetTop, behavior: 'smooth' });
      } else {
        scrollBox.scrollTop = targetTop;
      }
    } catch {
      if (typeof element.offsetTop === 'number') {
        scrollBox.scrollTop = Math.max(0, element.offsetTop - topOffset);
      }
    }
  }

  /**
   * Snap scroll container to bottom with microtask/RAF redundancy.
   */
  function scrollChatToBottom(scrollBox) {
    if (!scrollBox) return;
    scrollBox.scrollTop = scrollBox.scrollHeight;
    if (typeof requestAnimationFrame === 'function') {
      requestAnimationFrame(() => {
        scrollBox.scrollTop = scrollBox.scrollHeight;
      });
    } else {
      setTimeout(() => {
        scrollBox.scrollTop = scrollBox.scrollHeight;
      }, 0);
    }
  }

  /**
   * Mount and manage an animated typing / loading bubble.
   */
  function createTypingIndicator(container, options = {}) {
    if (!container) return null;
    const id = options.id || ('typing-' + Date.now());
    const label = options.initialLabel || 'Thinking...';
    const avatarHtml = options.avatarHtml || '';

    const el = document.createElement('div');
    el.id = id;
    el.className = options.className || 'hvl-typing-indicator';
    el.innerHTML = `
      ${avatarHtml}
      <div class="hvl-typing-dots">
        <span class="hvl-typing-dot"></span>
        <span class="hvl-typing-dot"></span>
        <span class="hvl-typing-dot"></span>
      </div>
      <span class="hvl-typing-label">${escapeHtml(label)}</span>
    `;

    container.appendChild(el);
    const scrollBox = options.scrollBox || container;
    scrollChatToBottom(scrollBox);

    return {
      id: id,
      element: el,
      updateStatus(newLabel) {
        const labelEl = el.querySelector('.hvl-typing-label');
        if (labelEl) labelEl.textContent = newLabel;
      },
      remove() {
        const found = document.getElementById(id);
        if (found) found.remove();
        else el.remove();
      }
    };
  }

  /**
   * Poll an async background job with exponential backoff and 429 rate limit tolerance.
   */
  async function pollChatJob(statusUrlOrFn, options = {}) {
    const maxAttempts = options.maxAttempts || 120;
    let delay = options.initialDelayMs || 450;
    const maxDelay = options.maxDelayMs || 2000;
    const onProgress = options.onProgress || null;

    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      await new Promise(resolve => setTimeout(resolve, delay));
      const url = typeof statusUrlOrFn === 'function' ? statusUrlOrFn() : statusUrlOrFn;
      try {
        const res = await fetch(url);
        if (res.status === 429) {
          // Back off when hit by burst rate limits
          delay = Math.min(maxDelay, delay + 800);
          continue;
        }
        if (!res.ok) {
          if (res.status === 404 && attempt < 3) {
            delay = 500;
            continue;
          }
          throw new Error(`Status check returned ${res.status}`);
        }
        const data = await res.json();
        if (onProgress && typeof onProgress === 'function') {
          onProgress(data, attempt);
        }
        if (data.status === 'completed' || data.status === 'failed' || (data.success && data.status !== 'processing')) {
          return data;
        }
      } catch (err) {
        if (attempt >= maxAttempts - 1) throw err;
      }
      delay = Math.min(maxDelay, Math.floor(delay * 1.25));
    }
    return { success: false, status: 'failed', error: 'AI generation timed out. Please try again.' };
  }

  /**
   * Factory creating a unified Chat Drawer Controller.
   */
  function createChatDrawerController(config) {
    const cfg = {
      messagesContainerId: 'chat-messages',
      scrollContainerId: 'chat-box',
      inputId: 'chat-input',
      submitBtnId: 'chat-submit-btn',
      clearBtnId: 'clear-chat-btn',
      typingLabel: 'Generating response...',
      ...config
    };

    let chatHistory = [];
    let activeConversationId = null;

    function getMessagesEl() {
      return document.getElementById(cfg.messagesContainerId);
    }

    function getScrollBox() {
      const box = getMessagesEl();
      if (!box) return document.getElementById(cfg.scrollContainerId);
      return box.closest('.ff-chat-box, .ai-advisor-messages, .hvl-chat-container') ||
        document.getElementById(cfg.scrollContainerId) ||
        box;
    }

    return {
      getHistory: () => chatHistory,
      setHistory: (hist) => { chatHistory = hist || []; },
      getActiveConversationId: () => activeConversationId,
      setActiveConversationId: (id) => { activeConversationId = id; },
      getMessagesContainer: getMessagesEl,
      getScrollContainer: getScrollBox,
      scrollToBottom: () => scrollChatToBottom(getScrollBox()),
      scrollToElement: (el, offset = 12) => scrollChatToElement(getScrollBox(), el, offset),
      createTypingIndicator: (customLabel) => {
        return createTypingIndicator(getMessagesEl(), {
          initialLabel: customLabel || cfg.typingLabel,
          avatarHtml: cfg.botAvatarHtml || '',
          scrollBox: getScrollBox()
        });
      },
      pollJob: (url, opts = {}) => pollChatJob(url, opts)
    };
  }

  return {
    escapeHtml,
    sanitizeChatHtml,
    renderChatMarkdown,
    hydrateChatMarkdown,
    appendAssistantChatTurn,
    formatRelativeChatTime,
    scrollChatToElement,
    scrollChatToBottom,
    createTypingIndicator,
    pollChatJob,
    createChatDrawerController
  };
}));
