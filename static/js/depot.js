// ============================================================================
// DEPOT.JS - Supply Depot purchases, upgrades, xenobiology lab
// ============================================================================

// Sanitize error messages - NEVER show blockchain/crypto terms to users
function sanitizeErrorMsg(msg) {
    if (!msg) return 'Unable to complete request. Please try again.';
    const lower = msg.toLowerCase();
    const blockedTerms = ['transaction', 'nonce', 'gas', 'blockchain', 'eth', 'wallet', 'hash', '0x', 'code', '-32'];
    if (blockedTerms.some(t => lower.includes(t))) {
        return 'Unable to complete request. Please try again.';
    }
    return msg;
}

// Global transaction lock - prevents multiple purchases at once
let _txInProgress = false;
function lockAllPurchases() {
    _txInProgress = true;
    document.querySelectorAll('.depot-card .btn-purchase, .btn-unlock, .btn-upgrade').forEach(btn => {
        btn.disabled = true;
        btn.dataset.lockedByTx = 'true';
    });
}
function unlockAllPurchases() {
    _txInProgress = false;
    document.querySelectorAll('[data-locked-by-tx="true"]').forEach(btn => {
        btn.disabled = false;
        delete btn.dataset.lockedByTx;
    });
}
function isTxLocked() { return _txInProgress; }

// Load page data from template (Jinja2 bridge)
const DEPOT_DATA = JSON.parse(document.getElementById('depotData').textContent);

// UI Icons from page data
const DEPOT_ICONS = DEPOT_DATA.icons;

const UPGRADE_DATA = DEPOT_DATA.upgradeCatalog;
const CURRENT_BALANCE = DEPOT_DATA.currentBalance;
const INFRA_ITEMS = DEPOT_DATA.infraItems;
const SHOP_ITEMS = DEPOT_DATA.shopItems;


// Filtering and sorting
function initDepotControls() {
    const grid = document.getElementById('depotGrid');
    const filterBtns = document.querySelectorAll('.filter-btn');
    const sortSelect = document.getElementById('sortSelect');

    if (!grid) return;

    filterBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            filterBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            filterCards(btn.dataset.filter);
        });
    });

    if (sortSelect) {
        sortSelect.addEventListener('change', () => sortCards(sortSelect.value));
        sortCards('price-asc'); // Initial sort
    }
}

function filterCards(filter) {
    const cards = document.querySelectorAll('.depot-card');
    cards.forEach(card => {
        let show = true;
        if (filter === 'affordable') show = card.dataset.affordable === 'true';
        else if (filter === 'owned') show = card.dataset.owned === 'true';
        else if (filter === 'upgradeable') show = card.dataset.upgradeable === 'true';
        card.style.display = show ? '' : 'none';
    });
}

function sortCards(sortBy) {
    const grid = document.getElementById('depotGrid');
    const cards = Array.from(grid.querySelectorAll('.depot-card'));

    cards.sort((a, b) => {
        if (sortBy === 'price-asc') return parseInt(a.dataset.price) - parseInt(b.dataset.price);
        if (sortBy === 'price-desc') return parseInt(b.dataset.price) - parseInt(a.dataset.price);
        if (sortBy === 'category') return a.dataset.category.localeCompare(b.dataset.category);
        return 0;
    });

    cards.forEach(card => grid.appendChild(card));
}

window.addEventListener('DOMContentLoaded', function() {
    initDepotControls();
    initItemDetailModal();
    initBuildCountdowns();
    initBuildQueueCountdowns();
    maybeShowBuildCompletionsModal();
});

