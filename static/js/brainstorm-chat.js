/**
 * brainstorm-chat.js - Reusable chat widget for brainstorm pages
 *
 * Usage: Set window.BRAINSTORM_CONFIG before loading this script:
 *   window.BRAINSTORM_CONFIG = {
 *       apiEndpoint: '/api/brainstorm/tech-tree-chat',
 *       context: 'Your brainstorm context string...'
 *   };
 */

let conversationHistory = [];

function sendSuggestion(el) {
    document.getElementById('chat-input').value = el.textContent;
    sendMessage();
}

function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
}

async function sendMessage() {
    const input = document.getElementById('chat-input');
    const message = input.value.trim();
    if (!message) return;

    addMessage('user', message);
    input.value = '';

    const sendBtn = document.getElementById('chat-send');
    sendBtn.disabled = true;

    const typingDiv = document.createElement('div');
    typingDiv.className = 'chat-message assistant';
    typingDiv.id = 'typing-indicator';
    typingDiv.innerHTML = `
        <div class="chat-avatar">\u{1F9E0}</div>
        <div class="chat-bubble">
            <div class="typing-indicator">
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
            </div>
        </div>
    `;
    document.getElementById('chat-messages').appendChild(typingDiv);
    scrollToBottom();

    try {
        const config = window.BRAINSTORM_CONFIG || {};
        const response = await fetch(config.apiEndpoint || '/api/brainstorm/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: message,
                context: config.context || '',
                history: conversationHistory
            })
        });

        const data = await response.json();
        document.getElementById('typing-indicator')?.remove();

        if (data.success) {
            addMessage('assistant', data.response);
            conversationHistory.push({ role: 'user', content: message });
            conversationHistory.push({ role: 'assistant', content: data.response });
        } else {
            addMessage('assistant', 'Sorry, I encountered an error. Please try again.');
        }
    } catch (err) {
        document.getElementById('typing-indicator')?.remove();
        addMessage('assistant', 'Sorry, I encountered an error. Please try again.');
    }

    sendBtn.disabled = false;
}

function addMessage(role, content) {
    const messagesDiv = document.getElementById('chat-messages');
    const messageDiv = document.createElement('div');
    messageDiv.className = `chat-message ${role}`;

    const avatar = role === 'user' ? '\u{1F464}' : '\u{1F9E0}';
    messageDiv.innerHTML = `
        <div class="chat-avatar">${avatar}</div>
        <div class="chat-bubble">${escapeHtml(content)}</div>
    `;

    messagesDiv.appendChild(messageDiv);
    scrollToBottom();
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML.replace(/\n/g, '<br>');
}

function scrollToBottom() {
    const messagesDiv = document.getElementById('chat-messages');
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}
