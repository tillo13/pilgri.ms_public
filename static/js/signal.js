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
            // Not a transaction hash - reject with cryptic message
            status.textContent = 'FORMAT UNRECOGNIZED';
            status.className = 'decoder-status error';
            result.innerHTML = `<div class="decode-error"><em>"This does not match the ledger format. The eternal record uses a different language..."</em></div>`;
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

        // Valid transaction hash format - send to backend
        status.textContent = 'SCANNING LEDGER...';
        status.className = 'decoder-status processing';
        submit.disabled = true;

        try {
            const resp = await fetch('/api/signal/decode-tx', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tx_hash: code })
            });
            const data = await resp.json();

            if (data.success) {
                // Check if this is an ARIA bond fragment
                if (data.is_fragment) {
                    if (data.bond_complete) {
                        // BOND COMPLETED! Show epic revelation with image
                        status.textContent = '\u26A1 FIRST CONTACT ESTABLISHED \u26A1';
                        status.className = 'decoder-status success';

                        const imageHtml = data.bond_image_url ? `
                            <div style="text-align: center; margin: 16px 0;">
                                <img src="${data.bond_image_url}" alt="Entangled Fragment"
                                     style="max-width: 280px; width: 100%; border-radius: 12px; border: 3px solid rgba(6, 182, 212, 0.5); box-shadow: 0 8px 32px rgba(6, 182, 212, 0.3);">
                            </div>
                        ` : '';

                        result.innerHTML = `
                            <div class="decode-bond-complete">
                                <div class="decode-success-title" style="color: #06b6d4; font-size: 18px; text-align: center;">\u26A1 ARIA BOND #${data.bond_number || '?'} \u26A1</div>
                                ${imageHtml}
                                <div style="text-align: center; margin: 16px 0; padding: 12px; background: rgba(6, 182, 212, 0.1); border-radius: 8px;">
                                    <div style="font-size: 10px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 4px;">Entangled Fragment: ${data.landmark}</div>
                                    <span style="color: var(--color-sepolia); font-weight: 600; font-size: 16px;">${data.captain_1}</span>
                                    <span style="color: #06b6d4; margin: 0 8px;">+</span>
                                    <span style="color: var(--color-sepolia); font-weight: 600; font-size: 16px;">${data.captain_2}</span>
                                    <div style="font-size: 11px; color: var(--text-muted); margin-top: 6px;">SOL ${data.sol}</div>
                                </div>
                                <div style="padding: 16px; background: rgba(138, 112, 219, 0.1); border: 1px solid rgba(138, 112, 219, 0.3); border-radius: 8px; margin: 16px 0;">
                                    <div style="font-size: 11px; color: var(--color-aria); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px;">ARIA MEMORY UNLOCKED</div>
                                    <p style="font-style: italic; color: var(--text-secondary); line-height: 1.8; white-space: pre-line; font-size: 13px;">${data.aria_revelation}</p>
                                </div>
                                <p style="font-size: 12px; color: var(--text-muted); text-align: center;"><em>"${data.message}"</em></p>
                                <div style="text-align: center; margin-top: 12px;">
                                    <a href="/colony" style="color: #06b6d4; font-size: 12px;">View in Colony \u2192</a>
                                </div>
                            </div>
                        `;
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
                    } else if (data.already_bonded) {
                        // Bond already complete
                        status.textContent = 'BOND EXISTS';
                        status.className = 'decoder-status success';
                        result.innerHTML = `
                            <div class="decode-success" style="background: rgba(6, 182, 212, 0.1); border-color: rgba(6, 182, 212, 0.3);">
                                <div class="decode-success-title" style="color: #06b6d4;">\u26A1 ETERNAL RESONANCE</div>
                                <p style="color: var(--text-secondary);"><em>"${data.message}"</em></p>
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
            } else {
                status.textContent = 'TRANSMISSION REJECTED';
                status.className = 'decoder-status error';
                result.innerHTML = `<div class="decode-error"><em>"${data.error || 'The ledger does not recognize this entry...'}"</em></div>`;
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

    // Refresh shard balance on Signal page load
    fetch('/api/user/balance')
        .then(r => r.json())
        .then(data => {
            if (data.success && data.balance !== undefined && typeof window.setBalance === 'function') {
                window.setBalance(data.balance);
            }
        })
        .catch(() => {});

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
