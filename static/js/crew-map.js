// ============================================================================
// CREW-MAP.JS - Trail Map, Chart Trail Modal, Crew Selection
// ============================================================================

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
        zoom: 6,
        minZoom: 4,
        maxZoom: 8,
        zoomControl: false
    });

    L.tileLayer('https://cartocdn-gusc.global.ssl.fastly.net/opmbuilder/api/v1/map/named/opm-mars-basemap-v0-2/all/{z}/{x}/{y}.png', {
        attribution: ''
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
    const chainCovered = getChainCoveredDestinations();

    nearbyTrails.forEach(t => {
        if (!t.latitude || !t.longitude) return;

        // Skip HOME→X when a chain Y→X exists (dedup gold-line clutter)
        const isHomeLeg = !t.from_landmark || t.from_landmark === 'HOME';
        if (isHomeLeg && chainCovered.has(t.name)) return;

        // Color based on trail completion percentage (segment distance for chain routing)
        const kmBuilt = t.km_built || 0;
        const totalKm = t.segment_distance_km || t.distance_km || 1;
        const percent = Math.min(100, (kmBuilt / totalKm) * 100);
        const color = percent >= 100 ? '#ffdc32' : percent >= 50 ? '#64dc96' : percent > 0 ? '#f0a860' : '#888';

        // Draw trail line: solid portion = built, dashed = remaining
        const fromLat = (t.from_landmark && t.from_landmark !== 'HOME' && t.from_latitude) ? t.from_latitude : baseCoords.latitude;
        const fromLon = (t.from_landmark && t.from_landmark !== 'HOME' && t.from_longitude) ? t.from_longitude : baseCoords.longitude;

        if (percent > 0 && percent < 100) {
            // Interpolate the midpoint where built portion ends
            const frac = percent / 100;
            const midLat = fromLat + (t.latitude - fromLat) * frac;
            const midLon = fromLon + (t.longitude - fromLon) * frac;

            // Solid line: HOME → built point (thick, bright)
            const solidLine = L.polyline(
                [[fromLat, fromLon], [midLat, midLon]],
                { color: color, weight: 4, opacity: 1.0 }
            ).addTo(crewTrailMap);
            trailMapMarkers.push(solidLine);

            // Dashed line: built point → destination (white, high contrast for colorblind)
            const dashedLine = L.polyline(
                [[midLat, midLon], [t.latitude, t.longitude]],
                { color: '#ffffff', weight: 3, opacity: 0.7, dashArray: '8,10' }
            ).addTo(crewTrailMap);
            trailMapMarkers.push(dashedLine);
        } else {
            // Fully complete (solid gold) or not started (white dashed, high contrast)
            const line = L.polyline(
                [[fromLat, fromLon], [t.latitude, t.longitude]],
                { color: percent >= 100 ? '#ffdc32' : '#ffffff', weight: percent >= 100 ? 4 : 3, opacity: percent >= 100 ? 0.9 : 0.7, dashArray: percent < 100 ? '8,10' : null }
            ).addTo(crewTrailMap);
            trailMapMarkers.push(line);
        }

        // Add destination marker - CLICK opens the Chart Trail modal
        const marker = L.circleMarker([t.latitude, t.longitude], {
            radius: 8,
            fillColor: color,
            color: '#fff',
            weight: 2,
            fillOpacity: 0.9
        }).addTo(crewTrailMap);

        // Store trail data on marker for click handler
        marker.trailData = t;
        marker.on('click', function() {
            openChartTrailModal(this.trailData);
        });

        // Simple tooltip on hover
        marker.bindTooltip(`<strong>${t.name}</strong><br>${percent.toFixed(1)}% trail`, { direction: 'top' });

        trailMapMarkers.push(marker);
    });

    // Auto-fit map to show base + all trail markers with padding
    if (nearbyTrails.length > 0) {
        const points = [[baseCoords.latitude, baseCoords.longitude]];
        nearbyTrails.forEach(t => {
            if (t.latitude && t.longitude) points.push([t.latitude, t.longitude]);
        });
        if (points.length > 1) {
            crewTrailMap.fitBounds(L.latLngBounds(points), { padding: [30, 30], maxZoom: 7 });
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

// Update Top Trails section - shows best trails to continue working on
function updateTopTrails() {
    const section = document.getElementById('top-trails-section');
    const list = document.getElementById('top-trails-list');
    if (!section || !list) return;

    // Filter trails that have been started (km_built > 0) but not yet complete.
    // Bug #1291: completed trails are now in nearbyTrails for map rendering, but
    // "Top Trails" is for trails to continue working on — exclude finished ones.
    // Also dedup: if Y→X exists as a chain trail, hide the stale HOME→X entry.
    const chainCovered = getChainCoveredDestinations();
    const inProgress = nearbyTrails
        .filter(t => (t.km_built || 0) > 0 && !t.is_complete)
        .filter(t => {
            const isHomeLeg = !t.from_landmark || t.from_landmark === 'HOME';
            return !(isHomeLeg && chainCovered.has(t.name));
        })
        .map(t => ({
            ...t,
            totalKm: t.segment_distance_km || t.distance_km || 1,
            percent: Math.min(100, ((t.km_built || 0) / (t.segment_distance_km || t.distance_km || 1)) * 100)
        }))
        .sort((a, b) => b.percent - a.percent)  // Highest progress first
        .slice(0, 5);  // Top 5

    section.style.display = 'block';
    if (inProgress.length === 0) {
        list.innerHTML = '<div class="text-xs opacity-60 p-8" style="background: var(--bg-tertiary); border-radius: 6px;">No trails in progress yet. Click a destination on the map to start charting a trail!</div>';
        return;
    }

    list.innerHTML = inProgress.map(t => {
        const barColor = t.percent >= 100 ? '#ffdc32' : t.percent >= 50 ? '#64dc96' : '#f0a860';
        // Show enough precision for small percentages
        let statusText;
        if (t.percent >= 100) statusText = '✓ Complete!';
        else if (t.percent >= 1) statusText = `${t.percent.toFixed(1)}%`;
        else if (t.percent >= 0.01) statusText = `${t.percent.toFixed(2)}%`;
        else if (t.percent > 0) statusText = `${t.percent.toFixed(6).replace(/\.?0+$/, '')}%`;
        else statusText = '0%';
        return `
            <div class="p-8" style="background: var(--bg-tertiary); border-radius: 6px; cursor: pointer; border: 1px solid var(--border-default);" onclick="openChartTrailModalByName('${t.name.replace(/'/g, "\\'")}')">
                <div class="flex justify-between items-center mb-4">
                    <span class="text-xs font-semibold">${t.from_landmark && t.from_landmark !== 'HOME' ? t.from_landmark + ' → ' : ''}${t.name}</span>
                    <span class="text-xs" style="color: ${barColor};">${statusText}</span>
                </div>
                <div style="height: 4px; background: var(--bg-secondary); border-radius: 2px; overflow: hidden;">
                    <div style="height: 100%; width: ${t.percent}%; background: ${barColor}; transition: width 0.3s;"></div>
                </div>
                <div class="flex justify-between text-xs opacity-60 mt-4">
                    <span>${(t.km_built || 0).toFixed(3)} / ${(t.totalKm).toFixed(1)} km</span>
                    <span>${(1 + (t.km_built || 0) / (t.totalKm) * 0.5).toFixed(2)}× speed</span>
                </div>
            </div>
        `;
    }).join('');
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
