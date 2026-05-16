
// — DASHBOARD.JS - Mission Control —
let accumulatedData = null, updateInterval = null, nextUpdateCountdown = null;

// Check if user is authenticated (set by template)
const isAuthenticated = typeof window.userAuthenticated !== 'undefined' ? window.userAuthenticated : false;

window.addEventListener('DOMContentLoaded', function() {
    // Only call authenticated APIs if user is logged in
    if (isAuthenticated) {
        checkInfrastructureIncome(); loadInfrastructureCount(); loadRecentDiscoveries();
        startPolling();
        // Fleet status ETAs and Review Haul buttons
        updateFleetETAs();
        setInterval(updateFleetETAs, 1000);
        initFleetReviewButtons();
        initLastBuggyExpedition();
        // Auto-popup haul modal for first unseen returned expedition (non-buggy fallback)
        autoShowReturnedExpedition();
    } else {
        // Anonymous user - run demo animations
        runAnonDemoAnimations();
    }
});

// Fleet Status ETA countdown
function updateFleetETAs() {
    document.querySelectorAll('.fleet-eta').forEach(el => {
        const etaIso = el.dataset.eta;
        if (!etaIso) { el.textContent = '--'; return; }
        const eta = new Date(etaIso);
        const now = new Date();
        const diffMs = eta - now;
        if (diffMs <= 0) {
            el.textContent = 'Arrived!';
            el.style.color = 'var(--color-success)';
            // Could trigger a refresh here to update status
            return;
        }
        const hours = Math.floor(diffMs / 3600000);
        const mins = Math.floor((diffMs % 3600000) / 60000);
        const secs = Math.floor((diffMs % 60000) / 1000);
        if (hours > 0) {
            el.textContent = `${hours}h ${mins}m`;
        } else if (mins > 0) {
            el.textContent = `${mins}m ${secs}s`;
        } else {
            el.textContent = `${secs}s`;
        }
    });
}

// Fleet Review Haul Modal — uses unified MarsModal
function initFleetReviewButtons() {
    document.querySelectorAll('.fleet-review-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const expeditionId = parseInt(btn.dataset.expeditionId) || 0;
            if (expeditionId > 0) {
                showExpeditionHaulModal(expeditionId, true);
            } else {
                showFleetHaulModalFallback(btn.dataset);
            }
        });
    });
}

function initLastBuggyExpedition() {
    const card = document.querySelector('.lbe-card');
    if (!card) return;
    const expId = parseInt(card.dataset.expeditionId) || 0;
    if (expId > 0) {
        card.addEventListener('click', () => showExpeditionHaulModal(expId, true));
    }
}

function autoShowReturnedExpedition() {
    // Auto-pop haul modal for the first returned expedition on page load
    // Skip expeditions already dismissed this session
    const dismissed = JSON.parse(sessionStorage.getItem('dismissedHauls') || '[]');
    const btns = document.querySelectorAll('.fleet-review-btn');
    for (const btn of btns) {
        const expId = parseInt(btn.dataset.expeditionId) || 0;
        if (expId > 0 && !dismissed.includes(expId)) {
            setTimeout(() => showExpeditionHaulModal(expId, true), 500);
            break;
        }
    }
}

async function showExpeditionHaulModal(expeditionId, showClaimButton = true) {
    MarsModal.show({ title: 'Loading...', body: '<div style="text-align:center;padding:20px;color:var(--text-muted);">Fetching expedition data...</div>', width: 'sm' });
    try {
        const resp = await fetch(`/api/expeditions/${expeditionId}/haul`);
        const data = await resp.json();
        if (!data.success) { MarsModal.hide(); if (data.error !== 'Unauthorized') showToast(data.error || 'Failed to load', 'error'); return; }
        renderHaulModal(data, showClaimButton);
    } catch (e) { MarsModal.hide(); }
}

function renderHaulModal(data, showClaimButton) {
    const exp = data.expedition;
    const discoveries = data.discoveries || [];
    // Distance bonus
    let bonusMult = 1, bonusLabel = '';
    if (exp.distance_km >= 2000) { bonusMult = 10; bonusLabel = 'Legendary Journey'; }
    else if (exp.distance_km >= 1000) { bonusMult = 5; bonusLabel = 'Frontier Run'; }
    else if (exp.distance_km >= 500) { bonusMult = 3; bonusLabel = 'Deep Expedition'; }
    else if (exp.distance_km >= 200) { bonusMult = 2; bonusLabel = 'Long Haul'; }
    // Travel time
    let travelStr = '';
    if (exp.travel_hours >= 24) travelStr = Math.floor(exp.travel_hours / 24) + 'd ' + Math.round(exp.travel_hours % 24) + 'h';
    else if (exp.travel_hours >= 1) travelStr = Math.round(exp.travel_hours) + ' hours';
    else travelStr = Math.round(exp.travel_hours * 60) + ' minutes';
    // Body: summary KVs
    const vehicle = (exp.vehicle_type || 'Rover').replace('_', ' ').replace(/\b\w/g, c => c.toUpperCase());
    let body = `<div class="mm-section-label">Expedition Summary</div>`;
    body += `<div class="mm-kv"><span class="mm-kv-label">Travel Time</span><span class="mm-kv-value">${travelStr}</span></div>`;
    body += `<div class="mm-kv"><span class="mm-kv-label">Shards Earned</span><span class="mm-kv-value" style="color:var(--color-warning);">${Math.round(exp.shards_earned).toLocaleString()}</span></div>`;
    if (exp.sv_earned) body += `<div class="mm-kv"><span class="mm-kv-label">SV Earned</span><span class="mm-kv-value" style="color:var(--color-success);">+${exp.sv_earned.toLocaleString()} SV</span></div>`;
    if (bonusLabel) body += `<div class="mm-kv"><span class="mm-kv-label">Distance Bonus</span><span class="mm-kv-value" style="color:var(--color-warning);">${bonusMult}&times; ${bonusLabel}</span></div>`;
    // Discoveries grid
    body += `<hr class="mm-divider"><div class="mm-section-label">Discoveries (${discoveries.length})</div>`;
    if (discoveries.length > 0) {
        body += '<div class="mm-stats" style="grid-template-columns:repeat(auto-fill,minmax(80px,1fr));">';
        body += discoveries.map(d => {
            const img = d.image_url ? `<img src="${d.image_url}" alt="" style="width:56px;height:56px;border-radius:6px;object-fit:cover;display:block;margin:0 auto 6px;">` : '';
            return `<div class="mm-stat" style="text-align:center;cursor:pointer;" title="${d.description || d.item_name}">${img}<div style="font-size:10px;color:var(--text-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${d.item_name}</div><div style="font-size:9px;font-weight:600;color:var(--text-muted);margin-top:2px;">${(d.rarity || 'common').toUpperCase()}</div></div>`;
        }).join('');
        body += '</div>';
    } else {
        body += '<div style="text-align:center;padding:20px;color:var(--text-muted);font-size:13px;">No discoveries this expedition</div>';
    }
    // Footer button
    let footer = '';
    if (showClaimButton && data.unclaimed_count > 0) {
        footer = `<button class="btn btn-primary mm-btn-full" id="mmActionBtn">Claim ${data.unclaimed_count} Discoveries</button>`;
    } else {
        footer = `<button class="btn btn-secondary mm-btn-full" onclick="MarsModal.hide()">Close</button>`;
    }
    MarsModal.show({
        hero: exp.destination_image || null, heroHeight: 140,
        badge: 'Mission Complete', theme: 'success',
        title: `${vehicle} returned!`,
        subtitle: `From ${exp.destination} &middot; ${exp.distance_km.toLocaleString()} km`,
        body, footer, width: 'sm'
    });
    // Mark as dismissed so auto-popup won't re-show this expedition
    const dismissed = JSON.parse(sessionStorage.getItem('dismissedHauls') || '[]');
    if (!dismissed.includes(exp.id)) { dismissed.push(exp.id); sessionStorage.setItem('dismissedHauls', JSON.stringify(dismissed)); }
    if (showClaimButton && data.unclaimed_count > 0) {
        const btn = document.getElementById('mmActionBtn');
        if (btn) btn.onclick = () => claimFleetDiscoveries(exp.id);
    }
}

