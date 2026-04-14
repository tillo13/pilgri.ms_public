/* Depot Page - Upgrade System & Shop Purchases */
/* Depends on: depot.js (sanitizeErrorMsg, lockAllPurchases, unlockAllPurchases, isTxLocked) */

// ============================================================================
// UPGRADE SYSTEM
// ============================================================================
async function performUpgrade(category, itemKey) {
    if (isTxLocked()) {
        showToast('Please wait for the current operation to complete.', 'warning');
        return;
    }
    lockAllPurchases();
    const card = document.querySelector(`[data-upgrade-category="${category}"][data-upgrade-item="${itemKey}"]`);
    const btn = card?.querySelector('button');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Upgrading...';
    }

    try {
        const data = await apiPost('/api/upgrade', { category, item_key: itemKey });

        if (data.success) {
            // Check if this is a building upgrade (has wait time) vs instant
            if (data.is_building && data.build_time_days > 0) {
                // Building started - show construction message with time
                const days = data.build_time_days;
                let timeStr;
                if (days >= 14) timeStr = '2 weeks';
                else if (days >= 7) timeStr = '1 week';
                else if (days > 1) timeStr = `${days} days`;
                else timeStr = '1 day';

                if (data.is_first_reveal) {
                    showToast(`First in the colony! ${data.item_name} construction started!\nReady in ${timeStr}.`, 'celebration', 'Construction Started', 6000);
                } else {
                    showToast(`${data.item_name} construction started!\nReady in ${timeStr}.`, 'success', 'Construction Started', 5000);
                }
            } else {
                // Instant upgrade (build_time_days = 0)
                if (data.is_first_reveal) {
                    showToast(`First in the colony! You discovered ${data.item_name} ${data.level_name}!`, 'celebration', 'Discovery', 6000);
                } else {
                    showToast(`${data.item_name} upgraded to ${data.level_name}!`, 'success', 'Upgrade', 4000);
                }
            }
            // Reload page to show updated state (building timer or completed)
            setTimeout(() => location.reload(), 1500);
        } else {
            showToast(sanitizeErrorMsg(data.error) || 'Upgrade failed', 'error');
            unlockAllPurchases();
            if (btn) btn.textContent = 'Upgrade';
        }
    } catch (e) {
        showToast('Connection error', 'error');
        unlockAllPurchases();
        if (btn) btn.textContent = 'Upgrade';
    }
}

// ============================================================================
// RICH UPGRADE MODAL (deep-link from expedition modal + depot card clicks)
// ============================================================================
function formatBuildTimeRemaining(seconds) {
    if (!seconds || seconds <= 0) return 'Ready';
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    if (days >= 14) return '2 weeks';
    if (days >= 7) return `${Math.floor(days / 7)} week${days >= 14 ? 's' : ''}`;
    if (days > 0) return `${days}d ${hours}h`;
    if (hours > 0) return `${hours}h ${mins}m`;
    return `${mins}m`;
}

