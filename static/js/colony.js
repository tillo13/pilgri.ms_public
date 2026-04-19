/* Colony Page - Discoveries, Equipment, Assets, Lab, Activity */

// Load page data from template (Jinja2 bridge)
const COLONY_DATA = JSON.parse(document.getElementById('colonyPageData').textContent);
const UI_ICONS = COLONY_DATA.icons;

// allDiscoveries is defined in discovery_utils.js (shared)

// Tab callbacks - register with core.js tab system
let activityLoaded = false, labLoaded = false;
console.log('[COLONY] Registering tab callbacks...');
window.tabCallbacks = window.tabCallbacks || {};
window.tabCallbacks.colony = {
    activity: () => {
        console.log('[COLONY] Activity callback fired, activityLoaded=' + activityLoaded);
        if (!activityLoaded) { activityLoaded = true; loadActivity(); }
    },
    lab: () => {
        console.log('[COLONY] Lab callback fired, labLoaded=' + labLoaded);
        if (!labLoaded) { labLoaded = true; loadLab(); }
    }
};
console.log('[COLONY] tabCallbacks.colony registered:', window.tabCallbacks.colony);

// Activity log - icons and colors for each activity category
const ACTIVITY_ICONS = {
    purchase: 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/activity_purchase_1769206502.png',
    infrastructure: 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/activity_infrastructure_1769206548.png',
    expedition: 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/activity_expedition_1769206558.png',
    upgrade: 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/activity_upgrade_1769206568.png',
    research: 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/activity_research_1769206618.png',
    discovery: 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/activity_discovery_1769206581.png',
    landmark: 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/activity_landmark_1769206592.png',
    claim: 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/activity_claim_1769206605.png',
    trail: COLONY_DATA.trailIcon || '',
    sharding: 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/activity_discovery_1769206581.png',
    income: 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/activity_claim_1769206605.png',
    equipment: 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/activity_purchase_1769206502.png',
    modification: 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/activity_upgrade_1769206568.png',
    media: 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/activity_discovery_1769206581.png',
    transmutation: 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/activity_research_1769206618.png'
};
const ACTIVITY_COLORS = {
    purchase: '#f59e0b', infrastructure: '#8b5cf6', expedition: '#06b6d4', upgrade: '#10b981',
    research: '#ec4899', discovery: '#f97316', landmark: '#14b8a6', claim: '#6366f1', trail: '#a855f7',
    sharding: '#22c55e', income: '#22c55e', equipment: '#f59e0b', modification: '#6366f1',
    media: '#8b5cf6', transmutation: '#ec4899'
};

async function loadActivity() {
    console.log('[COLONY] loadActivity() called');
    // Reuse data if welcome-back already fetched it
    if (window._allActivityData && window._allActivityData.length) {
        renderActivityList(window._allActivityData);
        return;
    }
    try {
        const resp = await fetch('/api/colony/activity');
        const data = await resp.json();
        if (!data.success || !data.activity.length) {
            document.getElementById('activityList').innerHTML = '<div class="empty-state"><div class="empty-state-text">No activity yet</div></div>';
            return;
        }
        window._allActivityData = data.activity;
        renderActivityList(data.activity);
    } catch(e) {
        document.getElementById('activityList').innerHTML = '<div class="empty-state"><div class="empty-state-text">Failed to load activity</div></div>';
    }
}

