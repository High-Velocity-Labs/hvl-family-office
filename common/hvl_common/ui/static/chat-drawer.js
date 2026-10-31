/**
 * High Velocity Labs Shared AI Chat Drawer Core Engine (hvl_common)
 * Unified clientside orchestration for Gemini AI chat drawers, markdown hydration,
 * deterministic scroll geometry, job polling, and hands-free HvlVoiceAdvisor.
 */
(function (root, factory) {
  const lib = factory();
  if (typeof exports === 'object' && typeof module !== 'undefined') {
    module.exports = lib;
  }
  const target = (typeof window !== 'undefined') ? window : root;
  if (target) {
    Object.assign(target, {
      hvlChatDrawer: lib,
      renderChatMarkdown: lib.renderChatMarkdown,
      hydrateChatMarkdown: lib.hydrateChatMarkdown,
      sanitizeChatHtml: lib.sanitizeChatHtml,
      formatRelativeChatTime: lib.formatRelativeChatTime,
      scrollChatToElement: lib.scrollChatToElement,
      scrollChatToBottom: lib.scrollChatToBottom,
      createTypingIndicator: lib.createTypingIndicator,
      pollChatJob: lib.pollChatJob,
      createChatDrawerController: lib.createChatDrawerController,
      HvlVoiceAdvisor: lib.HvlVoiceAdvisor,
    });
  }
}(typeof globalThis !== 'undefined' ? globalThis : typeof window !== 'undefined' ? window : this, function () {
  'use strict';

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

  const ALLOWED_MD_TAGS = new Set([
    'p', 'br', 'strong', 'b', 'em', 'i', 'code', 'pre', 'ul', 'ol', 'li',
    'blockquote', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a', 'table', 'thead',
    'tbody', 'tr', 'th', 'td', 'hr', 'span', 'del'
  ]);

  function _isSafeHref(rawHref) {
    const raw = String(rawHref || '').trim();
    if (!raw) return false;
    const decoded = raw
      .replace(/&#x([0-9a-f]+);?/gi, (_m, hex) => String.fromCharCode(parseInt(hex, 16)))
      .replace(/&#([0-9]+);?/g, (_m, dec) => String.fromCharCode(parseInt(dec, 10)))
      .replace(/&(colon|tab|newline);/gi, ':')
      .replace(/[\u0000-\u0020]+/g, '');
    if (/^(?:javascript|vbscript|data):/i.test(decoded)) return false;
    return /^(?:https?:\/\/|mailto:|\/(?!\/)|#)/i.test(raw);
  }

  function sanitizeChatHtml(html) {
    if (!html) return '';
    // Every tag kept is rebuilt by this function and parked as a placeholder; then any '<' or '>' still left
    // (an unclosed '<details ontoggle=...' with no '>', a stray '<!--') is escaped, so nothing the regexes missed
    // can be completed into a live tag by the markup around it. Entities from marked stay as they are.
    const kept = [];
    const park = (tagHtml) => `\u0000${kept.push(tagHtml) - 1}\u0000`;
    return String(html)
      .replace(/\u0000/g, '')
      .replace(/<!--[\s\S]*?-->/g, '')
      .replace(/<(script|style|iframe|object|embed|svg|math|form|textarea)\b[^>]*>[\s\S]*?<\/\1>/gi, '')
      .replace(/<\/?([a-zA-Z0-9-]+)\b([^>]*)>/g, (full, rawTag, rawAttrs) => {
        const tag = String(rawTag).toLowerCase();
        if (!ALLOWED_MD_TAGS.has(tag)) return '';
        if (full.startsWith('</')) return park(`</${tag}>`);
        if (tag === 'a') {
          const hm = /\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>"']+))/i.exec(rawAttrs || '');
          const hrefVal = hm ? (hm[1] ?? hm[2] ?? hm[3] ?? '') : '';
          return park(
            _isSafeHref(hrefVal)
              ? `<a href="${escapeHtml(hrefVal.trim())}" target="_blank" rel="noopener noreferrer">`
              : '<a>'
          );
        }
        if (tag === 'code' || tag === 'span') {
          const cm = /\bclass\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>"']+))/i.exec(rawAttrs || '');
          const cls = (cm ? (cm[1] ?? cm[2] ?? cm[3] ?? '') : '').replace(/[^a-zA-Z0-9_\-\s]/g, '').trim();
          if (cls) return park(`<${tag} class="${cls}">`);
        }
        return park(`<${tag}>`);
      })
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\u0000(\d+)\u0000/g, (_m, i) => kept[Number(i)]);
  }

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

  const DEFAULT_MARKDOWN_SELECTOR = '[data-chat-markdown]';

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

  function formatRelativeChatTime(isoStr) {
    if (!isoStr) return '';
    try {
      const d = new Date(isoStr.endsWith('Z') ? isoStr : isoStr + 'Z');
      const diffSec = Math.floor((Date.now() - d.getTime()) / 1000);
      if (isNaN(diffSec) || diffSec < 60) return 'Just now';
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

  function scrollChatToElement(scrollBox, element, topOffset = 12) {
    if (!scrollBox || !element) return;
    try {
      const scrollRect = scrollBox.getBoundingClientRect();
      const elemRect = element.getBoundingClientRect();
      const targetTop = Math.max(0, (elemRect.top - scrollRect.top) + scrollBox.scrollTop - topOffset);
      if (typeof scrollBox.scrollTo === 'function') scrollBox.scrollTo({ top: targetTop, behavior: 'smooth' });
      else scrollBox.scrollTop = targetTop;
    } catch {
      if (typeof element.offsetTop === 'number') scrollBox.scrollTop = Math.max(0, element.offsetTop - topOffset);
    }
  }

  function scrollChatToBottom(scrollBox) {
    if (!scrollBox) return;
    scrollBox.scrollTop = scrollBox.scrollHeight;
    const sync = () => { scrollBox.scrollTop = scrollBox.scrollHeight; };
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(sync);
    else setTimeout(sync, 0);
  }

  function createTypingIndicator(container, options = {}) {
    if (!container) return null;
    const id = options.id || ('typing-' + Date.now());
    const label = options.initialLabel || 'Thinking...';
    const avatarHtml = options.avatarHtml || '';
    const el = document.createElement('div');
    el.id = id;
    el.className = options.className || 'hvl-typing-indicator';
    el.innerHTML = `${avatarHtml}<div class="hvl-typing-dots"><span class="hvl-typing-dot"></span><span class="hvl-typing-dot"></span><span class="hvl-typing-dot"></span></div><span class="hvl-typing-label">${escapeHtml(label)}</span>`;
    container.appendChild(el);
    scrollChatToBottom(options.scrollBox || container);
    return {
      id,
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

  async function pollChatJob(statusUrlOrFn, options = {}) {
    const maxAttempts = options.maxAttempts || 120;
    let delay = options.initialDelayMs || 450;
    const maxDelay = options.maxDelayMs || 2000;
    const onProgress = options.onProgress || null;

    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      await new Promise(resolve => setTimeout(resolve, delay));
      const url = typeof statusUrlOrFn === 'function' ? statusUrlOrFn() : statusUrlOrFn;
      try {
        const res = await fetch(url, { skipReactiveMorph: true });
        if (res.status === 429) {
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
        if (typeof onProgress === 'function') onProgress(data, attempt);
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
    const getMessagesEl = () => document.getElementById(cfg.messagesContainerId);
    const getScrollBox = () => {
      const box = getMessagesEl();
      if (!box) return document.getElementById(cfg.scrollContainerId);
      return box.closest('.ff-chat-box, .ai-advisor-messages, .hvl-chat-container') ||
        document.getElementById(cfg.scrollContainerId) || box;
    };
    return {
      getHistory: () => chatHistory,
      setHistory: (hist) => { chatHistory = hist || []; },
      getActiveConversationId: () => activeConversationId,
      setActiveConversationId: (id) => { activeConversationId = id; },
      getMessagesContainer: getMessagesEl,
      getScrollContainer: getScrollBox,
      scrollToBottom: () => scrollChatToBottom(getScrollBox()),
      scrollToElement: (el, offset = 12) => scrollChatToElement(getScrollBox(), el, offset),
      createTypingIndicator: (customLabel) => createTypingIndicator(getMessagesEl(), {
        initialLabel: customLabel || cfg.typingLabel,
        avatarHtml: cfg.botAvatarHtml || '',
        scrollBox: getScrollBox()
      }),
      pollJob: (url, opts = {}) => pollChatJob(url, opts)
    };
  }

  const SILENCE_DEBOUNCE_MS = 2000;

  function _setVoiceBtnState(btnEl, listening) {
    if (!btnEl) return;
    btnEl.classList.toggle('is-listening', Boolean(listening));
    const lbl = btnEl.querySelector('[data-voice-label]');
    if (lbl) lbl.textContent = listening ? 'Listening...' : 'Voice';
  }

  const HvlVoiceAdvisor = {
    SILENCE_DEBOUNCE_MS,
    _active: false,
    _rec: null,
    _btnEl: null,
    _timer: null,

    isVoiceActive() {
      return Boolean(this._active);
    },

    consumeVoiceActive() {
      const active = Boolean(this._active);
      this._active = false;
      return active;
    },

    extractSpokenText(raw) {
      if (!raw) return '';
      const m = /<voice_reply>\s*([\s\S]*?)\s*<\/voice_reply>/i.exec(String(raw));
      const base = m ? m[1] : String(raw);
      return base
        .replace(/```[\s\S]*?```/g, ' ')
        .replace(/<[^>]+>/g, ' ')
        .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
        .replace(/https?:\/\/\S+/g, '')
        .replace(/[*_~`#>-]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
    },

    speak(text, opts = {}) {
      if (typeof window === 'undefined' || !window.speechSynthesis) return false;
      const clean = this.extractSpokenText(text);
      if (!clean) return false;
      try {
        window.speechSynthesis.cancel();
        const utter = new window.SpeechSynthesisUtterance(clean);
        utter.rate = opts.rate || 1.03;
        utter.pitch = opts.pitch || 1.0;
        window.speechSynthesis.speak(utter);
        return true;
      } catch {
        return false;
      }
    },

    stopSpeaking() {
      if (typeof window !== 'undefined' && window.speechSynthesis) {
        try { window.speechSynthesis.cancel(); } catch { /* ignore */ }
      }
    },

    startListening({ inputEl, submitBtn, btnEl, onTranscript }) {
      const SR = typeof window !== 'undefined' && (window.SpeechRecognition || window.webkitSpeechRecognition);
      if (!SR) return false;
      this.stopListening(false);
      this.stopSpeaking();
      const rec = new SR();
      rec.continuous = true;
      rec.interimResults = true;
      rec.lang = 'en-US';
      let finalBuf = '';
      let interimBuf = '';
      const resetDebounce = () => {
        if (this._timer) clearTimeout(this._timer);
        this._timer = setTimeout(() => {
          const combined = (finalBuf + ' ' + interimBuf).replace(/\s+/g, ' ').trim();
          this.stopListening(Boolean(combined));
          if (combined) {
            if (inputEl) inputEl.value = combined;
            if (typeof onTranscript === 'function') onTranscript(combined);
            else if (submitBtn && submitBtn.form && typeof submitBtn.form.requestSubmit === 'function') submitBtn.form.requestSubmit();
            else if (submitBtn && typeof submitBtn.click === 'function') submitBtn.click();
          }
        }, SILENCE_DEBOUNCE_MS);
      };
      rec.onresult = (ev) => {
        interimBuf = '';
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          const t = ev.results[i][0].transcript;
          if (ev.results[i].isFinal) finalBuf += ' ' + t;
          else interimBuf += t;
        }
        const live = (finalBuf + ' ' + interimBuf).replace(/\s+/g, ' ').trim();
        if (inputEl && live) inputEl.value = live;
        resetDebounce();
      };
      rec.onend = () => { _setVoiceBtnState(btnEl, false); };
      this._rec = rec;
      this._btnEl = btnEl || null;
      this._active = true;
      _setVoiceBtnState(btnEl, true);
      try {
        rec.start();
        return true;
      } catch {
        _setVoiceBtnState(btnEl, false);
        return false;
      }
    },

    stopListening(keepActive = false) {
      if (this._timer) {
        clearTimeout(this._timer);
        this._timer = null;
      }
      if (this._rec) {
        try { this._rec.stop(); } catch { /* ignore */ }
        this._rec = null;
      }
      if (this._btnEl) {
        _setVoiceBtnState(this._btnEl, false);
        this._btnEl = null;
      }
      if (!keepActive) this._active = false;
    },

    attachAll(root) {
      const scope = root || (typeof document !== 'undefined' ? document : null);
      if (!scope || typeof scope.querySelectorAll !== 'function') return;
      const composerSel = '.ai-advisor-drawer, .ops-advisor-drawer, #chat-form, [data-hvl-chat-form]';
      scope.querySelectorAll(composerSel).forEach((container) => {
        if (container.querySelector('[data-hvl-voice-btn], [data-voice-btn]')) return;
        const submitBtn = container.querySelector('button[type="submit"], [data-chat-submit]');
        if (!submitBtn || !submitBtn.parentElement) return;
        const micBtn = document.createElement('button');
        micBtn.type = 'button';
        micBtn.className = 'btn btn-ghost btn-icon';
        micBtn.setAttribute('data-hvl-voice-btn', '1');
        micBtn.setAttribute('aria-label', 'Voice input');
        micBtn.innerHTML = '<svg class="hvl-icon" width="16" height="16"><use href="/common/icons.svg#icon-mic"></use></svg>';
        submitBtn.parentElement.insertBefore(micBtn, submitBtn);
      });
      scope.querySelectorAll('[data-hvl-voice-btn], [data-voice-btn]').forEach((btn) => {
        if (btn.getAttribute('data-hvl-voice-bound') === '1') return;
        btn.setAttribute('data-hvl-voice-bound', '1');
        const container = btn.closest(composerSel + ', form, .hvl-chat-composer') || document;
        const inputEl = container.querySelector('textarea, input[type="text"]');
        if (inputEl && inputEl.getAttribute('data-hvl-voice-input-bound') !== '1') {
          inputEl.setAttribute('data-hvl-voice-input-bound', '1');
          inputEl.addEventListener('input', () => { if (!this._rec) this._active = false; });
        }
        btn.addEventListener('click', (e) => {
          e.preventDefault();
          const curInput = container.querySelector('textarea, input[type="text"]');
          const submitBtn = container.querySelector('button[type="submit"], [data-chat-submit]');
          if (btn.classList.contains('is-listening')) {
            this.stopListening(false);
            _setVoiceBtnState(btn, false);
          } else {
            this.startListening({ inputEl: curInput, submitBtn, btnEl: btn });
          }
        });
      });
    }
  };

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => HvlVoiceAdvisor.attachAll(document));
    else setTimeout(() => HvlVoiceAdvisor.attachAll(document), 0);
  }

  return {
    SILENCE_DEBOUNCE_MS, HvlVoiceAdvisor, escapeHtml, sanitizeChatHtml,
    renderChatMarkdown, hydrateChatMarkdown,
    formatRelativeChatTime, scrollChatToElement, scrollChatToBottom,
    createTypingIndicator, pollChatJob, createChatDrawerController
  };
}));
