// ============================================================================
// EXPEDITIONS-LAUNCH.JS - Launch Flow, Recall, Completion, Rewards
// ============================================================================

// Store current landmark for modal launch
let pendingLaunchLandmark = null;

async function launchExpedition(l) {
    pendingLaunchLandmark = l;
    showPreLaunchModal(l);
}

async function showPreLaunchModal(l) {
    // Fetch preview data
    try {
        const data = await apiPost('/api/expedition/preview', { distance_km: l.distance_km, destination_type: l.type, destination_name: l.name });
        if (!data.success) { showToast(data.error || 'Preview failed', 'error'); return; }
        renderPreLaunchModal(l, data);
    } catch { showToast('Network error loading preview', 'error'); }
}

function renderPreLaunchModal(l, preview) {
    const vehicles = preview.vehicles || [];
    const firstAvailable = vehicles.find(v => v.available) || vehicles[0];
    const selectedType = firstAvailable ? firstAvailable.vehicle_type : 'rover';
    const cap = preview.captain;
    const sci = preview.scientist;
    const sb = preview.speed_breakdown;

    let body = `
        <!-- Destination -->
        <div style="text-align:center; margin-bottom:16px;">
            <div style="font-size:13px; color:var(--text-muted);">${l.type} • ${l.distance_km} km</div>
            <div style="font-size:10px; margin-top:4px; display:flex; gap:12px; justify-content:center;">
                ${l.link ? `<a href="${l.link}" target="_blank" rel="noopener" style="color:var(--text-muted); opacity:0.7; text-decoration:none;">NASA ↗</a>` : ''}
                <a href="/brainstorm/trail-network" target="_blank" style="color:var(--text-muted); opacity:0.7; text-decoration:none;">Trail Roadmap ↗</a>
            </div>
        </div>
        <!-- Vehicle Selector -->
        <div class="mm-section-label">Select Vehicle</div>
        <div id="modal-vehicle-selector" style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:16px;">
            ${vehicles.map(v => `
                <button class="modal-vehicle-btn ${v.vehicle_type === selectedType ? 'selected' : ''} ${!v.available ? 'disabled' : ''}"
                    data-type="${v.vehicle_type}" ${!v.available ? 'disabled' : ''}
                    onclick="selectModalVehicle('${v.vehicle_type}')"
                    style="flex:1; min-width:100px; padding:8px; border-radius:8px; border:2px solid ${v.vehicle_type === selectedType ? 'var(--color-mars)' : 'rgba(255,255,255,0.15)'}; background:${v.vehicle_type === selectedType ? 'rgba(239,68,68,0.15)' : 'rgba(255,255,255,0.05)'}; color:${!v.available ? 'var(--text-muted)' : 'var(--text-primary)'}; cursor:${v.available ? 'pointer' : 'not-allowed'}; text-align:center;">
                    ${v.image_url ? `<img src="${v.image_url}" alt="" style="width:36px; height:36px; border-radius:6px; object-fit:cover; margin-bottom:4px; ${!v.available ? 'opacity:0.4;' : ''}">` : ''}
                    <div style="font-size:13px; font-weight:600;">${v.vehicle_type.charAt(0).toUpperCase() + v.vehicle_type.slice(1)}</div>
                    <div style="font-size:11px; opacity:0.8;">Lv${v.level} • ${v.cargo} cargo</div>
                    ${!v.available ? `<div style="font-size:10px; color:var(--color-mars);">${v.unavailable_reason || 'In use'}</div>${v.unavailable_reason && v.unavailable_reason.includes('range') ? `<a href="/depot?upgrade=${v.vehicle_type}" onclick="event.stopPropagation(); window.location='/depot?upgrade=${v.vehicle_type}';" style="font-size:9px; color:var(--color-sepolia); text-decoration:none; pointer-events:auto; position:relative; z-index:10;">Upgrade range →</a>` : ''}` : ''}
                </button>
            `).join('')}
        </div>
        <!-- Trip Estimate -->
        <div id="modal-trip-estimate" style="margin-bottom:16px;">${renderTripEstimate(firstAvailable)}</div>
        <!-- Speed Breakdown -->
        <div id="modal-speed-stack">${renderSpeedStack(firstAvailable, sb)}</div>
        <!-- Bug #1329: Research Tech Bonuses — list every tech multiplier/bonus that applies to this expedition -->
        ${renderTechBonuses(preview.tech_bonuses)}
        <!-- Captain -->
        <div class="mm-section-label">Captain</div>
        <div class="mm-person">
            ${cap.image_url ? `<img src="${cap.image_url}" alt="" class="mm-person-avatar">` : ''}
            <div style="flex:1; font-size:12px;">
                <div style="font-weight:600; margin-bottom:4px;">${cap.name}</div>
                <div style="display:grid; grid-template-columns:1fr auto; gap:3px 8px;">
                    <span>Logistics</span><span style="text-align:right; color:var(--color-success);">${cap.logistics} → ×${cap.logistics_mult} speed</span>
                    <span>Exploration</span><span style="text-align:right; ${cap.exploration > 0 ? 'color:var(--color-success)' : 'opacity:0.5'};">${cap.exploration} → +${Math.round(cap.exploration)}% value</span>
                    <span>Strategy</span><span style="text-align:right; ${cap.strategy > 0 ? 'color:var(--color-success)' : 'opacity:0.5'};">${cap.strategy} → +${Math.round(cap.strategy / 2)}% rare</span>
                    <span>Leadership</span><span style="text-align:right; ${cap.leadership > 0 ? 'color:var(--color-success)' : 'opacity:0.5'};">${cap.leadership} → +${Math.round(cap.leadership / 10)}% finds</span>
                    <span>Charisma</span><span style="text-align:right; ${cap.charisma > 0 ? 'color:var(--color-success)' : 'opacity:0.5'};">${cap.charisma} → -${Math.round(cap.charisma / 5)}% cost</span>
                </div>
            </div>
        </div>`;

    if (sci) {
        body += `<div class="mm-section-label">Colony Scientist</div>
        <div class="mm-person">
            ${sci.image_url ? `<img src="${sci.image_url}" alt="" class="mm-person-avatar">` : ''}
            <div style="flex:1; font-size:12px;">
                <div style="font-weight:600; margin-bottom:4px;">${sci.name} <span style="opacity:0.6; font-weight:400;">"${sci.specialty}"</span></div>
                <div style="display:grid; grid-template-columns:1fr auto; gap:3px 8px;">
                    <span>Navigation</span><span style="text-align:right; ${sci.nav_mult > 1 ? 'color:var(--color-success)' : 'opacity:0.5'};">${sci.stats.navigation}/50 → ×${sci.nav_mult} speed</span>
                    <span>Analysis</span><span style="text-align:right; ${sci.stats.analysis > 0 ? 'color:var(--color-success)' : 'opacity:0.5'};">${sci.stats.analysis}/50 → +${Math.round(sci.stats.analysis / 2)}% value</span>
                    <span>Geology</span><span style="text-align:right; ${sci.stats.geology > 0 ? 'color:var(--color-success)' : 'opacity:0.5'};">${sci.stats.geology}/50 → +${Math.round(sci.stats.geology)}% minerals</span>
                    <span>Engineering</span><span style="text-align:right; ${sci.stats.engineering >= 10 ? 'color:var(--color-success)' : 'opacity:0.5'};">${sci.stats.engineering}/50 → +${Math.floor(sci.stats.engineering / 10)} cargo</span>
                </div>
            </div>
        </div>`;
    }

    if (preview.fleet_status.length > 0) {
        body += `<div class="mm-section-label">Fleet Status (${preview.slots_used}/${preview.max_slots})</div>`;
        body += preview.fleet_status.map(f => `
            <div class="mm-kv"><span class="mm-kv-label">${f.vehicle_type.charAt(0).toUpperCase() + f.vehicle_type.slice(1)} → ${f.destination}</span><span class="mm-kv-value">${f.status}</span></div>
        `).join('');
    }

    const footer = `<button id="modal-launch-btn" class="btn mm-btn-full" onclick="confirmExpeditionLaunch()"
        style="background:var(--color-mars); color:white; ${!firstAvailable || !firstAvailable.available ? 'opacity:0.4; cursor:not-allowed;' : 'cursor:pointer;'}"
        ${!firstAvailable || !firstAvailable.available ? 'disabled' : ''}>
        ${!firstAvailable || !firstAvailable.available ? 'No vehicle in range' : `Deploy ${selectedType.charAt(0).toUpperCase() + selectedType.slice(1)}`}
    </button>`;

    MarsModal.show({
        title: l.link ? `<a href="${l.link}" target="_blank" rel="noopener" style="color:var(--text-primary); text-decoration:none; border-bottom:1px dashed rgba(255,255,255,0.3);">${l.name} ↗</a>` : l.name,
        width: 'md',
        body, footer
    });
    // Set title as HTML since it may contain a link
    if (l.link) {
        const titleEl = document.querySelector('.mm-title');
        if (titleEl) titleEl.innerHTML = `<a href="${l.link}" target="_blank" rel="noopener" style="color:var(--text-primary); text-decoration:none; border-bottom:1px dashed rgba(255,255,255,0.3);">${l.name} ↗</a>`;
    }
    window._previewData = preview;
    window._estimatedReturn = l._estimatedReturn || null;
}

