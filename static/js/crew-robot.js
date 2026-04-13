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
                showToast(e.message || String(e), 'error', 'Golem');
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
                    showToast('Construction started — first stage assembling now.', 'success', 'Golem');
                }
                reloadSoon();
            } catch (e) {
                btn.disabled = false;
                btn.style.opacity = '1';
                btn.textContent = 'Begin Construction';
            }
        });
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
                    showToast('Name cannot be blank.', 'error', 'Golem');
                }
                return;
            }
            saveBtn.disabled = true;
            saveBtn.textContent = 'Saving…';
            try {
                await postJSONSafe('/api/robot/name', { name });
                saveBtn.textContent = 'Saved';
                if (typeof showToast === 'function') {
                    showToast('Golem named "' + name + '".', 'success', 'Golem');
                }
                setTimeout(() => {
                    saveBtn.disabled = false;
                    saveBtn.textContent = 'Save';
                }, 1500);
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
        const golemName = (document.getElementById('robot-name-input') || {}).value || 'Your Golem';

        EpicReveal.show({
            title: 'GOLEM AWAKENED',
            lines: [
                { text: '*stone shifts... crystals pulse*', cls: 'static-crackle', sound: 'crackle' },
                { text: 'Five fragments. Five sites.', sound: 'glitch' },
                { text: 'Five hands that recovered them — yours.', sound: 'glitch' },
                { text: 'A new crew member stirs to life.', cls: 'emphasis' },
            ],
            image: robotImage,
            info: {
                label: 'CONSTRUCTION COMPLETE',
                detail: golemName + ' — forged from 5 real expedition fragments',
            },
            revelation: {
                label: 'NEW CREW MEMBER',
                text: 'Your fourth crew member has awakened. Tune their role dial to direct their effort.',
            },
            actions: [
                { label: 'Tune Role Dial', href: '/crew?tab=robot', cls: 'primary' },
                { label: 'Continue', cls: 'secondary' },
            ],
            onClose: function () {
                if (markPlayed) {
                    fetch('/api/robot/cinematic_played', { method: 'POST' }).catch(() => {});
                }
            },
        });
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

    // ----- INIT -------------------------------------------------------------
    document.addEventListener('DOMContentLoaded', () => {
        wireBuildButton();
        wireNameSave();
        wireDial();
        startCountdown();
        wireReplayButton();
        maybeFireRobotCinematic();
    });
})();
