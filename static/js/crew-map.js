// ============================================================================
// CREW-MAP.JS - Trail Map, Chart Trail Modal, Crew Selection
// ============================================================================

// v3 (#1414): hydrate active_direction + chain segments + chain progress for the modal.
async function loadActiveTrailDirection() {
    try {
        const data = await apiGet('/api/trails/chains');
        if (data && data.success) {
            window.activeTrailDirection = data.active_direction || 'N';
            window.allChainSegments = data.all_segments || [];
            window.lastChainState = data;
            if (typeof updateTopTrails === 'function') updateTopTrails();
            if (typeof crewTrailMap !== 'undefined' && crewTrailMap && typeof updateCrewTrailMapMarkers === 'function') {
                updateCrewTrailMapMarkers();
            }
        }
    } catch (e) { /* silent */ }
}
document.addEventListener('DOMContentLoaded', loadActiveTrailDirection);

function initCrewTrailMap() {
    if (typeof L === 'undefined') {
        // Load Leaflet if not available
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
        document.head.appendChild(link);

        const script = document.createElement('script');
        script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
        script.onload = () => setTimeout(initCrewTrailMap, 100);
        document.head.appendChild(script);
        return;
    }

    const mapContainer = document.getElementById('crew-trail-map');
    if (!mapContainer || crewTrailMap) return;

    // Get base coords from nearby trails or default
    const baseCoords = window.baseCoords || { latitude: -4.5, longitude: 137.4 };

    crewTrailMap = L.map('crew-trail-map', {
        center: [baseCoords.latitude, baseCoords.longitude],
        zoom: 4,
        minZoom: 1,
        maxZoom: 8,
        zoomControl: true,
        scrollWheelZoom: true,
        doubleClickZoom: true,
        worldCopyJump: false,                 // Don't tile Mars horizontally — chains span the planet
        maxBoundsViscosity: 1.0,
        maxBounds: [[-90, -180], [90, 180]]   // Lock view to one Mars
    });

    L.tileLayer('https://cartocdn-gusc.global.ssl.fastly.net/opmbuilder/api/v1/map/named/opm-mars-basemap-v0-2/all/{z}/{x}/{y}.png', {
        attribution: '',
        noWrap: true                          // Don't repeat tiles past lon=180
    }).addTo(crewTrailMap);

    // Add base marker
    L.circleMarker([baseCoords.latitude, baseCoords.longitude], {
        radius: 10,
        fillColor: '#4299e1',
        color: '#2b6cb0',
        weight: 2,
        fillOpacity: 0.9
    }).addTo(crewTrailMap).bindPopup('🏠 Your Base');

    // Populate with nearby trails
    updateCrewTrailMapMarkers();
}

// Bug #1291: destinations that already have an incoming chain trail (Y→X)
// should NOT also render a direct HOME→X line/marker. Otherwise the map shows
// duplicate gold lines: one Base→X and another Base→Y→X for the same endpoint.
function getChainCoveredDestinations() {
    const covered = new Set();
    nearbyTrails.forEach(t => {
        if (t.from_landmark && t.from_landmark !== 'HOME' && t.name) {
            covered.add(t.name);
        }
    });
    return covered;
}

function updateCrewTrailMapMarkers() {
    if (!crewTrailMap) return;

    // Clear old markers
    trailMapMarkers.forEach(m => crewTrailMap.removeLayer(m));
    trailMapMarkers = [];

    const baseCoords = window.baseCoords || { latitude: -4.5, longitude: 137.4 };

    // v3 (#1414) — minimal map: NO chain lines. Just one throbbing antipode beacon
    // showing where all 4 chains converge. Click → modal with full chain data.
    // Top Trails section below the map shows per-direction NSEW progress.
    let antipodeCoords = null;
    let antipodeName = null;
    if (window.allChainSegments && window.allChainSegments.length) {
        // All 4 chains terminate at the same antipode landmark. Use the highest segment_index of any direction.
        const final = window.allChainSegments.reduce((best, s) =>
            (s.to_latitude != null && s.segment_index > (best ? best.segment_index : -1)) ? s : best, null);
        if (final) {
            antipodeCoords = [final.to_latitude, final.to_longitude];
            antipodeName = final.to_landmark;
        }
    }
    if (antipodeCoords) {
        const beacon = L.marker(antipodeCoords, {
            icon: L.divIcon({
                className: '',
                html: '<div class="antipode-beacon" title="Click for chain progress"></div>',
                iconSize: [22, 22],
                iconAnchor: [11, 11]
            })
        }).addTo(crewTrailMap);
        beacon.on('click', () => openAntipodeModal(antipodeName));
        beacon.bindTooltip(`Antipode: ${antipodeName} — click for chain progress`, { direction: 'top', offset: [0, -8] });
        trailMapMarkers.push(beacon);
    }

    // Auto-fit to base + antipode so the planet-scale view fits in one frame
    const points = [[baseCoords.latitude, baseCoords.longitude]];
    if (antipodeCoords) points.push(antipodeCoords);
    if (points.length > 1) {
        crewTrailMap.fitBounds(L.latLngBounds(points), { padding: [40, 40], maxZoom: 3 });
    }
}