// Filter activity by category
function filterActivity(category) {
    // Update filter button states (only within activity tab)
    document.querySelectorAll('#tab-activity .filter-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelector(`#tab-activity [data-filter="${category}"]`)?.classList.add('active');

    if (!window._allActivityData || !window._allActivityData.length) return;

    // Category mapping: some filters include multiple categories
    const categoryMap = {
        'all': null,
        'expedition': ['expedition'],
        'purchase': ['purchase', 'equipment'],
        'upgrade': ['upgrade', 'infrastructure', 'modification'],
        'research': ['research'],
        'discovery': ['discovery', 'landmark'],
        'trail': ['trail'],
        'media': ['media'],
        'income': ['income', 'claim', 'sharding']
    };

    const categories = categoryMap[category];
    const filtered = categories ? window._allActivityData.filter(item => categories.includes(item.category)) : window._allActivityData;

    renderActivityList(filtered);
}

// Render activity list
function renderActivityList(items) {
    if (!items || !items.length) {
        document.getElementById('activityList').innerHTML = '<div class="empty-state"><div class="empty-state-text">No activity in this category</div></div>';
        return;
    }
    window._activityData = items; // Store current filtered list for modal clicks
    document.getElementById('activityList').innerHTML = items.map((item, i) => {
        const d = new Date(item.timestamp);
        const dateStr = d.toLocaleDateString('en-US', {month:'short', day:'numeric', year:'numeric'});
        const timeStr = d.toLocaleTimeString('en-US', {hour:'numeric', minute:'2-digit'});
        // Bug #1315: sv_recorded amounts are SV, not shards — title already shows "Recorded X.X SV" so suppress redundant right-column cost entirely for that event type
        const isSV = item.event_type === 'sv_recorded';
        const cost = (item.amount && !isSV) ? `<span style="color: ${ACTIVITY_COLORS[item.category] || '#888'}; font-weight: 600;">${Math.round(item.amount).toLocaleString()} shards</span>` : '';
        const detailLine = item.detail ? `<span style="color:var(--text-tertiary); font-size:10px; margin-left:6px;">\u00B7 ${item.detail}</span>` : '';
        return `<div class="activity-row" onclick="showActivityDetail(${i})" style="display:flex; align-items:center; gap:12px; padding:10px 12px; background:var(--bg-primary); border-radius:8px; cursor:pointer; transition:background 0.15s;" onmouseover="this.style.background='var(--bg-tertiary)'" onmouseout="this.style.background='var(--bg-primary)'">
            <img src="${ACTIVITY_ICONS[item.category] || ACTIVITY_ICONS.purchase}" style="width:28px; height:28px; border-radius:4px; object-fit:cover;" alt="${item.category}">
            <div style="flex:1; min-width:0;">
                <div style="font-size:13px; font-weight:600; color:var(--text-primary); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${item.title}${detailLine}</div>
                <div style="font-size:11px; color:var(--text-secondary);">${dateStr} at ${timeStr}</div>
            </div>
            ${cost ? `<div style="text-align:right; font-size:12px;">${cost}</div>` : ''}
        </div>`;
    }).join('');
}

// Shared event card builder — used by activity detail modal AND welcome-back carousel
function buildEventCardHtml(item) {
    const d = new Date(item.timestamp);
    const dateStr = d.toLocaleDateString('en-US', {weekday:'short', month:'short', day:'numeric', year:'numeric'});
    const timeStr = d.toLocaleTimeString('en-US', {hour:'numeric', minute:'2-digit', second:'2-digit'});
    const color = ACTIVITY_COLORS[item.category] || '#888';
    const icon = ACTIVITY_ICONS[item.category] || ACTIVITY_ICONS.purchase;
    let body = '';
    if (item.image_url) body += `<img class="mm-image" src="${item.image_url}" alt="">`;
    else body += `<div style="text-align:center;padding:8px 0;"><img src="${icon}" style="width:48px;height:48px;border-radius:8px;"></div>`;
    body += `<div class="mm-section-label">--- EVENT DETAILS ---</div>`;
    body += `<div class="mm-kv"><span class="mm-kv-label">Date</span><span class="mm-kv-value">${dateStr}</span></div>`;
    body += `<div class="mm-kv"><span class="mm-kv-label">Time</span><span class="mm-kv-value">${timeStr}</span></div>`;
    body += `<div class="mm-kv"><span class="mm-kv-label">Category</span><span class="mm-kv-value" style="color:${color};">${item.category.charAt(0).toUpperCase() + item.category.slice(1)}</span></div>`;
    if (item.amount) {
        // Bug #1315: sv_recorded events are Science Value, not shards
        const isSV = item.event_type === 'sv_recorded';
        const amtStr = isSV
            ? `${Number(item.amount).toFixed(1)} SV`
            : `${Math.round(item.amount).toLocaleString()} shards`;
        body += `<div class="mm-kv"><span class="mm-kv-label">Amount</span><span class="mm-kv-value" style="color:${color};">${amtStr}</span></div>`;
    }
    if (item.detail) body += `<div class="mm-kv"><span class="mm-kv-label">Detail</span><span class="mm-kv-value">${item.detail}</span></div>`;
    if (item.status) body += `<div class="mm-kv"><span class="mm-kv-label">Status</span><span class="mm-kv-value">${item.status.charAt(0).toUpperCase() + item.status.slice(1)}</span></div>`;
    if (item.tx_hash) body += `<div class="mm-kv"><span class="mm-kv-label">Signature</span><span class="mm-kv-value" style="font-family:monospace; font-size:11px; word-break:break-all; color:var(--color-sepolia);">${item.tx_hash.slice(0,12)}...${item.tx_hash.slice(-8)}</span></div>`;
    return { body, color };
}

function showActivityDetail(index) {
    const item = window._activityData[index];
    if (!item) return;
    if (item.category === 'expedition' && item.is_complete && item.expedition_id) { showActivityExpeditionHaul(item); return; }
    const { body, color } = buildEventCardHtml(item);
    MarsModal.show({ title: item.title, subtitle: `<span style="color:${color};">${item.category}</span>`, width: 'sm', body });
}

// Show expedition haul modal for completed expeditions in Activity tab
function showActivityExpeditionHaul(item) {
    // Use the shared expedition haul modal from dashboard.js (without claim button since it's history)
    if (typeof window.showExpeditionHaulModal === 'function') {
        window.showExpeditionHaulModal(item.expedition_id, false);
    } else {
        // Fallback if dashboard.js not loaded
        MarsModal.show({
            title: `Expedition to ${item.destination || 'Mars'}`,
            subtitle: 'Mission Complete',
            body: `<div class="mm-kv"><span class="mm-kv-label">Distance</span><span class="mm-kv-value">${(item.distance_km || 0).toLocaleString()} km</span></div>
                   <div class="mm-kv"><span class="mm-kv-label">Shards Earned</span><span class="mm-kv-value" style="color:var(--color-warning);">${Math.round(item.shards_earned || 0).toLocaleString()}</span></div>
                   <div class="mm-kv"><span class="mm-kv-label">Discoveries</span><span class="mm-kv-value">${item.discovery_count || 0} items</span></div>`,
            width: 'sm'
        });
    }
}


// Lab tab
function formatTechEffect(effects) {
    const parts = [];
    if (effects.expedition_speed_bonus) parts.push(`+${(effects.expedition_speed_bonus*100).toFixed(0)}% speed`);
    if (effects.fuel_efficiency_bonus) parts.push(`-${(effects.fuel_efficiency_bonus*100).toFixed(0)}% fuel`);
    if (effects.discovery_chance_bonus) parts.push(`+${(effects.discovery_chance_bonus*100).toFixed(0)}% discovery`);
    if (effects.rare_chance_bonus) parts.push(`+${(effects.rare_chance_bonus*100).toFixed(0)}% rare`);
    if (effects.legendary_chance_bonus) parts.push(`+${(effects.legendary_chance_bonus*100).toFixed(0)}% legendary`);
    if (effects.dust_storm_resistance) parts.push(`dust immune`);
    if (effects.cargo_bonus) parts.push(`+${effects.cargo_bonus} cargo`);
    if (effects.range_bonus_km) parts.push(`+${effects.range_bonus_km.toLocaleString()} km range`);
    if (effects.passive_income_bonus) parts.push(`+${(effects.passive_income_bonus*100).toFixed(0)}% income`);
    if (effects.generation_rate_bonus) parts.push(`+${(effects.generation_rate_bonus*100).toFixed(0)}% gen`);
    if (effects.shard_yield_bonus) parts.push(`+${(effects.shard_yield_bonus*100).toFixed(0)}% yield`);
    if (effects.extraction_efficiency) parts.push(`+${(effects.extraction_efficiency*100).toFixed(0)}% extract`);
    if (effects.bio_value_bonus) parts.push(`+${(effects.bio_value_bonus*100).toFixed(0)}% bio`);
    if (effects.specimen_quality_bonus) parts.push(`+${(effects.specimen_quality_bonus*100).toFixed(0)}% discovery quality`);
    return parts.join(' · ') || '';
}

window._techCache = window._techCache || {};

function showTechDetailModalByKey(branchKey, techKey) {
    const tech = (window._techCache[branchKey] || {})[techKey];
    if (!tech) return;
    const branch = window._techCache.__branches && window._techCache.__branches[branchKey];
    showTechDetailModal(tech, branch);
}

function formatDuration(seconds) {
    if (!seconds || seconds <= 0) return '—';
    if (seconds >= 86400) return `${Math.floor(seconds/86400)}d ${Math.floor((seconds%86400)/3600)}h`;
    if (seconds >= 3600) return `${Math.floor(seconds/3600)}h ${Math.floor((seconds%3600)/60)}m`;
    if (seconds >= 60) return `${Math.floor(seconds/60)}m`;
    return `${seconds}s`;
}

function showTechDetailModal(tech, branch) {
    const statusColors = { completed: 'var(--color-success)', researching: 'var(--color-sepolia)', available: 'var(--text-primary)', locked: 'var(--text-muted)' };
    const statusLabels = { completed: 'Completed', researching: 'Researching...', available: 'Available', locked: 'Locked — prereqs not met' };
    const effectLine = formatTechEffect(tech.effects || {});
    const reqs = (tech.requires || []).length ? tech.requires.join(', ') : 'None';
    const row = (label, value) => `<div style="display:flex; justify-content:space-between; gap:12px; padding:6px 0; border-bottom:1px solid rgba(255,255,255,0.05); font-size:12px;"><span style="color:var(--text-muted);">${label}</span><span style="color:var(--text-primary); text-align:right;">${value}</span></div>`;

    const imgHtml = tech.image_url
        ? `<img src="${tech.image_url}" style="width:100%; max-width:260px; aspect-ratio:1/1; object-fit:cover; border-radius:12px; border:2px solid ${statusColors[tech.status]};" loading="lazy">`
        : `<div style="width:260px; height:260px; background:var(--bg-tertiary); border-radius:12px; display:flex; align-items:center; justify-content:center; font-size:60px; color:var(--text-muted);">?</div>`;

    const progressHtml = tech.status === 'researching' && tech.progress_pct !== undefined ? `
        <div style="margin-top:12px;">
            <div style="display:flex; justify-content:space-between; font-size:11px; color:var(--text-muted); margin-bottom:4px;">
                <span>Progress</span><span>${tech.progress_pct}% · ${formatDuration(tech.remaining_seconds)} remaining</span>
            </div>
            <div style="height:8px; background:rgba(255,255,255,0.08); border-radius:4px; overflow:hidden;">
                <div style="height:100%; width:${tech.progress_pct}%; background:var(--color-sepolia); border-radius:4px;"></div>
            </div>
        </div>` : '';

    const body = `
        <div style="text-align:center; margin-bottom:14px;">${imgHtml}</div>
        <div style="text-align:center; margin-bottom:12px;">
            <div style="display:inline-block; padding:4px 10px; border-radius:10px; background:rgba(255,255,255,0.05); font-size:11px; font-weight:700; color:${statusColors[tech.status]}; text-transform:uppercase; letter-spacing:0.5px;">${statusLabels[tech.status]}</div>
        </div>
        <div style="font-size:13px; color:var(--text-secondary); line-height:1.5; margin-bottom:14px;">${tech.description || ''}</div>
        ${effectLine ? `<div style="background:rgba(168,85,247,0.1); border:1px solid rgba(168,85,247,0.25); border-radius:8px; padding:10px 12px; margin-bottom:14px; font-size:13px; color:var(--color-sepolia); font-weight:600;">${effectLine}</div>` : ''}
        <div style="background:var(--bg-card); border-radius:8px; padding:8px 12px; margin-bottom:12px;">
            ${branch ? row('Branch', `${branch.name} · Lv${branch.branch_level || 1}`) : ''}
            ${row('Tier', tech.tier || 1)}
            ${tech.status !== 'completed' ? row('SV Cost', `${(tech.cost_sv || 0).toLocaleString()} SV`) : ''}
            ${tech.status !== 'completed' ? row('Research Time', formatDuration(tech.research_time_seconds)) : ''}
            ${row('Prerequisites', reqs)}
            ${row('Tech Key', tech.tech_key || '—')}
        </div>
        ${progressHtml}
    `;
    new MarsModal({ title: tech.name, body, width: 'md' }).show();
}

async function loadLab() {
    try {
        const resp = await fetch('/api/tech/status');
        const data = await resp.json();
        if (!data.has_research_station) {
            document.getElementById('labContent').innerHTML = `
                <div class="empty-state" style="padding:40px 20px;">
                    <div style="font-size:36px; margin-bottom:12px;">&#128300;</div>
                    <div class="empty-state-text">Research Station required</div>
                    <div style="font-size:12px; color:var(--text-secondary); margin:8px 0 16px;">Build a Research Station in the Depot to unlock the Tech Tree.</div>
                    <a href="/depot" class="btn btn-purple btn-small">Go to Depot</a>
                </div>`;
            return;
        }
        const branches = data.branches || {};
        const active = data.active_research;
        const sp = data.research_points || 0;

        let activeHtml = '';
        if (active) {
            const remaining = active.remaining_seconds || 0;
            const pct = active.progress_pct || 0;
            const timeLeft = remaining > 86400 ? `${Math.floor(remaining/86400)}d ${Math.floor((remaining%86400)/3600)}h` : remaining > 3600 ? `${Math.floor(remaining/3600)}h ${Math.floor((remaining%3600)/60)}m` : `${Math.floor(remaining/60)}m`;
            activeHtml = `<div style="background:var(--bg-card); border-radius:var(--radius-md); padding:14px 16px; margin-bottom:16px; border:1px solid rgba(168,85,247,0.2);">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                    <span style="font-size:13px; font-weight:600; color:var(--text-primary);">Researching: ${active.tech_name}</span>
                    <span style="font-size:12px; font-weight:600; color:var(--color-sepolia); font-family:monospace;">${timeLeft}</span>
                </div>
                <div style="height:6px; background:rgba(255,255,255,0.08); border-radius:3px; overflow:hidden;">
                    <div style="height:100%; width:${pct}%; background:var(--color-sepolia); border-radius:3px; transition:width 0.3s;"></div>
                </div>
            </div>`;
        }

        let branchesHtml = '';
        window._techCache = { __branches: {} };
        for (const [branchKey, branch] of Object.entries(branches)) {
            const branchIcon = branch.icon_url ? `<img src="${branch.icon_url}" style="width:20px;height:20px;border-radius:3px;">` : `<span style="font-size:16px;">${branch.icon}</span>`;
            const completed = branch.completed_count || 0;
            const total = branch.total_techs || 5;
            const lvl = branch.branch_level || 1;
            window._techCache.__branches[branchKey] = branch;
            window._techCache[branchKey] = {};

            // Build tech items grid
            let techsHtml = '';
            const techs = branch.techs || {};
            for (const [techKey, tech] of Object.entries(techs)) {
                window._techCache[branchKey][techKey] = tech;
                const statusBorder = tech.status === 'completed' ? 'var(--color-success)' : tech.status === 'researching' ? 'var(--color-sepolia)' : 'rgba(255,255,255,0.08)';
                const opacity = tech.status === 'locked' ? '0.4' : '1';
                const badge = tech.status === 'completed' ? '<div style="position:absolute;top:-2px;right:-2px;width:14px;height:14px;background:var(--color-success);border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:9px;color:white;">&#10003;</div>' : '';
                techsHtml += `<div onclick="showTechDetailModalByKey('${branchKey}','${techKey}')" style="cursor:pointer; position:relative; display:flex; flex-direction:column; align-items:center; gap:4px; opacity:${opacity};">
                    <div style="width:48px; height:48px; border-radius:8px; border:2px solid ${statusBorder}; overflow:hidden; background:var(--bg-tertiary);">
                        ${tech.image_url ? `<img src="${tech.image_url}" style="width:100%;height:100%;object-fit:cover;" loading="lazy">` : `<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:20px;">?</div>`}
                    </div>
                    ${badge}
                    <div style="font-size:9px; color:var(--text-secondary); text-align:center; max-width:60px; line-height:1.2; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${tech.base_name || tech.name}</div>
                </div>`;
            }

            branchesHtml += `<div style="background:var(--bg-card); border-radius:var(--radius-md); padding:12px; margin-bottom:10px; border:1px solid rgba(255,255,255,0.06);">
                <div style="display:flex; align-items:center; gap:8px; margin-bottom:10px;">
                    ${branchIcon}
                    <div style="flex:1;">
                        <span style="font-size:13px; font-weight:600; color:var(--text-primary);">${branch.name}</span>
                        <span style="font-size:11px; color:var(--text-muted); margin-left:6px;">Lv${lvl} · ${completed}/${total}</span>
                    </div>
                </div>
                <div style="display:flex; gap:12px; justify-content:space-around;">
                    ${techsHtml}
                </div>
            </div>`;
        }

        document.getElementById('labContent').innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
                <div>
                    <div style="font-size:11px; color:var(--text-muted); text-transform:uppercase; font-weight:600;">Scientific Value</div>
                    <div style="font-size:22px; font-weight:700; color:var(--color-sepolia);">${sp.toLocaleString()} SV</div>
                </div>
                <a href="/research" class="btn btn-purple btn-small">Full Tech Tree &rarr;</a>
            </div>
            ${activeHtml}
            ${branchesHtml}
        `;
    } catch(e) {
        document.getElementById('labContent').innerHTML = '<div class="empty-state"><div class="empty-state-text">Failed to load lab status</div></div>';
    }
}

// Handle URL query parameter for tab switching and item modal
function handleTabFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const tab = params.get('tab');
    const itemId = params.get('item');
    // Support both ?tab=assets and #base hash (alias: base → assets)
    const hashTab = window.location.hash.replace('#', '');
    const effectiveTab = tab || ({'base': 'assets'}[hashTab] || hashTab) || null;
    if (effectiveTab && ['discoveries', 'equipment', 'assets', 'lab', 'activity'].includes(effectiveTab)) switchColonyTab(effectiveTab);
    if (itemId) {
        setTimeout(() => {
            const allCards = document.querySelectorAll('.asset-card.building');
            for (const card of allCards) {
                const cardName = card.dataset.name?.toLowerCase().replace(/\s+/g, '_');
                const searchId = itemId.toLowerCase();
                if (cardName && (cardName.includes(searchId) || searchId.includes(cardName))) { card.click(); return; }
            }
            if (window.equipmentData) {
                const matchingIndex = window.equipmentData.findIndex(item =>
                    item.id === itemId || item.name?.toLowerCase().replace(/\s+/g, '_').includes(itemId.toLowerCase())
                );
                if (matchingIndex >= 0) showEquipmentModal(window.equipmentData[matchingIndex]);
            }
        }, 500);
    }
}

// ARIA Bonds Section
function renderAriaBonds() {
    const bonds = COLONY_DATA.ariaBonds || [];
    if (!bonds.length) return;

    const section = document.getElementById('ariaBondsSection');
    const grid = document.getElementById('ariaBondsGrid');
    if (!section || !grid) return;

    section.style.display = 'block';
    window._ariaBondsData = bonds;

    grid.innerHTML = bonds.map((bond, i) => {
        const isPending = bond.status === 'pending';
        const statusColor = isPending ? '#f59e0b' : '#06b6d4';
        const statusText = isPending ? (bond.my_submitted ? 'Waiting for Partner' : 'Fragment Ready') : 'Bonded';
        const borderColor = isPending ? 'rgba(245,158,11,0.3)' : 'rgba(6,182,212,0.3)';
        const img = bond.bond_image_url
            ? `<img src="${bond.bond_image_url}" style="width:100%;height:100%;object-fit:cover;" loading="lazy">`
            : `<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:28px;color:${statusColor};">&#9830;</div>`;
        return `<div onclick="showBondDetail(${i})" style="cursor:pointer; background:var(--bg-card); border-radius:var(--radius-md); border:1px solid ${borderColor}; padding:10px; text-align:center; transition:transform 0.15s;" onmouseover="this.style.transform='scale(1.02)'" onmouseout="this.style.transform='scale(1)'">
            <div style="width:64px;height:64px;border-radius:8px;overflow:hidden;margin:0 auto 8px;background:var(--bg-tertiary);border:2px solid ${statusColor};">${img}</div>
            <div style="font-size:12px;font-weight:600;color:var(--text-primary);margin-bottom:2px;">${bond.landmark_name}</div>
            <div style="font-size:10px;color:var(--text-secondary);margin-bottom:4px;">with ${bond.partner_name}</div>
            <div style="font-size:10px;font-weight:600;color:${statusColor};">${statusText}</div>
        </div>`;
    }).join('');
}

function showBondDetail(index) {
    const bond = window._ariaBondsData[index];
    if (!bond) return;

    const isPending = bond.status === 'pending';
    const statusColor = isPending ? '#f59e0b' : '#06b6d4';
    const statusLabel = isPending ? (bond.my_submitted ? 'Awaiting Partner Fragment' : 'Your Fragment is Ready') : 'Fully Bonded';

    let body = '';
    if (bond.bond_image_url) body += `<img class="mm-image" src="${bond.bond_image_url}" alt="Bond at ${bond.landmark_name}">`;

    body += `<div class="mm-section-label">--- BOND STATUS ---</div>`;
    body += `<div class="mm-kv"><span class="mm-kv-label">Status</span><span class="mm-kv-value" style="color:${statusColor};font-weight:600;">${statusLabel}</span></div>`;
    body += `<div class="mm-kv"><span class="mm-kv-label">Location</span><span class="mm-kv-value">${bond.landmark_name}</span></div>`;
    body += `<div class="mm-kv"><span class="mm-kv-label">Bonded With</span><span class="mm-kv-value">${bond.partner_name}</span></div>`;
    body += `<div class="mm-kv"><span class="mm-kv-label">Detected</span><span class="mm-kv-value">${bond.created_at}</span></div>`;
    if (bond.bonded_at) body += `<div class="mm-kv"><span class="mm-kv-label">Bonded On</span><span class="mm-kv-value">${bond.bonded_at}</span></div>`;

    if (bond.bond_tx_hash) {
        body += `<div class="mm-section-label">--- CRYSTAL FRAGMENT ---</div>`;
        body += `<div class="mm-kv"><span class="mm-kv-label">Fragment Code</span><span class="mm-kv-value" style="font-family:monospace;font-size:11px;word-break:break-all;color:var(--color-sepolia);cursor:pointer;" onclick="navigator.clipboard.writeText('${bond.bond_tx_hash}');showToast('Fragment code copied!')" title="Click to copy">${bond.bond_tx_hash}</span></div>`;
        body += `<div style="font-size:11px;color:var(--text-muted);padding:4px 0;text-align:center;">Click the code to copy it, then paste it into The Signal's Decoder Terminal</div>`;
        if (isPending && !bond.my_submitted) {
            body += `<div style="margin-top:12px;text-align:center;"><a href="/signal" class="btn btn-purple btn-small">Enter Fragment on The Signal &rarr;</a></div>`;
        }
    }

    if (bond.status === 'bonded') {
        body += `<div class="mm-section-label">--- WHAT'S NEXT ---</div>`;
        body += `<div style="font-size:12px;color:var(--text-secondary);line-height:1.5;padding:8px 0;">This bond is permanently recorded. Both captains share a crystal resonance at ${bond.landmark_name}. Ask ARIA about it — she has new things to say.</div>`;
        body += `<div style="display:flex;gap:8px;justify-content:center;margin-top:12px;flex-wrap:wrap;">`;
        body += `<a href="/aria-first-contact/replay" class="btn btn-purple btn-small">Replay First Contact</a>`;
        body += `<a href="/signal" class="btn btn-small" style="background:rgba(6,182,212,0.15);color:#06b6d4;border:1px solid rgba(6,182,212,0.3);">Enter Fragment on Signal</a>`;
        body += `</div>`;
    }

    MarsModal.show({
        title: `ARIA Bond: ${bond.landmark_name}`,
        subtitle: `<span style="color:${statusColor};">${statusLabel}</span>`,
        width: 'sm',
        body
    });
}

// Initialize
document.addEventListener('DOMContentLoaded', function() {
    handleTabFromUrl();
    loadDiscoveries();
    loadEquipment();
    initBuildCountdowns();
    renderAriaBonds();
});
