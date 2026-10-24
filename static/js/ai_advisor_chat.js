/**
 * AI Financial Advisor - Chat Submission & Message Rendering
 * Handles async job polling, message submission, typing indicators, and Markdown parsing.
 */

async function pollAdvisorJobStatus(jobId, maxAttempts = 120, intervalMs = 600, onProgress = null) {
    if (typeof window.pollChatJob === 'function') {
        return window.pollChatJob(`/api/ai-advisor/jobs/${encodeURIComponent(jobId)}`, {
            maxAttempts,
            initialDelayMs: intervalMs,
            onProgress
        });
    }
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
        await new Promise(resolve => setTimeout(resolve, intervalMs));
        try {
            const pollResp = await fetch(`/api/ai-advisor/jobs/${encodeURIComponent(jobId)}`);
            if (pollResp.status === 429) {
                await new Promise(resolve => setTimeout(resolve, 1500));
                continue;
            }
            if (!pollResp.ok) continue;
            const pollData = await pollResp.json();
            if (onProgress && typeof onProgress === 'function') {
                onProgress(pollData, attempt);
            }
            if (pollData && pollData.status !== 'processing') {
                return pollData;
            }
        } catch (e) {}
    }
    return { success: false, status: 'failed', error: 'Advisor request timed out while processing.' };
}

async function submitAiAdvisorMessage() {
    const textarea = document.getElementById('ai-advisor-input');
    const sendBtn = document.getElementById('btn-submit-ai-advisor');
    if (!textarea) return;

    const message = textarea.value.trim();
    if (!message) return;

    textarea.value = '';
    textarea.style.height = '';
    const charCounter = document.getElementById('advisor-char-counter');
    const maxLen = textarea.maxLength > 0 ? textarea.maxLength : 8000;
    if (charCounter) charCounter.textContent = `0 / ${maxLen}`;

    appendAdvisorMessage('user', message);
    const typingIndicator = appendAdvisorTypingIndicator();
    if (sendBtn) sendBtn.disabled = true;

    try {
        const modelSelect = document.getElementById('advisor-model-select');
        const selectedTier = modelSelect ? modelSelect.value : 'lite';
        const resp = await fetch('/api/ai-advisor/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: message,
                active_tab: currentAdvisorTab,
                conversation_id: activeConversationId || 'new',
                history: advisorChatHistory,
                model_tier: selectedTier
            })
        });

        let data = await resp.json();

        if (resp.ok && data.success && data.status === 'processing' && data.job_id) {
            if (data.conversation_id) {
                activeConversationId = data.conversation_id;
                if (data.conversation_title) activeConversationTitle = data.conversation_title;
                if (typeof updateThreadBarUI === 'function') updateThreadBarUI();
            }
            data = await pollAdvisorJobStatus(data.job_id, 120, 600, (jobData) => {
                if (typingIndicator && jobData && jobData.status_message && typeof typingIndicator.updateStatus === 'function') {
                    typingIndicator.updateStatus(jobData.status_message);
                }
            });
        }

        removeAdvisorTypingIndicator(typingIndicator);

        if (resp.ok && data.success && data.reply) {
            appendAdvisorMessage('bot', data.reply, Boolean(data.demo_mode), Boolean(data.is_fallback), data.fallback_reason, data.model_badge || data.model_used || '');
            advisorChatHistory.push({ role: 'user', content: message });
            advisorChatHistory.push({ role: 'model', content: data.reply });
            if (advisorChatHistory.length > 16) {
                advisorChatHistory = advisorChatHistory.slice(-16);
            }

            if (data.conversation_id) {
                activeConversationId = data.conversation_id;
                if (data.conversation_title) activeConversationTitle = data.conversation_title;
                if (typeof updateThreadBarUI === 'function') updateThreadBarUI();
                if (typeof fetchSavedConversations === 'function') fetchSavedConversations();
            }

            if (Array.isArray(data.follow_up_suggestions) && data.follow_up_suggestions.length > 0 && typeof renderAdvisorSuggestionChips === 'function') {
                renderAdvisorSuggestionChips(data.follow_up_suggestions, `Suggested Follow-ups (${data.follow_up_suggestions.length})`);
            }
        } else {
            const errMsg = data.error || 'Unable to send message.';
            appendAdvisorMessage('bot', `Advisor Error: ${errMsg}`);
            if (typeof window.showModalAlert === 'function') {
                const isLimit = resp.status === 400 || /maximum/i.test(errMsg);
                await window.showModalAlert(errMsg, {
                    title: isLimit ? 'AI Advisor Limit Reached' : 'AI Advisor Error',
                    type: 'error'
                });
            }
        }
    } catch (err) {
        removeAdvisorTypingIndicator(typingIndicator);
        appendAdvisorMessage('bot', `Network error connecting to AI Advisor: ${err.message}`);
        if (typeof window.showModalAlert === 'function') {
            await window.showModalAlert(err.message || 'Unable to send message.', {
                title: 'AI Advisor Error',
                type: 'error'
            });
        }
    } finally {
        if (sendBtn) sendBtn.disabled = false;
        if (textarea) textarea.focus();
    }
}

