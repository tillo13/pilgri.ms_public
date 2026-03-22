// ============================================================================
// EXPEDITIONS-PAGE.JS - Tabs, Sorting, Ledger, Vehicles, Signal Decoder
// ============================================================================

// Load icons from PAGE_DATA bridge
const EXP_PAGE_DATA = JSON.parse(document.getElementById('expeditionPageData')?.textContent || '{}');
const UI_ICONS = EXP_PAGE_DATA.icons || {};

// ============================================================================
// MAIN TAB SWITCHING (Map / Vehicles / Signal)
// ============================================================================

function switchMainTab(tab) {
    document.querySelectorAll('.main-tab-content').forEach(c => c.style.display = 'none');
    document.querySelectorAll('.expedition-tab').forEach(t => t.classList.remove('active'));
    const tabContent = document.getElementById('main-tab-' + tab);
    if (tabContent) tabContent.style.display = 'block';
    const tabBtn = document.querySelector(`.expedition-tab[data-tab="${tab}"]`);
    if (tabBtn) tabBtn.classList.add('active');
    if (tab === 'map' && typeof map !== 'undefined') {
        setTimeout(() => map.invalidateSize(), 100);
    }
}

document.addEventListener('DOMContentLoaded', function() {
    const urlParams = new URLSearchParams(window.location.search);
    const tabParam = urlParams.get('tab');
    if (tabParam && ['map', 'vehicles', 'signal'].includes(tabParam)) {
        switchMainTab(tabParam);
    }
});

// Signal decoder is handled by signal.js (loaded on this page)
// No duplicate decoder code here — DRY!

// ============================================================================
// SUB-TAB SWITCHING (within Map tab: new/ledger)
// ============================================================================

function switchExpeditionTab(tab) {
    document.querySelectorAll('.expedition-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.expedition-tab-content').forEach(c => c.style.display = 'none');
    document.querySelector(`[data-tab="${tab}"]`).classList.add('active');
    document.getElementById(`tab-${tab}`).style.display = 'block';
}

// ============================================================================
// MARS CONDITIONS HELP MODAL
// ============================================================================

function showConditionsHelp() {
    ItemDetailModal.show({
        name: 'Mars Atmospheric Conditions',
        image: null,
        category: `<img src="${UI_ICONS.env_sun_power}" alt="" style="width: 16px; height: 16px; vertical-align: middle;"> Environmental Status`,
        description: 'Real-time atmospheric data affects your expedition operations. These conditions are calculated based on Mars orbital mechanics and dust storm patterns.',
        stats: [
            { label: 'Solar Efficiency', value: 'Shard generation rate from solar arrays' },
            { label: 'Status', value: 'Current atmospheric clarity level' },
            { label: 'Sun Angle', value: 'Optimal range: 45-75° for best collection' },
            { label: 'Fee Multiplier', value: 'Transaction costs based on interference' }
        ],
        effects: `<div style="line-height: 1.6; font-size: 12px;">
            <div style="margin-bottom: 8px;"><strong style="color: var(--color-success);">Clear Skies:</strong> 95-100% efficiency, 1.0× fees</div>
            <div style="margin-bottom: 8px;"><strong style="color: var(--color-mars);">Dusty:</strong> 70-90% efficiency, 1.1-1.2× fees</div>
            <div style="margin-bottom: 8px;"><strong style="color: var(--color-danger);">Dust Storm:</strong> 30-60% efficiency, 1.3-1.5× fees</div>
            <div style="color: var(--color-primary); font-style: italic; margin-top: 12px;">Conditions update in real-time as Mars rotates.</div>
        </div>`
    });
}

// ============================================================================
// SORTING
// ============================================================================

