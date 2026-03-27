// ============================================================================
// CREW-MISSIONS.JS - Trail Missions, Bonuses, Status, Notifications
// ============================================================================

/* ─── Crew Missions ─── */
// Crew Missions JavaScript
let crewMissionStatus = null;
let nearbyTrails = [];
let pendingMissionMember = null;

// Trail bonuses (scanner + consumables)
let trailConsumables = [];
let trailScannerBonus = { bonus_percent: 0, scanner_name: null };
let selectedConsumableId = null;

// Duration tiers based on total bonus (matches config.py TRAIL_BONUS_DURATIONS)
const BONUS_DURATION_TIERS = [
    { bonus: 15, duration: 3 },   // +15%+ → 3 min
    { bonus: 12, duration: 4 },   // +12-14% → 4 min
    { bonus: 10, duration: 5 },   // +10-11% → 5 min
    { bonus: 8, duration: 6 },    // +8-9% → 6 min
    { bonus: 5, duration: 8 },    // +5-7% → 8 min
    { bonus: 2, duration: 12 },   // +2-4% → 12 min (scanner only)
    { bonus: 0, duration: 15 },   // 0% → 15 min (no bonus)
];

function getDurationFromBonus(totalBonusPercent) {
    for (const tier of BONUS_DURATION_TIERS) {
        if (totalBonusPercent >= tier.bonus) return tier.duration;
    }
    return 15;
}

async function loadTrailBonuses() {
    try {
        const res = await fetch('/api/trail/consumables');
        const data = await res.json();
        if (data.success) {
            trailScannerBonus = data.scanner || { bonus_percent: 0 };
            trailConsumables = data.consumables || [];
            updateTrailBonusUI();
        }
    } catch (e) {
        console.error('Failed to load trail bonuses:', e);
    }
}

function updateTrailBonusUI() {
    // Scanner display (always shown, even if 0%)
    const scannerDisplay = document.getElementById('scanner-bonus-display');
    const scannerName = document.getElementById('scanner-name-display');
    if (scannerDisplay) scannerDisplay.textContent = `+${trailScannerBonus.bonus_percent || 0}%`;
    if (scannerName) scannerName.textContent = trailScannerBonus.scanner_name ? `(${trailScannerBonus.scanner_name})` : '(none)';

    // Populate consumable dropdown (grouped with counts)
    const select = document.getElementById('consumable-select');
    if (select) {
        select.innerHTML = '<option value="">None (+0%)</option>';
        trailConsumables.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.id;
            const countLabel = c.count > 1 ? ` ×${c.count}` : '';
            opt.textContent = `${c.item_name} (+${c.trail_bonus_percent}%)${countLabel}`;
            select.appendChild(opt);
        });
    }

    // Reset selection and update total
    selectedConsumableId = null;
    updateTotalBonus();
}

function onConsumableChange(value) {
    selectedConsumableId = value || null;
    const warning = document.getElementById('consumable-warning');
    if (warning) warning.style.display = value ? 'block' : 'none';
    updateTotalBonus();
}

function updateTotalBonus() {
    // Calculate total bonus (scanner + consumable)
    // Note: Crew stat bonus is added server-side, but we show scanner+consumable here
    let equipmentBonus = trailScannerBonus.bonus_percent || 0;
    let consumableBonus = 0;
    if (selectedConsumableId) {
        const c = trailConsumables.find(x => x.id == selectedConsumableId);
        if (c) consumableBonus = c.trail_bonus_percent;
    }
    const total = equipmentBonus + consumableBonus;
    const display = document.getElementById('total-bonus-display');
    if (display) display.textContent = `+${total}%`;

    // Update trip duration display (based on total bonus)
    // Crew stats also affect this, so we show "~X min" as estimate
    const duration = getDurationFromBonus(total);
    const durationDisplay = document.getElementById('trip-duration-display');
    if (durationDisplay) {
        // Show as estimate since crew stats also affect it
        durationDisplay.textContent = `~${duration} min`;
        // Color code: faster = greener
        if (duration <= 5) durationDisplay.style.color = 'var(--color-success)';
        else if (duration <= 10) durationDisplay.style.color = 'var(--color-warning)';
        else durationDisplay.style.color = 'var(--text-secondary)';
    }
}