function renderTripEstimate(vehicle) {
    if (!vehicle) return '<div style="font-size:13px; color:var(--text-muted);">No vehicle available</div>';
    const est = window._estimatedReturn;
    const returnHtml = est ? `
        <div style="text-align:center; margin-top:-4px; margin-bottom:8px;">
            <span style="font-size:13px; color:var(--color-success); font-weight:600;">${Math.round(est.low).toLocaleString()} - ${Math.round(est.high).toLocaleString()} shards</span>
            <span style="font-size:10px; color:var(--text-muted); display:block; margin-top:2px;">estimated return (claim finds, then extract)</span>
        </div>` : '';
    return `
        <div class="mm-section-label">Trip Estimate</div>
        <div class="mm-stats mm-stats-3">
            <div class="mm-stat" style="text-align:center;"><div class="mm-stat-value">${vehicle.round_trip_days.toFixed(1)}</div><div class="mm-stat-label">Days RT</div></div>
            <div class="mm-stat" style="text-align:center;"><div class="mm-stat-value">${vehicle.cargo}</div><div class="mm-stat-label">Cargo</div></div>
            <div class="mm-stat" style="text-align:center;"><div class="mm-stat-value">${vehicle.effective_speed_kmh}</div><div class="mm-stat-label">km/h</div></div>
        </div>${returnHtml}`;
}