function appendAdvisorMessage(sender, text, isDemo = false, isFallback = false, fallbackReason = '', modelBadge = '') {
    const container = document.getElementById('ai-advisor-messages');
    if (!container) return;

    const welcomeMsg = document.getElementById('advisor-welcome-msg');
    if (welcomeMsg && sender === 'user' && advisorChatHistory.length === 0) {
        welcomeMsg.remove();
    }

    const isUser = sender === 'user';
    const msgDiv = document.createElement('div');
    msgDiv.className = `advisor-msg ${isUser ? 'advisor-msg-user' : 'advisor-msg-bot'}`;

    const avatarSvgUser = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>';
    const avatarSvgDemo = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>';
    const avatarSvgFallback = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>';
    const avatarSvgBot = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg>';

    const avatar = isUser ? avatarSvgUser : (isDemo ? avatarSvgDemo : (isFallback ? avatarSvgFallback : avatarSvgBot));
    const formattedContent = isUser ? _escapeAdvisorHtml(text).replace(/\n/g, '<br>') : renderAdvisorMarkdown(text);

    const avatarStyle = isDemo
        ? 'style="background: rgba(249, 115, 22, 0.2); color: #F97316; border: 1px solid rgba(249, 115, 22, 0.4);"'
        : (isFallback ? 'style="background: rgba(245, 158, 11, 0.2); color: #F59E0B; border: 1px solid rgba(245, 158, 11, 0.4);"' : '');
    const bodyStyle = isDemo ? 'style="border: 1px solid rgba(249, 115, 22, 0.35); background: rgba(249, 115, 22, 0.08);"' : '';

    const fallbackBanner = (!isUser && isFallback) ? `
        <div class="advisor-fallback-banner" style="display: flex; align-items: flex-start; gap: 6px; padding: 6px 10px; background: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.3); border-radius: 6px; font-size: 0.725rem; color: #F59E0B; margin-bottom: 10px;">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink: 0; margin-top: 2px;"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>
            <span><strong>Rules Fallback:</strong> ${_escapeAdvisorHtml(fallbackReason || 'Gemini free-tier rate limit or offline mode active. Answering from local deterministic calculation engine.')}</span>
        </div>
    ` : '';

    const modelBadgeHtml = (!isUser && modelBadge)
        ? `<div style="margin-top:6px;"><span class="badge badge-blue" style="font-size:0.65rem;padding:1px 6px;">${_escapeAdvisorHtml(modelBadge)}</span></div>`
        : '';

    msgDiv.innerHTML = `
        <div class="advisor-msg-avatar" ${avatarStyle}>${avatar}</div>
        <div class="advisor-msg-body" ${bodyStyle}>
            ${fallbackBanner}
            ${formattedContent}
            ${modelBadgeHtml}
        </div>
    `;

    container.appendChild(msgDiv);
    if (isUser) {
        if (typeof window.scrollChatToBottom === 'function') window.scrollChatToBottom(container);
        else container.scrollTop = container.scrollHeight;
    } else {
        setTimeout(() => {
            if (typeof window.scrollChatToElement === 'function') {
                window.scrollChatToElement(container, msgDiv, 12);
            } else {
                const containerRect = container.getBoundingClientRect();
                const msgRect = msgDiv.getBoundingClientRect();
                const targetScrollTop = Math.max(0, (msgRect.top - containerRect.top) + container.scrollTop - 12);
                if (typeof container.scrollTo === 'function') {
                    container.scrollTo({ top: targetScrollTop, behavior: 'smooth' });
                } else {
                    container.scrollTop = targetScrollTop;
                }
            }
        }, 50);
    }
}