function showFleetHaulModalFallback(data) {
    renderHaulModal({
        expedition: {
            id: 0, destination: data.destination || 'Unknown', destination_image: null,
            distance_km: parseInt(data.distance) || 0, vehicle_type: data.vehicle || 'rover',
            shards_earned: parseFloat(data.shards) || 0, travel_hours: 2.5, status: 'complete'
        },
        discoveries: JSON.parse(data.discoveries || '[]').map((d, i) => ({
            id: i, item_name: `${d.rarity} Discovery`, rarity: d.rarity, image_url: null, description: '', enhanced_value: 100
        })).flatMap(d => Array(d.count || 1).fill(d)),
        unclaimed_count: parseInt(data.totalDiscoveries) || 0
    }, true);
}

async function claimFleetDiscoveries(expeditionId) {
    try {
        showToast('Claiming discoveries...', 'info');
        const resp = await fetch(`/api/expeditions/${expeditionId}/claim_all`, { method: 'POST' });
        const data = await resp.json();
        if (data.success) {
            showToast(`Claimed ${data.claimed_count} discoveries!`, 'success');
            MarsModal.hide();
            setTimeout(() => location.reload(), 500);
        } else { showToast(data.error || 'Failed to claim', 'error'); }
    } catch (e) { showToast('Network error', 'error'); }
}

window.showExpeditionHaulModal = showExpeditionHaulModal;

// Polling control - pause when tab is hidden to save server resources
function startPolling() {
    updateInterval = setInterval(checkInfrastructureIncome, 60000);
    let sec = 60;
    nextUpdateCountdown = setInterval(() => { sec--; if (sec <= 0) sec = 60; const el = $('nextUpdate'); if (el) el.textContent = sec + 's'; }, 1000);
}

function stopPolling() {
    if (updateInterval) { clearInterval(updateInterval); updateInterval = null; }
    if (nextUpdateCountdown) { clearInterval(nextUpdateCountdown); nextUpdateCountdown = null; }
}

// Pause polling when tab is hidden, resume when visible
document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        stopPolling();
    } else if (isAuthenticated && !updateInterval) {
        // Tab became visible again - refresh immediately and restart polling
        checkInfrastructureIncome();
        startPolling();
    }
});

window.onbeforeunload = () => stopPolling();

// Demo animations for anonymous users
function runAnonDemoAnimations() {
    const counter = $('anonSepoliaCounter');
    if (counter) {
        let value = 0;
        const target = window.previewBalance || 50; // Use actual preview from backend
        const duration = 1500;
        const steps = 45;
        const increment = target / steps;
        const interval = setInterval(() => {
            value += increment;
            if (value >= target) { value = target; clearInterval(interval); }
            counter.textContent = value.toFixed(1);
        }, duration / steps);
    }
}

// Mining functions for anonymous users
async function triggerMining(e) {
    const btn = e.target; showProcessing('Claiming Shard cache...'); btn.disabled = true;
    try { const data = await apiPost('/api/asteroid_impact'); if (data.success) location.reload(); else { hideProcessing(); showError(data.error || 'Mining failed'); btn.disabled = false; } }
    catch (err) { hideProcessing(); showError('Network error: ' + err.message); btn.disabled = false; }
}

async function claimAdditionalCache(e) {
    const btn = e.target; btn.disabled = true; showProcessing('Searching for additional deposits...');
    try { await apiPost('/api/clear_session_wallet'); const data = await apiPost('/api/asteroid_impact'); if (data.success) { showToast('Found more Shards!', 'success', 'Additional Cache!'); setTimeout(() => location.reload(), 1500); } else { hideProcessing(); showError(data.error || 'No caches available'); btn.disabled = false; } }
    catch (err) { hideProcessing(); showError('Network error: ' + err.message); btn.disabled = false; }
}

// Expose to window for onclick handlers
window.triggerMining = triggerMining;
window.claimAdditionalCache = claimAdditionalCache;

async function loadInfrastructureCount() {
    try { const r = await fetch('/api/infrastructure/accumulated'); const data = await r.json(); const el = $('infrastructureCount'); if (el) el.textContent = data.details?.length || 0; }
    catch (e) { console.error('Infrastructure count failed:', e); }
}

