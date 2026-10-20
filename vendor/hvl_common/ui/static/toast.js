/**
 * High Velocity Labs — Shared Layer 0 Toast Notification Controller
 * File: /common/toast.js
 */
(function () {
  'use strict';

  function showToast(message, variant, durationMs) {
    if (!message || typeof document === 'undefined') return;
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
      'pointer-events:auto;padding:12px 16px;border-radius:var(--radius-md, 10px);background:var(--bg-surface-elevated);color:var(--text-primary);border:1px solid var(--border-bright);border-left:4px solid ' +
      borderColor +
      ';box-shadow:var(--shadow-lg);font-size:0.86rem;line-height:1.45;transition:opacity 0.25s ease;';
    toast.textContent = String(message);
    container.appendChild(toast);

    const ttl = typeof durationMs === 'number' && durationMs > 0 ? durationMs : 5500;
    setTimeout(function () {
      toast.style.opacity = '0';
      setTimeout(function () {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
      }, 260);
    }, ttl);
  }

  window.showToast = showToast;
  window.hvlShowToast = showToast;
})();