// v3 (#1414): click handler for the throbbing antipode beacon.
// Pulls live data from /api/trails/chains and opens a MarsModal with all 4 chain progress.
window.openAntipodeModal = async function(antipodeName) {
    if (typeof MarsModal === 'undefined') return;
    // Andy's preferred 4-color palette: blue/red/black/white (per 2026-04-28 feedback)
    const dirStyle = {
        N: { color: '#3b82f6', label: '⬆ N CHAIN', desc: 'via the North Pole' },
        E: { color: '#ef4444', label: '➡ E CHAIN', desc: 'east through the equator' },
        S: { color: '#000000', label: '⬇ S CHAIN', desc: 'via the South Pole' },
        W: { color: '#ffffff', label: '⬅ W CHAIN', desc: 'west through the equator' }
    };
    let chains = (window.lastChainState && window.lastChainState.chains) || null;
    let activeDir = window.activeTrailDirection || 'N';
    if (!chains) {
        try {
            const data = await apiGet('/api/trails/chains');
            if (data && data.success) {
                chains = data.chains;
                activeDir = data.active_direction || activeDir;
                window.lastChainState = data;
            }
        } catch (e) { /* show stub */ }
    }
    let body = `<div class="mm-card-accent" style="text-align:center;">
        <div class="mm-section-label">Antipode</div>
        <div style="font-size:18px; font-weight:700; color:var(--text-primary);">${antipodeName || '—'}</div>
        <div style="font-size:11px; color:var(--text-muted); margin-top:4px;">All 4 of your chains terminate here</div>
    </div>`;
    body += `<div class="grid" style="grid-template-columns: 1fr; gap: 6px;">`;
    for (const d of ['N', 'E', 'S', 'W']) {
        const info = (chains && chains[d]) || {};
        const pct = info.percent_complete || 0;
        const total = info.total_km || 0;
        const built = info.km_built_total || 0;
        const segs = info.completed_segments || 0;
        const totalSegs = info.total_segments || 0;
        const tier = info.prestige_tier || 'none';
        const isActive = (d === activeDir);
        const ds = dirStyle[d];
        const textColor = (d === 'W') ? '#000000' : '#ffffff';
        const activeBadge = isActive ? `<span style="background:${ds.color};color:${textColor};padding:2px 6px;border-radius:3px;font-size:10px;font-weight:700;margin-left:6px;border:1px solid rgba(255,255,255,0.3);">● ACTIVE</span>` : '';
        body += `<div style="border-left: 4px solid ${ds.color}; padding: 8px 12px; background: rgba(0,0,0,0.25); border-radius: 0 6px 6px 0;">
            <div style="font-weight:600; color: ${ds.color === '#ffffff' ? '#fff' : ds.color}; font-size: 13px;">${ds.label}${activeBadge}</div>
            <div style="font-size: 11px; opacity: 0.8; margin: 2px 0;">${ds.desc} · ${tier}</div>
            <div style="font-size: 12px;">${built.toFixed(0)} / ${total.toFixed(0)} km · ${segs}/${totalSegs} segments · ${pct.toFixed(1)}%</div>
            <div style="background: rgba(255,255,255,0.08); height: 4px; border-radius: 2px; margin-top: 4px; overflow: hidden;">
                <div style="background: ${ds.color}; height: 100%; width: ${Math.min(100, pct)}%; transition: width 0.3s;"></div>
            </div>
        </div>`;
    }
    body += `</div>`;
    MarsModal.show({
        title: 'Your 4 Antipode Chains',
        subtitle: `<span style="color:var(--color-sepolia)">All terminate at ${antipodeName || 'your antipode'}</span>`,
        icon: '🎯',
        width: 'md',
        body: body,
        footer: `<button class="btn btn-primary mm-btn-full" onclick="MarsModal.hide()">Got it</button>`
    });
};

