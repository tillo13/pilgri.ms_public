// ============================================================================
// EXPEDITIONS-TRACKING.JS - Active Expedition Tracking, Rover, Countdown
// ============================================================================

function initializeActiveExpeditionTracking() {
    // Support both old and new banner structure
    const banners = $$('.active-expedition-banner, .active-expedition-widget');
    banners.forEach(w => {
        const id = parseInt(w.dataset.expeditionId);
        const arrives = new Date(w.dataset.arrivesAt);
        const returnArrives = new Date(w.dataset.returnArrivesAt || w.dataset.arrivesAt);  // Fallback for old expeditions
        const destLat = parseFloat(w.dataset.destLat);
        const destLon = parseFloat(w.dataset.destLon);
        const departed = new Date(w.dataset.departedAt);
        const status = w.dataset.status || 'traveling';  // 'traveling' or 'complete'

        // Extract destination name and distance from data attributes (hidden banner or visible banner)
        const destName = w.dataset.destinationName || w.querySelector('.active-expedition-name')?.textContent?.replace(/En Route:\s*/, '').replace(/Returning:\s*/, '').replace(/Arrived:\s*/, '').split('(')[0].trim() || 'Unknown';
        const distance = parseFloat(w.dataset.distanceKm) || 0;

        // Extract vehicle info from banner data attribute
        const vehicleType = w.dataset.vehicleType || 'rover';

        // Store expedition data for popups (including return time)
        activeExpeditionData.set(id, { name: destName, arrives, returnArrives, departed, destLat, destLon, distance, status, vehicleType });

        // If already marked as complete from server, just show arrived state and load discoveries
        if (status === 'complete') {
            // Already complete - just show destination marker and load discoveries
            if (!isNaN(destLat) && !isNaN(destLon)) {
                addRoverMarker(id, destLat, destLon, 1.0);
                addRouteLine(id, destLat, destLon);
                addDestinationMarker(id, destLat, destLon, true);  // arrived = true
            }
            startDiscoveryUpdates(id, w);
            return;  // Skip the countdown logic
        }

        const now = new Date();
        // PREFETCH: Check expedition phase
        if (now >= returnArrives) {
            // Vehicle has returned - show RETURNED and check completion
            const el = w.querySelector('.expedition-timer');
            if (el) {
                el.textContent = 'RETURNED!';
                el.style.color = 'var(--color-success)';
            }
            updatePhaseLabel(w, 'Returned');
            checkExpeditionCompletion(w);
            // Show rover at destination
            if (!isNaN(destLat) && !isNaN(destLon)) {
                addRoverMarker(id, destLat, destLon, 1.0);
                addRouteLine(id, destLat, destLon);
                addDestinationMarker(id, destLat, destLon, true);  // arrived = true
            }
        } else if (now >= arrives) {
            // At destination or returning - countdown to return
            updatePhaseLabel(w, 'Returning');
            startExpeditionCountdown(w, returnArrives, 'returning');
            if (!isNaN(destLat) && !isNaN(destLon)) {
                addRouteLine(id, destLat, destLon);
                addDestinationMarker(id, destLat, destLon, true);  // arrived = true
                startReturnTracking(id, destLat, destLon, arrives, returnArrives);
            }
        } else {
            // Outbound - but always show time until RETURN (round-trip)
            updatePhaseLabel(w, 'En Route');
            startExpeditionCountdown(w, returnArrives, 'outbound_roundtrip', arrives);
            if (!isNaN(destLat) && !isNaN(destLon)) {
                addRouteLine(id, destLat, destLon);
                addDestinationMarker(id, destLat, destLon, false);  // arrived = false
                startRoverTracking(id, destLat, destLon, departed, arrives);
            }
        }
        startDiscoveryUpdates(id, w);
    });
}

// Update the phase label in the expedition banner
function updatePhaseLabel(w, phase) {
    const phaseEl = w.querySelector('.phase-text');
    if (phaseEl) phaseEl.textContent = phase;
}

