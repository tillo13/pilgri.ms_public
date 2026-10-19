// ============================================================================
// EXPEDITIONS.JS - Mars expedition system
// ============================================================================

let map, expeditionMarkers = [], baseMarker, landmarksData = [], baseCoords = { latitude: 0, longitude: 0 };
const expeditionTimers = new Map(), discoveryUpdateTimers = new Map();
let rangeCircle = null;  // Leaflet circle for vehicle range overlay

// #1485: plot longitudes RELATIVE TO THE CAPTAIN'S BASE via shortest-arc, so a point just
// past the lon 0/360 seam (e.g. a western frontier dot at lon 350 when base is lon 5) renders
// just-west of base (lon -10) instead of way off on the far/NE edge. This is the display-layer
// twin of the server-side _lon_delta shortest-arc fix (utilities/postgres/map.py) — the same bug
// (flat longitude vs. shortest-arc) lived in both the data and the render. Leaflet plots
// out-of-[-180,180] longitudes fine because the Mars tile layer wraps (worldCopyJump). Exposed
// on window so expeditions-origin.js (signal markers) plots on the SAME normalized frame.
function plotMapLon(lon) {
    if (lon == null || !isFinite(lon)) return lon;
    const d = ((lon - baseCoords.longitude + 540) % 360) - 180;  // shortest signed arc, (-180,180]
    return baseCoords.longitude + d;
}
function plotMapLL(lat, lon) { return [lat, plotMapLon(lon)]; }
window.plotMapLL = plotMapLL;
window.plotMapLon = plotMapLon;


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
    map = L.map('mars-map', { center: [baseCoords.latitude, baseCoords.longitude], zoom: 5, minZoom: 1, maxZoom: 6, worldCopyJump: true });
    L.tileLayer('https://cartocdn-gusc.global.ssl.fastly.net/opmbuilder/api/v1/map/named/opm-mars-basemap-v0-2/all/{z}/{x}/{y}.png', { attribution: 'Mars: NASA/JPL', minZoom: 1, maxZoom: 6 }).addTo(map);
    // Base marker: uses CSS variable colors
    const baseColor = getCSSColor('--color-marker-base');
    const baseBorder = getCSSColor('--color-marker-base-border');
    baseMarker = L.circleMarker([baseCoords.latitude, baseCoords.longitude], { radius: 12, fillColor: baseColor, color: baseBorder, weight: 3, opacity: 1, fillOpacity: 0.9 }).addTo(map);
    baseMarker.bindPopup(`<div class="map-popup"><div class="map-popup-title base">${icon('home_base')} Colony Base</div><div class="map-popup-coords">${baseCoords.latitude.toFixed(4)}°, ${baseCoords.longitude.toFixed(4)}°</div></div>`);
    addExpeditionMarkers();
    addOriginSiteMarkers();
    initializeMapResizeHandlers();
    applyDeepLinkFocus();
}