async function loadCrewMissions() {
    try {
        // Load mission status
        const statusRes = await fetch('/api/crew/mission/status');
        const statusData = await statusRes.json();
        if (statusData.success) {
            crewMissionStatus = statusData;

            // Auto-claim any completed missions (no click required!)
            for (const member of ['captain', 'scientist', 'aria']) {
                const status = statusData[member];
                if (status?.complete) {
                    await autoClaimTrailMission(member);
                }
            }

            updateMissionUI();
        }

        // Load nearby trails
        const trailsRes = await fetch('/api/crew/mission/nearby');
        const trailsData = await trailsRes.json();
        if (trailsData.success) {
            nearbyTrails = trailsData.trails;
            // Store base coords from response and re-center map if needed
            if (trailsData.base_coords) {
                window.baseCoords = trailsData.base_coords;
                if (crewTrailMap) {
                    crewTrailMap.setView([trailsData.base_coords.latitude, trailsData.base_coords.longitude], crewTrailMap.getZoom());
                }
            }
            // Update map markers, top trails, and crew contributions
            updateCrewTrailMapMarkers();
            updateTopTrails();
            updateCrewTrailContributions();
        }
    } catch (e) {
        console.error('Failed to load crew missions:', e);
    }
}

// Auto-claim completed trail mission (no user interaction needed)
async function autoClaimTrailMission(member) {
    const memberName = member === 'captain' ? 'Captain' : member === 'scientist' ? 'Scientist' : 'ARIA';

    try {
        const res = await fetch('/api/trail/complete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ worker_type: member })
        });
        const data = await res.json();

        if (data.success) {
            let msg = `${memberName} returned! +${(data.km_added || 0).toFixed(3)} km to ${data.destination}`;
            if (data.xp_gained) msg += `, +${data.xp_gained} XP`;
            if (data.trail) msg += ` (${data.trail.percent_complete?.toFixed(1) || 0}% complete)`;
            showToast?.(msg, 'success');

            // Update local status to reflect claim
            if (crewMissionStatus?.[member]) {
                crewMissionStatus[member] = { busy: false, complete: false };
            }
        }
    } catch (e) {
        console.warn(`Failed to auto-claim ${member} mission:`, e);
    }
}

// ARIA skills removed - she just has free daily trail help now

function updateMissionUI() {
    if (!crewMissionStatus) return;

    const cap = crewMissionStatus.captain;
    const sci = crewMissionStatus.scientist;
    const aria = crewMissionStatus.aria;

    // Update crew status badges (compact row)
    updateCrewStatusBadges(cap, sci, aria);

    // XP bars
    updateXPBars(cap?.xp || 0, sci?.xp || 0);

    // Update modal stat displays
    updateModalStatDisplay();
}

function updateModalStatDisplay() {
    const cap = crewMissionStatus?.captain;
    const sci = crewMissionStatus?.scientist;
    const aria = crewMissionStatus?.aria;

    // Captain stats
    if (cap) {
        const capXp = document.getElementById('captain-xp-modal');
        const capBonus = document.getElementById('captain-bonus');
        if (capXp) capXp.textContent = cap.stat_value || 0;
        if (capBonus) {
            const bonus = Math.round((cap.stat_multiplier - 1) * 100);
            capBonus.textContent = `+${bonus}%`;
        }
    }

    // Scientist stats
    if (sci) {
        const sciXp = document.getElementById('scientist-xp-modal');
        const sciBonus = document.getElementById('scientist-bonus');
        if (sciXp) sciXp.textContent = sci.stat_value || 0;
        if (sciBonus) {
            const bonus = Math.round((sci.stat_multiplier - 1) * 100);
            sciBonus.textContent = `+${bonus}%`;
        }
    }

    // ARIA stats
    if (aria) {
        const ariaXp = document.getElementById('aria-xp-modal');
        const ariaBonus = document.getElementById('aria-bonus');
        if (ariaXp) ariaXp.textContent = aria.stat_value || 1;
        if (ariaBonus) {
            const bonus = Math.round((aria.stat_multiplier - 1) * 100);
            ariaBonus.textContent = `+${bonus}%`;
        }
    }
}