// Add pulsing rover marker at current position
function addRoverMarker(expeditionId, lat, lon, outboundProgress) {
    if (typeof L === 'undefined' || !map) return;

    // Get expedition data for accurate status
    const expData = activeExpeditionData.get(expeditionId) || {};
    const vehicleType = expData.vehicleType || 'rover';

    // Vehicle display names and actual GCP images
    const vehicleInfo = {
        'rover': { name: 'Rover', image: 'https://storage.googleapis.com/galactica-pilgrim-assets/shop_items/rover_basic_1767505567.png' },
        'buggy': { name: 'Buggy', image: 'https://storage.googleapis.com/galactica-pilgrim-assets/upgrades/vehicles_buggy_lv1_1768788998.png' },
        'drone': { name: 'Drone', image: 'https://storage.googleapis.com/galactica-pilgrim-assets/upgrades/vehicles_drone_lv1_1767751017.png' }
    };
    const info = vehicleInfo[vehicleType] || vehicleInfo['rover'];

    // Calculate round-trip progress and status
    const now = new Date();
    const atDestination = expData.arrives && expData.arrives <= now;
    const hasReturned = expData.returnArrives && expData.returnArrives <= now;

    // Round-trip progress: outbound = 0-50%, return = 50-100%
    let roundTripProgress = 0;
    let statusLabel = '';
    let statusColor = 'var(--color-mars)';

    if (hasReturned) {
        roundTripProgress = 100;
        statusLabel = 'Returned to base';
        statusColor = 'var(--color-success)';
    } else if (atDestination) {
        // At destination or returning - calculate return progress
        if (expData.arrives && expData.returnArrives) {
            const returnTotal = expData.returnArrives - expData.arrives;
            const returnElapsed = now - expData.arrives;
            const returnProgress = Math.min(1, Math.max(0, returnElapsed / returnTotal));
            roundTripProgress = 50 + (returnProgress * 50);
        } else {
            roundTripProgress = 50;
        }
        statusLabel = 'Returning to base';
        statusColor = 'var(--color-sepolia)';
    } else {
        // Outbound - 0-50%
        roundTripProgress = outboundProgress * 50;
        statusLabel = `En route to ${expData.name || 'destination'}`;
        statusColor = 'var(--color-mars)';
    }

    // Remove existing marker for this expedition
    if (roverMarkers.has(expeditionId)) {
        map.removeLayer(roverMarkers.get(expeditionId));
    }

    // Create custom pulsing icon
    const roverIcon = L.divIcon({
        className: 'rover-marker-container',
        html: '<div class="rover-marker"></div>',
        iconSize: [22, 22],
        iconAnchor: [11, 11]
    });

    // Build informative popup
    const popupHtml = `
        <div style="text-align:center; min-width: 160px;">
            <img src="${info.image}" alt="${info.name}" style="width:48px;height:48px;border-radius:8px;object-fit:cover;margin-bottom:8px;box-shadow: 0 2px 8px rgba(0,0,0,0.3);">
            <div style="font-weight: 600; font-size: 14px; color: var(--text-primary); margin-bottom: 4px;">${info.name}</div>
            <div style="font-size: 12px; color: ${statusColor}; margin-bottom: 8px;">${statusLabel}</div>
            <div style="background: var(--bg-tertiary); border-radius: 6px; height: 6px; overflow: hidden; margin-bottom: 6px;">
                <div style="background: ${statusColor}; height: 100%; width: ${roundTripProgress}%; transition: width 0.3s;"></div>
            </div>
            <div style="font-size: 11px; color: var(--text-muted);">Round trip: ${Math.round(roundTripProgress)}%</div>
            ${expData.distance ? `<div style="font-size: 10px; color: var(--text-muted); margin-top: 4px;">${expData.distance} km journey</div>` : ''}
        </div>
    `;

    const marker = L.marker([lat, lon], { icon: roverIcon, zIndexOffset: 1000 }).addTo(map);
    marker.bindPopup(popupHtml);
    roverMarkers.set(expeditionId, marker);
}

// Add animated route line from base to destination
function addRouteLine(expeditionId, destLat, destLon) {
    if (typeof L === 'undefined' || !map) return;

    // Remove existing line for this expedition
    if (routeLines.has(expeditionId)) {
        map.removeLayer(routeLines.get(expeditionId));
    }

    // Create dashed animated line using CSS variable
    const routeColor = getCSSColor('--color-marker-route');
    const line = L.polyline(
        [[baseCoords.latitude, baseCoords.longitude], [destLat, destLon]],
        {
            color: routeColor,
            weight: 3,
            opacity: 0.7,
            dashArray: '10, 8',
            className: 'route-line'
        }
    ).addTo(map);

    routeLines.set(expeditionId, line);
}

