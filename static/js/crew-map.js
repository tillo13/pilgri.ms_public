// ============================================================================
// CREW-MAP.JS - Trail Map, Chart Trail Modal, Crew Selection
// ============================================================================

// #1434: single source of truth for the N/E/S/W trail palette (config.TRAIL_DIR_PALETTE,
// via the #trailPaletteData PAGE_DATA bridge). Map lines, boxes, antipode modal + mission
// list all read TRAIL_DIR so colours/dashes/labels can never drift. The fallback mirrors
// config so a parse miss can't crash the map (scripts are deferred, so the bridge is
// normally present). Direction is encoded by colour + dash + label — never colour alone.
// window-scoped + idempotent so crew-map.js and crew-missions.js (both loaded on /crew)
// share ONE parse without a `const` redeclaration collision.
window.TRAIL_DIR = window.TRAIL_DIR || (function () {
    try {
        const el = document.getElementById('trailPaletteData');
        if (el && el.textContent) return JSON.parse(el.textContent);
    } catch (e) { /* fall through to default */ }
    return {
        N: { color: '#FFFFFF', halo: '#000000', dash: null,       label: 'N CHAIN' },
        E: { color: '#00FFFF', halo: '#000000', dash: '16,8',     label: 'E CHAIN' },
        S: { color: '#FF1493', halo: '#000000', dash: '4,6',      label: 'S CHAIN' },
        W: { color: '#000000', halo: '#FFFFFF', dash: '12,4,4,4', label: 'W CHAIN' },
    };
})();
const TRAIL_DIR = window.TRAIL_DIR;

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

    // v3 (#1414) — show ONLY what the captain has actually built (the "plus sign" of
    // traveled distance), plus a throbbing antipode beacon. NO ghost/unbuilt lines.
    // #1434: colours/halos/dashes come from the shared TRAIL_DIR palette so the lines
    // ALWAYS match the Top Trails boxes + legend.
    const dirColor = { N: TRAIL_DIR.N.color, E: TRAIL_DIR.E.color, S: TRAIL_DIR.S.color, W: TRAIL_DIR.W.color };
    const dirHalo  = { N: TRAIL_DIR.N.halo,  E: TRAIL_DIR.E.halo,  S: TRAIL_DIR.S.halo,  W: TRAIL_DIR.W.halo };

    // Per direction: draw the line through every built segment + a marker DOT at each
    // traveled-through landmark. The first marker in each direction is the first NSEW
    // location (e.g., for N it's the first hop from base going north). No ghost / unbuilt.
    if (window.allChainSegments && window.allChainSegments.length) {
        const byDir = { N: [], E: [], S: [], W: [] };
        window.allChainSegments.forEach(s => { if (byDir[s.direction]) byDir[s.direction].push(s); });
        Object.keys(byDir).forEach(d => byDir[d].sort((a, b) => a.segment_index - b.segment_index));

        for (const d of ['N', 'E', 'S', 'W']) {
            const segs = byDir[d];
            const color = dirColor[d];
            const halo = dirHalo[d];
            // Walk the chain accumulating built portions. Drop a marker at each fully-built
            // to_landmark. Stop at the first unbuilt segment (or partial-built tip).
            let pts = [[baseCoords.latitude, baseCoords.longitude]];
            const markerStops = [];
            let accumulatedKm = 0;
            const totalChainKm = segs.reduce((sum, s) => sum + (parseFloat(s.segment_distance_km) || 0), 0);
            for (const s of segs) {
                const segDist = parseFloat(s.segment_distance_km) || 0;
                const built = parseFloat(s.km_built) || 0;
                if (built <= 0 || segDist <= 0) break;
                if (s.to_latitude == null || s.to_longitude == null) break;
                if (built >= segDist - 1e-6) {
                    pts.push([s.to_latitude, s.to_longitude]);
                    markerStops.push({ lat: s.to_latitude, lon: s.to_longitude, name: s.to_landmark, segIdx: s.segment_index, segDist });
                    accumulatedKm += segDist;
                } else {
                    // Partial — interpolate, mark as the current "in-progress" tip, stop.
                    const frac = built / segDist;
                    const fromCoords = pts[pts.length - 1];
                    const midLat = fromCoords[0] + (s.to_latitude - fromCoords[0]) * frac;
                    const midLon = fromCoords[1] + (s.to_longitude - fromCoords[1]) * frac;
                    pts.push([midLat, midLon]);
                    accumulatedKm += built;
                    markerStops.push({
                        lat: midLat, lon: midLon, name: `${s.to_landmark} (in progress)`,
                        segIdx: s.segment_index, segDist, partial: true,
                        partialPct: (built / segDist * 100).toFixed(1) + '%'
                    });
                    break;
                }
            }
            if (pts.length < 2) continue;
            const kmLeft = Math.max(0, totalChainKm - accumulatedKm);
            // #1434: per-direction dash so the 4 lines differ by SHAPE, not colour alone
            // (both users are colourblind). Solid halo underneath keeps the dashed colour line legible.
            const dDash = TRAIL_DIR[d].dash || undefined;
            // Line: halo underneath + bright color on top
            trailMapMarkers.push(L.polyline(pts, { color: halo, weight: 7, opacity: 0.55 }).addTo(crewTrailMap));
            trailMapMarkers.push(L.polyline(pts, { color: color, weight: 4, opacity: 1.0, dashArray: dDash }).addTo(crewTrailMap));
            // #1434: a permanent N/E/S/W label at the built tip so direction is also conveyed by TEXT.
            const tip = pts[pts.length - 1];
            trailMapMarkers.push(
                L.marker(tip, {
                    icon: L.divIcon({
                        className: 'trail-dir-label',
                        html: `<span style="background:${halo};color:${color};border:1px solid ${color};border-radius:3px;padding:0 3px;font-size:10px;font-weight:700;">${d}</span>`,
                        iconSize: null,
                    }),
                    interactive: false,
                }).addTo(crewTrailMap)
            );
            // Dot at every traveled-through landmark
            markerStops.forEach((stop, i) => {
                const isCurrent = !!stop.partial;
                const marker = L.circleMarker([stop.lat, stop.lon], {
                    radius: isCurrent ? 7 : 5,
                    fillColor: color,
                    color: halo,
                    weight: 2,
                    fillOpacity: isCurrent ? 0.95 : 0.85
                }).addTo(crewTrailMap);
                const tooltip = isCurrent
                    ? `<strong>${d} CHAIN — current build</strong><br>${stop.name}<br>seg ${stop.segIdx} ${stop.partialPct} built<br>${kmLeft.toFixed(0)} km left to antipode`
                    : `<strong>${d} CHAIN — passed through</strong><br>${stop.name}<br>seg ${stop.segIdx} complete<br>${kmLeft.toFixed(0)} km left to antipode`;
                marker.bindTooltip(tooltip, { direction: 'top' });
                trailMapMarkers.push(marker);
            });
        }
    }

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
        const labelText = (antipodeName || 'ANTIPODE').toUpperCase();
        // Sonar-ping rings — TWO outer rings at different phases so a pulse is always visible.
        // We grow each ring from radius 12 → 36, fade opacity, then reset, with offset timing.
        const makeRing = () => L.circleMarker(antipodeCoords, {
            radius: 12,
            fillColor: '#fbbf24',
            color: '#fbbf24',
            weight: 3,
            opacity: 0.95,
            fillOpacity: 0.0,
            interactive: false
        }).addTo(crewTrailMap);
        const ringA = makeRing();
        const ringB = makeRing();
        trailMapMarkers.push(ringA);
        trailMapMarkers.push(ringB);
        // Animate via setInterval — direct radius/opacity changes (more reliable than CSS on SVG)
        const animateRing = (ring, phase) => {
            // phase 0..1
            const r = 12 + phase * 28;
            const o = 0.95 * (1 - phase);
            ring.setRadius(r);
            ring.setStyle({ opacity: o });
        };
        let t = 0;
        if (window._antipodePulseTimer) clearInterval(window._antipodePulseTimer);
        window._antipodePulseTimer = setInterval(() => {
            t = (t + 0.025) % 1.0;
            animateRing(ringA, t);
            animateRing(ringB, (t + 0.5) % 1.0);
        }, 50);
        // Inner solid marker (clickable, always at fixed size)
        const beacon = L.circleMarker(antipodeCoords, {
            radius: 11,
            fillColor: '#ec7427',
            color: '#ffffff',
            weight: 3,
            opacity: 1,
            fillOpacity: 1
        }).addTo(crewTrailMap);
        beacon.bindTooltip(`◆ ${labelText} — antipode (click for chain progress)`, { direction: 'top', offset: [0, -8] });
        beacon.on('click', () => openAntipodeModal(antipodeName));
        trailMapMarkers.push(beacon);
        // Permanent label below the beacon so it's always identifiable
        const label = L.marker(antipodeCoords, {
            icon: L.divIcon({
                className: '',
                html: `<div style="white-space:nowrap;font-size:11px;font-weight:700;color:#fff;background:rgba(0,0,0,0.85);padding:2px 8px;border-radius:4px;border:1px solid #ec7427;text-transform:uppercase;letter-spacing:0.5px;text-shadow:0 1px 2px rgba(0,0,0,0.9);transform:translate(-50%, 14px);">◆ ${labelText}</div>`,
                iconSize: [0, 0],
                iconAnchor: [0, 0]
            }),
            interactive: false,
            zIndexOffset: 1000
        }).addTo(crewTrailMap);
        trailMapMarkers.push(label);
    } else if (window._antipodePulseTimer) {
        clearInterval(window._antipodePulseTimer);
        window._antipodePulseTimer = null;
    }

    // v3: auto-fit to base + BUILT segment tips only (NOT the antipode — it's literally on the
    // far side of the planet, including it forces Mars to render tiled multiple times).
    // The antipode beacon remains in the data; users can zoom out or click "Fly to Antipode"
    // (button below the map) to pan to it.
    const points = [[baseCoords.latitude, baseCoords.longitude]];
    if (window.allChainSegments) {
        const byDir = { N: [], E: [], S: [], W: [] };
        window.allChainSegments.forEach(s => { if (byDir[s.direction]) byDir[s.direction].push(s); });
        Object.keys(byDir).forEach(d => byDir[d].sort((a, b) => a.segment_index - b.segment_index));
        for (const d of ['N','E','S','W']) {
            for (const s of byDir[d] || []) {
                if ((parseFloat(s.km_built) || 0) > 0 && s.to_latitude != null) {
                    points.push([s.to_latitude, s.to_longitude]);
                }
            }
        }
    }
    // Skip auto-recentering once the captain has flown to the antipode — otherwise the 30s
    // poll yanks them back to base mid-read.
    if (!crewTrailMap._suppressAutoRecenter) {
        if (points.length > 1) {
            crewTrailMap.fitBounds(L.latLngBounds(points), { padding: [60, 60], maxZoom: 5 });
        } else {
            crewTrailMap.setView([baseCoords.latitude, baseCoords.longitude], 4);
        }
    }
    // Stash the antipode coords on the map for the "Fly to Antipode" button below
    crewTrailMap._antipodeCoords = antipodeCoords;
    crewTrailMap._antipodeName = antipodeName;
}