// Update the compact crew status badges
function updateCrewStatusBadges(cap, sci, aria) {
    // Captain badge
    const capBadge = document.getElementById('captain-status-badge');
    if (capBadge) {
        if (cap?.busy) {
            capBadge.innerHTML = `<span style="color: var(--color-warning);">Building</span>`;
        } else if (cap?.complete) {
            capBadge.innerHTML = `<span style="color: var(--color-success);">✓ Claim!</span>`;
        } else {
            capBadge.innerHTML = `<span style="color: var(--color-success);">Ready</span>`;
        }
    }

    // Scientist badge
    const sciBadge = document.getElementById('scientist-status-badge');
    if (sciBadge) {
        if (sci?.busy) {
            sciBadge.innerHTML = `<span style="color: var(--color-warning);">Building</span>`;
        } else if (sci?.complete) {
            sciBadge.innerHTML = `<span style="color: var(--color-success);">✓ Claim!</span>`;
        } else {
            sciBadge.innerHTML = `<span style="color: var(--color-success);">Ready</span>`;
        }
    }

    // ARIA badge
    const ariaBadge = document.getElementById('aria-status-badge');
    if (ariaBadge) {
        if (aria?.busy) {
            ariaBadge.innerHTML = `<span style="color: var(--color-warning);">Building</span>`;
        } else if (aria?.complete) {
            ariaBadge.innerHTML = `<span style="color: var(--color-success);">✓ Claim!</span>`;
        } else {
            ariaBadge.innerHTML = `<span style="color: var(--color-success);">Ready</span>`;
        }
    }
}

function getTimeRemaining(isoDate) {
    const end = new Date(isoDate);
    const now = new Date();
    const diff = end - now;
    if (diff <= 0) return 'Complete!';
    const mins = Math.ceil(diff / 60000);
    if (mins < 60) return `${mins}m`;
    return `${Math.floor(mins/60)}h ${mins%60}m`;
}

function updateXPBars(capXP, sciXP) {
    const capDisplay = document.getElementById('captain-xp-display');
    const capBar = document.getElementById('captain-xp-bar');
    if (capDisplay) capDisplay.textContent = capXP;
    if (capBar) capBar.style.width = `${Math.min(100, capXP / 20)}%`;

    const sciDisplay = document.getElementById('scientist-xp-display');
    const sciBar = document.getElementById('scientist-xp-bar');
    if (sciDisplay) sciDisplay.textContent = sciXP;
    if (sciBar) sciBar.style.width = `${Math.min(100, sciXP / 20)}%`;
}

function startCrewMission(member) {
    pendingMissionMember = member;
    document.getElementById('mission-picker-title').textContent = member === 'captain' ? 'Captain Survey' : 'Scientist Analysis';
    renderTrailList();
    document.getElementById('mission-picker-modal').style.display = 'flex';
}

