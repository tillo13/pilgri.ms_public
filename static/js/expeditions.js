// ============================================================================
// EXPEDITIONS.JS - Mars expedition system
// ============================================================================

let map, expeditionMarkers = [], baseMarker, landmarksData = [], baseCoords = { latitude: 0, longitude: 0 };
const expeditionTimers = new Map(), discoveryUpdateTimers = new Map();
let rangeCircle = null;  // Leaflet circle for vehicle range overlay


// Get CSS variable values for Leaflet (which needs actual color strings)
function getCSSColor(varName) {
    return getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
}

// Active expedition visualization
let roverMarkers = new Map();  // expedition_id -> marker
let routeLines = new Map();    // expedition_id -> polyline
let destinationMarkers = new Map();  // expedition_id -> pulsing destination marker
let activeExpeditionData = new Map();  // expedition_id -> { name, arrives, departed, destLat, destLon, distance }

document.addEventListener('DOMContentLoaded', function() {
    const mapData = $('map-data'), baseData = $('base-coords');
    if (mapData && baseData) {
        landmarksData = JSON.parse(mapData.textContent);
        baseCoords = JSON.parse(baseData.textContent);
        initializeMap();
        updateAllExpeditionCosts();
        initializeSolarConditions();
        initializeActiveExpeditionTracking();
    }
});

function initializeMap() {
    if (typeof L === 'undefined') return;
    const mapEl = $('mars-map');
    if (!mapEl) return;

    // Zoom level 5 for closer view centered on user's base
    map = L.map('mars-map', { center: [baseCoords.latitude, baseCoords.longitude], zoom: 5, minZoom: 1, maxZoom: 6 });
    L.tileLayer('https://cartocdn-gusc.global.ssl.fastly.net/opmbuilder/api/v1/map/named/opm-mars-basemap-v0-2/all/{z}/{x}/{y}.png', { attribution: 'Mars: NASA/JPL', minZoom: 1, maxZoom: 6 }).addTo(map);
    // Base marker: uses CSS variable colors
    const baseColor = getCSSColor('--color-marker-base');
    const baseBorder = getCSSColor('--color-marker-base-border');
    baseMarker = L.circleMarker([baseCoords.latitude, baseCoords.longitude], { radius: 12, fillColor: baseColor, color: baseBorder, weight: 3, opacity: 1, fillOpacity: 0.9 }).addTo(map);
    baseMarker.bindPopup(`<div class="map-popup"><div class="map-popup-title base">🏠 Colony Base</div><div class="map-popup-coords">${baseCoords.latitude.toFixed(4)}°, ${baseCoords.longitude.toFixed(4)}°</div></div>`);
    addExpeditionMarkers();
    addOriginSiteMarkers();
    initializeMapResizeHandlers();
}

// Handle map resize on window resize and orientation change
function initializeMapResizeHandlers() {
    if (!map) return;

    let resizeTimer;

    // Debounced resize handler (250ms) to prevent performance issues
    window.addEventListener('resize', function() {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(function() {
            if (map) {
                map.invalidateSize();
            }
        }, 250);
    }, { passive: true });

    // Handle orientation change explicitly (300ms delay for browser reflow)
    window.addEventListener('orientationchange', function() {
        setTimeout(function() {
            if (map) {
                map.invalidateSize();
            }
        }, 300);
    }, { passive: true });
}

function addExpeditionMarkers() {
    // Get colors from CSS variables
    const visitedColor = getCSSColor('--color-marker-visited');
    const visitedBorder = getCSSColor('--color-marker-visited-border');
    const unexploredColor = getCSSColor('--color-marker-unexplored');
    const unexploredBorder = getCSSColor('--color-marker-unexplored-border');

    landmarksData.forEach((l, i) => {
        const disc = l.is_discovered;
        const m = L.circleMarker([l.latitude, l.longitude], {
            radius: 8,
            fillColor: disc ? visitedColor : unexploredColor,
            color: disc ? visitedBorder : unexploredBorder,
            weight: 2, opacity: 1, fillOpacity: 0.8
        }).addTo(map);

        // Store landmark index on marker for popup updates
        m._landmarkIndex = i;

        // Create popup with placeholder for cost - will be updated when opened
        m.bindPopup(() => buildMarkerPopup(i));
        expeditionMarkers.push(m);
    });
}