// Pan the map smoothly to the captain's antipode (called by the "Fly to Antipode" button).
// Suppresses the 30s poll's auto-recenter so the view stays put, then opens the antipode modal
// once the flight finishes — same UX as clicking the throbbing beacon directly.
window.flyToAntipode = function() {
    if (!crewTrailMap || !crewTrailMap._antipodeCoords) return;
    crewTrailMap._suppressAutoRecenter = true;
    crewTrailMap.flyTo(crewTrailMap._antipodeCoords, 5, { duration: 1.5 });
    crewTrailMap.once('moveend', () => {
        if (typeof window.openAntipodeModal === 'function') {
            window.openAntipodeModal(crewTrailMap._antipodeName);
        }
    });
};

// Pan back to the captain's base — clears the suppression flag so polling resumes normal centering.
window.flyToBase = function() {
    if (!crewTrailMap) return;
    const baseCoords = window.baseCoords || { latitude: -4.5, longitude: 137.4 };
    crewTrailMap._suppressAutoRecenter = false;
    crewTrailMap.flyTo([baseCoords.latitude, baseCoords.longitude], 4, { duration: 1.5 });
};

// v3 (#1414): click handler for the throbbing antipode beacon.
// Pulls live data from /api/trails/chains and opens a MarsModal with all 4 chain progress.
window.openAntipodeModal = async function(antipodeName) {
    if (typeof MarsModal === 'undefined') return;
    // #1434: colours + labels from the shared TRAIL_DIR palette so the antipode modal
    // matches the map lines, boxes + legend.
    const dirStyle = {
        N: { color: TRAIL_DIR.N.color, label: TRAIL_DIR.N.label, desc: 'via the North Pole' },
        E: { color: TRAIL_DIR.E.color, label: TRAIL_DIR.E.label, desc: 'east through the equator' },
        S: { color: TRAIL_DIR.S.color, label: TRAIL_DIR.S.label, desc: 'via the South Pole' },
        W: { color: TRAIL_DIR.W.color, label: TRAIL_DIR.W.label, desc: 'west through the equator' }
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
    // Chain prestige tiers (must mirror CHAIN_PRESTIGE_TIERS in utilities/postgres/trails/chains.py)
    const PRESTIGE = [
        { km: 0,     name: 'none' },
        { km: 1000,  name: 'Surveying' },
        { km: 5000,  name: 'Marked' },
        { km: 11000, name: 'Complete' },
    ];
    const fmt = (n) => Number(n).toLocaleString(undefined, { maximumFractionDigits: 1 });
    const nextTier = (built) => {
        for (const t of PRESTIGE) { if (built < t.km) return t; }
        return null;
    };

    // Mars-radius haversine for the "X km away" line — matches utilities/postgres/trails/chains.py
    const marsHaversine = (lat1, lon1, lat2, lon2) => {
        const R = 3389.5; // km, Mars mean radius
        const toRad = (x) => x * Math.PI / 180;
        const dLat = toRad(lat2 - lat1), dLon = toRad(lon2 - lon1);
        const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
        return 2 * R * Math.asin(Math.min(1, Math.sqrt(a)));
    };
    const baseC = window.baseCoords || { latitude: -4.5, longitude: 137.4 };
    const antC = (crewTrailMap && crewTrailMap._antipodeCoords) ? crewTrailMap._antipodeCoords : null;
    const antDist = antC ? marsHaversine(baseC.latitude, baseC.longitude, antC[0], antC[1]) : null;
    const baseStr = `(${Number(baseC.latitude).toFixed(2)}°, ${Number(baseC.longitude).toFixed(2)}°)`;
    const antStr = antC ? `(${Number(antC[0]).toFixed(2)}°, ${Number(antC[1]).toFixed(2)}°)` : '—';

    let body = `<div class="mm-card-accent" style="text-align:center;">
        <div class="mm-section-label">Antipode</div>
        <div style="font-size:18px; font-weight:700; color:var(--text-primary);">${antipodeName || '—'}</div>
        <div style="font-size:11px; color:var(--text-muted); margin-top:4px;">All 4 of your chains terminate here</div>
    </div>`;
    body += `<div style="font-size:11px;color:var(--text-muted);margin:8px 2px 4px;line-height:1.55;">
        <div style="margin-bottom:6px;"><strong style="color:var(--text-primary);">What is an antipode?</strong>
        The point on Mars directly opposite your base — the furthest reachable landmark from where you stand.
        Mathematically it's <code>(−lat, lon ± 180°)</code>; in-game it's the named landmark with the largest
        great-circle distance from your base, scanned across every Mars landmark
        (<code>find_antipode_landmark()</code> in <code>utilities/postgres/trails/chains.py</code>).</div>
        <div style="margin-bottom:6px;"><strong style="color:var(--text-primary);">Why ${antipodeName || 'this landmark'}?</strong>
        Your base is at <strong>${baseStr}</strong>. We computed the haversine distance (Mars radius 3,389.5 km)
        from your base to every landmark and picked the maximum: <strong>${antipodeName || '—'}</strong> at
        <strong>${antStr}</strong>${antDist ? ` — <strong>${antDist.toFixed(0)} km</strong> away.` : '.'}
        Every captain gets their own antipode based on where their base sits.</div>
        <div><strong style="color:var(--text-primary);">How chain % is computed:</strong>
        sum of <code>km_built</code> across every segment ÷ sum of <code>segment_distance_km</code>.
        Each segment is one trail leg; km come from Captain + Scientist + ARIA + drones + robots.</div>
    </div>`;
    body += `<div class="grid" style="grid-template-columns: 1fr; gap: 8px;">`;
    for (const d of ['N', 'E', 'S', 'W']) {
        const info = (chains && chains[d]) || {};
        const pct = info.percent_complete || 0;
        const total = info.total_km || 0;
        const built = info.km_built_total || 0;
        const segs = info.completed_segments || 0;
        const totalSegs = info.total_segments || 0;
        const tier = info.prestige_tier || 'none';
        const nu = info.next_unbuilt || null;
        const isActive = (d === activeDir);
        const ds = dirStyle[d];
        const textColor = (d === 'W') ? '#000000' : '#ffffff';
        const activeBadge = isActive ? `<span style="background:${ds.color};color:${textColor};padding:2px 6px;border-radius:3px;font-size:10px;font-weight:700;margin-left:6px;border:1px solid rgba(255,255,255,0.3);">● ACTIVE</span>` : '';
        const nt = nextTier(built);
        const tierLine = nt
            ? `<span style="opacity:.85">Prestige: <strong>${tier}</strong></span> · next: <strong>${nt.name}</strong> at ${fmt(nt.km)} km <span style="opacity:.7">(${fmt(Math.max(0, nt.km - built))} km to go)</span>`
            : `<span style="opacity:.85">Prestige: <strong>${tier}</strong></span> · max tier reached`;

        let segBlock = '';
        if (nu) {
            const segPct = nu.segment_distance_km ? (Number(nu.km_built || 0) / Number(nu.segment_distance_km) * 100) : 0;
            const cap = Number(nu.captain_km || 0), sci = Number(nu.scientist_km || 0), ar = Number(nu.aria_km || 0);
            const dr = Number(nu.drone_km || 0), ro = Number(nu.robot_km || 0);
            segBlock = `<div style="margin-top:6px;padding:6px 8px;background:rgba(255,255,255,0.04);border-radius:4px;font-size:11px;line-height:1.55;">
                <div style="opacity:.9;"><strong>Building seg ${nu.segment_index}/${totalSegs}:</strong> ${nu.from_landmark} → ${nu.to_landmark}</div>
                <div style="opacity:.85;">${fmt(nu.km_built)} / ${fmt(nu.segment_distance_km)} km (${segPct.toFixed(1)}%) · tier: <strong>${nu.tier || 'none'}</strong></div>
                <div style="opacity:.7;font-size:10px;">Cap ${fmt(cap)} · Sci ${fmt(sci)} · ARIA ${fmt(ar)} · Drones ${fmt(dr)} · Robots ${fmt(ro)}</div>
            </div>`;
        }

        body += `<div style="border-left: 4px solid ${ds.color}; padding: 8px 12px; background: rgba(0,0,0,0.25); border-radius: 0 6px 6px 0;">
            <div style="font-weight:600; color: ${ds.color === '#ffffff' ? '#fff' : ds.color}; font-size: 13px;">${ds.label}${activeBadge}</div>
            <div style="font-size: 11px; opacity: 0.8; margin: 2px 0;">${ds.desc}</div>
            <div style="font-size: 12px;line-height:1.55;">
                <div><strong>${fmt(built)}</strong> km built ÷ <strong>${fmt(total)}</strong> km total = <strong>${pct.toFixed(2)}%</strong></div>
                <div style="opacity:.85;">Segments: <strong>${segs}/${totalSegs}</strong> complete · avg leg ≈ ${totalSegs ? fmt(total / totalSegs) : '0'} km</div>
                <div style="font-size: 11px;opacity:.85;margin-top:2px;">${tierLine}</div>
            </div>
            <div style="background: rgba(255,255,255,0.08); height: 4px; border-radius: 2px; margin-top: 4px; overflow: hidden;">
                <div style="background: ${ds.color}; height: 100%; width: ${Math.min(100, pct)}%; transition: width 0.3s;"></div>
            </div>
            ${segBlock}
        </div>`;
    }
    body += `</div>`;
    body += `<div style="font-size:10.5px;color:var(--text-muted);margin-top:10px;line-height:1.55;opacity:.85;">
        <strong style="color:var(--text-primary);">Per-segment tiers</strong> (by % built):
        Path 25% · Road 50% · Highway 75% · Superhighway 100%.
        <strong style="color:var(--text-primary);">Chain prestige</strong> (by total km in that direction):
        Surveying 1,000 · Marked 5,000 · Complete 11,000.
    </div>`;
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

    // #1434: read the shared TRAIL_DIR palette (was a duplicate hardcoded copy). NOTE: this
    // function (drawGhostChainRoutes) is currently DEAD — defined, called nowhere — but kept
    // (CLAUDE.md: ask before removing). Reading the shared palette means it can't reintroduce
    // colour drift if it's ever rewired.
    const dirColor = { N: TRAIL_DIR.N.color, E: TRAIL_DIR.E.color, S: TRAIL_DIR.S.color, W: TRAIL_DIR.W.color };
    const dirDash  = { N: TRAIL_DIR.N.dash,  E: TRAIL_DIR.E.dash,  S: TRAIL_DIR.S.dash,  W: TRAIL_DIR.W.dash };
    const dirHalo  = { N: TRAIL_DIR.N.halo,  E: TRAIL_DIR.E.halo,  S: TRAIL_DIR.S.halo,  W: TRAIL_DIR.W.halo };
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
// Bug #1303: previously summed only captain+scientist+aria, dropping drone_km
// and robot_km on the floor — Luke caught it because the 3 visible cards
// always summed to 100%. Now sums all 5 sources so the percentages and the
// "Your Total Trail Progress" km value reflect every contributor.
function updateCrewTrailContributions() {
    // Sum up all km built by each crew member across all trails
    let captainTotal = 0, scientistTotal = 0, ariaTotal = 0, droneTotal = 0, robotTotal = 0;
    nearbyTrails.forEach(t => {
        captainTotal += t.captain_km || 0;
        scientistTotal += t.scientist_km || 0;
        ariaTotal += t.aria_km || 0;
        droneTotal += t.drone_km || 0;
        robotTotal += t.robot_km || 0;
    });
    const grandTotal = captainTotal + scientistTotal + ariaTotal + droneTotal + robotTotal;

    // Update crew contribution displays. drone-/robot-trail-contrib are only in
    // the DOM when the captain has the corresponding source (template gates).
    const captainEl   = document.getElementById('captain-trail-contrib');
    const scientistEl = document.getElementById('scientist-trail-contrib');
    const ariaEl      = document.getElementById('aria-trail-contrib');
    const droneEl     = document.getElementById('drone-trail-contrib');
    const robotEl     = document.getElementById('robot-trail-contrib');

    const setPct = (el, total) => {
        if (!el) return;
        if (grandTotal > 0) {
            el.textContent = `${(total / grandTotal * 100).toFixed(1)}% contrib`;
        } else {
            el.textContent = 'No trails yet';
        }
    };
    setPct(captainEl, captainTotal);
    setPct(scientistEl, scientistTotal);
    setPct(ariaEl, ariaTotal);
    setPct(droneEl, droneTotal);
    setPct(robotEl, robotTotal);

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
    // #1434: colours/dashes/halos from the shared TRAIL_DIR palette so the Top Trails boxes
    // ALWAYS match the map lines + legend. (Direction also shown by the dash + the 'D CHAIN'
    // label + the arrow icon below — never colour alone.)
    const dirColor = { N: TRAIL_DIR.N.color, E: TRAIL_DIR.E.color, S: TRAIL_DIR.S.color, W: TRAIL_DIR.W.color };
    const dirDash  = { N: TRAIL_DIR.N.dash,  E: TRAIL_DIR.E.dash,  S: TRAIL_DIR.S.dash,  W: TRAIL_DIR.W.dash };
    const dirHalo  = { N: TRAIL_DIR.N.halo,  E: TRAIL_DIR.E.halo,  S: TRAIL_DIR.S.halo,  W: TRAIL_DIR.W.halo };
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

    // Bug #1430: removed loadTrailBonuses() call — scanner/consumable speed-bonus
    // UI was deleted along with /api/trail/consumables endpoint.

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
            // Bug #1430: scanner+consumable bonuses removed. Trip duration is a
            // server-driven constant for now (15 min baseline × stat × EVA suit).
            const estimatedDuration = 15;
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
        // Bug #1430: consumable burn-for-bonus loop removed — no more consumable_id.
        const data = await apiPost('/api/trail/build', {
            destination_name: trailName,
            worker_type: member,
        });

        if (data.success) {
            // Show toast with chain routing info
            const routeDesc = data.from_landmark && data.from_landmark !== 'HOME'
                ? `${data.from_landmark} → ${trailName}`
                : trailName;
            const msg = `${memberName} departed! Building ${routeDesc} ~${data.km_to_add.toFixed(3)} km in ${data.duration_minutes} min`;
            showToast?.(msg, 'success');
            loadCrewMissions(); // Refresh to show countdown
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
            // Bug #21 Deploy C: stat-up popups from crew mission complete
            if (typeof processStatEvents === 'function') processStatEvents(data);
            loadCrewMissions(); // Refresh
        } else {
            showToast?.(data.error || 'Failed to claim mission', 'error');
        }
    } catch (e) {
        showToast?.('Network error', 'error');
    }
}

// Store base coords for map