async function checkInfrastructureIncome() {
    try {
        const r = await fetch('/api/infrastructure/accumulated'); const data = await r.json();
        const hasData = data.total_accumulated > 0 || data.details?.length > 0;
        const content = $('infrastructureContent'), empty = $('infrastructureEmpty');
        if (hasData) {
            content.style.display = 'block'; empty.style.display = 'none';

            // Main accumulated amount
            $('accumulatedAmount').textContent = data.total_accumulated.toFixed(1);
            // Only count hours from structures that actually generate (hourly_rate > 0)
            const generatingDetails = data.details.filter(d => d.hourly_rate > 0);
            const avgHours = generatingDetails.length > 0
                ? generatingDetails.reduce((s, d) => s + d.hours_elapsed, 0) / generatingDetails.length
                : 0;
            $('hoursElapsed').textContent = avgHours.toFixed(1);
            $('totalAllTime').textContent = data.total_all_time.toFixed(1);

            // Rate breakdown (NEW)
            const rb = data.rate_breakdown || {};
            const bonuses = data.bonuses_applied || {};
            const generators = data.generators_breakdown || [];

            // Build generators list dynamically
            const genContainer = $('generatorsBreakdown');
            if (genContainer) {
                const lat = data.latitude || 0;
                genContainer.innerHTML = generators.map(g => {
                    const latNote = g.latitude_affected ? ` <span style="opacity:0.7">(${Math.abs(lat).toFixed(1)}°)</span>` : '';
                    const lvl = g.level ? ` <span style="color:var(--color-sepolia);font-size:10px;">Lv${g.level}/${g.max_level || '?'}</span>` : '';
                    return `<div style="display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--border-default);">
                        <span class="card-label" style="font-size: 12px;">${g.icon} ${g.name}${lvl}${latNote}</span>
                        <span class="card-value" style="font-size: 13px; font-weight: 600;">${g.hourly_rate.toFixed(1)}/hr</span>
                    </div>`;
                }).join('');
            }

            // Base total (sum of all generator rates)
            const baseRateEl = $('baseHourlyRate');
            if (baseRateEl) baseRateEl.textContent = (rb.base_hourly_rate || 0).toFixed(1) + '/hr';
            // Show base total row only if multiple generators
            const baseTotalRow = $('baseRateTotalRow');
            if (baseTotalRow) baseTotalRow.style.display = generators.length > 1 ? 'flex' : 'none';

            // Power equipment row (show if mult > 1) - displays the actual item name
            const solarRow = $('solarUpgradeRow');
            if (solarRow) {
                const source = bonuses.passive_income_source;
                if (source && source.mult > 1.0) {
                    solarRow.style.display = 'flex';
                    const label = $('powerEquipmentLabel');
                    if (label && source.name) {
                        const levelName = source.level_name ? ` (${source.level_name})` : '';
                        // Highlight "LvN" in sepolia color to show it's upgradeable
                        const nameHtml = source.name.replace(/(Lv\d+)/, '<span style="color:var(--color-sepolia);">$1</span>');
                        label.innerHTML = (source.icon || '') + ' ' + nameHtml + levelName;
                    }
                    // Show the Shard Generator's own mult (not combined with tech)
                    $('solarUpgradeMult').textContent = '× ' + source.mult.toFixed(2);
                } else {
                    solarRow.style.display = 'none';
                }
            }

            // Tech tree passive bonus row (show if tech has boosted passive income)
            const techRow = $('techPassiveRow');
            if (techRow) {
                if (bonuses.tech_passive_mult > 1.0) {
                    techRow.style.display = 'flex';
                    $('techPassiveMult').textContent = '× ' + bonuses.tech_passive_mult.toFixed(2);
                } else {
                    techRow.style.display = 'none';
                }
            }

            // Fusion reactor row (show if mult > 1)
            const fusionRow = $('fusionReactorRow');
            if (fusionRow) {
                if (bonuses.all_generation_mult > 1.0) {
                    fusionRow.style.display = 'flex';
                    $('fusionReactorMult').textContent = '× ' + bonuses.all_generation_mult.toFixed(1);
                } else {
                    fusionRow.style.display = 'none';
                }
            }

            // Mining drone row (show if base > 0)
            const droneRow = $('miningDroneRow');
            if (droneRow) {
                if (bonuses.passive_income_base > 0) {
                    droneRow.style.display = 'flex';
                    $('miningDroneBonus').textContent = '+ ' + bonuses.passive_income_base + '/hr';
                } else {
                    droneRow.style.display = 'none';
                }
            }

            // Scientist bonus row (analysis stat → shard gen boost)
            const scientistRow = $('scientistBonusRow');
            if (scientistRow) {
                if (bonuses.scientist_shard_mult > 1.0) {
                    scientistRow.style.display = 'flex';
                    $('scientistBonusMult').textContent = '× ' + bonuses.scientist_shard_mult.toFixed(2);
                } else {
                    scientistRow.style.display = 'none';
                }
            }

            // Bug #1423: Signal Bonus row (origin sites)
            const signalRow = $('signalBonusRow');
            if (signalRow) {
                const sigShards = data.signal_shards_per_hour || 0;
                const sigSites = (data.signal_bonus && data.signal_bonus.sites_count) || bonuses.signal_sites_count || 0;
                if (sigShards > 0) {
                    signalRow.style.display = 'flex';
                    $('signalBonusRate').textContent = '+ ' + sigShards.toFixed(1) + '/hr';
                    const sitesEl = $('signalBonusSites');
                    if (sitesEl) sitesEl.textContent = sigSites > 0 ? '(' + sigSites + ' site' + (sigSites !== 1 ? 's' : '') + ')' : '';
                } else {
                    signalRow.style.display = 'none';
                }
            }

            // Bug #1423: Fragment Bond Bonus row (ARIA bond shards mult delta)
            const fragShardsRow = $('fragmentBondShardsRow');
            if (fragShardsRow) {
                const fragShards = data.bond_shards_per_hour || 0;
                const fragMult = data.bond_shards_mult || 1.0;
                if (fragShards > 0 || fragMult > 1.0) {
                    fragShardsRow.style.display = 'flex';
                    $('fragmentBondShardsRate').textContent = '+ ' + fragShards.toFixed(1) + '/hr';
                    const mEl = $('fragmentBondShardsMult');
                    if (mEl) mEl.textContent = fragMult > 1.0 ? '(× ' + fragMult.toFixed(2) + ')' : '';
                } else {
                    fragShardsRow.style.display = 'none';
                }
            }

            // Environmental Impact row (dust, temperature, latitude factors)
            const envRow = $('envImpactRow');
            const envFactors = rb.mars_env_factors;
            if (envRow && envFactors) {
                envRow.style.display = 'block';
                const combinedPct = Math.round(envFactors.combined * 100);
                $('envCombinedMult').textContent = combinedPct + '% effective';
                const detailEl = $('envFactorsDetail');
                if (detailEl) {
                    const tags = [
                        {label: 'Dust', value: Math.round(envFactors.dust * 100) + '%', note: envFactors.dust_condition},
                        {label: 'Temp', value: Math.round(envFactors.temperature * 100) + '%', note: envFactors.temp_celsius + '°C'},
                        {label: 'Latitude', value: Math.round(envFactors.latitude * 100) + '%', note: Math.abs(data.latitude || 0).toFixed(1) + '°'},
                    ];
                    detailEl.innerHTML = tags.map(t =>
                        `<span style="font-size:11px;padding:2px 8px;border-radius:4px;background:rgba(var(--color-mars-rgb),0.15);color:var(--text-secondary);">${t.label}: ${t.value} <span style="opacity:0.7">(${t.note})</span></span>`
                    ).join('');
                }
            }

            // Effective rate (the actual average this period)
            const effectiveEl = $('effectiveRate');
            if (effectiveEl) effectiveEl.textContent = (rb.actual_avg_rate || 0).toFixed(1) + '/hr';

            // Day/night efficiency (now pure day/night cycle, env separated out)
            const dayNightEl = $('dayNightEfficiency');
            if (dayNightEl) dayNightEl.textContent = (rb.day_night_efficiency || 100) + '%';

            // Science Value generation card (below discoveries)
            const svCard = $('svGenerationCard');
            const svRateEl = $('svRate');
            const svAccEl = $('svAccumulated');
            const svBreakdownEl = $('svBreakdown');
            if (data.sv_hourly_rate > 0) {
                if (svCard) svCard.style.display = 'block';
                if (svRateEl) svRateEl.textContent = data.sv_hourly_rate.toFixed(1);
                if (svAccEl) svAccEl.textContent = Math.round(data.sv_accumulated);
                // Bug #1401: mirror the Record SV affordance from the Crew
                // tab — enable only when there's ≥1 SV accumulated.
                const svRecordBtn = $('svRecordBtn');
                if (svRecordBtn) {
                    const hasSv = (data.sv_accumulated || 0) >= 1;
                    svRecordBtn.disabled = !hasSv;
                    svRecordBtn.style.opacity = hasSv ? '1' : '0.5';
                    svRecordBtn.style.cursor = hasSv ? 'pointer' : 'not-allowed';
                }
                // SV source breakdown
                if (svBreakdownEl && data.sv_sources) {
                    let html = '';
                    for (const src of data.sv_sources) {
                        html += `<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:11px;"><span style="color:var(--text-secondary);">${src.name} Lv${src.level}</span><span style="color:var(--color-aria);font-weight:600;">${src.rate.toFixed(1)} SV/hr</span></div>`;
                    }
                    if (data.sv_scientist_name && data.sv_scientist_extra > 0) {
                        html += `<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:11px;border-top:1px solid rgba(255,255,255,0.06);margin-top:2px;padding-top:4px;"><span style="color:var(--text-secondary);">${data.sv_scientist_name} (Analysis) ×${data.sv_scientist_bonus.toFixed(1)}</span><span style="color:var(--color-aria);font-weight:600;">+${data.sv_scientist_extra.toFixed(1)} SV/hr</span></div>`;
                    }
                    // Bug #1423: surface Signal + Fragment Bond as their own line items
                    const sigSv = data.signal_sv_per_hour || 0;
                    if (sigSv > 0) {
                        html += `<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:11px;"><span style="color:var(--text-secondary);">Signal Network</span><span style="color:#fbbf24;font-weight:600;">+${sigSv.toFixed(1)} SV/hr</span></div>`;
                    }
                    const bondSv = data.bond_sv_per_hour || 0;
                    const bondSvMult = data.bond_sv_mult || 1.0;
                    if (bondSv > 0 || bondSvMult > 1.0) {
                        html += `<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:11px;"><span style="color:var(--text-secondary);">Fragment Bond ${bondSvMult > 1.0 ? '×' + bondSvMult.toFixed(2) : ''}</span><span style="color:#06b6d4;font-weight:600;">+${bondSv.toFixed(1)} SV/hr</span></div>`;
                    }
                    svBreakdownEl.innerHTML = html;
                }
            }

            // Show/hide dust storm warning based on whether any structure is at cap
            const dustWarning = $('dustStormWarning'), normalMsg = $('harvestNormal');
            if (data.any_at_cap) {
                if (dustWarning) dustWarning.style.display = 'block';
                if (normalMsg) normalMsg.style.display = 'none';
            } else {
                if (dustWarning) dustWarning.style.display = 'none';
                if (normalMsg) normalMsg.style.display = 'block';
            }

            const btn = $('claimButton');
            if (btn) {
                btn.disabled = !data.can_claim;
                // Update button text based on state
                if (data.any_at_cap && data.can_claim) {
                    btn.textContent = '🌫️ Harvest & Clean Panels';
                    btn.style.background = 'var(--gradient-mars)';
                } else if (data.can_claim) {
                    btn.textContent = '⚡ Harvest';
                    btn.style.background = 'var(--gradient-success)';
                } else {
                    btn.textContent = 'Keep Generating (min: 0.1)';
                    btn.style.background = 'var(--gradient-secondary)';
                }
            }

            accumulatedData = data;
        } else { content.style.display = 'none'; empty.style.display = 'block'; }
    } catch (e) { console.error('Infrastructure check failed:', e); }
}