function sortExpeditions(value) {
    const [field, dir] = value.split('-');
    const grids = [document.getElementById('newExpeditionsGrid'), document.getElementById('visitedExpeditionsGrid')];
    grids.forEach(grid => {
        if (!grid) return;
        const cards = Array.from(grid.querySelectorAll('.exp-card'));
        cards.sort((a, b) => {
            let aVal, bVal;
            if (field === 'distance') {
                aVal = parseFloat(a.dataset.distance);
                bVal = parseFloat(b.dataset.distance);
            } else if (field === 'cost') {
                aVal = parseFloat(a.querySelector('.expedition-total-cost').textContent) || 9999;
                bVal = parseFloat(b.querySelector('.expedition-total-cost').textContent) || 9999;
            }
            return dir === 'asc' ? aVal - bVal : bVal - aVal;
        });
        cards.forEach(card => grid.appendChild(card));
    });
}

// ============================================================================
// EXPEDITION LEDGER / HISTORY
// ============================================================================

let ledgerLoaded = false;
let ledgerData = { expeditions: [], total_count: 0 };

async function loadExpeditionHistory(offset = 0) {
    const loading = document.getElementById('ledger-loading');
    const empty = document.getElementById('ledger-empty');
    const content = document.getElementById('ledger-content');
    const list = document.getElementById('ledger-list');
    const countEl = document.getElementById('ledger-count');

    if (offset === 0) {
        loading.style.display = 'block';
        empty.style.display = 'none';
        content.style.display = 'none';
    }

    try {
        const r = await fetch(`/api/expeditions/history?limit=20&offset=${offset}`);
        const data = await r.json();

        if (!data.success) throw new Error(data.error || 'Failed to load');

        ledgerData = data;
        ledgerLoaded = true;

        if (countEl) countEl.textContent = data.total_count;
        loading.style.display = 'none';

        if (data.expeditions.length === 0 && offset === 0) {
            empty.style.display = 'block';
            content.style.display = 'none';
            return;
        }

        content.style.display = 'block';
        renderLedger(data.expeditions, list);
        renderLedgerPagination(data.total_count, data.offset, data.limit);

    } catch (e) {
        console.error('Failed to load expedition history:', e);
        loading.style.display = 'none';
        empty.style.display = 'block';
    }
}