// v3 (#1414): draw a faint full-antipode-route line behind the bright built portion,
// so captains can see WHERE their N/E/S/W chains are headed before they're built.
let ghostRouteLines = [];
function drawGhostChainRoutes() {
    if (!crewTrailMap || !window.allChainSegments) return;
    // Clear any prior ghost
    ghostRouteLines.forEach(l => crewTrailMap.removeLayer(l));
    ghostRouteLines = [];

    // High-contrast palette tuned for severe colorblind viewers on the orange-red Mars terrain.
    // Each color sits at the OPPOSITE end of the color wheel from Mars red — and pairs with
    // a unique dash pattern so direction is encoded by SHAPE too, not color alone.
    // Tested against deuteranopia, protanopia, tritanopia simulators.
    const dirColor = {
        N: '#FFFFFF',  // pure white — max luminance contrast on red, reads at any size
        E: '#00FFFF',  // bright cyan — Mars-red's complementary color, can't be confused with terrain
        S: '#FF1493',  // hot pink/magenta — high saturation against orange, distinct from red
        W: '#000000'   // pure black — minimum luminance contrast on red
    };
    // Per-direction dash pattern (so colorblind viewers can tell chains apart by shape too)
    const dirDash  = { N: null,      E: '16,8',     S: '4,6',     W: '12,4,4,4' };
    // Every chain line gets drawn TWICE — first a dark halo underneath (for high contrast on any bg),
    // then the bright color on top. Halo color picks the opposite luminance of the chain color.
    const dirHalo  = { N: '#000000', E: '#000000',  S: '#000000', W: '#FFFFFF' };
    const baseCoords = window.baseCoords || { latitude: -4.5, longitude: 137.4 };

    // Build a from_landmark → coords lookup using nearbyTrails (which has lat/lon for built segments)
    // and fall back to a separate landmark lookup we'll need server-side. For now: greedy lookup
    // through nearbyTrails AND chain segments (which have to_landmark only).
    // Group segments by direction in segment_index order, draw per-direction polyline through to_landmarks.
    // /api/trails/chains now returns to_latitude/to_longitude on each segment, so we can plot every hop
    // including unbuilt future ones.
    const byDir = { N: [], E: [], S: [], W: [] };
    (window.allChainSegments || []).forEach(s => { if (byDir[s.direction]) byDir[s.direction].push(s); });
    Object.keys(byDir).forEach(d => byDir[d].sort((a, b) => a.segment_index - b.segment_index));

    for (const d of ['N', 'E', 'S', 'W']) {
        const segs = byDir[d];
        if (!segs || !segs.length) continue;
        const pts = [[baseCoords.latitude, baseCoords.longitude]];
        for (const seg of segs) {
            if (seg.to_latitude != null && seg.to_longitude != null) {
                pts.push([seg.to_latitude, seg.to_longitude]);
            }
        }
        if (pts.length < 2) continue;
        // Halo (drawn first, underneath) — opposite luminance so the colored line pops on ANY terrain
        const ghostHalo = L.polyline(pts, {
            color: dirHalo[d],
            weight: 6,
            opacity: 0.45,
            dashArray: dirDash[d] || '6,10'
        }).addTo(crewTrailMap);
        ghostRouteLines.push(ghostHalo);
        // Bright color on top
        const ghost = L.polyline(pts, {
            color: dirColor[d],
            weight: 3,
            opacity: 0.85,
            dashArray: dirDash[d] || '6,10'
        }).addTo(crewTrailMap);
        ghostRouteLines.push(ghost);

        // Antipode beacon — bigger + brighter so the arrival point is visible at any zoom
        const antipode = segs[segs.length - 1];
        const ac = (antipode.to_latitude != null && antipode.to_longitude != null)
            ? [antipode.to_latitude, antipode.to_longitude] : null;
        if (ac) {
            const beacon = L.circleMarker(ac, {
                radius: 9,
                fillColor: dirColor[d],
                color: '#000',
                weight: 2,
                fillOpacity: 0.85,
                opacity: 1.0
            }).addTo(crewTrailMap).bindTooltip(`${d} chain antipode → ${antipode.to_landmark}`, { direction: 'top' });
            ghostRouteLines.push(beacon);
        }
    }
}

