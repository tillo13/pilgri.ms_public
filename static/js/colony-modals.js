/* Colony Page - Equipment, Infrastructure, Vehicle & Equipment Modals */

// Load Equipment
async function loadEquipment() {
    try {
        const response = await fetch('/api/user/equipment');
        const data = await response.json();
        const owned = data.owned || [];
        const eqEl = document.getElementById('equipmentCount');
        if (eqEl) eqEl.textContent = owned.length;

        if (!owned.length) {
            document.getElementById('equipmentGrid').innerHTML = `
                <div class="empty-state">
                    <img src="${UI_ICONS.empty_equipment}" alt="" class="empty-state-icon" style="width: 48px; height: 48px; opacity: 0.5;">
                    <div class="empty-state-text">No equipment yet</div>
                    <a href="/depot" class="btn btn-purple">Browse Shop</a>
                </div>`;
            return;
        }

        // Store equipment data for modal access
        window.equipmentData = owned;

        document.getElementById('equipmentGrid').innerHTML = owned.map((item, index) => {
            const isBuilding = item.status === 'building';
            const remaining = item.seconds_remaining || 0;
            let timeStr = '';
            if (isBuilding && remaining > 0) {
                const days = Math.floor(remaining / 86400);
                const hours = Math.floor((remaining % 86400) / 3600);
                if (days > 0) timeStr = `${days}d ${hours}h remaining`;
                else if (hours > 0) timeStr = `${hours}h remaining`;
                else timeStr = `${Math.floor(remaining / 60)}m remaining`;
            }
            return `
            <div class="equip-card ${isBuilding ? 'equip-building' : ''}" onclick="showEquipmentModal(window.equipmentData[${index}])" style="cursor: pointer;">
                ${item.image_url ?
                    `<img src="${item.image_url}" class="equip-card-icon w-full object-cover" style="height: 120px;${isBuilding ? ' opacity: 0.6;' : ''}" loading="lazy">` :
                    `<div class="equip-card-icon"><img src="${UI_ICONS.tab_tools}" alt="${item.name}" style="width: 40px; height: 40px;"></div>`}
                ${isBuilding ? `<div class="equip-building-badge">&#128736; Building</div>` : ''}
                <div class="equip-card-content">
                    <div class="equip-card-name">${item.name}</div>
                    <div class="equip-card-cat">${item.category}</div>
                    ${isBuilding ? `<div class="equip-build-time">&#9200; ${timeStr}</div>` : ''}
                    <div class="equip-card-desc">${item.description}</div>
                    ${!isBuilding && item.effects ? `
                        <div class="equip-card-effects">
                            <div class="equip-bonuses-label">BONUSES</div>
                            ${formatEffects(item.effects)}
                        </div>` : ''}
                    ${isBuilding ? `<div class="equip-card-effects" style="opacity: 0.5;"><div class="equip-bonuses-label">BONUSES (when complete)</div>${formatEffects(item.effects)}</div>` : ''}
                    <div class="equip-card-acquired">
                        ${isBuilding ? 'Under construction' : (item.purchased_at ? `Acquired ${new Date(item.purchased_at).toLocaleDateString()}` : 'Equipped')}
                    </div>
                </div>
            </div>`;
        }).join('');
    } catch (error) {
        console.error('Failed to load equipment:', error);
    }
}

// formatEffects() is now in discovery_utils.js (shared)

// Building countdown timers - shows decimal days ticking down (e.g., 17.3842d)
function initBuildCountdowns() {
    const buildingCards = document.querySelectorAll('.asset-card.building');
    if (!buildingCards.length) return;

    buildingCards.forEach(card => {
        card._remainingSeconds = parseInt(card.dataset.secondsRemaining) || 0;
    });

    // Update immediately, then every second
    function updateTimers() {
        buildingCards.forEach(card => {
            if (card._remainingSeconds <= 0) return;
            card._remainingSeconds--;
            const remaining = card._remainingSeconds;

            // Show as decimal days (ticks visibly every second with 5 decimals)
            const days = remaining / 86400;
            const timeStr = days.toFixed(5) + 'd';

            const timerEl = card.querySelector('.building-timer');
            if (timerEl) timerEl.textContent = timeStr;

            if (card._remainingSeconds <= 0) {
                showToast('Construction complete! Refresh to see your new asset.', 'success', 'Build Complete', 5000);
            }
        });
    }

    updateTimers(); // Initial update
    setInterval(updateTimers, 1000);
}

// Modal countdown interval tracker
let modalCountdownInterval = null;

// formatCountdown() is now in core.js (shared utility)

// Show detailed modal for infrastructure with LIVE countdown
function showInfrastructureModal(el) {
    if (modalCountdownInterval) { clearInterval(modalCountdownInterval); modalCountdownInterval = null; }
    const d = el.dataset;
    const stats = [];
    const isBuilding = d.status === 'building';
    const isUpgrading = d.isUpgrading === 'true';
    const level = parseInt(d.level) || 1;
    const maxLevel = parseInt(d.maxLevel) || 10;
    const canUpgrade = !isBuilding && !isUpgrading && level < maxLevel;

    // Status with level info
    let statusText = isBuilding ? 'Under Construction' : (isUpgrading ? 'Upgrading...' : 'Active & Operational');
    stats.push({ label: 'Status', value: statusText });
    stats.push({ label: 'Structure Type', value: (d.type || 'Structure').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) });
    stats.push({ label: 'Level', value: `Lv${level} / ${maxLevel}${d.levelName ? ' (' + d.levelName + ')' : ''}` });
    stats.push({ label: 'Category', value: (d.category || 'General').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) });
    if (isBuilding && el._remainingSeconds > 0) {
        stats.push({ label: '\u2500\u2500\u2500 CONSTRUCTION \u2500\u2500\u2500', value: '' });
        stats.push({ label: 'Time Remaining', value: `<span id="modalCountdown">${formatCountdown(el._remainingSeconds)}</span>` });
        if (d.ready) stats.push({ label: 'Ready On', value: d.ready });
        const buildTimeTotal = parseInt(d.buildTimeTotal) || 0;
        if (buildTimeTotal > 0) stats.push({ label: 'Total Build Time', value: formatCountdown(buildTimeTotal) });
    }
    stats.push({ label: '\u2500\u2500\u2500 OUTPUT \u2500\u2500\u2500', value: '' });
    if (d.generates === 'sepolia' && parseFloat(d.rate) > 0) {
        stats.push({ label: isBuilding ? 'Will Generate' : 'Generation Rate', value: parseFloat(d.rate).toFixed(1) + ' shards/hr' });
        const dailyRate = parseFloat(d.rate) * 24;
        stats.push({ label: isBuilding ? 'Daily (projected)' : 'Daily Rate', value: dailyRate.toFixed(0) + ' shards/day' });
        if (!isBuilding && parseFloat(d.totalGenerated) > 0) stats.push({ label: 'Total Generated', value: parseFloat(d.totalGenerated).toLocaleString() + ' shards' });
    } else {
        stats.push({ label: 'Resource Output', value: 'None (utility structure)' });
    }
    if (d.effect) {
        stats.push({ label: '\u2500\u2500\u2500 EFFECTS \u2500\u2500\u2500', value: '' });
        let effectStr = d.effect.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
        if (d.effectValue) {
            const val = parseFloat(d.effectValue);
            if (d.effect.includes('mult')) effectStr = '+' + ((val - 1) * 100).toFixed(0) + '% ' + d.effect.replace('_mult', '').replace(/_/g, ' ');
            else if (d.effect.includes('bonus')) effectStr = '+' + (val * 100).toFixed(0) + '% ' + d.effect.replace('_bonus', '').replace(/_/g, ' ');
        }
        stats.push({ label: isBuilding ? 'Effect (when complete)' : 'Active Effect', value: effectStr });
        if (d.effect === 'night_generation') stats.push({ label: 'Special', value: 'Generates Sepolia shards during Martian night' });
        else if (d.effect === 'discovery_value_mult') stats.push({ label: 'Special', value: 'Increases value of all discoveries' });
        else if (d.effect === 'discovery_chance_bonus') stats.push({ label: 'Special', value: 'More discoveries per expedition' });
        else if (d.effect === 'fuel_cost_mult') stats.push({ label: 'Special', value: 'Reduces expedition costs' });
        else if (d.effect === 'research_enabled') stats.push({ label: 'Special', value: 'Unlocks Xenobiology experiments' });
    }
    if (d.requirements) {
        stats.push({ label: '\u2500\u2500\u2500 REQUIREMENTS \u2500\u2500\u2500', value: '' });
        stats.push({ label: 'Prerequisites', value: d.requirements || 'None' });
    }
    stats.push({ label: '\u2500\u2500\u2500 ACQUISITION \u2500\u2500\u2500', value: '' });
    if (parseInt(d.cost) > 0) stats.push({ label: 'Purchase Cost', value: parseInt(d.cost).toLocaleString() + ' shards' });
    if (d.created && d.created !== 'Unknown') stats.push({ label: 'Construction Started', value: d.created });
    if (!isBuilding && d.completed) stats.push({ label: 'Completed', value: d.completed });
    if (!isBuilding) {
        if (d.timeOwned) stats.push({ label: 'Time Owned', value: d.timeOwned });
        if (d.timeActive) stats.push({ label: 'Time Active', value: d.timeActive });
    }
    if (d.txHash) {
        stats.push({ label: '\u2500\u2500\u2500 BLOCKCHAIN \u2500\u2500\u2500', value: '' });
        stats.push({ label: 'Transaction', value: d.txHash.substring(0, 12) + '...' });
    }
    // Upgrade info section
    if (canUpgrade && d.nextLevelCost) {
        stats.push({ label: '\u2500\u2500\u2500 NEXT LEVEL \u2500\u2500\u2500', value: '' });
        const nextCost = parseInt(d.nextLevelCost) || 0;
        stats.push({ label: 'Upgrade To', value: d.nextLevelName || `Level ${level + 1}` });
        stats.push({ label: 'Cost', value: nextCost.toLocaleString() + ' shards' });
        const buildDays = parseFloat(d.nextBuildTimeDays) || 0;
        if (buildDays > 0) {
            stats.push({ label: 'Build Time', value: buildDays + ' days' });
        }
    } else if (level >= maxLevel) {
        stats.push({ label: '\u2500\u2500\u2500 LEVEL \u2500\u2500\u2500', value: '' });
        stats.push({ label: 'Status', value: 'Maximum Level Reached' });
    } else if (isUpgrading) {
        stats.push({ label: '\u2500\u2500\u2500 UPGRADE \u2500\u2500\u2500', value: '' });
        try {
            const upgradeStatus = JSON.parse(d.upgradeStatus || '{}');
            if (upgradeStatus.ready_at) {
                const readyDate = new Date(upgradeStatus.ready_at);
                stats.push({ label: 'Upgrading To', value: `Level ${upgradeStatus.pending_level || level + 1}` });
                stats.push({ label: 'Ready On', value: readyDate.toLocaleString() });
                if (upgradeStatus.seconds_remaining > 0) {
                    stats.push({ label: 'Time Remaining', value: formatCountdown(upgradeStatus.seconds_remaining) });
                }
            }
        } catch(e) {}
    }

    // Link to depot for upgrades (don't do inline upgrades here)
    let actionButton = null;
    if (canUpgrade) {
        actionButton = {
            text: 'Upgrade in Depot',
            onclick: () => { ItemDetailModal.hide(); window.location.href = '/depot?tab=infrastructure'; },
            class: 'btn-purple'
        };
    }

    ItemDetailModal.show({
        name: d.name, image: d.image || null,
        category: (isBuilding ? '&#128736; BUILDING' : (isUpgrading ? '&#9889; UPGRADING' : '&#9889; ACTIVE')) + ' - ' + (d.category || 'INFRASTRUCTURE').toUpperCase(),
        description: d.description || 'A vital structure in your Mars colony.', stats: stats,
        action: actionButton
    });
    if (isBuilding && el._remainingSeconds > 0) {
        modalCountdownInterval = setInterval(() => {
            if (el._remainingSeconds > 0) {
                const countdownEl = document.getElementById('modalCountdown');
                if (countdownEl) countdownEl.textContent = formatCountdown(el._remainingSeconds);
                else { clearInterval(modalCountdownInterval); modalCountdownInterval = null; }
            } else { clearInterval(modalCountdownInterval); modalCountdownInterval = null; }
        }, 1000);
    }
}

// Show detailed modal for building equipment with LIVE countdown
function showBuildingEquipmentModal(el) {
    if (modalCountdownInterval) { clearInterval(modalCountdownInterval); modalCountdownInterval = null; }
    const d = el.dataset;
    const stats = [];
    stats.push({ label: 'Status', value: 'Under Construction' });
    stats.push({ label: 'Category', value: (d.category || 'Equipment').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) });
    const maxOwned = parseInt(d.maxOwned) || 1;
    if (maxOwned > 1) stats.push({ label: 'Max Allowed', value: maxOwned + ' units' });
    stats.push({ label: '\u2500\u2500\u2500 CONSTRUCTION \u2500\u2500\u2500', value: '' });
    if (el._remainingSeconds > 0) stats.push({ label: 'Time Remaining', value: `<span id="modalCountdown">${formatCountdown(el._remainingSeconds)}</span>` });
    if (d.readyAt) stats.push({ label: 'Ready On', value: d.readyAt });
    const buildTimeTotal = parseInt(d.buildTimeTotal) || 0;
    if (buildTimeTotal > 0) stats.push({ label: 'Total Build Time', value: formatCountdown(buildTimeTotal) });
    const discoveryBonus = parseFloat(d.discoveryBonus) || 0;
    const rareBonus = parseFloat(d.rareBonus) || 0;
    const legendaryBonus = parseFloat(d.legendaryBonus) || 0;
    const speedMult = parseFloat(d.speedMult) || 0;
    const cargoSlots = parseInt(d.cargoSlots) || 0;
    const fuelMult = parseFloat(d.fuelMult) || 0;
    const bonusStats = [];
    if (discoveryBonus > 0) bonusStats.push({ label: 'Discovery Rate', value: '+' + (discoveryBonus * 100).toFixed(0) + '%' });
    if (rareBonus > 0) bonusStats.push({ label: 'Rare Find Chance', value: '+' + (rareBonus * 100).toFixed(0) + '%' });
    if (legendaryBonus > 0) bonusStats.push({ label: 'Legendary Chance', value: '+' + (legendaryBonus * 100).toFixed(0) + '%' });
    if (speedMult > 0 && speedMult !== 1.0) {
        const speedPct = speedMult > 1 ? '+' + ((speedMult - 1) * 100).toFixed(0) : '-' + ((1 - speedMult) * 100).toFixed(0);
        bonusStats.push({ label: 'Expedition Speed', value: speedPct + '%' });
    }
    if (cargoSlots > 0) bonusStats.push({ label: 'Extra Cargo', value: '+' + cargoSlots + ' slots' });
    if (fuelMult > 0 && fuelMult < 1.0) bonusStats.push({ label: 'Cost Efficiency', value: '-' + ((1 - fuelMult) * 100).toFixed(0) + '% expedition cost' });
    if (bonusStats.length > 0) {
        stats.push({ label: '\u2500\u2500\u2500 BONUSES (when complete) \u2500\u2500\u2500', value: '' });
        bonusStats.forEach(b => stats.push(b));
    }
    if (d.requirements) {
        stats.push({ label: '\u2500\u2500\u2500 REQUIREMENTS \u2500\u2500\u2500', value: '' });
        stats.push({ label: 'Prerequisites', value: d.requirements });
    }
    stats.push({ label: '\u2500\u2500\u2500 ACQUISITION \u2500\u2500\u2500', value: '' });
    if (parseInt(d.cost) > 0) stats.push({ label: 'Purchase Cost', value: parseInt(d.cost).toLocaleString() + ' shards' });
    if (d.purchasedAt) stats.push({ label: 'Purchased', value: d.purchasedAt });
    if (d.txHash) stats.push({ label: 'Transaction', value: d.txHash.substring(0, 12) + '...' });
    ItemDetailModal.show({
        name: d.name, image: d.image || null,
        category: '&#128736; BUILDING - ' + (d.category || 'EQUIPMENT').toUpperCase(),
        description: d.description || 'Equipment under construction.', stats: stats
    });
    if (el._remainingSeconds > 0) {
        modalCountdownInterval = setInterval(() => {
            if (el._remainingSeconds > 0) {
                const countdownEl = document.getElementById('modalCountdown');
                if (countdownEl) countdownEl.textContent = formatCountdown(el._remainingSeconds);
                else { clearInterval(modalCountdownInterval); modalCountdownInterval = null; }
            } else { clearInterval(modalCountdownInterval); modalCountdownInterval = null; }
        }, 1000);
    }
}

// Show detailed modal for vehicles
function showVehicleModal(el) {
    const d = el.dataset;
    const stats = [];
    const level = parseInt(d.level) || 1;
    const maxLevel = parseInt(d.maxLevel) || 4;
    const isOnExpedition = d.onExpedition === 'true';
    if (isOnExpedition) {
        const now = new Date();
        const arrives = d.expeditionArrives ? new Date(d.expeditionArrives) : null;
        const returns = d.expeditionReturnsIso ? new Date(d.expeditionReturnsIso) : null;
        const phase = (arrives && now >= arrives) ? 'Returning' : 'En Route';
        stats.push({ label: '\u2500\u2500\u2500 ACTIVE TRIP \u2500\u2500\u2500', value: '' });
        stats.push({ label: 'Status', value: phase + (d.expeditionDestination ? ' \u2192 ' + d.expeditionDestination : '') });
        stats.push({ label: 'Distance', value: (d.expeditionDistance || '?') + ' km' });
        const target = returns || arrives;
        if (target && target > now) {
            const rem = target - now;
            const days = Math.floor(rem / 86400000);
            const hrs = Math.floor((rem % 86400000) / 3600000);
            const mins = Math.floor((rem % 3600000) / 60000);
            let timeStr = '';
            if (days > 0) timeStr += days + 'd ';
            timeStr += hrs + 'h ' + mins + 'm';
            stats.push({ label: phase === 'Returning' ? 'Returns In' : 'ETA', value: timeStr });
        }
        if (d.expeditionReturns) stats.push({ label: 'Returns On', value: d.expeditionReturns });
        stats.push({ label: '\u2500\u2500\u2500 VEHICLE STATS \u2500\u2500\u2500', value: '' });
    } else {
        stats.push({ label: 'Status', value: 'Available' });
    }
    stats.push({ label: 'Current Level', value: `${level} / ${maxLevel}` });
    stats.push({ label: 'Vehicle Type', value: (d.type || 'Vehicle').replace('_', ' ').replace(/\b\w/g, c => c.toUpperCase()) });
    stats.push({ label: 'Cargo Capacity', value: (d.cargo || 0) + ' items per expedition' });
    const speedMult = parseFloat(d.speedMult) || 1.0;
    const baseSpeed = parseFloat(d.baseSpeed) || 1.0;
    const speedFromUpgrades = speedMult - baseSpeed;
    let speedCalc = baseSpeed + '× base';
    if (speedFromUpgrades > 0) speedCalc += ' + ' + speedFromUpgrades.toFixed(1) + '× upgrades';
    speedCalc += ' = ' + speedMult.toFixed(1) + '×';
    stats.push({ label: 'Travel Speed', value: speedMult.toFixed(1) + 'x' + (speedMult > 1 ? ' (faster)' : ''), detail: speedCalc, detailNote: 'Logistics, terrain & trail bonuses apply per-trip' });
    // Range breakdown
    const maxRange = parseInt(d.maxRange) || 0;
    const baseRange = parseInt(d.baseRange) || 0;
    const effectiveRange = parseInt(d.effectiveRange) || 0;
    const rangeMult = parseFloat(d.rangeMult) || 1.0;
    const discoveryCount = parseInt(d.discoveryCount) || 0;
    const rangeUpgrade = maxRange - baseRange;
    let rangeCalc = baseRange.toLocaleString() + ' km base';
    if (rangeUpgrade > 0) rangeCalc += ' + ' + rangeUpgrade.toLocaleString() + ' km upgrades';
    if (rangeMult !== 1.0) rangeCalc += ' × ' + rangeMult + '× exploration (' + discoveryCount + ' discoveries)';
    rangeCalc += ' = ' + effectiveRange.toLocaleString() + ' km';
    stats.push({ label: 'Max Range', value: effectiveRange.toLocaleString() + ' km', detail: rangeCalc });
    const fuelMult = parseFloat(d.fuelMult) || 1.0;
    if (fuelMult < 1.0) stats.push({ label: 'Cost Efficiency', value: '-' + ((1 - fuelMult) * 100).toFixed(0) + '% expedition cost' });
    else if (fuelMult > 1.0) stats.push({ label: 'Expedition Cost', value: '+' + ((fuelMult - 1) * 100).toFixed(0) + '% (less efficient)' });
    else stats.push({ label: 'Cost Efficiency', value: 'Standard' });
    const discoveryBonus = parseFloat(d.discoveryBonus) || 0;
    const rareBonus = parseFloat(d.rareBonus) || 0;
    const legendaryBonus = parseFloat(d.legendaryBonus) || 0;
    stats.push({ label: 'Discovery Rate', value: discoveryBonus === 0 ? 'Normal' : (discoveryBonus > 0 ? '+' : '') + (discoveryBonus * 100).toFixed(0) + '%' });
    stats.push({ label: 'Rare Find Chance', value: rareBonus === 0 ? 'Normal' : (rareBonus > 0 ? '+' : '') + (rareBonus * 100).toFixed(0) + '%' });
    if (legendaryBonus === -1) stats.push({ label: 'Legendary Chance', value: 'Cannot find legendary' });
    else if (legendaryBonus < 0) stats.push({ label: 'Legendary Chance', value: (legendaryBonus * 100).toFixed(0) + '%' });
    else if (legendaryBonus > 0) stats.push({ label: 'Legendary Chance', value: '+' + (legendaryBonus * 100).toFixed(0) + '%' });
    else stats.push({ label: 'Legendary Chance', value: 'Normal' });
    const costPaid = parseInt(d.costPaid) || 0;
    if (costPaid > 0) stats.push({ label: 'Cost Paid', value: costPaid.toLocaleString() + ' shards' });
    else stats.push({ label: 'Cost Paid', value: 'Starting equipment (free)' });
    if (d.acquired) stats.push({ label: 'Acquired', value: d.acquired });
    if (d.nextLevel && d.nextLevel !== 'None') {
        const nextCost = parseInt(d.nextLevelCost) || 0;
        const nextCargo = parseInt(d.nextLevelCargo) || 0;
        const nextSpeed = parseFloat(d.nextLevelSpeed) || 0;
        const nextBuildDays = parseInt(d.nextLevelBuildDays) || 0;
        stats.push({ label: '\u2500\u2500\u2500 NEXT LEVEL \u2500\u2500\u2500', value: d.nextLevelName || `Level ${d.nextLevel}` });
        stats.push({ label: 'Upgrade Cost', value: nextCost.toLocaleString() + ' shards' });
        if (nextBuildDays > 0) stats.push({ label: 'Build Time', value: nextBuildDays + ' day' + (nextBuildDays !== 1 ? 's' : '') });
        stats.push({ label: 'New Cargo', value: nextCargo + ' items' });
        stats.push({ label: 'New Speed', value: nextSpeed.toFixed(2) + 'x' });
    } else {
        stats.push({ label: '\u2500\u2500\u2500 MAX LEVEL \u2500\u2500\u2500', value: 'Fully upgraded!' });
    }
    if (d.txHash) stats.push({ label: 'Blockchain TX', value: d.txHash.substring(0, 10) + '...' });
    const action = isOnExpedition
        ? { label: 'Track on Map', className: 'btn-purple', onClick: () => { ItemDetailModal.hide(); window.location.href = '/expeditions'; } }
        : { label: 'Upgrade at Depot', className: 'btn-purple', onClick: () => { ItemDetailModal.hide(); window.location.href = '/depot'; } };
    const category = isOnExpedition
        ? '&#128663; VEHICLE - ON EXPEDITION'
        : '&#128663; VEHICLE - LEVEL ' + d.level + ' / ' + maxLevel;
    ItemDetailModal.show({
        name: d.name, image: d.image || null, category: category,
        description: d.description || 'A capable exploration vehicle for Mars expeditions.',
        stats: stats, action: action
    });
}

// Show detailed modal for equipment (from dynamically loaded data)
function showEquipmentModal(item) {
    const stats = [];
    stats.push({ label: 'Status', value: item.status === 'building' ? 'Under Construction' : 'Equipped & Active' });
    stats.push({ label: 'Category', value: (item.category || 'Equipment').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) });
    if (item.status === 'building') {
        stats.push({ label: '\u2500\u2500\u2500 CONSTRUCTION \u2500\u2500\u2500', value: '' });
        if (item.seconds_remaining > 0) stats.push({ label: 'Time Remaining', value: formatCountdown(item.seconds_remaining) });
        if (item.ready_at) stats.push({ label: 'Ready On', value: new Date(item.ready_at).toLocaleString() });
    }
    const bonusStats = [];
    if (item.effects && Object.keys(item.effects).length > 0) {
        Object.entries(item.effects).forEach(([key, value]) => {
            let label, displayValue;
            switch(key) {
                case 'expedition_speed_mult': label = 'Expedition Speed'; displayValue = value >= 1 ? '+' + ((value - 1) * 100).toFixed(0) + '%' : '-' + ((1 - value) * 100).toFixed(0) + '%'; break;
                case 'discovery_chance_mult': label = 'Discovery Rate'; displayValue = '+' + ((value - 1) * 100).toFixed(0) + '%'; break;
                case 'discovery_chance_bonus': label = 'Discovery Rate'; displayValue = '+' + (value * 100).toFixed(0) + '%'; break;
                case 'rare_find_mult': label = 'Rare Find Chance'; displayValue = '+' + ((value - 1) * 100).toFixed(0) + '%'; break;
                case 'rare_chance_bonus': label = 'Rare Find Chance'; displayValue = '+' + (value * 100).toFixed(0) + '%'; break;
                case 'legendary_chance_bonus': label = 'Legendary Chance'; displayValue = '+' + (value * 100).toFixed(0) + '%'; break;
                case 'cargo_slots': label = 'Extra Cargo'; displayValue = '+' + value + ' slots'; break;
                case 'fuel_cost_mult': label = 'Cost Efficiency'; displayValue = value < 1 ? '-' + ((1 - value) * 100).toFixed(0) + '% expedition cost' : '+' + ((value - 1) * 100).toFixed(0) + '% expedition cost'; break;
                case 'life_support_cost_mult': label = 'Life Support'; displayValue = value < 1 ? '-' + ((1 - value) * 100).toFixed(0) + '% cost' : 'Standard'; break;
                case 'passive_income_mult': label = 'Passive Income'; displayValue = '+' + ((value - 1) * 100).toFixed(0) + '%'; break;
                case 'passive_income_base': label = 'Passive Income'; displayValue = '+' + value + ' shards/hr'; break;
                default: label = key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()); displayValue = String(value);
            }
            bonusStats.push({ label: label, value: displayValue });
        });
    }
    if (bonusStats.length > 0) {
        stats.push({ label: item.status === 'building' ? '\u2500\u2500\u2500 BONUSES (when complete) \u2500\u2500\u2500' : '\u2500\u2500\u2500 ACTIVE BONUSES \u2500\u2500\u2500', value: '' });
        bonusStats.forEach(b => stats.push(b));
    }
    stats.push({ label: '\u2500\u2500\u2500 ACQUISITION \u2500\u2500\u2500', value: '' });
    if (item.cost) stats.push({ label: 'Purchase Cost', value: parseInt(item.cost).toLocaleString() + ' shards' });
    if (item.purchased_at) {
        const purchaseDate = new Date(item.purchased_at);
        stats.push({ label: 'Acquired', value: purchaseDate.toLocaleDateString() + ' at ' + purchaseDate.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) });
        const now = new Date();
        const diffMs = now - purchaseDate;
        const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
        const diffHours = Math.floor((diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
        if (diffDays > 0) stats.push({ label: 'Time Owned', value: diffDays + ' day' + (diffDays !== 1 ? 's' : '') + ' ' + diffHours + 'h' });
        else stats.push({ label: 'Time Owned', value: diffHours + ' hour' + (diffHours !== 1 ? 's' : '') });
    } else {
        stats.push({ label: 'Acquired', value: 'N/A' });
    }
    if (item.tx_hash) {
        stats.push({ label: '\u2500\u2500\u2500 BLOCKCHAIN \u2500\u2500\u2500', value: '' });
        stats.push({ label: 'Transaction', value: item.tx_hash.substring(0, 12) + '...' });
    }
    ItemDetailModal.show({
        name: item.name, image: item.image_url || null,
        category: '&#128295; EQUIPMENT - ' + (item.category || 'GEAR').toUpperCase(),
        description: item.description || 'Specialized equipment for Mars operations.', stats: stats
    });
}

// Upgrade infrastructure building to next level
async function upgradeInfrastructure(buildingType) {
    if (!buildingType) {
        showToast('Invalid building type', 'error');
        return;
    }

    // Close current modal
    MarsModal.close();

    // Show loading state
    showToast('Starting infrastructure upgrade...', 'info');

    try {
        const response = await fetch('/api/upgrade', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                category: 'infrastructure',
                item_key: buildingType
            })
        });

        const result = await response.json();

        if (result.success) {
            const levelName = result.level_name || `Level ${result.new_level}`;
            if (result.is_building) {
                showToast(`Upgrade started! ${result.item_name} upgrading to ${levelName}`, 'success');
            } else {
                showToast(`${result.item_name} upgraded to ${levelName}!`, 'success');
            }
            // Reload page to show updated state
            setTimeout(() => window.location.reload(), 1500);
        } else {
            showToast(result.error || 'Upgrade failed', 'error');
        }
    } catch (err) {
        console.error('Upgrade error:', err);
        showToast('Network error - please try again', 'error');
    }
}