function appendAdvisorTypingIndicator(customLabel) {
    const container = document.getElementById('ai-advisor-messages');
    if (!container) return null;

    if (typeof window.createTypingIndicator === 'function') {
        return window.createTypingIndicator(container, {
            initialLabel: customLabel || 'Thinking...',
            avatarHtml: '<div class="advisor-msg-avatar"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg></div>',
            scrollBox: container
        });
    }

    const id = 'typing-' + Date.now();
    const div = document.createElement('div');
    div.id = id;
    div.className = 'advisor-msg advisor-msg-bot';
    div.innerHTML = `
        <div class="advisor-msg-avatar"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg></div>
        <div class="advisor-msg-body">
            <div class="advisor-typing-indicator">
                <span class="advisor-typing-dot"></span>
                <span class="advisor-typing-dot"></span>
                <span class="advisor-typing-dot"></span>
                <span style="font-size: 0.75rem; color: var(--text-muted); margin-left: 6px;">${_escapeAdvisorHtml(customLabel || 'Thinking...')}</span>
            </div>
        </div>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return {
        id,
        remove: () => div.remove(),
        updateStatus: (lbl) => {
            const span = div.querySelector('span:last-child');
            if (span) span.textContent = lbl;
        }
    };
}

function removeAdvisorTypingIndicator(indicatorOrId) {
    if (!indicatorOrId) return;
    if (typeof indicatorOrId.remove === 'function') {
        indicatorOrId.remove();
        return;
    }
    const el = document.getElementById(indicatorOrId);
    if (el) el.remove();
}

function clearAiAdvisorHistory() {
    advisorChatHistory = [];
    const container = document.getElementById('ai-advisor-messages');
    if (container) {
        container.innerHTML = `
            <div class="advisor-msg advisor-msg-bot" id="advisor-welcome-msg">
                <div class="advisor-msg-avatar"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg></div>
                <div class="advisor-msg-body" id="advisor-welcome-body">
                    ${getWelcomeMessageForTab(currentAdvisorTab)}
                </div>
            </div>
        `;
    }
}

function renderAdvisorMarkdown(md) {
    if (!md) return '';
    if (typeof window.renderChatMarkdown === 'function') {
        return window.renderChatMarkdown(md);
    }
    if (typeof window.marked !== 'undefined' && typeof window.marked.parse === 'function') {
        try {
            window.marked.setOptions({ breaks: true, gfm: true });
            const html = window.marked.parse(md);
            return sanitizeRenderedHtml(html);
        } catch (e) {
            console.warn('Marked parse failed, using fallback:', e);
        }
    }
    return renderFallbackMarkdown(md);
}

function sanitizeRenderedHtml(html) {
    if (!html) return '';
    if (typeof window.sanitizeChatHtml === 'function') {
        return window.sanitizeChatHtml(html);
    }
    return html
        .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
        .replace(/\son\w+="[^"]*"/gi, '')
        .replace(/\son\w+='[^']*'/gi, '')
        .replace(/javascript:[^"']*/gi, '');
}

function renderFallbackMarkdown(md) {
    let out = _escapeAdvisorHtml(md);
    out = out.replace(/^#### (.*$)/gim, '<h5>$1</h5>');
    out = out.replace(/^### (.*$)/gim, '<h4>$1</h4>');
    out = out.replace(/^## (.*$)/gim, '<h3>$1</h3>');
    out = out.replace(/^# (.*$)/gim, '<h2>$1</h2>');
    out = out.replace(/^\> (.*$)/gim, '<blockquote>$1</blockquote>');
    out = out.replace(/\*\*(.*?)\*\*/gim, '<strong>$1</strong>');
    out = out.replace(/\*(.*?)\*/gim, '<em>$1</em>');
    out = out.replace(/^[\*\-] (.*$)/gim, '<li>$1</li>');
    out = out.replace(/(<li>.*<\/li>)/gims, '<ul>$1</ul>');
    out = out.replace(/<\/ul>\s*<ul>/gim, '');
    out = out.replace(/^\d+\.\s+(.*$)/gim, '<li>$1</li>');
    out = out.replace(/^---$/gim, '<hr>');
    out = out.replace(/\n\n+/g, '</p><p>');
    out = `<p>${out}</p>`;
    out = out.replace(/<p><\/p>/g, '');
    out = out.replace(/<p>(<h[2345]>.*?<\/h[2345]>)<\/p>/g, '$1');
    out = out.replace(/<p>(<ul>.*?<\/ul>)<\/p>/g, '$1');
    out = out.replace(/<p>(<ol>.*?<\/ol>)<\/p>/g, '$1');
    out = out.replace(/<p>(<hr.*?>)<\/p>/g, '$1');
    out = out.replace(/<p>(<blockquote.*?>.*?<\/blockquote>)<\/p>/g, '$1');
    return out;
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        pollAdvisorJobStatus,
        submitAiAdvisorMessage,
        appendAdvisorMessage,
        appendAdvisorTypingIndicator,
        removeAdvisorTypingIndicator,
        clearAiAdvisorHistory,
        renderAdvisorMarkdown,
        sanitizeRenderedHtml,
        renderFallbackMarkdown
    });
}
