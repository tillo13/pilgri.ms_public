// ============================================================================
// CORE.JS - All JS, one file
// ============================================================================

const $ = id => document.getElementById(id);
const $$ = sel => document.querySelectorAll(sel);
const show = id => { const el = $(id); if (el) el.classList.remove('hidden'); };
const hide = id => { const el = $(id); if (el) el.classList.add('hidden'); };

// #38: custom-icon registry + helper — replaces inline Unicode emojis in JS-rendered HTML.
// Reads the global #globalIcons block (base.html). icon('key') -> <img> string for innerHTML/template
// literals; icon('key','inline-icon-sm') to size. Returns '' for an unknown key (safe in concatenation).
const ICONS = (() => { try { return JSON.parse(document.getElementById('globalIcons').textContent); } catch (e) { return {}; } })();
function icon(key, cls = 'inline-icon') {
  const url = ICONS[key];
  return url ? `<img src="${url}" alt="" class="${cls}">` : '';
}
window.icon = icon;

// API helpers — replace the repeated fetch+JSON+parse boilerplate.
// Usage: const data = await apiPost('/api/foo', {name: 'bar'});
//        const data = await apiGet('/api/foo');
async function apiPost(url, body) {
    const opts = { method: 'POST', headers: { 'Content-Type': 'application/json' } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const r = await fetch(url, opts);
    return r.json();
}
async function apiGet(url) {
    const r = await fetch(url);
    return r.json();
}

// ============================================================================
// UNIVERSAL TAB SYSTEM - Use this for all page tabs
// Usage: switchTab('colony', 'discoveries') or switchTab('crew', 'trails')
// Tabs should have: class="{prefix}-tab" data-tab="{tabname}"
// Content should have: class="{prefix}-tab-content" id="tab-{tabname}"
// ============================================================================
window.tabCallbacks = window.tabCallbacks || {}; // Page-specific callbacks: tabCallbacks.crew = { trails: fn, captain: fn }

function switchTab(prefix, tab) {
    console.log(`[TAB] switchTab called: prefix=${prefix}, tab=${tab}`);
    console.log(`[TAB] tabCallbacks:`, window.tabCallbacks);

    // Update tab buttons
    document.querySelectorAll(`.${prefix}-tab`).forEach(t => t.classList.remove('active'));
    const activeTab = document.querySelector(`.${prefix}-tab[data-tab="${tab}"]`);
    if (activeTab) activeTab.classList.add('active');

    // Update tab content
    document.querySelectorAll(`.${prefix}-tab-content`).forEach(c => c.style.display = 'none');
    const tabContent = document.getElementById(`tab-${tab}`);
    if (tabContent) tabContent.style.display = 'block';

    // Call page-specific callback if registered
    if (window.tabCallbacks[prefix] && window.tabCallbacks[prefix][tab]) {
        console.log(`[TAB] Calling callback for ${prefix}.${tab}`);
        window.tabCallbacks[prefix][tab]();
    } else {
        console.log(`[TAB] No callback found for ${prefix}.${tab}`);
    }
}

// Convenience wrappers for each page (so onclick="switchColonyTab('lab')" works)
function switchColonyTab(tab) { switchTab('colony', tab); }
function switchCrewTab(tab) { switchTab('crew', tab); }
function switchExpeditionsTab(tab) { switchTab('expeditions', tab); }

// Auto-switch tab from URL param (e.g., /crew?tab=scientist)
document.addEventListener('DOMContentLoaded', () => {
    const params = new URLSearchParams(window.location.search);
    const tab = params.get('tab');
    if (tab) {
        // Try each prefix until one works
        ['crew', 'colony', 'expeditions'].forEach(prefix => {
            const el = document.querySelector(`.${prefix}-tab[data-tab="${tab}"]`);
            if (el) switchTab(prefix, tab);
        });
    }
});

// Processing overlay with fast-moving timer
let processingStartTime = 0;
let processingTimerInterval = null;

function showProcessing(msg) {
    const o = $('processingOverlay'), t = $('processingText'), timer = $('processingTimer');
    if (t) t.textContent = msg;
    if (o) o.classList.add('show');
    // Start timer
    processingStartTime = performance.now();
    if (timer) {
        timer.textContent = '0.000s';
        processingTimerInterval = setInterval(() => {
            const elapsed = (performance.now() - processingStartTime) / 1000;
            timer.textContent = elapsed.toFixed(3) + 's';
        }, 37); // ~27fps for smooth movement
    }
}
function hideProcessing() {
    const o = $('processingOverlay');
    if (o) o.classList.remove('show');
    // Stop timer
    if (processingTimerInterval) {
        clearInterval(processingTimerInterval);
        processingTimerInterval = null;
    }
}
function showError(msg) { const el = $('errorMessage'); if (el) { el.textContent = `Error: ${msg}`; el.classList.add('show'); setTimeout(() => el.classList.remove('show'), 5000); } }

// apiCall() is apiPost/apiGet's strict sibling — throws on !data.success.
// Kept for arrival.js's try/catch flow; new code should prefer apiPost/apiGet.
async function apiCall(endpoint, options = {}) { const r = await fetch(endpoint, options); const data = await r.json(); if (!data.success) throw new Error(data.error); return data; }

function disableBtn(btn, text) { if (btn) { btn.disabled = true; btn.style.opacity = '0.5'; if (text) btn.textContent = text; } }
function enableBtn(btn, text) { if (btn) { btn.disabled = false; btn.style.opacity = '1'; if (text) btn.textContent = text; } }

function showToast(message, type = 'info', title = '', duration = 5000) {
    let c = $('toastContainer');
    if (!c) { c = document.createElement('div'); c.id = 'toastContainer'; c.className = 'toast-container'; document.body.appendChild(c); }
    const toast = document.createElement('div'); toast.className = `toast ${type}`;
    // Use ARIA avatar image (same as chat widget) for unified branding
    const ariaImg = 'https://storage.googleapis.com/galactica-pilgrim-assets/aria/concept_aria_rock_v3_1767666240.png';
    toast.innerHTML = `<div class="toast-icon aria-orb"><img src="${ariaImg}" alt="ARIA"></div><div class="toast-content">${title ? `<div class="toast-title">${title}</div>` : ''}<div class="toast-message">${message}</div></div><button class="toast-close" onclick="removeToast(this.parentElement)">×</button>`;
    c.appendChild(toast);
    if (duration > 0) setTimeout(() => removeToast(toast), duration);
}
function removeToast(toast) { toast.classList.add('removing'); setTimeout(() => { toast.remove(); const c = $('toastContainer'); if (c && !c.children.length) c.remove(); }, 300); }

// Bug #21 Deploy C: Captain stat-up toast. Pulls one event from any API
// response shape that includes `stat_events: [...]`. Each event looks like
// {stat, delta, old, new, capped, source_kind}. Suppresses baseline +
// retro_credit (those land off-screen, not "live" growth).
const STAT_LABEL = { leadership:'Leadership', strategy:'Strategy', exploration:'Exploration', logistics:'Logistics', charisma:'Charisma' };
function showStatToast(evt) {
    if (!evt || !evt.stat) return;
    if (evt.source_kind === 'baseline' || evt.source_kind === 'retro_credit') return;
    const label = STAT_LABEL[evt.stat] || evt.stat;
    const delta = Number(evt.delta || 0);
    const sign = delta >= 0 ? '+' : '';
    const deltaStr = Math.abs(delta) < 1 ? delta.toFixed(2) : delta.toFixed(1);
    const capMark = evt.capped ? ' ' + icon('star_milestone') : '';
    const msg = `${sign}${deltaStr} → ${evt.new}/75${capMark}`;
    showToast(msg, 'success', `${label} up`, 4000);
}
// Helper: process whatever `data.stat_events` your API returned. Safe with
// missing / null / non-array — just no-ops.
function processStatEvents(data) {
    const arr = (data && data.stat_events) || null;
    if (!Array.isArray(arr) || !arr.length) return;
    // Stagger toasts slightly so multiple stat-ups don't pile up identically
    arr.forEach((ev, i) => setTimeout(() => showStatToast(ev), i * 350));
}
window.showStatToast = showStatToast;
window.processStatEvents = processStatEvents;

// Persist the per-captain "auto-show haul popup" preference. Shared by the
// in-modal opt-out link (dashboard.js) and the Crew → Services → Auto-Popup
// toggle (crew.js). Updates window.autoShowHaul so the home page respects it
// without a reload; reverts on failure.
async function setHaulPopupPref(enabled) {
    window.autoShowHaul = enabled;
    try {
        const resp = await fetch('/api/user/haul_popup_pref', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled })
        });
        const data = await resp.json();
        if (data.success) {
            showToast(enabled ? 'Haul popup will show automatically' : "Haul popup won't auto-show anymore", 'success');
        } else { showToast('Could not save preference', 'error'); window.autoShowHaul = !enabled; }
    } catch (e) { showToast('Network error', 'error'); window.autoShowHaul = !enabled; }
    return window.autoShowHaul === enabled;
}
window.setHaulPopupPref = setHaulPopupPref;


