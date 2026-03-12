/* Inventory Page - Tab switching, Equipment, Activity Feed */

// Load page data from template (Jinja2 bridge)
const INV_PAGE_DATA = JSON.parse(document.getElementById('inventoryPageData')?.textContent || '{}');
const UI_ICONS = INV_PAGE_DATA.icons || {};

let allActivities = [];

// Tab switching
function switchInventoryTab(tab) {
    document.querySelectorAll('.inventory-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.inventory-tab-content').forEach(c => c.style.display = 'none');
    document.querySelector(`[data-tab="${tab}"]`).classList.add('active');
    document.getElementById(`tab-${tab}`).style.display = 'block';
}


// Show ARIA Bond details modal
function showAriaBondDetails(bondId) {
    // For now, just show a toast - can expand to full modal later
    showToast('Entangled Fragment - a permanent bond between two ARIAs', 'info');
}

// Load Equipment
async function loadEquipment() {
    try {
        const response = await fetch('/api/user/equipment');
        const data = await response.json();

        const owned = data.owned || [];
        document.getElementById('equipmentCount').textContent = owned.length;

        if (!owned.length) {
            document.getElementById('equipmentGrid').innerHTML = `
                <div class="empty-state">
                    <img src="${UI_ICONS.empty_equipment}" alt="" class="empty-state-icon" style="width: 48px; height: 48px; opacity: 0.5;">
                    <div class="empty-state-text">No equipment yet</div>
                    <a href="/depot" class="btn btn-purple">Browse Shop</a>
                </div>`;
            return;
        }

        document.getElementById('equipmentGrid').innerHTML = owned.map(item => {
            const isBuilding = item.status === 'building';
            const remaining = item.seconds_remaining || 0;
            let timeStr = '';
            if (isBuilding && remaining > 0) {
                const days = Math.floor(remaining / 86400);
                const hours = Math.floor((remaining % 86400) / 3600);
                if (days > 0) timeStr = `${days}d ${hours}h remaining`;
                else if (hours > 0) timeStr = `${hours}h remaining`;
                else timeStr = `${Math.floor(remaining / 60)}m remaining`;
            }
            return `
            <div class="equip-card ${isBuilding ? 'equip-building' : ''}">
                ${item.image_url ?
                    `<img src="${item.image_url}" class="equip-card-icon w-full object-cover" style="height: 120px;${isBuilding ? ' opacity: 0.6;' : ''}" loading="lazy">` :
                    `<div class="equip-card-icon"><img src="${UI_ICONS.tab_tools}" alt="${item.name}" style="width: 40px; height: 40px;"></div>`}
                ${isBuilding ? `<div class="equip-building-badge">🔧 Building</div>` : ''}
                <div class="equip-card-content">
                    <div class="equip-card-name">${item.name}</div>
                    <div class="equip-card-cat">${item.category}</div>
                    ${isBuilding ? `<div class="equip-build-time">⏱️ ${timeStr}</div>` : ''}
                    <div class="equip-card-desc">${item.description}</div>
                    ${!isBuilding && item.effects ? `
                        <div class="equip-card-effects">
                            <div class="equip-bonuses-label">BONUSES</div>
                            ${formatEffects(item.effects)}
                        </div>` : ''}
                    ${isBuilding ? `<div class="equip-card-effects" style="opacity: 0.5;"><div class="equip-bonuses-label">BONUSES (when complete)</div>${formatEffects(item.effects)}</div>` : ''}
                    <div class="equip-card-acquired">
                        ${isBuilding ? 'Under construction' : (item.purchased_at ? `Acquired ${new Date(item.purchased_at).toLocaleDateString()}` : 'Equipped')}
                    </div>
                </div>
            </div>`;
        }).join('');
    } catch (error) {
        console.error('Failed to load equipment:', error);
    }
}

// formatEffects() is now in discovery_utils.js (shared)

