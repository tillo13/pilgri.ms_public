/**
 * PilgrimBot — Codebase Q&A chat interface
 * Bug-aware mode: when launched from bug tracker (?bug=<id>), shows
 * action bar + smart follow-ups so QA can investigate and update bugs.
 */

(function() {
    'use strict';

    const USER_NAME = window.PB_USER_NAME || 'Captain';
    const BUG_ID = window.PB_BUG_ID || null;
    const BUG_NAME = window.PB_BUG_NAME || '';
    let currentChatId = null;
    let isStreaming = false;
    let lastResponseText = '';

    const messagesEl = document.getElementById('pbMessages');
    const inputEl = document.getElementById('pbInput');
    const sendBtn = document.getElementById('pbSend');
    const welcomeEl = document.getElementById('pbWelcome');
    const chatListEl = document.getElementById('pbChatList');
    const newChatBtn = document.getElementById('pbNewChat');
    const bugBarEl = document.getElementById('pbBugBar');

    // === Bug mode bar ===

    if (BUG_ID && bugBarEl) {
        bugBarEl.style.display = '';
        bugBarEl.innerHTML =
            '<div class="pb-bug-bar-inner">' +
                '<a href="/admin/bugs" class="pb-bug-back">&larr; Bug Tracker</a>' +
                '<span class="pb-bug-tag">Analyzing Bug #' + BUG_ID + ': ' + escapeHtml(BUG_NAME) + '</span>' +
                '<div class="pb-bug-actions">' +
                    '<button class="pb-bug-action" id="pbSaveToBug" title="Save PilgrimBot analysis as a comment on this bug">Save to Bug</button>' +
                    '<button class="pb-bug-action pb-bug-action-new" id="pbNewBug" title="Create a NEW bug from this conversation">+ New Bug</button>' +
                    '<button class="pb-bug-action pb-bug-action-dev" id="pbPassToDev" title="Move bug to Todo status for dev to pick up">Pass to Dev</button>' +
                '</div>' +
            '</div>';
        document.getElementById('pbSaveToBug').addEventListener('click', saveToBug);
        document.getElementById('pbPassToDev').addEventListener('click', passToDev);
        document.getElementById('pbNewBug').addEventListener('click', createBugFromChat);
    }

    function saveToBug() {
        if (!lastResponseText) { showToast('No PilgrimBot response to save yet.', 'error'); return; }
        const btn = document.getElementById('pbSaveToBug');
        btn.disabled = true;
        btn.textContent = 'Saving...';
        fetch('/api/admin/bugs/' + BUG_ID + '/comments', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({author: 'PilgrimBot', body: lastResponseText})
        }).then(r => r.json()).then(data => {
            btn.textContent = data.success ? 'Saved!' : 'Error';
            setTimeout(() => { btn.textContent = 'Save to Bug'; btn.disabled = false; }, 2000);
        }).catch(() => {
            btn.textContent = 'Error';
            setTimeout(() => { btn.textContent = 'Save to Bug'; btn.disabled = false; }, 2000);
        });
    }

    function passToDev() {
        if (!window.confirm('Move Bug #' + BUG_ID + ' to "Todo" for dev to pick up?')) return;
        const btn = document.getElementById('pbPassToDev');
        btn.disabled = true;
        btn.textContent = 'Updating...';
        // Update status to Todo
        fetch('/api/admin/bugs/' + BUG_ID, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({status: 'Todo', changed_by: USER_NAME})
        }).then(r => r.json()).then(data => {
            if (data.success) {
                // Also add a comment noting the handoff
                const note = 'Passed to dev for action. ' +
                    (lastResponseText ? 'PilgrimBot analysis saved above.' : '');
                fetch('/api/admin/bugs/' + BUG_ID + '/comments', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({author: USER_NAME, body: note})
                });
                btn.textContent = 'Passed to Dev!';
                btn.classList.add('pb-bug-action-done');
            } else {
                btn.textContent = 'Error';
            }
            setTimeout(() => {
                btn.textContent = 'Pass to Dev';
                btn.disabled = false;
                btn.classList.remove('pb-bug-action-done');
            }, 3000);
        }).catch(() => {
            btn.textContent = 'Error';
            setTimeout(() => { btn.textContent = 'Pass to Dev'; btn.disabled = false; }, 2000);
        });
    }

    function createBugFromChat() {
        if (!currentChatId) { showToast('Start a conversation first.', 'error'); return; }
        showNewBugModal(document.getElementById('pbNewBug'));
    }

    // === New Bug Modal ===
    function showNewBugModal(triggerBtn, responseText) {
        // Remove existing modal if any
        var old = document.getElementById('pbNewBugModal');
        if (old) old.remove();

        var overlay = document.createElement('div');
        overlay.id = 'pbNewBugModal';
        overlay.style.cssText = 'position:fixed;inset:0;z-index:99999;background:rgba(0,0,0,0.7);display:flex;align-items:center;justify-content:center;';
        overlay.innerHTML =
            '<div style="background:var(--bg-primary);border:1px solid var(--border-default);border-radius:12px;padding:24px;max-width:500px;width:90%;max-height:80vh;overflow-y:auto;">' +
                '<h3 style="margin:0 0 16px;color:var(--text-primary);">Create New Bug</h3>' +
                '<p style="font-size:13px;color:var(--text-secondary);margin-bottom:16px;">Creates a bug based on <strong>this specific response only</strong> (not the full conversation).</p>' +
                '<label style="font-size:12px;color:var(--text-muted);text-transform:uppercase;letter-spacing:1px;">Bug Title (optional)</label>' +
                '<input type="text" id="pbNewBugTitle" placeholder="Leave blank for auto-generated title" style="width:100%;padding:10px;margin:6px 0 12px;background:var(--bg-secondary);border:1px solid var(--border-default);border-radius:8px;color:var(--text-primary);font-size:14px;">' +
                '<label style="font-size:12px;color:var(--text-muted);text-transform:uppercase;letter-spacing:1px;">Priority</label>' +
                '<select id="pbNewBugPriority" style="width:100%;padding:10px;margin:6px 0 12px;background:var(--bg-secondary);border:1px solid var(--border-default);border-radius:8px;color:var(--text-primary);font-size:14px;">' +
                    '<option value="P1">P1 — Critical</option>' +
                    '<option value="P2" selected>P2 — Important</option>' +
                    '<option value="P3">P3 — Nice to have</option>' +
                '</select>' +
                (BUG_ID ? '<p style="font-size:12px;color:var(--text-muted);margin-bottom:16px;">Original bug #' + BUG_ID + ' will stay as-is. This creates a separate bug.</p>' : '') +
                '<div style="display:flex;gap:8px;justify-content:flex-end;">' +
                    '<button id="pbNewBugCancel" style="padding:8px 20px;background:var(--bg-secondary);border:1px solid var(--border-default);border-radius:8px;color:var(--text-secondary);cursor:pointer;">Cancel</button>' +
                    '<button id="pbNewBugSubmit" style="padding:8px 20px;background:var(--color-success);border:none;border-radius:8px;color:white;font-weight:600;cursor:pointer;">Create Bug</button>' +
                '</div>' +
            '</div>';
        document.body.appendChild(overlay);

        // Focus title input
        document.getElementById('pbNewBugTitle').focus();

        // Cancel
        document.getElementById('pbNewBugCancel').addEventListener('click', function() { overlay.remove(); });
        overlay.addEventListener('click', function(e) { if (e.target === overlay) overlay.remove(); });

        // Submit
        document.getElementById('pbNewBugSubmit').addEventListener('click', function() {
            var submitBtn = this;
            var title = document.getElementById('pbNewBugTitle').value.trim();
            var priority = document.getElementById('pbNewBugPriority').value;
            submitBtn.disabled = true;
            submitBtn.textContent = 'Creating...';

            fetch('/api/pilgrimbot/create_bug', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({response_text: responseText, chat_id: currentChatId, title: title, priority: priority})
            }).then(function(r) { return r.json(); }).then(function(data) {
                if (data.success) {
                    overlay.remove();
                    showToast('Bug #' + data.bug_id + ' created!', 'success');
                    appendMessage('assistant', '**New Bug Created:** [#' + data.bug_id + ' — ' + (data.title || title) + '](/admin/bugs?open=' + data.bug_id + ')\n\n*Searching for related bugs in the background.*');
                    if (triggerBtn) {
                        triggerBtn.textContent = 'Bug #' + data.bug_id + ' Created!';
                        setTimeout(function() { triggerBtn.textContent = '+ New Bug from This'; triggerBtn.disabled = false; }, 4000);
                    }
                } else {
                    submitBtn.textContent = data.error || 'Error creating bug';
                    submitBtn.disabled = false;
                }
            }).catch(function() {
                submitBtn.textContent = 'Error — try again';
                submitBtn.disabled = false;
            });
        });

        // Enter to submit
        document.getElementById('pbNewBugTitle').addEventListener('keydown', function(e) {
            if (e.key === 'Enter') { e.preventDefault(); document.getElementById('pbNewBugSubmit').click(); }
        });
    }

    // === Utilities ===

    function escapeHtml(str) {
        if (!str) return '';
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }

    function parseMarkdown(text) {
        if (!text) return '';
        if (typeof marked !== 'undefined') {
            marked.setOptions({breaks: true, gfm: true, headerIds: false, mangle: false});
            return marked.parse(text);
        }
        let h = escapeHtml(text);
        h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        h = h.replace(/`([^`]+)`/g, '<code>$1</code>');
        h = h.replace(/\n/g, '<br>');
        return h;
    }

    function formatTime(date) {
        return new Date(date).toLocaleTimeString('en-US', {
            hour: 'numeric', minute: '2-digit', hour12: true
        });
    }

    // === Smart follow-up suggestions ===

    function getSmartSuggestions() {
        if (!BUG_ID) return [];
        const resp = (lastResponseText || '').toLowerCase();
        const suggestions = [];

        // Always offer test steps — QA's core job
        suggestions.push({label: 'Write test steps for QA', q: 'Write detailed QA test steps to verify this bug is fixed. Be specific about what to click, type, and expect to see.'});

        // If response mentions files/code, offer deeper dive
        if (resp.match(/\.py|\.js|\.html|\.css|function|class |def /)) {
            suggestions.push({label: 'Show me the exact code', q: 'Show me the exact code that needs to change. Give file paths, line numbers, and what the fix looks like.'});
        } else {
            suggestions.push({label: 'What files need to change?', q: 'What specific files and functions need to change to fix this? Give me exact file paths and line numbers.'});
        }

        // If response mentions other bugs or duplicates
        if (resp.match(/related|duplicate|similar|#\d+/)) {
            suggestions.push({label: 'Should we merge these bugs?', q: 'Based on the related bugs you found, should any be merged or closed as duplicates? Which ones and why?'});
        } else {
            suggestions.push({label: 'Find related bugs', q: 'Are there other bugs in the tracker that might be related or duplicates of this one?'});
        }

        // Summarize for handoff to dev
        suggestions.push({label: 'Summarize for dev handoff', q: 'Write a concise dev handoff summary: root cause, suggested fix approach, files to change, and QA test steps. Keep it actionable.'});

        return suggestions;
    }

    function renderSuggestions() {
        // Remove existing suggestions
        const existing = document.querySelector('.pb-suggestions');
        if (existing) existing.remove();
        const suggestions = getSmartSuggestions();
        if (!suggestions.length) return;

        const wrap = document.createElement('div');
        wrap.className = 'pb-suggestions';
        suggestions.forEach(s => {
            const btn = document.createElement('button');
            btn.className = 'pb-suggestion-btn';
            btn.textContent = s.label;
            btn.addEventListener('click', () => {
                wrap.remove();
                sendMessage(s.q);
            });
            wrap.appendChild(btn);
        });
        messagesEl.appendChild(wrap);
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    // === Message rendering ===

    function appendMessage(role, text, timestamp) {
        const div = document.createElement('div');
        div.className = 'pb-msg pb-msg-' + role;
        const name = role === 'user' ? USER_NAME : 'PilgrimBot';
        const time = timestamp ? formatTime(timestamp) : formatTime(new Date());
        const content = parseMarkdown(text);

        div.innerHTML =
            '<div class="pb-msg-header">' + escapeHtml(name) +
            ' <span class="pb-msg-time">' + time + '</span></div>' +
            '<div class="pb-msg-content">' + content + '</div>';

        // Footer: context-aware button
        if (role === 'assistant' && text) {
            addFooterToEl(div, text);
        }

        messagesEl.appendChild(div);
        messagesEl.scrollTop = messagesEl.scrollHeight;
        return div;
    }

    let _typingTimer = null;

    function showTyping() {
        const div = document.createElement('div');
        div.className = 'pb-typing';
        div.id = 'pbTyping';
        div.innerHTML =
            '<div class="pb-typing-header">PilgrimBot</div>' +
            '<div class="pb-typing-body">' +
                '<div class="pb-typing-dots"><span></span><span></span><span></span></div>' +
                '<span class="pb-typing-timer">0s</span>' +
            '</div>';
        messagesEl.appendChild(div);
        messagesEl.scrollTop = messagesEl.scrollHeight;
        // Live ticking timer
        const startTime = Date.now();
        const timerEl = div.querySelector('.pb-typing-timer');
        _typingTimer = setInterval(() => {
            if (timerEl) timerEl.textContent = Math.round((Date.now() - startTime) / 1000) + 's';
        }, 1000);
        return div;
    }

    function removeTyping(el) {
        if (_typingTimer) { clearInterval(_typingTimer); _typingTimer = null; }
        if (el && el.parentNode) el.remove();
    }

    // === Send message ===

    function sendMessage(text) {
        if (!text || isStreaming) return;
        text = text.trim();
        if (!text && !pendingImageUrl) return;

        if (welcomeEl) welcomeEl.style.display = 'none';
        const existingSugg = document.querySelector('.pb-suggestions');
        if (existingSugg) existingSugg.remove();

        // Show user message with image if attached
        var displayText = text;
        var imageUrl = pendingImageUrl;
        if (imageUrl) {
            displayText = (text ? text + '\n\n' : '') + '![screenshot](' + imageUrl + ')';
        }
        appendMessage('user', displayText);
        inputEl.value = '';
        inputEl.style.height = 'auto';
        // Clear image preview
        if (imagePreviewEl) { imagePreviewEl.remove(); imagePreviewEl = null; }
        pendingImageUrl = null;
        isStreaming = true;
        sendBtn.disabled = true;

        const typingEl = showTyping();
        let gotFirstDelta = false;
        const sendStartTime = Date.now();

        // Timeout updates typing indicator label — NEVER kills the stream
        const TIMEOUT_MS = 30000;
        let timeoutCount = 0;
        let streamTimeout = null;

        function resetStreamTimeout() {
            clearTimeout(streamTimeout);
            streamTimeout = setTimeout(() => {
                if (isStreaming && typingEl && typingEl.parentNode) {
                    timeoutCount++;
                    let header = typingEl.querySelector('.pb-typing-header');
                    if (header) {
                        header.textContent = timeoutCount === 1
                            ? 'Still working...' : 'Deep diving into the code...';
                    }
                    resetStreamTimeout();
                }
            }, TIMEOUT_MS);
        }
        resetStreamTimeout();

        let contentEl = null;
        let fullText = '';
        let assistantEl = null;

        // === Event queue: stagger status/tool_call renders so they appear one-at-a-time ===
        const eventQueue = [];
        let draining = false;
        let lastEventRenderTime = 0;
        const MIN_GAP_MS = 350;

        function ensureAssistantEl() {
            removeTyping(typingEl);
            if (!assistantEl) {
                assistantEl = document.createElement('div');
                assistantEl.className = 'pb-msg pb-msg-assistant';
                assistantEl.innerHTML =
                    '<div class="pb-msg-header">PilgrimBot <span class="pb-msg-time">' +
                    formatTime(new Date()) + '</span></div>' +
                    '<div class="pb-tool-calls"></div>' +
                    '<div class="pb-msg-content"></div>';
                messagesEl.appendChild(assistantEl);
                contentEl = assistantEl.querySelector('.pb-msg-content');
            }
        }

        function renderStatusEvent(data) {
            ensureAssistantEl();
            let toolArea = assistantEl.querySelector('.pb-tool-calls');
            if (!toolArea) return;
            // Remove old dots
            let oldDots = toolArea.querySelector('.pb-tool-dots');
            if (oldDots) oldDots.remove();
            // Create status/tool line
            let el = document.createElement('div');
            if (data.type === 'status') {
                el.className = 'pb-tool-line pb-tool-status';
                el.textContent = data.message;
            } else if (data.type === 'phase') {
                el.className = 'pb-phase-divider';
                el.textContent = data.label;
            } else {
                el.className = 'pb-tool-line' + (data.found ? '' : ' pb-tool-miss');
                el.textContent = (data.found ? 'Read ' : 'Not found: ') + data.file;
            }
            toolArea.appendChild(el);
            // Always re-add pulsing dots below
            let dots = document.createElement('div');
            dots.className = 'pb-tool-dots';
            dots.innerHTML = '<span class="pb-typing-dots"><span></span><span></span><span></span></span>';
            toolArea.appendChild(dots);
            messagesEl.scrollTop = messagesEl.scrollHeight;
            resetStreamTimeout();
        }

        function drainQueue() {
            if (!eventQueue.length) { draining = false; return; }
            let elapsed = Date.now() - lastEventRenderTime;
            if (elapsed < MIN_GAP_MS) {
                setTimeout(drainQueue, MIN_GAP_MS - elapsed);
                return;
            }
            renderStatusEvent(eventQueue.shift());
            lastEventRenderTime = Date.now();
            if (eventQueue.length) setTimeout(drainQueue, MIN_GAP_MS);
            else draining = false;
        }

        let _lastStatusText = '';
        function queueEvent(data) {
            // Deduplicate consecutive identical status messages
            var text = data.message || data.label || data.file || '';
            if (data.type === 'status' && text === _lastStatusText) return;
            _lastStatusText = text;
            eventQueue.push(data);
            if (!draining) { draining = true; drainQueue(); }
        }

        function flushQueue() {
            while (eventQueue.length) renderStatusEvent(eventQueue.shift());
            draining = false;
        }

        function removeDots() {
            if (assistantEl) {
                let d = assistantEl.querySelector('.pb-tool-dots');
                if (d) d.remove();
            }
        }

        // === SSE fetch ===
        fetch('/api/pilgrimbot/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({message: text, chat_id: currentChatId, stream: true, bug_mode: !!BUG_ID, image_url: imageUrl || undefined})
        }).then(response => {
            if (!response.ok) throw new Error('Server error: ' + response.status);
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            function processChunk() {
                reader.read().then(({done, value}) => {
                    if (done) {
                        flushQueue();
                        clearTimeout(streamTimeout);
                        removeDots();
                        if (contentEl) contentEl.innerHTML = parseMarkdown(fullText);
                        addFooterToEl(assistantEl, fullText, Date.now() - sendStartTime);
                        finishStream(fullText);
                        return;
                    }
                    buffer += decoder.decode(value, {stream: true});
                    const lines = buffer.split('\n');
                    buffer = lines.pop();

                    for (const line of lines) {
                        if (!line.startsWith('data: ')) continue;
                        try {
                            const data = JSON.parse(line.slice(6));
                            if (data.type === 'start' && data.chat_id) {
                                currentChatId = data.chat_id;
                                resetStreamTimeout();

                            } else if (data.type === 'status' || data.type === 'tool_call' || data.type === 'phase') {
                                queueEvent(data);

                            } else if (data.type === 'delta' && data.text) {
                                // Flush pending status events immediately, then stream text
                                flushQueue();
                                if (!gotFirstDelta) {
                                    gotFirstDelta = true;
                                    clearTimeout(streamTimeout);
                                    removeTyping(typingEl);
                                    removeDots();
                                    ensureAssistantEl();
                                    contentEl = assistantEl.querySelector('.pb-msg-content');
                                }
                                fullText += data.text;
                                contentEl.innerHTML = parseMarkdown(fullText);
                                messagesEl.scrollTop = messagesEl.scrollHeight;

                            } else if (data.type === 'stop') {
                                flushQueue();
                                clearTimeout(streamTimeout);
                                removeTyping(typingEl);
                                removeDots();
                                if (contentEl) contentEl.innerHTML = parseMarkdown(fullText);
                                addFooterToEl(assistantEl, fullText, Date.now() - sendStartTime);
                                finishStream(fullText);
                                return;

                            } else if (data.type === 'error') {
                                flushQueue();
                                clearTimeout(streamTimeout);
                                removeTyping(typingEl);
                                removeDots();
                                // Render error INLINE — never as a separate message
                                ensureAssistantEl();
                                if (fullText) {
                                    // Partial response exists — add subtle note in tool area
                                    let toolArea = assistantEl.querySelector('.pb-tool-calls');
                                    if (toolArea) {
                                        let note = document.createElement('div');
                                        note.className = 'pb-tool-line pb-tool-error';
                                        note.textContent = data.message || 'Deep dive interrupted';
                                        toolArea.appendChild(note);
                                    }
                                } else {
                                    // No response at all — show in content area
                                    if (contentEl) contentEl.innerHTML = '<span class="pb-error-text">' + escapeHtml(data.message || 'Something went wrong.') + '</span>';
                                }
                                finishStream(fullText);
                                return;
                            }
                        } catch (e) { console.warn('PilgrimBot SSE parse error:', e, line); }
                    }
                    processChunk();
                }).catch(err => {
                    console.error('PilgrimBot stream read error:', err);
                    flushQueue();
                    clearTimeout(streamTimeout);
                    removeTyping(typingEl);
                    removeDots();
                    if (!fullText) appendMessage('assistant', 'Connection lost. Please try again.');
                    finishStream(fullText);
                });
            }
            processChunk();
        }).catch(err => {
            console.error('PilgrimBot fetch error:', err);
            clearTimeout(streamTimeout);
            removeTyping(typingEl);
            appendMessage('assistant', 'Connection error. Please try again.');
            finishStream('');
        });
    }

    function addFooterToEl(el, text, elapsedMs) {
        if (!el || !text) return;
        const footer = document.createElement('div');
        footer.className = 'pb-msg-footer';

        if (BUG_ID) {
            // Bug mode: save to existing bug OR create new bug from this response
            footer.innerHTML =
                '<button class="pb-feedback-link pb-save-link">Save to Bug #' + BUG_ID + '</button>' +
                '<button class="pb-feedback-link pb-new-bug-link" style="margin-left: 8px; color: var(--color-success);">+ New Bug from This</button>';
            footer.querySelector('.pb-save-link').addEventListener('click', function() {
                const btn = this;
                btn.disabled = true;
                btn.textContent = 'Saving...';
                fetch('/api/admin/bugs/' + BUG_ID + '/comments', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({author: 'PilgrimBot', body: text})
                }).then(r => r.json()).then(data => {
                    btn.textContent = data.success ? 'Saved!' : 'Error saving';
                }).catch(() => { btn.textContent = 'Error saving'; });
            });
            footer.querySelector('.pb-new-bug-link').addEventListener('click', function() {
                if (!currentChatId) { showToast('Start a conversation first.', 'error'); return; }
                showNewBugModal(this, text);
            });
        } else {
            // Normal mode: create new bug from conversation
            footer.innerHTML =
                '<button class="pb-feedback-link pb-create-bug-link">+ Create Bug from Chat</button>';
            footer.querySelector('.pb-create-bug-link').addEventListener('click', function() {
                if (!currentChatId) { showToast('Start a conversation first.', 'error'); return; }
                showNewBugModal(this, text);
            });
        }
        // Response time badge
        if (elapsedMs) {
            var secs = (elapsedMs / 1000).toFixed(1);
            var timeSpan = document.createElement('span');
            timeSpan.className = 'pb-response-time';
            timeSpan.textContent = secs + 's';
            footer.appendChild(timeSpan);
        }
        el.appendChild(footer);
    }

    function finishStream(text) {
        isStreaming = false;
        sendBtn.disabled = false;
        inputEl.focus();
        lastResponseText = text;
        refreshChatList();

        // Auto-save first PilgrimBot response to bug as comment
        if (window.PB_BUG_ID && text && window._pbAutoSave !== false) {
            fetch('/api/admin/bugs/' + window.PB_BUG_ID + '/comments', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({author: 'PilgrimBot', body: text})
            });
            window._pbAutoSave = false; // only auto-save the first response
        }

        // Show smart follow-up suggestions in bug mode
        if (BUG_ID && text) {
            renderSuggestions();
        }
    }

    // === Chat list ===

    function hideChat(chatId, el) {
        if (!confirm('Hide this conversation? It won\'t appear in the list anymore.')) return;
        fetch('/api/pilgrimbot/hide', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({chat_id: chatId})
        }).then(r => r.json()).then(data => {
            if (data.success) {
                el.remove();
                if (currentChatId === chatId) startNewChat();
            }
        }).catch(() => {});
    }

    function buildChatItem(chat) {
        const div = document.createElement('div');
        div.className = 'pb-chat-item' + (chat.chat_id === currentChatId ? ' active' : '');
        div.dataset.chatId = chat.chat_id;
        div.innerHTML =
            '<button class="pb-chat-hide" title="Hide conversation">&times;</button>' +
            '<div class="pb-chat-title">' + escapeHtml(chat.title) + '</div>' +
            '<div class="pb-chat-meta">' + chat.message_count + ' messages</div>';
        div.querySelector('.pb-chat-hide').addEventListener('click', function(e) {
            e.stopPropagation();
            hideChat(chat.chat_id, div);
        });
        div.addEventListener('click', () => loadChat(chat.chat_id));
        return div;
    }

    let _refreshTimer = null;
    function refreshChatList() {
        // Debounce — avoid spamming API on rapid messages
        clearTimeout(_refreshTimer);
        _refreshTimer = setTimeout(() => {
            fetch('/api/pilgrimbot/chats')
                .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
                .then(data => {
                    if (!data.success) return;
                    chatListEl.innerHTML = '';
                    data.chats.forEach(chat => {
                        chatListEl.appendChild(buildChatItem(chat));
                    });
                }).catch(() => {});
        }, 500);
    }

    function loadChat(chatId) {
        currentChatId = chatId;
        messagesEl.innerHTML = '';
        if (welcomeEl) welcomeEl.style.display = 'none';

        fetch('/api/pilgrimbot/history?chat_id=' + chatId)
            .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
            .then(data => {
                if (data.success && data.messages) {
                    data.messages.forEach(m => appendMessage(m.role, m.content, m.created_at));
                }
                document.querySelectorAll('.pb-chat-item').forEach(el => {
                    el.classList.toggle('active', el.dataset.chatId === chatId);
                });
            }).catch(() => {});
    }

    function startNewChat() {
        currentChatId = null;
        messagesEl.innerHTML = '';
        if (welcomeEl) {
            welcomeEl.style.display = '';
            messagesEl.appendChild(welcomeEl);
        }
        document.querySelectorAll('.pb-chat-item').forEach(el => el.classList.remove('active'));
        inputEl.focus();
    }

    // === Paste screenshot support ===
    var pendingImageUrl = null;
    var imagePreviewEl = null;

    function showImagePreview(url) {
        pendingImageUrl = url;
        if (imagePreviewEl) imagePreviewEl.remove();
        imagePreviewEl = document.createElement('div');
        imagePreviewEl.style.cssText = 'display:flex;align-items:center;gap:8px;padding:6px 10px;background:var(--bg-secondary);border:1px solid var(--border-default);border-radius:8px;margin-bottom:6px;';
        imagePreviewEl.innerHTML =
            '<img src="' + url + '" style="height:48px;border-radius:4px;border:1px solid var(--border-default);">' +
            '<span style="font-size:12px;color:var(--text-secondary);flex:1;">Screenshot attached</span>' +
            '<button style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:16px;" title="Remove">&times;</button>';
        imagePreviewEl.querySelector('button').addEventListener('click', function() {
            pendingImageUrl = null;
            imagePreviewEl.remove();
            imagePreviewEl = null;
        });
        inputEl.parentNode.insertBefore(imagePreviewEl, inputEl);
    }

    inputEl.addEventListener('paste', function(e) {
        var items = e.clipboardData && e.clipboardData.items;
        if (!items) return;
        for (var i = 0; i < items.length; i++) {
            if (items[i].type.indexOf('image') !== -1) {
                e.preventDefault();
                var file = items[i].getAsFile();
                var formData = new FormData();
                formData.append('image', file, 'screenshot.png');
                showToast('Uploading screenshot...', 'info');
                fetch('/api/pilgrimbot/upload', {
                    method: 'POST',
                    body: formData
                }).then(function(r) { return r.json(); }).then(function(data) {
                    if (data.success) {
                        showImagePreview(data.url);
                        showToast('Screenshot attached — type your question and send', 'success');
                    } else {
                        showToast('Upload failed: ' + (data.error || 'unknown'), 'error');
                    }
                }).catch(function() { showToast('Screenshot upload failed', 'error'); });
                break;
            }
        }
    });

    // === Event listeners ===

    sendBtn.addEventListener('click', () => sendMessage(inputEl.value));
    inputEl.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(inputEl.value); }
    });
    inputEl.addEventListener('input', () => {
        inputEl.style.height = 'auto';
        inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
    });
    newChatBtn.addEventListener('click', startNewChat);
    document.querySelectorAll('.pb-example').forEach(btn => {
        btn.addEventListener('click', () => sendMessage(btn.dataset.q));
    });
    // Add listeners to server-rendered chat items (buildChatItem only handles dynamic ones)
    document.querySelectorAll('.pb-chat-item').forEach(el => {
        el.addEventListener('click', () => loadChat(el.dataset.chatId));
        const hideBtn = el.querySelector('.pb-chat-hide');
        if (hideBtn) {
            hideBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                hideChat(el.dataset.chatId, el);
            });
        }
    });

    // === Role picker ===
    var roleSelect = document.getElementById('pbRoleSelect');
    if (roleSelect) {
        roleSelect.addEventListener('change', function() {
            fetch('/api/pilgrimbot/role', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({role: this.value})
            }).then(function(r) { return r.json(); }).then(function(data) {
                if (data.success) {
                    roleSelect.style.outline = '2px solid #4a4';
                    setTimeout(function() { roleSelect.style.outline = ''; }, 1000);
                }
            });
        });
    }

    // Auto-send bug context if linked from bug tracker
    // Reuse existing chat for this bug if one exists, otherwise create new (once only)
    if (window.PB_BUG_CONTEXT && BUG_ID) {
        var existingBugChat = null;
        var bugTag = 'Bug #' + BUG_ID + ':';
        document.querySelectorAll('.pb-chat-item').forEach(function(el) {
            var titleEl = el.querySelector('.pb-chat-title');
            if (titleEl && titleEl.textContent.indexOf(bugTag) === 0 && !existingBugChat) {
                existingBugChat = el.dataset.chatId;
            }
        });
        if (existingBugChat) {
            // Existing chat found — load it, then check if it has an assistant response
            currentChatId = existingBugChat;
            messagesEl.innerHTML = '';
            if (welcomeEl) welcomeEl.style.display = 'none';
            fetch('/api/pilgrimbot/history?chat_id=' + existingBugChat)
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data.success && data.messages) {
                        data.messages.forEach(function(m) { appendMessage(m.role, m.content, m.created_at); });
                        // If no assistant response exists, re-send the bug context
                        var hasAssistant = data.messages.some(function(m) { return m.role === 'assistant'; });
                        if (!hasAssistant) {
                            setTimeout(function() { sendMessage(window.PB_BUG_CONTEXT); }, 200);
                        }
                    }
                    document.querySelectorAll('.pb-chat-item').forEach(function(el) {
                        el.classList.toggle('active', el.dataset.chatId === existingBugChat);
                    });
                });
        } else {
            // No chat yet — auto-send bug context immediately
            startNewChat();
            setTimeout(function() { sendMessage(window.PB_BUG_CONTEXT); }, 100);
        }
    }

})();