function showImageModal(src, alt) {
    const m = document.createElement('div'); m.className = 'image-modal';
    m.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.9);z-index:10000;display:flex;align-items:center;justify-content:center;cursor:pointer;';
    const img = document.createElement('img'); img.src = src; img.alt = alt || '';
    img.style.cssText = 'max-width:90%;max-height:90%;border-radius:12px;box-shadow:0 4px 60px rgba(0,0,0,0.5);object-fit:contain;';
    m.appendChild(img); document.body.appendChild(m);
    const close = () => { document.body.removeChild(m); };
    m.onclick = close;
    document.addEventListener('keydown', function h(e) { if (e.key === 'Escape') { close(); document.removeEventListener('keydown', h); } });
}
function showVideoModal(src) {
    const m = document.createElement('div'); m.className = 'image-modal';
    m.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.9);z-index:10000;display:flex;align-items:center;justify-content:center;cursor:pointer;';
    const v = document.createElement('video'); v.src = src; v.autoplay = true; v.loop = true; v.muted = true; v.playsInline = true; v.controls = true;
    v.style.cssText = 'max-width:90%;max-height:90%;border-radius:12px;box-shadow:0 4px 60px rgba(0,0,0,0.5);';
    v.onclick = (e) => e.stopPropagation(); // Don't close when clicking video controls
    m.appendChild(v); document.body.appendChild(m);
    const close = () => { v.pause(); document.body.removeChild(m); };
    m.onclick = close;
    document.addEventListener('keydown', function h(e) { if (e.key === 'Escape') { close(); document.removeEventListener('keydown', h); } });
}
function formatDuration(sec) { const d = sec / 86400, h = sec / 3600, m = sec / 60; return d >= 1 ? `${d.toFixed(1)} days` : h >= 1 ? `${h.toFixed(1)} hours` : m >= 1 ? `${m.toFixed(1)} minutes` : `${sec} seconds`; }