function renderTrailList() {
    const container = document.getElementById('mission-trail-list');
    if (nearbyTrails.length === 0) {
        container.innerHTML = '<div class="text-xs opacity-60">No discovered landmarks yet. Explore on expeditions first!</div>';
        return;
    }

    container.innerHTML = nearbyTrails.map(t => {
        const kmBuilt = t.km_built || 0;
        const totalKm = t.distance_km || 1;
        const percent = Math.min(100, (kmBuilt / totalKm) * 100).toFixed(1);
        const speedMult = (1 + (kmBuilt / totalKm) * 0.5).toFixed(2);
        return `
        <div class="trail-option" onclick="selectTrail('${t.name}')"
             style="padding: 12px; border: 1px solid var(--border-default); border-radius: 8px; margin-bottom: 8px; cursor: pointer; transition: all 0.2s;"
             onmouseover="this.style.borderColor='var(--color-primary)'" onmouseout="this.style.borderColor='var(--border-default)'">
            <div class="flex justify-between items-center mb-8">
                <div>
                    <div class="text-sm font-semibold">${t.name}</div>
                    <div class="text-xs opacity-60">${t.type} • ${t.distance_km.toFixed(1)}km from base</div>
                </div>
                <div class="text-right">
                    <div class="text-xs font-semibold" style="color: var(--color-sepolia);">${speedMult}× speed</div>
                    <div class="text-xs opacity-60">${percent}% built</div>
                </div>
            </div>
            <div style="background: var(--bg-primary); height: 4px; border-radius: 2px; overflow: hidden;">
                <div style="background: var(--color-sepolia); height: 100%; width: ${percent}%; transition: width 0.3s;"></div>
            </div>
            <div class="text-xs opacity-50 mt-4">${kmBuilt.toFixed(3)} / ${totalKm.toFixed(1)} km</div>
        </div>
    `}).join('');
}

async function selectTrail(name) {
    closeMissionPicker();
    const btn = document.getElementById(`${pendingMissionMember}-mission-btn`);
    btn.disabled = true;
    btn.textContent = pendingMissionMember === 'aria' ? 'Attuning...' : 'Building...';

    try {
        // Use new km-based trail building API (duration calculated server-side)
        const res = await fetch('/api/trail/build', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                destination_name: name,
                worker_type: pendingMissionMember
            })
        });
        const data = await res.json();

        if (data.success) {
            const trail = data.trail;
            showToast(`+${data.km_added.toFixed(3)} km to ${name} (${trail.percent_complete.toFixed(1)}% complete, ${trail.speed_mult.toFixed(2)}× speed)`, 'success');
            loadCrewMissions(); // Refresh
        } else {
            showToast(data.error || 'Failed to build trail', 'error');
            loadCrewMissions();
        }
    } catch (e) {
        showToast('Network error', 'error');
        loadCrewMissions();
    }
}


async function selectTrailForAria(name) {
    if (pendingMissionMember === 'aria') {
        closeMissionPicker();
        const btn = document.getElementById('aria-mission-btn');
        btn.disabled = true;
        btn.textContent = 'Attuning...';

        try {
            const res = await fetch('/api/aria/resonance', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({destination_name: name})
            });
            const data = await res.json();
            if (data.success) {
                showToast(`ARIA resonance: +2 trail to ${name} (now ${data.trail.trail_level})`, 'success');
                loadCrewMissions();
            } else {
                showToast(data.error || 'Resonance failed', 'error');
                loadCrewMissions();
            }
        } catch (e) {
            showToast('Network error', 'error');
            loadCrewMissions();
        }
    } else {
        selectTrail(name);
    }
}

// Override selectTrail to handle ARIA
const _originalSelectTrail = selectTrail;
selectTrail = function(name) {
    if (pendingMissionMember === 'aria') {
        selectTrailForAria(name);
    } else {
        _originalSelectTrail(name);
    }
};

function closeMissionPicker() {
    document.getElementById('mission-picker-modal').style.display = 'none';
    pendingMissionMember = null;
}

// Close modal on overlay click
document.getElementById('mission-picker-modal')?.addEventListener('click', function(e) {
    if (e.target === this) closeMissionPicker();
});

// Mini trail map for crew page
let crewTrailMap = null;
let trailMapMarkers = [];


// Preserve template-injected baseCoords if set
window.baseCoords = window.baseCoords || null;

// Load on page init
document.addEventListener('DOMContentLoaded', function() {
    loadCrewMissions();

    // Init trail map after a short delay
    setTimeout(initCrewTrailMap, 500);
});

// Refresh every 30s
setInterval(loadCrewMissions, 30000);