// Vehicle range circle overlay
function setVehicleRange(btn, vehicleType) {
    // Update active button
    document.querySelectorAll('.vehicle-range-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');

    if (!map) return;

    // Remove existing circle
    if (rangeCircle) { map.removeLayer(rangeCircle); rangeCircle = null; }

    // Get marker colors
    const visitedColor = getCSSColor('--color-marker-visited');
    const visitedBorder = getCSSColor('--color-marker-visited-border');
    const unexploredColor = getCSSColor('--color-marker-unexplored');
    const unexploredBorder = getCSSColor('--color-marker-unexplored-border');
    const dimColor = '#555';
    const dimBorder = '#444';

    if (vehicleType === 'all') {
        // Restore all markers to default
        expeditionMarkers.forEach((m, i) => {
            const disc = landmarksData[i].is_discovered;
            m.setStyle({ fillColor: disc ? visitedColor : unexploredColor, color: disc ? visitedBorder : unexploredBorder, fillOpacity: 0.8, opacity: 1 });
            m.setRadius(8);
        });
        window.__currentRangeKm = null;
        return;
    }

    const rangeKm = parseInt(btn.dataset.range) || 0;

    // Draw range circle — Leaflet assumes Earth radius (6371km) for its circle rendering.
    // Our Mars haversine distances use Mars radius (3396km). To convert: a D_km Mars
    // distance subtends angle D/3396 rad; Leaflet needs that same angle as Earth meters
    // = (D/3396) * 6371000 = D * (6371/3396) * 1000. Mathematically verified correct.
    const marsCorrection = 6371 / 3396;
    rangeCircle = L.circle([baseCoords.latitude, baseCoords.longitude], {
        radius: rangeKm * 1000 * marsCorrection,
        color: '#ffffff',
        fillColor: '#ffffff',
        fillOpacity: 0.04,
        weight: 2,
        opacity: 0.7,
        dashArray: '8, 6',
        interactive: false
    }).addTo(map);
    // Bug #1283: explicit label on the range circle so Luke can verify visually that
    // a marker labeled "403km" is correctly OUT of a 300km vehicle range. Without
    // this, the dashed circle is just a hint — players can't tell what km it represents.
    rangeCircle.bindTooltip(`${rangeKm.toLocaleString()} km range`, { permanent: true, direction: 'top', className: 'range-circle-label' });
    // Store current selected range so marker popups can compute in/out status
    window.__currentRangeKm = rangeKm;

    // Dim out-of-range landmarks, brighten in-range ones
    expeditionMarkers.forEach((m, i) => {
        const dist = landmarksData[i].distance_km;
        const inRange = dist <= rangeKm;
        const disc = landmarksData[i].is_discovered;
        if (inRange) {
            m.setStyle({ fillColor: disc ? visitedColor : unexploredColor, color: disc ? visitedBorder : unexploredBorder, fillOpacity: 0.95, opacity: 1 });
            m.setRadius(9);
        } else {
            m.setStyle({ fillColor: dimColor, color: dimBorder, fillOpacity: 0.3, opacity: 0.4 });
            m.setRadius(6);
        }
    });
}