function formatLevelStats(stats, category) {
    const parts = [];
    const green = s => `<span style="color: var(--color-success);">${s}</span>`;
    const gold = s => `<span style="color: var(--color-sepolia);">${s}</span>`;
    const red = s => `<span style="color: var(--color-danger);">${s}</span>`;

    // === VEHICLES (rover, drone, buggy) ===
    if (stats.expedition_speed_mult) parts.push(`${stats.expedition_speed_mult.toFixed(1)}× speed`);
    if (stats.max_range_km) {
        const rangeMult = DEPOT_DATA.rangeMult || 1.0;
        const effective = Math.round(stats.max_range_km * rangeMult);
        parts.push(rangeMult !== 1.0 ? `${effective.toLocaleString()} km (${stats.max_range_km.toLocaleString()} × ${rangeMult}×)` : `${stats.max_range_km.toLocaleString()} km`);
    }
    if (stats.cargo) parts.push(`${stats.cargo} cargo`);
    if (stats.fuel_cost_mult && stats.fuel_cost_mult !== 1.0) {
        if (stats.fuel_cost_mult < 1.0) parts.push(green(`-${((1 - stats.fuel_cost_mult) * 100).toFixed(0)}% cost`));
        else parts.push(red(`+${((stats.fuel_cost_mult - 1) * 100).toFixed(0)}% cost`));
    }
    // Drone/buggy discovery bonuses (can be negative!)
    if (stats.discovery_bonus !== undefined && stats.discovery_bonus !== 0) {
        parts.push(stats.discovery_bonus > 0 ? green(`+${(stats.discovery_bonus * 100).toFixed(0)}% disc`) : red(`${(stats.discovery_bonus * 100).toFixed(0)}% disc`));
    }
    if (stats.rare_bonus !== undefined && stats.rare_bonus !== 0) {
        parts.push(stats.rare_bonus > 0 ? gold(`+${(stats.rare_bonus * 100).toFixed(0)}% rare`) : red(`${(stats.rare_bonus * 100).toFixed(0)}% rare`));
    }
    if (stats.legendary_bonus !== undefined) {
        if (stats.legendary_bonus === -1.0) parts.push(red('no legendary'));
        else if (stats.legendary_bonus < 0) parts.push(red(`${(stats.legendary_bonus * 100).toFixed(0)}% legendary`));
        else if (stats.legendary_bonus > 0) parts.push(gold(`+${(stats.legendary_bonus * 100).toFixed(0)}% legendary`));
    }

    // === SCANNERS (uses _chance_ suffix) ===
    if (stats.discovery_chance_bonus) parts.push(green(`+${(stats.discovery_chance_bonus * 100).toFixed(0)}% discovery`));
    if (stats.rare_chance_bonus) parts.push(gold(`+${(stats.rare_chance_bonus * 100).toFixed(0)}% rare`));
    if (stats.legendary_chance_bonus) parts.push(gold(`+${(stats.legendary_chance_bonus * 100).toFixed(0)}% legendary`));

    // === LIFE SUPPORT ===
    if (stats.life_support_cost_mult && stats.life_support_cost_mult < 1.0) {
        parts.push(green(`-${((1 - stats.life_support_cost_mult) * 100).toFixed(0)}% life support`));
    }

    // === GENERATOR (passive_income_mult) ===
    if (stats.passive_income_mult && stats.passive_income_mult > 1.0) {
        parts.push(gold(`${stats.passive_income_mult.toFixed(2)}x passive income`));
    }

    // === RESEARCH (discovery_value_mult) ===
    if (stats.discovery_value_mult && stats.discovery_value_mult > 1.0) {
        parts.push(gold(`${stats.discovery_value_mult.toFixed(2)}x disc value`));
    }

    // === GEAR (EVA Suit) ===
    if (stats.stat_exploration_bonus) parts.push(green(`+${stats.stat_exploration_bonus}% exploration`));

    // === AUTOMATION ===
    if (stats.passive_income_base) parts.push(gold(`+${stats.passive_income_base} shards/hr`));
    if (stats.dust_storm_immune === true) parts.push(green('dust immune'));

    // === STORAGE BUNKER ===
    if (stats.storage_capacity) parts.push(`${stats.storage_capacity} storage`);
    if (stats.capacity) parts.push(`${stats.capacity} storage`);

    // === CARGO ===
    if (stats.cargo_slots) parts.push(`+${stats.cargo_slots} cargo`);
    if (stats.bio_discovery_value_mult && stats.bio_discovery_value_mult > 1.0) {
        parts.push(gold(`${stats.bio_discovery_value_mult.toFixed(2)}x bio value`));
    }

    // === INFRASTRUCTURE ===
    if (stats.generation_rate) parts.push(gold(`${stats.generation_rate.toFixed(1)}/hr`));
    if (stats.science_generation_rate) parts.push(`${stats.science_generation_rate.toFixed(1)} SV/hr`);
    if (stats.fuel_cost_reduction) parts.push(green(`-${(stats.fuel_cost_reduction * 100).toFixed(0)}% cost`));
    if (stats.life_support_reduction) parts.push(green(`-${(stats.life_support_reduction * 100).toFixed(0)}% life support`));
    if (stats.night_generation) parts.push(`${(stats.night_generation * 100).toFixed(0)}% night gen`);
    if (stats.all_generation_mult && stats.all_generation_mult > 1.0) {
        parts.push(gold(`${stats.all_generation_mult.toFixed(2)}x all gen`));
    }
    if (stats.expedition_capacity) parts.push(`${stats.expedition_capacity} expedition slots`);
    if (stats.legendary_discovery_chance) parts.push(gold(`+${(stats.legendary_discovery_chance * 100).toFixed(0)}% legendary`));
    if (stats.research_enabled === true) parts.push(green('enables xenobiology research'));

    return parts.length > 0 ? parts.join(' · ') : '';
}

