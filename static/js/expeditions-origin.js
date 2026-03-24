/* Expeditions - Origin Sites (historical Mars landing sites) */
/* Depends on: expeditions.js (map, getCSSColor, showToast, MarsModal) */

// Origin site data and markers (global for popup access)
let originSiteData = [];
let originSiteMarkers = [];

// Origin Site markers (claimable historical Mars landing sites)
async function addOriginSiteMarkers() {
    try {
        const response = await fetch('/api/signal/origin/eligibility');
        const data = await response.json();

        if (!data.success || !data.sites) return;

        originSiteData = data.sites;

        // ALL 14 Origin Sites use the same BRIGHT GOLD color
        // Luke's request: make all dots the same color so they're clearly visible
        const originColor = '#fbbf24';   // Bright gold for ALL origin sites
        const originBorder = '#f59e0b';

        // Add ARIA-like pulse animation CSS
        if (!document.getElementById('origin-pulse-css')) {
            const pulseStyle = document.createElement('style');
            pulseStyle.id = 'origin-pulse-css';
            pulseStyle.textContent = `
                /* Outer expanding ring - ARIA style */
                .origin-pulse-ring {
                    animation: originRingPulse 3s ease-in-out infinite;
                    pointer-events: none !important;
                }
                @keyframes originRingPulse {
                    0%, 100% {
                        opacity: 0.3;
                        transform: scale(1);
                    }
                    50% {
                        opacity: 0.7;
                        transform: scale(1.15);
                    }
                }
                /* Inner marker glow - gentle pulse like ARIA orb */
                .origin-marker-glow {
                    animation: originMarkerPulse 3s ease-in-out infinite;
                    filter: drop-shadow(0 0 4px rgba(251, 191, 36, 0.6));
                }
                @keyframes originMarkerPulse {
                    0%, 100% {
                        filter: drop-shadow(0 0 4px rgba(251, 191, 36, 0.5));
                    }
                    50% {
                        filter: drop-shadow(0 0 10px rgba(251, 191, 36, 0.9)) drop-shadow(0 0 20px rgba(251, 191, 36, 0.5));
                    }
                }
                /* Claimable sites pulse faster/brighter */
                .origin-pulse-ring.claimable {
                    animation: originRingPulseClaimable 2s ease-in-out infinite;
                }
                @keyframes originRingPulseClaimable {
                    0%, 100% {
                        opacity: 0.4;
                        transform: scale(1);
                    }
                    50% {
                        opacity: 0.9;
                        transform: scale(1.25);
                    }
                }
            `;
            document.head.appendChild(pulseStyle);
        }

        // Show ALL 14 origin sites — always visible, always pulsing
        // The Signal is the endgame; players must know the nodes exist
        originSiteData.forEach((site, i) => {
            // ALL sites use the same bright gold color
            const fillColor = originColor;
            const borderColor = originBorder;

            // Add outer pulse ring to ALL origin sites (ARIA-style glow)
            const pulseRing = L.circleMarker([site.latitude, site.longitude], {
                radius: 18,
                fillColor: '#ffffff',
                color: '#fbbf24',
                weight: 2,
                opacity: 0.5,
                fillOpacity: 0.15,
                className: site.can_claim ? 'origin-pulse-ring claimable' : 'origin-pulse-ring',
                interactive: false  // Don't block clicks!
            }).addTo(map);
            originSiteMarkers.push(pulseRing);

            // Main marker on top - this one is clickable, ALL get the glow
            const marker = L.circleMarker([site.latitude, site.longitude], {
                radius: 12,
                fillColor: fillColor,
                color: borderColor,
                weight: 3,
                opacity: 1,
                fillOpacity: 0.9,
                className: 'origin-marker-glow'
            }).addTo(map);

            marker._originSiteIndex = i;
            marker.bindPopup(() => buildOriginSitePopup(i));
            originSiteMarkers.push(marker);
        });

    } catch (e) {
        console.error('Failed to load Origin Site markers:', e);
    }
}