// Build popup content for a marker (called when popup opens)
function buildMarkerPopup(landmarkIndex) {
    const l = landmarksData[landmarkIndex];
    const disc = l.is_discovered;
    const cost = l._calculatedCost;
    const balance = typeof window.getBalance === 'function' ? window.getBalance() : 0;
    const slotsAvailable = (window.activeExpeditionCount || 0) < (window.maxConcurrentExpeditions || 1);

    // If cost not calculated yet, fetch it and update popup
    if (cost === undefined) {
        fetchLandmarkCost(landmarkIndex);
    }

    const canAfford = !cost || balance >= cost;
    const canLaunch = canAfford && slotsAvailable;
    const costDisplay = cost !== undefined ? `<br><b>Cost:</b> <span style="color: ${canAfford ? 'var(--color-mars)' : 'var(--color-error)'}">${cost.toFixed(0)} shards</span>` : '<br><b>Cost:</b> <span style="color: var(--text-muted)">calculating...</span>';
    // Bug #1283: when a vehicle range is selected, show explicit in/out-of-range status in the popup
    let rangeStatus = '';
    if (window.__currentRangeKm) {
        const inRange = l.distance_km <= window.__currentRangeKm;
        rangeStatus = `<br><b>Range:</b> <span style="color: ${inRange ? 'var(--color-success)' : 'var(--color-error)'}">${inRange ? 'In range' : 'Out of range'} (${l.distance_km} km / ${window.__currentRangeKm} km vehicle range)</span>`;
    }
    const est = l._estimatedReturn;
    const returnDisplay = est ? `<br><b>Est. Return:</b> <span style="color: var(--color-success)">${Math.round(est.low)} - ${Math.round(est.high)} shards</span>` : '';

    let popup = `<div class="map-popup">
        <div class="map-popup-title">${l.name}</div>
        <div class="map-popup-status ${disc ? 'visited' : 'unexplored'}">${disc ? '✅ VISITED' : '🔍 UNEXPLORED'}</div>
        <div class="map-popup-details"><b>Type:</b> ${l.type}<br><b>Distance:</b> ${l.distance_km} km${rangeStatus}${costDisplay}${returnDisplay}</div>`;
    if (disc && l.last_visit) {
        popup += `<div class="map-popup-history">
            <div class="map-popup-history-label">LAST EXPEDITION</div>
            <div class="map-popup-history-content">${new Date(l.last_visit).toLocaleDateString()}<br>Yield: ${l.last_yield.toFixed(1)} Shards</div>
        </div>`;
    }
    // Add expedition button - disabled if can't afford or no slots
    const btnClass = canLaunch ? 'map-popup-btn' : 'map-popup-btn disabled';
    const btnText = !slotsAvailable ? 'No Slots' : (!canAfford ? 'Insufficient Shards' : (disc ? 'Plan Revisit' : 'Plan Expedition'));
    popup += `<button class="${btnClass}" ${canLaunch ? `onclick="launchExpeditionFromMap(${landmarkIndex})"` : 'disabled'}>${btnText}</button>`;
    popup += `</div>`;
    return popup;
}

// Fetch cost for a landmark and refresh its popup
async function fetchLandmarkCost(landmarkIndex) {
    const l = landmarksData[landmarkIndex];
    if (!l || l._calculatedCost !== undefined) return;

    try {
        const data = await apiPost('/api/expeditions/calculate_cost', { distance_km: l.distance_km, destination_type: l.type });
        if (data.success) {
            l._calculatedCost = data.total_pricing.total_cost_display;
            l._canAfford = data.total_pricing.can_afford;
            if (data.estimated_return) l._estimatedReturn = data.estimated_return;
            // Refresh the popup if it's still open for this marker
            expeditionMarkers.forEach(m => {
                if (m._landmarkIndex === landmarkIndex && m.isPopupOpen()) {
                    m.setPopupContent(buildMarkerPopup(landmarkIndex));
                }
            });
        }
    } catch (e) {
        console.error('Failed to fetch landmark cost:', e);
    }
}

// Update costs for all expedition cards (new structure)
async function updateAllExpeditionCosts() {
    const cards = $$('.exp-card');
    for (const card of cards) {
        const landmarkIndex = parseInt(card.dataset.landmarkIndex);
        if (!isNaN(landmarkIndex) && landmarksData[landmarkIndex]) {
            await updateExpeditionCost(card, landmarksData[landmarkIndex]);
        }
    }
}

async function updateExpeditionCost(card, l) {
    try {
        const data = await apiPost('/api/expeditions/calculate_cost', { distance_km: l.distance_km, destination_type: l.type });
        if (data.success) updateCostDisplay(card, data, l);
        else card.querySelector('.expedition-total-cost').textContent = 'Error';
    } catch {
        card.querySelector('.expedition-total-cost').textContent = '--';
    }
}

