/* Shared Discovery & Extraction Utilities
 * Used by: colony-discoveries.js, inventory.js
 * Functions: loadDiscoveries, renderDiscoveries, filterDiscoveries, sortDiscoveries,
 *            updateShardItAllBanner, showShardItAllModal, executeShardItAll
 */

let allDiscoveries = [];
let discoveryValueMult = 1.0;
let bioDiscoveryValueMult = 1.0;

async function loadDiscoveries() {
    try {
        const response = await fetch('/api/user/claimed_discoveries');
        const data = await response.json();

        // ARIA Bonds rendering handled by colony.js renderAriaBonds() from PAGE_DATA

        if (!data.success || !data.discoveries.length) {
            document.getElementById('discoveriesGrid').innerHTML = `
                <div class="empty-state">
                    <img src="${UI_ICONS.empty_discoveries}" alt="" class="empty-state-icon" style="width: 48px; height: 48px; opacity: 0.5;">
                    <div class="empty-state-text">No discoveries yet. Start exploring!</div>
                    <a href="/expeditions" class="btn btn-purple">Begin Expedition</a>
                </div>`;
            return;
        }

        const rarityOrder = { legendary: 0, rare: 1, uncommon: 2, common: 3 };
        allDiscoveries = data.discoveries.sort((a, b) => rarityOrder[a.rarity] - rarityOrder[b.rarity]);
        discoveryValueMult = data.discovery_value_mult || 1.0;
        bioDiscoveryValueMult = data.bio_discovery_value_mult || 1.0;

        // Update stats (elements may not exist on all pages)
        const el = id => document.getElementById(id);
        if (el('totalItems')) el('totalItems').textContent = data.total_count.toLocaleString();
        if (el('totalValue')) el('totalValue').textContent = data.total_scientific_value.toFixed(0).toLocaleString();
        if (el('totalWeight')) el('totalWeight').textContent = data.total_weight_kg.toFixed(1) + ' kg';
        if (el('legendaryCount')) el('legendaryCount').textContent = (data.by_rarity.legendary || 0).toLocaleString();

        // Update Shard It All banner
        updateShardItAllBanner(allDiscoveries);

        renderDiscoveries(allDiscoveries);
    } catch (error) {
        console.error('Failed to load discoveries:', error);
        document.getElementById('discoveriesGrid').innerHTML = `
            <div class="empty-state">
                <img src="${UI_ICONS.warning_alert}" alt="" class="empty-state-icon" style="width: 48px; height: 48px; opacity: 0.5;">
                <div class="empty-state-text">Failed to load discoveries</div>
            </div>`;
    }
}