function buildOriginSitePopup(siteIndex) {
    const site = originSiteData[siteIndex];
    if (!site) return '<div class="map-popup">Loading...</div>';

    // CLAIMABLE - Clean popup, excitement in modal
    if (site.can_claim) {
        // Store site data globally for the modal
        window.pendingOriginClaim = site;
        console.log('Building claimable popup for site:', site.site_code, site);
        return `<div class="map-popup" style="border: 1px solid var(--color-sepolia);">
            <div class="map-popup-title" style="color: var(--color-sepolia);">
                ${site.mission_name}
            </div>
            <div style="text-align: center; margin: 4px 0;">
                <span style="font-size: 9px; font-weight: 600; letter-spacing: 1px; color: var(--color-sepolia); text-transform: uppercase;">Origin Site</span>
            </div>
            <div class="map-popup-details">
                <b>Distance:</b> ${site.distance_km}km
            </div>
            <button class="map-popup-btn" id="origin-claim-btn-${site.id}">
                Claim Site
            </button>
        </div>`;
    }

    // Already claimed - show founder info and visit option
    if (site.is_claimed) {
        const founder = site.founder_wallet_prefix
            ? `${site.founder_commander_name} ◆ ${site.founder_wallet_prefix}`
            : site.founder_commander_name;

        // Check if user can visit (within range and hasn't visited)
        let visitSection = '';
        if (site.can_visit) {
            window.pendingOriginVisit = site;
            visitSection = `
                <div style="margin-top: 12px; padding-top: 12px; border-top: 1px solid rgba(107, 114, 128, 0.3);">
                    <div style="font-size: 10px; color: #10b981; text-transform: uppercase; letter-spacing: 1px; text-align: center; margin-bottom: 8px;">
                        ✨ Within Range
                    </div>
                    <button class="map-popup-btn" id="origin-visit-btn-${site.id}" style="background: linear-gradient(135deg, #10b981, #059669);">
                        Make Pilgrimage
                    </button>
                </div>`;
        } else if (site.has_visited) {
            visitSection = `
                <div style="margin-top: 8px; font-size: 10px; color: #10b981; text-align: center;">
                    ✓ You have visited this site
                </div>`;
        } else if (site.distance_km) {
            visitSection = `
                <div style="margin-top: 8px; font-size: 10px; color: var(--text-muted); text-align: center;">
                    Your closest: ${site.distance_km}km away
                </div>`;
        }

        return `<div class="map-popup" style="border: 1px solid #6b7280;">
            <div class="map-popup-title" style="color: #9ca3af;">
                ${site.mission_name}
            </div>
            <div style="text-align: center; margin: 8px 0; padding: 8px; background: rgba(107, 114, 128, 0.1); border-radius: 4px;">
                <div style="font-size: 10px; color: #6b7280; text-transform: uppercase; letter-spacing: 1px;">Founder</div>
                <div style="color: #fbbf24; font-weight: 600; margin-top: 4px;">${founder}</div>
            </div>
            ${visitSection}
        </div>`;
    }

    // Lost signal site - requires decoder to unlock
    if (site.is_lost_signal) {
        window.pendingLostSite = site;
        const hints = {
            'MARS-3': "Twenty seconds of contact, then silence. December 1971. So close...",
            'BEAGLE-2': "A Christmas gift that never opened. 2003. It's still there, waiting.",
            'SCHIAPARELLI': "The computer thought it had landed. It hadn't. October 2016."
        };
        const hint = hints[site.site_code] || "Something is here... but the signal is fragmented.";

        return `<div class="map-popup" style="border: 1px solid #06b6d4; min-width: 220px;">
            <div class="map-popup-title" style="color: #06b6d4;">
                🔒 LOST SIGNAL
            </div>
            <div style="font-size: 10px; color: #06b6d4; text-align: center; letter-spacing: 1px; margin: 4px 0;">
                ░░░ FRAGMENTED ░░░
            </div>
            <div style="font-size: 11px; color: var(--text-muted); text-align: center; font-style: italic; margin: 8px 0; padding: 0 4px;">
                "${hint}"
            </div>
            <div style="margin-top: 10px;">
                <input type="text" id="lost-site-code-${site.id}" placeholder="0x..."
                    style="width: 100%; padding: 6px 8px; font-family: monospace; font-size: 11px;
                    background: rgba(6, 182, 212, 0.1); border: 1px solid #06b6d4; border-radius: 4px;
                    color: #06b6d4; text-align: center;">
            </div>
            <button class="map-popup-btn" id="lost-decode-btn-${site.id}"
                style="background: linear-gradient(135deg, #06b6d4, #0891b2); margin-top: 8px;">
                Decode Signal
            </button>
        </div>`;
    }

    // Unclaimed / not yet in range — mysterious, matches Signal page node language
    const nodeId = site.node_id || 'NODE-??????';
    const strength = site.signal_strength || 'Faint';
    const strengthColors = { 'Strong': '#f59e0b', 'Faint': '#a78bfa', 'Fragmented': '#06b6d4' };
    const strengthColor = strengthColors[strength] || '#a78bfa';

    // Proximity hint — cryptic breadcrumb if they've been within 500km
    let proximityHint = '';
    if (site.distance_km && site.distance_km <= 500) {
        proximityHint = `<div style="font-size: 10px; color: ${strengthColor}; text-align: center; font-style: italic; margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(107, 114, 128, 0.2);">
            "Something stirred during a recent journey... a faint resonance, ${Math.round(site.distance_km / 50) * 50}+ clicks out."
        </div>`;
    } else if (site.distance_km && site.distance_km <= 1000) {
        proximityHint = `<div style="font-size: 10px; color: var(--text-muted); text-align: center; font-style: italic; margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(107, 114, 128, 0.2);">
            "A distant echo. Too far to read, but... it's there."
        </div>`;
    }

    return `<div class="map-popup" style="border: 1px solid ${strengthColor}40;">
        <div class="map-popup-title" style="color: ${strengthColor}; font-family: var(--font-mono, monospace); font-size: 13px; letter-spacing: 1px;">
            ${nodeId}
        </div>
        <div style="text-align: center; margin: 4px 0;">
            <span style="font-size: 9px; font-weight: 600; letter-spacing: 1px; color: ${strengthColor}; text-transform: uppercase;">Signal: ${strength}</span>
        </div>
        <div style="font-size: 10px; color: var(--text-muted); text-align: center; margin: 8px 0; font-style: italic;">
            "Dormant. Awaiting contact."
        </div>
        <div style="font-size: 9px; color: var(--text-muted); text-align: center; text-transform: uppercase; letter-spacing: 1px;">
            Awaiting Founder
        </div>
        ${proximityHint}
    </div>`;
}