// Signal → Map deep link (Bug #1275):
// ?lat=X&lon=Y&zoom=N&marker=LABEL pans the map and drops a pulsing highlight
// so captains clicking a coord on the Signal page land on that exact spot.
function applyDeepLinkFocus() {
    if (!map) return;
    const params = new URLSearchParams(window.location.search);
    const lat = parseFloat(params.get('lat'));
    const lon = parseFloat(params.get('lon'));
    if (!isFinite(lat) || !isFinite(lon)) return;
    const zoom = Math.max(1, Math.min(6, parseInt(params.get('zoom') || '6', 10)));
    const label = params.get('marker') || '';

    // Switch to map tab if we're not already on it
    if (typeof switchMainTab === 'function') {
        switchMainTab('map');
    }

    map.setView(plotMapLL(lat, lon), zoom);

    const highlight = L.circleMarker(plotMapLL(lat, lon), {
        radius: 18,
        fillColor: '#facc15',
        color: '#f97316',
        weight: 4,
        opacity: 1,
        fillOpacity: 0.4,
        className: 'deep-link-pulse'
    }).addTo(map);

    if (label) {
        highlight.bindPopup(
            `<div class="map-popup"><div class="map-popup-title">${label}</div>` +
            `<div class="map-popup-coords">${lat.toFixed(4)}°, ${lon.toFixed(4)}°</div></div>`
        ).openPopup();
    }

    // Fade the highlight out after 20s so it doesn't stick forever.
    setTimeout(() => { if (map.hasLayer(highlight)) map.removeLayer(highlight); }, 20000);
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
        const m = L.circleMarker(plotMapLL(l.latitude, l.longitude), {
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

    // ============================================================================
    // 🛑 DO NOT TOUCH WITHOUT READING BUGS #1057, #1112, #1394, #1460 IN FULL.
    // ============================================================================
    // This function has been broken FIVE times. Each break re-introduced a
    // constraint Luke had already rejected in a prior bug. The next break will
    // make him very tired. Read the predecessor bugs before changing anything.
    //
    // LOCKED INVARIANTS — every one is a direct Luke quote. Violating any of
    // these will cause Luke to file another P1 within days.
    //
    // 1. WHITE STROKE — never orange/red/anything blendable with Mars terrain.
    //    Luke is severely colorblind. Bug #1112 (2026-03-22):
    //    > "the 'orange' on that Martian background map is TERRIBLE for me,
    //    >  i can't see it at all... can we make the circle white?"
    //
    // 2. BASE-CENTERED, SHOWS WHAT'S REACHABLE. Never invert to show the
    //    unreachable region. Luke's origin ask, bug #1057 (2026-03-21):
    //    > "adding some kind of circle that shows the max distance a vehicle
    //    >  can go on Expedition Map."
    //
    // 3. CLOSED SHAPE — must connect on all sides. Bug #1394 (2026-04-30):
    //    > "it's Ok for the circle to not be a perfect circle, it just has to
    //    >  connect on all sides and show up on the map in a user friendly way."
    //
    // 4. VISIBLE IN VIEWPORT — auto-fitBounds() so Luke never has to scroll
    //    to find the ring. Bug #1394 (2026-04-29):
    //    > "Still don't see Buggy Circle at all."
    //
    // 5. DOT DIM/BRIGHT CLASSIFICATION IS SOURCE OF TRUTH. The visible ring
    //    is allowed to be a Mercator approximation. Bug #1394 (2026-04-29):
    //    > "The distances seem to be calculating correctly now (dots greyed
    //    >  out if they are not reachable, and outside circle)."
    //
    // 6. "COVERS THE WHOLE PLANET" IS FINE — preferable to no ring at all.
    //    Bug #1394 (2026-04-29):
    //    > "I want the Buggy circle back, even if it 'covers' the whole planet."
    //
    // 7. NO INVERTED / "OUT OF RANGE" / ANTIPODE FRAMING EVER. Bug #1460
    //    (2026-05-09) — Luke filed a fresh P1 the moment v4 hit case (b):
    //    > "Rover circle not showing up. But i do see a dotted 'orange' circle,
    //    >  but not sure what it is trying to highlight. The message in the text
    //    >  box says 'only this zone is too far to reach'...no idea what this
    //    >  means."
    //    Translation: orange = invisible (#1112) + inverted = wrong mental
    //    model (#1057). Violating either is an automatic P1.
    //
    // ============================================================================
    // PRIOR ATTEMPT HISTORY — every version Luke rejected, lined up so the
    // next person to touch this code can avoid re-attempting a failed shape:
    //
    //   v0/v1  L.circle, Earth/Mars scale       → dots in/out didn't match.
    //   v2     128-pt geodesic polygon          → antimeridian straight lines.
    //   v3     geodesic polyline + AM splitter  → "sin wave" / "bell" at δ>90°
    //                                             from pole-crossing; Buggy
    //                                             ring offscreen.
    //   v4     L.circle base ring (δ<90°)       → violated #1057 + #1112 in
    //          + ORANGE ANTIPODE (90°≤δ<180°)     case (b); Luke filed #1460.
    //          + Global Reach label (δ≥180°)
    //   v5 (current — bug #1460 fix, 2026-05-17): collapse v4's case (b) into
    //          case (a). Single white L.circle around base for ALL δ < 180°.
    //          Yes the ellipse is huge and stretched at δ≈110-150°. Per
    //          INVARIANTS 3 + 6 above, that is explicitly Luke-approved.
    //          Bug #1428 (Backlog P5) tracks the eventual sphere-map switch
    //          that would let us draw geodesic-correct rings.
    // ============================================================================
    const MARS_RADIUS_KM = 3396;
    const EARTH_RADIUS_KM = 6371;
    const marsCorrection = EARTH_RADIUS_KM / MARS_RADIUS_KM;
    const angularRad = rangeKm / MARS_RADIUS_KM;
    const angularDeg = angularRad * 180 / Math.PI;

    // δ ≥ 180°: range exceeds half-circumference, every landmark is reachable.
    // No meaningful ring to draw; pin a "Global Reach" label at base instead.
    // (Luke approved this branch in v4 QA.)
    if (angularDeg >= 180) {
        rangeCircle = L.marker([baseCoords.latitude, baseCoords.longitude], {
            opacity: 0,
            interactive: false,
        }).addTo(map);
        rangeCircle.bindTooltip(`${rangeKm.toLocaleString()} km range — Global Reach (every landmark is in range)`, { permanent: true, direction: 'top', className: 'range-circle-label' });
    } else {
        // δ < 180°: single white-dashed L.circle around base. ALWAYS base-centered.
        // ALWAYS white. ALWAYS shows reach. At δ approaching 180° the ellipse will
        // visually cover most of the map — that is explicitly Luke-approved per
        // INVARIANTS 3 + 6.
        rangeCircle = L.circle([baseCoords.latitude, baseCoords.longitude], {
            radius: rangeKm * 1000 * marsCorrection,
            color: '#ffffff',
            weight: 2,
            opacity: 0.85,
            fillOpacity: 0.05,
            dashArray: '8, 6',
            interactive: false,
        }).addTo(map);
        rangeCircle.bindTooltip(`${rangeKm.toLocaleString()} km range`, { permanent: true, direction: 'top', className: 'range-circle-label' });
    }

    // Auto-fit map so base + ring are both visible. Solves Luke's "Buggy ring missing"
    // (the antipode ring on the western hemisphere wasn't in his eastern-hemisphere view).
    try {
        if (typeof rangeCircle.getBounds === 'function') {
            const bounds = rangeCircle.getBounds().extend([baseCoords.latitude, baseCoords.longitude]);
            map.fitBounds(bounds, { padding: [40, 40], maxZoom: 4, animate: true });
        } else {
            // Global Reach case: just center on base at a wide zoom so user sees label + global dots.
            map.setView([baseCoords.latitude, baseCoords.longitude], 2, { animate: true });
        }
    } catch (e) { /* fitBounds may throw on degenerate bounds; ignore. */ }

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

// Trace a true geodesic circle on a sphere of given radius as N lat/lon points.
// Angular distance δ = distanceKm / sphereRadiusKm; for each bearing θ in [0,2π):
//   lat = asin(sin(lat0)·cos(δ) + cos(lat0)·sin(δ)·cos(θ))
//   lon = lon0 + atan2(sin(θ)·sin(δ)·cos(lat0), cos(δ) − sin(lat0)·sin(lat))
function geodesicCirclePoints(centerLat, centerLon, distanceKm, sphereRadiusKm, n) {
    const rad = Math.PI / 180;
    const lat0 = centerLat * rad;
    const lon0 = centerLon * rad;
    const delta = distanceKm / sphereRadiusKm; // angular distance in radians
    const pts = [];
    for (let i = 0; i < n; i++) {
        const theta = (2 * Math.PI * i) / n;
        const sinLat = Math.sin(lat0) * Math.cos(delta) +
                       Math.cos(lat0) * Math.sin(delta) * Math.cos(theta);
        const lat = Math.asin(sinLat);
        const lon = lon0 + Math.atan2(
            Math.sin(theta) * Math.sin(delta) * Math.cos(lat0),
            Math.cos(delta) - Math.sin(lat0) * sinLat
        );
        pts.push([lat / rad, lon / rad]);
    }
    return pts;
}

// Bug #1394 ReOpen v2 helper. Walk the closed ring, normalize lons to (-180, 180],
// and break it into one or more open arcs whenever adjacent vertices straddle the
// antimeridian (|Δlon| > 180°). Polylines that span the whole map width otherwise
// render as a horizontal smear connecting the two edges.
function splitRingAtAntimeridian(pts) {
    if (!pts || pts.length < 2) return [];
    const norm = (lon) => {
        let l = lon;
        while (l > 180) l -= 360;
        while (l <= -180) l += 360;
        return l;
    };
    // Append the first vertex at the end so the closing edge is also evaluated.
    const closed = pts.concat([pts[0]]);
    const normalized = closed.map(([lat, lon]) => [lat, norm(lon)]);
    const segments = [];
    let cur = [normalized[0]];
    for (let i = 1; i < normalized.length; i++) {
        const [lat, lon] = normalized[i];
        const prevLon = normalized[i - 1][1];
        if (Math.abs(lon - prevLon) > 180) {
            if (cur.length > 1) segments.push(cur);
            cur = [];
        }
        cur.push([lat, lon]);
    }
    if (cur.length > 1) segments.push(cur);
    return segments;
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
        <div class="map-popup-status ${disc ? 'visited' : 'unexplored'}">${disc ? `${icon('success_check')} VISITED` : `${icon('magnifier_discovery')} UNEXPLORED`}</div>
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

// Update costs for all expedition cards — single bulk request
async function updateAllExpeditionCosts() {
    const cards = $$('.exp-card');
    const entries = [];
    for (const card of cards) {
        const landmarkIndex = parseInt(card.dataset.landmarkIndex);
        const l = !isNaN(landmarkIndex) ? landmarksData[landmarkIndex] : null;
        if (l) entries.push({ card, l });
    }
    if (!entries.length) return;

    try {
        const payload = { items: entries.map(e => ({ distance_km: e.l.distance_km, destination_type: e.l.type })) };
        const resp = await apiPost('/api/expeditions/calculate_costs_bulk', payload);
        if (!resp.success || !Array.isArray(resp.results)) {
            entries.forEach(e => { const el = e.card.querySelector('.expedition-total-cost'); if (el) el.textContent = '--'; });
            return;
        }
        resp.results.forEach((data, i) => {
            const { card, l } = entries[i];
            if (data && data.success) updateCostDisplay(card, data, l);
            else {
                const el = card.querySelector('.expedition-total-cost');
                if (el) el.textContent = 'Error';
            }
        });
        // Bug #1481: reward + cost are async — re-apply an active reward/cost sort now
        // that real per-card values exist (a sort chosen before load saw only 0/--).
        const sel = document.getElementById('expeditionSort');
        if (sel && typeof sortExpeditions === 'function' &&
            (sel.value.startsWith('reward') || sel.value.startsWith('cost'))) {
            sortExpeditions(sel.value);
        }
    } catch {
        entries.forEach(e => { const el = e.card.querySelector('.expedition-total-cost'); if (el) el.textContent = '--'; });
    }
}

function updateCostDisplay(card, data, landmark) {
    const ep = data.expedition_pricing, tp = data.total_pricing;

    // Store cost on landmark for map popup
    landmark._calculatedCost = tp.total_cost_display;
    landmark._canAfford = tp.can_afford;

    // Bug #1481: expose expected-shard midpoint so "Shards: Most/Least Expected" can sort on it.
    if (data.estimated_return) {
        const mid = ((data.estimated_return.low || 0) + (data.estimated_return.high || 0)) / 2;
        card.dataset.reward = String(mid);
        landmark._estimatedReturn = data.estimated_return;
    }

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
                breakdownHtml += `<div style="display: flex; justify-content: space-between; color: var(--color-mars); font-weight: 600;"><span>${icon('warning_alert')} Slow terrain</span><span>-${speedPct}% speed</span></div>`;
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
    map.setView(plotMapLL(l.latitude, l.longitude), 6, { animate: true });

    // Flash the marker
    const marker = expeditionMarkers[idx];
    if (marker) {
        marker.setRadius(16);
        marker.openPopup();
        setTimeout(() => marker.setRadius(8), 2000);
    }
}