// Get milestone notes for special bonuses at certain levels
function getMilestoneNote(itemKey, level) {
    const milestones = {
        'habitat_module': { 5: '⭐ +1 concurrent build slot!' },
        'automation': { 3: '⭐ Gains dust storm immunity!' },
        'regolith_forge': { 5: '⭐ Unlocks Resonance Chamber!' },
        'resonance_chamber': { 5: '⭐ Unlocks Thermal Vent Tap!' },
        'thermal_vent_tap': { 5: '⭐ Unlocks Monolith Antenna!' },
        'refinery': { 7: '⭐ Unlocks Regolith Forge!' }
    };
    return milestones[itemKey]?.[level] || '';
}

// Get detailed description for what each upgrade category does
function getUpgradeEffectDescription(category, itemKey) {
    const descriptions = {
        'vehicles': {
            'rover': 'Increases expedition speed, cargo capacity, and cost efficiency. Higher levels unlock longer range missions.',
            'drone': 'Fast aerial recon - trades discovery chance for speed. Great for quick scouting runs.',
            'buggy': 'All-terrain vehicle - balanced speed and discovery. Good for mid-range expeditions.'
        },
        'equipment': {
            'scanner': 'Boosts discovery and rare find chances during expeditions. Essential for treasure hunters.',
            'life_support': 'Reduces life support costs on all expeditions, saving shards on every mission.',
            'generator': 'Multiplies passive income from solar arrays and other sources. Compounds over time.',
            'research': 'Multiplies the value of discoveries when sold. Higher levels = more shards per find.'
        },
        'gear': {
            'suit': 'Boosts exploration stat and trail building speed (+5% per level). Better mobility on Mars.'
        },
        'automation': {
            'automation': 'Generates passive shards per hour automatically. At Lv3+, immune to dust storms.'
        },
        'storage': {
            'bunker': 'Increases discovery storage capacity. More storage = more finds before you must sell.'
        },
        'cargo': {
            'cargo': 'Adds cargo slots for expeditions. Bio-cargo upgrades boost biological discovery values.'
        },
        'infrastructure': {
            'solar_array': 'Excites Sepolia shard deposits using Mars sunlight. Main shard income source.',
            'battery_storage': 'Stores charged shards for Mars nights. Increases overnight generation.',
            'water_extractor': 'Extracts water from regolith. Reduces expedition fuel costs.',
            'refinery': 'Processes raw materials into refined shards. Direct shard generation.',
            'habitat_module': 'Expands living quarters. At Lv5, unlocks an extra build queue slot.',
            'greenhouse': 'Grows food from Martian soil. Reduces life support costs.',
            'research_station': 'Generates Scientific Value and boosts discovery values.',
            'xenobiology_lab': 'Studies alien biology discoveries. Boosts bio discovery values.',
            'comms_array': 'Long-range communications. Improves discovery chances on expeditions.',
            'regolith_forge': 'Forges materials from regolith. Generates shards and SV.',
            'resonance_chamber': 'Amplifies crystal resonance. Multiplies all generation rates.',
            'thermal_vent_tap': 'Taps geothermal energy. Immune to dust storms.',
            'monolith_antenna': 'Ancient signal receiver. Boosts legendary discovery chance.'
        }
    };
    return descriptions[category]?.[itemKey] || '';
}