// Register crew tab callbacks (uses universal switchTab from core.js)
window.tabCallbacks = window.tabCallbacks || {};
// Update tab description when switching tabs
function updateTabDescription(tab) {
    ['trails', 'captain', 'scientist', 'aria', 'services'].forEach(t => {
        const el = document.getElementById(`tab-desc-${t}`);
        if (el) el.style.display = t === tab ? 'inline' : 'none';
    });
}

window.tabCallbacks.crew = {
    trails: function() {
        if (!crewTrailMap) {
            setTimeout(initCrewTrailMap, 100);
        } else {
            setTimeout(() => crewTrailMap.invalidateSize(), 100);
        }
        updateTabDescription('trails');
    },
    captain: function() {
        updateTabDescription('captain');
    },
    scientist: function() {
        updateTabDescription('scientist');
    },
    aria: function() {
        updateTabDescription('aria');
    },
    services: function() {
        updateTabDescription('services');
    }
};

// Update quick status bar
function updateQuickStatus() {
    if (!crewMissionStatus) return;

    const cap = crewMissionStatus.captain;
    const sci = crewMissionStatus.scientist;
    const aria = crewMissionStatus.aria_cooldown;

    // Captain quick status
    const capQuick = document.getElementById('captain-quick-status');
    if (capQuick) {
        if (cap?.busy) {
            const remaining = getTimeRemaining(cap.ends_at);
            capQuick.innerHTML = `<span style="color:var(--color-success);">${remaining}</span>`;
        } else {
            capQuick.textContent = 'Ready';
        }
    }

    // Scientist quick status
    const sciQuick = document.getElementById('scientist-quick-status');
    if (sciQuick) {
        if (sci?.busy) {
            const remaining = getTimeRemaining(sci.ends_at);
            sciQuick.innerHTML = `<span style="color:var(--color-sepolia);">${remaining}</span>`;
        } else {
            sciQuick.textContent = 'Ready';
        }
    }

    // ARIA quick status
    const ariaQuick = document.getElementById('aria-quick-status');
    if (ariaQuick) {
        const ariaData = crewMissionStatus.aria;
        if (ariaData && ariaData.busy) {
            ariaQuick.innerHTML = `<span style="color:var(--color-sepolia);">On mission</span>`;
        } else if (ariaData && ariaData.complete) {
            ariaQuick.textContent = 'Complete';
        } else {
            ariaQuick.textContent = 'Ready';
        }
    }

    // ARIA tab status
    const ariaTabStatus = document.getElementById('aria-tab-status');
    if (ariaTabStatus) {
        const ariaData = crewMissionStatus.aria;
        if (ariaData && ariaData.busy) {
            ariaTabStatus.innerHTML = `<span style="color:var(--color-sepolia);">● On mission</span>`;
        } else if (ariaData && ariaData.complete) {
            ariaTabStatus.innerHTML = `<span style="color:var(--color-success);">● Mission complete</span>`;
        } else {
            ariaTabStatus.innerHTML = `<span style="color:var(--color-success);">● Ready</span>`;
        }
    }

    // Captain tab XP
    const capXp = crewMissionStatus.captain?.xp || 0;
    const capTabXp = document.getElementById('captain-tab-xp');
    const capTabBar = document.getElementById('captain-tab-xp-bar');
    if (capTabXp) capTabXp.textContent = capXp;
    if (capTabBar) capTabBar.style.width = Math.min(100, capXp / 20) + '%';

    // Scientist tab XP
    const sciXp = crewMissionStatus.scientist?.xp || 0;
    const sciTabXp = document.getElementById('scientist-tab-xp');
    const sciTabBar = document.getElementById('scientist-tab-xp-bar');
    if (sciTabXp) sciTabXp.textContent = sciXp;
    if (sciTabBar) sciTabBar.style.width = Math.min(100, sciXp / 20) + '%';
}

// Call updateQuickStatus after mission UI updates
const _originalUpdateMissionUI = updateMissionUI;
updateMissionUI = function() {
    _originalUpdateMissionUI();
    updateQuickStatus();
    checkMissionNotifications();
};