// Bug #1329: render the Research Tech Bonuses section — the tech multipliers
// are applied server-side (preview.py) but were never shown in the modal. This
// only renders if at least one bonus is non-trivial, to keep the modal quiet
// for captains with no research completed yet.
function renderTechBonuses(tb) {
    if (!tb) return '';
    const rows = [];
    if (tb.speed_mult > 1) rows.push(['Expedition Speed', `×${tb.speed_mult}`]);
    if (tb.cargo_mult > 1) rows.push(['Cargo Capacity', `×${tb.cargo_mult}`]);
    if (tb.fuel_cost_mult && tb.fuel_cost_mult < 1) rows.push(['Fuel Cost', `×${tb.fuel_cost_mult} (${Math.round((1 - tb.fuel_cost_mult) * 100)}% cheaper)`]);
    if (tb.discovery_chance_bonus > 0) rows.push(['Discovery Chance', `+${Math.round(tb.discovery_chance_bonus * 100)}%`]);
    if (tb.legendary_chance_bonus > 0) rows.push(['Legendary Chance', `+${Math.round(tb.legendary_chance_bonus * 100)}%`]);
    if (tb.discovery_value_mult > 1) rows.push(['Discovery Value', `×${tb.discovery_value_mult}`]);
    if (!rows.length) return '';
    return `
        <div class="mm-section-label">Research Tech Bonuses</div>
        <div style="font-size:12px; display:grid; grid-template-columns:1fr auto; gap:4px 12px; margin-bottom:16px;">
            ${rows.map(([label, val]) => `
                <span>${label}</span>
                <span style="text-align:right; color:var(--color-success);">${val}</span>
            `).join('')}
        </div>`;
}