async function loadRecentDiscoveries() {
    const container = $('recentDiscoveriesContainer'), content = $('discoveriesContent'), empty = $('discoveriesEmpty'), claimBtn = $('claimAllButton'), countText = $('discoveryCountText');
    if (!container || !content) return;
    try {
        const r = await fetch('/api/expeditions/recent_discoveries'); const data = await r.json();
        // Use total_unclaimed for the real count across ALL expeditions
        const totalUnclaimed = data.total_unclaimed || data.count || 0;
        if (!data.success || totalUnclaimed === 0) { content.style.display = 'none'; empty.style.display = 'block'; return; }
        const disc = data.discoveries, shownCount = disc.length;
        content.style.display = 'block'; empty.style.display = 'none';
        if (countText) { countText.textContent = `${totalUnclaimed} discoveries`; countText.style.color = 'var(--color-success)'; }
        if (claimBtn && totalUnclaimed > 0) { claimBtn.style.display = 'block'; claimBtn.textContent = `📦 Claim All (${totalUnclaimed})`; }
        container.innerHTML = disc.slice(0, 3).map(d => `<div class="discovery-card-compact" style="transition:all 0.2s;cursor:pointer;" data-discovery-id="${d.discovery_item_id}" onmouseover="this.style.transform='translateY(-2px)';this.style.boxShadow='0 4px 12px rgba(0,0,0,0.2)';" onmouseout="this.style.transform='';this.style.boxShadow='';">${d.image_url ? `<img src="${d.image_url}" class="discovery-image-small" alt="${d.item_name}">` : '<div class="discovery-image-small" style="display:flex;align-items:center;justify-content:center;font-size:24px;">📦</div>'}<div class="discovery-info"><div class="discovery-name">${d.item_name}<span class="rarity-badge rarity-${d.rarity}">${d.rarity}</span></div><div class="discovery-details">${d.found_at_km > 0 ? `Found at ${d.found_at_km.toLocaleString()}km` : `From ${d.destination_name || 'expedition'}`}</div></div><div class="discovery-value"><div class="discovery-value-number">${d.enhanced_value}</div><div class="discovery-value-label">Sci Value</div></div></div>`).join('') + (totalUnclaimed > shownCount ? `<div style="text-align:center;padding:12px;font-size:13px;color:rgba(0,0,0,0.7);background:rgba(255,255,255,0.2);border-radius:8px;margin-top:8px;">Showing ${shownCount} of ${totalUnclaimed} unclaimed</div>` : '');
        $$('#recentDiscoveriesContainer .discovery-card-compact').forEach(c => c.onclick = function() { const id = this.dataset.discoveryId; if (id) showDiscoveryDetails(parseInt(id)); });
    } catch (e) { console.error('Discoveries failed:', e); content.style.display = 'none'; empty.style.display = 'block'; }
}