// Bug #1397 ReOpen v3 (2026-04-29): comprehensive rewrite addressing Luke's three pains:
//   (a) "shows ~25% of the time" — fragile localStorage hash-based suppression replaced
//       with a server-side timestamp (pilgrim.users.depot_completions_seen_at). The
//       backend filters completions newer than that stamp; we POST to bump it on dismiss.
//   (b) "disappears after ~2 seconds" — the most likely cause is an accidental click on
//       the modal's dim backdrop dismissing it. We pass dismissOnBackdrop:false so only
//       the X button or the explicit Got It button can close this modal. Escape too.
//   (c) "no old/new building images" — server-side build_completions.py was already
//       returning prev_image_url; the JS just wasn't using it. Now renders BEFORE → AFTER
//       side-by-side with an arrow.
function maybeShowBuildCompletionsModal() {
    const completions = DEPOT_DATA.recentCompletions || [];
    if (!completions.length) return;

    const shardIcon = DEPOT_DATA.shardIcon || '';
    const cards = completions.map(c => {
        const beforeImg = c.prev_image_url
            ? `<img src="${c.prev_image_url}" alt="Lv ${c.old_level}" loading="lazy" style="width:72px;height:72px;border-radius:6px;object-fit:cover;flex-shrink:0;border:1px solid rgba(255,255,255,0.15);opacity:0.7;">`
            : `<div style="width:72px;height:72px;border-radius:6px;background:rgba(255,255,255,0.05);flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:10px;color:var(--text-muted);border:1px solid rgba(255,255,255,0.08);">Lv ${c.old_level}</div>`;
        const arrow = `<div style="display:flex;align-items:center;justify-content:center;flex-shrink:0;color:var(--color-success);font-size:20px;font-weight:700;">→</div>`;
        const afterImg = c.image_url
            ? `<img src="${c.image_url}" alt="Lv ${c.new_level}" loading="lazy" style="width:72px;height:72px;border-radius:6px;object-fit:cover;flex-shrink:0;border:1px solid rgba(255,180,50,0.5);box-shadow:0 0 8px rgba(255,180,50,0.2);">`
            : `<div style="width:72px;height:72px;border-radius:6px;background:rgba(255,180,50,0.1);flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:10px;color:var(--color-warning);border:1px solid rgba(255,180,50,0.5);">Lv ${c.new_level}</div>`;
        const costLine = c.cost
            ? `<div style="font-size:11px;color:var(--text-muted);margin-top:3px;"><img src="${shardIcon}" alt="" class="inline-icon-sm"> ${c.cost.toLocaleString()}</div>`
            : '';
        const diffLines = (c.effect_diff || []).map(d =>
            `<div style="font-size:11px;color:var(--color-success);line-height:1.4;">${d}</div>`
        ).join('');
        return `
            <div style="padding:10px;background:var(--bg-secondary);border-radius:6px;border:1px solid rgba(255,180,50,0.2);margin-bottom:10px;">
                <div style="display:flex;gap:8px;align-items:center;justify-content:center;margin-bottom:8px;">
                    ${beforeImg}
                    ${arrow}
                    ${afterImg}
                </div>
                <div style="font-size:13px;color:var(--text-primary);font-weight:600;text-align:center;">${escapeHtml(c.item_name)}</div>
                <div style="font-size:12px;color:var(--color-warning);font-weight:500;margin-top:2px;text-align:center;">Lv ${c.old_level} → ${c.new_level}</div>
                ${costLine ? `<div style="text-align:center;">${costLine}</div>` : ''}
                ${diffLines ? `<div style="margin-top:6px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.06);">${diffLines}</div>` : ''}
            </div>
        `;
    }).join('');

    let dismissed = false;
    const dismiss = () => {
        if (dismissed) return;
        dismissed = true;
        // Fire-and-forget; if the network call fails the modal will simply re-show on
        // the next /depot load (mild annoyance, not data loss).
        fetch('/api/depot/completions/mark-seen', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
        }).catch(() => {});
        MarsModal.hide();
    };

    MarsModal.show({
        title: `${completions.length} build${completions.length > 1 ? 's' : ''} complete`,
        subtitle: 'Ready at the Depot',
        width: 'md',
        body: `<div style="max-height:60vh;overflow-y:auto;padding:4px 2px;">${cards}</div>`,
        footer: '<button class="btn btn-primary mm-dismiss-completions mm-btn-full">Got it</button>',
        // Sticky: only the X button or Got It button closes it.
        dismissOnBackdrop: false,
        dismissOnEscape: false,
        onClose: dismiss,
    });
    const btn = document.querySelector('.mm-dismiss-completions');
    if (btn) btn.addEventListener('click', dismiss);
}

