/* Expeditions - Completion, Rewards Summary, Claiming, Cost Help */
/* Depends on: expeditions.js (expeditionTimers, discoveryUpdateTimers), core.js (MarsModal, showToast) */

async function checkExpeditionCompletion(w) {
    const id = parseInt(w.dataset.expeditionId);
    try {
        const r = await fetch(`/api/expeditions/status/${id}`);
        const data = await r.json();
        if (data.success && data.complete) {
            showToast(`Expedition complete! ${data.discovery_message}`, 'success');
            clearInterval(expeditionTimers.get(id.toString()));

            // Check for ARIA bond fragment discovery
            if (data.aria_fragment) {
                setTimeout(() => showAriaFragmentDiscovery(data.aria_fragment), 1500);
            }

            setTimeout(() => {
                fetch(`/api/expeditions/discoveries/${id}`)
                    .then(r => r.json())
                    .then(data => { if (data.success) updateDiscoveryDisplay(w, data); });
            }, 1000);
        }
    } catch (e) {
        console.error('Completion check failed:', e);
    }
}

// Show ARIA fragment discovery modal - cryptic hint about /signal
function showAriaFragmentDiscovery(fragment) {
    MarsModal.show({
        title: 'Unusual Fragment Recovered',
        subtitle: fragment.landmark || 'Unknown Location',
        icon: '⚡',
        width: 'md',
        body: `
            <div class="mm-aria" style="color:#06b6d4; text-align:center;">
                "Your scout found crystalline residue that doesn't match any known Martian mineral.
                The shard resonates at a frequency identical to... your own ARIA's signature.
                But that's impossible. Unless..."
            </div>
            <div class="mm-card-accent" style="text-align:center;">
                <div class="mm-section-label">Fragment Signature</div>
                <div style="font-family:monospace; font-size:11px; color:#06b6d4; word-break:break-all; background:rgba(6,182,212,0.1); padding:10px; border-radius:4px;">
                    ${fragment.pending ? '⏳ Processing...' : '0x...'}
                </div>
                <div style="font-size:10px; color:var(--text-muted); margin-top:8px;">Check expedition history for the complete code</div>
            </div>
            <div class="mm-aria">📡 ARIA suggests: "This fragment carries an encoded pattern. I've seen similar resonances on
                <a href="/signal" style="color:#06b6d4; font-weight:600;">The Signal</a>. Perhaps the decoder there could reveal its meaning..."</div>
        `,
        footer: `<a href="/signal" class="btn btn-primary mm-btn-full" style="background:linear-gradient(135deg,#06b6d4,#0891b2); text-align:center;">Go to The Signal</a>
                 <button class="btn btn-secondary" style="flex:1;" onclick="MarsModal.hide()">Later</button>`
    });
}

async function claimAllExpeditionDiscoveries(id, e) {
    e.stopPropagation();
    try {
        showToast('Claiming discoveries...', 'info');
        const r = await fetch(`/api/expeditions/${id}/claim_all`, { method: 'POST' });
        const data = await r.json();
        if (data.success) {
            showToast(`Claimed ${data.claimed_count} items!`, 'success');
            const w = document.querySelector(`[data-expedition-id="${id}"]`);
            if (w) {
                const status = w.dataset.status;
                // If expedition was already complete (showing for unclaimed items only),
                // remove the banner entirely after claiming
                if (status === 'complete') {
                    w.style.opacity = '0.5';
                    w.style.transition = 'opacity 0.5s';
                    setTimeout(() => {
                        w.remove();
                        // Update the header count if present
                        const headerCount = document.querySelector('.active-expedition-banner');
                        if (!headerCount) {
                            // No more banners, could refresh or update UI
                        }
                    }, 500);
                } else {
                    // Still traveling - just hide the claim button and update display
                    const claimBtn = w.querySelector('.claim-all-expedition-btn');
                    if (claimBtn) claimBtn.style.display = 'none';
                    setTimeout(() => {
                        fetch(`/api/expeditions/discoveries/${id}`)
                            .then(r => r.json())
                            .then(data => { if (data.success) updateDiscoveryDisplay(w, data); });
                    }, 500);
                }
            }
        } else {
            showToast(data.error || 'Failed', 'error');
        }
    } catch {
        showToast('Network error', 'error');
    }
}