// Bug #1444 (Luke 2026-05-12): depot countdowns showed "5.5d" decimal days
// instead of "5d 12h". Shared helper so every surface (build buttons, queue,
// detail rows, depot card stats) renders the same way. Granularity collapses
// once a unit dominates — "5d 12h" hides minutes (irrelevant at multi-day
// scale), "12h 30m" hides seconds, etc.
function formatDaysHours(sec) {
    sec = Math.max(0, Math.floor(Number(sec) || 0));
    if (sec >= 86400) {
        const d = Math.floor(sec / 86400);
        const h = Math.floor((sec % 86400) / 3600);
        return h > 0 ? `${d}d ${h}h` : `${d}d`;
    }
    if (sec >= 3600) {
        const h = Math.floor(sec / 3600);
        const m = Math.floor((sec % 3600) / 60);
        return m > 0 ? `${h}h ${m}m` : `${h}h`;
    }
    if (sec >= 60) {
        const m = Math.floor(sec / 60);
        const s = sec % 60;
        return s > 0 ? `${m}m ${s}s` : `${m}m`;
    }
    return `${sec}s`;
}

// Shared countdown formatter (used by colony.js, available globally)
function formatCountdown(seconds) {
    if (seconds <= 0) return 'Complete!';
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (d > 0) return `${d}d ${h}h ${m}m ${s}s`;
    if (h > 0) return `${h}h ${m}m ${s}s`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
}

// Balance - SINGLE SOURCE OF TRUTH
// Nav bar #currentBalance is the canonical display. All pages read from here.
let currentBalance = 0;
function updateBalanceDisplay() {
    const el = $('currentBalance');
    if (el) el.textContent = currentBalance.toFixed(0);
    // Keep window.initialBalance synced so any legacy reads get current value
    window.initialBalance = currentBalance;
}
// Set balance from API response or direct value - use this after ANY transaction
function setBalance(newBalance) {
    if (typeof newBalance === 'number' && !isNaN(newBalance) && newBalance >= 0) {
        currentBalance = newBalance;
        updateBalanceDisplay();
    }
}
// Adjust balance by delta (positive = add, negative = subtract)
function adjustBalance(delta) {
    if (typeof delta === 'number' && !isNaN(delta)) {
        currentBalance = Math.max(0, currentBalance + delta);
        updateBalanceDisplay();
    }
}
// Read current balance - preferred way for other scripts to check balance
function getBalance() { return currentBalance; }
// Expose globally for other scripts
window.setBalance = setBalance;
window.adjustBalance = adjustBalance;
window.getBalance = getBalance;
window.updateBalanceDisplay = updateBalanceDisplay;

// ============================================================================
// NAV STATS REFRESH - Call this to update all nav/profile stats from server
// ============================================================================
async function refreshNavStats() {
    try {
        const res = await fetch('/api/nav/stats');
        const data = await res.json();
        if (data.success) {
            // Update balance
            if (data.balance !== undefined) setBalance(data.balance);
            // Update menu stats
            const menuExp = $('menuExpeditions');
            const menuItems = $('menuItemCount');
            if (menuExp && data.expeditions !== undefined) menuExp.textContent = data.expeditions;
            if (menuItems && data.items !== undefined) menuItems.textContent = data.items;
            console.log('Nav stats refreshed:', data);
        }
    } catch (e) {
        console.warn('Failed to refresh nav stats:', e);
    }
}
window.refreshNavStats = refreshNavStats;

// Video Modal
function openVideoModal(url) {
    const m = document.createElement('div'); m.className = 'video-modal';
    const v = document.createElement('video'); v.src = url; v.controls = v.autoplay = v.loop = true; v.style.cssText = 'max-width:90%;max-height:90%;border-radius:12px;';
    m.appendChild(v); document.body.appendChild(m);
    const close = () => { v.pause(); document.body.removeChild(m); };
    m.onclick = e => { if (e.target === m) close(); };
    document.addEventListener('keydown', function h(e) { if (e.key === 'Escape') { close(); document.removeEventListener('keydown', h); } });
}