function showUpgradeModal(category, itemKey) {
    const categoryData = UPGRADE_DATA[category];
    if (!categoryData) return;
    const item = categoryData[itemKey];
    if (!item) { showToast('Item not found', 'error'); return; }

    const currentLevel = item.current_level || 0;
    const maxLevel = item.max_level || 1;
    const isMax = currentLevel >= maxLevel;
    const isBuilding = item.is_building;
    const buildStatus = item.build_status;
    const nextCost = item.upgrade_cost || 0;
    const canAfford = item.can_afford && !isBuilding;  // Can't upgrade while building
    const shortfall = nextCost > CURRENT_BALANCE ? nextCost - CURRENT_BALANCE : 0;
    const effectDesc = getUpgradeEffectDescription(category, itemKey);

    // Build level progression
    let levelsHtml = '';
    for (let lv = 1; lv <= maxLevel; lv++) {
        const stats = item.all_levels ? item.all_levels[lv] : null;
        if (!stats) continue;
        const isCurrent = lv === currentLevel;
        const isNext = lv === currentLevel + 1;
        const isLocked = lv > currentLevel + 1;
        const cost = stats.cost ? stats.cost.toLocaleString() : 'Free';
        const buildDays = stats.build_time_days || 0;
        const statsLine = formatLevelStats(stats, category);
        const milestone = getMilestoneNote(itemKey, lv);

        levelsHtml += `
            <div style="display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 8px; margin-bottom: 6px;
                        background: ${isCurrent ? 'rgba(var(--color-success-rgb), 0.1)' : isNext ? 'rgba(var(--color-sepolia-rgb), 0.1)' : 'var(--bg-tertiary)'};
                        border: 1px solid ${isCurrent ? 'var(--color-success)' : isNext ? 'var(--color-sepolia)' : 'var(--border-color)'};
                        ${isLocked ? 'opacity: 0.5;' : ''}">
                <div style="width: 28px; text-align: center; font-weight: 700; font-size: 14px; color: ${isCurrent ? 'var(--color-success)' : isNext ? 'var(--color-sepolia)' : 'var(--text-muted)'};">
                    ${isCurrent ? '✓' : isNext ? '→' : lv}
                </div>
                <div style="flex: 1;">
                    <div style="font-weight: 600; font-size: 13px; color: var(--text-primary);">${stats.name || 'Lv' + lv}</div>
                    <div style="font-size: 11px; color: var(--text-secondary); margin-top: 2px;">${statsLine}</div>
                    ${milestone ? `<div style="font-size: 10px; color: var(--color-sepolia); margin-top: 2px; font-weight: 600;">${milestone}</div>` : ''}
                </div>
                <div style="text-align: right; font-size: 11px;">
                    ${stats.cost === 0 ? '<span style="color: var(--color-success);">Free</span>' :
                      `<div style="color: var(--text-primary); font-weight: 600;">${cost}</div>`}
                    ${buildDays ? `<div style="color: var(--text-muted);">${buildDays}d build</div>` : ''}
                </div>
            </div>`;
    }

    // Vehicle effective stats summary (speed + range breakdown)
    let vehicleSummaryHtml = '';
    if (category === 'vehicles' && currentLevel > 0) {
        const curStats = item.all_levels ? item.all_levels[currentLevel] : null;
        const lv1Stats = item.all_levels ? item.all_levels[1] : null;
        if (curStats) {
            const speed = curStats.expedition_speed_mult || 1.0;
            const baseSpeed = lv1Stats?.expedition_speed_mult || 1.0;
            const speedUp = speed - baseSpeed;
            let speedCalc = `${baseSpeed}× base`;
            if (speedUp > 0) speedCalc += ` + ${speedUp.toFixed(1)}× upgrades`;
            speedCalc += ` = <strong>${speed.toFixed(1)}×</strong>`;

            const maxRange = curStats.max_range_km || 0;
            const baseRange = lv1Stats?.max_range_km || maxRange;
            const rangeMult = DEPOT_DATA.rangeMult || 1.0;
            const discoveryCount = DEPOT_DATA.discoveryCount || 0;
            const effectiveRange = Math.round(maxRange * rangeMult);
            const rangeUp = maxRange - baseRange;
            let rangeCalc = `${baseRange.toLocaleString()} km base`;
            if (rangeUp > 0) rangeCalc += ` + ${rangeUp.toLocaleString()} km upgrades`;
            if (rangeMult !== 1.0) rangeCalc += ` × ${rangeMult}× exploration (${discoveryCount} discoveries)`;
            rangeCalc += ` = <strong>${effectiveRange.toLocaleString()} km</strong>`;

            vehicleSummaryHtml = `
            <div style="background: var(--bg-tertiary); border-radius: 8px; padding: 10px 12px; margin-bottom: 12px; font-size: 12px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                    <span style="color: var(--text-muted);">Travel Speed</span>
                    <span style="font-weight: 700;">${speed.toFixed(1)}× faster</span>
                </div>
                <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 8px; line-height: 1.5;">${speedCalc}</div>
                <div style="font-size: 10px; color: var(--text-muted); font-style: italic; margin-bottom: 10px; opacity: 0.7;">Logistics, terrain & trail bonuses apply per-trip</div>
                <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                    <span style="color: var(--text-muted);">Max Range</span>
                    <span style="font-weight: 700;">${effectiveRange.toLocaleString()} km</span>
                </div>
                <div style="font-size: 11px; color: var(--text-muted); line-height: 1.5;">${rangeCalc}</div>
            </div>`;
        }
    }

    const modalHtml = `
        <div style="max-width: 400px; margin: 0 auto;">
            ${item.image_url ? `<div style="text-align: center; margin-bottom: 12px;"><img src="${item.image_url}" alt="${item.name}" style="width: 80px; height: 80px; border-radius: 12px; object-fit: cover;"></div>` : ''}
            <div style="text-align: center; margin-bottom: 16px;">
                <div style="font-size: 18px; font-weight: 700;">${item.icon || ''} ${item.name || itemKey}</div>
                <div style="font-size: 13px; color: var(--text-secondary); margin-top: 4px;">${item.description || ''}</div>
                ${effectDesc ? `<div style="font-size: 11px; color: var(--text-muted); margin-top: 6px; padding: 6px 10px; background: var(--bg-tertiary); border-radius: 6px;">${effectDesc}</div>` : ''}
                <div style="font-size: 12px; margin-top: 6px; color: ${isMax ? 'var(--color-success)' : isBuilding ? 'var(--color-warning)' : 'var(--color-sepolia)'}; font-weight: 600;">
                    ${isMax ? '★ Max Level Reached' : isBuilding ? '🔧 Upgrading to Level ' + (buildStatus?.pending_level || currentLevel + 1) : currentLevel === 0 ? 'Not Yet Unlocked' : `Level ${currentLevel} → ${currentLevel + 1}`}
                </div>
            </div>
            ${vehicleSummaryHtml}

            <div style="font-size: 12px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">Upgrade Path</div>
            ${levelsHtml}

            ${!isMax ? `
            <div style="margin-top: 16px; padding: 12px; border-radius: 8px; background: ${isBuilding ? 'rgba(var(--color-warning-rgb), 0.08)' : canAfford ? 'rgba(var(--color-success-rgb), 0.08)' : 'rgba(var(--color-danger-rgb), 0.08)'}; border: 1px solid ${isBuilding ? 'rgba(var(--color-warning-rgb), 0.3)' : canAfford ? 'rgba(var(--color-success-rgb), 0.3)' : 'rgba(var(--color-danger-rgb), 0.3)'};">
                ${isBuilding ? `
                    <div style="text-align: center;">
                        <div style="font-size: 14px; font-weight: 600; color: var(--color-warning); margin-bottom: 4px;">🔧 Construction In Progress</div>
                        <div style="font-size: 12px; color: var(--text-secondary);">${formatBuildTimeRemaining(buildStatus?.seconds_remaining || 0)} remaining</div>
                        <div style="font-size: 11px; color: var(--text-muted); margin-top: 6px;">Upgrading to Level ${buildStatus?.pending_level || currentLevel + 1}</div>
                    </div>
                ` : canAfford ? `
                    <button onclick="performUpgrade('${category}', '${itemKey}')" class="btn btn-purple" style="width: 100%; padding: 12px; font-size: 14px; font-weight: 700;">
                        ${currentLevel === 0 ? 'Unlock' : 'Upgrade to'} ${item.next_level_name || 'Next Level'} (${nextCost.toLocaleString()} shards)
                    </button>
                ` : `
                    <div style="text-align: center;">
                        <div style="font-size: 14px; font-weight: 600; color: var(--color-danger); margin-bottom: 4px;">Not Affordable</div>
                        <div style="font-size: 12px; color: var(--text-secondary);">Need ${shortfall.toLocaleString()} more shards</div>
                        <div style="font-size: 11px; color: var(--text-muted); margin-top: 6px;">Current: ${CURRENT_BALANCE.toLocaleString()} / Required: ${nextCost.toLocaleString()}</div>
                    </div>
                `}
            </div>` : ''}
        </div>`;

    ItemDetailModal.show({
        name: `${item.name || itemKey} — ${isMax ? 'Maxed' : 'Upgrade Path'}`,
        description: modalHtml,
        htmlDescription: true
    });
}

