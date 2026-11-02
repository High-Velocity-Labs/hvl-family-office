/**
 * High Velocity Labs — Shared Layer 0 Toast Notification Controller
 * File: /common/toast.js (styles & hvl-spin-360 keyframes in /common/components.css)
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
      document.body.appendChild(container);
    }

    const isSticky = durationMs === 0 || durationMs === Infinity || variant === 'progress';
    const toast = document.createElement('div');
    const isError = variant === 'error' || variant === 'danger';
    const isSuccess = variant === 'success';
    const variantCls = isError ? ' hvl-toast-error' : isSuccess ? ' hvl-toast-success' : '';

    toast.className = 'hvl-toast' + variantCls;

    if (isSticky) {
      const spinnerSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      spinnerSvg.setAttribute('class', 'icon hvl-toast-spinner');
      spinnerSvg.setAttribute('width', '16');
      spinnerSvg.setAttribute('height', '16');
      spinnerSvg.setAttribute('aria-hidden', 'true');
      const useEl = document.createElementNS('http://www.w3.org/2000/svg', 'use');
      useEl.setAttribute('href', '/common/icons.svg#icon-shared-sync');
      spinnerSvg.appendChild(useEl);
      toast.appendChild(spinnerSvg);
    }

    const msgSpan = document.createElement('span');
    msgSpan.className = 'hvl-toast-message';
    msgSpan.textContent = String(message);
    toast.appendChild(msgSpan);

    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'hvl-toast-close';
    closeBtn.setAttribute('aria-label', 'Dismiss notification');
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
      if (toast.classList) toast.classList.add('is-dismissing');
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
    }

    closeBtn.addEventListener('click', dismiss);
    toast.dismiss = dismiss;

    if (!isSticky) {
      const ttl = typeof durationMs === 'number' && durationMs > 0 ? durationMs : 5500;
      autoTimer = setTimeout(function () {
        if (toast.classList) toast.classList.add('is-dismissing');
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