function renderDiscoveries(discoveries) {
    const container = document.getElementById('discoveriesGrid');
    if (!discoveries.length) {
        container.innerHTML = `
            <div class="empty-state">
                <img src="${UI_ICONS.empty_discoveries}" alt="" class="empty-state-icon" style="width: 48px; height: 48px; opacity: 0.5;">
                <div class="empty-state-text">No items match this filter</div>
            </div>`;
        return;
    }

    // Rarity icons as image URLs
    const rarityIconUrls = {
        legendary: UI_ICONS.rarity_legendary,
        rare: UI_ICONS.rarity_rare,
        uncommon: UI_ICONS.rarity_uncommon,
        common: UI_ICONS.rarity_common
    };

    container.innerHTML = discoveries.map(d => `
        <div class="inv-card rarity-${d.rarity}" onclick="showDiscoveryDetails(${d.discovery_item_id})" data-rarity="${d.rarity}" data-value="${d.enhanced_value}" data-weight="${d.weight_kg || 0}" data-distance="${d.found_at_km}" data-date="${d.claimed_at}">
            ${d.image_url ?
                `<img src="${d.image_url}" class="inv-card-image" alt="${d.item_name}" loading="lazy">` :
                `<div class="inv-card-image"><img src="${rarityIconUrls[d.rarity] || UI_ICONS.rarity_common}" alt="${d.rarity}" style="width: 40px; height: 40px;"></div>`}
            <div class="inv-card-content">
                <div class="inv-card-header">
                    <div class="inv-card-name">${d.item_name}</div>
                    <div class="inv-card-value rarity-${d.rarity}">${d.enhanced_value.toFixed(0)}</div>
                </div>
                <div class="inv-card-type">
                    <span class="rarity-badge rarity-${d.rarity} rarity-badge-compact"><img src="${rarityIconUrls[d.rarity]}" alt="" style="width: 12px; height: 12px; vertical-align: middle;"> ${d.rarity.toUpperCase()}</span>
                    <span class="inv-item-type">${d.item_type || 'Sample'}</span>
                    ${d.quantity > 1 ? `<span class="inv-item-qty">×${d.quantity}</span>` : ''}
                </div>
                ${d.description ? `<div class="inv-card-desc">${d.description.substring(0, 80)}${d.description.length > 80 ? '...' : ''}</div>` : ''}
                <div class="inv-card-stats">
                    <div class="inv-stat">
                        <div class="inv-stat-value">${d.weight_kg || 0}</div>
                        <div class="inv-stat-label">Weight (kg)</div>
                    </div>
                    <div class="inv-stat">
                        <div class="inv-stat-value">${d.found_at_km.toFixed(0)}</div>
                        <div class="inv-stat-label">Found (km)</div>
                    </div>
                    <div class="inv-stat">
                        <div class="inv-stat-value">${d.base_scientific_value || d.enhanced_value.toFixed(0)}</div>
                        <div class="inv-stat-label">Base Value</div>
                    </div>
                </div>
                <div class="inv-card-details">
                    <div class="inv-card-details-row">
                        <span title="Expedition destination"><img src="${UI_ICONS.location_pin}" alt="" style="width: 12px; height: 12px;"> ${d.destination_name}</span>
                        <span title="Discovery date"><img src="${UI_ICONS.calendar_date}" alt="" style="width: 12px; height: 12px;"> ${new Date(d.claimed_at).toLocaleDateString()}</span>
                    </div>
                    ${d.expedition_id ? `<div class="inv-card-expedition">Expedition #${d.expedition_id}</div>` : ''}
                </div>
            </div>
        </div>
    `).join('');
}

function filterDiscoveries(rarity) {
    document.querySelectorAll('.filter-btn').forEach(p => p.classList.remove('active'));
    document.querySelector(`[data-filter="${rarity}"]`).classList.add('active');

    const filtered = rarity === 'all' ? allDiscoveries : allDiscoveries.filter(d => d.rarity === rarity);
    // Re-apply current sort after filtering
    const currentSort = document.getElementById('discoverySort').value;
    sortDiscoveriesInternal(filtered, currentSort);
}

function sortDiscoveries(sortBy) {
    // Get currently filtered discoveries
    const activeFilter = document.querySelector('.filter-btn.active')?.dataset.filter || 'all';
    const filtered = activeFilter === 'all' ? allDiscoveries : allDiscoveries.filter(d => d.rarity === activeFilter);
    sortDiscoveriesInternal(filtered, sortBy);
}

function sortDiscoveriesInternal(discoveries, sortBy) {
    let sorted = [...discoveries];
    const rarityOrder = { legendary: 0, rare: 1, uncommon: 2, common: 3 };

    switch (sortBy) {
        case 'rarity-desc':
            sorted.sort((a, b) => rarityOrder[a.rarity] - rarityOrder[b.rarity]);
            break;
        case 'rarity-asc':
            sorted.sort((a, b) => rarityOrder[b.rarity] - rarityOrder[a.rarity]);
            break;
        case 'value-desc':
            sorted.sort((a, b) => b.enhanced_value - a.enhanced_value);
            break;
        case 'value-asc':
            sorted.sort((a, b) => a.enhanced_value - b.enhanced_value);
            break;
        case 'weight-desc':
            sorted.sort((a, b) => (b.weight_kg || 0) - (a.weight_kg || 0));
            break;
        case 'weight-asc':
            sorted.sort((a, b) => (a.weight_kg || 0) - (b.weight_kg || 0));
            break;
        case 'distance-desc':
            sorted.sort((a, b) => b.found_at_km - a.found_at_km);
            break;
        case 'recent':
            sorted.sort((a, b) => new Date(b.claimed_at) - new Date(a.claimed_at));
            break;
        case 'oldest':
            sorted.sort((a, b) => new Date(a.claimed_at) - new Date(b.claimed_at));
            break;
        default:
            sorted.sort((a, b) => rarityOrder[a.rarity] - rarityOrder[b.rarity]);
    }
    renderDiscoveries(sorted);
}

const scientistBulkQuotes = [
    "Another gorgeous Sepolia formation! These crystalline beauties never cease to amaze me.",
    "Red dust meets pure energy. Mars continues to whisper her secrets.",
    "Look at those shard geometries! Exquisite molecular architecture in miniature.",
    "Crystallography is poetry written in atomic landscapes. This specimen is pure verse.",
    "Every shard tells a story older than human civilization. Listen closely.",
    "Remarkable! The molecular resonance on this sample is off the charts.",
    "Mars doesn't give up her treasures easily. But we're persistent scientists.",
    "Fascinating fractal patterns. The universe loves complexity!",
    "These Sepolia shards are like frozen music from an alien symphony.",
    "Extracting energy from stone — we're basically planetary alchemists.",
    "The red planet never disappoints. What quantum secrets will this reveal?",
    "Crystalline structures more complex than any Earth-based mineral. Pure magic.",
    "Another testament to Mars' incredible geological DNA.",
    "Each shard is a miniature time capsule of Martian history.",
    "Quantum resonance incoming! Prepare for molecular excitement.",
    "The atoms are dancing today. Beautiful, beautiful science.",
    "Martian minerals continue to challenge everything we know.",
    "Pure energy, compressed into geometric perfection.",
    "These shards are literal stardust, compressed and transformed.",
    "Mars whispers her secrets through these magnificent structures.",
    "Geological miracles, right here in our extraction chamber.",
    "Mars doesn't just give; she reveals profound mysteries.",
    "The universe encoded in crystalline structures.",
    "Mars continues to surprise even the most seasoned scientists.",
    "Sepolia shards: nature's quantum batteries.",
    "Extracting energy from stone — just another day on Mars.",
    "These crystals hold more stories than human libraries.",
    "Mars speaks through her minerals. We're just learning the language.",
    "The red dust reveals another of its magnificent secrets.",
    "Each Sepolia shard is a quantum time machine.",
    "Mars reveals her secrets, one shard at a time.",
    "Another shard sings its crystalline song through the resonance chamber.",
    "Olympus Mons could fit an entire civilization in these microscopic lattices.",
    "Dust storms outside, precision work inside. Classic Martian Tuesday.",
    "Low gravity makes shard extraction... weirdly elegant.",
    "Iron oxide whispers secrets through these Sepolia fragments.",
    "I left Earth's complexity for THIS complexity. No regrets.",
    "Calibrating harmonic frequencies. The crystal speaks, we listen.",
    "Valles Marineris might be big, but these shards hold entire universes.",
    "Still amazed something this beautiful grows in Martian regolith.",
    "Crushing procedure complete. Molecular poetry in progress.",
    "Phobos watches. Always watching. Always judging my extraction technique.",
    "Another perfectly fractured shard. Mars, you magnificent research beast.",
    "Sometimes science is just aggressive appreciation of beauty.",
    "These crystals remember more geological history than humanity ever will.",
    "Extraction isn't a process. It's a conversation with ancient stone.",
    "Deimos rises. Time to realign the resonance grid.",
    "Who needs Earth's complicated labs? This closet-sized station works perfectly.",
    "Shard lattice looking particularly sassy today.",
    "Breaking rocks, breaking records. Just another Martian workday.",
    "Resonance frequency: tuned. Existential wonder: maximum.",
    "If these crystals could talk... well, they kind of do.",
    "Regolith today, interplanetary energy source tomorrow.",
    "Precision isn't a choice on Mars. It's survival.",
    "Crushing procedure: part science, part interpretive dance.",
    "Every shard is a tiny manuscript of planetary memory.",
    "Mars doesn't just give up its secrets. It negotiates.",
    "Extraction technique: part surgeon, part poet, part rock whisperer.",
    "Low gravity makes everything a delicate ballet of science.",
    "Another sol, another thousand microscopic universes discovered.",
    "Who knew rocks could be this... charismatic?",
    "Sepolia shards: nature's most elegant energy storage system.",
    "Calibration complete. The crystal hums its agreement.",
    "Resonance chamber activated. Prepare for molecular magic.",
    "Some people collect stamps. I collect planetary energy signatures.",
    "Dust storms can't interrupt THIS level of concentration.",
    "Each shard is a tiny, perfect rebellion against entropy.",
    "Martian research: where 'mundane' is a foreign concept.",
    "Crushing crystals with the tenderness of a neurosurgeon.",
    "Sometimes science feels like translating an alien language.",
    "Phobos and Deimos: my silent research assistants.",
    "Energy extraction isn't a job. It's a calling.",
    "Another day, another thousand microscopic universes mapped.",
    "The ordinary becomes extraordinary when viewed as raw Sepolia shard resonance.",
    "These common finds hide ancient Sepolia shard potential. Let me release it.",
    "So many samples, so little time. Let us be thorough.",
    "Each extraction teaches me something new about Martian crystallography.",
    "A mountain of specimens, a river of shards. The cycle continues.",
    "Every crystal extracted brings us closer to understanding this world.",
    "These samples have served their purpose. The shards within call to be free..."
];

function updateShardItAllBanner(discoveries) {
    const banner = document.getElementById('shardItAllBanner');
    const quoteEl = document.getElementById('shardBannerQuote');
    const countEl = document.getElementById('shardableCount');
    const valueEl = document.getElementById('shardableValue');

    // Filter to only common and uncommon (shardable items)
    const shardable = discoveries.filter(d => d.rarity === 'common' || d.rarity === 'uncommon');

    if (shardable.length === 0) {
        banner.style.display = 'none';
        return;
    }

    // Calculate totals with multipliers + equipment bonuses
    const payoutMultipliers = { common: 0.5, uncommon: 0.75 };
    let totalCount = 0;
    let totalShards = 0;

    shardable.forEach(d => {
        const qty = d.quantity || 1;
        totalCount += qty;
        let payout = Math.floor(d.enhanced_value * qty * (payoutMultipliers[d.rarity] || 0.5));
        if (discoveryValueMult > 1.0) payout = Math.floor(payout * discoveryValueMult);
        if (d.item_type === 'biological' && bioDiscoveryValueMult > 1.0) payout = Math.floor(payout * bioDiscoveryValueMult);
        totalShards += payout;
    });

    const totalSV = Math.floor(totalShards * 0.15);

    // Update banner
    countEl.textContent = totalCount;
    valueEl.textContent = totalShards.toLocaleString();
    quoteEl.textContent = `"${scientistBulkQuotes[Math.floor(Math.random() * scientistBulkQuotes.length)]}"`;
    banner.style.display = 'flex';
}

function showShardItAllModal() {
    // Get shardable items for confirmation
    const shardable = allDiscoveries.filter(d => d.rarity === 'common' || d.rarity === 'uncommon');
    if (shardable.length === 0) {
        showToast('No common or uncommon discoveries to shard', 'info');
        return;
    }

    const payoutMultipliers = { common: 0.5, uncommon: 0.75 };
    let totalCount = 0;
    let totalShards = 0;
    let commonCount = 0;
    let uncommonCount = 0;
    shardable.forEach(d => {
        const qty = d.quantity || 1;
        totalCount += qty;
        let payout = Math.floor(d.enhanced_value * qty * (payoutMultipliers[d.rarity] || 0.5));
        if (discoveryValueMult > 1.0) payout = Math.floor(payout * discoveryValueMult);
        if (d.item_type === 'biological' && bioDiscoveryValueMult > 1.0) payout = Math.floor(payout * bioDiscoveryValueMult);
        totalShards += payout;
        if (d.rarity === 'common') commonCount += qty;
        if (d.rarity === 'uncommon') uncommonCount += qty;
    });
    const totalSV = Math.floor(totalShards * 0.15);

    // Pick a random scientist quote
    const quote = scientistBulkQuotes[Math.floor(Math.random() * scientistBulkQuotes.length)];

    // Use ItemDetailModal for confirmation
    ItemDetailModal.show({
        name: 'Bulk Extraction',
        image: null,
        category: `<img src="${UI_ICONS.shard_gem}" alt="" style="width: 16px; height: 16px; vertical-align: middle;"> Shard It All`,
        description: `Extract shards from all ${totalCount} common and uncommon specimens in your inventory.`,
        stats: [
            { label: 'Specimens', value: totalCount },
            { label: 'Common', value: commonCount },
            { label: 'Uncommon', value: uncommonCount },
            { label: 'Total Shards', value: totalShards.toLocaleString() },
            { label: 'SV Bonus', value: `+${totalSV} SV (15%)` }
        ],
        effects: `<div class="shard-modal-quote">
            "${quote}"
            <div class="shard-modal-warning">
                <img src="${UI_ICONS.warning_alert}" alt="" style="width: 14px; height: 14px; vertical-align: middle;"> This will permanently extract all common and uncommon discoveries. Rare and legendary items are preserved.
            </div>
        </div>`,
        action: {
            label: `Extract All (${totalShards.toLocaleString()} Shards + ${totalSV} SV)`,
            className: 'btn-warning',
            onClick: executeShardItAll
        }
    });
}

async function executeShardItAll() {
    // Disable button and show processing
    const btn = document.getElementById('mmActionBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Extracting...'; }

    try {
        const response = await fetch('/api/discovery/shard_all', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await response.json();

        if (data.success) {
            ItemDetailModal.hide();
            // Build message with bonus info if applicable
            let msg = `Extracted ${data.shards_received.toFixed(0)} Shards from ${data.quantity_analyzed} specimens!`;
            if (data.bonus_applied && data.discovery_value_mult > 1.0) {
                const bonusPct = ((data.discovery_value_mult - 1) * 100).toFixed(0);
                // Show bonus type - include bio bonus info if applicable
                if (data.bio_bonus_applied && data.bio_bonus_count > 0) {
                    msg += ` (Research Lab + Cryo Storage +${bonusPct}%)`;
                } else {
                    msg += ` (Research Lab +${bonusPct}%)`;
                }
            }
            if (data.sv_awarded > 0) msg += ` + ${data.sv_awarded} SV`;
            showToast(msg, 'success', 'Bulk Extraction Complete', 5000);
            // Update balance display
            if (typeof currentBalance !== 'undefined') {
                currentBalance += data.shards_received;
                updateBalanceDisplay();
            }
            if (data.sv_awarded > 0 && typeof adjustSV === 'function') adjustSV(data.sv_awarded);
            // Refresh page after delay
            setTimeout(() => location.reload(), 2500);
        } else {
            showToast(data.error || 'Extraction failed', 'error');
            if (btn) { btn.disabled = false; btn.textContent = 'Extract All'; }
        }
    } catch (e) {
        showToast('Network error', 'error');
        if (btn) { btn.disabled = false; btn.textContent = 'Extract All'; }
    }
}

// Format equipment effects for display (shared by colony + inventory)
function formatEffects(effects) {
    return Object.entries(effects).map(([k, v]) => {
        if (k === 'expedition_speed_mult') return `+${((v - 1) * 100).toFixed(0)}% speed`;
        if (k === 'discovery_chance_mult') return `+${((v - 1) * 100).toFixed(0)}% discovery`;
        if (k === 'discovery_chance_bonus') return `+${(v * 100).toFixed(0)}% discovery`;
        if (k === 'rare_find_mult') return `+${((v - 1) * 100).toFixed(0)}% rare finds`;
        if (k === 'rare_chance_bonus') return `+${(v * 100).toFixed(0)}% rare finds`;
        if (k === 'legendary_chance_bonus') return `+${(v * 100).toFixed(0)}% legendary`;
        if (k === 'cargo_slots') return `+${v} cargo`;
        if (k === 'fuel_cost_mult') return `-${((1 - v) * 100).toFixed(0)}% cost`;
        if (k === 'life_support_cost_mult') return `-${((1 - v) * 100).toFixed(0)}% life support`;
        if (k === 'passive_income_mult') return `+${((v - 1) * 100).toFixed(0)}% passive`;
        if (k === 'passive_income_base') return `+${v}/hr passive`;
        return `${k}: ${v}`;
    }).join(' &bull; ');
}