function updateCostDisplay(card, data, landmark) {
    const ep = data.expedition_pricing, tp = data.total_pricing;

    // Store cost on landmark for map popup
    landmark._calculatedCost = tp.total_cost_display;
    landmark._canAfford = tp.can_afford;

    // Update cost
    const costEl = card.querySelector('.expedition-total-cost');
    if (costEl) costEl.textContent = tp.total_cost_display.toFixed(1);

    // Update travel time (round-trip - that's what matters to users)
    const travelEl = card.querySelector('.expedition-travel-time');
    if (travelEl) travelEl.textContent = ep.round_trip_days || (ep.travel_days * 2);

    // Update speed multiplier
    const speedEl = card.querySelector('.expedition-speed-mult');
    if (speedEl) speedEl.textContent = `${ep.logistics_speed_multiplier.toFixed(1)}×`;

    // Update cost breakdown (if exists) - New vehicle-based system
    const breakdownEl = card.querySelector('.expedition-cost-breakdown');
    if (breakdownEl) {
        let breakdownHtml = `<div style="display: flex; flex-direction: column; gap: 4px;">`;

        // Base cost
        breakdownHtml += `<div style="display: flex; justify-content: space-between;"><span>Base (${ep.distance_tier})</span><span>${ep.base_cost || ep.base_fuel_cost}</span></div>`;

        // Terrain cost (if significant)
        if (ep.terrain_cost > 0) {
            breakdownHtml += `<div style="display: flex; justify-content: space-between;"><span>Terrain (${ep.terrain_multiplier}×)</span><span>+${ep.terrain_cost.toFixed(0)}</span></div>`;
        } else if (ep.terrain_multiplier < 1.0) {
            const discount = ((1 - ep.terrain_multiplier) * 100).toFixed(0);
            breakdownHtml += `<div style="display: flex; justify-content: space-between; color: var(--color-success);"><span>Terrain (easy)</span><span>-${discount}%</span></div>`;
        }

        // Terrain SPEED impact (critical info for users!)
        if (ep.terrain_speed_mult && ep.terrain_speed_mult !== 1.0) {
            const speedPct = Math.abs((ep.terrain_speed_mult - 1) * 100).toFixed(0);
            if (ep.terrain_speed_mult < 1) {
                breakdownHtml += `<div style="display: flex; justify-content: space-between; color: var(--color-mars); font-weight: 600;"><span>⚠️ Slow terrain</span><span>-${speedPct}% speed</span></div>`;
            } else {
                breakdownHtml += `<div style="display: flex; justify-content: space-between; color: var(--color-success);"><span>Fast terrain</span><span>+${speedPct}% speed</span></div>`;
            }
        }

        // Vehicle efficiency
        if (ep.vehicle_savings > 0) {
            breakdownHtml += `<div style="display: flex; justify-content: space-between; color: var(--color-sepolia);"><span>Vehicle efficiency</span><span>-${ep.vehicle_savings.toFixed(0)}</span></div>`;
        }

        // Logistics skill
        if (ep.logistics_savings > 0) {
            breakdownHtml += `<div style="display: flex; justify-content: space-between; color: var(--color-success);"><span>Logistics (${ep.logistics_skill})</span><span>-${ep.logistics_savings.toFixed(0)}</span></div>`;
        }

        // Strategy (terrain reduction)
        if (ep.strategy_savings > 0) {
            breakdownHtml += `<div style="display: flex; justify-content: space-between; color: var(--color-success);"><span>Strategy (${ep.strategy_skill})</span><span>-${ep.strategy_savings.toFixed(0)}</span></div>`;
        }

        // Experience discount
        if (ep.experience_savings > 0) {
            breakdownHtml += `<div style="display: flex; justify-content: space-between; color: var(--color-success);"><span>Experience (-${ep.experience_discount_pct.toFixed(0)}%)</span><span>-${ep.experience_savings.toFixed(0)}</span></div>`;
        }

        // Return visit bonus
        if (ep.is_return_visit && ep.return_savings > 0) {
            breakdownHtml += `<div style="display: flex; justify-content: space-between; color: var(--color-sepolia);"><span>Return visit (-30%)</span><span>-${ep.return_savings.toFixed(0)}</span></div>`;
        }

        // Total
        breakdownHtml += `
            <div style="border-top: 1px solid var(--border-default); margin-top: 4px; padding-top: 4px; display: flex; justify-content: space-between; font-weight: 600;"><span>Total</span><span>${tp.total_cost_display.toFixed(1)} Shards</span></div>
        </div>`;

        breakdownEl.innerHTML = breakdownHtml;
    }

    // Store landmark data on card for launch
    card._landmark = landmark;

    // Grey out unaffordable cards (like depot)
    const btn = card.querySelector('.expedition-launch-btn');
    if (!tp.can_afford) {
        card.classList.add('insufficient');
        if (costEl) costEl.style.color = 'var(--text-muted)';
        if (btn && !btn.disabled) {
            btn.title = `Need ${tp.shortfall_display.toFixed(1)} more Shards`;
            btn.disabled = true;
            btn.textContent = 'Insufficient';
        }
    } else {
        card.classList.remove('insufficient');
        if (costEl) costEl.style.color = '';
        if (btn && card.dataset.slotsFull !== 'true') {
            btn.title = '';
            btn.disabled = false;
            btn.textContent = card.classList.contains('discovered') ? 'Plan Revisit' : 'Plan Expedition';
        }
    }
}

