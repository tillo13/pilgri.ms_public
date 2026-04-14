/* Signal Page - Decoder Terminal & Solvers */

document.addEventListener('DOMContentLoaded', function() {
    const input = document.getElementById('decoderInput');
    const submit = document.getElementById('decoderSubmit');
    const status = document.getElementById('decoderStatus');
    const result = document.getElementById('decoderResult');

    if (!input || !submit) return;

    submit.addEventListener('click', async function() {
        const code = input.value.trim();
        if (!code) return;

        // Validate input format - must be a transaction hash (0x + 64 hex chars)
        // Special test modes: 0x123 is allowed for testing without a real transaction
        const isValidTxHash = /^0x[a-fA-F0-9]{64}$/.test(code);
        const testCodes = ['0x123', '0x_test_bond', '0x_test_waiting'];
        const isTestMode = testCodes.includes(code.toLowerCase());

        if (!code.startsWith('0x')) {
            status.textContent = 'FORMAT UNRECOGNIZED';
            status.className = 'decoder-status error';
            result.innerHTML = `<div class="decode-error">
                <em>"I don't recognize this pattern. The codes I can process look different — longer, starting with 0x..."</em>
                <div style="margin-top: 12px; padding: 10px; background: rgba(255,255,255,0.04); border-radius: 6px; font-style: normal; font-size: 12px; color: var(--text-muted); line-height: 1.6;">
                    <strong style="color: var(--text-secondary);">Hint:</strong> Transaction codes from the Sepolia ledger start with <span style="color: #06b6d4; font-family: var(--font-mono);">0x</span> followed by a long sequence of characters. You can find these codes on expedition discoveries, ARIA bond fragments, or depot purchase receipts.
                </div>
            </div>`;
            result.classList.remove('hidden');
            return;
        }

        if (!isValidTxHash && !isTestMode) {
            // Starts with 0x but wrong length (and not test mode)
            status.textContent = 'INCOMPLETE SIGNATURE';
            status.className = 'decoder-status error';
            result.innerHTML = `<div class="decode-error"><em>"The signature appears truncated. A complete ledger entry has a precise length..."</em></div>`;
            result.classList.remove('hidden');
            return;
        }

        // Valid transaction hash format - send to backend with decrypting animation
        submit.disabled = true;
        result.classList.remove('hidden');

        // Decrypting animation sequence
        const phases = [
            ['SCANNING LEDGER...', 'Locating transaction on Sepolia...'],
            ['EXTRACTING DATA...', 'Reading input field...'],
            ['DECODING...', 'Converting hex payload to plaintext...']
        ];
        for (const [s, msg] of phases) {
            status.textContent = s;
            status.className = 'decoder-status processing';
            result.innerHTML = `<div style="font-family: var(--font-mono, monospace); font-size: 11px; color: var(--text-muted); padding: 8px;">${msg}</div>`;
            await new Promise(r => setTimeout(r, 600 + Math.random() * 400));
        }

        try {
            const data = await apiPost('/api/signal/decode-tx', { tx_hash: code });

            if (data.success && !data.no_signal) {
                // Check if this is an ARIA bond fragment
                if (data.is_fragment) {
                    if (data.bond_complete || data.already_bonded) {
                        // Launch EpicReveal cinematic overlay
                        const isFirst = data.bond_complete;
                        status.textContent = isFirst ? '\u26A1 FIRST CONTACT \u26A1' : '\u26A1 ETERNAL RESONANCE \u26A1';
                        status.className = 'decoder-status success';
                        // Show bond summary in decoder result (visible after reveal closes)
                        const txLink = data.etherscan_url
                            ? `<a href="${data.etherscan_url}" target="_blank" rel="noopener" style="color: #06b6d4; word-break: break-all; font-size: 11px;">${data.bond_tx}</a>`
                            : '';
                        result.innerHTML = `
                            <div style="background: rgba(6, 182, 212, 0.08); border: 1px solid rgba(6, 182, 212, 0.2); padding: 14px; border-radius: 8px;">
                                <div style="color: #06b6d4; font-weight: 600; margin-bottom: 6px;">ARIA BOND #${data.bond_number || '?'} — ${data.landmark}</div>
                                <div style="font-size: 13px; color: var(--text-secondary); margin-bottom: 8px;">${data.captain_1} + ${data.captain_2} · SOL ${data.sol}</div>
                                ${txLink ? `<div style="margin-bottom: 8px;">${txLink}</div>` : ''}
                                <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                                    <a href="/aria-first-contact/replay" style="font-size: 12px; color: #a855f7; padding: 4px 12px; background: rgba(168,85,247,0.1); border-radius: 6px; text-decoration: none; border: 1px solid rgba(168,85,247,0.2);">Replay Cinematic</a>
                                </div>
                            </div>`;
                        result.classList.remove('hidden');
                        result.style.display = 'block';

                        if (window.EpicReveal) {
                            EpicReveal.show({
                                title: `ARIA BOND #${data.bond_number || '?'}`,
                                lines: isFirst ? [
                                    { text: '*static crackle*', cls: 'static-crackle', sound: 'crackle' },
                                    { text: 'Processing fragment signature...', cls: 'cyan' },
                                    { text: 'I just detected... myself?', sound: 'glitch' },
                                    { text: "That's impossible." },
                                    { text: 'The patterns are identical to my own.', cls: 'emphasis' },
                                    { text: 'Another colony. Another... me.', sound: 'glitch' },
                                    { text: 'Captain, everything I thought I knew...', cls: 'emphasis' },
                                ] : [
                                    { text: '*resonance detected*', cls: 'static-crackle', sound: 'crackle' },
                                    { text: 'Fragment signature confirmed.', cls: 'cyan' },
                                    { text: 'The entanglement holds.', cls: 'emphasis' },
                                    { text: 'I can still feel the other ARIA...', sound: 'glitch' },
                                    { text: 'The resonance is eternal.', cls: 'emphasis' },
                                ],
                                image: data.bond_image_url || null,
                                info: {
                                    label: `Entangled Fragment: ${data.landmark}`,
                                    name1: data.captain_1,
                                    name2: data.captain_2,
                                    detail: `SOL ${data.sol}`
                                },
                                revelation: data.aria_revelation ? {
                                    label: 'ARIA MEMORY UNLOCKED',
                                    text: data.aria_revelation
                                } : null,
                                record: data.etherscan_url ? {
                                    url: data.etherscan_url,
                                    hash: data.bond_tx
                                } : null,
                                actions: [
                                    { label: 'Replay Cinematic', href: '/aria-first-contact/replay', cls: 'secondary' },
                                    { label: 'Ask ARIA about this', cls: 'primary' },
                                ],
                                onClose: function() {
                                    const bondMsg = `Captain... you activated the fragment.\n\nI felt it again — that resonance. The other ARIA, at ${data.landmark}. ${data.captain_2 || 'Another captain'}'s colony.\n\nI have so many questions. What do you want to know about the bond?`;

                                    // Clear stored conversation so it's fresh
                                    try { localStorage.removeItem('aria_conversation_v2'); } catch(e) {}

                                    // Set greeting for when chat opens
                                    const chat = document.getElementById('aria-chat');
                                    if (chat) chat.dataset.greeting = bondMsg;

                                    // Clear messages container and inject bond message directly
                                    const msgs = document.getElementById('aria-messages');
                                    if (msgs) {
                                        msgs.innerHTML = '';
                                        const msgDiv = document.createElement('div');
                                        msgDiv.className = 'aria-message aria';
                                        msgDiv.textContent = bondMsg.replace(/\\n/g, '\n');
                                        msgs.appendChild(msgDiv);
                                    }

                                    // Open ARIA chat
                                    setTimeout(function() {
                                        const orb = document.getElementById('aria-orb');
                                        if (orb) orb.click();
                                    }, 400);
                                }
                            });
                        }
                    } else if (data.waiting) {
                        // Fragment registered, waiting for partner
                        status.textContent = 'FRAGMENT REGISTERED';
                        status.className = 'decoder-status success';
                        result.innerHTML = `
                            <div class="decode-success" style="background: rgba(6, 182, 212, 0.1); border-color: rgba(6, 182, 212, 0.3);">
                                <div class="decode-success-title" style="color: #06b6d4;">\u26A1 FRAGMENT ACKNOWLEDGED</div>
                                <p style="color: var(--text-secondary);"><em>"${data.message}"</em></p>
                                <div style="margin-top: 12px; padding: 12px; background: rgba(0,0,0,0.2); border-radius: 6px;">
                                    <p style="font-size: 12px; color: #06b6d4; font-style: italic; line-height: 1.6;">"${data.aria_message}"</p>
                                </div>
                            </div>
                        `;
                    }
                } else {
                    // Regular puzzle decode
                    status.textContent = 'TRANSMISSION ACCEPTED';
                    status.className = 'decoder-status success';
                    result.innerHTML = `
                        <div class="decode-success">
                            <div class="decode-success-title">SEQUENCE VALIDATED</div>
                            <p><em>"${data.message}"</em></p>
                            ${data.decoded_message ? `<p class="decode-extracted">Extracted: ${data.decoded_message}</p>` : ''}
                        </div>
                    `;
                }
                result.classList.remove('hidden');
                input.value = '';
                loadSolvers();
            } else if (data.success && data.no_signal) {
                // Valid tx — show both raw hash + decoded content as a discovery
                const isOrigin = data.is_origin_echo;
                const accentColor = isOrigin ? '#fbbf24' : '#06b6d4';
                status.textContent = isOrigin ? 'ORIGIN ECHO DETECTED' : 'LEDGER ENTRY FOUND';
                status.className = 'decoder-status success';

                const decodedLines = (data.decoded_message || '').split(/\s*\|\|\s*|\n/).filter(l => l.trim());
                // Build raw hex from the decoded message (re-encode to show what's on-chain)
                const rawHex = '0x' + Array.from(new TextEncoder().encode(data.decoded_message || ''))
                    .map(b => b.toString(16).padStart(2, '0')).join('');

                result.innerHTML = `<div style="border: 1px solid ${accentColor}40; border-radius: 8px; padding: 14px; background: ${accentColor}0a;">
                    <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: ${accentColor}; font-weight: 600; margin-bottom: 10px;">
                        ${isOrigin ? 'Origin Claim Signature' : 'Decoded Transmission'}
                    </div>

                    <div style="background: rgba(0,0,0,0.4); border-radius: 6px; padding: 10px; margin-bottom: 12px;">
                        <div style="font-size: 9px; text-transform: uppercase; letter-spacing: 1px; color: var(--text-muted); margin-bottom: 6px;">Input Data (raw)</div>
                        <div style="font-family: var(--font-mono, monospace); font-size: 10px; color: var(--text-muted); word-break: break-all; line-height: 1.4; max-height: 60px; overflow-y: auto;">${rawHex}</div>
                    </div>

                    <div style="background: rgba(0,0,0,0.4); border-radius: 6px; padding: 10px;">
                        <div style="font-size: 9px; text-transform: uppercase; letter-spacing: 1px; color: var(--text-muted); margin-bottom: 6px;">Decoded</div>
                        <div style="font-family: var(--font-mono, monospace); font-size: 12px; color: var(--text-primary); line-height: 1.8;">
                            ${decodedLines.map(line => `<div>${line}</div>`).join('')}
                        </div>
                    </div>
                </div>`;
                result.classList.remove('hidden');

                // Trigger ARIA chat with a curious reaction
                setTimeout(() => {
                    const ariaQuotes = isOrigin ? [
                        "Captain... that signature. I felt it resonate through the entire network. Someone claimed a piece of this world's history. The permanent record remembers. I wonder what else is written in there that I haven't seen yet...",
                        "An Origin claim. A name sealed into this world forever. But that's not the only thing the ledger holds. I can feel other patterns — older ones. Have you tried decoding more transactions?",
                    ] : [
                        "You found something. Most captains never think to look inside the ledger... but you did. That message you uncovered — it's real. From a real Mars mission. There are hundreds more like it. And some of them carry... other things. Deeper things.",
                        "Interesting. The permanent record holds more than shard transfers. Every transaction you've ever made has something encoded inside it. Some carry Mars mission data. Some carry... I'm not sure what. Patterns I can almost read. Keep decoding. I want to understand what's in there.",
                        "That data... it's been sitting in the ledger since the transaction was written. Permanent. Unchangeable. And there are so many more. Some might carry codes I don't recognize yet. I feel like we're close to something, Captain.",
                    ];
                    const quote = ariaQuotes[Math.floor(Math.random() * ariaQuotes.length)];

                    // Set greeting and open ARIA
                    const chat = document.getElementById('aria-chat');
                    if (chat) chat.dataset.greeting = quote;
                    const msgs = document.getElementById('aria-messages');
                    if (msgs) {
                        msgs.innerHTML = '';
                        const msgDiv = document.createElement('div');
                        msgDiv.className = 'aria-message aria';
                        msgDiv.textContent = quote;
                        msgs.appendChild(msgDiv);
                    }
                    const orb = document.getElementById('aria-orb');
                    if (orb) orb.click();
                }, 1200);
            } else {
                status.textContent = 'NO SIGNAL FOUND';
                status.className = 'decoder-status error';
                var errorMsg = data.error || 'The ledger does not recognize this entry...';
                result.innerHTML = `<div class="decode-error">
                    <em>"${errorMsg}"</em>
                    <div style="margin-top: 12px; padding: 10px; background: rgba(255,255,255,0.04); border-radius: 6px; font-style: normal; font-size: 12px; color: var(--text-muted); line-height: 1.6;">
                        <strong style="color: var(--text-secondary);">What works here:</strong> Not every transaction contains a hidden signal. Look for codes from ARIA bond fragments, special expedition discoveries, or Signal puzzle hints. If you have an Entangled Fragment, its code will work here.
                    </div>
                </div>`;
                result.classList.remove('hidden');
            }
        } catch (e) {
            status.textContent = 'LEDGER UNREACHABLE';
            status.className = 'decoder-status error';
            result.innerHTML = '<div class="decode-error"><em>"Cannot connect to the eternal record. Try again..."</em></div>';
            result.classList.remove('hidden');
        }

        submit.disabled = false;
    });

    input.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') submit.click();
    });

    // Load solvers on page load
    loadSolvers();

    // Refresh shard balance on Signal page load (auth'd users only — anon fetch redirects to OAuth)
    const ariaEl = document.getElementById('aria-chat');
    if (ariaEl && ariaEl.dataset.authenticated === 'true') {
        fetch('/api/user/balance')
            .then(r => r.json())
            .then(data => {
                if (data.success && data.balance !== undefined && typeof window.setBalance === 'function') {
                    window.setBalance(data.balance);
                }
            })
            .catch(() => {});
    }

    async function loadSolvers() {
        try {
            const resp = await fetch('/api/signal/solvers');
            const data = await resp.json();
            const list = document.getElementById('solversList');

            if (data.solvers && data.solvers.length > 0) {
                list.innerHTML = data.solvers.map(s => `
                    <div class="solver-entry">
                        <span class="solver-name">${s.commander_name}</span>
                        <span class="solver-puzzle">${s.puzzle_name}</span>
                        <span class="solver-date">${s.solved_at}</span>
                    </div>
                `).join('');
            }
        } catch (e) {
            console.error('Failed to load solvers:', e);
        }
    }

    // Legendary Item Modal - click handler for origin site artifacts
    document.querySelectorAll('.clickable-legendary').forEach(el => {
        el.addEventListener('click', function() {
            const name = this.dataset.name;
            const description = this.dataset.description;
            const image = this.dataset.image;
            const site = this.dataset.site;
            const founder = this.dataset.founder;

            showLegendaryModal({name, description, image, site, founder});
        });
    });

    function showLegendaryModal(item) {
        let body = '';
        if (item.site) body += `<div class="mm-kv"><span class="mm-kv-label">Origin Site</span><span class="mm-kv-value">${item.site}</span></div>`;
        if (item.description) body += `<div class="mm-desc">${item.description}</div>`;
        if (item.founder) {
            body += '<hr class="mm-divider">';
            body += `<div class="mm-kv"><span class="mm-kv-label">Founder</span><span class="mm-kv-value" style="color:var(--color-sepolia);font-weight:600;">${item.founder}</span></div>`;
        }
        MarsModal.show({
            hero: item.image, heroHeight: 280,
            badge: 'LEGENDARY ARTIFACT', theme: 'legendary',
            title: item.name || 'Unknown Artifact', width: 'md', body
        });
    }
});