// Load Activity
async function loadActivity() {
    try {
        const response = await fetch('/api/user/all_activity');
        const data = await response.json();

        allActivities = data.activities || [];
        document.getElementById('activityCount').textContent = allActivities.length;

        if (!allActivities.length) {
            document.getElementById('activityFeed').innerHTML = `
                <div class="empty-state">
                    <img src="${UI_ICONS.chart_activity}" alt="" class="empty-state-icon" style="width: 48px; height: 48px; opacity: 0.5;">
                    <div class="empty-state-text">No activity yet</div>
                </div>`;
            return;
        }

        renderActivity(allActivities);
    } catch (error) {
        console.error('Failed to load activity:', error);
    }
}

function renderActivity(activities) {
    const container = document.getElementById('activityFeed');

    container.innerHTML = activities.map(activity => {
        const info = getActivityInfo(activity);
        const timestamp = new Date(activity.timestamp).toLocaleString('en-US', {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
        });

        return `
            <div class="activity-item">
                <div class="activity-icon ${info.iconClass}">${info.icon}</div>
                <div class="activity-content">
                    <div class="activity-title">${info.title}</div>
                    <div class="activity-details">${info.details}</div>
                    <div class="activity-meta">${timestamp}${info.txHash ? ` • <a href="https://sepolia.etherscan.io/tx/${info.txHash}" target="_blank" class="activity-tx-link">View TX</a>` : ''}</div>
                </div>
                ${info.amount ? `<div class="activity-amount ${info.amountClass}">${info.amount}</div>` : ''}
            </div>
        `;
    }).join('');
}

function getActivityIcon(iconKey) {
    return `<img src="${UI_ICONS[iconKey]}" alt="" style="width: 20px; height: 20px;">`;
}