// Update crew trail contribution percentages
function updateCrewTrailContributions() {
    // Sum up all km built by each crew member across all trails
    let captainTotal = 0, scientistTotal = 0, ariaTotal = 0;
    nearbyTrails.forEach(t => {
        captainTotal += t.captain_km || 0;
        scientistTotal += t.scientist_km || 0;
        ariaTotal += t.aria_km || 0;
    });
    const grandTotal = captainTotal + scientistTotal + ariaTotal;

    // Update crew contribution displays
    const captainEl = document.getElementById('captain-trail-contrib');
    const scientistEl = document.getElementById('scientist-trail-contrib');
    const ariaEl = document.getElementById('aria-trail-contrib');

    if (grandTotal > 0) {
        const captainPct = (captainTotal / grandTotal * 100).toFixed(1);
        const scientistPct = (scientistTotal / grandTotal * 100).toFixed(1);
        const ariaPct = (ariaTotal / grandTotal * 100).toFixed(1);

        if (captainEl) captainEl.textContent = `${captainPct}% contrib`;
        if (scientistEl) scientistEl.textContent = `${scientistPct}% contrib`;
        if (ariaEl) ariaEl.textContent = `${ariaPct}% contrib`;
    } else {
        if (captainEl) captainEl.textContent = 'No trails yet';
        if (scientistEl) scientistEl.textContent = 'No trails yet';
        if (ariaEl) ariaEl.textContent = 'No trails yet';
    }

    // Update global Mars progress
    const globalKmEl = document.getElementById('global-km-built');
    const globalPctEl = document.getElementById('global-mars-percent');

    if (globalKmEl) {
        globalKmEl.textContent = grandTotal >= 1 ? `${grandTotal.toFixed(1)} km` : `${grandTotal.toFixed(3)} km`;
    }
    if (globalPctEl) {
        // Mars surface area = 144,798,500 km²
        const marsSurfaceKm = 144798500;
        const marsPct = (grandTotal / marsSurfaceKm) * 100;
        // Format with enough decimals to show progress
        if (marsPct === 0) {
            globalPctEl.textContent = '0%';
        } else if (marsPct < 0.0000001) {
            globalPctEl.textContent = marsPct.toExponential(2);
        } else {
            globalPctEl.textContent = marsPct.toFixed(10).replace(/\.?0+$/, '') + '%';
        }
    }
}