// Infrastructure

async function harvestSepolia() {
    const btn = $('claimButton'); disableBtn(btn);
    showToast(icon('lightning_power') + ' Harvesting Shards...', 'info', '', 5000);
    try {
        const data = await apiPost('/api/infrastructure/claim');
        if (data.success) {
            // Update balance immediately from response
            if (data.new_balance !== undefined) setBalance(data.new_balance);
            else adjustBalance(data.amount_claimed);
            let harvestMsg = `${icon('checkmark_done')} Harvested ${data.amount_claimed.toFixed(1)} Shards!`;
            showToast(harvestMsg, 'success', '', 8000);
            setTimeout(() => location.reload(), 3000);
        } else { showToast(`Error: ${data.error}`, 'error'); enableBtn(btn); }
    }
    catch (e) { showToast(e.message || 'Connection failed. Please try again.', 'error'); enableBtn(btn); }
}


// ============================================================================
// MARS MODAL - Unified modal system
// Usage: MarsModal.show({ title, subtitle, icon, body, footer, width, onClose,
//            hero, heroHeight, badge, theme, carousel })
//        MarsModal.update({ body, footer })
//        MarsModal.hide()
//        MarsModal.getBody() - returns live body DOM node
// ============================================================================
const MarsModal = {
    _el: null,
    _onClose: null,
    _carousel: null,

    _ensure() {
        if (this._el) return;
        this._el = document.createElement('div');
        this._el.className = 'mm-overlay';
        this._el.innerHTML = `
            <div class="mm-dialog">
                <button class="mm-close" aria-label="Close">&times;</button>
                <img class="mm-hero" style="display:none;">
                <div class="mm-header">
                    <span class="mm-icon"></span>
                    <div class="mm-titles">
                        <h3 class="mm-title"></h3>
                        <div class="mm-subtitle"></div>
                    </div>
                </div>
                <div class="mm-badge-wrap" style="display:none;"></div>
                <div class="mm-body"></div>
                <div class="mm-footer"></div>
                <div class="mm-carousel-nav" style="display:none;"></div>
            </div>
        `;
        document.body.appendChild(this._el);
        this._el.querySelector('.mm-close').onclick = () => this.hide();
        // Bug #1397 ReOpen v3: per-modal opt-out for backdrop & Escape dismissal.
        // Default behavior unchanged (true). Sticky modals (build completion) set
        // these to false so an accidental click outside the dialog can't kill the
        // modal before the captain reads it.
        this._el.addEventListener('click', e => {
            if (e.target === this._el && this._dismissOnBackdrop !== false) this.hide();
        });
        document.addEventListener('keydown', e => {
            if (!this._el || !this._el.classList.contains('show')) return;
            if (e.key === 'Escape' && this._dismissOnEscape !== false) this.hide();
            if (this._carousel && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
                e.preventDefault();
                this._navCarousel(e.key === 'ArrowLeft' ? -1 : 1);
            }
        });
    },

    _setHero(url, height) {
        const hero = this._el.querySelector('.mm-hero');
        if (url) {
            hero.src = url;
            hero.style.display = '';
            if (height === 0) { hero.className = 'mm-hero mm-hero-auto'; }
            else { hero.className = 'mm-hero'; hero.style.height = (height || 180) + 'px'; }
        } else {
            hero.style.display = 'none';
            hero.src = '';
        }
    },

    _renderCarousel(idx) {
        const c = this._carousel;
        if (!c || idx < 0 || idx >= c.items.length) return;
        c.current = idx;
        const item = c.items[idx];
        const cfg = c.render(item, idx, c.items.length);
        // Update content from render result
        if (cfg.title !== undefined) this._el.querySelector('.mm-title').textContent = cfg.title;
        if (cfg.subtitle !== undefined) this._el.querySelector('.mm-subtitle').innerHTML = cfg.subtitle;
        if (cfg.body !== undefined) this._el.querySelector('.mm-body').innerHTML = cfg.body;
        if (cfg.hero !== undefined) this._setHero(cfg.hero, cfg.heroHeight);
        if (cfg.badge !== undefined) {
            const bw = this._el.querySelector('.mm-badge-wrap');
            if (cfg.badge) { bw.innerHTML = `<span class="mm-badge">${cfg.badge}</span>`; bw.style.display = ''; }
            else { bw.style.display = 'none'; }
        }
        // Update carousel nav
        const nav = this._el.querySelector('.mm-carousel-nav');
        const isFirst = idx === 0, isLast = idx === c.items.length - 1;
        const labels = c.labels || {};
        nav.innerHTML = `
            <button class="mm-carousel-btn mm-carousel-prev" ${isFirst ? 'style="visibility:hidden;"' : ''}>${labels.prev || 'Previous'}</button>
            <span class="mm-carousel-counter">${idx + 1} of ${c.items.length}</span>
            ${c.items.length > 1 && !isLast ? `<button class="mm-carousel-btn mm-carousel-skip">${labels.skip || 'Skip All'}</button>` : ''}
            <button class="mm-carousel-btn mm-carousel-next">${isLast ? (labels.done || 'Done') : (labels.next || 'Next')}</button>
        `;
        nav.querySelector('.mm-carousel-prev').onclick = () => this._navCarousel(-1);
        nav.querySelector('.mm-carousel-next').onclick = () => isLast ? this.hide() : this._navCarousel(1);
        const skipBtn = nav.querySelector('.mm-carousel-skip');
        if (skipBtn) skipBtn.onclick = () => this.hide();
        // Callback
        if (c.onNavigate) c.onNavigate(idx);
    },

    _navCarousel(dir) {
        if (!this._carousel) return;
        const next = this._carousel.current + dir;
        if (next < 0 || next >= this._carousel.items.length) return;
        this._renderCarousel(next);
    },

    _initSwipeHandlers() {
        if (this._swipeHandlersAttached) return;

        let touchStartX = 0;
        let touchStartY = 0;
        let touchEndX = 0;
        let touchEndY = 0;

        const dialog = this._el.querySelector('.mm-dialog');

        dialog.addEventListener('touchstart', (e) => {
            touchStartX = e.changedTouches[0].screenX;
            touchStartY = e.changedTouches[0].screenY;
        }, { passive: true });

        dialog.addEventListener('touchend', (e) => {
            touchEndX = e.changedTouches[0].screenX;
            touchEndY = e.changedTouches[0].screenY;

            const deltaX = touchEndX - touchStartX;
            const deltaY = touchEndY - touchStartY;
            const minSwipeDistance = 50;

            // Horizontal swipe must be dominant (not vertical scroll)
            if (Math.abs(deltaX) > Math.abs(deltaY) && Math.abs(deltaX) > minSwipeDistance) {
                if (this._carousel) {
                    if (deltaX > 0) {
                        // Swipe right -> previous
                        this._navCarousel(-1);
                    } else {
                        // Swipe left -> next
                        this._navCarousel(1);
                    }
                }
            }
        }, { passive: true });

        this._swipeHandlersAttached = true;
    },

    show({ title, subtitle, icon, body, footer, width, onClose, hero, heroHeight, badge, theme, carousel,
            dismissOnBackdrop, dismissOnEscape } = {}) {
        this._ensure();
        this._onClose = onClose || null;
        this._carousel = carousel || null;
        // Default true (existing callers unchanged); explicit false for sticky modals.
        this._dismissOnBackdrop = dismissOnBackdrop !== false;
        this._dismissOnEscape = dismissOnEscape !== false;
        const dialog = this._el.querySelector('.mm-dialog');
        let cls = 'mm-dialog' + (width ? ` mm-${width}` : ' mm-md');
        if (theme) cls += ` mm-theme-${theme}`;
        dialog.className = cls;

        // Hero image
        this._setHero(hero, heroHeight);

        // Header
        const headerEl = this._el.querySelector('.mm-header');
        const iconEl = this._el.querySelector('.mm-icon');
        const titleEl = this._el.querySelector('.mm-title');
        const subtitleEl = this._el.querySelector('.mm-subtitle');
        if (title || icon) {
            headerEl.style.display = '';
            iconEl.innerHTML = icon || '';
            iconEl.style.display = icon ? '' : 'none';
            titleEl.textContent = title || '';
            subtitleEl.innerHTML = subtitle || '';
            subtitleEl.style.display = subtitle ? '' : 'none';
        } else {
            headerEl.style.display = 'none';
        }

        // Badge
        const badgeWrap = this._el.querySelector('.mm-badge-wrap');
        if (badge) { badgeWrap.innerHTML = `<span class="mm-badge">${badge}</span>`; badgeWrap.style.display = ''; }
        else { badgeWrap.style.display = 'none'; }

        // Body + Footer
        this._el.querySelector('.mm-body').innerHTML = body || '';
        const footerEl = this._el.querySelector('.mm-footer');
        if (footer) { footerEl.innerHTML = footer; footerEl.style.display = ''; }
        else { footerEl.style.display = 'none'; }

        // Carousel
        const carouselNav = this._el.querySelector('.mm-carousel-nav');
        if (carousel && carousel.items && carousel.items.length > 0) {
            carouselNav.style.display = '';
            this._renderCarousel(carousel.current || 0);
            // Initialize swipe handlers for touch devices
            if (carousel.items.length > 1) {
                this._initSwipeHandlers();
            }
        } else {
            carouselNav.style.display = 'none';
        }

        this._el.classList.add('show');
    },

    update({ body, footer } = {}) {
        if (!this._el) return;
        if (body !== undefined) this._el.querySelector('.mm-body').innerHTML = body;
        if (footer !== undefined) {
            const f = this._el.querySelector('.mm-footer');
            f.innerHTML = footer || '';
            f.style.display = footer ? '' : 'none';
        }
    },

    hide() {
        if (this._el) {
            this._el.classList.remove('show');
            this._carousel = null;
            if (this._onClose) { this._onClose(); this._onClose = null; }
        }
    },

    getBody() {
        return this._el ? this._el.querySelector('.mm-body') : null;
    }
};
window.MarsModal = MarsModal;

