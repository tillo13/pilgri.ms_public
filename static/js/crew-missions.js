// ============================================================================
// CREW-MISSIONS.JS - Trail Missions, Bonuses, Status, Notifications
// ============================================================================

/* ─── Crew Missions ─── */
// Crew Missions JavaScript
// #1434: shared N/E/S/W trail palette (config.TRAIL_DIR_PALETTE via #trailPaletteData).
// window-scoped + idempotent so it shares ONE parse with crew-map.js (no redeclaration).
window.TRAIL_DIR = window.TRAIL_DIR || (function () {
    try {
        const el = document.getElementById('trailPaletteData');
        if (el && el.textContent) return JSON.parse(el.textContent);
    } catch (e) { /* fall through */ }
    return { N: { color: '#FFFFFF' }, E: { color: '#00FFFF' }, S: { color: '#FF1493' }, W: { color: '#000000' } };
})();
let crewMissionStatus = null;
let nearbyTrails = [];
let pendingMissionMember = null;

// Bug #1430 (Luke 2026-04-29): removed scanner+consumable trail-speed-bonus state,
// loader, and UI updater. Trail km still scales with crew member stat × EVA suit
// (server-side); the optional consumable-burn-for-bonus loop was never used.

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
                if (crewTrailMap && !crewTrailMap._suppressAutoRecenter) {
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
        const data = await apiPost('/api/trail/complete', { worker_type: member });

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
            capBadge.innerHTML = `<span style="color: var(--color-success);">${icon('checkmark_done')} Claim!</span>`;
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
            sciBadge.innerHTML = `<span style="color: var(--color-success);">${icon('checkmark_done')} Claim!</span>`;
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
            ariaBadge.innerHTML = `<span style="color: var(--color-success);">${icon('checkmark_done')} Claim!</span>`;
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
    // v3 (#1414): show 4 cardinal chain rows. Captain picks a direction;
    // backend auto-targets the next unbuilt segment of that chain.
    const container = document.getElementById('mission-trail-list');
    const buildable = nearbyTrails.filter(t => !t.is_complete && t.chain_direction);
    if (buildable.length === 0) {
        container.innerHTML = '<div class="text-xs opacity-60">No active chain segments — your chains may all be complete.</div>';
        return;
    }
    // #1434: shared TRAIL_DIR palette so the mission list matches the map + boxes.
    const dirColor = { N: window.TRAIL_DIR.N.color, E: window.TRAIL_DIR.E.color, S: window.TRAIL_DIR.S.color, W: window.TRAIL_DIR.W.color };
    container.innerHTML = buildable.map(t => {
        const kmBuilt = t.km_built || 0;
        const segKm = t.segment_distance_km || 1;
        const segPct = Math.min(100, (kmBuilt / segKm) * 100).toFixed(1);
        const speedMult = (1 + (kmBuilt / segKm) * 0.5).toFixed(2);
        const chainPct = t.chain_total_km ? ((t.chain_km_built / t.chain_total_km) * 100).toFixed(1) : '0';
        const color = dirColor[t.chain_direction] || '#888';
        return `
        <div class="trail-option" onclick="selectChainDirection('${t.chain_direction}', '${t.name.replace(/'/g, "\\'")}')"
             style="padding: 14px; border: 2px solid ${color}; border-radius: 8px; margin-bottom: 10px; cursor: pointer; transition: all 0.2s;"
             onmouseover="this.style.boxShadow='0 0 12px ${color}55'" onmouseout="this.style.boxShadow='none'">
            <div class="flex justify-between items-center mb-8">
                <div>
                    <div class="text-sm font-semibold" style="color: ${color}; letter-spacing: 1px;">${t.chain_direction} CHAIN — segment ${t.segment_index} of ${t.chain_total_segments}</div>
                    <div class="text-xs font-semibold mt-4">→ ${t.name}</div>
                    <div class="text-xs opacity-60">${segKm.toFixed(0)} km segment · ${t.chain_prestige_tier || 'none'}</div>
                </div>
                <div class="text-right">
                    <div class="text-xs font-semibold" style="color: var(--color-sepolia);">${speedMult}× speed</div>
                    <div class="text-xs opacity-60">${segPct}% segment</div>
                    <div class="text-xs opacity-50 mt-4">Chain: ${chainPct}%</div>
                </div>
            </div>
            <div style="background: var(--bg-primary); height: 4px; border-radius: 2px; overflow: hidden;">
                <div style="background: ${color}; height: 100%; width: ${segPct}%; transition: width 0.3s;"></div>
            </div>
            <div class="text-xs opacity-50 mt-4">${kmBuilt.toFixed(2)} / ${segKm.toFixed(0)} km this segment</div>
        </div>
    `}).join('');
}

async function selectChainDirection(direction, segmentName) {
    // v3: set active direction, then trigger the build for the active crew member.
    closeMissionPicker();
    const btn = document.getElementById(`${pendingMissionMember}-mission-btn`);
    btn.disabled = true;
    btn.textContent = pendingMissionMember === 'aria' ? 'Attuning...' : 'Building...';
    try {
        await apiPost('/api/trails/active_direction', { direction });
        if (pendingMissionMember === 'aria') {
            const data = await apiPost('/api/aria/resonance', {});
            if (data.success) {
                showToast(`ARIA resonance: +${(data.km_added || 0).toFixed(2)}km to ${direction} chain seg ${data.segment_index}`, 'success');
            } else {
                showToast(data.error || 'Resonance failed', 'error');
            }
        } else {
            const data = await apiPost('/api/trail/build', { worker_type: pendingMissionMember });
            if (data.success) {
                showToast(`Building ${direction} chain seg ${data.chain_segment_index} → ${segmentName}`, 'success');
            } else {
                showToast(data.error || 'Failed to start mission', 'error');
            }
        }
    } catch (e) {
        showToast('Network error', 'error');
    }
    loadCrewMissions();
}

// v2 compat shim — old callsites
async function selectTrail(name) {
    // Find the chain row matching this destination and route through the new picker
    const row = nearbyTrails.find(t => t.name === name);
    const direction = row ? row.chain_direction : 'N';
    return selectChainDirection(direction, name);
}

async function selectTrailForAria(name) {
    return selectTrail(name);
}

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

function isAuthenticated() {
    const el = document.getElementById('aria-chat');
    return el && el.dataset.authenticated === 'true';
}

// Load on page init
document.addEventListener('DOMContentLoaded', function() {
    if (!isAuthenticated()) return;  // Anonymous users can't hit auth'd endpoints
    loadCrewMissions();

    // Init trail map after a short delay
    setTimeout(initCrewTrailMap, 500);
});

// Refresh every 30s (only when authenticated)
setInterval(function() { if (isAuthenticated()) loadCrewMissions(); }, 30000);

// Register crew tab callbacks (uses universal switchTab from core.js)
window.tabCallbacks = window.tabCallbacks || {};
// Update tab description when switching tabs
function updateTabDescription(tab) {
    ['trails', 'captain', 'scientist', 'aria', 'robot', 'services'].forEach(t => {
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
    robot: function() {
        updateTabDescription('robot');
        // Robot tab self-initializes via crew-robot.js DOMContentLoaded;
        // calling refresh on each entry keeps the countdown live.
        if (typeof window.refreshRobotTab === 'function') {
            window.refreshRobotTab();
        }
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

