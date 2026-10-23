/**
 * High Velocity Labs Shared Multimodal Chat Attachments Controller (hvl_common)
 * File: /common/chat-attachments.js
 *
 * Provides shared client-side attachment primitives across HVL AI chat drawers:
 * - '+' popover menu (Take Photo, Upload Photo/Screenshot, Upload PDF/Document)
 * - Client-side <canvas> downscaler (<= 1536px analysis JPEG + <= 96px encrypted thumbnail)
 * - Queued thumbnail chip tray with 30-day auto-wipe privacy caption
 * - Clipboard paste and drag-and-drop file handlers
 * - Message bubble thumbnail and expired-pill HTML renderer
 */
(function (root, factory) {
  const lib = factory();
  if (typeof exports === 'object' && typeof module !== 'undefined') module.exports = lib;
  const target = (typeof window !== 'undefined') ? window : root;
  if (target) {
    target.hvlChatAttachments = lib;
    target.initChatAttachments = lib.initChatAttachments;
    target.renderChatAttachmentsHtml = lib.renderChatAttachmentsHtml;
  }
}(typeof globalThis !== 'undefined' ? globalThis : typeof window !== 'undefined' ? window : this, function () {
  'use strict';

  const MAX_ATTACHMENTS = 4;
  const MAX_ANALYSIS_EDGE = 1536;
  const MAX_THUMB_EDGE = 96;
  const MAX_THUMB_CHARS = 24000;
  const TRAY_CAPTION = 'Encrypted thumbnail saved in chat history \u00b7 Auto-wiped after 30 days or when chat is deleted';
  const MENU_CAPTION = 'Encrypted thumbnails auto-wipe after 30 days or when chat is deleted.';

  function _esc(str) {
    if (typeof window !== 'undefined' && typeof window.escapeHtml === 'function') {
      return window.escapeHtml(str);
    }
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function _notifyWarn(msg) {
    if (typeof window !== 'undefined' && typeof window.showToast === 'function') window.showToast(msg, 'warning');
    else console.warn('[hvlChatAttachments]', msg);
  }

  function _isMobileCaptureDevice() {
    const ua = (typeof navigator !== 'undefined' && navigator.userAgent) ? navigator.userAgent : '';
    return /Android|iPhone|iPad|iPod|Mobile/i.test(ua) || Boolean(typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(pointer: coarse)').matches);
  }

  function _stripDataUrlPrefix(dataUrl) {
    const str = String(dataUrl || '');
    const idx = str.indexOf(';base64,');
    return idx >= 0 ? str.slice(idx + 8) : str;
  }

  function _readFileAsDataUrl(file) {
    return new Promise((resolve, reject) => {
      if (typeof FileReader === 'undefined') return resolve('');
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ''));
      reader.onerror = () => reject(new Error('Failed to read file'));
      reader.readAsDataURL(file);
    });
  }

  function _scaleCanvasDataUrl(img, maxEdge, quality) {
    if (typeof document === 'undefined') return '';
    const w = img.naturalWidth || img.width || 0;
    const h = img.naturalHeight || img.height || 0;
    if (!w || !h) return '';
    const scale = Math.min(1, maxEdge / Math.max(w, h));
    const targetW = Math.max(1, Math.round(w * scale));
    const targetH = Math.max(1, Math.round(h * scale));
    const canvas = document.createElement('canvas');
    canvas.width = targetW;
    canvas.height = targetH;
    const ctx = typeof canvas.getContext === 'function' ? canvas.getContext('2d') : null;
    if (!ctx || typeof ctx.drawImage !== 'function' || typeof canvas.toDataURL !== 'function') {
      return '';
    }
    ctx.drawImage(img, 0, 0, targetW, targetH);
    const out = canvas.toDataURL('image/jpeg', quality);
    return (out && out.startsWith('data:image/')) ? out : '';
  }

  function _processImageDataUrl(rawDataUrl, origMime, origSize) {
    return new Promise((resolve) => {
      const fallback = () => {
        const b64 = _stripDataUrlPrefix(rawDataUrl);
        resolve({
          mime_type: origMime || 'image/jpeg',
          data_b64: b64,
          thumb_data_url: rawDataUrl.length <= MAX_THUMB_CHARS ? rawDataUrl : '',
          size_bytes: origSize || Math.round((b64.length * 3) / 4),
          kind: 'image'
        });
      };

      if (typeof Image === 'undefined' || !rawDataUrl.startsWith('data:image/')) {
        fallback();
        return;
      }

      let settled = false;
      const timer = setTimeout(fallback, 150);
      const img = new Image();
      img.onload = () => {
        clearTimeout(timer);
        if (settled) return;
        settled = true;
        try {
          const fullUrl = _scaleCanvasDataUrl(img, MAX_ANALYSIS_EDGE, 0.84) || rawDataUrl;
          const thumbUrl = _scaleCanvasDataUrl(img, MAX_THUMB_EDGE, 0.65) || (fullUrl.length <= MAX_THUMB_CHARS ? fullUrl : '');
          const b64 = _stripDataUrlPrefix(fullUrl);
          resolve({
            mime_type: fullUrl.startsWith('data:image/jpeg') ? 'image/jpeg' : (origMime || 'image/jpeg'),
            data_b64: b64,
            thumb_data_url: thumbUrl.length <= MAX_THUMB_CHARS ? thumbUrl : '',
            size_bytes: Math.round((b64.length * 3) / 4) || origSize || 0,
            kind: 'image'
          });
        } catch {
          fallback();
        }
      };
      img.onerror = () => {
        clearTimeout(timer);
        if (!settled) {
          settled = true;
          fallback();
        }
      };
      img.src = rawDataUrl;
    });
  }

  /** Renders safe HTML for a message bubble's attachments (active thumbnails, expired pills, or PDF chips). */
  function renderChatAttachmentsHtml(attachments) {
    if (!Array.isArray(attachments) || attachments.length === 0) return '';
    const cards = attachments.map((att) => {
      if (!att || typeof att !== 'object') return '';
      const name = _esc(att.name || att.filename || 'attachment');
      const mime = String(att.mime_type || '').toLowerCase();
      const isImage = att.kind === 'image' || mime.startsWith('image/');
      if (att.expired && isImage) {
        return `<div class="hvl-msg-attach-expired">[Image expired (30d policy): ${name}]</div>`;
      }
      const thumb = String(att.thumb_data_url || '');
      if (isImage && thumb.startsWith('data:image/')) {
        return `<div class="hvl-msg-attach-card"><img src="${_esc(thumb)}" alt="${name}" class="hvl-msg-attach-thumb" loading="lazy"><span class="hvl-msg-attach-name">${name}</span></div>`;
      }
      return `<div class="hvl-msg-attach-doc"><svg class="hvl-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg><span class="hvl-msg-attach-name">${name}</span></div>`;
    }).filter(Boolean);

    return cards.length ? `<div class="hvl-msg-attachments">${cards.join('')}</div>` : '';
  }

  /**
   * Initializes multimodal attachment UI (+ popover, tray, file inputs, paste/drop) on a chat form.
   */
  function initChatAttachments(options = {}) {
    if (typeof document === 'undefined') return null;
    const form = options.formElement || document.querySelector(options.formSelector || '#asst-chat-form');
    if (!form) return null;
    if (form.__hvlAttachmentsController) return form.__hvlAttachmentsController;

    const inputSel = options.inputSelector || '#asst-chat-input';
    const inputEl = options.inputElement || form.querySelector(inputSel) || document.querySelector(inputSel);
    const maxCount = options.maxAttachments || MAX_ATTACHMENTS;
    let pending = [];

    let tray = form.parentElement ? form.parentElement.querySelector('.hvl-attach-tray') : null;
    if (!tray) {
      tray = document.createElement('div');
      tray.className = 'hvl-attach-tray';
      tray.style.display = 'none';
      if (form.parentElement) form.parentElement.insertBefore(tray, form);
      else form.prepend(tray);
    }

    let wrap = form.querySelector('.hvl-attach-wrap');
    if (!wrap) {
      const showCamera = Boolean(options.showCameraOnDesktop || _isMobileCaptureDevice());
      const btnTitle = showCamera ? 'Add photos, camera capture, or PDF' : 'Add photos, screenshots, or documents';
      const camStyle = showCamera ? '' : ' style="display:none;"';
      wrap = document.createElement('div');
      wrap.className = 'hvl-attach-wrap';
      wrap.innerHTML = [
        `<button type="button" class="hvl-attach-btn" aria-label="Add photos or files" title="${btnTitle}">+</button>`,
        '<div class="hvl-attach-menu" role="menu">',
        `  <button type="button" class="hvl-attach-menu-item hvl-attach-camera-only" data-attach-mode="camera"${camStyle}>Take Photo</button>`,
        '  <button type="button" class="hvl-attach-menu-item" data-attach-mode="photo">Upload Photo or Screenshot</button>',
        '  <button type="button" class="hvl-attach-menu-item" data-attach-mode="doc">Upload PDF or Document</button>',
        `  <div class="hvl-attach-menu-footer">${_esc(MENU_CAPTION)}</div>`,
        '</div>',
        '<input type="file" class="hvl-attach-file-input" data-input-mode="camera" accept="image/*" capture="environment">',
        '<input type="file" class="hvl-attach-file-input" data-input-mode="photo" accept="image/png,image/jpeg,image/webp,image/gif" multiple>',
        '<input type="file" class="hvl-attach-file-input" data-input-mode="doc" accept="application/pdf,text/csv,text/plain" multiple>'
      ].join('\n');
      if (inputEl && inputEl.parentElement === form) form.insertBefore(wrap, inputEl);
      else form.prepend(wrap);
    }

    const plusBtn = wrap.querySelector('.hvl-attach-btn');
    const menuEl = wrap.querySelector('.hvl-attach-menu');

    function renderTray() {
      if (pending.length === 0) {
        tray.style.display = 'none';
        tray.innerHTML = '';
        return;
      }
      tray.style.display = 'flex';
      const chipsHtml = pending.map((att, idx) => {
        const badge = att.kind === 'image' ? 'IMG' : 'DOC';
        const thumbImg = (att.kind === 'image' && att.thumb_data_url)
          ? `<img src="${_esc(att.thumb_data_url)}" alt="${_esc(att.name)}" class="hvl-attach-chip-thumb">`
          : `<span class="hvl-attach-chip-badge">${badge}</span>`;
        return `<div class="hvl-attach-chip" data-attach-idx="${idx}">${thumbImg}<span class="hvl-attach-chip-name">${_esc(att.name)}</span><button type="button" class="hvl-attach-chip-remove" data-remove-idx="${idx}" aria-label="Remove attachment">\u00d7</button></div>`;
      }).join('');
      tray.innerHTML = `<div class="hvl-attach-chip-list">${chipsHtml}</div><div class="hvl-attach-tray-footer">${_esc(TRAY_CAPTION)}</div>`;
    }

    tray.addEventListener('click', (e) => {
      const rmBtn = e.target.closest('[data-remove-idx]');
      if (!rmBtn) return;
      const idx = parseInt(rmBtn.getAttribute('data-remove-idx'), 10);
      if (!isNaN(idx) && idx >= 0 && idx < pending.length) {
        pending.splice(idx, 1);
        renderTray();
      }
    });

    function addAttachmentObject(att) {
      if (!att || typeof att !== 'object') return false;
      if (pending.length >= maxCount) {
        _notifyWarn(`Maximum ${maxCount} attachments per message.`);
        return false;
      }
      const mime = String(att.mime_type || att.type || 'application/octet-stream').toLowerCase();
      const rawB64 = _stripDataUrlPrefix(att.data_b64 || att.data_url || '');
      pending.push({
        name: String(att.name || att.filename || 'attachment'),
        mime_type: mime,
        data_b64: rawB64,
        thumb_data_url: String(att.thumb_data_url || ''),
        size_bytes: Number(att.size_bytes || Math.round((rawB64.length * 3) / 4) || 0),
        kind: att.kind || (mime.startsWith('image/') ? 'image' : 'document')
      });
      renderTray();
      if (typeof options.onChange === 'function') options.onChange(pending.slice());
      return true;
    }

    async function processSelectedFiles(fileList) {
      const added = [];
      for (const file of Array.from(fileList || [])) {
        if (pending.length >= maxCount) {
          _notifyWarn(`Maximum ${maxCount} attachments per message.`);
          break;
        }
        const mime = String(file.type || '').toLowerCase();
        const dataUrl = await _readFileAsDataUrl(file);
        if (mime.startsWith('image/')) {
          const processed = await _processImageDataUrl(dataUrl, mime, file.size);
          const obj = { name: file.name || 'photo.jpg', ...processed };
          if (addAttachmentObject(obj)) added.push(obj);
        } else {
          const b64 = _stripDataUrlPrefix(dataUrl);
          const obj = {
            name: file.name || 'document.pdf',
            mime_type: mime || 'application/pdf',
            data_b64: b64,
            thumb_data_url: '',
            size_bytes: file.size || Math.round((b64.length * 3) / 4),
            kind: 'document'
          };
          if (addAttachmentObject(obj)) added.push(obj);
        }
      }
      return added;
    }

    if (plusBtn && menuEl) {
      plusBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        menuEl.classList.toggle('open');
      });
      wrap.querySelectorAll('[data-attach-mode]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const mode = btn.getAttribute('data-attach-mode');
          menuEl.classList.remove('open');
          const fileInput = wrap.querySelector(`input[data-input-mode="${mode}"]`);
          if (fileInput) fileInput.click();
        });
      });
      wrap.querySelectorAll('.hvl-attach-file-input').forEach((inp) => {
        inp.addEventListener('change', () => {
          if (inp.files && inp.files.length > 0) {
            processSelectedFiles(inp.files);
            inp.value = '';
          }
        });
      });
      document.addEventListener('click', (e) => {
        if (!wrap.contains(e.target)) menuEl.classList.remove('open');
      });
    }

    if (inputEl) {
      inputEl.addEventListener('paste', (e) => {
        const files = e.clipboardData && e.clipboardData.files;
        if (files && files.length > 0) {
          e.preventDefault();
          processSelectedFiles(files);
        }
      });
    }
    form.addEventListener('dragover', (e) => e.preventDefault());
    form.addEventListener('drop', (e) => {
      const files = e.dataTransfer && e.dataTransfer.files;
      if (files && files.length > 0) {
        e.preventDefault();
        processSelectedFiles(files);
      }
    });

    const controller = {
      getPendingAttachments: () => pending.slice(),
      clearPendingAttachments: () => {
        pending = [];
        renderTray();
        if (typeof options.onChange === 'function') options.onChange([]);
      },
      addAttachmentObject,
      processSelectedFiles
    };
    form.__hvlAttachmentsController = controller;
    return controller;
  }

  return { initChatAttachments, renderChatAttachmentsHtml };
}));