// v3 (#1414): Top Trails is now a distinctly NSEW view — one row per cardinal chain
// with chain-cumulative progress. Click a row to set it as your active direction
// AND open the chart-trail modal for the next unbuilt segment.
function updateTopTrails() {
    const section = document.getElementById('top-trails-section');
    const list = document.getElementById('top-trails-list');
    if (!section || !list) return;
    section.style.display = 'block';

    // Group nearbyTrails by chain_direction. The backend returns one row per direction
    // for the next unbuilt segment + completed segment rows.
    const dirOrder = ['N', 'E', 'S', 'W'];
    // High-contrast palette tuned for severe colorblind viewers on the orange-red Mars terrain.
    // Each color sits at the OPPOSITE end of the color wheel from Mars red — and pairs with
    // a unique dash pattern so direction is encoded by SHAPE too, not color alone.
    // Tested against deuteranopia, protanopia, tritanopia simulators.
    const dirColor = {
        N: '#FFFFFF',  // pure white — max luminance contrast on red, reads at any size
        E: '#00FFFF',  // bright cyan — Mars-red's complementary color, can't be confused with terrain
        S: '#FF1493',  // hot pink/magenta — high saturation against orange, distinct from red
        W: '#000000'   // pure black — minimum luminance contrast on red
    };
    // Per-direction dash pattern (so colorblind viewers can tell chains apart by shape too)
    const dirDash  = { N: null,      E: '16,8',     S: '4,6',     W: '12,4,4,4' };
    // Every chain line gets drawn TWICE — first a dark halo underneath (for high contrast on any bg),
    // then the bright color on top. Halo color picks the opposite luminance of the chain color.
    const dirHalo  = { N: '#000000', E: '#000000',  S: '#000000', W: '#FFFFFF' };
    const dirIcon  = { N: '⬆', E: '➡', S: '⬇', W: '⬅' };
    const byDir = { N: [], E: [], S: [], W: [] };
    for (const t of nearbyTrails) {
        if (t.chain_direction && byDir[t.chain_direction]) byDir[t.chain_direction].push(t);
    }

    // Get active direction from window (set by crew page) so we can highlight it
    const activeDir = window.activeTrailDirection || 'N';

    list.innerHTML = dirOrder.map(d => {
        const segs = byDir[d];
        if (!segs || segs.length === 0) {
            return `<div class="p-8" style="background: var(--bg-tertiary); border-radius: 6px; border: 1px solid var(--border-default); opacity: 0.6;">
                <div class="text-xs"><span style="color:${dirColor[d]}; font-weight:700;">${dirIcon[d]} ${d} CHAIN</span> — no chain data</div>
            </div>`;
        }
        // Chain-cumulative state from any row (all rows for same direction share these)
        const meta = segs[0];
        const totalKm = meta.chain_total_km || 0;
        const builtKm = meta.chain_km_built || 0;
        const completedSegs = meta.chain_completed_segments || 0;
        const totalSegs = meta.chain_total_segments || 0;
        const tier = meta.chain_prestige_tier || 'none';
        const pct = totalKm > 0 ? Math.min(100, (builtKm / totalKm) * 100) : 0;
        // Find the next-unbuilt segment row (is_complete=false)
        const next = segs.find(s => !s.is_complete);
        const isActive = (d === activeDir);
        const borderStyle = isActive ? `2px solid ${dirColor[d]}` : `1px solid var(--border-default)`;
        const activeBadge = isActive ? `<span style="color:${dirColor[d]}; font-size:10px; font-weight:700;">● ACTIVE</span>` : '';
        const segLabel = next ? `seg ${next.segment_index} of ${totalSegs} → ${next.name}` : `${totalSegs}/${totalSegs} segments — ✓ Complete`;
        const onclick = next
            ? `setActiveChainAndOpen('${d}', '${(next.name||'').replace(/'/g, "\\'")}')`
            : `setActiveChainOnly('${d}')`;
        return `
            <div class="p-8" style="background: var(--bg-tertiary); border-radius: 6px; cursor: pointer; border: ${borderStyle};" onclick="${onclick}">
                <div class="flex justify-between items-center mb-4">
                    <span class="text-xs font-semibold" style="color: ${dirColor[d]}; letter-spacing: 1px;">${dirIcon[d]} ${d} CHAIN ${activeBadge}</span>
                    <span class="text-xs" style="color: ${dirColor[d]};">${pct.toFixed(1)}% · ${tier}</span>
                </div>
                <div class="text-xs opacity-70 mb-4">${segLabel}</div>
                <div style="height: 4px; background: var(--bg-secondary); border-radius: 2px; overflow: hidden;">
                    <div style="height: 100%; width: ${pct}%; background: ${dirColor[d]}; transition: width 0.3s;"></div>
                </div>
                <div class="flex justify-between text-xs opacity-60 mt-4">
                    <span>${builtKm.toFixed(0)} / ${totalKm.toFixed(0)} km · ${completedSegs}/${totalSegs} segs</span>
                </div>
            </div>
        `;
    }).join('');
}

async function setActiveChainOnly(direction) {
    try {
        await apiPost('/api/trails/active_direction', { direction });
        window.activeTrailDirection = direction;
        if (typeof showToast === 'function') showToast(`Active chain: ${direction}`, 'success');
        updateTopTrails();  // re-render to show new active
    } catch (e) {
        if (typeof showToast === 'function') showToast('Failed to set active direction', 'error');
    }
}

async function setActiveChainAndOpen(direction, segmentName) {
    await setActiveChainOnly(direction);
    openChartTrailModalByName(segmentName);
}

// Helper to open modal by trail name
function openChartTrailModalByName(name) {
    const trail = nearbyTrails.find(t => t.name === name);
    if (trail) openChartTrailModal(trail);
}

// Current trail being charted
let currentChartTrail = null;