// Add pulsing destination marker for active expedition target
function addDestinationMarker(expeditionId, destLat, destLon, hasArrived) {
    if (typeof L === 'undefined' || !map) return;

    // Remove existing destination marker for this expedition
    if (destinationMarkers.has(expeditionId)) {
        map.removeLayer(destinationMarkers.get(expeditionId));
    }

    // Create pulsing destination icon
    const iconClass = hasArrived ? 'destination-marker-arrived' : 'destination-marker-active';
    const destIcon = L.divIcon({
        className: 'destination-marker-container',
        html: `<div class="${iconClass}"></div>`,
        iconSize: [28, 28],
        iconAnchor: [14, 14]
    });

    const marker = L.marker([destLat, destLon], { icon: destIcon, zIndexOffset: 900 }).addTo(map);
    marker.bindPopup(() => buildDestinationPopup(expeditionId));
    destinationMarkers.set(expeditionId, marker);
}

// Build popup content for destination marker
function buildDestinationPopup(expeditionId) {
    const data = activeExpeditionData.get(expeditionId);
    if (!data) return '<div class="map-popup"><b>Destination</b></div>';

    const now = new Date();
    const atDestination = data.arrives <= now;
    const hasReturned = data.returnArrives <= now;
    // Round-trip: total time is from departed to returnArrives
    const total = data.returnArrives - data.departed;
    const elapsed = now - data.departed;
    const progress = Math.min(100, Math.max(0, (elapsed / total) * 100));

    // Vehicle icon based on type
    const vehicleType = data.vehicleType || 'rover';
    const vehicleIcon = vehicleType === 'drone' ? '🛸' : vehicleType === 'buggy' ? '🏎️' : '🚗';
    const vehicleName = vehicleType.charAt(0).toUpperCase() + vehicleType.slice(1);

    let timeStr = '';
    let phaseLabel = '';
    if (hasReturned) {
        timeStr = '<span style="color: var(--color-success); font-weight: 700;">RETURNED!</span>';
        phaseLabel = `✅ ${vehicleName} RETURNED`;
    } else {
        // Always show time until return (round-trip) - that's when user gets their stuff
        const rem = data.returnArrives - now;
        const h = Math.floor(rem / 3600000);
        const m = Math.floor((rem % 3600000) / 60000);
        const s = Math.floor((rem % 60000) / 1000);
        timeStr = `<span style="font-family: monospace; font-size: 18px; font-weight: 700;">${h}h ${m}m ${s}s</span>`;
        phaseLabel = atDestination ? `${vehicleIcon} ${vehicleName} RETURNING` : `${vehicleIcon} ${vehicleName} EN ROUTE`;
    }

    return `<div class="map-popup destination-popup">
        <div class="map-popup-title" style="color: var(--color-mars);">🎯 ${data.name}</div>
        <div class="map-popup-status ${hasReturned ? 'returned' : atDestination ? 'at-destination' : 'en-route'}">${phaseLabel}</div>
        <div style="text-align: center; margin: 12px 0;">${timeStr}</div>
        <div class="destination-progress-bar">
            <div class="destination-progress-fill" style="width: ${progress}%"></div>
        </div>
        <div class="map-popup-details" style="margin-top: 8px;">
            <b>Distance:</b> ${data.distance} km<br>
            <b>Round-trip progress:</b> ${progress.toFixed(0)}%
        </div>
    </div>`;
}

// Track rover position during transit
function startRoverTracking(expeditionId, destLat, destLon, departed, arrives) {
    function updateRoverPosition() {
        const now = new Date();
        const total = arrives - departed;
        const elapsed = now - departed;
        const progress = Math.min(1, Math.max(0, elapsed / total));

        // Interpolate position between base and destination
        const currentLat = baseCoords.latitude + (destLat - baseCoords.latitude) * progress;
        const currentLon = baseCoords.longitude + (destLon - baseCoords.longitude) * progress;

        addRoverMarker(expeditionId, currentLat, currentLon, progress);

        if (progress >= 1) {
            clearInterval(trackingTimer);
        }
    }

    updateRoverPosition();
    const trackingTimer = setInterval(updateRoverPosition, 10000); // Update every 10 seconds
    expeditionTimers.set(`rover_${expeditionId}`, trackingTimer);
}