async function claimAllDiscoveries() {
    const btn = $('claimAllButton'), content = $('discoveriesContent');
    if (btn) btn.disabled = true; if (content) content.style.opacity = '0.5';
    showToast('Claiming discoveries...', 'success', '🎉 Secured', 4000);
    setTimeout(() => { if (content) content.style.display = 'none'; $('discoveriesEmpty').style.display = 'block'; }, 1000);
    try { const data = await apiPost('/api/expeditions/claim_all_discoveries');
        if (data.success) showToast(`${data.claimed_count} discoveries secured (Value: ${data.total_value})`, 'info', '', 3000);
        else { showToast(`Error: ${data.error}`, 'error'); setTimeout(() => location.reload(), 2000); }
    } catch { showToast('Network error.', 'error'); setTimeout(() => location.reload(), 2000); }
    setTimeout(() => location.reload(), 3000);
}

window.claimAllDiscoveries = claimAllDiscoveries;

// — ARIA HINT (anonymous users) —
function dismissAriaHint() {
    const hint = document.getElementById('ariaHint');
    if (hint) {
        hint.style.transition = 'opacity 0.3s, transform 0.3s';
        hint.style.opacity = '0';
        hint.style.transform = 'translateY(20px)';
        setTimeout(() => hint.remove(), 300);
        localStorage.setItem('ariaHintDismissed', 'true');
    }
}

document.addEventListener('DOMContentLoaded', function() {
    if (localStorage.getItem('ariaHintDismissed')) {
        const hint = document.getElementById('ariaHint');
        if (hint) hint.remove();
    } else {
        setTimeout(dismissAriaHint, 15000);
        const orb = document.getElementById('aria-orb');
        if (orb) orb.addEventListener('click', dismissAriaHint, { once: true });
    }
});

// — BRIEFING, LIVE STATS, HARVEST (authenticated users) —
function dismissBriefing() {
    const briefing = document.getElementById('away-briefing');
    if (briefing) {
        briefing.style.transition = 'opacity 0.3s, transform 0.3s';
        briefing.style.opacity = '0';
        briefing.style.transform = 'translateY(-10px)';
        setTimeout(() => {
            briefing.style.maxHeight = '0';
            briefing.style.marginBottom = '0';
            briefing.style.padding = '0';
            briefing.style.overflow = 'hidden';
            briefing.style.border = 'none';
            setTimeout(() => briefing.remove(), 200);
        }, 250);
        // Store content-based key — re-shows only when briefing content changes (not on every game action)
        const timer = document.getElementById('briefingTimer');
        const briefingKey = timer ? (timer.dataset.briefingKey || timer.dataset.lastActivity) : '';
        localStorage.setItem('briefingDismissedFor', briefingKey || 'true');
    }
}

function formatElapsedTime(ms) {
    const seconds = Math.floor(ms / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);
    if (days > 0) return `${days}d ${hours % 24}h ago`;
    if (hours > 0) return `${hours}h ${minutes % 60}m ago`;
    if (minutes > 0) return `${minutes}m ${seconds % 60}s ago`;
    return `${(ms / 1000).toFixed(1)}s ago`;
}

function startBriefingTimer() {
    const timerEl = document.getElementById('briefingTimer');
    if (!timerEl) return;
    const lastActivity = new Date(timerEl.dataset.lastActivity);
    if (isNaN(lastActivity.getTime())) return;
    function update() { timerEl.textContent = formatElapsedTime(Date.now() - lastActivity.getTime()); }
    update();
    setInterval(update, 100);
}