// Event delegation for origin claim button (onclick doesn't work in Leaflet popups)
document.addEventListener('click', function(e) {
    if (e.target && e.target.id && e.target.id.startsWith('origin-claim-btn-')) {
        console.log('Origin claim button clicked via delegation');
        showOriginClaimConfirm();
    }
    // Visit button for claimed sites
    if (e.target && e.target.id && e.target.id.startsWith('origin-visit-btn-')) {
        console.log('Origin visit button clicked via delegation');
        const siteId = e.target.id.replace('origin-visit-btn-', '');
        attemptOriginVisit(parseInt(siteId));
    }
    // Lost site decode button
    if (e.target && e.target.id && e.target.id.startsWith('lost-decode-btn-')) {
        const siteId = e.target.id.replace('lost-decode-btn-', '');
        const codeInput = document.getElementById(`lost-site-code-${siteId}`);
        if (codeInput) {
            attemptLostSiteDecode(siteId, codeInput.value.trim());
        }
    }
});

// Attempt to decode a Lost Signal site
async function attemptLostSiteDecode(siteId, code) {
    if (!code || !code.startsWith('0x')) {
        showToast('Enter a valid 0x code to decode the signal', 'error');
        return;
    }

    const btn = document.getElementById(`lost-decode-btn-${siteId}`);
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Decoding...';
    }

    try {
        const response = await fetch('/api/signal/lost/decode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ site_id: parseInt(siteId), code: code })
        });

        const data = await response.json();

        if (data.success) {
            showToast(data.message || 'Signal decoded! The site is now unlocked.', 'success');
            map.closePopup();
            // Refresh the map to show the site as claimable now
            setTimeout(() => {
                clearOriginSiteMarkers();
                addOriginSiteMarkers();
            }, 500);
        } else {
            showToast(data.error || 'Decode failed. The signal remains fragmented.', 'error');
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'Decode Signal';
            }
        }
    } catch (err) {
        console.error('Decode error:', err);
        showToast('Connection error. Try again.', 'error');
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Decode Signal';
        }
    }
}