function renderLedger(expeditions, container) {
    container.innerHTML = expeditions.map(exp => {
        const date = exp.completed_at ? new Date(exp.completed_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : 'Unknown';
        const expData = JSON.stringify(exp).replace(/"/g, '&quot;');
        const visitBadge = exp.visit_count > 1 ? `<span class="visit-badge">${exp.visit_count}x visited</span>` : '';
        const travelDays = (exp.duration_hours / 24).toFixed(1);
        const discoveriesCount = exp.discovery_count || 0;

        return `
        <div class="exp-card completed" onclick="showLedgerDetail(${expData})">
            <div class="exp-card-header">
                <div>
                    <div class="exp-card-name">${exp.destination}${visitBadge}</div>
                    <div class="exp-card-type">${exp.type.split(',')[0]} · ${date}</div>
                </div>
                <div class="exp-card-cost">
                    <div class="exp-card-cost-value">${exp.total_extracted.toFixed(0)}</div>
                    <div class="exp-card-cost-label">Extracted</div>
                </div>
            </div>
            <div class="exp-card-metrics">
                <div class="exp-metric">
                    <div class="exp-metric-value">${exp.distance_km}</div>
                    <div class="exp-metric-label">km</div>
                </div>
                <div class="exp-metric">
                    <div class="exp-metric-value">${travelDays}</div>
                    <div class="exp-metric-label">days</div>
                </div>
                <div class="exp-metric">
                    <div class="exp-metric-value highlight">${discoveriesCount}</div>
                    <div class="exp-metric-label">finds</div>
                </div>
            </div>
            <div class="exp-card-actions">
                <button class="btn btn-secondary" onclick="event.stopPropagation(); returnVisit(${expData})" style="flex: 1;">
                    <img src="${UI_ICONS.location_pin}" alt="" style="width: 14px; height: 14px; vertical-align: middle; margin-right: 6px;">Survey Again
                </button>
            </div>
            <details style="margin-top: 12px;" onclick="event.stopPropagation()">
                <summary style="cursor: pointer; font-size: 11px; color: var(--text-muted);">Expedition details</summary>
                <div style="margin-top: 8px; font-size: 11px; color: var(--text-secondary); display: grid; grid-template-columns: 1fr 1fr; gap: 4px;">
                    <div>Cost: <span style="color: var(--color-mars);">${exp.cost.toFixed(0)}</span> shards</div>
                    <div>Science: <span style="color: var(--color-purple);">${exp.scientific_value || 0}</span></div>
                    <div>Travel: ${exp.duration_hours}h</div>
                    <div>Extracted: <span style="color: var(--color-success);">${exp.total_extracted.toFixed(0)}</span></div>
                </div>
            </details>
        </div>`;
    }).join('');
}

function returnVisit(exp) {
    const mapDetails = document.querySelector('details:has(#mars-map)');
    if (mapDetails) {
        mapDetails.open = true;
        mapDetails.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    if (typeof map !== 'undefined' && exp.lat && exp.lon) {
        setTimeout(() => {
            map.setView([exp.lat, exp.lon], 5);
            if (typeof expeditionMarkers !== 'undefined') {
                expeditionMarkers.forEach(m => {
                    const ll = m.getLatLng();
                    if (Math.abs(ll.lat - exp.lat) < 0.01 && Math.abs(ll.lng - exp.lon) < 0.01) {
                        m.openPopup();
                    }
                });
            }
        }, 300);
    }
}

function renderLedgerPagination(total, offset, limit) {
    const pag = document.getElementById('ledger-pagination');
    if (total <= limit) {
        pag.innerHTML = `<div style="font-size: 12px; color: var(--text-muted);">Showing all ${total} expedition${total !== 1 ? 's' : ''}</div>`;
        return;
    }

    const page = Math.floor(offset / limit) + 1;
    const totalPages = Math.ceil(total / limit);

    let html = '<div style="display: flex; gap: 8px; justify-content: center; align-items: center;">';
    if (page > 1) {
        html += `<button class="btn btn-secondary" style="padding: 6px 12px; font-size: 12px;" onclick="loadExpeditionHistory(${(page - 2) * limit})">← Prev</button>`;
    }
    html += `<span style="font-size: 12px; color: var(--text-secondary);">Page ${page} of ${totalPages}</span>`;
    if (page < totalPages) {
        html += `<button class="btn btn-secondary" style="padding: 6px 12px; font-size: 12px;" onclick="loadExpeditionHistory(${page * limit})">Next →</button>`;
    }
    html += '</div>';
    pag.innerHTML = html;
}

async function showLedgerDetail(exp) {
    if (typeof ItemDetailModal === 'undefined') return;

    const date = exp.completed_at ? new Date(exp.completed_at).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' }) : 'Unknown';

    const rarityParts = [];
    if (exp.legendary > 0) rarityParts.push(`<span style="color: var(--color-gold);">${exp.legendary} Legendary</span>`);
    if (exp.rare > 0) rarityParts.push(`<span style="color: var(--color-purple);">${exp.rare} Rare</span>`);
    if (exp.uncommon > 0) rarityParts.push(`<span style="color: var(--color-success);">${exp.uncommon} Uncommon</span>`);
    if (exp.common > 0) rarityParts.push(`<span style="color: var(--text-secondary);">${exp.common} Common</span>`);
    const rarityBreakdown = rarityParts.length ? rarityParts.join(' · ') : 'No discoveries';

    const visitIndicator = exp.visit_count > 1
        ? `<div style="background: var(--color-purple); color: white; padding: 4px 10px; border-radius: 12px; font-size: 11px; display: inline-block; margin-top: 6px;">You've visited this site ${exp.visit_count} times</div>`
        : '';

    let discoveriesHtml = '<div style="text-align: center; color: var(--text-secondary); padding: 16px;">Loading discoveries...</div>';
    try {
        const r = await fetch(`/api/expeditions/${exp.id}/items`);
        const data = await r.json();
        if (data.success && data.discoveries.length > 0) {
            discoveriesHtml = '<div style="display: flex; flex-direction: column; gap: 8px; max-height: 220px; overflow-y: auto;">' +
                data.discoveries.map(d => {
                    const rarityColor = {common: 'var(--text-secondary)', uncommon: 'var(--color-success)', rare: 'var(--color-purple)', legendary: 'var(--color-gold)'}[d.rarity] || 'var(--text-secondary)';
                    const sciValue = d.scientific_value || 0;
                    const statusHtml = d.claimed
                        ? `<div style="font-size: 11px; color: var(--color-success);">Sold for ${Math.round(d.enhanced_value || 0)} shards</div>`
                        : `<div style="font-size: 11px; color: var(--text-muted);">In inventory</div>`;
                    return `<div style="display: flex; align-items: center; gap: 10px; padding: 10px; background: var(--bg-secondary); border-radius: 6px;">
                        ${d.image_url ? `<img src="${d.image_url}" style="width: 40px; height: 40px; border-radius: 4px; object-fit: cover;">` : '<div style="width: 40px; height: 40px; background: var(--bg-tertiary); border-radius: 4px;"></div>'}
                        <div style="flex: 1; min-width: 0;">
                            <div style="font-weight: 600; color: ${rarityColor}; font-size: 13px;">${d.quantity > 1 ? d.quantity + 'x ' : ''}${d.item_name}</div>
                            <div style="font-size: 11px; color: var(--text-muted);">${d.nearby_feature ? d.nearby_feature : 'Found at ' + d.found_at_km.toFixed(1) + ' km'}</div>
                        </div>
                        <div style="text-align: right;">
                            <div style="font-size: 13px; font-weight: 600; color: var(--color-purple);">${sciValue} <span style="font-size: 10px; color: var(--text-muted);">science</span></div>
                            ${statusHtml}
                        </div>
                    </div>`;
                }).join('') + '</div>';
        } else if (data.discoveries && data.discoveries.length === 0) {
            discoveriesHtml = '<div style="text-align: center; color: var(--text-secondary); padding: 16px; font-size: 13px;">No discoveries recorded for this expedition</div>';
        }
    } catch (e) {
        console.error('Failed to load discoveries:', e);
        discoveriesHtml = '<div style="text-align: center; color: var(--text-secondary); padding: 16px;">Failed to load discoveries</div>';
    }

    ItemDetailModal.show({
        name: exp.destination,
        image: null,
        htmlDescription: true,
        category: `<span style="text-transform: capitalize;"><img src="${UI_ICONS.mountain_type}" alt="" style="width: 14px; height: 14px; vertical-align: middle;"> ${exp.type.split(',')[0]}</span>`,
        description: `
            <div style="margin-bottom: 12px; color: var(--text-secondary); font-size: 13px;">
                <strong>${date}</strong> · ${exp.distance_km} km · ${exp.duration_hours}h travel
                ${visitIndicator}
            </div>
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; text-align: center; margin-bottom: 16px; padding: 12px; background: var(--bg-secondary); border-radius: 8px;">
                <div>
                    <div style="font-size: 22px; font-weight: 700; color: var(--color-mars);">${exp.cost.toFixed(0)}</div>
                    <div style="font-size: 10px; color: var(--text-muted);">Cost (shards)</div>
                </div>
                <div>
                    <div style="font-size: 22px; font-weight: 700; color: var(--color-purple);">${exp.scientific_value || 0}</div>
                    <div style="font-size: 10px; color: var(--text-muted);">Science</div>
                </div>
                <div>
                    <div style="font-size: 22px; font-weight: 700; color: var(--color-success);">${exp.claimed_count || 0}/${exp.discovery_count || 0}</div>
                    <div style="font-size: 10px; color: var(--text-muted);">Sold</div>
                </div>
            </div>
            <div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 16px; text-align: center;">${rarityBreakdown}</div>
            <div style="font-weight: 600; margin-bottom: 10px; font-size: 14px; border-bottom: 1px solid var(--border-color); padding-bottom: 8px;">Discoveries (${exp.discovery_count})</div>
            ${discoveriesHtml}`,
        stats: [],
        action: exp.link ? {
            label: 'View NASA Research',
            className: 'btn-secondary',
            onClick: () => window.open(exp.link, '_blank')
        } : null
    });

    if (exp.lat && exp.lon && typeof map !== 'undefined') {
        map.setView([exp.lat, exp.lon], 5);
    }
}

// ============================================================================
// VEHICLE SELECTION & DETAIL
// ============================================================================

window.selectedVehicle = { type: 'rover', name: 'Rover' };

document.addEventListener('DOMContentLoaded', function() {
    const firstVehicle = document.querySelector('.colony-mini-card[data-vehicle-type]');
    if (firstVehicle) selectVehicle(firstVehicle);
});

function selectVehicle(el) {
    document.querySelectorAll('.colony-mini-card[data-vehicle-type]').forEach(c => c.classList.remove('selected'));
    el.classList.add('selected');
    window.selectedVehicle = { type: el.dataset.vehicleType, name: el.dataset.vehicleName };
    showToast(`${window.selectedVehicle.name} selected for expeditions`, 'info');
}

function showVehicleDetail(el) {
    selectVehicle(el);
    const d = el.dataset;
    const isRover = d.vehicleType === 'rover' || d.vehicleType === 'buggy';
    const onMission = !!d.expeditionId;
    const stats = [];

    const vehicleTypeLabels = { 'rover': '🚗 Ground Rover', 'buggy': '🪨 Ground Buggy', 'drone': '🛸 Aerial Drone' };
    stats.push({ label: 'Type', value: vehicleTypeLabels[d.vehicleType] || '🚗 Vehicle' });
    stats.push({ label: 'Level', value: d.vehicleLevel });
    stats.push({ label: 'Cargo Capacity', value: `${d.vehicleCargo} physical items`, note: 'Weightless data (readings, signals) has no cargo limit' });

    // Speed breakdown
    const MARS_BASE_SPEED_KMH = 2.0;  // Base walking speed on Mars
    const speed = parseFloat(d.vehicleSpeed) || 1.0;
    const baseSpeed = parseFloat(d.vehicleBaseSpeed) || 1.0;
    const speedFromUpgrades = speed - baseSpeed;
    const vehicleKmh = (MARS_BASE_SPEED_KMH * speed).toFixed(1);
    let speedBreakdown = `${baseSpeed}× base`;
    if (speedFromUpgrades > 0) speedBreakdown += ` + ${speedFromUpgrades.toFixed(1)}× upgrades`;
    speedBreakdown += ` = <strong>${speed}× (${vehicleKmh} km/h)</strong>`;
    stats.push({ label: 'Travel Speed', value: `${vehicleKmh} km/h`, breakdown: speedBreakdown, note: 'Crew logistics, terrain & trail bonuses apply on each expedition launch' });

    // Range breakdown
    const maxRange = parseInt(d.vehicleMaxRange) || 0;
    const baseRange = parseInt(d.vehicleBaseRange) || 0;
    const effectiveRange = parseInt(d.vehicleEffectiveRange) || 0;
    const rangeMult = parseFloat(d.rangeMult) || 1.0;
    const discoveryCount = parseInt(d.discoveryCount) || 0;
    const rangeFromUpgrades = maxRange - baseRange;
    let rangeBreakdown = `${baseRange.toLocaleString()} km base`;
    if (rangeFromUpgrades > 0) rangeBreakdown += ` + ${rangeFromUpgrades.toLocaleString()} km upgrades`;
    if (rangeMult !== 1.0) rangeBreakdown += ` × ${rangeMult}× exploration (${discoveryCount} discoveries)`;
    rangeBreakdown += ` = <strong>${effectiveRange.toLocaleString()} km</strong>`;
    stats.push({ label: 'Max Range', value: `${effectiveRange.toLocaleString()} km`, breakdown: rangeBreakdown });

    const discovery = parseFloat(d.vehicleDiscovery) || 0;
    const rare = parseFloat(d.vehicleRare) || 0;
    const legendary = parseFloat(d.vehicleLegendary) || 0;

    if (discovery !== 0) stats.push({ label: 'Discovery Rate', value: `${discovery > 0 ? '+' : ''}${(discovery * 100).toFixed(0)}%` });
    if (rare !== 0) stats.push({ label: 'Rare Chance', value: `${rare > 0 ? '+' : ''}${(rare * 100).toFixed(0)}%` });
    if (legendary !== 0) {
        const legVal = legendary === -1 ? 'Cannot find' : `${(legendary * 100).toFixed(0)}%`;
        stats.push({ label: 'Legendary Chance', value: legVal });
    }

    // Build mission section if vehicle is on expedition
    let missionHtml = '';
    if (onMission && d.expDest) {
        const now = Date.now();
        const arrivesAt = new Date(d.expArrivesAt).getTime();
        const returnAt = new Date(d.expReturnAt).getTime();
        const departedAt = new Date(d.expDepartedAt).getTime();
        const status = d.expStatus;
        const isReturning = now >= arrivesAt || status === 'recalled';
        const targetTime = isReturning ? returnAt : arrivesAt;
        const remainMs = Math.max(0, targetTime - now);
        const remainH = Math.floor(remainMs / 3600000);
        const remainM = Math.floor((remainMs % 3600000) / 60000);

        const phase = status === 'recalled' ? 'Returning (recalled)' : (isReturning ? 'Returning to base' : 'En route');
        const progressTotal = isReturning ? (returnAt - arrivesAt) : (arrivesAt - departedAt);
        const progressElapsed = isReturning ? (now - arrivesAt) : (now - departedAt);
        const progressPct = progressTotal > 0 ? Math.min(100, Math.max(0, (progressElapsed / progressTotal) * 100)) : 0;

        missionHtml = `
            <div style="background: linear-gradient(135deg, rgba(181,112,64,0.2), rgba(181,112,64,0.05)); border: 1px solid var(--color-mars); border-radius: 12px; padding: 16px; margin-bottom: 16px;">
                <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--color-mars); font-weight: 700; margin-bottom: 8px;">Active Mission</div>
                <div style="font-weight: 700; font-size: 15px; margin-bottom: 4px;">${d.expDest}</div>
                <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 10px;">${d.expDestType} &middot; ${parseFloat(d.expDistance).toLocaleString()} km</div>
                <div style="font-size: 13px; color: var(--text-secondary); margin-bottom: 8px;">${phase}</div>
                <div style="background: var(--bg-secondary); border-radius: 4px; height: 6px; overflow: hidden; margin-bottom: 6px;">
                    <div style="background: var(--color-mars); height: 100%; width: ${progressPct.toFixed(1)}%; border-radius: 4px; transition: width 0.3s;"></div>
                </div>
                <div style="display: flex; justify-content: space-between; font-size: 11px; color: var(--text-muted);">
                    <span>${progressPct.toFixed(0)}% complete</span>
                    <span>${remainH}h ${remainM}m remaining</span>
                </div>
            </div>`;
    }

    const description = onMission ? '' : (isRover
        ? 'Rovers are your primary expedition vehicles. They travel across the Martian surface to explore landmarks, collect discoveries, and return with cargo. Higher level rovers have more cargo capacity and faster travel times.'
        : 'Drones provide fast aerial reconnaissance. They travel quickly but carry less cargo and are better at finding common items. Great for quick scouting missions to nearby locations.');

    const statsHtml = stats.map(s => `
        <div style="padding: 10px 0; border-bottom: 1px solid var(--border-default);">
            <div style="display: flex; justify-content: space-between;">
                <span style="color: var(--text-muted); font-size: 13px;">${s.label}</span>
                <span style="font-weight: 600; color: var(--text-primary);">${s.value}</span>
            </div>
            ${s.breakdown ? `<div style="font-size: 11px; color: var(--text-muted); margin-top: 4px; line-height: 1.5;">${s.breakdown}</div>` : ''}
            ${s.note ? `<div style="font-size: 10px; color: var(--text-muted); margin-top: 2px; font-style: italic; opacity: 0.7;">${s.note}</div>` : ''}
        </div>
    `).join('');

    const headerBg = onMission
        ? 'linear-gradient(135deg, rgba(181,112,64,1) 0%, rgba(140,80,40,1) 100%)'
        : 'linear-gradient(135deg, var(--color-mars) 0%, var(--color-mars-dark) 100%)';
    const statusBadge = onMission
        ? '<div style="display: inline-block; background: rgba(255,255,255,0.25); padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; color: white; margin-top: 6px;">ON MISSION</div>'
        : '';

    const modalHtml = `
        <div id="vehicleModal" style="position: fixed; inset: 0; background: rgba(0,0,0,0.85); z-index: 1000; display: flex; align-items: center; justify-content: center; padding: 20px;" onclick="if(event.target===this)this.remove()">
            <div style="background: var(--bg-card); border-radius: 16px; max-width: 420px; width: 100%; max-height: 90vh; overflow-y: auto; box-shadow: 0 25px 50px rgba(0,0,0,0.5); border: 1px solid var(--border-default);">
                <div style="padding: 24px; text-align: center; background: ${headerBg}; border-radius: 15px 15px 0 0;">
                    ${d.vehicleImage ? `<img src="${d.vehicleImage}" alt="${d.vehicleName}" style="width: 80px; height: 80px; border-radius: 12px; margin-bottom: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);">` : `<div style="width: 80px; height: 80px; margin: 0 auto 12px; background: rgba(255,255,255,0.2); border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 40px;">${isRover ? '🚗' : '🛸'}</div>`}
                    <h3 style="margin: 0; color: white; font-size: 20px; text-shadow: 0 2px 8px rgba(0,0,0,0.3);">${d.vehicleName}</h3>
                    <div style="color: rgba(255,255,255,0.9); font-size: 13px; margin-top: 4px;">Level ${d.vehicleLevel} ${isRover ? 'Rover' : 'Drone'}</div>
                    ${statusBadge}
                </div>
                <div style="padding: 20px;">
                    ${missionHtml}
                    ${statsHtml}
                    ${description ? `<p style="margin: 16px 0 0 0; font-size: 13px; color: var(--text-secondary); line-height: 1.6;">${description}</p>` : ''}
                </div>
                <div style="padding: 0 20px 20px; display: flex; gap: 12px; justify-content: center;">
                    <a href="/colony?tab=assets" style="background: var(--color-primary); color: white; border: none; padding: 10px 20px; border-radius: 8px; cursor: pointer; font-weight: 600; text-decoration: none; font-size: 13px;">View in Colony</a>
                    <button onclick="this.closest('#vehicleModal').remove()" style="background: var(--bg-tertiary); color: var(--text-primary); border: none; padding: 10px 20px; border-radius: 8px; cursor: pointer; font-weight: 600; font-size: 13px;">Close</button>
                </div>
            </div>
        </div>
    `;

    const existing = document.getElementById('vehicleModal');
    if (existing) existing.remove();
    document.body.insertAdjacentHTML('beforeend', modalHtml);
}
