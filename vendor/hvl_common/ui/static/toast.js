/**
 * High Velocity Labs — Shared Layer 0 Toast Notification Controller
 * File: /common/toast.js
 */
(function () {
  'use strict';

  function showToast(message, variant, durationMs) {
    if (!message || typeof document === 'undefined') return null;
    window.__lastToastMsg = String(message);
    window.__lastToastVariant = variant || 'info';

    let container = document.getElementById('hvl-toast-container') || document.getElementById('fo-toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'hvl-toast-container';
      container.style.cssText =
        'position:fixed;bottom:24px;right:24px;z-index:var(--z-toast, 3000);display:flex;flex-direction:column;gap:8px;max-width:440px;pointer-events:none;';
      document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    const isError = variant === 'error' || variant === 'danger';
    const isSuccess = variant === 'success';
    const borderColor = isError
      ? 'var(--status-red)'
      : isSuccess
      ? 'var(--status-green)'
      : 'var(--brand-primary)';

    toast.className = 'hvl-toast';
    toast.style.cssText =
      'pointer-events:auto;display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding:12px 16px;border-radius:var(--radius-md, 10px);background:var(--bg-surface-elevated);color:var(--text-primary);border:1px solid var(--border-bright);border-left:4px solid ' +
      borderColor +
      ';box-shadow:var(--shadow-lg);font-size:0.86rem;line-height:1.45;transition:opacity 0.25s ease;';

    const msgSpan = document.createElement('span');
    msgSpan.className = 'hvl-toast-message';
    msgSpan.textContent = String(message);
    toast.appendChild(msgSpan);

    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'hvl-toast-close';
    closeBtn.setAttribute('aria-label', 'Dismiss notification');
    closeBtn.style.cssText =
      'background:transparent;border:none;color:var(--text-secondary);cursor:pointer;font-size:1.1rem;line-height:1;padding:0 2px;flex-shrink:0;';
    closeBtn.textContent = '×';
    toast.appendChild(closeBtn);

    container.appendChild(toast);

    let autoTimer = null;
    let dismissed = false;

    function dismiss() {
      if (dismissed) return;
      dismissed = true;
      if (autoTimer) {
        clearTimeout(autoTimer);
        autoTimer = null;
      }
      toast.style.opacity = '0';
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
    }

    closeBtn.addEventListener('click', dismiss);
    toast.dismiss = dismiss;

    const isSticky = durationMs === 0 || durationMs === Infinity;
    if (!isSticky) {
      const ttl = typeof durationMs === 'number' && durationMs > 0 ? durationMs : 5500;
      autoTimer = setTimeout(function () {
        toast.style.opacity = '0';
        setTimeout(function () {
          if (toast.parentNode) toast.parentNode.removeChild(toast);
        }, 260);
      }, ttl);
    }

    return toast;
  }

  window.showToast = showToast;
  window.hvlShowToast = showToast;
})();