// ============================================================================
// ARIA WHISPER MODAL — shared puzzle-fragment whisper (Bug #1448)
// Used by /signal (auto-pop pending + click-to-replay) and the expedition-complete
// toast. Consolidates the two former copies (signal.js showFragmentWhisper +
// expeditions-rewards.js showPuzzleFragmentWhisper) into one — DRY.
//
// CRITICAL (Luke 2026-05-20: "once you refresh the Signal page it goes away"):
// the whisper_seen ack fires ONLY on the explicit "I'll Hold Onto It" button, NOT
// from MarsModal's onClose — onClose runs on ✕/backdrop/Escape too, which silently
// consumed the whisper so it never re-popped. With ackOnConfirm, dismissing any
// other way leaves the whisper UNSEEN, so it re-surfaces on the next /signal visit
// until the captain deliberately acknowledges it.
// ============================================================================
function showAriaWhisper({ fragmentId, name, whisperText, description, ackOnConfirm = false, footerNote = '' } = {}) {
    if (typeof MarsModal === 'undefined') {
        alert((name ? name + '\n' : '') + (whisperText || ''));
        return;
    }
    MarsModal.show({
        title: name || 'A Fragment Found',
        subtitle: '<span style="color:#a855f7">ARIA whispers...</span>',
        icon: icon('star_milestone'),
        width: 'md',
        body: `
            ${description ? `<div class="mm-card-accent" style="text-align:center; font-style:italic; color:var(--text-secondary);">${description}</div>` : ''}
            <div class="mm-aria" style="font-size:15px; line-height:1.55;">"${whisperText}"</div>
            ${footerNote}
        `,
        footer: `<button class="btn btn-primary mm-btn-full" id="aria-whisper-ack">I'll Hold Onto It</button>`
    });
    // Ack fires from the button only — never from onClose (see header note).
    setTimeout(() => {
        const btn = document.getElementById('aria-whisper-ack');
        if (btn) btn.addEventListener('click', () => {
            if (ackOnConfirm && fragmentId) {
                apiPost(`/api/signal/puzzle_fragments/${fragmentId}/whisper_seen`, {}).catch(() => {});
            }
            MarsModal.hide();
        });
    }, 50);
}
window.showAriaWhisper = showAriaWhisper;

