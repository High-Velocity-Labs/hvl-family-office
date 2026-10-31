/**
 * AI Financial Advisor - Chat Submission & Message Rendering
 * Handles async job polling, message submission and typing indicators; bubbles are server-rendered fragments.
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

    await appendAdvisorMessage('user', { user: message });
    const typingIndicator = appendAdvisorTypingIndicator();
    if (sendBtn) sendBtn.disabled = true;

    try {
        const modelSelect = document.getElementById('advisor-model-select');
        const selectedTier = modelSelect ? modelSelect.value : 'lite';
        const voiceMode = Boolean(window.HvlVoiceAdvisor && window.HvlVoiceAdvisor.isVoiceActive());
        const resp = await fetch('/api/ai-advisor/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: message,
                active_tab: AdvisorState.tab,
                conversation_id: AdvisorState.conversationId || 'new',
                history: AdvisorState.chatHistory,
                model_tier: selectedTier,
                voice_mode: voiceMode
            })
        });

        let data = await resp.json();
        const jobId = data.job_id || '';

        if (resp.ok && data.success && data.status === 'processing' && data.job_id) {
            if (data.conversation_id) {
                AdvisorState.conversationId = data.conversation_id;
                if (data.conversation_title) AdvisorState.conversationTitle = data.conversation_title;
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
            await appendAdvisorMessage('bot', data.demo_mode ? { demo_for: message } : { job: jobId });
            if (data.lifecycle_action === 'compact') {
                AdvisorState.chatHistory = [{ role: 'model', content: data.reply }];
            } else if (data.lifecycle_action === 'carryover' || data.lifecycle_action === 'new_conversation') {
                AdvisorState.chatHistory = [{ role: 'model', content: data.reply }];
                if (data.conversation_id) AdvisorState.conversationId = data.conversation_id;
            } else {
                AdvisorState.chatHistory.push({ role: 'user', content: message });
                AdvisorState.chatHistory.push({ role: 'model', content: data.reply });
                if (AdvisorState.chatHistory.length > 16) {
                    AdvisorState.chatHistory = AdvisorState.chatHistory.slice(-16);
                }
            }

            if (data.conversation_id) {
                AdvisorState.conversationId = data.conversation_id;
                if (data.conversation_title) AdvisorState.conversationTitle = data.conversation_title;
                if (typeof updateThreadBarUI === 'function') updateThreadBarUI();
                if (typeof fetchSavedConversations === 'function') fetchSavedConversations();
            }

            if (data.voice_reply && window.HvlVoiceAdvisor && (data.voice_mode || window.HvlVoiceAdvisor.isVoiceActive())) {
                window.HvlVoiceAdvisor.speak(data.voice_reply);
            }

            if (Array.isArray(data.follow_up_suggestions) && data.follow_up_suggestions.length > 0 && typeof renderAdvisorSuggestionChips === 'function') {
                renderAdvisorSuggestionChips(data.follow_up_suggestions, `Suggested Follow-ups (${data.follow_up_suggestions.length})`);
            }
        } else {
            const errMsg = data.error || 'Unable to send message.';
            await appendAdvisorMessage('bot', { notice: `Advisor Error: ${errMsg}` });
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
        await appendAdvisorMessage('bot', { notice: `Network error connecting to AI Advisor: ${err.message}` });
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

/** Appends a server-rendered bubble. `source`: { user } | { job } | { demo_for } | { notice }, see AdvisorFragments. */
async function appendAdvisorMessage(sender, source) {
    const container = document.getElementById('ai-advisor-messages');
    if (!container) return;

    const welcomeMsg = document.getElementById('advisor-welcome-msg');
    if (welcomeMsg && sender === 'user' && AdvisorState.chatHistory.length === 0) {
        welcomeMsg.remove();
    }

    const msgDiv = await AdvisorFragments.appendMessage(source);
    if (!msgDiv) return;

    if (sender === 'user') {
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

/** Shows the shared typing indicator; its avatar markup comes from the drawer's #advisor-typing-avatar template. */
function appendAdvisorTypingIndicator(customLabel) {
    const container = document.getElementById('ai-advisor-messages');
    if (!container) return null;
    const avatar = document.getElementById('advisor-typing-avatar');
    return window.createTypingIndicator(container, {
        initialLabel: customLabel || 'Thinking...',
        avatarHtml: avatar ? avatar.innerHTML : '',
        scrollBox: container
    });
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
    AdvisorState.chatHistory = [];
    return AdvisorFragments.showWelcome(AdvisorState.tab);
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        pollAdvisorJobStatus,
        submitAiAdvisorMessage,
        appendAdvisorMessage,
        appendAdvisorTypingIndicator,
        removeAdvisorTypingIndicator,
        clearAiAdvisorHistory
    });
}