function renderSpeedStack(vehicle, baseBreakdown) {
    // Use vehicle-specific values when available, fall back to base breakdown
    const vehicleMult = vehicle ? vehicle.speed_mult : baseBreakdown.vehicle_mult;
    const effectiveSpeed = vehicle ? vehicle.effective_speed_kmh : baseBreakdown.effective_speed_kmh;
    const terrainMult = vehicle && vehicle.terrain_speed_mult != null ? vehicle.terrain_speed_mult : baseBreakdown.terrain_speed_mult;
    const terrainName = vehicle && vehicle.terrain_name ? vehicle.terrain_name : baseBreakdown.terrain_name;
    const sb = baseBreakdown;
    const segments = sb.segments || [];
    const hasCompounding = sb.has_segment_compounding && segments.length > 1;

    let html = `
        <div class="mm-section-label">Speed Stack</div>
        <div style="font-size:12px; display:grid; grid-template-columns:1fr auto; gap:4px 12px; margin-bottom:16px;">
            <span>Base Speed</span><span style="text-align:right;">${sb.base_speed} km/h</span>
            <span>Vehicle ×</span><span style="text-align:right; color:var(--color-success);">${vehicleMult}x</span>
            <span>Captain Logistics ×</span><span style="text-align:right; color:var(--color-success);">${sb.captain_logistics_mult}x</span>
            <span>Scientist Nav ×</span><span style="text-align:right; ${sb.scientist_nav_mult > 1 ? 'color:var(--color-success)' : 'opacity:0.5'};">${sb.scientist_nav_mult}x</span>
            <span>Research Tech ×</span><span style="text-align:right; ${sb.tech_speed_mult > 1 ? 'color:var(--color-success)' : 'opacity:0.5'};">${sb.tech_speed_mult != null ? sb.tech_speed_mult : 1}x</span>
            <span>Trail${sb.trail_level && sb.trail_level !== 'none' ? ' (' + sb.trail_level + ')' : ''}${hasCompounding ? ' <span style="font-size:9px; color:var(--color-sepolia);">⚡</span>' : ''}</span>
            <span style="text-align:right; ${sb.trail_speed_mult > 1 ? 'color:var(--color-success)' : 'opacity:0.5'};">${sb.trail_speed_mult}x${sb.trail_trip_count > 0 ? ' <span style="font-size:10px;opacity:0.6;">(' + sb.trail_trip_count + ' trips)</span>' : ''}</span>
            <span>Terrain (${terrainName.split(':')[0]})</span><span style="text-align:right; ${terrainMult < 1 ? 'color:var(--color-mars)' : ''}">${terrainMult}x</span>
            <span style="font-weight:600; border-top:1px solid rgba(255,255,255,0.1); padding-top:4px;">Effective Speed</span>
            <span style="font-weight:600; text-align:right; border-top:1px solid rgba(255,255,255,0.1); padding-top:4px;">${effectiveSpeed} km/h</span>
        </div>`;

    // Show segment compounding details if multiple segments
    if (hasCompounding) {
        html += `
        <div style="font-size:10px; color:var(--text-muted); margin:-10px 0 12px; padding:6px 8px; background:rgba(var(--color-sepolia-rgb),0.1); border-radius:4px;">
            <div style="margin-bottom:4px;"><span style="color:var(--color-sepolia);">⚡ Trail Compounding Active</span></div>
            ${segments.slice(0, 3).map(seg => `
                <div style="display:flex; justify-content:space-between; opacity:0.8;">
                    <span>${seg.distance.toFixed(0)}km → ${seg.landmark ? seg.landmark.substring(0, 15) : 'destination'}${seg.landmark && seg.landmark.length > 15 ? '...' : ''}</span>
                    <span style="color:${seg.speed_mult > 1 ? 'var(--color-success)' : 'inherit'};">${seg.speed_mult}×</span>
                </div>
            `).join('')}
            ${segments.length > 3 ? `<div style="opacity:0.5; text-align:center;">+${segments.length - 3} more segments</div>` : ''}
        </div>`;
    }

    // Add hint about improving trails
    if (sb.trail_speed_mult < 3) {
        html += `
        <div style="font-size:10px; text-align:center; margin-bottom:12px;">
            <a href="/crew" style="color:var(--text-muted); text-decoration:none; opacity:0.6;">
                💡 Send crew on trail missions to boost speed
            </a>
        </div>`;
    }

    return html;
}

