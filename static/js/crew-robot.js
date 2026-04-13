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
            const r = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body || {}),
            });
            const data = await r.json();
            if (!data.success) throw new Error(data.error || 'Request failed');
            return data;
        } catch (e) {
            if (typeof showToast === 'function') {
                showToast(e.message || String(e), 'error', 'Norag');
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
        const el = document.getElementById('robot-countdown');
        if (!el) return;
        const initial = parseInt(el.dataset.seconds, 10);
        if (!Number.isFinite(initial)) return;

        let remaining = initial;
        const tick = () => {
            remaining -= 1;
            if (remaining <= 0) {
                el.textContent = '0s';
                clearInterval(countdownInterval);
                countdownInterval = null;
                // Reload so the server-side tick advances the next stage
                reloadSoon();
                return;
            }
            el.textContent = fmtSeconds(remaining);
        };
        if (countdownInterval) clearInterval(countdownInterval);
        countdownInterval = setInterval(tick, 1000);
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
            title: 'Norag Awakening',
            size: 'lg',
            theme: 'aria',
            body: '<video src="' + url + '" style="width:100%;border-radius:12px;" playsinline autoplay loop controls></video>',
        });
    };

    // ----- BUILD button -----------------------------------------------------
    function wireBuildButton() {
        const btn = document.getElementById('robot-build-btn');
        if (!btn) return;
        btn.addEventListener('click', async () => {
            btn.disabled = true;
            btn.style.opacity = '0.6';
            btn.textContent = 'Sourcing parts…';
            try {
                await postJSONSafe('/api/robot/build', {});
                if (typeof showToast === 'function') {
                    showToast('Construction started — first stage assembling now.', 'success', 'Norag');
                }
                reloadSoon();
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
                    showToast('Name cannot be blank.', 'error', 'Norag');
                }
                return;
            }
            saveBtn.disabled = true;
            saveBtn.textContent = 'Saving…';
            try {
                await postJSONSafe('/api/robot/name', { name });
                if (typeof showToast === 'function') {
                    showToast('Norag named "' + name + '".', 'success', 'Norag');
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
                showToast('Role dial saved.', 'success', 'Norag');
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
                html: '<div class="er-info-label">NAME YOUR GOLEM</div>'
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
                detail: (existingName || 'Your Norag') + ' — forged from 5 real expedition fragments',
            };
        }

        EpicReveal.show({
            title: 'GOLEM AWAKENED',
            lines: [
                { text: '*stone shifts... crystals pulse*', cls: 'static-crackle', sound: 'stoneGrind' },
                { text: 'Five fragments. Five sites.', sound: 'deepRumble' },
                { text: 'Five hands that recovered them — yours.', sound: 'crystalChime' },
                { text: 'A new crew member stirs to life.', cls: 'emphasis', sound: 'golemAwaken' },
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
            fetch('/api/robot/cinematic_played', { method: 'POST' }).catch(() => {});
            return;
        }
        fireGolemCinematic(true);
    }

    function wireReplayButton() {
        const btn = document.getElementById('robot-replay-cinematic');
        if (!btn) return;
        btn.addEventListener('click', () => fireGolemCinematic(false));
    }

    // ----- VIDEO GENERATION ---------------------------------------------------
    function wireVideoButton() {
        var btn = document.getElementById('golem-gen-video-btn');
        if (!btn) return;
        btn.addEventListener('click', async function() {
            btn.disabled = true;
            btn.textContent = 'Generating...';
            var status = document.getElementById('golem-video-status');
            if (status) { status.style.display = 'block'; status.textContent = 'Starting video generation (~60s)...'; }
            try {
                var data = await postJSONSafe('/api/robot/generate_video', {});
                if (data.already_exists) {
                    reloadSoon();
                    return;
                }
                // Poll for completion
                var poll = setInterval(async function() {
                    try {
                        var r = await fetch('/api/robot/video_status');
                        var s = await r.json();
                        if (s.url) {
                            clearInterval(poll);
                            if (status) status.textContent = 'Video ready!';
                            reloadSoon();
                        } else if (s.error) {
                            clearInterval(poll);
                            if (status) status.textContent = 'Generation failed. Try again later.';
                            btn.disabled = false;
                            btn.textContent = 'Generate Video';
                        } else if (status) {
                            status.textContent = 'Generating... this takes about 60 seconds.';
                        }
                    } catch (e) { /* keep polling */ }
                }, 5000);
            } catch (e) {
                btn.disabled = false;
                btn.textContent = 'Generate Video';
            }
        });
    }

    // ----- INIT -------------------------------------------------------------
    document.addEventListener('DOMContentLoaded', () => {
        wireBuildButton();
        wireNameSave();
        loadNameSuggestions();
        wireDial();
        startCountdown();
        wireReplayButton();
        wireVideoButton();
        maybeFireRobotCinematic();
    });
})();
