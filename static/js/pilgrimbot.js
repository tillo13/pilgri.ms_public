/**
 * PilgrimBot — Codebase Q&A chat interface
 */

(function() {
    'use strict';

    const USER_NAME = window.PB_USER_NAME || 'Captain';
    let currentChatId = null;
    let isStreaming = false;

    const messagesEl = document.getElementById('pbMessages');
    const inputEl = document.getElementById('pbInput');
    const sendBtn = document.getElementById('pbSend');
    const welcomeEl = document.getElementById('pbWelcome');
    const chatListEl = document.getElementById('pbChatList');
    const newChatBtn = document.getElementById('pbNewChat');

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
        // Fallback
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

    // === Message rendering ===

    function appendMessage(role, text, timestamp) {
        const div = document.createElement('div');
        div.className = `pb-msg pb-msg-${role}`;
        const name = role === 'user' ? USER_NAME : 'PilgrimBot';
        const time = timestamp ? formatTime(timestamp) : formatTime(new Date());
        const content = role === 'user' ? escapeHtml(text) : parseMarkdown(text);

        div.innerHTML =
            '<div class="pb-msg-header">' + escapeHtml(name) + ' <span class="pb-msg-time">' + time + '</span></div>' +
            '<div class="pb-msg-content">' + content + '</div>';
        messagesEl.appendChild(div);
        messagesEl.scrollTop = messagesEl.scrollHeight;
        return div;
    }

    function showTyping() {
        const div = document.createElement('div');
        div.className = 'pb-typing';
        div.id = 'pbTyping';
        div.innerHTML =
            '<div class="pb-typing-header">PilgrimBot</div>' +
            '<div class="pb-typing-body">' +
                '<div class="pb-typing-dots"><span></span><span></span><span></span></div>' +
            '</div>';
        messagesEl.appendChild(div);
        messagesEl.scrollTop = messagesEl.scrollHeight;
        return div;
    }

    function removeTyping(el) {
        if (el && el.parentNode) el.remove();
    }

    // === Send message ===

    function sendMessage(text) {
        if (!text || isStreaming) return;
        text = text.trim();
        if (!text) return;

        if (welcomeEl) welcomeEl.style.display = 'none';

        appendMessage('user', text);
        inputEl.value = '';
        inputEl.style.height = 'auto';
        isStreaming = true;
        sendBtn.disabled = true;

        const typingEl = showTyping();
        let gotFirstDelta = false;

        const streamTimeout = setTimeout(() => {
            if (!gotFirstDelta && isStreaming) {
                removeTyping(typingEl);
                appendMessage('assistant', 'PilgrimBot took too long to respond. Please try again.');
                finishStream('', false, text);
            }
        }, 30000);

        const userQuestion = text;
        let contentEl = null;
        let fullText = '';
        let cantAnswer = false;

        fetch('/api/pilgrimbot/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({message: text, chat_id: currentChatId, stream: true})
        }).then(response => {
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            function processChunk() {
                reader.read().then(({done, value}) => {
                    if (done) {
                        clearTimeout(streamTimeout);
                        if (contentEl) contentEl.innerHTML = parseMarkdown(fullText);
                        finishStream(fullText, cantAnswer, userQuestion);
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
                            } else if (data.type === 'delta' && data.text) {
                                if (!gotFirstDelta) {
                                    gotFirstDelta = true;
                                    clearTimeout(streamTimeout);
                                    removeTyping(typingEl);
                                    const el = appendMessage('assistant', '');
                                    contentEl = el.querySelector('.pb-msg-content');
                                }
                                fullText += data.text;
                                // Show raw text while streaming, render markdown on finish
                                contentEl.textContent = fullText;
                                messagesEl.scrollTop = messagesEl.scrollHeight;
                            } else if (data.type === 'stop') {
                                clearTimeout(streamTimeout);
                                if (data.cant_answer) cantAnswer = true;
                                removeTyping(typingEl);
                                if (contentEl) contentEl.innerHTML = parseMarkdown(fullText);
                                finishStream(fullText, cantAnswer, userQuestion);
                                return;
                            } else if (data.type === 'error') {
                                clearTimeout(streamTimeout);
                                removeTyping(typingEl);
                                appendMessage('assistant', data.message || 'Something went wrong.');
                                finishStream(fullText, false, userQuestion);
                                return;
                            }
                        } catch (e) { /* skip malformed */ }
                    }
                    processChunk();
                });
            }
            processChunk();
        }).catch(() => {
            clearTimeout(streamTimeout);
            removeTyping(typingEl);
            appendMessage('assistant', 'Connection error. Please try again.');
            finishStream('', false, userQuestion);
        });
    }

    function finishStream(text, cantAnswer, userQuestion) {
        isStreaming = false;
        sendBtn.disabled = false;
        inputEl.focus();

        if (cantAnswer && userQuestion) {
            const reportDiv = document.createElement('div');
            reportDiv.className = 'pb-report-offer';
            reportDiv.innerHTML = '<button class="pb-report-btn">Flag this for the dev team</button>';
            messagesEl.appendChild(reportDiv);
            messagesEl.scrollTop = messagesEl.scrollHeight;
            reportDiv.querySelector('.pb-report-btn').addEventListener('click', function() {
                this.disabled = true;
                this.textContent = 'Reporting...';
                fetch('/api/pilgrimbot/report', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({question: userQuestion})
                }).then(r => r.json()).then(data => {
                    this.textContent = data.success ? 'Reported — thanks!' : 'Could not report.';
                    this.classList.add('pb-report-done');
                }).catch(() => { this.textContent = 'Connection error.'; });
            });
        }
        refreshChatList();
    }

    // === Chat list ===

    function refreshChatList() {
        fetch('/api/pilgrimbot/chats')
            .then(r => r.json())
            .then(data => {
                if (!data.success) return;
                chatListEl.innerHTML = '';
                data.chats.forEach(chat => {
                    const div = document.createElement('div');
                    div.className = 'pb-chat-item' + (chat.chat_id === currentChatId ? ' active' : '');
                    div.dataset.chatId = chat.chat_id;
                    div.innerHTML =
                        '<div class="pb-chat-title">' + escapeHtml(chat.title) + '</div>' +
                        '<div class="pb-chat-meta">' + chat.message_count + ' messages</div>';
                    div.addEventListener('click', () => loadChat(chat.chat_id));
                    chatListEl.appendChild(div);
                });
            }).catch(() => {});
    }

    function loadChat(chatId) {
        currentChatId = chatId;
        messagesEl.innerHTML = '';
        if (welcomeEl) welcomeEl.style.display = 'none';

        fetch('/api/pilgrimbot/history?chat_id=' + chatId)
            .then(r => r.json())
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
    document.querySelectorAll('.pb-chat-item').forEach(el => {
        el.addEventListener('click', () => loadChat(el.dataset.chatId));
    });

})();