// Track rover position during return leg (destination -> base)
function startReturnTracking(expeditionId, destLat, destLon, arrives, returnArrives) {
    function updateReturnPosition() {
        const now = new Date();
        const total = returnArrives - arrives;
        const elapsed = now - arrives;
        const progress = Math.min(1, Math.max(0, elapsed / total));

        // Interpolate from destination back to base (reverse of outbound)
        const currentLat = destLat + (baseCoords.latitude - destLat) * progress;
        const currentLon = destLon + (baseCoords.longitude - destLon) * progress;

        addRoverMarker(expeditionId, currentLat, currentLon, 1.0 - progress);

        if (progress >= 1) {
            clearInterval(trackingTimer);
        }
    }

    updateReturnPosition();
    const trackingTimer = setInterval(updateReturnPosition, 10000);
    expeditionTimers.set(`return_${expeditionId}`, trackingTimer);
}

function startExpeditionCountdown(w, targetTime, phase = 'outbound', arrivalTime = null) {
    const el = w.querySelector('.expedition-timer');
    if (!el) return;

    let labelUpdated = false;  // Track if we've updated label to "Returning"
    let timer;
    function update() {
        const now = new Date();
        const rem = targetTime - now;

        // For outbound_roundtrip: update label when vehicle reaches destination and start return tracking
        if (phase === 'outbound_roundtrip' && arrivalTime && !labelUpdated && now >= arrivalTime) {
            updatePhaseLabel(w, 'Returning');
            labelUpdated = true;
            // Transition rover marker from outbound to return tracking
            const id = parseInt(w.dataset.expeditionId);
            const expData = activeExpeditionData.get(id);
            if (expData && !isNaN(expData.destLat) && !isNaN(expData.destLon)) {
                const roverTimer = expeditionTimers.get(`rover_${id}`);
                if (roverTimer) clearInterval(roverTimer);
                startReturnTracking(id, expData.destLat, expData.destLon, arrivalTime, targetTime);
            }
        }

        if (rem <= 0) {
            // Finished - vehicle has returned
            el.textContent = 'RETURNED!';
            el.style.color = 'var(--color-success)';
            clearInterval(timer);
            checkExpeditionCompletion(w);
            return;
        }
        const h = Math.floor(rem / 3600000);
        const m = Math.floor((rem % 3600000) / 60000);
        const s = Math.floor((rem % 60000) / 1000);
        el.textContent = `${h}h ${m}m ${s}s`;
    }
    update();
    timer = setInterval(update, 1000);
    expeditionTimers.set(w.dataset.expeditionId, timer);
}

function startDiscoveryUpdates(id, w) {
    function update() {
        fetch(`/api/expeditions/discoveries/${id}`)
            .then(r => r.json())
            .then(data => { if (data.success) updateDiscoveryDisplay(w, data); })
            .catch(e => console.error('Discovery fetch failed:', e));
    }
    update();
    const timer = setInterval(update, 30000);
    discoveryUpdateTimers.set(id, timer);
}

// Vehicle expedition timers removed - expedition details now shown in orange banners at top of Fleet tab

function updateDiscoveryDisplay(w, data) {
    const prog = w.querySelector('.distance-progress');
    const bar = w.querySelector('.discovery-progress-fill');
    const status = w.querySelector('.discovery-status');
    const container = w.querySelector('.discoveries-container');
    const claimBtn = w.querySelector('.claim-all-expedition-btn');

    const pct = (data.current_distance_km / data.total_distance_km) * 100;
    if (prog) prog.textContent = `${data.current_distance_km} km`;
    if (bar) bar.style.width = `${Math.min(100, pct)}%`;

    const total = data.unlocked_count || 0;
    const unclaimed = data.unlocked_discoveries?.filter(d => !d.claimed_by_user).length || 0;

    if (status) {
        if (total === 0) {
            status.textContent = 'Scanning...';
        } else {
            status.textContent = `${total} items found`;
        }
    }

    if (claimBtn) {
        claimBtn.style.display = (unclaimed > 0 && data.expedition_complete) ? 'inline-block' : 'none';
        claimBtn.textContent = `Claim ${unclaimed} Discover${unclaimed > 1 ? 'ies' : 'y'}`;
    }

    // Only show discoveries when expedition is COMPLETE - keeps cards compact during travel
    if (container && total > 0 && data.expedition_complete) {
        container.style.display = 'block';
        renderDiscoveries(container, data.unlocked_discoveries, data.expedition_complete);
    } else if (container) {
        container.style.display = 'none';
    }
}