// Open the Chart Trail modal when clicking a visited site
function openChartTrailModal(trail) {
    currentChartTrail = trail;

    // Set destination name with chain routing origin
    const destNameEl = document.getElementById('trail-destination-name');
    if (trail.from_landmark && trail.from_landmark !== 'HOME') {
        destNameEl.textContent = `${trail.from_landmark} → ${trail.name}`;
    } else {
        destNameEl.textContent = trail.name;
    }

    // Calculate trail progress using segment distance for chain routing
    const kmBuilt = trail.km_built || 0;
    const totalKm = trail.segment_distance_km || trail.distance_km || 1;
    const percent = Math.min(100, (kmBuilt / totalKm) * 100);
    const speedMult = (1 + (kmBuilt / totalKm) * 0.5).toFixed(2);

    // Update progress display
    document.getElementById('trail-progress-text').textContent = `${kmBuilt.toFixed(3)} / ${totalKm.toFixed(1)} km`;
    document.getElementById('trail-progress-bar').style.width = `${percent}%`;
    document.getElementById('trail-speed-bonus').textContent = `Speed bonus: ${speedMult}×`;
    // SV earned from trail building (5 SV per km built)
    const svEarned = Math.floor(kmBuilt * 5);
    const svEl = document.getElementById('trail-sv-earned');
    if (svEl) svEl.textContent = `Science Value earned: ${svEarned.toLocaleString()} SV (${kmBuilt.toFixed(1)} km × 5 SV/km)`;
    // Show enough precision for small percentages
    let pctText;
    if (percent >= 1) pctText = percent.toFixed(1);
    else if (percent >= 0.01) pctText = percent.toFixed(2);
    else if (percent > 0) pctText = percent.toFixed(6).replace(/\.?0+$/, '');
    else pctText = '0';
    document.getElementById('trail-percent').textContent = `${pctText}% complete`;

    // Update contributor stats
    document.getElementById('captain-contributed').textContent = `${(trail.captain_km || 0).toFixed(3)} km`;
    const sciContrib = document.getElementById('scientist-contributed');
    if (sciContrib) sciContrib.textContent = `${(trail.scientist_km || 0).toFixed(3)} km`;
    document.getElementById('aria-contributed').textContent = `${(trail.aria_km || 0).toFixed(3)} km`;

    // Update crew member availability in modal
    updateCrewModalStatus();

    // Load trail bonuses (scanner + consumables)
    loadTrailBonuses();

    // Show modal
    document.getElementById('chart-trail-modal').style.display = 'flex';
}

// Update crew member status in the Chart Trail modal
function updateCrewModalStatus() {
    const members = ['captain', 'scientist', 'aria'];

    members.forEach(member => {
        const card = document.getElementById(`crew-option-${member}`);
        const deployBtn = document.getElementById(`${member}-deploy-btn`);
        if (!card) return;

        const status = crewMissionStatus?.[member];
        const buildRateEl = document.getElementById(`${member}-build-rate`);

        if (status?.busy) {
            // Show building status - crew is on mission
            card.style.opacity = '0.6';
            if (buildRateEl) buildRateEl.innerHTML = `<span style="color: var(--color-warning);">Building trail...</span>`;
            if (deployBtn) {
                deployBtn.disabled = true;
                deployBtn.style.opacity = '0.5';
                deployBtn.textContent = `⏳ Building...`;
            }
        } else if (status?.complete) {
            // Mission complete - should auto-claim, but show claim option if not yet claimed
            card.style.opacity = '1';
            card.style.borderColor = 'var(--color-success)';
            if (buildRateEl) buildRateEl.innerHTML = `<span style="color: var(--color-success);">✓ Mission complete!</span>`;
            if (deployBtn) {
                deployBtn.disabled = false;
                deployBtn.style.opacity = '1';
                deployBtn.style.background = 'var(--gradient-success)';
                deployBtn.textContent = '✓ Claim Rewards';
                deployBtn.onclick = () => claimTrailMission(member);
            }
        } else {
            // Ready to send - factor in stat multiplier and estimated duration
            card.style.opacity = '1';
            card.style.borderColor = member === 'captain' ? 'var(--color-success)' : member === 'scientist' ? 'var(--color-sepolia)' : '#a855f7';
            const multiplier = status?.stat_multiplier || 1.0;
            // Estimate duration based on visible bonuses (stat included in multiplier)
            const equipmentBonus = trailScannerBonus.bonus_percent || 0;
            const consumableBonus = selectedConsumableId ? (trailConsumables.find(x => x.id == selectedConsumableId)?.trail_bonus_percent || 0) : 0;
            const totalEquipBonus = equipmentBonus + consumableBonus;
            const estimatedDuration = getDurationFromBonus(totalEquipBonus + (multiplier - 1) * 100);
            const kmEstimate = (0.15 * multiplier * estimatedDuration / 60).toFixed(3);
            const svEstimate = Math.floor(parseFloat(kmEstimate) * 5);
            if (buildRateEl) buildRateEl.textContent = `~${kmEstimate} km (+${svEstimate} SV)`;
            if (deployBtn) {
                deployBtn.disabled = false;
                deployBtn.style.opacity = '1';
                deployBtn.textContent = '🛤️ Deploy to Trail';
                deployBtn.onclick = () => selectCrewMember(member);
            }
        }
    });
}