// Convenience alias for expedition modal deep-link
function showVehicleUpgradeModal(vehicleType) {
    showUpgradeModal('vehicles', vehicleType);
}

// Auto-open upgrade modal from URL params (?upgrade=rover or ?upgrade=infrastructure:solar_array)
(function checkUpgradeParam() {
    const params = new URLSearchParams(window.location.search);
    const upgradeType = params.get('upgrade');
    if (upgradeType) {
        let category = null, itemKey = upgradeType;
        // Support explicit category:item format (e.g., infrastructure:solar_array)
        if (upgradeType.includes(':')) {
            [category, itemKey] = upgradeType.split(':');
            if (UPGRADE_DATA[category]?.[itemKey]) {
                setTimeout(() => showUpgradeModal(category, itemKey), 300);
            }
        } else {
            // Search all categories for this item
            for (const cat of Object.keys(UPGRADE_DATA)) {
                if (UPGRADE_DATA[cat][upgradeType]) {
                    setTimeout(() => showUpgradeModal(cat, upgradeType), 300);
                    break;
                }
            }
        }
        window.history.replaceState({}, '', '/depot');
    }
})();


// ============================================================================
// DEPOT SHOP - Purchases, modifications, infusions
// ============================================================================

document.addEventListener('DOMContentLoaded', function() {
    // depotData already loaded as DEPOT_DATA above
    const depot = {
        initialBalance: DEPOT_DATA.currentBalance,
        commanderUrl: DEPOT_DATA.currentCommanderUrl,
        commanderStats: DEPOT_DATA.currentStats,
        // Escalating costs from server (user-specific)
        rerollCost: DEPOT_DATA.pricing.reroll_cost,
        transmutationCost: DEPOT_DATA.pricing.transmutation_cost,
        modifyCost: DEPOT_DATA.pricing.modify_cost,
        // Atmospheric pricing (updated from API)
        atmosphericPricing: null
    };
    console.log('✅ Depot initialized, balance:', depot.initialBalance, 'rerollCost:', depot.rerollCost, 'transmutationCost:', depot.transmutationCost);

    function getBalance() { if (typeof window.getBalance === 'function') return window.getBalance(); const el = $('currentBalance'); if (el) { const b = parseFloat(el.textContent); if (!isNaN(b) && b >= 0) return b; } return depot.initialBalance; }
    function setBalance(b) {
        // Use global setBalance if available, otherwise update locally
        if (typeof window.setBalance === 'function') {
            window.setBalance(b);
        } else {
            const el = $('currentBalance'); if (el) el.textContent = b.toFixed(1);
            if (typeof window.currentBalance !== 'undefined') window.currentBalance = b;
        }
    }

    async function updateAtmosphericConditions() {
        try {
            const r = await fetch('/api/mars_conditions'); const data = await r.json(); if (!data.success) return;
            const { conditions, pricing } = data;
            // Update all condition displays
            const effEl = $('solarEfficiency'), statusEl = $('conditionStatus');
            const angleEl = $('solarAngle'), feeEl = $('feeMultiplier');
            if (effEl) effEl.textContent = conditions.efficiency;
            if (statusEl) statusEl.textContent = conditions.condition;
            if (angleEl) angleEl.textContent = conditions.solar_angle?.toFixed(1) || '--';
            if (feeEl) feeEl.textContent = conditions.fee_multiplier?.toFixed(2) || '--';
            // Store atmospheric pricing for modify/video (non-escalating)
            depot.atmosphericPricing = pricing;
            // Update modify/video cost displays (not reroll/transmutation - those are server-rendered)
            const modifyEl = $('modifyTotalCost');
            if (modifyEl && pricing.modify) modifyEl.textContent = pricing.modify.total_cost_display.toFixed(1);
            const videoEl = $('videoTotalCost');
            if (videoEl && pricing.video) videoEl.textContent = pricing.video.total_cost_display.toFixed(1);
        } catch (e) { console.error('Atmospheric update failed:', e); }
    }

    function showPreview(url, stats, type) {
        $('shopInterface').style.display = 'none';
        const img = $('previewImage'); if (img && url) img.src = url;
        const title = $('statsTitle'), msg = $('successMessage');
        if (type === 'reroll' && stats) { if (title) title.textContent = 'Updated Attributes'; if (msg) msg.textContent = 'Attributes rerolled. New stats shown.'; displayPreviewStats(stats); }
        else if (type === 'modification') { if (title) title.textContent = 'Captain Attributes'; if (msg) msg.textContent = 'Appearance modified. Attributes unchanged.'; displayPreviewStats(stats || depot.commanderStats); }
        const panel = $('commanderPreview'); panel.style.display = 'block'; panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function displayPreviewStats(stats) {
        if (!stats) return; let total = 0;
        ['leadership', 'strategy', 'exploration', 'logistics', 'charisma'].forEach(s => { const v = stats[s] || 0; const bar = $('preview_' + s + 'Bar'), val = $('preview_' + s + 'Value'); if (bar) bar.style.width = (v / 90 * 100) + '%'; if (val) val.textContent = v; total += v; });
        const t = $('preview_totalScore'); if (t) t.textContent = total;
    }

    window.resetDepotView = function() {
        $('commanderPreview').style.display = 'none'; $('shopInterface').style.display = 'grid';
        ['rerollButton', 'modifyButton', 'videoButton'].forEach(id => { const b = $(id); if (b) { b.disabled = false; b.style.opacity = '1'; b.style.cursor = 'pointer'; } });
        const p = $('modifyPrompt'); if (p) { p.value = ''; p.disabled = false; p.style.opacity = '1'; }
    };

    // Shard Infusion - stats can only improve or stay same, never decrease
    window.purchaseInfusion = async function() {
        const cost = depot.rerollCost;
        const bal = getBalance();
        const btn = $('rerollButton');

        if (bal < cost) {
            showToast(`Need ${cost.toLocaleString()} Sepolia Shards, have ${bal.toFixed(0)}`, 'warning', 'Insufficient');
            return;
        }

        disableBtn(btn, 'Channeling...');
        setBalance(bal - cost);
        showToast('Channeling Sepolia shards into your neural pathways...', 'info', 'Infusing', 5000);

        try {
            const data = await apiPost('/api/shop/reroll_stats');
            if (data.success) {
                const nextCost = data.next_infusion_cost || data.next_reroll_cost || (cost * 2);
                const gained = data.total_gained || 0;
                const improved = data.stats_improved || [];

                let message;
                if (gained > 0) {
                    const boosts = improved.map(s => s.charAt(0).toUpperCase() + s.slice(1) + ' +1').join(', ');
                    message = `The shards resonate! ${boosts}\n\nNext infusion: ${nextCost.toLocaleString()} Shards`;
                } else {
                    message = `The shards pulse but find no room to grow.\nYour potential remains intact.\n\nNext infusion: ${nextCost.toLocaleString()} Shards`;
                }
                showToast(message, gained > 0 ? 'success' : 'info', gained > 0 ? 'Enhanced!' : 'No Change', 8000);
                setTimeout(() => location.reload(), 3000);
            } else {
                showToast(sanitizeErrorMsg(data.error), 'error');
                setBalance(bal);
                setTimeout(() => location.reload(), 2000);
            }
        } catch {
            showToast('Network error.', 'error');
            setBalance(bal);
            setTimeout(() => location.reload(), 2000);
        }
    };

    // Legacy alias for backwards compatibility
    window.purchaseReroll = window.purchaseInfusion;

    // Purchase modification (uses atmospheric pricing)
    window.purchaseModification = async function() {
        const input = $('modifyPrompt'), prompt = input?.value.trim();
        if (!prompt) { showToast('Describe the changes.', 'warning', 'Missing Description'); return; }
        if (!depot.atmosphericPricing) { showToast('Wait for atmospheric update', 'warning'); return; }

        const cost = depot.atmosphericPricing.modify.total_cost_display;
        const bal = getBalance();
        const btn = $('modifyButton');

        if (bal < cost) {
            showToast(`Need ${cost.toFixed(1)} Sepolia Shards, have ${bal.toFixed(1)}`, 'warning', 'Insufficient');
            return;
        }

        input.disabled = true; input.style.opacity = '0.5';
        disableBtn(btn, '✓ Processing!');
        setBalance(bal - cost);
        showToast('Modification started! Your captain is being outfitted...', 'info', 'Processing', 8000);

        try {
            const data = await apiPost('/api/shop/modify_character', { prompt });
            if (data.success) {
                showToast('✓ Modification complete! Visit Crew tab in ~1 min to see your updated captain.', 'success', 'Complete!', 10000);
            } else {
                showToast(sanitizeErrorMsg(data.error), 'error');
                setBalance(bal);
                setTimeout(() => location.reload(), 2000);
            }
        } catch {
            showToast('Network error.', 'error');
            setBalance(bal);
            setTimeout(() => location.reload(), 2000);
        }
        setTimeout(() => { enableBtn(btn, 'Get'); input.disabled = false; input.style.opacity = '1'; input.value = ''; }, 3000);
    };

    // Purchase video (uses atmospheric pricing)
    window.purchaseVideo = async function() {
        if (!depot.atmosphericPricing) { showToast('Wait for atmospheric update', 'warning'); return; }

        const cost = depot.atmosphericPricing.video.total_cost_display;
        const bal = getBalance();
        const btn = $('videoButton');

        if (bal < cost) {
            showToast(`Need ${cost.toFixed(1)} Sepolia Shards, have ${bal.toFixed(1)}`, 'warning', 'Insufficient');
            return;
        }

        disableBtn(btn, '✓ Processing!');
        setBalance(bal - cost);
        showToast('Video generation started! This takes ~2 minutes.', 'info', 'Processing', 8000);

        try {
            const data = await apiPost('/api/shop/generate_video');
            if (data.success) {
                showToast('✓ Video generation queued! Visit Crew tab in ~2 min to watch.', 'success', 'Complete!', 10000);
            } else {
                showToast(sanitizeErrorMsg(data.error), 'error');
                setBalance(bal);
                setTimeout(() => location.reload(), 2000);
            }
        } catch {
            showToast('Network error.', 'error');
            setBalance(bal);
            setTimeout(() => location.reload(), 2000);
        }
        setTimeout(() => enableBtn(btn, 'Get'), 3000);
    };

    // Equipment/Upgrade purchases
    window.purchaseUpgrade = async function(itemId) {
        const btn = document.querySelector(`[data-item-id="${itemId}"] button`);
        if (!btn) return;

        const bal = getBalance();
        const costEl = document.querySelector(`[data-item-id="${itemId}"] .depot-card-price`);
        const cost = parseFloat(costEl?.textContent.replace(/,/g, '') || 0);

        if (bal < cost) {
            showToast(`Need ${cost.toLocaleString()} Sepolia Shards, have ${bal.toFixed(0)}`, 'warning', 'Insufficient');
            return;
        }

        disableBtn(btn, 'Processing...');
        setBalance(bal - cost);

        try {
            const data = await apiPost('/api/shop/purchase_upgrade', { item_id: itemId });

            if (data.success) {
                // Show build time in message
                let msg = `${data.item.name} purchased!`;
                if (data.build_time_seconds) {
                    const days = Math.round(data.build_time_seconds / 86400);
                    if (days >= 30) msg += ` Building: ${Math.round(days / 30)} month${days >= 60 ? 's' : ''}`;
                    else if (days >= 7) msg += ` Building: ${Math.round(days / 7)} week${days >= 14 ? 's' : ''}`;
                    else msg += ` Building: ${days} day${days > 1 ? 's' : ''}`;
                }
                showToast(msg, 'success', 'Construction Started!', 5000);
                setTimeout(() => location.reload(), 2000);
            } else {
                showToast(sanitizeErrorMsg(data.error), 'error');
                setBalance(bal);
                setTimeout(() => location.reload(), 2000);
            }
        } catch (e) {
            showToast('Network error.', 'error');
            setBalance(bal);
            setTimeout(() => location.reload(), 2000);
        }
    };

    // Photo upload for transmutation (uses escalating cost from depotData)
    const depotFileInput = $('depotFileInput');
    const depotCameraInput = $('depotCameraInput');

    async function handlePhotoUpload(file) {
        const cost = depot.transmutationCost;
        const bal = getBalance();

        if (bal < cost) {
            showToast(`Need ${cost.toLocaleString()} Sepolia Shards, have ${bal.toFixed(0)}`, 'warning', 'Insufficient');
            return;
        }

        setBalance(bal - cost);
        showToast('📤 Transmuting... Your captain will emerge in ~60-90 seconds.', 'info', 'Processing', 8000);

        const formData = new FormData();
        formData.append('image', file);
        formData.append('async', 'true');

        try {
            const r = await fetch('/api/upload_custom_commander', { method: 'POST', body: formData });
            const data = await r.json();
            if (data.success) {
                const nextCost = data.next_transmutation_cost || (cost * 2);
                showToast(`✓ Transmutation initiated! The shards are absorbing your image. Next transmutation: ${nextCost.toLocaleString()} Shards.\n\nCheck Crew in ~60-90 seconds.`, 'success', 'Complete!', 10000);
            } else {
                showToast(sanitizeErrorMsg(data.error) || 'Transmutation failed', 'error');
                setBalance(bal);
            }
        } catch {
            showToast('Network error.', 'error');
            setBalance(bal);
        }
    }

    if (depotFileInput) depotFileInput.addEventListener('change', e => { if (e.target.files?.[0]) handlePhotoUpload(e.target.files[0]); });
    if (depotCameraInput) depotCameraInput.addEventListener('change', e => { if (e.target.files?.[0]) handlePhotoUpload(e.target.files[0]); });

    updateAtmosphericConditions();
});
