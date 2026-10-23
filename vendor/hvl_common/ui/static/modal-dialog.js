/**
 * Custom Modal Dialog System (Alerts, Confirms, Prompts)
 * Replaces browser-controlled alert/confirm dialogs with theme-styled, accessible modals.
 */

(function () {
    // Preserve native references if needed
    window._nativeAlert = window.alert;
    window._nativeConfirm = window.confirm;
    window._nativePrompt = window.prompt;

    const ICONS = {
        error: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>`,
        success: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>`,
        warning: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>`,
        info: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>`,
        confirm: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>`
    };

    let modalBackdrop = null;
    let modalElements = {};
    let dialogQueue = [];
    let currentDialog = null;
    let previousActiveElement = null;

    function buildModalDOM() {
        if (document.getElementById('custom-modal-backdrop')) {
            modalBackdrop = document.getElementById('custom-modal-backdrop');
            initElementRefs();
            return;
        }

        const backdrop = document.createElement('div');
        backdrop.id = 'custom-modal-backdrop';
        backdrop.className = 'custom-modal-backdrop';
        backdrop.setAttribute('role', 'dialog');
        backdrop.setAttribute('aria-modal', 'true');
        backdrop.setAttribute('aria-labelledby', 'custom-modal-title');
        backdrop.setAttribute('aria-describedby', 'custom-modal-message');

        backdrop.innerHTML = `
            <div class="custom-modal-card" tabindex="-1">
                <button type="button" class="custom-modal-close-btn" id="custom-modal-close-btn" aria-label="Close dialog">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                </button>
                <div class="custom-modal-header">
                    <div class="custom-modal-icon-wrap" id="custom-modal-icon-wrap"></div>
                    <div class="custom-modal-header-text">
                        <h3 class="custom-modal-title" id="custom-modal-title"></h3>
                    </div>
                </div>
                <div class="custom-modal-body">
                    <div class="custom-modal-message" id="custom-modal-message"></div>
                    <div class="custom-modal-input-wrap" id="custom-modal-input-wrap" style="display: none;">
                        <input type="text" class="custom-modal-input" id="custom-modal-input" />
                    </div>
                </div>
                <div class="custom-modal-actions">
                    <button type="button" class="custom-modal-btn custom-modal-btn-cancel" id="custom-modal-cancel-btn">Cancel</button>
                    <button type="button" class="custom-modal-btn custom-modal-btn-primary" id="custom-modal-confirm-btn">OK</button>
                </div>
            </div>
        `;

        document.body.appendChild(backdrop);
        modalBackdrop = backdrop;
        initElementRefs();
        attachEventListeners();
    }

    function initElementRefs() {
        modalElements = {
            card: modalBackdrop.querySelector('.custom-modal-card'),
            closeBtn: modalBackdrop.querySelector('#custom-modal-close-btn'),
            iconWrap: modalBackdrop.querySelector('#custom-modal-icon-wrap'),
            title: modalBackdrop.querySelector('#custom-modal-title'),
            message: modalBackdrop.querySelector('#custom-modal-message'),
            inputWrap: modalBackdrop.querySelector('#custom-modal-input-wrap'),
            input: modalBackdrop.querySelector('#custom-modal-input'),
            cancelBtn: modalBackdrop.querySelector('#custom-modal-cancel-btn'),
            confirmBtn: modalBackdrop.querySelector('#custom-modal-confirm-btn')
        };
    }

    function attachEventListeners() {
        // Backdrop click dismissal
        modalBackdrop.addEventListener('click', (e) => {
            if (e.target === modalBackdrop && currentDialog && currentDialog.closeOnBackdrop !== false) {
                handleDismiss();
            }
        });

        // Close button
        modalElements.closeBtn.addEventListener('click', () => {
            handleDismiss();
        });

        // Cancel button
        modalElements.cancelBtn.addEventListener('click', () => {
            handleDismiss();
        });

        // Confirm button
        modalElements.confirmBtn.addEventListener('click', () => {
            handleConfirm();
        });

        // Keyboard handler
        window.addEventListener('keydown', (e) => {
            if (!currentDialog || !modalBackdrop.classList.contains('is-open')) return;

            if (e.key === 'Escape' && currentDialog.closeOnEscape !== false) {
                e.preventDefault();
                handleDismiss();
            } else if (e.key === 'Enter') {
                // If focus is specifically on cancel button, let Enter cancel it
                if (document.activeElement === modalElements.cancelBtn) {
                    e.preventDefault();
                    handleDismiss();
                } else if (document.activeElement === modalElements.input || document.activeElement === modalElements.confirmBtn || !currentDialog.isPrompt) {
                    e.preventDefault();
                    handleConfirm();
                }
            } else if (e.key === 'Tab') {
                handleFocusTrap(e);
            }
        });
    }

    function handleFocusTrap(e) {
        const focusableSelectors = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
        const focusable = Array.from(modalBackdrop.querySelectorAll(focusableSelectors))
            .filter(el => !el.disabled && el.offsetParent !== null);
        
        if (focusable.length === 0) return;

        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
        }
    }

    function handleDismiss() {
        if (!currentDialog) return;
        const dialog = currentDialog;
        closeDialogModal(() => {
            if (dialog.resolve) {
                if (dialog.isPrompt) dialog.resolve(null);
                else if (dialog.isConfirm) dialog.resolve(false);
                else dialog.resolve(true);
            }
            processNextDialog();
        });
    }

    function handleConfirm() {
        if (!currentDialog) return;
        const dialog = currentDialog;
        let val = true;
        if (dialog.isPrompt) {
            val = modalElements.input.value;
            if (typeof val === 'string') {
                // Strip non-printable ASCII control characters
                val = val.replace(/[\x00-\x1f\x7f]/g, '').trim();
            }
        }
        closeDialogModal(() => {
            if (dialog.resolve) {
                dialog.resolve(val);
            }
            processNextDialog();
        });
    }

    function closeDialogModal(callback) {
        if (!modalBackdrop) return;
        modalBackdrop.classList.remove('is-open');

        // Restore focus
        if (previousActiveElement && typeof previousActiveElement.focus === 'function') {
            try { previousActiveElement.focus(); } catch (_) {}
            previousActiveElement = null;
        }

        setTimeout(() => {
            currentDialog = null;
            if (callback) callback();
        }, 180);
    }

    function processNextDialog() {
        if (dialogQueue.length === 0) return;
        const next = dialogQueue.shift();
        renderDialog(next);
    }

    function renderDialog(dialog) {
        buildModalDOM();
        currentDialog = dialog;
        previousActiveElement = document.activeElement;

        // Set title and message
        modalElements.title.textContent = dialog.title || 'Notice';
        modalElements.message.textContent = dialog.message || '';

        // Configure Icon & Styling Type
        const type = dialog.type || 'info';
        modalElements.iconWrap.className = `custom-modal-icon-wrap type-${type}`;
        modalElements.iconWrap.innerHTML = ICONS[type] || ICONS.info;

        // Prompt input
        if (dialog.isPrompt) {
            modalElements.inputWrap.style.display = 'block';
            modalElements.input.value = dialog.promptValue || '';
            modalElements.input.placeholder = dialog.promptPlaceholder || '';
            if (dialog.maxLength) {
                modalElements.input.maxLength = dialog.maxLength;
            } else {
                modalElements.input.removeAttribute('maxlength');
            }
        } else {
            modalElements.inputWrap.style.display = 'none';
        }

        // Cancel button
        if (dialog.showCancel) {
            modalElements.cancelBtn.style.display = 'inline-flex';
            modalElements.cancelBtn.textContent = dialog.cancelText || 'Cancel';
        } else {
            modalElements.cancelBtn.style.display = 'none';
        }

        // Confirm button
        modalElements.confirmBtn.textContent = dialog.confirmText || (dialog.showCancel ? 'Confirm' : 'OK');
        const variant = dialog.confirmVariant || (type === 'error' ? 'danger' : 'primary');
        modalElements.confirmBtn.className = `custom-modal-btn custom-modal-btn-${variant}`;

        // Show dialog
        modalBackdrop.classList.add('is-open');

        // Focus synchronously within the user gesture call stack so mobile
        // browsers (iOS Safari / Android) open the virtual keyboard immediately
        const applyDialogFocus = () => {
            if (dialog.isPrompt) {
                modalElements.input.focus();
                modalElements.input.select();
                try {
                    modalElements.input.setSelectionRange(0, modalElements.input.value.length);
                } catch (_) { /* ignore if unsupported */ }
            } else if (dialog.showCancel && variant === 'danger') {
                // For dangerous actions, default focus to cancel for safety
                modalElements.cancelBtn.focus();
            } else {
                modalElements.confirmBtn.focus();
            }
        };

        applyDialogFocus();
        requestAnimationFrame(() => {
            if (currentDialog !== dialog) return;
            const targetEl = dialog.isPrompt
                ? modalElements.input
                : (dialog.showCancel && variant === 'danger' ? modalElements.cancelBtn : modalElements.confirmBtn);
            if (document.activeElement !== targetEl) {
                applyDialogFocus();
            }
        });
    }

    function detectTypeFromMessage(msg) {
        if (!msg) return 'info';
        const str = String(msg).toLowerCase();
        if (str.includes('error') || str.includes('failed') || str.includes('failure') || str.includes('issue') || str.includes('denied') || str.includes('invalid')) {
            return 'error';
        }
        if (str.includes('success') || str.includes('successfully') || str.includes('saved') || str.includes('updated') || str.includes('copied')) {
            return 'success';
        }
        if (str.includes('warning') || str.includes('caution') || str.includes('please') || str.includes('confirm') || str.includes('remove') || str.includes('delete')) {
            return 'warning';
        }
        return 'info';
    }

    function detectTitle(type, msg) {
        if (type === 'error') return 'Error';
        if (type === 'success') return 'Success';
        if (type === 'warning') return 'Notice';
        if (type === 'confirm') return 'Confirmation';
        return 'Family Office Notice';
    }

    /**
     * Show a custom styled alert dialog.
     * Can be awaited or called synchronously.
     */
    function showModalAlert(message, options) {
        let opts = {};
        if (typeof options === 'string') {
            opts = { title: options };
        } else if (typeof options === 'object' && options !== null) {
            opts = { ...options };
        }

        const msgString = message !== undefined && message !== null ? String(message) : '';
        const inferredType = opts.type || detectTypeFromMessage(msgString);
        const inferredTitle = opts.title || detectTitle(inferredType, msgString);

        return new Promise((resolve) => {
            const dialog = {
                message: msgString,
                title: inferredTitle,
                type: inferredType,
                showCancel: false,
                confirmText: opts.confirmText || 'OK',
                confirmVariant: opts.confirmVariant || (inferredType === 'error' ? 'danger' : 'primary'),
                closeOnBackdrop: opts.closeOnBackdrop !== false,
                closeOnEscape: opts.closeOnEscape !== false,
                isConfirm: false,
                isPrompt: false,
                resolve
            };

            if (currentDialog) {
                dialogQueue.push(dialog);
            } else {
                renderDialog(dialog);
            }
        });
    }

    /**
     * Show a custom styled confirmation dialog with Confirm and Cancel buttons.
     * Returns Promise<boolean>.
     */
    function showModalConfirm(message, options) {
        let opts = {};
        if (typeof options === 'string') {
            opts = { title: options };
        } else if (typeof options === 'object' && options !== null) {
            opts = { ...options };
        }

        const msgString = message !== undefined && message !== null ? String(message) : '';
        const isDestructive = /delete|remove|clear|purge|sign out|logout/i.test(msgString) || /delete|remove|sign out|logout/i.test(opts.title || '');
        const inferredType = opts.type || (isDestructive ? 'warning' : 'confirm');
        const inferredTitle = opts.title || (isDestructive ? 'Confirm Action' : 'Please Confirm');

        return new Promise((resolve) => {
            const dialog = {
                message: msgString,
                title: inferredTitle,
                type: inferredType,
                showCancel: true,
                cancelText: opts.cancelText || 'Cancel',
                confirmText: opts.confirmText || (isDestructive ? 'Delete' : 'Confirm'),
                confirmVariant: opts.confirmVariant || (isDestructive ? 'danger' : 'primary'),
                closeOnBackdrop: opts.closeOnBackdrop !== false,
                closeOnEscape: opts.closeOnEscape !== false,
                isConfirm: true,
                isPrompt: false,
                resolve
            };

            if (currentDialog) {
                dialogQueue.push(dialog);
            } else {
                renderDialog(dialog);
            }
        });
    }

    /**
     * Show a custom styled prompt dialog with a text input.
     * Returns Promise<string|null>.
     */
    function showModalPrompt(message, defaultValue = '', options = {}) {
        const msgString = message !== undefined && message !== null ? String(message) : '';

        return new Promise((resolve) => {
            const dialog = {
                message: msgString,
                title: options.title || 'Input Required',
                type: options.type || 'info',
                showCancel: true,
                cancelText: options.cancelText || 'Cancel',
                confirmText: options.confirmText || 'OK',
                confirmVariant: options.confirmVariant || 'primary',
                promptValue: defaultValue,
                promptPlaceholder: options.placeholder || '',
                maxLength: options.maxLength || options.maxlength || null,
                closeOnBackdrop: options.closeOnBackdrop !== false,
                closeOnEscape: options.closeOnEscape !== false,
                isConfirm: false,
                isPrompt: true,
                resolve
            };

            if (currentDialog) {
                dialogQueue.push(dialog);
            } else {
                renderDialog(dialog);
            }
        });
    }

    /**
     * Generic DOM modal helper: opens a modal element by ID or reference.
     * Removes `.hidden`, sets `style.display = 'flex'` if previously `'none'`, and locks body scroll.
     */
    function openModal(id) {
        if (typeof document === 'undefined') return null;
        const el = typeof id === 'string' ? document.getElementById(id.replace(/^#/, '')) : id;
        if (!el) return null;
        if (el.classList) {
            el.classList.remove('hidden');
            el.classList.add('open');
        }
        if (el.style && el.style.display === 'none') {
            el.style.display = 'flex';
        }
        if (document.body && document.body.style) {
            document.body.style.overflow = 'hidden';
        }
        return el;
    }

    /**
     * Generic DOM modal helper: closes a modal element by ID or reference.
     * Adds `.hidden`, sets `style.display = 'none'` if inline display was used, and restores body scroll.
     */
    function closeModal(id) {
        if (typeof document === 'undefined') return null;
        const el = typeof id === 'string' ? document.getElementById(id.replace(/^#/, '')) : id;
        if (el) {
            if (el.classList) {
                el.classList.add('hidden');
                el.classList.remove('open');
            }
            if (el.style && (el.style.display === 'flex' || el.style.display === 'block')) {
                el.style.display = 'none';
            }
        }
        if (document.body && document.body.style) {
            document.body.style.overflow = '';
        }
        return el || null;
    }

    // Expose APIs globally
    window.alert = showModalAlert;
    window.showModalAlert = showModalAlert;
    window.showAlertModal = showModalAlert;
    window.showAlert = showModalAlert;

    window.confirm = showModalConfirm;
    window.showModalConfirm = showModalConfirm;
    window.showConfirmModal = showModalConfirm;
    window.showConfirm = showModalConfirm;

    window.prompt = showModalPrompt;
    window.showModalPrompt = showModalPrompt;
    window.showPromptModal = showModalPrompt;
    window.showPrompt = showModalPrompt;

    window.openModal = openModal;
    window.closeModal = closeModal;

    // Build DOM if document is already loaded
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', buildModalDOM);
    } else {
        buildModalDOM();
    }
})();