function renderDiscoveries(c, disc, complete) {
    if (!disc?.length) {
        c.innerHTML = '<div class="exp-discovery-empty">No discoveries yet</div>';
        return;
    }
    // Use CSS classes instead of inline colors
    c.innerHTML = disc.slice(0, 5).map((d, i) => `
        <div class="exp-discovery-item" data-discovery-index="${i}">
            <div>
                <div class="exp-discovery-name">${d.item_name}</div>
                <div class="exp-discovery-meta rarity-text-${d.rarity}">${d.rarity} • ${d.found_at_km}km</div>
            </div>
            <div class="exp-discovery-status">
                ${d.claimed_by_user ? '✓' : '📦'}
            </div>
        </div>
    `).join('') + (disc.length > 5 ? `<div class="exp-discovery-more">+${disc.length - 5} more</div>` : '');

    // Store discovery data for modal
    c._discoveries = disc.slice(0, 5);

    // Add click handlers
    c.querySelectorAll('.exp-discovery-item').forEach((el, i) => {
        el.addEventListener('click', (e) => {
            e.stopPropagation();
            showExpeditionDiscoveryDetail(c._discoveries[i]);
        });
    });
}

function showExpeditionDiscoveryDetail(d) {
    if (!d || typeof ItemDetailModal === 'undefined') return;

    // Build action button for unclaimed discoveries
    let action = null;
    if (!d.claimed_by_user && d.id) {
        action = {
            label: '📦 Claim Now',
            className: 'btn-primary',
            onClick: async () => {
                if (typeof DiscoveryUtils !== 'undefined') {
                    ItemDetailModal.hide();
                    await DiscoveryUtils.claimAndRefresh(d.id);
                }
            }
        };
    }

    ItemDetailModal.show({
        name: d.item_name,
        image: d.image_url || null,
        category: `<span class="rarity-badge rarity-${d.rarity}">${d.rarity.toUpperCase()}</span>`,
        description: d.description || 'A discovery from your Mars expedition.',
        stats: [
            { label: 'Found At', value: `${d.found_at_km} km` },
            { label: 'Weight', value: d.weight_kg ? `${d.weight_kg} kg` : 'Unknown' },
            { label: 'Scientific Value', value: d.scientific_value ? d.scientific_value.toFixed(1) : '-' },
            { label: 'Status', value: d.claimed_by_user ? '✓ Claimed' : '📦 Unclaimed' }
        ].filter(s => s.value && s.value !== '-' && s.value !== 'Unknown'),
        action: action
    });
}

// Event delegation for new card structure
document.addEventListener('click', function(e) {
    // Launch button
    if (e.target.classList.contains('expedition-launch-btn')) {
        e.preventDefault();
        if (e.target.disabled) {
            // Different messages based on why it's disabled
            const card = e.target.closest('.exp-card');
            if (card && card.dataset.slotsFull === 'true') {
                showToast('All expedition slots in use. Wait for one to complete.', 'warning');
            } else if (e.target.textContent.includes('Insufficient')) {
                showToast('Not enough shards for this expedition', 'warning');
            } else {
                showToast('Complete active expedition first', 'warning');
            }
            return;
        }
        const card = e.target.closest('.exp-card');
        if (card && card._landmark) {
            launchExpedition(card._landmark);
        } else if (card) {
            const landmarkIndex = parseInt(card.dataset.landmarkIndex);
            if (!isNaN(landmarkIndex) && landmarksData[landmarkIndex]) {
                launchExpedition(landmarksData[landmarkIndex]);
            }
        }
    }

    // Show on map button
    if (e.target.classList.contains('expedition-show-map')) {
        e.preventDefault();
        const card = e.target.closest('.exp-card');
        if (card) {
            const landmarkIndex = parseInt(card.dataset.landmarkIndex);
            if (!isNaN(landmarkIndex) && landmarksData[landmarkIndex]) {
                showOnMap(landmarksData[landmarkIndex]);
                // Open the map details if closed
                const mapDetails = document.querySelector('.dashboard-card details');
                if (mapDetails && !mapDetails.open) mapDetails.open = true;
            }
        }
    }
});

