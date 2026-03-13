/**
 * PilgrimBot — Codebase Q&A chat interface
 */

(function() {
    'use strict';

    let currentChatId = null;
    let isStreaming = false;

    const messagesEl = document.getElementById('pbMessages');
    const inputEl = document.getElementById('pbInput');
    const sendBtn = document.getElementById('pbSend');
    const welcomeEl = document.getElementById('pbWelcome');
    const chatListEl = document.getElementById('pbChatList');
    const newChatBtn = document.getElementById('pbNewChat');

    // === Send message ===

    function sendMessage(text) {
        if (!text || isStreaming) return;
        text = text.trim();
        if (!text) return;

        // Hide welcome screen
        if (welcomeEl) welcomeEl.style.display = 'none';

        // Add user message
        appendMessage('user', text);
        inputEl.value = '';
        inputEl.style.height = 'auto';
        isStreaming = true;
        sendBtn.disabled = true;

        // Create assistant placeholder
        const assistantEl = appendMessage('assistant', '');
        const contentEl = assistantEl.querySelector('.pb-msg-content');

        // Stream response
        const userQuestion = text;
        fetch('/api/pilgrimbot/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                message: text,
                chat_id: currentChatId,
                stream: true
            })
        }).then(response => {
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let fullText = '';
            let cantAnswer = false;

            function processChunk() {
                reader.read().then(({done, value}) => {
                    if (done) {
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
                                fullText += data.text;
                                contentEl.textContent = fullText;
                                messagesEl.scrollTop = messagesEl.scrollHeight;
                            } else if (data.type === 'stop') {
                                if (data.cant_answer) cantAnswer = true;
                                finishStream(fullText, cantAnswer, userQuestion);
                                return;
                            } else if (data.type === 'error') {
                                contentEl.textContent = data.message || 'Something went wrong.';
                                finishStream(fullText, false, userQuestion);
                                return;
                            }
                        } catch (e) { /* skip malformed */ }
                    }
                    processChunk();
                });
            }
            processChunk();
        }).catch(err => {
            contentEl.textContent = 'Connection error. Please try again.';
            finishStream('', false, userQuestion);
        });
    }

    function finishStream(text, cantAnswer, userQuestion) {
        isStreaming = false;
        sendBtn.disabled = false;
        inputEl.focus();
        // Show "Report this" button if PilgrimBot couldn't answer
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
                    this.textContent = data.success ? 'Reported — the dev team will follow up!' : 'Could not report. Try again later.';
                    this.classList.add('pb-report-done');
                }).catch(() => {
                    this.textContent = 'Connection error.';
                });
            });
        }
        // Refresh sidebar
        refreshChatList();
    }

    // === DOM helpers ===

    function appendMessage(role, text) {
        const div = document.createElement('div');
        div.className = `pb-msg pb-msg-${role}`;
        div.innerHTML = `
            <div class="pb-msg-label">${role === 'user' ? 'You' : 'PilgrimBot'}</div>
            <div class="pb-msg-content">${escapeHtml(text)}</div>
        `;
        messagesEl.appendChild(div);
        messagesEl.scrollTop = messagesEl.scrollHeight;
        return div;
    }

    function escapeHtml(str) {
        if (!str) return '';
        return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
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
                    div.innerHTML = `
                        <div class="pb-chat-title">${escapeHtml(chat.title)}</div>
                        <div class="pb-chat-meta">${chat.message_count} messages</div>
                    `;
                    div.addEventListener('click', () => loadChat(chat.chat_id));
                    chatListEl.appendChild(div);
                });
            });
    }

    function loadChat(chatId) {
        currentChatId = chatId;
        // Clear messages and load from API
        messagesEl.innerHTML = '';
        if (welcomeEl) welcomeEl.style.display = 'none';

        fetch(`/api/pilgrimbot/chats`)
            .then(r => r.json())
            .then(data => {
                // Mark active in sidebar
                document.querySelectorAll('.pb-chat-item').forEach(el => {
                    el.classList.toggle('active', el.dataset.chatId === chatId);
                });
            });

        // Load chat history by sending empty request? No, we need a history endpoint.
        // For now, start fresh with the chat_id — messages will load on next send.
        // TODO: Add GET /api/pilgrimbot/history?chat_id=X endpoint
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

    inputEl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage(inputEl.value);
        }
    });

    // Auto-resize textarea
    inputEl.addEventListener('input', () => {
        inputEl.style.height = 'auto';
        inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
    });

    newChatBtn.addEventListener('click', startNewChat);

    // Example question buttons
    document.querySelectorAll('.pb-example').forEach(btn => {
        btn.addEventListener('click', () => sendMessage(btn.dataset.q));
    });

    // Chat list click handlers (for initial server-rendered items)
    document.querySelectorAll('.pb-chat-item').forEach(el => {
        el.addEventListener('click', () => loadChat(el.dataset.chatId));
    });

})();