// ============================================================================
// ITEM DETAIL MODAL - Backward-compatible wrapper around MarsModal
// Usage: ItemDetailModal.show({ name, image, category, description, price, stats, effects, action })
// ============================================================================
const ItemDetailModal = {
    show(item) {
        const { name, image, category, description, price, stats, effects, requirements, action, htmlDescription } = item;
        let body = '';
        if (image) body += `<img class="mm-image" src="${image}" alt="">`;
        if (category) body += `<div class="mm-section-label">${category}</div>`;
        if (description) body += `<div class="mm-desc">${htmlDescription ? description : escapeHtml(description)}</div>`;
        if (stats && stats.length) {
            body += '<div class="mm-stats">' + stats.map(s =>
                `<div class="mm-stat"><div class="mm-stat-label">${s.label}</div><div class="mm-stat-value">${s.value}</div></div>` +
                (s.detail ? `<div class="mm-stat-detail">${s.detail}</div>` : '') +
                (s.detailNote ? `<div class="mm-stat-detail-note">${s.detailNote}</div>` : '')
            ).join('') + '</div>';
        }
        if (effects) body += `<div class="mm-card">${effects}</div>`;
        if (requirements) body += `<div class="mm-card-accent">${requirements}</div>`;

        let footer = '';
        if (action && action.label) {
            footer = `<button class="btn ${action.className || 'btn-primary'} mm-btn-full" id="mmActionBtn">${action.label}</button>`;
            if (action.secondaryAction) {
                footer += `<button class="btn btn-secondary mm-btn-sm" id="mmActionBtn2">${action.secondaryAction.label}</button>`;
            }
            if (action.tertiaryAction) {
                footer += `<button class="btn btn-secondary mm-btn-sm" id="mmActionBtn3">${action.tertiaryAction.label}</button>`;
            }
        }

        MarsModal.show({
            title: name || '',
            subtitle: price ? `<span class="mm-price">${price}</span>` : '',
            body, footer, width: 'md'
        });

        // Bind action buttons after render
        if (action && action.onClick) {
            const btn = document.getElementById('mmActionBtn');
            if (btn) btn.onclick = action.onClick;
        }
        if (action && action.secondaryAction) {
            const btn2 = document.getElementById('mmActionBtn2');
            if (btn2) btn2.onclick = action.secondaryAction.onClick;
        }
        if (action && action.tertiaryAction) {
            const btn3 = document.getElementById('mmActionBtn3');
            if (btn3) btn3.onclick = action.tertiaryAction.onClick;
        }
    },
    hide() { MarsModal.hide(); }
};
window.ItemDetailModal = ItemDetailModal;