// Clear origin site markers for refresh
function clearOriginSiteMarkers() {
    originSiteMarkers.forEach(m => map.removeLayer(m));
    originSiteMarkers = [];
    originSiteData = [];
}

// Attempt to visit (pilgrimage to) an already-claimed Origin Site
async function attemptOriginVisit(siteId) {
    const site = window.pendingOriginVisit;
    if (!site) {
        showToast('No site data available', 'error');
        return;
    }

    const btn = document.getElementById(`origin-visit-btn-${siteId}`);
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Recording visit...';
    }

    try {
        const response = await fetch(`/api/signal/origin/visit/${siteId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        const data = await response.json();

        if (data.success) {
            map.closePopup();
            showOriginVisitSuccess(data);
        } else {
            showToast(data.error || 'Visit failed', 'error');
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'Make Pilgrimage';
            }
        }
    } catch (err) {
        console.error('Visit error:', err);
        showToast('Connection error. Try again.', 'error');
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Make Pilgrimage';
        }
    }
}

// Show success modal after visiting an Origin Site
function showOriginVisitSuccess(data) {
    const tierEmojis = { 'Early Witness': '🌟', 'Pioneer': '🚀', 'Pilgrim': '📍' };
    const tierEmoji = tierEmojis[data.tier_name] || '📍';

    MarsModal.show({
        title: 'Pilgrimage Complete',
        subtitle: `<span style="color:${data.tier_color}">You are ${data.tier_name} #${data.visitor_rank}</span>`,
        icon: tierEmoji,
        width: 'md',
        body: `
            <div class="mm-card-accent" style="text-align:center;">
                <div class="mm-section-label">Origin Site</div>
                <div style="font-size:18px; font-weight:700; color:var(--text-primary);">${data.mission_name}</div>
                <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">Founded by ${data.founder_name}</div>
            </div>
            <div class="mm-card">
                <div class="mm-section-label" style="color:${data.tier_color}">Your Reward</div>
                As <strong style="color:${data.tier_color};">${data.tier_name} #${data.visitor_rank}</strong>, you will receive a
                <strong>${data.item_rarity}</strong> artifact from this historic site.
            </div>
            <div class="mm-aria">💫 "Your pilgrimage has been recorded in the Shard Network, Captain.
                You walked where Earth first touched Mars. You are part of the story now."</div>
        `,
        footer: `<button class="btn btn-primary mm-btn-full" onclick="MarsModal.hide()" style="background:linear-gradient(135deg,${data.tier_color},${data.tier_color}cc);">Continue</button>`,
        onClose: () => { setTimeout(() => { clearOriginSiteMarkers(); addOriginSiteMarkers(); }, 300); }
    });

    setTimeout(() => { clearOriginSiteMarkers(); addOriginSiteMarkers(); }, 500);
}

function showOriginClaimConfirm() {
    const site = window.pendingOriginClaim;
    if (!site) return;
    map.closePopup();

    MarsModal.show({
        title: 'You Found Something Ancient',
        subtitle: '<span style="color:var(--color-sepolia)">This changes everything.</span>',
        icon: '🔮',
        width: 'lg',
        body: `
            <div class="mm-card-accent" style="text-align:center;">
                <div class="mm-section-label">Origin Site</div>
                <div style="font-size:20px; font-weight:700; color:var(--text-primary);">${site.mission_name}</div>
                <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">The exact location where Earth first touched Mars</div>
            </div>
            <div class="mm-card-mars" style="text-align:center;">
                <div class="mm-section-label" style="color:#a855f7;">You Will Receive</div>
                <div style="font-size:18px; font-weight:600; color:var(--text-primary); margin-bottom:6px;">${site.legendary_item_name || 'Origin Fragment'}</div>
                <div style="font-size:12px; color:var(--text-secondary); line-height:1.5;">
                    A one-of-a-kind artifact. Your name will be permanently etched into it.
                    No one else can ever claim this. <strong>Only 14 exist.</strong>
                </div>
            </div>
            <div class="mm-aria">💫 "Captain... you're about to become the <strong style="color:var(--color-sepolia);">first</strong> to claim this site. Ever.
                Others may visit after you. But history will remember only one name: yours.
                After you claim this, visit <a href="/signal" style="color:var(--color-sepolia); font-weight:600;">The Signal</a> to understand what you now possess."</div>
            <div style="text-align:center; font-size:11px; color:var(--text-muted);">This action cannot be undone. You will become the permanent Founder.</div>
        `,
        footer: `<button id="origin-confirm-btn" class="btn btn-primary mm-btn-full" onclick="confirmOriginClaim(${site.id})">Claim as Founder</button>
                 <button class="btn btn-secondary" style="flex:1;" onclick="MarsModal.hide()">Not Yet</button>`
    });
}