window.onbeforeunload = () => {
    expeditionTimers.forEach(t => clearInterval(t));
    discoveryUpdateTimers.forEach(t => clearInterval(t));
};

// Expedition Cost Details Modal - explains each cost component
function showExpeditionCostHelp() {
    if (typeof ItemDetailModal === 'undefined') return;

    ItemDetailModal.show({
        name: 'Expedition Cost Breakdown',
        image: null,
        category: 'How costs are calculated',
        htmlDescription: true,
        description: `
            <div style="line-height: 1.6; font-size: 13px;">
                <div style="margin-bottom: 16px; padding: 12px; background: var(--bg-tertiary); border-radius: 8px;">
                    <div style="font-weight: 700; color: var(--color-mars); margin-bottom: 6px;">Base Cost</div>
                    <div style="color: var(--text-secondary);">Fuel cost based on distance tier. Nearby (0-50km) costs less than Far (500+ km). Think of it as how many Sepolia shards the vehicle consumes.</div>
                </div>

                <div style="margin-bottom: 16px; padding: 12px; background: var(--bg-tertiary); border-radius: 8px;">
                    <div style="font-weight: 700; color: var(--color-mars); margin-bottom: 6px;">Terrain Multiplier</div>
                    <div style="color: var(--text-secondary);">Mars terrain dramatically affects costs. <strong>Planitia</strong> (flat plains) = 0.7× cheaper. <strong>Mons</strong> (mountains) = 2.5× more expensive. <strong>Rupes</strong> (cliffs) = 3.0× due to rerouting.</div>
                </div>

                <div style="margin-bottom: 16px; padding: 12px; background: var(--bg-tertiary); border-radius: 8px;">
                    <div style="font-weight: 700; color: var(--color-sepolia); margin-bottom: 6px;">Vehicle Efficiency</div>
                    <div style="color: var(--text-secondary);">Your vehicle's shard efficiency. <strong>Buggies</strong> are 10-15% cheaper (built for efficiency). <strong>Drones</strong> cost slightly more (aerial operations). <strong>Rovers</strong> are balanced.</div>
                </div>

                <div style="margin-bottom: 16px; padding: 12px; background: var(--bg-tertiary); border-radius: 8px;">
                    <div style="font-weight: 700; color: var(--color-success); margin-bottom: 6px;">Logistics Skill</div>
                    <div style="color: var(--text-secondary);">Your captain's logistics stat reduces base expedition costs. Higher logistics = better route planning = fewer shards spent.</div>
                </div>

                <div style="margin-bottom: 16px; padding: 12px; background: var(--bg-tertiary); border-radius: 8px;">
                    <div style="font-weight: 700; color: var(--color-success); margin-bottom: 6px;">Strategy Skill</div>
                    <div style="color: var(--text-secondary);">Your captain's strategy stat reduces terrain penalties. High strategy = smart path-finding around obstacles.</div>
                </div>

                <div style="margin-bottom: 16px; padding: 12px; background: var(--bg-tertiary); border-radius: 8px;">
                    <div style="font-weight: 700; color: var(--color-success); margin-bottom: 6px;">Experience Discount</div>
                    <div style="color: var(--text-secondary);">The more expeditions you've completed, the more efficient your crew becomes. Up to 20% discount for veteran explorers.</div>
                </div>

                <div style="padding: 12px; background: linear-gradient(135deg, rgba(168, 85, 247, 0.1) 0%, rgba(139, 92, 246, 0.05) 100%); border: 1px solid rgba(168, 85, 247, 0.3); border-radius: 8px;">
                    <div style="font-weight: 700; color: var(--color-sepolia); margin-bottom: 6px;">Return Visit Bonus</div>
                    <div style="color: var(--text-secondary);">Visiting a place you've already explored? Your vehicle knows the route! <strong>-50% travel time</strong> and <strong>-30% cost</strong>. Great for harvesting known sites.</div>
                </div>
            </div>
        `,
        stats: []
    });
}