function escapeHtml(s) {
    return String(s || '').replace(/[&<>"']/g, c =>
        ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// Live countdown timers for building items in the grid
function initBuildCountdowns() {
    const buildingCards = document.querySelectorAll('.depot-card.building');
    if (!buildingCards.length) return;

    // Store remaining seconds for each element
    buildingCards.forEach(card => {
        card._remainingSeconds = parseInt(card.dataset.secondsRemaining) || 0;
    });

    // Bug #1444: use the shared formatDaysHours helper (core.js) so days
    // render as "5d 12h" instead of the old "5.5d" decimal format.

    // Update every second
    setInterval(() => {
        buildingCards.forEach(card => {
            if (card._remainingSeconds <= 0) return;
            card._remainingSeconds--;
            const timeStr = formatDaysHours(card._remainingSeconds);

            const timerEl = card.querySelector('.build-timer');
            if (timerEl) timerEl.textContent = timeStr;

            const remainingEl = card.querySelector('.build-time-remaining');
            if (remainingEl) remainingEl.textContent = timeStr;

            if (card._remainingSeconds <= 0) {
                showToast('Construction complete! Refresh to see your new equipment.', 'success', 'Build Complete', 5000);
            }
        });
    }, 1000);
}

// Build queue header countdown timers
function initBuildQueueCountdowns() {
    const countdownEls = document.querySelectorAll('.build-countdown');
    if (!countdownEls.length) return;

    // Bug #1444: shared formatDaysHours (core.js) — same "5d 12h" format
    // across every depot countdown.

    // Initialize each countdown
    countdownEls.forEach(el => {
        el._seconds = parseInt(el.dataset.seconds) || 0;
        el.textContent = formatDaysHours(el._seconds);
    });

    // Update every second
    setInterval(() => {
        countdownEls.forEach(el => {
            if (el._seconds <= 0) return;
            el._seconds--;
            el.textContent = formatDaysHours(el._seconds);
            if (el._seconds <= 0) {
                el.textContent = 'Done!';
                el.style.color = 'var(--color-success)';
            }
        });
    }, 1000);
}

// Item Detail Modal - for non-upgrade shop items only (upgrade cards have their own onclick)
function initItemDetailModal() {
    document.querySelectorAll('.depot-card').forEach(card => {
        // Skip upgrade cards - they have inline onclick already
        if (card.dataset.upgradeCategory) return;

        card.style.cursor = 'pointer';
        card.addEventListener('click', (e) => {
            if (e.target.closest('button')) return; // Don't trigger on button clicks
            showDepotItemDetail(card);
        });
    });
}

// Effect label mapping for rich modals
const EFFECT_LABELS = {
    'passive_income_mult': 'Passive Generation', 'expedition_speed_mult': 'Expedition Speed',
    'cargo_slots': 'Cargo Capacity', 'fuel_cost_mult': 'Cost Efficiency',
    'discovery_chance_bonus': 'Discovery Chance', 'rare_chance_bonus': 'Rare Find Chance',
    'legendary_chance_bonus': 'Legendary Chance', 'discovery_value_mult': 'Discovery Value',
    'bio_discovery_value_mult': 'Bio Sample Value', 'life_support_cost_mult': 'Life Support',
    'dust_storm_immune': 'Storm Immunity', 'night_generation': 'Night Shards',
    'fuel_cost_reduction': 'Cost Savings', 'expedition_capacity': 'Max Expeditions',
    'discovery_bonus': 'Discovery Chance', 'all_generation_mult': 'All Generation',
    'legendary_discovery_chance': 'Legendary Chance', 'research_enabled': 'Xenobiology Research',
    'expedition_range': 'Expedition Range', 'passive_income_base': 'Base Income'
};

function formatEffectValue(key, val) {
    if (val === true || val === 'true' || val === 'True') return 'Enabled';
    const n = parseFloat(val);
    if (isNaN(n)) return String(val);
    if (key.includes('_mult')) return `${n.toFixed(2)}x`;
    if (key.includes('_bonus') || key.includes('_chance') || key.includes('_reduction')) return `+${Math.round(n * 100)}%`;
    if (key === 'cargo_slots' || key === 'expedition_capacity') return `+${n}`;
    return String(val);
}

function formatBuildTime(seconds) {
    if (!seconds) return 'Instant';
    // Bug #1425: apply build_time_mult so the modal matches the card row's
    // discounted figure. Actual upgrade-start in flow.py / construction.py
    // already applies the same multiplier — display was the only liar.
    const mult = (window.DEPOT_DATA && DEPOT_DATA.buildTimeMult) || 1.0;
    const adjusted = Math.max(60, seconds * mult);
    const savedPct = mult < 1.0 ? Math.round((1 - mult) * 100) : 0;
    // Bug #1444: route through the shared formatDaysHours helper so "Build Time"
    // labels match the in-progress countdowns ("5d 12h" not "5.5 days").
    let label;
    if (adjusted >= 86400 * 365) label = `${(adjusted / (86400 * 365)).toFixed(1)} years`;
    else label = formatDaysHours(adjusted);
    return savedPct > 0 ? `${label} (−${savedPct}%)` : label;
}

function formatReqName(id) { return id.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()); }

function showDepotItemDetail(card) {
    const img = card.querySelector('.depot-card-image');
    const name = card.querySelector('.depot-card-header h4')?.textContent || '';
    const price = card.querySelector('.depot-card-price')?.textContent || '';
    const desc = card.querySelector('.depot-card-desc')?.textContent || '';
    const tag = card.querySelector('.depot-card-tag')?.textContent || '';
    const owned = card.dataset.owned === 'true';
    const status = card.dataset.status;
    const isBuilding = status === 'building';
    const secondsRemaining = card._remainingSeconds || parseInt(card.dataset.secondsRemaining) || 0;

    const stats = [];
    let priceText = owned ? '✓ Owned' : (price ? `${price} Shards` : '');

    if (isBuilding) {
        // Bug #1444: shared formatDaysHours helper across every depot countdown.
        priceText = '🔧 ' + formatDaysHours(secondsRemaining) + ' remaining';
    }

    // Infrastructure items - rich data from INFRA_ITEMS
    const infraType = card.dataset.infraType;
    if (infraType && INFRA_ITEMS[infraType]) {
        const d = INFRA_ITEMS[infraType];
        const tierNames = { 1: 'Starter', 2: 'Early', 3: 'Mid', 4: 'Late', 5: 'Advanced' };
        const catNames = { power: 'Shard Generation', extraction: 'Extraction', habitat: 'Habitat', research: 'Research', life_support: 'Life Support', logistics: 'Logistics' };
        stats.push({ label: 'Tier', value: `${d.tier} (${tierNames[d.tier] || 'Unknown'})` });
        stats.push({ label: 'Type', value: catNames[d.category] || d.category });
        stats.push({ label: 'Build Time', value: formatBuildTime(d.build_time) });
        if (d.generates && d.gen_rate) stats.push({ label: 'Generates', value: `${d.gen_rate}/hr ${d.generates}` });
        if (d.effect && d.effect_value !== 0) stats.push({ label: EFFECT_LABELS[d.effect] || d.effect, value: formatEffectValue(d.effect, d.effect_value) });
        if (d.requirements.length) stats.push({ label: 'Requires', value: d.requirements.map(formatReqName).join(', ') });
        else stats.push({ label: 'Requires', value: 'None' });
        ItemDetailModal.show({ name, image: img?.src || null, category: `Tier ${d.tier} Infrastructure`, description: desc, price: priceText, stats });
        return;
    }

    // Equipment items - rich data from SHOP_ITEMS
    const itemId = card.dataset.itemId;
    if (itemId && SHOP_ITEMS[itemId]) {
        const d = SHOP_ITEMS[itemId];
        stats.push({ label: 'Type', value: d.category });
        stats.push({ label: 'Build Time', value: formatBuildTime(d.build_time) });
        if (d.max_owned > 1) stats.push({ label: 'Max Owned', value: `${d.current_owned}/${d.max_owned}` });
        // Show all effects as stats
        for (const [key, val] of Object.entries(d.effects)) {
            stats.push({ label: EFFECT_LABELS[key] || key, value: formatEffectValue(key, val) });
        }
        if (d.requirements.length) stats.push({ label: 'Requires', value: d.requirements.map(formatReqName).join(', ') });
        else stats.push({ label: 'Requires', value: 'None' });
        if (owned) stats.push({ label: 'Status', value: '✓ Active' });
        ItemDetailModal.show({ name, image: img?.src || null, category: tag, description: desc, price: priceText, stats });
        return;
    }

    // Fallback for commander cards etc - basic card scraping
    ItemDetailModal.show({ name, image: img?.src || null, category: isBuilding ? '🔧 BUILDING' : tag, description: desc, price: priceText });
}

// Show detail modal for owned colony structures (reads from data attributes)
function showStructureDetailFromData(el) {
    const d = el.dataset;

    // Special handling for Xenobiology Lab - open research modal
    if (d.buildingType === 'xenobiology_lab' && d.buildingStatus === 'active') {
        openXenobiologyModal();
        return;
    }

    const stats = [];

    // Tier badge
    const tier = parseInt(d.buildingTier) || 1;
    const tierNames = { 1: 'Starter', 2: 'Early', 3: 'Mid', 4: 'Late', 5: 'Advanced' };
    stats.push({ label: 'Tier', value: `${tier} (${tierNames[tier] || 'Unknown'})` });

    // Category
    const categoryNames = {
        'power': 'Shard Generation', 'extraction': 'Extraction', 'habitat': 'Habitat',
        'research': 'Research', 'life_support': 'Life Support', 'logistics': 'Logistics'
    };
    if (d.buildingCategory) {
        stats.push({ label: 'Type', value: categoryNames[d.buildingCategory] || d.buildingCategory });
    }

    // Status and dates
    if (d.buildingStatus === 'building') {
        const readyAt = new Date(d.buildingReadyAt);
        const now = new Date();
        const remainingMs = readyAt - now;
        let timeStr = 'Ready soon';
        if (remainingMs > 0) {
            const hours = Math.floor(remainingMs / 3600000);
            const mins = Math.floor((remainingMs % 3600000) / 60000);
            if (hours > 0) timeStr = `${hours}h ${mins}m remaining`;
            else timeStr = `${mins}m remaining`;
        }
        stats.push({ label: 'Status', value: `<img src="${DEPOT_ICONS.hammer_building}" alt="" style="width: 14px; height: 14px; vertical-align: middle;"> Building` });
        stats.push({ label: 'Completion', value: timeStr });
        stats.push({ label: 'Ready At', value: readyAt.toLocaleString() });
    } else {
        stats.push({ label: 'Status', value: `<img src="${DEPOT_ICONS.success_check}" alt="" style="width: 14px; height: 14px; vertical-align: middle;"> Active` });
        if (d.buildingBuiltAt) {
            stats.push({ label: 'Built', value: new Date(d.buildingBuiltAt).toLocaleDateString() });
        }
    }

    // Cost paid
    const cost = parseInt(d.buildingCost) || 0;
    if (cost > 0) {
        stats.push({ label: 'Cost Paid', value: `${cost.toLocaleString()} shards` });
    } else {
        stats.push({ label: 'Cost Paid', value: 'Free (starter)' });
    }

    // Generation rate
    const rate = parseFloat(d.buildingRate) || 0;
    if (d.buildingGenerates && rate > 0) {
        stats.push({ label: 'Generating', value: `${rate.toFixed(1)}/hr ${d.buildingGenerates}` });

        // Total generated lifetime
        const totalGen = parseFloat(d.buildingTotalGenerated) || 0;
        if (totalGen > 0) {
            stats.push({ label: 'Total Generated', value: `${totalGen.toLocaleString(undefined, {maximumFractionDigits: 1})} shards` });
        }
    }

    // Effect if any
    if (d.buildingEffect) {
        const effectNames = {
            'night_generation': 'Night Shards',
            'fuel_cost_reduction': 'Cost Savings',
            'expedition_capacity': 'Expedition Slots',
            'discovery_bonus': 'Discovery Chance',
            'discovery_chance_bonus': 'Discovery Chance',
            'rare_chance_bonus': 'Rare Find Chance',
            'legendary_chance_bonus': 'Legendary Chance',
            'discovery_value_mult': 'Discovery Value',
            'expedition_range': 'Expedition Range',
            'expedition_speed_mult': 'Travel Speed',
            'fuel_cost_mult': 'Expedition Cost',
            'life_support_cost_mult': 'Life Support Cost',
            'dust_storm_immune': 'Dust Storm Immunity',
            'all_generation_mult': 'All Generation',
            'legendary_discovery_chance': 'Legendary Chance',
            'research_enabled': 'Research',
            'passive_income_base': 'Passive Income'
        };
        const effectName = effectNames[d.buildingEffect] || d.buildingEffect;
        let effectValue = d.buildingEffectValue;
        const numVal = parseFloat(effectValue);
        if (!isNaN(numVal) && numVal < 1) {
            effectValue = `+${Math.round(numVal * 100)}%`;
        } else if (!isNaN(numVal) && numVal > 1) {
            effectValue = `${numVal}×`;
        } else if (effectValue === 'True' || effectValue === 'true') {
            effectValue = 'Enabled';
        }
        stats.push({ label: effectName, value: effectValue });
    }

    ItemDetailModal.show({
        name: d.buildingName,
        image: d.buildingImage || null,
        category: `Tier ${tier} Colony Structure`,
        description: d.buildingDescription || 'Part of your Mars colony infrastructure.',
        stats: stats
    });
}

// Infrastructure building (moved from core.js)
async function buildStructure(type, name, time, cost) {
    if (isTxLocked()) {
        showToast('Please wait for the current operation to complete.', 'warning');
        return;
    }
    const btn = event.target;
    // Check affordability before attempting purchase
    if (cost > 0 && currentBalance < cost) {
        showToast(`Need ${cost.toFixed(0)} Sepolia Shards, have ${currentBalance.toFixed(1)}`, 'warning', 'Insufficient Funds');
        return;
    }
    lockAllPurchases();
    disableBtn(btn);
    showToast(`🚀 Building ${name}...`, 'success', 'Construction Started', 4000);
    try {
        const data = await apiPost('/api/infrastructure/build', { structure_type: type });
        if (data.success) {
            // Update balance immediately from response
            if (data.new_balance !== undefined) setBalance(data.new_balance);
            // Check if this is a first-time build (reward pending = new user flow)
            if (data.reward && data.reward.pending) {
                showToast(`✅ ${name} construction started! +${data.reward.amount.toFixed(0)} Shards incoming. Explore Mars while it processes!`, 'success', 'Colony Established', 5000);
                // Redirect to expeditions after a moment - give them something to do!
                setTimeout(() => { window.location.href = '/expeditions'; }, 3000);
            } else {
                // Show build time in message
                const timeStr = data.time_display ? ` (${data.time_display})` : '';
                showToast(`🔧 ${name} construction started!${timeStr}`, 'success', 'Construction Started', 4000);
                setTimeout(() => location.reload(), 2000);
            }
        } else {
            showToast(sanitizeErrorMsg(data.error), 'error');
            unlockAllPurchases();
            enableBtn(btn);
        }
    }
    catch (e) { showToast(sanitizeErrorMsg(e.message) || 'Connection failed. Please try again.', 'error'); unlockAllPurchases(); enableBtn(btn); }
}


// --- Shard Rush (bug #1270 Phase 4) ---
async function confirmShardRush(btn) {
    if (isTxLocked()) {
        showToast('Please wait for the current operation to complete.', 'warning');
        return;
    }
    const category = btn.dataset.category;
    const itemKey = btn.dataset.itemKey;
    const name = btn.dataset.name;
    const targetLevel = btn.dataset.targetLevel;
    const rushCost = parseInt(btn.dataset.rushCost, 10);
    const rushPct = btn.dataset.rushPct;

    MarsModal.show({
        title: '⚡ Shard Rush',
        body: `<div style="font-size: 14px; line-height: 1.6;">
            <p>Pay <strong>${rushCost.toLocaleString()} shards</strong> to instantly complete <strong>${escapeHtml(name)} Lv${targetLevel}</strong>.</p>
            <p style="color: var(--text-muted); font-size: 12px; margin-top: 8px;">Rush cost: ${rushPct}% of base upgrade price (discount grows with Life Support + Water Extractor levels).</p>
        </div>`,
        footer: `
            <button class="btn btn-secondary" id="shardRushCancelBtn">Cancel</button>
            <button class="btn btn-primary" id="shardRushConfirmBtn">⚡ Rush for ${rushCost.toLocaleString()}</button>
        `
    });
    document.getElementById('shardRushCancelBtn').onclick = () => MarsModal.hide();
    document.getElementById('shardRushConfirmBtn').onclick = () => {
        MarsModal.hide();
        executeShardRush(category, itemKey, name);
    };
}

async function executeShardRush(category, itemKey, name) {
    lockAllPurchases();
    showToast(`⚡ Rushing ${name}...`, 'success', 'Shard Rush', 3000);
    try {
        const isInfraL1 = category === 'infrastructure' && document.querySelector(`.btn-shard-rush[data-item-key="${itemKey}"][data-target-level="1"]`);
        const endpoint = isInfraL1 ? '/api/shard-rush/infrastructure' : '/api/shard-rush/upgrade';
        const payload = isInfraL1 ? { structure_type: itemKey } : { category, item_key: itemKey };
        const resp = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await resp.json();
        if (data.success && data.rushed) {
            showToast(`✅ ${name} complete! ${data.rush_cost.toLocaleString()} shards spent.`, 'success', 'Rush Complete', 4000);
            // Bug #21 Deploy C: stat-up toast(s) from the rush level-up
            if (typeof processStatEvents === 'function') processStatEvents(data);
            setTimeout(() => window.location.reload(), 1200);
        } else {
            showToast(sanitizeErrorMsg(data.error) || 'Rush failed.', 'error', 'Rush Failed');
            unlockAllPurchases();
        }
    } catch (e) {
        showToast(sanitizeErrorMsg(e.message) || 'Connection failed.', 'error', 'Rush Failed');
        unlockAllPurchases();
    }
}