function getActivityInfo(activity) {
    let icon = getActivityIcon('chart_activity'), iconClass = 'action', title = 'Activity', details = '', amount = '', amountClass = '', txHash = '';

    if (activity.type === 'depot_transaction') {
        const pt = activity.data.purchase_type;
        const itemDetails = activity.data.item_details || {};
        txHash = activity.data.tx_hash;

        if (pt === 'infrastructure_income') {
            const structures = itemDetails.structures || [];
            const structCount = structures.length || 1;
            icon = getActivityIcon('activity_income'); iconClass = 'income';
            title = `Harvested Shards from ${structCount} generator${structCount > 1 ? 's' : ''}`;
            details = structures.length ? structures.map(s => s.name || s.type).join(', ') : 'Solar Array generation';
            amount = `+${activity.data.amount_display.toFixed(1)}`;
            amountClass = 'positive';
        }
        else if (pt === 'infrastructure_completion') {
            icon = getActivityIcon('activity_construction'); iconClass = 'income';
            title = 'Infrastructure Completion Bonus';
            details = itemDetails.structure_name || 'Structure completed and operational';
            amount = `+${activity.data.amount_display.toFixed(1)}`;
            amountClass = 'positive';
        }
        else if (pt === 'stat_reroll') {
            icon = getActivityIcon('dice_random'); iconClass = 'expense';
            title = 'Captain Attribute Reroll';
            if (itemDetails.old_stats && itemDetails.new_stats) {
                const oldTotal = Object.values(itemDetails.old_stats).reduce((a, b) => a + b, 0);
                const newTotal = Object.values(itemDetails.new_stats).reduce((a, b) => a + b, 0);
                details = `Stats changed: ${oldTotal} → ${newTotal} total points`;
            } else {
                details = 'Randomized captain attributes';
            }
            amount = `-${activity.data.amount_display.toFixed(1)}`;
            amountClass = 'negative';
        }
        else if (pt === 'character_modification') {
            icon = getActivityIcon('edit_pencil'); iconClass = 'expense';
            title = 'Captain Appearance Modified';
            details = itemDetails.prompt ? `"${itemDetails.prompt.substring(0, 60)}${itemDetails.prompt.length > 60 ? '...' : ''}"` : 'AI-generated appearance modification';
            amount = `-${activity.data.amount_display.toFixed(1)}`;
            amountClass = 'negative';
        }
        else if (pt === 'video_generation') {
            icon = getActivityIcon('video_film'); iconClass = 'expense';
            title = 'Captain Video Generated';
            details = 'Animated captain video created';
            amount = `-${activity.data.amount_display.toFixed(1)}`;
            amountClass = 'negative';
        }
        else if (pt === 'expedition_start') {
            icon = getActivityIcon('rocket_launch'); iconClass = 'expedition';
            title = `Expedition to ${itemDetails.destination || 'Unknown'}`;
            details = `Distance: ${itemDetails.distance_km || '?'} km • Travel time: ${itemDetails.travel_days || '?'} days`;
            amount = `-${activity.data.amount_display.toFixed(1)}`;
            amountClass = 'negative';
        }
        else if (pt === 'expedition_discovery') {
            icon = getActivityIcon('gift_box'); iconClass = 'income';
            title = 'Expedition Discovery Claimed';
            details = itemDetails.item_name || 'Items collected from expedition';
            amount = `+${activity.data.amount_display.toFixed(1)}`;
            amountClass = 'positive';
        }
        else if (pt === 'infrastructure_build') {
            icon = getActivityIcon('wrench_repair'); iconClass = 'expense';
            title = `Built ${itemDetails.structure_name || 'Structure'}`;
            details = itemDetails.build_time ? `Build time: ${itemDetails.build_time}` : 'Construction started';
            amount = `-${activity.data.amount_display.toFixed(1)}`;
            amountClass = 'negative';
        }
        else if (pt === 'equipment_purchase') {
            icon = getActivityIcon('shopping_cart'); iconClass = 'expense';
            title = `Purchased ${itemDetails.item_name || 'Equipment'}`;
            details = itemDetails.category || 'Expedition equipment';
            amount = `-${activity.data.amount_display.toFixed(1)}`;
            amountClass = 'negative';
        }
        else {
            icon = getActivityIcon('shop_storefront'); iconClass = 'expense';
            title = 'Depot Transaction';
            details = pt.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
            amount = activity.data.amount_display > 0 ? `-${activity.data.amount_display.toFixed(1)}` : '';
            amountClass = 'negative';
        }
    }
    else if (activity.type === 'character_image') {
        icon = activity.data.is_original ? getActivityIcon('camera_photo') : getActivityIcon('edit_pencil');
        iconClass = 'action';
        title = activity.data.is_original ? 'Captain Created' : 'Captain Modified';
        details = activity.data.prompt ? `"${activity.data.prompt.substring(0, 60)}..."` : 'Captain portrait generated';
    }
    else if (activity.type === 'character_video') {
        icon = getActivityIcon('video_film'); iconClass = 'action';
        title = 'Captain Video Created';
        details = 'Animated video generated';
    }
    else if (activity.type === 'expedition') {
        icon = getActivityIcon('rocket_launch'); iconClass = 'expedition';
        title = `Expedition: ${activity.destination || 'Unknown'}`;
        details = `Status: ${activity.status || 'In progress'}`;
    }

    return { icon, iconClass, title, details, amount, amountClass, txHash };
}

function filterActivity(filter) {
    if (filter === 'all') {
        renderActivity(allActivities);
        return;
    }

    const filtered = allActivities.filter(a => {
        if (filter === 'income') {
            return a.type === 'depot_transaction' &&
                ['infrastructure_income', 'infrastructure_completion', 'expedition_discovery'].includes(a.data?.purchase_type);
        }
        if (filter === 'expenses') {
            return a.type === 'depot_transaction' &&
                !['infrastructure_income', 'infrastructure_completion', 'expedition_discovery'].includes(a.data?.purchase_type);
        }
        if (filter === 'expeditions') {
            return a.type === 'expedition' ||
                (a.type === 'depot_transaction' && a.data?.purchase_type?.includes('expedition'));
        }
        return true;
    });

    renderActivity(filtered);
}

// ============================================================================
// SHARD IT ALL - Bulk extraction of common/uncommon discoveries
// ============================================================================

// Initialize
document.addEventListener('DOMContentLoaded', function() {
    loadDiscoveries();
    loadEquipment();
    loadActivity();
});

