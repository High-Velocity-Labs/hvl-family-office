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
      .replace(/javascript:/gi, 'blocked:');
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
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong class="ff-text-strong">$1</strong>');
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    html = html.replace(/\n\n+/g, '</p><p>');
    html = html.replace(/\n/g, '<br>');
    return `<div class="hvl-chat-markdown"><p>${html}</p></div>`;
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
    formatRelativeChatTime,
    scrollChatToElement,
    scrollChatToBottom,
    createTypingIndicator,
    pollChatJob,
    createChatDrawerController
  };
}));