function initializeSolarConditions() {
    updateSolarConditions();
    // No interval needed - conditions don't change frequently
}

async function updateSolarConditions() {
    try {
        const r = await fetch('/api/mars_conditions');
        const data = await r.json();
        if (!data.success) return;
        const { conditions } = data;
        // Update all condition displays
        const effEl = $('solarEfficiency');
        const statusEl = $('conditionStatus');
        const angleEl = $('solarAngle');
        const feeEl = $('feeMultiplier');
        if (effEl) effEl.textContent = conditions.efficiency;
        if (statusEl) statusEl.textContent = conditions.condition;
        if (angleEl) angleEl.textContent = conditions.solar_angle?.toFixed(1) || '--';
        if (feeEl) feeEl.textContent = conditions.fee_multiplier?.toFixed(2) || '--';
    } catch (e) {
        console.error('Solar conditions update failed:', e);
    }
}

// Map landmark search
function searchMapLandmark(query) {
    const results = $('map-search-results');
    if (!results) return;
    if (!query || query.length < 2) { results.style.display = 'none'; return; }

    const q = query.toLowerCase();
    const matches = landmarksData
        .filter(l => l.name && l.name.toLowerCase().includes(q))
        .slice(0, 8);

    if (!matches.length) {
        results.style.display = 'none';
        return;
    }

    results.innerHTML = matches.map(l => {
        const disc = l.is_discovered;
        const dot = disc ? '🟢' : '🔴';
        const dist = l.distance_km ? `${Math.round(l.distance_km).toLocaleString()} km` : '';
        return `<div onclick="zoomToLandmark('${l.name.replace(/'/g, "\\'")}')" style="padding: 8px 12px; cursor: pointer; border-bottom: 1px solid var(--border-default); font-size: 12px;" onmouseover="this.style.background='var(--bg-tertiary)'" onmouseout="this.style.background=''">${dot} <strong>${l.name}</strong> <span style="opacity:0.6; margin-left:4px;">${l.type || ''}</span> <span style="float:right; color:var(--text-muted);">${dist}</span></div>`;
    }).join('');
    results.style.display = 'block';
}

function zoomToLandmark(name) {
    const results = $('map-search-results');
    const searchInput = $('map-search');
    if (results) results.style.display = 'none';
    if (searchInput) searchInput.value = name;

    const idx = landmarksData.findIndex(l => l.name === name);
    if (idx < 0 || !map) return;

    const l = landmarksData[idx];
    map.setView([l.latitude, l.longitude], 6, { animate: true });

    // Flash the marker
    const marker = expeditionMarkers[idx];
    if (marker) {
        marker.setRadius(16);
        marker.openPopup();
        setTimeout(() => marker.setRadius(8), 2000);
    }
}

