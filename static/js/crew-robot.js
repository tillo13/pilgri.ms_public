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
        // 2026-04-30: stats are flat 5/100 base for every Narog. Preview UI
        // shows the static baseline; no shape variance per roll. The 4 rows
        // are pre-rendered server-side at 5%, so this is a no-op now.
        if (!profile) return;
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

    // ----- ROLE DIAL — rotary knobs (visual chrome lives in narog-knob.js) --
    // 4 dials map to Luke's brainstorm §4. Phase 1 unlocks only `exploration`;
    // Phase 3/4/5 unlock the others. Locked + solo-pinned dials open a modal.
    // Sum across UNLOCKED dials must always equal 100; rebalancing happens here.
    const DIAL_KEYS = ['exploration', 'logistics', 'research', 'expeditions'];
    const DIAL_STEP = 5;
    const DIAL_TOTAL = 100;
    const DIAL_PHASES = {
        exploration: 'Phase 1 — Built',
        logistics:   'Phase 3 — Circuits',
        research:    'Phase 4 — Core',
        expeditions: 'Phase 5 — Crystal Resonance',
    };
    const DIAL_DESCRIPTIONS = {
        exploration: 'Speeds up autonomous trail building while you’re away. The base Exploration stat × this dial % = your Narog’s effective trail bonus.',
        logistics:   'Speeds up Depot and Robotics-Lab build times. Higher allocation = bigger reduction on every active build.',
        research:    'Helps the Scientist run experiments faster. Boosts SV/hr and accelerates active research.',
        expeditions: 'Sends your Narog on solo scout runs while you’re offline — brings back shards + discoveries from beyond your current range.',
    };

    let dialState = null;          // { key: pct } — shared across rows
    let allocInstances = {};        // { key: NarogAllocator handle }
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

    function isUnlocked(key) {
        const inst = allocInstances[key];
        return inst && inst.el.dataset.locked !== 'true';
    }

    // Apply state to all allocator instances + active/idle summary.
    function repaint() {
        if (!dialState) return;
        DIAL_KEYS.forEach(k => {
            if (allocInstances[k]) allocInstances[k].setValue(dialState[k]);
        });
        const status = document.getElementById('robot-dial-status');
        if (status) {
            const total = DIAL_KEYS.reduce((s, k) => s + dialState[k], 0);
            const idle = Math.max(0, 100 - total);
            status.textContent = `Active ${total}% · Idle ${idle}%`;
            status.style.color = 'var(--text-secondary)';
        }
    }

    // Set `key` to `newVal`. Two regimes:
    //   1. Solo mode (only this row unlocked): set freely 0-100, no rebalance.
    //      Unallocated time is "idle" — the robot just doesn't burn cycles.
    //      Lets captains preview the mechanic at Phase 1 (e.g. set 38% to see
    //      ~1.9% effective trail bonus on a 5/100 base).
    //   2. Multi-row mode (2+ unlocked): rebalance across other unlocked rows
    //      to keep sum ≤ 100. Adding to this row steals from largest others;
    //      subtracting donates to smallest. Sum can stay below 100 (idle time).
    function setDialValue(key, newVal) {
        if (!dialState || !isUnlocked(key)) return;
        newVal = Math.max(0, Math.min(100, Math.round(newVal / DIAL_STEP) * DIAL_STEP));
        const cur = dialState[key];
        if (newVal === cur) return;
        const others = DIAL_KEYS.filter(k => k !== key && isUnlocked(k));

        if (!others.length) {
            // Solo mode: freely settable 0-100. No rebalance, no clamp on total.
            dialState[key] = newVal;
        } else {
            // Multi-row mode: enforce sum-across-unlocked ≤ 100.
            const otherSum = others.reduce((s, k) => s + dialState[k], 0);
            const headroom = 100 - otherSum;
            if (newVal > headroom) newVal = headroom;
            dialState[key] = newVal;
            // No auto-redistribute when subtracting — let the freed % stay idle.
            // Captain can manually pull it into another row if they want it used.
        }
        repaint();
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
                const orig = status.textContent;
                status.textContent = 'Saved · ' + orig;
                setTimeout(() => { if (status) repaint(); }, 1500);
            }
        } catch (e) {
            reloadSoon();
        }
    }

    // Modal explaining the Base X/100 stat system — universal, same content
    // for all 4 rows. Triggered by clicking the "Base X/100" pill on any row.
    function showBaseStatModal() {
        if (typeof MarsModal === 'undefined' || !MarsModal.show) return;
        MarsModal.show({
            title: 'Narog Base Stats',
            body: `
                <div style="font-size:13px; color:var(--text-secondary); line-height:1.7;">
                    <p style="margin:0 0 12px;">Every Narog starts at <strong style="color:#ffc88a;">5/100</strong> in all four stats — <strong>Exploration</strong>, <strong>Logistics</strong>, <strong>Research</strong>, <strong>Expeditions</strong>. The number is the cap; the allocation % below is how much of that cap is being applied.</p>
                    <p style="margin:0 0 12px;"><strong style="color:var(--text-primary);">Effective bonus = Base × allocation %.</strong> So 100% of 5/100 = an effective 5; 50% of 5/100 = 2.5. That number drives every passive bonus your Narog produces.</p>
                    <p style="margin:0 0 12px;">As you upgrade <strong>Depot</strong> and <strong>Robotics Lab</strong> buildings, the base stats rise toward 100. A fully built-out Narog might land near 55/100 in each stat — at which point 100% allocation = 55× the current passive bonus.</p>
                    <div style="background:rgba(0,0,0,0.3); border:1px solid var(--border-default); border-radius:8px; padding:10px 12px; font-size:12px; color:var(--text-muted); margin-top:12px;">
                        <strong style="color:#ffc88a;">In progress:</strong> Luke is finalizing which buildings raise which stats and by how much (tracked in <code>#1436</code>). Right now every Narog is at 5/100 across the board — the dial mechanic works end-to-end so you can see how an allocation translates to live km/day on the home page.
                    </div>
                </div>
            `,
        });
    }

    function showLockedDialModal(key) {
        if (typeof MarsModal === 'undefined' || !MarsModal.show) return;
        const titleMap = {
            logistics:   'Logistics (locked)',
            research:    'Research (locked)',
            expeditions: 'Expeditions (locked)',
        };
        const rowsHtml = DIAL_KEYS.map(k => {
            const active = (k === key) ? ' active' : '';
            return `<div class="na-modal-row${active}">
                <div style="flex:1;">
                    <strong>${k.charAt(0).toUpperCase() + k.slice(1)}</strong>
                    <span style="color:var(--text-muted); font-size:11px; margin-left:6px;">${DIAL_PHASES[k]}</span>
                    <div style="font-size:12px; color:var(--text-secondary); margin-top:4px; line-height:1.5;">${DIAL_DESCRIPTIONS[k] || ''}</div>
                </div>
            </div>`;
        }).join('');
        MarsModal.show({
            title: titleMap[key] || 'Dial info',
            body: `
                <div style="font-size:12px; color:var(--text-secondary); line-height:1.6; margin-bottom:8px;">
                    Your Narog can only build trails right now. The other three rows unlock as you upgrade your Robotics Lab and complete later phases. Here's what each will do:
                </div>
                <div class="na-modal-list">${rowsHtml}</div>
                <div style="font-size:10px; color:var(--text-muted); margin-top:10px; text-align:center;">
                    Phase &amp; bonus formulas: TBD — Luke is finalizing the Depot upgrade matrix.
                </div>
            `,
        });
    }

    // Spawn a NarogAllocator into each .na-card slot using server-rendered
    // config (data-key, data-locked, data-unlock-phase). The card supplies
    // header + description; we inject only the bar widget into .na-slot.
    function wireDial() {
        const dialEl = document.getElementById('robot-dial');
        if (!dialEl || typeof NarogAllocator === 'undefined') return;
        dialState = readDialState();
        if (!dialState) return;

        const cards = Array.from(dialEl.querySelectorAll('.na-card'));

        cards.forEach(card => {
            const key = card.dataset.key;
            const slot = card.querySelector('.na-slot');
            if (!slot) return;
            const cardLocked = card.dataset.locked === 'true';

            allocInstances[key] = NarogAllocator.create({
                container: slot,
                key,
                value: dialState[key] || 0,
                locked: cardLocked,
                ariaLabel: `${key} role allocation`,
                onChange: (newPct) => setDialValue(key, newPct),
            });

            // Base-stat pill is clickable on every row — opens the universal
            // explainer about the 5/100 system. Stop propagation so it doesn't
            // also fire the locked-card click handler below.
            const statPill = card.querySelector('.na-row-stat');
            if (statPill) {
                statPill.addEventListener('click', (e) => {
                    e.stopPropagation();
                    showBaseStatModal();
                });
            }

            if (cardLocked) {
                card.classList.add('is-locked');
                // Click anywhere ELSE on a locked card opens the locked-row modal
                card.addEventListener('click', () => showLockedDialModal(key));
            }
        });
        repaint();
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
        // stage context. Each card has TWO clickable icons:
        //   • base icon (data-role="base") → stage info modal (what this stage builds)
        //   • item icon (data-role="item") → source modal (which discovery + ledger tx)
        // Clicks on the label / source text / card chrome default to the source modal
        // because that's what captains expect from the prior single-click behavior.
        const cards = document.querySelectorAll('.robot-stage-card[data-source]');
        cards.forEach(card => {
            if (card.closest('#robot-preview-grid')) return;  // pre-build grid has its own handler
            card.addEventListener('click', (e) => {
                let src = null;
                try { src = JSON.parse(card.dataset.source || '{}'); } catch (err) { /* noop */ }
                const stageCtx = {
                    idx: card.dataset.stageIdx,
                    key: card.dataset.stageKey,
                    label: card.dataset.stageLabel,
                    part: card.dataset.stagePart,
                    tx_hash: card.dataset.txHash || '',
                };
                const role = e.target && e.target.dataset ? e.target.dataset.role : null;
                if (role === 'base') {
                    showStageInfoModal(card);
                    return;
                }
                // role === 'item' OR any other click on the card → source modal
                if (!src || !src.item_name) return;
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
    // ----- RECALIBRATION (re-pick / re-roll image / re-roll video / lock-in) ----
    // 2026-04-30: post-canonical Narog adjustments. Test-mode pricing (1% of
    // production) lets Andy + Luke iterate cheaply before we open this for
    // real captains. Click = fire (no confirmation modal — cost + counter
    // already visible on the button itself).
    let recalState = null;
    let recalCountdownTimer = null;

    function fmtCost(cost) {
        if (!cost) return 'Free';
        if (cost.shards && cost.sv) return `${cost.shards} shards + ${cost.sv} SV`;
        if (cost.shards) return `${cost.shards} shards`;
        if (cost.sv) return `${cost.sv} SV`;
        return 'Free';
    }

    async function loadRecalState() {
        try {
            const r = await fetch('/api/robot/recalibration_state', { credentials: 'same-origin' });
            const j = await r.json();
            recalState = (j && j.success) ? j.state : null;
        } catch (e) { recalState = null; }
        renderRecal();
    }

    function renderRecal() {
        const card = document.getElementById('narog-recal-card');
        if (!card) return;
        if (!recalState || !recalState.available) {
            card.style.display = 'none';
            return;
        }
        card.style.display = '';
        // Recalibration card has only repick + reroll_image (no New Awakening
        // button — video re-render is surfaced via the "Bring to Life" CTA in
        // the hero area when video_url is missing).
        ['repick','reroll_image'].forEach(action => {
            const btn = card.querySelector(`.narog-recal-action[data-action="${action}"]`);
            if (!btn) return;
            const a = recalState.actions[action];
            if (!a) return;
            btn.querySelector('.cost-shards').textContent = fmtCost(a.cost);
            btn.querySelector('.cost-counter').textContent = `${a.used}/${a.cap} used`;
            btn.disabled = a.remaining <= 0;
        });

        // Update the Bring-to-Life CTA cost (only present in DOM if video missing)
        const briefCta = document.getElementById('robot-bring-to-life-cta');
        const briefCost = document.getElementById('robot-bring-to-life-cost');
        if (briefCta && briefCost && recalState.actions.reroll_video) {
            const v = recalState.actions.reroll_video;
            briefCost.textContent = `${fmtCost(v.cost)} · ${v.used}/${v.cap} used`;
            if (v.remaining <= 0) {
                briefCta.style.opacity = '0.5';
                briefCta.style.cursor = 'not-allowed';
            }
        }

        const lockBtn = card.querySelector('.narog-recal-lockin-big[data-action="lock_in"]');
        if (lockBtn) lockBtn.disabled = !!recalState.locked;

        // 72hr countdown banner
        const banner = document.getElementById('narog-recal-window-banner');
        if (banner) {
            if (recalState.window_seconds_remaining != null && !recalState.locked) {
                banner.style.display = '';
                paintCountdown();
                if (recalCountdownTimer) clearInterval(recalCountdownTimer);
                recalCountdownTimer = setInterval(paintCountdown, 1000);
            } else {
                banner.style.display = 'none';
                if (recalCountdownTimer) { clearInterval(recalCountdownTimer); recalCountdownTimer = null; }
            }
        }
    }

    function paintCountdown() {
        if (!recalState || recalState.window_seconds_remaining == null) return;
        const el = document.getElementById('narog-recal-countdown');
        if (!el) return;
        // Tick down locally (integer seconds) between server polls
        recalState.window_seconds_remaining = Math.max(0, Math.floor(recalState.window_seconds_remaining) - 1);
        const s = recalState.window_seconds_remaining;
        const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
        el.textContent = `${h}h ${m}m ${sec}s`;
        if (s <= 0) loadRecalState();  // window expired — re-sync server state
    }

    // Build a rich "review everything" modal for Lock In — captain sees the
    // full Narog state (image, components, stats, allocation, video) before
    // committing. The 3 reroll actions DON'T need this — their costs are on
    // the button and they're cheap to undo by re-rolling again.
    async function showLockInReviewModal() {
        if (typeof MarsModal === 'undefined' || !MarsModal.show) return true;
        let robot = null;
        try {
            const r = await fetch('/api/robot/status', { credentials: 'same-origin' });
            const j = await r.json();
            robot = j && j.data && j.data.robot;
        } catch (e) {}
        if (!robot) return false;

        const sources = Array.isArray(robot.stage_sources) ? robot.stage_sources : [];
        const dial = robot.dial || {};
        const stats = {
            exploration: robot.stat_exploration ?? 5,
            logistics:   robot.stat_logistics   ?? 5,
            research:    robot.stat_research    ?? 5,
            expeditions: robot.stat_expeditions ?? 5,
        };
        const totalAllocation = ['exploration','logistics','research','expeditions']
            .reduce((s, k) => s + (parseInt(dial[k], 10) || 0), 0);
        const idle = Math.max(0, 100 - totalAllocation);

        const rarityBadge = (rarity) => {
            const r = (rarity || 'common').toLowerCase();
            const colors = { legendary:'#f59e0b', rare:'#3b82f6', uncommon:'#22c55e', common:'#94a3b8' };
            return `<span style="display:inline-block; padding:1px 6px; border-radius:3px; font-size:9px; font-weight:800; letter-spacing:0.06em; text-transform:uppercase; background:${colors[r] || '#94a3b8'}33; color:${colors[r] || '#94a3b8'}; border:1px solid ${colors[r] || '#94a3b8'}66;">${r}</span>`;
        };

        const heroImg = robot.current_image_url
            ? `<img src="${robot.current_image_url}" alt="" style="width:100%; max-width:280px; border-radius:10px; border:1px solid rgba(255,200,140,0.3); display:block; margin:0 auto;"/>`
            : '<div style="font-size:11px; color:var(--text-muted); text-align:center;">No image yet — re-roll image first to lock in with one.</div>';

        const sourcesList = sources.length
            ? sources.map(s => `
                <div style="display:flex; align-items:center; gap:10px; padding:8px 10px; background:rgba(0,0,0,0.3); border-radius:6px; border:1px solid var(--border-default);">
                    ${s.item_image_url ? `<img src="${s.item_image_url}" alt="" style="width:32px; height:32px; border-radius:4px; flex-shrink:0;"/>` : ''}
                    <div style="flex:1; min-width:0;">
                        <div style="font-size:12px; font-weight:700; color:var(--text-primary);">${s.item_name || 'Unknown'}</div>
                        <div style="font-size:10px; color:var(--text-muted);">${s.landmark_name || '—'}</div>
                    </div>
                    ${rarityBadge(s.rarity)}
                </div>
            `).join('')
            : '<div style="font-size:11px; color:var(--text-muted);">No components.</div>';

        const allocRow = (k, label) => {
            const pct = parseInt(dial[k], 10) || 0;
            const stat = stats[k];
            const active = (stat * pct / 100).toFixed(1);
            return `<div style="display:flex; justify-content:space-between; font-size:11px; padding:3px 0;">
                <span style="color:var(--text-secondary);">${label}</span>
                <span style="color:var(--text-primary); font-variant-numeric:tabular-nums;">${pct}% of ${stat} = <strong style="color:#ffc88a;">${active}</strong></span>
            </div>`;
        };

        // If video is missing, lock-in will auto-render it (Wan call) and
        // charge the reroll_video cost. Disclose this clearly so the captain
        // isn't surprised by the deduction.
        const videoCost = recalState && recalState.actions && recalState.actions.reroll_video
            ? recalState.actions.reroll_video.cost : null;
        const videoLine = robot.video_url
            ? '<span style="color:#22c55e;">✓ rendered</span>'
            : `<span style="color:#fbbf24;">✗ not yet rendered — the scientist will record it now for <strong style="color:#ffc88a;">${fmtCost(videoCost)}</strong> when you lock in.</span>`;

        return new Promise((resolve) => {
            MarsModal.show({
                title: 'Lock In Your Narog?',
                body: `
                    <div style="font-size:12px; color:var(--text-muted); margin-bottom:14px;">Review everything below — once locked in, the recalibration window closes (you can re-open it later by paying any recalibration cost).</div>

                    <div style="margin-bottom:14px;">${heroImg}</div>

                    <div style="font-size:11px; font-weight:800; letter-spacing:0.08em; text-transform:uppercase; color:var(--color-sepolia); margin:14px 0 6px;">Name</div>
                    <div style="font-size:14px; font-weight:700; color:var(--text-primary); margin-bottom:14px;">${robot.name || '(unnamed)'}</div>

                    <div style="font-size:11px; font-weight:800; letter-spacing:0.08em; text-transform:uppercase; color:var(--color-sepolia); margin:14px 0 6px;">Components</div>
                    <div style="display:flex; flex-direction:column; gap:6px;">${sourcesList}</div>

                    <div style="font-size:11px; font-weight:800; letter-spacing:0.08em; text-transform:uppercase; color:var(--color-sepolia); margin:14px 0 6px;">Stats &amp; Allocation</div>
                    <div style="background:rgba(0,0,0,0.3); border-radius:6px; border:1px solid var(--border-default); padding:8px 12px;">
                        ${allocRow('exploration', 'Exploration')}
                        ${allocRow('logistics',   'Logistics')}
                        ${allocRow('research',    'Research')}
                        ${allocRow('expeditions', 'Expeditions')}
                        <div style="font-size:10px; color:var(--text-muted); border-top:1px dashed rgba(255,200,140,0.2); margin-top:6px; padding-top:6px;">Active ${totalAllocation}% · Idle ${idle}%</div>
                    </div>

                    <div style="font-size:11px; font-weight:800; letter-spacing:0.08em; text-transform:uppercase; color:var(--color-sepolia); margin:14px 0 6px;">Awakening Video</div>
                    <div style="font-size:12px; padding:8px 10px; background:rgba(0,0,0,0.3); border-radius:6px; border:1px solid var(--border-default);">${videoLine}</div>

                    <div style="border:1px solid rgba(168,85,247,0.4); background:rgba(168,85,247,0.08); border-radius:8px; padding:10px 14px; color:#d8b4fe; font-size:12px; margin-top:14px;">
                        After lock-in, you can still recalibrate — but every adjustment costs more energy each time.
                    </div>

                    <div style="display:flex; gap:10px; justify-content:flex-end; margin-top:14px;">
                        <button id="recal-cancel" style="background:var(--bg-secondary); color:var(--text-primary); border:1px solid var(--border-default); border-radius:8px; padding:10px 18px; font-weight:700; cursor:pointer;">Cancel</button>
                        <button id="recal-confirm" style="background:linear-gradient(135deg, #a855f7, #ec4899); color:white; border:none; border-radius:8px; padding:10px 22px; font-weight:800; cursor:pointer;">Lock In</button>
                    </div>
                `,
            });
            setTimeout(() => {
                const cancel = document.getElementById('recal-cancel');
                const confirm = document.getElementById('recal-confirm');
                if (cancel) cancel.onclick = () => { MarsModal.hide(); resolve(false); };
                if (confirm) confirm.onclick = () => { MarsModal.hide(); resolve(true); };
            }, 0);
        });
    }

    async function postRecalAction(action, btn) {
        // Lock-in needs a final review modal. The 3 reroll actions fire
        // immediately — their costs are on the button and re-rolls are cheap.
        if (action === 'lock_in') {
            const ok = await showLockInReviewModal();
            if (!ok) return;
        }
        btn.classList.add('is-busy');
        const endpoint = {
            repick:       '/api/robot/repick',
            reroll_image: '/api/robot/reroll_image',
            reroll_video: '/api/robot/reroll_video',
            lock_in:      '/api/robot/lock_in',
        }[action];
        try {
            const r = await fetch(endpoint, {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: '{}',
            });
            const j = await r.json();
            if (!j || !j.success) {
                if (typeof showToast === 'function') showToast(j && j.error ? j.error : 'Recalibration failed.', 'error', 'Narog');
                return;
            }
            if (typeof showToast === 'function') {
                const msg = action === 'lock_in' ? 'Narog locked in.' : 'Recalibration in progress.';
                showToast(msg, 'success', 'Narog');
            }
            // For repick / image / video re-rolls the page needs a fresh
            // render to show the loading state. Reload, preserving tab=robot.
            if (action === 'repick' || action === 'reroll_image' || action === 'reroll_video') {
                setTimeout(() => location.reload(), 500);
                return;
            }
            // Lock-in: just re-render the card
            recalState = j.state;
            renderRecal();
        } finally {
            btn.classList.remove('is-busy');
        }
    }

    // ----- Collapsible accordions (Build Manifest, Robot Allocation, ...) ----
    // State persisted in localStorage under key `narog-accordion:{key}`.
    // Defaults from data-default attr (open|closed). Click header to toggle.
    function wireAccordions() {
        document.querySelectorAll('.narog-accordion').forEach(acc => {
            const key = acc.dataset.accordionKey;
            if (!key) return;
            const storageKey = `narog-accordion:${key}`;
            const saved = localStorage.getItem(storageKey);
            const defaultState = acc.dataset.default || 'closed';
            const shouldOpen = saved === null ? (defaultState === 'open') : (saved === 'open');
            acc.classList.toggle('is-open', shouldOpen);
            const head = acc.querySelector('.narog-accordion-head');
            if (head) {
                head.addEventListener('click', () => {
                    const open = !acc.classList.contains('is-open');
                    acc.classList.toggle('is-open', open);
                    localStorage.setItem(storageKey, open ? 'open' : 'closed');
                });
            }
        });
    }

    function wireRecalibration() {
        const card = document.getElementById('narog-recal-card');
        if (card) {
            // Repick + reroll_image buttons
            card.querySelectorAll('.narog-recal-action').forEach(btn => {
                btn.addEventListener('click', () => {
                    const action = btn.dataset.action;
                    if (!action) return;
                    postRecalAction(action, btn);
                });
            });
            // Big Lock In button
            const lockBtn = card.querySelector('.narog-recal-lockin-big');
            if (lockBtn) {
                lockBtn.addEventListener('click', () => postRecalAction('lock_in', lockBtn));
            }
        }
        // Bring-to-Life CTA in the hero area (only in DOM when video missing)
        const brief = document.getElementById('robot-bring-to-life-cta');
        if (brief) {
            brief.addEventListener('click', () => {
                if (brief.style.cursor === 'not-allowed') return;
                postRecalAction('reroll_video', brief);
            });
        }
        loadRecalState();
    }

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
        wireAccordions();  // collapsible Build Manifest + Robot Allocation
        wireRecalibration();  // 2026-04-30: re-pick / re-roll image / re-roll video / lock-in
        maybeFireRobotCinematic();
    });
})();
