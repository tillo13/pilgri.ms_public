// ============================================================================
// CREW-ROBOT.JS — Crew tab → Robot
//
// Wires the buttons inside templates/crew/_tab_robot.html to:
//   POST /api/robot/build           — start the build
//   POST /api/robot/name            — save the robot's name
//   POST /api/robot/dial            — update the role dial (mod-5, sum=100)
//   POST /api/robot/cinematic_played— mark the build-complete cinematic shown
//
// Data flow: server renders the tab with `robot_data` (see db_robot.get_robot_page_data).
// A small JSON island (#robotPageData) gives us the live build state without polling
// the API on page load. After any POST, we re-render by reloading the page (Step 4d
// is intentionally simple — Step 6 hooks the cinematic + Step 4c will swap to a
// proper SPA refresh once Kontext images are wired).
// ============================================================================

(function () {
    const BRIDGE = (() => {
        const el = document.getElementById('robotPageData');
        if (!el) return null;
        try { return JSON.parse(el.textContent); } catch (e) { return null; }
    })();

    let countdownInterval = null;

    // ----- helpers ----------------------------------------------------------
    function fmtSeconds(s) {
        if (s == null || s < 0) s = 0;
        if (s < 60) return s + 's';
        const m = Math.floor(s / 60);
        const r = s % 60;
        return m + 'm ' + (r < 10 ? '0' : '') + r + 's';
    }

    async function postJSONSafe(url, body) {
        try {
            const data = await apiPost(url, body || {});
            if (!data.success) throw new Error(data.error || 'Request failed');
            return data;
        } catch (e) {
            if (typeof showToast === 'function') {
                showToast(e.message || String(e), 'error', 'Narog');
            } else {
                alert('Golem: ' + (e.message || e));
            }
            throw e;
        }
    }

    function reloadSoon() {
        // Simple, predictable refresh — server re-renders the whole tab.
        // crew-robot.js will pick up the new state on the next DOMContentLoaded.
        setTimeout(() => window.location.reload(), 250);
    }

    // ----- countdown --------------------------------------------------------
    function startCountdown() {
        // If the hero image is in forging state (build in progress), poll
        // for stage advances so each per-stage Flux call's output appears
        // without manual reload. No countdown timer — the backend drives
        // cadence via Flux call durations.
        const heroForging = document.querySelector('.robot-hero-forging');
        if (heroForging) {
            pollForStageAdvance();
            return;
        }
        const el = document.getElementById('robot-countdown');
        if (!el) return;
        const initial = parseInt(el.dataset.seconds, 10);
        if (!Number.isFinite(initial)) return;

        // If the timer is already expired on page load, the background Kontext
        // thread is still generating the image. Reloading every second creates
        // an infinite refresh loop — poll status instead, and only reload when
        // visual_stage actually advances.
        if (initial <= 0) {
            pollForStageAdvance();
            return;
        }

        let remaining = initial;
        const tick = () => {
            remaining -= 1;
            if (remaining <= 0) {
                el.textContent = 'Forging…';
                clearInterval(countdownInterval);
                countdownInterval = null;
                pollForStageAdvance();
                return;
            }
            el.textContent = fmtSeconds(remaining);
        };
        if (countdownInterval) clearInterval(countdownInterval);
        countdownInterval = setInterval(tick, 1000);
    }

    function pollForStageAdvance() {
        const el = document.getElementById('robot-countdown');
        const currentStage = BRIDGE && BRIDGE.visual_stage;
        let attempts = 0;
        const check = async () => {
            attempts += 1;
            try {
                const r = await fetch('/api/robot/status');
                const data = await r.json();
                const newStage = data && data.data && data.data.robot && data.data.robot.visual_stage;
                if (Number.isFinite(newStage) && newStage !== currentStage) {
                    window.location.reload();
                    return;
                }
            } catch (e) { /* keep polling */ }
            if (el) el.textContent = 'Forging' + '.'.repeat((attempts % 4));
            if (attempts < 60) setTimeout(check, 5000); // 5 min ceiling
        };
        setTimeout(check, 3000);
    }

    // Exposed so the crew tab callback can re-arm the countdown when the
    // user re-enters the tab without a full reload.
    window.refreshRobotTab = function () {
        startCountdown();
    };

    // ----- VIDEO MODAL -------------------------------------------------------
    window.showGolemVideoModal = function (url) {
        if (typeof MarsModal === 'undefined') return;
        MarsModal.show({
            title: 'Narog Awakening',
            size: 'lg',
            theme: 'aria',
            body: '<video src="' + url + '" style="width:100%;border-radius:12px;" playsinline autoplay loop controls></video>',
        });
    };

    // ----- PREVIEW GRID + RE-ROLL + LOCK-IN ---------------------------------
    let currentSources = null;   // last sources from /api/robot/preview
    let currentScientist = 'Scientist';
    let isLocked = false;

    const SCI_LINES_ROLL = [
        "Let me turn the pile over again…",
        "Different bones, different song. Hold still.",
        "Hmm. I can do better than that. Watch.",
        "Swapping the stones. Stand back.",
        "The vault has other ideas tonight.",
    ];
    const SCI_LINES_LOCK = [
        "These are the ones. Don't touch them.",
        "Locked. The Narog will remember every fragment.",
        "I've marked the five. Your call, Captain.",
    ];
    const SCI_LINES_IDLE = [
        "I've laid out five candidates. Click any piece to inspect it, or have me reconsider.",
        "Five from the vault. Tell me if I should reconsider.",
        "These five feel right. But the choice is yours.",
    ];
    function pickLine(arr) { return arr[Math.floor(Math.random() * arr.length)]; }

    function rarityClass(r) {
        r = (r || 'common').toLowerCase();
        return ['common','uncommon','rare','legendary'].indexOf(r) >= 0 ? r : 'common';
    }

    function setScientistName(name) {
        if (!name) return;
        currentScientist = name;
        document.querySelectorAll('#robot-sci-name, .robot-sci-name-inline').forEach(el => {
            el.textContent = name;
        });
    }

    function setSciLine(text, thinking) {
        const box = document.getElementById('robot-sci-dialog');
        const line = document.getElementById('robot-sci-line');
        if (line) line.textContent = text;
        if (box) box.classList.toggle('thinking', !!thinking);
    }

    function setProfile(profile) {
        if (!profile) return;
        const keys = ['combat', 'mining', 'science', 'exploration'];
        // Find the leading stat for highlight
        let leader = null, leaderVal = -1;
        keys.forEach(k => { if ((profile[k] || 0) > leaderVal) { leader = k; leaderVal = profile[k]; } });
        keys.forEach(k => {
            const row = document.querySelector('.robot-profile-row[data-stat="' + k + '"]');
            if (!row) return;
            const fill = row.querySelector('.robot-profile-fill');
            const pct = row.querySelector('.robot-profile-pct');
            const v = profile[k] || 0;
            if (fill) fill.style.width = v + '%';
            if (pct) pct.textContent = v + '%';
            row.classList.toggle('lean', k === leader);
        });
    }

    function renderPreviewGrid(sources) {
        const grid = document.getElementById('robot-preview-grid');
        if (!grid || !Array.isArray(sources)) return;
        const cards = grid.querySelectorAll('.robot-stage-card');
        cards.forEach((card, i) => {
            const src = sources[i];
            const srcEl = card.querySelector('.robot-stage-source');
            if (!src || !srcEl) return;
            card.classList.remove('mystery');
            const baseImg = card.querySelector('.robot-stage-base-img');
            if (baseImg) baseImg.classList.remove('mystery-img');
            const rc = rarityClass(src.rarity);
            const item = src.item_name || 'Unknown';
            const land = src.landmark_name || 'Unknown Site';

            // Composite: base stage icon + captain's item icon
            const composite = card.querySelector('.robot-stage-composite');
            const itemIcon = card.querySelector('.robot-stage-item-icon');
            const baseWrap = card.querySelector('.robot-stage-img-wrap');
            if (composite && itemIcon && src.item_image_url) {
                itemIcon.src = src.item_image_url;
                itemIcon.alt = item;
                composite.style.display = 'flex';
                if (baseWrap) baseWrap.style.display = 'none';
            } else if (composite) {
                composite.style.display = 'none';
                if (baseWrap) baseWrap.style.display = '';
            }

            srcEl.innerHTML = '<strong>' + item + '</strong><br><em>' + land + '</em>'
                + '<div class="robot-stage-rarity rarity-' + rc + '">' + rc + '</div>';
        });
    }

    function renderGateMsg(gate, errMsg) {
        const el = document.getElementById('robot-gate-msg');
        const rerollBtn = document.getElementById('robot-reroll-btn');
        const lockBtn = document.getElementById('robot-lockin-btn');
        if (!el) return;
        const blocked = gate && !gate.met;
        if (blocked) {
            el.style.display = 'block';
            el.textContent = (errMsg || ('Need ' + gate.min_legendary + ' legendary + ' + gate.min_rare + ' rare (have ' + gate.legendary_count + ' / ' + gate.rare_count + ').'));
        } else {
            el.style.display = 'none';
        }
        [rerollBtn, lockBtn].forEach(b => {
            if (!b) return;
            b.disabled = !!blocked;
            b.style.opacity = blocked ? '0.5' : '1';
        });
    }

    async function staggerReveal() {
        const cards = document.querySelectorAll('#robot-preview-grid .robot-stage-card');
        cards.forEach(c => { c.classList.remove('revealing'); });
        for (let i = 0; i < cards.length; i++) {
            cards[i].classList.add('revealing');
            await new Promise(r => setTimeout(r, 110));
        }
    }

    async function fetchPreview(isReroll) {
        const rerollBtn = document.getElementById('robot-reroll-btn');
        const lockBtn = document.getElementById('robot-lockin-btn');
        const cards = document.querySelectorAll('#robot-preview-grid .robot-stage-card');

        if (isReroll) {
            setSciLine(pickLine(SCI_LINES_ROLL), true);
            cards.forEach(c => c.classList.add('fading'));
            if (rerollBtn) rerollBtn.disabled = true;
            if (lockBtn) lockBtn.disabled = true;
            await new Promise(r => setTimeout(r, 260));
        }

        try {
            const r = await fetch('/api/robot/preview');
            const data = await r.json();
            if (data.scientist_name) setScientistName(data.scientist_name);
            renderGateMsg(data.gate, data.success ? null : data.error);
            if (data.success && data.sources) {
                currentSources = data.sources;
                renderPreviewGrid(data.sources);
                setProfile(data.stat_profile);
            }
        } catch (e) { /* ignore */ }
        finally {
            cards.forEach(c => c.classList.remove('fading'));
            if (isReroll) await staggerReveal();
            if (!isLocked) {
                if (rerollBtn) rerollBtn.disabled = false;
                if (lockBtn) lockBtn.disabled = false;
            }
            setSciLine(isReroll ? "There. Tell me what you think." : pickLine(SCI_LINES_IDLE), false);
        }
    }

    // ----- Item modal (MarsModal) -------------------------------------------
    // stageCtx (optional): { idx, key, label, part, tx_hash, forged } — present
    // when opened from the Build Manifest (post-forge). When absent, we're in
    // the pre-build preview and show the "locks in when you forge" footer.
    function showSourceModal(src, stageCtx) {
        if (typeof MarsModal === 'undefined' || !src) return;
        const rc = rarityClass(src.rarity);
        const weight = { legendary: 30, rare: 10, uncommon: 3, common: 1 }[rc] || 1;
        const rarityBlurb = {
            legendary: 'Dominates the silhouette — the defining feature of your Narog.',
            rare:      'Clearly fused into the plating as a bold, recognizable accent.',
            uncommon:  'Integrated into the armor as a distinct body detail.',
            common:    'A faint trace etched into the Narog\'s material.',
        }[rc] || '';
        const recDate = src.recovered_at ? new Date(src.recovered_at) : null;
        const recAt = recDate ? recDate.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '—';
        const daysAgo = recDate ? Math.max(0, Math.floor((Date.now() - recDate.getTime()) / 86400000)) : null;
        const recAgo = daysAgo === null ? '' : (daysAgo === 0 ? ' (today)' : ' (' + daysAgo + ' day' + (daysAgo === 1 ? '' : 's') + ' ago)');
        const coord = (src.lat != null && src.lon != null)
            ? (Number(src.lat).toFixed(4) + '°, ' + Number(src.lon).toFixed(4) + '°')
            : '—';
        const mapLink = (src.lat != null && src.lon != null)
            ? ' <a href="/expeditions?lat=' + src.lat + '&lon=' + src.lon + '&zoom=6&marker=' + encodeURIComponent(src.landmark_name || '') + '" style="color:var(--color-sepolia);font-size:11px">› view on map</a>'
            : '';
        const imgBlock = src.item_image_url
            ? '<div style="display:flex;justify-content:center;padding:8px 0;"><img src="' + src.item_image_url + '" alt="' + (src.item_name || '') + '" onclick="window.showImageModal && window.showImageModal(this.src)" style="max-width:280px;max-height:280px;border-radius:12px;box-shadow:0 0 32px rgba(168,85,247,0.45);background:rgba(168,85,247,0.06);cursor:pointer;"></div>'
            : '';

        const stageBlock = stageCtx ? ''
            + '<hr style="border-color:var(--border-default);opacity:0.3;margin:4px 0">'
            + '<div style="background:rgba(168,85,247,0.06);border-left:3px solid var(--color-sepolia);padding:8px 12px;border-radius:0 6px 6px 0">'
            +   '<div class="text-xs" style="color:var(--text-muted)">FORGED INTO</div>'
            +   '<div style="font-weight:700">Stage ' + stageCtx.idx + ' · ' + stageCtx.label + '</div>'
            +   '<div class="text-xs" style="color:var(--text-secondary);margin-top:2px">' + (stageCtx.part || '') + '</div>'
            + '</div>'
            : '';
        const txBlock = (stageCtx && stageCtx.tx_hash) ? ''
            + '<div><div class="text-xs" style="color:var(--text-muted)">LEDGER TX</div>'
            + '<div style="font-family:ui-monospace,Menlo,monospace;font-size:10px;letter-spacing:-0.01em;word-break:break-all;line-height:1.4">' + stageCtx.tx_hash + '</div></div>'
            : '';
        const footer = stageCtx
            ? '<div class="text-xs" style="color:var(--text-muted);font-style:italic">This discovery has been consumed and fused into your Narog — it will not appear in your inventory again. Click the item image for a full-screen view.</div>'
            : '<div class="text-xs" style="color:var(--text-muted);font-style:italic">If you lock in this build, this discovery will be fused into your Narog permanently.</div>';

        const body = ''
            + '<div style="display:flex;flex-direction:column;gap:10px;font-size:13px;">'
            + imgBlock
            + '<div><div class="text-xs" style="color:var(--text-muted)">ITEM</div><div style="font-size:20px;font-weight:800">' + (src.item_name || '—') + '</div></div>'
            + '<div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">'
            +   '<div class="robot-stage-rarity rarity-' + rc + '">' + rc + '</div>'
            +   '<div style="font-weight:700;color:#ffb454">Influence: ' + weight + ' pts</div>'
            + '</div>'
            + (rarityBlurb ? '<div class="text-xs" style="color:var(--text-secondary);line-height:1.5">' + rarityBlurb + '</div>' : '')
            + stageBlock
            + '<hr style="border-color:var(--border-default);opacity:0.3;margin:4px 0">'
            + '<div><div class="text-xs" style="color:var(--text-muted)">RECOVERED AT</div><div>' + (src.landmark_name || '—') + mapLink + '</div></div>'
            + '<div><div class="text-xs" style="color:var(--text-muted)">COORDINATES</div><div style="font-family:ui-monospace,Menlo,monospace">' + coord + '</div></div>'
            + '<div><div class="text-xs" style="color:var(--text-muted)">DATE RECOVERED</div><div>' + recAt + recAgo + '</div></div>'
            + '<div><div class="text-xs" style="color:var(--text-muted)">DISCOVERY ID</div><div style="font-family:ui-monospace,Menlo,monospace">#' + (src.discovery_id || '—') + '</div></div>'
            + txBlock
            + '<hr style="border-color:var(--border-default);opacity:0.3;margin:4px 0">'
            + footer
            + '</div>';
        MarsModal.show({
            title: src.item_name || 'Fragment',
            size: 'md',
            theme: 'aria',
            body: body,
        });
    }

    function showStageInfoModal(card) {
        const key = card.dataset.stageKey || '';
        const label = card.dataset.stageLabel || 'Stage';
        const part = card.dataset.stagePart || '';
        const idx = card.dataset.stageIdx || '—';
        const baseImg = card.querySelector('.robot-stage-base-icon, .robot-stage-base-img');
        const src = baseImg ? baseImg.src : '';
        const imgBlock = src
            ? '<div style="display:flex;justify-content:center;padding:8px 0;"><img src="' + src + '" alt="' + label + '" style="max-width:220px;max-height:220px;border-radius:12px;background:rgba(255,255,255,0.04);"></div>'
            : '';
        const body = ''
            + '<div style="display:flex;flex-direction:column;gap:10px;font-size:13px;">'
            + imgBlock
            + '<div><div class="text-xs" style="color:var(--text-muted)">STAGE</div><div style="font-size:18px;font-weight:800">' + idx + '. ' + label + '</div></div>'
            + '<div><div class="text-xs" style="color:var(--text-muted)">WHAT THIS STAGE BUILDS</div><div>' + part + '</div></div>'
            + '<hr style="border-color:var(--border-default);opacity:0.3;margin:4px 0">'
            + '<div class="text-xs" style="color:var(--text-muted);font-style:italic">The item paired with this stage (click the right-hand icon) will be fused into the ' + part + ' during forging.</div>'
            + '</div>';
        MarsModal.show({ title: label, size: 'md', theme: 'aria', body: body });
    }

    function wireCardClicks() {
        const grid = document.getElementById('robot-preview-grid');
        if (!grid) return;
        grid.addEventListener('click', (e) => {
            const card = e.target.closest('.robot-stage-card');
            if (!card) return;
            const role = e.target.dataset ? e.target.dataset.role : null;
            const idx = parseInt(card.dataset.stageIdx, 10);
            if (role === 'base') {
                showStageInfoModal(card);
                return;
            }
            if (role === 'item') {
                if (!Number.isFinite(idx) || !currentSources) return;
                showSourceModal(currentSources[idx - 1]);
                return;
            }
            // Click on label/source/card chrome → item modal (existing behavior)
            if (!Number.isFinite(idx) || !currentSources) return;
            showSourceModal(currentSources[idx - 1]);
        });
    }

    // ----- Lock-in toggle ----------------------------------------------------
    function setLocked(locked) {
        isLocked = locked;
        const previewActions = document.getElementById('robot-preview-actions');
        const lockedActions = document.getElementById('robot-locked-actions');
        const cards = document.querySelectorAll('#robot-preview-grid .robot-stage-card');
        if (previewActions) previewActions.style.display = locked ? 'none' : 'flex';
        if (lockedActions) lockedActions.style.display = locked ? 'flex' : 'none';
        cards.forEach(c => c.classList.toggle('locked', locked));
        if (locked) setSciLine(pickLine(SCI_LINES_LOCK), false);
        else setSciLine(pickLine(SCI_LINES_IDLE), false);
    }

    function wireReroll() {
        const grid = document.getElementById('robot-preview-grid');
        if (!grid) return;

        fetchPreview(false);
        wireCardClicks();

        const reroll = document.getElementById('robot-reroll-btn');
        if (reroll) reroll.addEventListener('click', () => fetchPreview(true));

        const lockBtn = document.getElementById('robot-lockin-btn');
        if (lockBtn) lockBtn.addEventListener('click', () => setLocked(true));

        const unlockBtn = document.getElementById('robot-unlock-btn');
        if (unlockBtn) unlockBtn.addEventListener('click', () => setLocked(false));
    }

    // ----- BUILD button -----------------------------------------------------
    function wireBuildButton() {
        const btn = document.getElementById('robot-build-btn');
        if (!btn) return;
        btn.addEventListener('click', async () => {
            btn.disabled = true;
            btn.style.opacity = '0.6';
            btn.textContent = 'Sourcing parts…';
            try {
                await postJSONSafe('/api/robot/build', currentSources ? { sources: currentSources } : {});
                if (typeof showToast === 'function') {
                    showToast('Construction started — first stage assembling now.', 'success', 'Narog');
                }
                setTimeout(() => { window.location.href = '/crew?tab=robot'; }, 250);
            } catch (e) {
                btn.disabled = false;
                btn.style.opacity = '1';
                btn.textContent = 'Begin Construction';
            }
        });
    }

    // ----- NAME SUGGESTIONS ---------------------------------------------------
    function renderNamePills(container, names) {
        const input = document.getElementById('robot-name-input');
        container.innerHTML = '';
        names.forEach(name => {
            const pill = document.createElement('button');
            pill.textContent = name;
            pill.style.cssText = 'background: var(--bg-secondary); border: 1px solid var(--border-default); color: var(--text-primary); padding: 6px 14px; border-radius: 20px; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.15s;';
            pill.addEventListener('mouseenter', () => { pill.style.borderColor = 'var(--color-sepolia)'; pill.style.background = 'rgba(168,85,247,0.15)'; });
            pill.addEventListener('mouseleave', () => { pill.style.borderColor = 'var(--border-default)'; pill.style.background = 'var(--bg-secondary)'; });
            pill.addEventListener('click', () => {
                if (input) input.value = name;
                container.querySelectorAll('button').forEach(b => { b.style.borderColor = 'var(--border-default)'; b.style.background = 'var(--bg-secondary)'; });
                pill.style.borderColor = 'var(--color-sepolia)';
                pill.style.background = 'rgba(168,85,247,0.2)';
            });
            container.appendChild(pill);
        });
    }

    function loadNameSuggestions() {
        const container = document.getElementById('golem-name-suggestions');
        if (!container) return;

        // Read pre-generated suggestions from BRIDGE first
        var names = (BRIDGE && BRIDGE.name_suggestions) || [];
        if (names.length) {
            renderNamePills(container, names);
            return;
        }
        // Fallback: fetch from API
        fetch('/api/robot/suggest_names', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
        .then(r => r.json())
        .then(data => { if (data.success && data.names) renderNamePills(container, data.names); })
        .catch(() => { container.innerHTML = '<div class="text-xs" style="color:var(--text-muted)">Could not load suggestions</div>'; });
    }

    // ----- NAME save --------------------------------------------------------
    function wireNameSave() {
        const input = document.getElementById('robot-name-input');
        const saveBtn = document.getElementById('robot-name-save-btn');
        if (!input || !saveBtn) return;

        const save = async () => {
            const name = (input.value || '').trim();
            if (!name) {
                if (typeof showToast === 'function') {
                    showToast('Name cannot be blank.', 'error', 'Narog');
                }
                return;
            }
            saveBtn.disabled = true;
            saveBtn.textContent = 'Saving…';
            try {
                await postJSONSafe('/api/robot/name', { name });
                if (typeof showToast === 'function') {
                    showToast('Narog named "' + name + '".', 'success', 'Narog');
                }
                // If naming card is visible, collapse it and reload to show inline name
                const namingCard = document.getElementById('golem-naming-card');
                if (namingCard) {
                    reloadSoon();
                } else {
                    saveBtn.textContent = 'Saved';
                    setTimeout(() => { saveBtn.disabled = false; saveBtn.textContent = 'Save'; }, 1500);
                }
            } catch (e) {
                saveBtn.disabled = false;
                saveBtn.textContent = 'Save';
            }
        };

        saveBtn.addEventListener('click', save);
        input.addEventListener('keydown', (e) => { if (e.key === 'Enter') save(); });
    }

    // ----- ROLE DIAL --------------------------------------------------------
    // Each value is mod-5, all four sum to 100. Adjusting one value rebalances
    // the others by stealing/donating to whichever currently has the most/least
    // headroom — keeps the dial honest without forcing the user to do mental math.
    const DIAL_KEYS = ['mining', 'exploration', 'science', 'combat'];
    const DIAL_STEP = 5;
    const DIAL_TOTAL = 100;
    let dialState = null;
    let dialSaveTimer = null;

    function readDialState() {
        const el = document.getElementById('robot-dial');
        if (!el) return null;
        try {
            const raw = JSON.parse(el.dataset.dial);
            const obj = {};
            DIAL_KEYS.forEach(k => { obj[k] = parseInt(raw[k], 10) || 0; });
            return obj;
        } catch (e) { return null; }
    }

    function renderDial() {
        if (!dialState) return;
        DIAL_KEYS.forEach(k => {
            const row = document.querySelector(`.robot-dial-row[data-key="${k}"]`);
            if (!row) return;
            const valueEl = row.querySelector('.robot-dial-value');
            if (valueEl) valueEl.textContent = dialState[k] + '%';
            const dec = row.querySelector('[data-action="dec"]');
            const inc = row.querySelector('[data-action="inc"]');
            if (dec) dec.disabled = dialState[k] <= 0;
            // Inc is disabled if there's nothing left to steal from the others
            const others = DIAL_KEYS.filter(x => x !== k).reduce((s, x) => s + dialState[x], 0);
            if (inc) inc.disabled = others < DIAL_STEP;
        });
        const status = document.getElementById('robot-dial-status');
        if (status) {
            const total = DIAL_KEYS.reduce((s, k) => s + dialState[k], 0);
            status.textContent = 'Total: ' + total + '%';
            status.style.color = (total === DIAL_TOTAL) ? 'var(--text-secondary)' : 'var(--color-error, #f87171)';
        }
    }

    function adjustDial(key, delta) {
        if (!dialState) return;
        const next = dialState[key] + delta;
        if (next < 0) return;
        // Find a counterparty to absorb the inverse delta. Prefer the largest
        // for inc (steal from the biggest), the smallest for dec (donate to
        // the one furthest behind).
        const others = DIAL_KEYS.filter(k => k !== key);
        let target;
        if (delta > 0) {
            target = others.reduce((best, k) => (dialState[k] > dialState[best] ? k : best), others[0]);
            if (dialState[target] < delta) return; // not enough to steal
        } else {
            target = others.reduce((best, k) => (dialState[k] < dialState[best] ? k : best), others[0]);
        }
        dialState[key] = next;
        dialState[target] -= delta;
        renderDial();
        scheduleDialSave();
    }

    function scheduleDialSave() {
        if (dialSaveTimer) clearTimeout(dialSaveTimer);
        dialSaveTimer = setTimeout(saveDial, 500);
    }

    async function saveDial() {
        if (!dialState) return;
        try {
            await postJSONSafe('/api/robot/dial', { dial: dialState });
            if (typeof showToast === 'function') {
                showToast('Role dial saved.', 'success', 'Narog');
            }
            const status = document.getElementById('robot-dial-status');
            if (status) {
                status.textContent = 'Saved · Total: 100%';
                setTimeout(() => { if (status) status.textContent = 'Total: 100%'; }, 1500);
            }
        } catch (e) {
            // postJSONSafe already toasted; revert by reloading server state
            reloadSoon();
        }
    }

    function wireDial() {
        const dialEl = document.getElementById('robot-dial');
        if (!dialEl) return;
        dialState = readDialState();
        if (!dialState) return;

        dialEl.querySelectorAll('.robot-dial-row').forEach(row => {
            const key = row.dataset.key;
            row.querySelectorAll('.robot-dial-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const action = btn.dataset.action;
                    adjustDial(key, action === 'inc' ? DIAL_STEP : -DIAL_STEP);
                });
            });
        });
        renderDial();
    }

    // ----- CINEMATIC (Step 6) -----------------------------------------------
    // When the server tells us show_cinematic=true (build just completed and
    // the celebration hasn't been played yet), fire EpicReveal — the same
    // generalized cinematic framework used for ARIA bonds + Signal final.
    // After it plays we POST cinematic_played so it never replays.
    function fireGolemCinematic(markPlayed) {
        if (typeof window.EpicReveal === 'undefined') return;
        const heroImg = document.getElementById('robot-hero-img');
        const robotImage = heroImg ? heroImg.src : '';
        const existingName = (BRIDGE && BRIDGE.robot_name) || '';

        // If unnamed, show naming UI inside the cinematic
        var infoBlock;
        if (!existingName && markPlayed) {
            infoBlock = {
                html: '<div class="er-info-label">NAME YOUR NAROG</div>'
                    + '<div id="er-name-pills" style="display:flex;flex-wrap:wrap;gap:6px;justify-content:center;margin:6px 0;">'
                    + '<span style="color:rgba(255,255,255,0.3);font-size:12px;">Loading suggestions...</span></div>'
                    + '<div style="display:flex;gap:8px;margin-top:8px;justify-content:center;">'
                    + '<input id="er-name-input" type="text" placeholder="Or type your own..." '
                    + 'style="background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.2);color:#fff;'
                    + 'padding:8px 12px;border-radius:8px;font-size:14px;width:160px;outline:none;" />'
                    + '<button id="er-name-save" style="background:rgba(168,85,247,0.3);border:1px solid rgba(168,85,247,0.5);'
                    + 'color:#c084fc;padding:8px 16px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;">Submit</button>'
                    + '</div>'
                    + '<div id="er-name-detail" style="display:none;"></div>',
            };
        } else {
            infoBlock = {
                label: 'CONSTRUCTION COMPLETE',
                detail: (existingName || 'Your Narog') + ' — forged from 5 real expedition fragments',
            };
        }

        EpicReveal.show({
            title: 'NAROG AWAKENED',
            lines: [
                { text: '*stone shifts... crystals pulse*', cls: 'static-crackle', sound: 'stoneGrind' },
                { text: 'Five fragments. Five sites.', sound: 'deepRumble' },
                { text: 'Five hands that recovered them — yours.', sound: 'crystalChime' },
                { text: 'Your Narog stirs to life.', cls: 'emphasis', sound: 'golemAwaken' },
            ],
            revealSound: 'playGolemAwaken',
            image: robotImage,
            info: infoBlock,
            revelation: {
                label: 'NEW CREW MEMBER',
                text: 'Your fourth crew member has awakened. Tune their role dial to direct their effort.',
            },
            actions: [
                { label: 'Continue', cls: 'primary' },
            ],
            onClose: function () {
                if (markPlayed) {
                    fetch('/api/robot/cinematic_played', { method: 'POST' }).catch(() => {});
                    setTimeout(function() { window.location.href = '/crew?tab=robot'; }, 250);
                }
            },
        });

        // Wire up naming UI inside the cinematic if present
        if (!existingName && markPlayed) wireEpicNaming();
    }

    function wireEpicNaming() {
        // Read pre-generated suggestions from BRIDGE (generated at build time)
        var names = (BRIDGE && BRIDGE.name_suggestions) || [];
        var container = document.getElementById('er-name-pills');
        var input = document.getElementById('er-name-input');

        if (container && names.length) {
            container.innerHTML = '';
            names.forEach(function(name) {
                var pill = document.createElement('button');
                pill.textContent = name;
                pill.style.cssText = 'background:rgba(168,85,247,0.15);border:1px solid rgba(168,85,247,0.4);color:#c084fc;'
                    + 'padding:5px 12px;border-radius:16px;font-size:12px;font-weight:600;cursor:pointer;transition:all 0.15s;';
                pill.addEventListener('click', function() {
                    if (input) input.value = name;
                    container.querySelectorAll('button').forEach(function(b) {
                        b.style.borderColor = 'rgba(168,85,247,0.4)';
                        b.style.background = 'rgba(168,85,247,0.15)';
                    });
                    pill.style.borderColor = '#a855f7';
                    pill.style.background = 'rgba(168,85,247,0.3)';
                });
                container.appendChild(pill);
            });
        } else if (container) {
            // Fallback: fetch live if no pre-generated suggestions
            fetch('/api/robot/suggest_names', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.success || !data.names) return;
                container.innerHTML = '';
                data.names.forEach(function(name) {
                    var pill = document.createElement('button');
                    pill.textContent = name;
                    pill.style.cssText = 'background:rgba(168,85,247,0.15);border:1px solid rgba(168,85,247,0.4);color:#c084fc;'
                        + 'padding:5px 12px;border-radius:16px;font-size:12px;font-weight:600;cursor:pointer;transition:all 0.15s;';
                    pill.addEventListener('click', function() {
                        if (input) input.value = name;
                        container.querySelectorAll('button').forEach(function(b) {
                            b.style.borderColor = 'rgba(168,85,247,0.4)';
                            b.style.background = 'rgba(168,85,247,0.15)';
                        });
                        pill.style.borderColor = '#a855f7';
                        pill.style.background = 'rgba(168,85,247,0.3)';
                    });
                    container.appendChild(pill);
                });
            }).catch(function() {});
        }

        // Wire save button
        var saveBtn = document.getElementById('er-name-save');
        var input = document.getElementById('er-name-input');
        if (!saveBtn || !input) return;

        var doSave = function() {
            var name = (input.value || '').trim();
            if (!name) return;
            saveBtn.disabled = true;
            saveBtn.textContent = 'Saving...';
            postJSONSafe('/api/robot/name', { name: name }).then(function() {
                // Replace naming UI with the saved name
                var info = document.querySelector('.er-info');
                if (info) {
                    info.innerHTML = '<div class="er-info-label">CONSTRUCTION COMPLETE</div>'
                        + '<div class="er-info-detail">' + name + ' — forged from 5 real expedition fragments</div>';
                }
            }).catch(function() {
                saveBtn.disabled = false;
                saveBtn.textContent = 'Name';
            });
        };
        saveBtn.addEventListener('click', doSave);
        input.addEventListener('keydown', function(e) { if (e.key === 'Enter') doSave(); });
    }

    function maybeFireRobotCinematic() {
        if (!BRIDGE || !BRIDGE.show_cinematic) return;
        if (typeof window.EpicReveal === 'undefined') {
            // Do NOT auto-POST cinematic_played here — that permanently loses
            // the reveal if epic-reveal.js hasn't parsed yet. Leave
            // show_cinematic=true so the next page load retries.
            console.error('[crew-robot] EpicReveal missing at fire time; skipping (will retry next load)');
            return;
        }
        fireGolemCinematic(true);
    }

    function wireReplayButton() {
        const btn = document.getElementById('robot-replay-cinematic');
        if (!btn) return;
        btn.addEventListener('click', () => fireGolemCinematic(false));
    }

    // ----- VIDEO GENERATION (auto + regen) -------------------------------------
    // When the narog is complete but has no video yet, kick off generation
    // immediately and poll for completion. On error, surface the real message
    // from the server and offer a Retry button.
    function pollVideoStatus(statusEl) {
        var poll = setInterval(async function() {
            try {
                var r = await fetch('/api/robot/video_status');
                var s = await r.json();
                if (s && s.url) {
                    clearInterval(poll);
                    if (statusEl) statusEl.innerHTML = '<strong>Awakening video ready!</strong>';
                    reloadSoon();
                } else if (s && s.error) {
                    clearInterval(poll);
                    showVideoError(statusEl, s.error);
                }
            } catch (e) { /* keep polling */ }
        }, 5000);
    }

    function showVideoError(statusEl, errMsg) {
        if (!statusEl) return;
        statusEl.innerHTML = '<div style="color:#fca5a5;font-weight:700;">Video generation failed</div>'
            + '<div class="text-xs" style="color:var(--text-secondary);margin-top:4px;word-break:break-word;">'
            + String(errMsg || 'unknown error').slice(0, 240)
            + '</div>'
            + '<button id="robot-video-retry-btn" style="margin-top:8px;background:rgba(239,68,68,0.15);color:#fca5a5;border:1px solid rgba(239,68,68,0.45);border-radius:8px;padding:6px 14px;font-size:11px;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;cursor:pointer;">↻ Retry</button>';
        var btn = document.getElementById('robot-video-retry-btn');
        if (btn) btn.addEventListener('click', function() { triggerVideoRegen(statusEl, btn); });
    }

    async function triggerVideoRegen(statusEl, btn) {
        if (btn) { btn.disabled = true; btn.textContent = 'Starting...'; }
        if (statusEl) statusEl.innerHTML = 'Generating Awakening Video…<div class="text-xs" style="opacity:0.7;margin-top:4px;">~60 seconds</div>';
        try {
            await postJSONSafe('/api/robot/reset_video', {});
            pollVideoStatus(statusEl);
        } catch (e) {
            showVideoError(statusEl, (e && e.message) || 'request failed');
        }
    }

    function autoStartVideoGen() {
        var wrap = document.getElementById('robot-hero-awaiting-video');
        if (!wrap) return;  // only present when is_complete && !video_url
        var status = document.getElementById('robot-video-loading');
        (async function() {
            try {
                var data = await postJSONSafe('/api/robot/generate_video', {});
                if (data && data.already_exists) { reloadSoon(); return; }
                if (data && data.error) { showVideoError(status, data.error); return; }
            } catch (e) { /* fall through to polling */ }
            pollVideoStatus(status);
        })();
    }

    function wireRegenVideoButton() {
        var btn = document.getElementById('robot-regen-video-btn');
        if (!btn) return;
        btn.addEventListener('click', function() {
            if (!confirm) { /* should not happen, but guard */ }
            // Use MarsModal pattern — no native confirm() per project rules.
            if (typeof MarsModal === 'undefined') return;
            var body = '<div style="font-size:13px;color:var(--text-secondary);line-height:1.55;">'
                + 'Regenerate the awakening video? The forged Narog + stage log stay intact — only the Wan animation re-runs (~60s).'
                + '</div>';
            var footer = '<div style="display:flex;gap:10px;justify-content:flex-end;">'
                + '<button id="regen-cancel" style="background:var(--bg-secondary);color:var(--text-primary);border:1px solid var(--border-default);border-radius:8px;padding:10px 20px;font-weight:700;cursor:pointer;">Cancel</button>'
                + '<button id="regen-confirm" style="background:rgba(168,85,247,0.2);color:var(--color-sepolia);border:1px solid rgba(168,85,247,0.55);border-radius:8px;padding:10px 20px;font-weight:700;cursor:pointer;">↻ Regenerate</button>'
                + '</div>';
            MarsModal.show({ title: 'Regenerate Awakening Video', size: 'md', theme: 'aria', body: body, footer: footer });
            setTimeout(function() {
                var cancel = document.getElementById('regen-cancel');
                var confirmBtn = document.getElementById('regen-confirm');
                if (cancel) cancel.addEventListener('click', function() { MarsModal.hide(); });
                if (confirmBtn) confirmBtn.addEventListener('click', async function() {
                    confirmBtn.disabled = true;
                    confirmBtn.textContent = 'Starting...';
                    try {
                        await postJSONSafe('/api/robot/reset_video', {});
                        MarsModal.hide();
                        // Reload so the hero drops back to "generating..." placeholder
                        // and autoStartVideoGen takes over via pollVideoStatus.
                        window.location.reload();
                    } catch (e) {
                        confirmBtn.disabled = false;
                        confirmBtn.textContent = '↻ Regenerate';
                    }
                });
            }, 0);
        });
    }

    function wireResetButton() {
        const btn = document.getElementById('robot-reset-btn');
        if (!btn) return;
        btn.addEventListener('click', () => {
            const body = '<div style="font-size:13px;color:var(--text-secondary);line-height:1.55;">'
                + 'Wipe this captain\'s Narog and re-forge from scratch? The Kontext image chain will regenerate with fresh picks. '
                + '<br><br><em style="color:var(--text-muted);">QA use only — the existing robot row and stage log will be deleted.</em>'
                + '</div>';
            const footer = '<div style="display:flex;gap:10px;justify-content:flex-end;">'
                + '<button id="robot-reset-cancel" style="background:var(--bg-secondary);color:var(--text-primary);border:1px solid var(--border-default);border-radius:8px;padding:10px 20px;font-weight:700;cursor:pointer;">Cancel</button>'
                + '<button id="robot-reset-confirm" style="background:rgba(239,68,68,0.2);color:#fca5a5;border:1px solid rgba(239,68,68,0.55);border-radius:8px;padding:10px 20px;font-weight:700;cursor:pointer;">↻ Start Over</button>'
                + '</div>';
            MarsModal.show({ title: 'QA — Start Over', size: 'md', theme: 'aria', body, footer });
            setTimeout(() => {
                const cancel = document.getElementById('robot-reset-cancel');
                const confirmBtn = document.getElementById('robot-reset-confirm');
                if (cancel) cancel.addEventListener('click', () => MarsModal.hide());
                if (confirmBtn) confirmBtn.addEventListener('click', async () => {
                    confirmBtn.disabled = true;
                    confirmBtn.textContent = '↻ Resetting...';
                    try {
                        await postJSONSafe('/api/robot/reset', {});
                        MarsModal.hide();
                        window.location.href = '/crew?tab=robot';
                    } catch (e) {
                        confirmBtn.disabled = false;
                        confirmBtn.textContent = '↻ Start Over';
                    }
                });
            }, 0);
        });
    }

    // ----- Manifest card clicks (post-forge Build Manifest) -----------------
    function wireManifestClicks() {
        // Build Manifest cards are rendered server-side with data-source JSON +
        // stage context. Clicking anywhere on the card opens the rich modal.
        const cards = document.querySelectorAll('.robot-stage-card[data-source]');
        cards.forEach(card => {
            if (card.closest('#robot-preview-grid')) return;  // pre-build grid has its own handler
            card.addEventListener('click', () => {
                let src = null;
                try { src = JSON.parse(card.dataset.source || '{}'); } catch (e) { /* noop */ }
                if (!src || !src.item_name) return;
                const stageCtx = {
                    idx: card.dataset.stageIdx,
                    key: card.dataset.stageKey,
                    label: card.dataset.stageLabel,
                    part: card.dataset.stagePart,
                    tx_hash: card.dataset.txHash || '',
                };
                showSourceModal(src, stageCtx);
            });
        });
    }

    function wireRetryForgeButton() {
        const btn = document.getElementById('robot-retry-forge-btn');
        if (!btn) return;
        btn.addEventListener('click', async () => {
            btn.disabled = true;
            btn.style.opacity = '0.6';
            btn.textContent = 'Retrying…';
            try {
                const r = await fetch('/api/robot/retry_forge', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: '{}',
                });
                const data = await r.json();
                if (data && data.success) {
                    if (typeof showToast === 'function') {
                        showToast('Forge retrying — image-gen running again.', 'info', 'Narog');
                    }
                    setTimeout(() => { window.location.href = '/crew?tab=robot'; }, 400);
                } else {
                    btn.disabled = false;
                    btn.style.opacity = '1';
                    btn.textContent = '↻ Retry Forge';
                    if (typeof showToast === 'function') {
                        showToast(data.error || 'Retry failed', 'error', 'Narog');
                    }
                }
            } catch (e) {
                btn.disabled = false;
                btn.style.opacity = '1';
                btn.textContent = '↻ Retry Forge';
            }
        });
    }

    // ----- INIT -------------------------------------------------------------
    document.addEventListener('DOMContentLoaded', () => {
        wireBuildButton();
        wireReroll();
        wireResetButton();
        wireNameSave();
        loadNameSuggestions();
        wireDial();
        startCountdown();
        wireReplayButton();
        autoStartVideoGen();
        wireRegenVideoButton();
        wireRetryForgeButton();
        wireManifestClicks();
        maybeFireRobotCinematic();
    });
})();