function startLiveStats() {
    const grid = document.getElementById('liveStatsGrid');
    if (!grid) return;
    const shardRate = parseFloat(grid.dataset.shardRate) || 0;
    const kmRate = parseFloat(grid.dataset.kmRate) || 0;
    const techRate = parseFloat(grid.dataset.techRate) || 0;
    const trailRate = parseFloat(grid.dataset.trailRate) || 0;
    const buildRate = parseFloat(grid.dataset.buildRate) || 0;
    const shardEl = document.getElementById('statShards');
    const kmEl = document.getElementById('statKm');
    const techEl = document.getElementById('statTech');
    const trailEl = document.getElementById('statTrails');
    const buildEl = document.getElementById('statBuild');
    let shardValue = shardEl ? parseFloat(shardEl.dataset.value) || 0 : 0;
    let kmValue = kmEl ? parseFloat(kmEl.dataset.value) || 0 : 0;
    let techValue = techEl ? parseFloat(techEl.dataset.value) || 0 : 0;
    let trailValue = trailEl ? parseFloat(trailEl.dataset.value) || 0 : 0;
    let buildValue = buildEl ? parseFloat(buildEl.dataset.value) || 0 : 0;
    const startTime = performance.now();

    function formatNum(n, decimals) {
        if (n >= 1000) return n.toLocaleString('en-US', {maximumFractionDigits: decimals});
        return n.toFixed(decimals);
    }

    function update() {
        const elapsed = (performance.now() - startTime) / 1000;
        if (shardEl && shardRate > 0) shardEl.textContent = '+' + formatNum(shardValue + shardRate * elapsed, 3);
        if (kmEl && kmRate > 0) kmEl.textContent = formatNum(kmValue + kmRate * elapsed, 3);
        if (techEl && techRate > 0) techEl.textContent = formatNum(techValue + techRate * elapsed, 3) + '%';
        if (trailEl && trailRate > 0) trailEl.textContent = formatNum(trailValue + trailRate * elapsed, 4);
        if (buildEl && buildRate > 0) {
            const newBuild = Math.min(100, buildValue + buildRate * elapsed);
            buildEl.textContent = formatNum(newBuild, 3) + '%';
        }
    }

    if (shardRate > 0 || kmRate > 0 || techRate > 0 || trailRate > 0 || buildRate > 0) {
        update();
        setInterval(update, 100);
    }
}

document.addEventListener('DOMContentLoaded', function() {
    // Hide briefing if dismissed for current content (re-shows only when content changes)
    const briefing = document.getElementById('away-briefing');
    if (briefing) {
        const timer = document.getElementById('briefingTimer');
        const briefingKey = timer ? (timer.dataset.briefingKey || timer.dataset.lastActivity) : '';
        const dismissedFor = localStorage.getItem('briefingDismissedFor');
        if (dismissedFor && dismissedFor === (briefingKey || 'true')) {
            briefing.remove();
        }
    }
    startBriefingTimer();
    startLiveStats();
});

function triggerHarvest() {
    const harvestBtn = document.querySelector('[data-action="harvest"]');
    if (harvestBtn) {
        harvestBtn.click();
    } else {
        fetch('/api/infrastructure/claim', { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    showToast('success', 'Harvested ' + Math.round(data.amount_claimed).toLocaleString() + ' shards!');
                    dismissBriefing();
                    if (window.updateBalanceDisplay) window.updateBalanceDisplay();
                    setTimeout(() => location.reload(), 1500);
                } else {
                    showToast('error', data.error || 'Harvest failed');
                }
            })
            .catch(() => showToast('error', 'Connection error'));
    }
}

// — ARIA PHOTO JOURNAL - Snapshot Gallery (uses MarsModal carousel) —
const ARIA_AVATAR = 'https://storage.googleapis.com/galactica-pilgrim-assets/aria/concept_aria_rock_v3_1767666240.png';
let snapshotGallery = [];

document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.snapshot-card').forEach(card => {
        snapshotGallery.push({
            id: card.dataset.id, imageUrl: card.dataset.imageUrl, caption: card.dataset.caption,
            type: card.dataset.type, marsSol: card.dataset.marsSol,
            earthDate: card.dataset.earthDate, earthTime: card.dataset.earthTime
        });
    });
});

function _snapshotBody(snap) {
    let dateStr = '';
    if (snap.marsSol) dateStr += 'Sol ' + snap.marsSol;
    if (snap.earthDate) { if (dateStr) dateStr += ' \u2022 '; dateStr += snap.earthDate; if (snap.earthTime) dateStr += ' at ' + snap.earthTime; }
    return `<div class="mm-person">
        <img src="${ARIA_AVATAR}" alt="ARIA" class="mm-person-avatar">
        <div><div style="font-size:12px;color:var(--color-aria);text-transform:uppercase;letter-spacing:1px;font-weight:600;">ARIA</div>
        <div style="font-size:11px;color:var(--text-muted);">${dateStr}</div></div>
    </div>
    <div class="mm-aria">"${snap.caption}"</div>
    <div id="snapshot-narrative" style="font-size:14px;color:var(--text-secondary);line-height:1.6;">
        <span style="color:var(--text-muted);">Loading ARIA's thoughts...</span>
    </div>`;
}

function _fetchNarrative(snap) {
    apiPost('/api/aria/snapshot-narrative', { snapshot_id: snap.id, caption: snap.caption, type: snap.type, image_url: snap.imageUrl })
    .then(data => {
        const el = document.getElementById('snapshot-narrative');
        if (el) { if (data.narrative) el.innerHTML = data.narrative; else el.style.display = 'none'; }
    })
    .catch(() => { const el = document.getElementById('snapshot-narrative'); if (el) el.style.display = 'none'; });
}

function openSnapshotModal(id) {
    const startIdx = Math.max(0, snapshotGallery.findIndex(s => s.id === id));
    if (snapshotGallery.length > 1) {
        MarsModal.show({
            theme: 'aria', width: 'xl',
            carousel: {
                items: snapshotGallery, current: startIdx,
                render: (snap) => ({ hero: snap.imageUrl, heroHeight: 0, title: '', body: _snapshotBody(snap) }),
                onNavigate: (idx) => _fetchNarrative(snapshotGallery[idx]),
                labels: { prev: '\u2039', next: '\u203a', done: 'Close' }
            }
        });
    } else {
        const snap = snapshotGallery[startIdx] || snapshotGallery[0];
        MarsModal.show({ hero: snap.imageUrl, heroHeight: 0, theme: 'aria', width: 'xl', body: _snapshotBody(snap) });
    }
    _fetchNarrative(snapshotGallery[startIdx] || snapshotGallery[0]);
}

document.addEventListener('click', function(e) {
    const card = e.target.closest('.snapshot-card');
    if (card) openSnapshotModal(card.dataset.id);
});

// — SOL CYCLE —
function updateSolCycle() {
    const solLengthMs = 88620000; // 24h 37m in ms
    const percentIntoSol = (Date.now() % solLengthMs) / solLengthMs;
    const solEl = document.getElementById('solCycle');
    if (solEl) {
        if (percentIntoSol < 0.25) solEl.textContent = 'Dawn';
        else if (percentIntoSol < 0.5) solEl.textContent = 'Day';
        else if (percentIntoSol < 0.75) solEl.textContent = 'Dusk';
        else solEl.textContent = 'Night';
    }
}
updateSolCycle();
setInterval(updateSolCycle, 60000);