function selectModalVehicle(type) {
    const preview = window._previewData;
    if (!preview) return;
    const vehicle = preview.vehicles.find(v => v.vehicle_type === type);
    if (!vehicle || !vehicle.available) return;

    // Update button states
    document.querySelectorAll('.modal-vehicle-btn').forEach(btn => {
        const isSelected = btn.dataset.type === type;
        btn.classList.toggle('selected', isSelected);
        btn.style.borderColor = isSelected ? 'var(--color-mars)' : 'rgba(255,255,255,0.15)';
        btn.style.background = isSelected ? 'rgba(239,68,68,0.15)' : 'rgba(255,255,255,0.05)';
    });

    // Update trip estimate
    document.getElementById('modal-trip-estimate').innerHTML = renderTripEstimate(vehicle);

    // Update speed stack with vehicle-specific values
    document.getElementById('modal-speed-stack').innerHTML = renderSpeedStack(vehicle, preview.speed_breakdown);

    // Update launch button
    const btn = document.getElementById('modal-launch-btn');
    btn.textContent = `Deploy ${type.charAt(0).toUpperCase() + type.slice(1)}`;
    btn.disabled = false;
    btn.style.opacity = '1';
    btn.style.cursor = 'pointer';
}

function closePreLaunchModal() { MarsModal.hide(); }

async function confirmExpeditionLaunch() {
    const l = pendingLaunchLandmark;
    if (!l) return;

    const selectedBtn = document.querySelector('.modal-vehicle-btn.selected');
    const vehicleType = selectedBtn ? selectedBtn.dataset.type : 'rover';
    const launchBtn = document.getElementById('modal-launch-btn');
    launchBtn.disabled = true;
    launchBtn.textContent = 'Launching...';

    try {
        const data = await apiPost('/api/expeditions/start', {
                destination_name: l.name,
                destination_type: l.type,
                latitude: l.latitude,
                longitude: l.longitude,
                distance_km: l.distance_km,
                vehicle_type: vehicleType
            });
        if (data.success) {
            if (data.new_balance !== undefined && typeof window.setBalance === 'function') {
                window.setBalance(data.new_balance);
            }
            closePreLaunchModal();
            const roundTripHours = Math.round((data.total_round_trip_seconds || data.travel_time_seconds * 2) / 3600);
            showToast(`Launched! Returns in ${roundTripHours}h.`, 'success');
            setTimeout(() => location.reload(), 2000);
        } else {
            showToast(data.error || 'Failed to launch', 'error');
            launchBtn.disabled = false;
            launchBtn.textContent = `Launch ${vehicleType.charAt(0).toUpperCase() + vehicleType.slice(1)}`;
        }
    } catch {
        showToast('Network error', 'error');
        launchBtn.disabled = false;
        launchBtn.textContent = 'Launch';
    }
}

// Launch expedition from map popup button
function launchExpeditionFromMap(landmarkIndex) {
    if (landmarkIndex >= 0 && landmarkIndex < landmarksData.length) {
        launchExpedition(landmarksData[landmarkIndex]);
    }
}

async function recallExpedition(expeditionId, btn) {
    if (!confirm('Recall this vehicle? It will return without discoveries.')) return;
    btn.disabled = true;
    btn.textContent = 'Recalling...';
    try {
        const data = await apiPost('/api/expedition/recall', { expedition_id: expeditionId });
        if (data.success) {
            const returnHours = Math.round(data.return_seconds / 3600);
            showToast(`${data.message}. Returns in ${returnHours}h.`, 'success');
            setTimeout(() => location.reload(), 2000);
        } else {
            showToast(data.error || 'Recall failed', 'error');
            btn.disabled = false;
            btn.textContent = 'Recall';
        }
    } catch {
        showToast('Network error', 'error');
        btn.disabled = false;
        btn.textContent = 'Recall';
    }
}

function showOnMap(l) {
    if (!map) return;
    map.setView([l.latitude, l.longitude], 4);
    expeditionMarkers.forEach(m => {
        const ll = m.getLatLng();
        if (Math.abs(ll.lat - l.latitude) < 0.001 && Math.abs(ll.lng - l.longitude) < 0.001) {
            m.openPopup();
        }
    });
}