function closeOriginConfirmModal() { MarsModal.hide(); }

async function confirmOriginClaim(siteId) {
    console.log('confirmOriginClaim called for site:', siteId);
    // Update button to loading state
    const btn = document.getElementById('origin-confirm-btn');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '⏳ Claiming...';
    }

    // Call the actual claim function
    await claimOriginSite(siteId);

    // Close confirm modal (claim modal will show on success)
    closeOriginConfirmModal();
}

async function claimOriginSite(siteId) {
    try {
        // Show loading state
        const btn = document.querySelector('.map-popup-btn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '⏳ Claiming...';
        }

        const response = await fetch(`/api/signal/origin/claim/${siteId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await response.json();

        if (data.success) {
            // Close any open popups
            map.closePopup();

            // Show EPIC claim modal!
            showOriginClaimModal(data);

            // Refresh the origin site markers
            originSiteMarkers.forEach(m => map.removeLayer(m));
            originSiteMarkers = [];
            await addOriginSiteMarkers();

        } else {
            if (typeof showToast === 'function') {
                showToast(data.error || 'Failed to claim site', 'error');
            } else {
                alert(data.error || 'Failed to claim site');
            }
        }
    } catch (e) {
        console.error('Failed to claim Origin Site:', e);
        if (typeof showToast === 'function') {
            showToast('Network error. Please try again.', 'error');
        }
    }
}

function showOriginClaimModal(data) {
    const founderDisplay = data.founder_wallet_prefix
        ? `${data.founder_name} ◆ ${data.founder_wallet_prefix}`
        : data.founder_name;

    MarsModal.show({
        title: 'You Did It.',
        subtitle: '<span style="color:var(--color-sepolia)">You are the First.</span>',
        icon: '🏆',
        width: 'lg',
        body: `
            <div class="mm-card-accent" style="text-align:center;">
                <div class="mm-section-label">First to Claim</div>
                <div style="font-size:22px; font-weight:700; color:var(--text-primary); margin-bottom:6px;">${data.mission_name || data.site_code}</div>
                <div style="font-size:13px; color:var(--text-secondary);">Others may follow. But you were first. That can never be taken from you.</div>
            </div>
            <div class="mm-card-mars" style="text-align:center;">
                <div class="mm-section-label" style="color:#a855f7;">Founder</div>
                <div style="font-size:22px; font-weight:700; color:var(--text-primary);">${founderDisplay}</div>
            </div>
            <div class="mm-card-accent" style="text-align:center;">
                <div class="mm-section-label">Legendary Artifact</div>
                <div style="font-size:16px; font-weight:600; color:var(--text-primary);">${data.legendary_item?.name || data.site_code + ' Origin Fragment'}</div>
            </div>
            <div class="mm-aria">💫 "Captain... congratulations. What you've done today, few will ever understand.
                Your artifact is being forged as we speak. Go to <a href="/signal" style="color:var(--color-sepolia); font-weight:600;">The Signal</a>.
                See what you've uncovered. Decide who you tell... and who you don't."</div>
            <div class="mm-card" style="text-align:center;">
                <strong style="color:var(--color-sepolia);">Check your Inventory</strong> before the next sol.
                <br><span style="font-size:11px; color:var(--text-muted);">Something legendary will be waiting for you.</span>
            </div>
        `,
        footer: `<a href="/signal" class="btn btn-primary mm-btn-full" style="text-align:center;">Go to The Signal</a>
                 <button class="btn btn-secondary" style="flex:1;" onclick="MarsModal.hide()">Stay Here</button>`
    });
}

// Expose to global scope for dynamic popup/modal onclick handlers
window.showOriginClaimConfirm = showOriginClaimConfirm;
window.closeOriginConfirmModal = closeOriginConfirmModal;
window.confirmOriginClaim = confirmOriginClaim;