// ============================================================================
// WELCOME BACK MODAL — "While You Were Away" event carousel
// Rich, verbose cards with real Mars icons and full metadata
// ============================================================================

const _I = 'https://storage.googleapis.com/galactica-pilgrim-assets/ui/icons/';
const WB_COLORS = {
    purchase: '#f59e0b', infrastructure: '#8b5cf6', expedition: '#06b6d4', upgrade: '#10b981',
    research: '#ec4899', discovery: '#f97316', landmark: '#14b8a6', claim: '#6366f1', trail: '#a855f7',
    sharding: '#22c55e', income: '#22c55e', equipment: '#f59e0b', modification: '#6366f1',
    media: '#8b5cf6', transmutation: '#ec4899'
};
const WB_ICONS = {
    purchase:       _I + 'icon_shopping_cart_1767996524.png',
    infrastructure: _I + 'icon_construction_crane_1767996647.png',
    expedition:     _I + 'icon_rocket_launch_1767996448.png',
    upgrade:        _I + 'icon_wrench_repair_1767996514.png',
    research:       _I + 'icon_microscope_lab_1767996545.png',
    discovery:      _I + 'icon_magnifier_discovery_1770309441.png',
    landmark:       _I + 'icon_mountain_terrain_1767995380.png',
    claim:          _I + 'icon_star_milestone_1770309293.png',
    trail:          _I + 'icon_compass_exploration_1767996574.png',
    media:          _I + 'icon_camera_photo_1767995406.png',
    sharding:       _I + 'icon_shard_gem_1767995363.png',
    income:         _I + 'icon_activity_income_1767995205.png',
    equipment:      _I + 'icon_wrench_repair_1767996514.png',
    modification:   _I + 'icon_hammer_building_1767996477.png',
    transmutation:  _I + 'icon_microscope_lab_1767996545.png'
};
const WB_VEHICLE_ICONS = {
    rover: _I + 'icon_vehicle_rover_1770309365.png',
    drone: _I + 'icon_vehicle_drone_1770309380.png',
    buggy: _I + 'icon_vehicle_buggy_1770309429.png'
};
const WB_LABELS = {
    purchase: 'Depot Purchase', infrastructure: 'Infrastructure', expedition: 'Expedition',
    upgrade: 'Equipment Upgrade', research: 'Tech Research', discovery: 'Discovery',
    landmark: 'Landmark Found', claim: 'Site Claimed', trail: 'Trail Mission',
    media: 'Captain Media', sharding: 'Shard Transaction', income: 'Passive Income',
    equipment: 'Equipment', modification: 'Captain Modification', transmutation: 'Transmutation'
};

function _kv(label, value, opts) {
    if (!value && value !== 0) return '';
    const style = opts?.color ? ` style="color:${opts.color};"` : '';
    const mono = opts?.mono ? ' style="font-family:monospace;font-size:11px;word-break:break-all;color:var(--color-sepolia);"' : '';
    return `<div class="mm-kv"><span class="mm-kv-label">${label}</span><span class="mm-kv-value"${style}${mono}>${value}</span></div>`;
}

