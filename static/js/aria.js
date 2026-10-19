/**
 * ARIA Chat Widget
 *
 * Handles the floating chat orb and chat window for ARIA,
 * the colony's ancient AI companion.
 *
 * Features:
 * - Streaming responses (SSE) for real-time text display
 * - Persistent conversation history via localStorage
 * - Markdown formatting on completion
 */

(function() {
    'use strict';

    // Storage key for conversation persistence
    // v2: Bumped to invalidate old caches after ARIA prompt rewrite (Jan 2026)
    const STORAGE_KEY = 'aria_conversation_v2';
    const MAX_HISTORY = 50; // Max messages to store
    const SESSION_TIMEOUT = 30 * 60 * 1000; // 30 minutes - reset conversation after this

    // State
    let isOpen = false;
    let isLoading = false;
    let conversationHistory = [];
    let lastActivityTime = Date.now();
    let greetingShown = false;

    // DOM Elements (cached after init)
    let orbButton = null;
    let chatWindow = null;
    let messagesContainer = null;
    let inputField = null;
    let sendButton = null;

    /**
     * Load conversation from localStorage
     */
    function loadConversation() {
        try {
            const stored = localStorage.getItem(STORAGE_KEY);
            if (stored) {
                const data = JSON.parse(stored);
                // Check if conversation is still fresh
                if (data.timestamp && (Date.now() - data.timestamp) < SESSION_TIMEOUT) {
                    // Check if auth state changed (user just logged in)
                    const currentAuth = document.getElementById('aria-chat')?.dataset?.authenticated || 'false';
                    if (data.authenticated === 'false' && currentAuth === 'true') {
                        // User just logged in - clear old anonymous conversation
                        console.log('ARIA: Auth state changed (logged in) - clearing conversation');
                        localStorage.removeItem(STORAGE_KEY);
                        return false;
                    }
                    // Check if we're on a different page - clear history for fresh greeting
                    const currentPage = document.getElementById('aria-chat')?.dataset?.page || 'unknown';
                    if (data.page && data.page !== currentPage) {
                        // Page changed - clear history so new greeting shows
                        localStorage.removeItem(STORAGE_KEY);
                        return false;
                    }
                    conversationHistory = data.messages || [];
                    lastActivityTime = data.timestamp;
                    return true;
                }
            }
        } catch (e) {
            console.warn('ARIA: Could not load conversation from storage', e);
        }
        return false;
    }

    /**
     * Save conversation to localStorage
     */
    function saveConversation() {
        try {
            const currentPage = chatWindow?.dataset?.page || 'unknown';
            const currentAuth = chatWindow?.dataset?.authenticated || 'false';
            const data = {
                messages: conversationHistory.slice(-MAX_HISTORY),
                timestamp: Date.now(),
                page: currentPage,
                authenticated: currentAuth
            };
            localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
        } catch (e) {
            console.warn('ARIA: Could not save conversation to storage', e);
        }
    }

    /**
     * Clear conversation history
     */
    function clearConversation() {
        conversationHistory = [];
        localStorage.removeItem(STORAGE_KEY);
        greetingShown = false;
        if (messagesContainer) {
            messagesContainer.innerHTML = '';
        }
    }

    /**
     * Get contextual hint from ARIA
     */
    async function getHint() {
        const hintBtn = document.getElementById('aria-hint-btn');
        if (hintBtn) {
            hintBtn.classList.add('loading');
            hintBtn.textContent = '...';
        }

        try {
            const response = await fetch('/api/aria/hint');
            const data = await response.json();

            if (data.success && data.hint) {
                // Clear conversation and show hint as greeting
                clearConversation();

                // Set the hint as the greeting
                if (chatWindow) {
                    chatWindow.dataset.greeting = data.hint;
                }

                // Open chat and show the hint
                if (!isOpen) {
                    openChat();
                } else {
                    // Already open - just add the hint message
                    addMessage(data.hint, 'aria');
                }
            } else {
                // Fallback
                if (!isOpen) openChat();
                addMessage("I'm having trouble reading your colony status. Try again?", 'aria');
            }
        } catch (error) {
            console.error('ARIA hint error:', error);
            if (!isOpen) openChat();
            addMessage("Dust interference... Please try again.", 'aria');
        } finally {
            if (hintBtn) {
                hintBtn.classList.remove('loading');
                hintBtn.textContent = '?';
            }
        }
    }

    /**
     * Load conversation history from server (for authenticated users)
     */
    async function loadServerHistory() {
        try {
            const response = await fetch('/api/aria/history');
            const data = await response.json();
            if (data.success && data.authenticated) {
                if (data.history && data.history.length > 0) {
                    conversationHistory = data.history;
                    console.log('ARIA: Loaded', data.history.length, 'messages from server');
                    return true;
                } else {
                    // Server has no history - clear localStorage to stay in sync
                    console.log('ARIA: Server history empty - clearing localStorage');
                    localStorage.removeItem(STORAGE_KEY);
                    conversationHistory = [];
                    return false;
                }
            }
        } catch (e) {
            console.warn('ARIA: Could not load server history', e);
        }
        return false;
    }

    /**
     * Initialize ARIA chat widget
     */
    async function init() {
        orbButton = document.getElementById('aria-orb');
        chatWindow = document.getElementById('aria-chat');
        messagesContainer = document.getElementById('aria-messages');
        inputField = document.getElementById('aria-input');
        sendButton = document.getElementById('aria-send');

        if (!orbButton || !chatWindow) {
            console.log('ARIA widget elements not found - skipping init');
            return;
        }

        // For authenticated users, try to load server-side history first
        const isAuthenticated = chatWindow?.dataset?.authenticated === 'true';
        let hasHistory = false;

        if (isAuthenticated) {
            // Try server history first (persisted across sessions)
            hasHistory = await loadServerHistory();
        }

        // Fall back to localStorage if no server history
        if (!hasHistory) {
            hasHistory = loadConversation();
        }

        // Event listeners
        orbButton.addEventListener('click', toggleChat);

        const closeBtn = document.getElementById('aria-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', closeChat);
        }

        if (sendButton) {
            sendButton.addEventListener('click', sendMessage);
        }

        if (inputField) {
            inputField.addEventListener('keypress', function(e) {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage();
                }
            });
        }

        // Hint button - "What should I do next?"
        const hintBtn = document.getElementById('aria-hint-btn');
        if (hintBtn) {
            hintBtn.addEventListener('click', getHint);
        }

        // Close chat when clicking outside
        document.addEventListener('click', function(e) {
            if (isOpen && !chatWindow.contains(e.target) && !orbButton.contains(e.target)) {
                closeChat();
            }
        });

        // Proximity detection - ARIA gets excited as cursor approaches
        document.addEventListener('mousemove', function(e) {
            if (isOpen || !orbButton) return;

            const rect = orbButton.getBoundingClientRect();
            const orbCenterX = rect.left + rect.width / 2;
            const orbCenterY = rect.top + rect.height / 2;

            const distance = Math.sqrt(
                Math.pow(e.clientX - orbCenterX, 2) +
                Math.pow(e.clientY - orbCenterY, 2)
            );

            // Remove all proximity classes first
            orbButton.classList.remove('aria-nearby', 'aria-close');

            // Add appropriate class based on distance
            if (distance < 100) {
                orbButton.classList.add('aria-close');
            } else if (distance < 200) {
                orbButton.classList.add('aria-nearby');
            }
        });

        // If we have history, restore the UI
        if (hasHistory && conversationHistory.length > 0) {
            restoreMessages();
            greetingShown = true; // Don't show greeting if we have history
        }

        // Auto-open if dust storm alert (ARIA needs to warn the captain!)
        const shouldAutoOpen = chatWindow.dataset.autoOpen === 'true';
        const hasDustStorm = chatWindow.dataset.dustStorm === 'true';
        if (shouldAutoOpen && hasDustStorm) {
            // Small delay so page loads first, then ARIA pops up to warn
            setTimeout(() => {
                openChat();
                // Add urgency styling to the orb
                orbButton.classList.add('aria-urgent');
            }, 1000);
        }

        console.log('ARIA chat widget initialized' + (hasHistory ? ' (conversation restored)' : '') + (hasDustStorm ? ' (DUST STORM ALERT!)' : ''));
    }

    /**
     * Restore messages from history to UI
     */
    function restoreMessages() {
        if (!messagesContainer) return;

        messagesContainer.innerHTML = '';

        for (const msg of conversationHistory) {
            const sender = msg.role === 'assistant' ? 'aria' : 'user';
            const messageDiv = document.createElement('div');
            messageDiv.className = `aria-message ${sender}`;

            if (sender === 'aria') {
                messageDiv.innerHTML = parseMarkdown(msg.content);
            } else {
                messageDiv.textContent = msg.content;
            }

            messagesContainer.appendChild(messageDiv);
        }

        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    /**
     * Toggle chat open/closed
     */
    function toggleChat() {
        if (isOpen) {
            closeChat();
        } else {
            openChat();
        }
    }

    /**
     * Open the chat window
     */
    function openChat() {
        isOpen = true;
        chatWindow.classList.add('open');
        orbButton.classList.add('active');

        // Clear proximity classes when open
        orbButton.classList.remove('aria-nearby', 'aria-close');

        // Show greeting only once per session (if no messages)
        if (conversationHistory.length === 0 && !greetingShown) {
            showGreeting();
            greetingShown = true;
        }

        // Focus input
        setTimeout(() => {
            if (inputField) inputField.focus();
        }, 300);
    }

    /**
     * Close the chat window
     */
    function closeChat() {
        isOpen = false;
        chatWindow.classList.remove('open');
        orbButton.classList.remove('active');
        // Clear urgent state - user has acknowledged by closing
        orbButton.classList.remove('aria-urgent');
    }

    /**
     * Show ARIA's initial greeting
     */
    function showGreeting() {
        // Get greeting from data attribute or use default
        const greeting = chatWindow.dataset.greeting ||
            "Hello, Commander. How may I assist your colony today?";

        // SAVE to history so ARIA knows what she said when user responds!
        addMessage(greeting, 'aria', true);
    }

    /**
     * Show ARIA animation video in chat (once per day max)
     */
    function showAriaAnimation(url, insertBeforeElement = null) {
        console.log('🎬 showAriaAnimation called with:', url, 'insertBefore:', !!insertBeforeElement);
        if (!messagesContainer || !url) return;

        // Create video container
        const videoDiv = document.createElement('div');
        videoDiv.className = 'aria-animation';
        videoDiv.innerHTML = `
            <video autoplay muted playsinline>
                <source src="${url}" type="video/mp4">
            </video>
        `;

        // Insert BEFORE the message div so animation shows first
        if (insertBeforeElement && insertBeforeElement.parentNode === messagesContainer) {
            messagesContainer.insertBefore(videoDiv, insertBeforeElement);
        } else {
            messagesContainer.appendChild(videoDiv);
        }
        videoDiv.scrollIntoView({ behavior: 'smooth', block: 'center' });

        // Remove after video ends (or after 8 seconds max)
        const video = videoDiv.querySelector('video');
        const removeAnimation = () => {
            videoDiv.style.opacity = '0';
            setTimeout(() => videoDiv.remove(), 500);
        };

        video.addEventListener('ended', removeAnimation);
        setTimeout(removeAnimation, 8000); // Safety timeout
    }

    /**
     * Escape HTML to prevent XSS
     */
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Parse simple markdown for chat messages
     * Handles: **bold**, *italics*, _italics_, line breaks
     */
    function parseMarkdown(text) {
        let html = escapeHtml(text);
        // Bold: **text** or __text__
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/__(.+?)__/g, '<strong>$1</strong>');
        // Italics: *text* or _text_
        html = html.replace(/\*([^*]+?)\*/g, '<em>$1</em>');
        html = html.replace(/(?<!\w)_([^_]+?)_(?!\w)/g, '<em>$1</em>');
        // Line breaks
        html = html.replace(/\n/g, '<br>');
        return html;
    }

    /**
     * Add a message to the chat
     */
    function addMessage(text, sender, save = true) {
        if (!messagesContainer) return null;

        const messageDiv = document.createElement('div');
        messageDiv.className = `aria-message ${sender}`;

        // ARIA messages get markdown parsing, user messages are escaped plaintext
        if (sender === 'aria') {
            messageDiv.innerHTML = parseMarkdown(text);
        } else {
            messageDiv.textContent = text;
        }

        messagesContainer.appendChild(messageDiv);

        // For ARIA messages, scroll to show the start; for user messages, scroll to bottom
        if (sender === 'aria') {
            messageDiv.scrollIntoView({ behavior: 'smooth', block: 'start' });
        } else {
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }

        // Track in history
        if (save) {
            conversationHistory.push({
                role: sender === 'aria' ? 'assistant' : 'user',
                content: text
            });
            saveConversation();
        }

        return messageDiv;
    }

    /**
     * Create a message div for streaming (returns element to update)
     */
    function createStreamingMessage() {
        if (!messagesContainer) return null;

        const messageDiv = document.createElement('div');
        messageDiv.className = 'aria-message aria streaming';
        messageDiv.textContent = ''; // Start empty

        messagesContainer.appendChild(messageDiv);
        // Scroll to show the start of ARIA's response
        messageDiv.scrollIntoView({ behavior: 'smooth', block: 'start' });

        return messageDiv;
    }

    /**
     * Show typing indicator
     */
    function showTyping() {
        if (!messagesContainer) return null;

        const typingDiv = document.createElement('div');
        typingDiv.className = 'aria-message aria typing';
        typingDiv.id = 'aria-typing';
        typingDiv.innerHTML = '<span></span><span></span><span></span>';

        messagesContainer.appendChild(typingDiv);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;

        return typingDiv;
    }

    /**
     * Remove typing indicator
     */
    function hideTyping() {
        const typingDiv = document.getElementById('aria-typing');
        if (typingDiv) {
            typingDiv.remove();
        }
    }

    /**
     * Handle streaming response from ARIA
     */
    async function handleStreamingResponse(response, messageDiv) {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let fullText = '';

        try {
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });

                // Process complete SSE events
                const lines = buffer.split('\n');
                buffer = lines.pop() || ''; // Keep incomplete line in buffer

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        try {
                            const data = JSON.parse(line.slice(6));
                            console.log('ARIA SSE event:', data.type, data.type === 'animation' ? data.url : '');

                            if (data.type === 'delta' && data.text) {
                                fullText += data.text;
                                // Show raw text while streaming
                                messageDiv.textContent = fullText;
                                // Scroll to show the START of ARIA's message
                                messageDiv.scrollIntoView({ behavior: 'smooth', block: 'start' });
                            } else if (data.type === 'stop') {
                                // Stream complete - apply markdown
                                messageDiv.innerHTML = parseMarkdown(fullText);
                                messageDiv.classList.remove('streaming');

                                // Save to history
                                conversationHistory.push({
                                    role: 'assistant',
                                    content: fullText
                                });
                                saveConversation();
                                return fullText;
                            } else if (data.type === 'animation') {
                                // Special ARIA animation - insert BEFORE text message
                                console.log('🎬 ARIA animation received:', data.url);
                                showAriaAnimation(data.url, messageDiv);
                            } else if (data.type === 'error') {
                                throw new Error(data.error || 'Stream error');
                            }
                        } catch (e) {
                            if (e.message !== 'Stream error') {
                                console.warn('ARIA: Error parsing SSE event', e);
                            } else {
                                throw e;
                            }
                        }
                    }
                }
            }
        } catch (error) {
            console.error('ARIA streaming error:', error);
            throw error;
        }

        // If we get here without a stop event, still save what we have
        if (fullText) {
            messageDiv.innerHTML = parseMarkdown(fullText);
            messageDiv.classList.remove('streaming');
            conversationHistory.push({
                role: 'assistant',
                content: fullText
            });
            saveConversation();
        }

        return fullText;
    }

    /**
     * Send a message to ARIA (with streaming support)
     */
    async function sendMessage() {
        if (isLoading || !inputField) return;

        const message = inputField.value.trim();
        if (!message) return;

        // Clear input
        inputField.value = '';

        // Clear urgent state - user has engaged
        orbButton.classList.remove('aria-urgent');

        // Add user message to chat
        addMessage(message, 'user');

        // Show loading state
        isLoading = true;
        if (sendButton) sendButton.disabled = true;

        // Create streaming message container with typing animation
        const streamingDiv = createStreamingMessage();
        streamingDiv.classList.add('typing');
        streamingDiv.innerHTML = '<span></span><span></span><span></span>';

        try {
            // Gather page context for ARIA
            const pageContext = {
                page: chatWindow.dataset.page || 'unknown',
                context: chatWindow.dataset.pageContext || '',
                url: window.location.pathname
            };

            // Send to API with streaming enabled
            const response = await fetch('/api/aria/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    message: message,
                    history: conversationHistory.slice(-20), // Last 20 messages for context
                    stream: true,
                    page_context: pageContext
                })
            });

            const contentType = response.headers.get('content-type');

            if (contentType && contentType.includes('text/event-stream')) {
                // Handle streaming response - remove typing animation
                streamingDiv.classList.remove('typing');
                streamingDiv.innerHTML = '';
                await handleStreamingResponse(response, streamingDiv);
            } else {
                // Fallback to non-streaming
                const data = await response.json();
                streamingDiv.remove();

                if (data.success && data.response) {
                    addMessage(data.response, 'aria');
                } else {
                    addMessage(
                        data.error || "My sensors are experiencing interference... Please try again.",
                        'aria'
                    );
                }
            }
        } catch (error) {
            console.error('ARIA chat error:', error);
            streamingDiv.classList.remove('typing', 'streaming');
            streamingDiv.innerHTML = parseMarkdown(
                "*static crackle* Connection lost. Please try again."
            );
        } finally {
            isLoading = false;
            if (sendButton) sendButton.disabled = false;
            if (inputField) inputField.focus();
        }
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Expose for debugging and external use
    window.ariaChat = {
        open: openChat,
        close: closeChat,
        toggle: toggleChat,
        clear: clearConversation,
        hint: getHint
    };
})();