function escapeHtml(s) {
    const d = document.createElement('div'); d.textContent = s; return d.innerHTML;
}

// Theme toggle - default to dark mode for Mars night aesthetic
function initTheme() {
    const saved = localStorage.getItem('theme');
    // Default to dark mode (Mars night) unless user explicitly chose light
    const theme = saved || 'dark';
    document.documentElement.setAttribute('data-theme', theme);
}
function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
}
// Apply theme immediately (before DOMContentLoaded to prevent flash)
initTheme();

// Hide processing overlay when page is shown (handles back-forward cache)
window.addEventListener('pageshow', function(event) {
    hideProcessing();
    // Bug #1397 v4: pageshow fires AFTER load, which fires AFTER DOMContentLoaded.
    // Stripping .mm-overlay.show on every fresh load was murdering the depot
    // build-completion modal ~0.5s after it opened (load wait = GCS image loads).
    // Only strip on bfcache restore, where stale overlays are a legit concern.
    if (event.persisted) {
        document.querySelectorAll('.mm-overlay.show').forEach(m => m.classList.remove('show'));
    }
});

// Init
document.addEventListener('DOMContentLoaded', function() {
    console.log('🚀 Pilgrims initialized');
    if (typeof window.initialBalance !== 'undefined') currentBalance = window.initialBalance;

    // Theme toggle button
    const themeToggle = $('themeToggle');
    if (themeToggle) themeToggle.onclick = toggleTheme;

    // Lazy image fade-in on load
    $$('img[loading="lazy"]').forEach(img => {
        if (img.complete) img.classList.add('loaded');
        else img.onload = () => img.classList.add('loaded');
    });

    const toggle = $('userToggle'), menu = $('userMenu');
    if (toggle && menu) {
        toggle.onclick = e => { e.stopPropagation(); menu.classList.toggle('show'); };
        document.onclick = e => { if (!menu.contains(e.target) && !toggle.contains(e.target)) menu.classList.remove('show'); };
        document.onkeydown = e => { if (e.key === 'Escape') menu.classList.remove('show'); };
    }

    // Commander name edit functionality
    const editBtn = $('commanderEditBtn'), display = $('commanderDisplay'), edit = $('commanderEdit');
    const nameInput = $('commanderNameInput'), nameText = $('commanderNameText');
    const saveBtn = $('commanderSaveBtn'), cancelBtn = $('commanderCancelBtn');

    if (editBtn && display && edit) {
        let originalName = nameInput ? nameInput.value : '';

        editBtn.onclick = e => {
            e.stopPropagation();
            display.style.display = 'none';
            edit.style.display = 'block';
            nameInput.focus();
            nameInput.select();
        };

        cancelBtn.onclick = e => {
            e.stopPropagation();
            nameInput.value = originalName;
            edit.style.display = 'none';
            display.style.display = 'flex';
        };

        saveBtn.onclick = async e => {
            e.stopPropagation();
            const newName = nameInput.value.trim();
            if (newName.length < 2) { showToast('Name must be at least 2 characters', 'error'); return; }
            if (newName.length > 30) { showToast('Name must be 30 characters or less', 'error'); return; }
            if (newName === originalName) { cancelBtn.click(); return; }

            saveBtn.disabled = true;
            saveBtn.textContent = '...';

            try {
                const data = await apiPost('/api/commander/rename', { name: newName });
                if (data.success) {
                    showToast('Captain renamed! Refreshing...', 'success');
                    // Reload page so ARIA and all UI elements get the new name
                    setTimeout(() => window.location.reload(), 800);
                    return;
                } else {
                    showToast(data.error || 'Failed to rename', 'error');
                }
            } catch (err) {
                showToast('Network error', 'error');
            }
            saveBtn.disabled = false;
            saveBtn.textContent = 'Save';
        };

        nameInput.onkeydown = e => {
            if (e.key === 'Enter') { e.preventDefault(); saveBtn.click(); }
            if (e.key === 'Escape') { cancelBtn.click(); }
        };

        // Prevent menu close when interacting with edit form
        edit.onclick = e => e.stopPropagation();
    }

    // Navigation with prefetching on hover (faster perceived load)
    const prefetchedUrls = new Set();
    function prefetchPage(url) {
        if (prefetchedUrls.has(url) || url === window.location.pathname) return;
        prefetchedUrls.add(url);
        const link = document.createElement('link');
        link.rel = 'prefetch';
        link.href = url;
        document.head.appendChild(link);
    }

    // Prefetch on hover for faster navigation
    $$('.nav-tab, .bottom-nav .nav-item').forEach(el => {
        el.addEventListener('mouseenter', function() { prefetchPage(this.getAttribute('href')); });
        el.addEventListener('touchstart', function() { prefetchPage(this.getAttribute('href')); }, { passive: true });
        el.onclick = function() { if (!this.classList.contains('active')) showProcessing('Transmitting...'); };
    });

    // Mars Status Bar Modal Toggle
    const marsBar = $('marsStatusBar');
    const marsOverlay = $('marsModalOverlay');
    const marsClose = $('marsModalClose');
    if (marsBar && marsOverlay) {
        marsBar.onclick = () => marsOverlay.classList.add('active');
        marsBar.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') marsOverlay.classList.add('active'); };
        if (marsClose) marsClose.onclick = () => marsOverlay.classList.remove('active');
        marsOverlay.onclick = e => { if (e.target === marsOverlay) marsOverlay.classList.remove('active'); };
        document.addEventListener('keydown', e => { if (e.key === 'Escape') marsOverlay.classList.remove('active'); });
    }

    // ============================================================================
    // MARS BANNER TICKING ANIMATIONS - Science, Shards, Time on Mars
    // ============================================================================

    const startTime = performance.now();

    // Format number with commas and 3 decimals
    function formatCurrency(n) {
        // Bug #1122: no decimals on Shard/SV ribbon — integer + thousand separators only
        return Math.floor(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    }

    // Science (SV) ticking animation
    const scienceItem = $('scienceItem');
    const scienceEl = $('scienceValue');
    if (scienceItem && scienceEl) {
        const svRate = parseFloat(scienceItem.dataset.svRate) || 0;
        const svValue = parseFloat(scienceItem.dataset.svValue) || 0;

        // Rate is per hour, convert to per ms
        const svPerMs = svRate / 3600 / 1000;

        function updateScience() {
            const elapsed = performance.now() - startTime;
            const currentSV = svValue + (svPerMs * elapsed);
            scienceEl.textContent = formatCurrency(currentSV);
        }

        updateScience();
        if (svRate > 0) setInterval(updateScience, 100);
    }

    // Adjust SV from extraction awards (updates ticker base value)
    window.adjustSV = function(amount) {
        const el = $('scienceItem');
        if (el) el.dataset.svValue = (parseFloat(el.dataset.svValue) || 0) + amount;
    };

    // Sepolia Shards ticking animation
    const shardsItem = $('shardsItem');
    const shardsEl = $('shardsValue');
    if (shardsItem && shardsEl) {
        const shardRate = parseFloat(shardsItem.dataset.shardRate) || 0;
        const shardValue = parseFloat(shardsItem.dataset.shardValue) || 0;

        // Rate is per hour, convert to per ms
        const shardPerMs = shardRate / 3600 / 1000;

        function updateShards() {
            const elapsed = performance.now() - startTime;
            const currentShards = shardValue + (shardPerMs * elapsed);
            shardsEl.textContent = formatCurrency(currentShards);
        }

        updateShards();
        if (shardRate > 0) setInterval(updateShards, 100);
    }

    // Time on Mars ticking animation (sols since first login)
    const timeOnMarsItem = $('timeOnMarsItem');
    const timeOnMarsEl = $('timeOnMars');
    const modalTimeOnMarsEl = $('modalTimeOnMars');
    if (timeOnMarsItem && timeOnMarsEl) {
        const firstLogin = new Date(timeOnMarsItem.dataset.firstLogin);
        if (!isNaN(firstLogin.getTime())) {
            // Mars sol length: 24h 37m 22s = 88,642 seconds = 88,642,000 ms
            const SOL_LENGTH_MS = 88642000;

            function updateTimeOnMars() {
                const elapsedMs = Date.now() - firstLogin.getTime();
                const sols = elapsedMs / SOL_LENGTH_MS;
                const solText = 'SOL ' + sols.toFixed(4);
                timeOnMarsEl.textContent = solText;
                // Also update modal if it exists
                if (modalTimeOnMarsEl) modalTimeOnMarsEl.textContent = solText;
            }

            updateTimeOnMars();
            setInterval(updateTimeOnMars, 100);
        }
    }

    // Modal elements for currency ticking (only update when modal is open)
    const modalShardsEl = $('modalShardsTotal');
    const modalScienceEl = $('modalScienceTotal');

    // If modal elements exist and we have the banner items, sync them
    if (modalShardsEl && shardsItem) {
        const shardRate = parseFloat(shardsItem.dataset.shardRate) || 0;
        const shardValue = parseFloat(shardsItem.dataset.shardValue) || 0;
        const shardPerMs = shardRate / 3600 / 1000;

        function updateModalShards() {
            const elapsed = performance.now() - startTime;
            const currentShards = shardValue + (shardPerMs * elapsed);
            modalShardsEl.textContent = formatCurrency(currentShards);
        }

        updateModalShards();
        if (shardRate > 0) setInterval(updateModalShards, 100);
    }

    if (modalScienceEl && scienceItem) {
        const svRate = parseFloat(scienceItem.dataset.svRate) || 0;
        const svValue = parseFloat(scienceItem.dataset.svValue) || 0;
        const svPerMs = svRate / 3600 / 1000;

        function updateModalScience() {
            const elapsed = performance.now() - startTime;
            const currentSV = svValue + (svPerMs * elapsed);
            modalScienceEl.textContent = formatCurrency(currentSV);
        }

        updateModalScience();
        if (svRate > 0) setInterval(updateModalScience, 100);
    }
});