// Origin site functions are in expeditions-origin.js (window exports there)
window.showExpeditionCostHelp = showExpeditionCostHelp;

// Expedition Rewards Summary Modal - shows discoveries when clicking RETURNED expedition
async function showExpeditionRewardsSummary(expeditionId) {
    const banner = document.querySelector(`[data-expedition-id="${expeditionId}"]`);
    if (!banner) return;

    // Get expedition data from banner attributes
    const destName = banner.querySelector('.active-expedition-name')?.textContent?.replace('Returned:', '').trim().split('(')[0].trim() || 'Expedition';
    const distanceKm = banner.querySelector('[style*="destination_type"]')?.textContent?.split('•')[1]?.trim() || banner.getAttribute('data-dest-lat') ? `${parseFloat(banner.dataset.destLat).toFixed(0)} km` : '';
    const vehicleType = banner.dataset.vehicleType || 'rover';
    const cargoCapacity = parseInt(banner.dataset.cargo) || 5;

    // Fetch discoveries
    try {
        const r = await fetch(`/api/expeditions/discoveries/${expeditionId}`);
        const data = await r.json();

        if (!data.success) {
            showToast('Failed to load expedition data', 'error');
            return;
        }

        const discoveries = data.unlocked_discoveries || [];
        const unclaimed = discoveries.filter(d => !d.claimed_by_user);
        const claimed = discoveries.filter(d => d.claimed_by_user);
        const fuelCost = data.fuel_cost_display || 0;

        // Calculate estimated shard values by rarity
        const rarityValues = {
            'common': 500,
            'uncommon': 1500,
            'rare': 4000,
            'epic': 10000,
            'legendary': 25000
        };

        let totalEstimatedValue = 0;
        discoveries.forEach(d => {
            totalEstimatedValue += rarityValues[d.rarity] || 500;
        });

        const netProfit = totalEstimatedValue - fuelCost;
        const isProfitable = netProfit > 0;

        // Build discovery list HTML
        const discoveryListHtml = discoveries.length > 0 ? discoveries.map(d => `
            <div style="display:flex; align-items:center; gap:10px; padding:8px; background:var(--bg-tertiary); border-radius:6px; margin-bottom:6px;">
                ${d.image_url ? `<img src="${d.image_url}" alt="" style="width:36px; height:36px; border-radius:4px; object-fit:cover;">` : `<div style="width:36px; height:36px; background:var(--bg-secondary); border-radius:4px; display:flex; align-items:center; justify-content:center; font-size:18px;">📦</div>`}
                <div style="flex:1; min-width:0;">
                    <div style="font-weight:600; font-size:12px; color:var(--text-primary); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${d.item_name}</div>
                    <div style="font-size:11px; display:flex; gap:8px; color:var(--text-muted);">
                        <span class="rarity-badge rarity-${d.rarity}" style="font-size:9px; padding:1px 5px;">${d.rarity.toUpperCase()}</span>
                        <span>${d.found_at_km} km</span>
                    </div>
                </div>
                <div style="text-align:right; font-size:11px;">
                    ${d.claimed_by_user
                        ? '<span style="color:var(--color-success);">✓ Claimed</span>'
                        : `<span style="color:var(--color-sepolia);">~${(rarityValues[d.rarity] || 500).toLocaleString()}</span>`}
                </div>
            </div>
        `).join('') : '<div style="text-align:center; color:var(--text-muted); padding:20px;">No discoveries found</div>';

        let body = `<div class="mm-stats mm-stats-3">
            <div class="mm-stat" style="text-align:center;"><div class="mm-stat-value" style="color:var(--color-mars);">${discoveries.length}</div><div class="mm-stat-label">Found</div></div>
            <div class="mm-stat" style="text-align:center;"><div class="mm-stat-value" style="color:var(--color-success);">${claimed.length}</div><div class="mm-stat-label">Claimed</div></div>
            <div class="mm-stat" style="text-align:center;"><div class="mm-stat-value" style="color:var(--color-sepolia);">${unclaimed.length}</div><div class="mm-stat-label">Unclaimed</div></div>
        </div>`;

        if (discoveries.length > 0) {
            // Enhanced shard breakdown with before/after and prominent profit/loss
            const profitColor = isProfitable ? '#4ade80' : '#f87171';
            const profitBg = isProfitable ? 'rgba(74, 222, 128, 0.1)' : 'rgba(248, 113, 113, 0.1)';
            const profitBorder = isProfitable ? 'rgba(74, 222, 128, 0.3)' : 'rgba(248, 113, 113, 0.3)';
            const profitIcon = isProfitable ? '📈' : '📉';
            const profitLabel = isProfitable ? 'PROFIT' : 'LOSS';

            body += `<div style="margin-bottom:16px;">
                <!-- Fuel Cost vs Discoveries Value -->
                <div style="display:flex; gap:8px; margin-bottom:8px;">
                    <div style="flex:1; padding:10px; background:var(--bg-tertiary); border-radius:8px; text-align:center;">
                        <div style="font-size:10px; text-transform:uppercase; color:var(--text-muted); margin-bottom:4px;">⛽ Fuel Cost</div>
                        <div style="font-size:16px; font-weight:600; color:#f87171;">-${fuelCost.toLocaleString()}</div>
                    </div>
                    <div style="flex:1; padding:10px; background:var(--bg-tertiary); border-radius:8px; text-align:center;">
                        <div style="font-size:10px; text-transform:uppercase; color:var(--text-muted); margin-bottom:4px;">💎 Found Value</div>
                        <div style="font-size:16px; font-weight:600; color:#4ade80;">+${totalEstimatedValue.toLocaleString()}</div>
                    </div>
                </div>
                <!-- NET RESULT - Prominent -->
                <div style="padding:14px; background:${profitBg}; border:2px solid ${profitBorder}; border-radius:10px; text-align:center;">
                    <div style="font-size:11px; text-transform:uppercase; letter-spacing:1px; color:${profitColor}; margin-bottom:4px;">${profitIcon} NET ${profitLabel}</div>
                    <div style="font-size:24px; font-weight:700; color:${profitColor};">
                        ${isProfitable ? '+' : ''}${netProfit.toLocaleString()} shards
                    </div>
                    ${unclaimed.length > 0 ? `<div style="font-size:11px; color:var(--text-muted); margin-top:8px;">Claim items, then extract in Inventory for shards</div>` : ''}
                </div>
            </div>`;
        }

        body += `<div class="mm-section-label">Discoveries</div><div style="max-height:200px; overflow-y:auto;">${discoveryListHtml}</div>`;

        let footer = '';
        if (unclaimed.length > 0) {
            footer += `<button class="btn btn-primary" style="flex:1;" onclick="claimAllFromModal(${expeditionId})">Claim ${unclaimed.length} Item${unclaimed.length > 1 ? 's' : ''}</button>`;
        }
        footer += `<button class="btn btn-secondary" style="${unclaimed.length > 0 ? '' : 'flex:1;'}" onclick="MarsModal.hide()">${unclaimed.length > 0 ? 'Close' : 'Done'}</button>`;

        MarsModal.show({
            title: 'Expedition Complete',
            subtitle: destName,
            icon: '🚀',
            width: 'md',
            body, footer
        });
    } catch (err) {
        console.error('Failed to load expedition rewards:', err);
        showToast('Failed to load expedition data', 'error');
    }
}

function closeExpeditionRewardsModal() { MarsModal.hide(); }

async function claimAllFromModal(expeditionId) {
    closeExpeditionRewardsModal();
    // Find the banner's claim button and trigger it
    const banner = document.querySelector(`[data-expedition-id="${expeditionId}"]`);
    if (banner) {
        const claimBtn = banner.querySelector('.claim-all-expedition-btn');
        if (claimBtn) {
            claimBtn.click();
        } else {
            // Fallback: call claimAllExpeditionDiscoveries directly
            await claimAllExpeditionDiscoveries(expeditionId, { stopPropagation: () => {} });
        }
    }
}

window.showExpeditionRewardsSummary = showExpeditionRewardsSummary;
window.closeExpeditionRewardsModal = closeExpeditionRewardsModal;
window.claimAllFromModal = claimAllFromModal;