function closeChartTrailModal() {
    document.getElementById('chart-trail-modal').style.display = 'none';
    currentChartTrail = null;
}

// Close modal on overlay click
document.getElementById('chart-trail-modal')?.addEventListener('click', function(e) {
    if (e.target === this) closeChartTrailModal();
});

// Select crew member and start trail building session
async function selectCrewMember(member) {
    if (!currentChartTrail) return;

    // Check if crew member is busy or has mission to claim
    const memberStatus = crewMissionStatus?.[member];
    if (memberStatus?.busy) {
        showToast?.(`${member.charAt(0).toUpperCase() + member.slice(1)} is still on a mission`, 'error');
        return;
    }
    if (memberStatus?.complete) {
        showToast?.(`${member.charAt(0).toUpperCase() + member.slice(1)} has a mission to claim first`, 'error');
        return;
    }

    const trailName = currentChartTrail.name;
    closeChartTrailModal();

    // Show toast that session is starting
    const memberName = member === 'captain' ? 'Captain' : member === 'scientist' ? 'Scientist' : 'ARIA';
    showToast?.(`${memberName} heading to ${trailName}...`, 'info');

    try {
        // Build request body with optional consumable (duration calculated server-side)
        const requestBody = {
            destination_name: trailName,
            worker_type: member
        };
        if (selectedConsumableId) {
            requestBody.consumable_id = parseInt(selectedConsumableId);
        }

        const data = await apiPost('/api/trail/build', requestBody);

        if (data.success) {
            // Show toast with chain routing info
            const routeDesc = data.from_landmark && data.from_landmark !== 'HOME'
                ? `${data.from_landmark} → ${trailName}`
                : trailName;
            let msg = `${memberName} departed! Building ${routeDesc} ~${data.km_to_add.toFixed(3)} km in ${data.duration_minutes} min`;
            if (data.consumable_used) {
                msg += ` (used ${data.consumable_used.item_name}!)`;
            }
            showToast?.(msg, 'success');
            selectedConsumableId = null; // Clear consumed item
            loadCrewMissions(); // Refresh to show countdown
            loadTrailBonuses(); // Refresh consumables list (count changed)
        } else {
            showToast?.(data.error || 'Failed to start mission', 'error');
        }
    } catch (e) {
        showToast?.('Network error', 'error');
    }
}

// Claim completed trail mission
async function claimTrailMission(member) {
    const memberName = member === 'captain' ? 'Captain' : member === 'scientist' ? 'Scientist' : 'ARIA';

    try {
        const data = await apiPost('/api/trail/complete', { worker_type: member });

        if (data.success) {
            const routeDesc = data.from_landmark && data.from_landmark !== 'HOME'
                ? `${data.from_landmark} → ${data.destination}`
                : data.destination;
            let msg = `${memberName} returned! +${(data.km_added || 0).toFixed(3)} km to ${routeDesc}`;
            if (data.xp_gained) msg += `, +${data.xp_gained} XP`;
            if (data.trail) msg += ` (${data.trail.percent_complete?.toFixed(1) || 0}% complete)`;
            showToast?.(msg, 'success');
            loadCrewMissions(); // Refresh
        } else {
            showToast?.(data.error || 'Failed to claim mission', 'error');
        }
    } catch (e) {
        showToast?.('Network error', 'error');
    }
}

// Store base coords for map