function _wbBuildCard(item) {
    const d = new Date(item.timestamp);
    const dateStr = d.toLocaleDateString('en-US', {weekday:'short', month:'short', day:'numeric', year:'numeric'});
    const timeStr = d.toLocaleTimeString('en-US', {hour:'numeric', minute:'2-digit'});
    const color = WB_COLORS[item.category] || '#888';
    const cat = item.category;
    const label = WB_LABELS[cat] || cat.charAt(0).toUpperCase() + cat.slice(1);

    // Hero image: use item image if available, else category icon with colored glow
    let icon = WB_ICONS[cat] || WB_ICONS.purchase;
    // Expedition cards: use vehicle-specific icon
    if (cat === 'expedition' && item.vehicle_type && WB_VEHICLE_ICONS[item.vehicle_type]) {
        icon = WB_VEHICLE_ICONS[item.vehicle_type];
    }
    let hero;
    if (item.image_url) {
        // height:auto + width:auto guarantees natural aspect ratio.
        // max-height: 320px gives room for 4:3 (1024x768) and 1:1 (1024x1024) renders.
        hero = `<div style="text-align:center;padding:6px 0;">
            <img src="${item.image_url}" alt="" style="max-width:100%;max-height:320px;width:auto;height:auto;border-radius:10px;border:2px solid ${color}40;box-shadow:0 4px 20px ${color}30;">
        </div>`;
    } else {
        hero = `<div style="text-align:center;padding:12px 0;">
            <div style="display:inline-flex;align-items:center;justify-content:center;width:72px;height:72px;border-radius:16px;background:${color}18;border:2px solid ${color}40;box-shadow:0 4px 24px ${color}25;">
                <img src="${icon}" alt="" style="width:48px;height:48px;">
            </div>
        </div>`;
    }

    let body = hero;
    body += `<div class="mm-section-label" style="color:${color};">--- ${label.toUpperCase()} ---</div>`;
    body += _kv('Event', label, {color});
    body += _kv('Date', dateStr);
    body += _kv('Time', timeStr);

    // Category-specific rich details
    if (cat === 'expedition') {
        if (item.destination) body += _kv('Destination', item.destination);
        if (item.vehicle_type) {
            const vIcon = WB_VEHICLE_ICONS[item.vehicle_type] || '';
            const vName = item.vehicle_type.charAt(0).toUpperCase() + item.vehicle_type.slice(1);
            body += _kv('Vehicle', vIcon ? `<img src="${vIcon}" style="width:16px;height:16px;vertical-align:middle;margin-right:4px;"> ${vName}` : vName);
        }
        if (item.distance_km) body += _kv('Distance', `${Number(item.distance_km).toLocaleString()} km`);
        if (item.is_complete) {
            body += _kv('Status', '<span style="color:var(--color-success);">Complete</span>');
            if (item.shards_earned) body += _kv('Shards Earned', `${Math.round(item.shards_earned).toLocaleString()}`, {color: 'var(--color-sepolia)'});
            if (item.discovery_count) body += _kv('Discoveries', `${item.discovery_count} item${item.discovery_count > 1 ? 's' : ''} found`);
            if (item.sv_earned) body += _kv('Science Value', `+${Math.round(item.sv_earned).toLocaleString()} SV`, {color: '#ec4899'});
        } else {
            body += _kv('Status', '<span style="color:#06b6d4;">Launched</span>');
        }
        if (item.amount) body += _kv('Fuel Cost', `${Math.round(item.amount).toLocaleString()} shards`);

    } else if (cat === 'infrastructure') {
        if (item.structure_type) body += _kv('Structure', item.structure_type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()));
        if (item.status) body += _kv('Status', item.status === 'active'
            ? '<span style="color:var(--color-success);">Active</span>'
            : '<span style="color:#f59e0b;">Building</span>');
        if (item.amount) body += _kv('Build Cost', `${Math.round(item.amount).toLocaleString()} shards`, {color});

    } else if (cat === 'research') {
        if (item.branch) body += _kv('Branch', item.branch.charAt(0).toUpperCase() + item.branch.slice(1));
        if (item.tech_key) body += _kv('Technology', item.tech_key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()));
        if (item.level) body += _kv('Level', `Level ${item.level}`);
        if (item.status) body += _kv('Status', item.status === 'completed'
            ? '<span style="color:var(--color-success);">Completed</span>'
            : '<span style="color:#ec4899;">In Progress</span>');
        if (item.amount) body += _kv('SP Cost', `${Math.round(item.amount).toLocaleString()} Science Points`);

    } else if (cat === 'landmark') {
        if (item.landmark_type) body += _kv('Type', item.landmark_type.charAt(0).toUpperCase() + item.landmark_type.slice(1));
        if (item.distance_km) body += _kv('Distance', `${Number(item.distance_km).toLocaleString()} km from colony`);
        if (item.amount) body += _kv('Reward', `${Math.round(item.amount).toLocaleString()} shards`, {color: 'var(--color-sepolia)'});
        if (item.detail) body += _kv('Details', item.detail);

    } else if (cat === 'discovery') {
        if (item.detail) body += _kv('Rarity', `<span style="color:${color};font-weight:600;">${item.detail}</span>`);
        if (item.amount) body += _kv('Value', `${Math.round(item.amount).toLocaleString()} shards`, {color: 'var(--color-sepolia)'});

    } else if (cat === 'upgrade') {
        if (item.item_key) body += _kv('Item', item.item_key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()));
        if (item.category_detail || item.detail) body += _kv('Type', item.category_detail || item.detail);
        if (item.level) body += _kv('Level', `Level ${item.level}`);
        if (item.amount) body += _kv('Cost', `${Math.round(item.amount).toLocaleString()} shards`, {color});

    } else if (cat === 'trail') {
        if (item.detail) body += _kv('Crew', item.detail);
        if (item.crew_member) body += _kv('Member', item.crew_member.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()));
        if (item.km_to_add) body += _kv('Distance', `${Number(item.km_to_add).toLocaleString()} km`);
        if (item.duration_minutes) body += _kv('Duration', `${Math.round(item.duration_minutes / 60)} hours`);

    } else if (cat === 'claim') {
        if (item.detail) body += _kv('Site', item.detail);

    } else if (cat === 'media') {
        if (item.detail) body += _kv('Type', item.detail);

    } else {
        // Generic fallback
        if (item.detail) body += _kv('Details', item.detail);
        if (item.amount) body += _kv('Amount', `${Math.round(item.amount).toLocaleString()} shards`, {color});
    }

    // Common fields for all events
    if (item.tx_hash) {
        body += `<div class="mm-section-label" style="color:var(--color-sepolia);">--- SEPOLIA RECORD ---</div>`;
        body += _kv('Signature', `${item.tx_hash.slice(0,16)}...${item.tx_hash.slice(-8)}`, {mono: true});
    }
    return body;
}

window._wb = {
    items: [],
    async init(force) {
        const wb = window.welcomeBack || {};
        console.log('[WB] init:', JSON.stringify(wb), 'dismissed:', sessionStorage.getItem('wb_dismissed'), 'force:', !!force);
        if (force) sessionStorage.removeItem('wb_dismissed');
        if (!force) {
            if (!wb || !wb.show) { console.log('[WB] skip: no welcome_back data'); return; }
            if (sessionStorage.getItem('wb_dismissed')) { console.log('[WB] skip: already dismissed this session'); return; }
        }
        try {
            const resp = await fetch('/api/colony/activity');
            const data = await resp.json();
            console.log('[WB] activity:', data.success, 'count:', data.activity?.length);
            if (!data.success || !data.activity || !data.activity.length) {
                if (force) showToast('No activity events yet', 'info');
                return;
            }
            if (force) {
                this.items = data.activity.slice(0, 20);
            } else {
                const cutoff = new Date(wb.previous_activity_iso).getTime();
                this.items = data.activity.filter(a => new Date(a.timestamp).getTime() > cutoff);
            }
            console.log('[WB] filtered:', this.items.length, 'events');
            if (!this.items.length) {
                if (force) showToast('No new events since last visit', 'info');
                return;
            }
            MarsModal.show({
                width: 'sm',
                carousel: {
                    items: this.items, current: 0,
                    render: (item) => ({
                        title: item.title,
                        subtitle: `<span style="color:${WB_COLORS[item.category] || '#888'};">While You Were Away</span>`,
                        body: _wbBuildCard(item)
                    }),
                    labels: { done: 'Continue to Colony', skip: 'Skip All' }
                },
                onClose: () => sessionStorage.setItem('wb_dismissed', '1')
            });
        } catch(e) { console.error('[WB] init failed:', e); }
    }
};

// WB available via briefing card click (window._wb.init(true)) — no auto-popup

// Bug #1401: Record SV from the Base page's Science Value card. Reuses the
// same /api/scientist/record-sv endpoint that the Crew > Scientist tab calls.
window.recordSVFromBase = async function() {
    const btn = $('svRecordBtn');
    if (!btn || btn.disabled) return;
    btn.disabled = true;
    const origText = btn.textContent;
    btn.textContent = 'Recording...';
    try {
        const data = await apiPost('/api/scientist/record-sv');
        if (data && data.success) {
            showToast('Recorded ' + data.sv_recorded + ' SV', 'success');
            const accEl = $('svAccumulated');
            if (accEl) accEl.textContent = '0';
            btn.textContent = origText;
            btn.style.opacity = '0.5';
            btn.style.cursor = 'not-allowed';
        } else {
            showToast((data && data.error) || 'Failed to record SV', 'error');
            btn.textContent = origText;
            btn.disabled = false;
        }
    } catch (e) {
        showToast('Connection failed', 'error');
        btn.textContent = origText;
        btn.disabled = false;
    }
};
