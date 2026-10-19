/* Discovery Modal - Detail view + Shard Extraction Flow */
/* Used on: inventory page (via discovery_utils.js onclick), home page (via dashboard.js) */
/* Depends on: core.js (ItemDetailModal, showToast, setBalance, adjustBalance) */

// Discovery Modal (inventory page) - uses ItemDetailModal with Analyze action
// Payout multipliers: science value > shard extraction (common=0.5x, uncommon=0.75x, rare=1x, legendary=BLOCKED)
window.showDiscoveryDetails = function(id) {
    apiGet(`/api/discovery_items/${id}/details`).then(data => {
        if (!data.success) { showToast('Failed to load discovery details', 'error'); return; }
        const i = data.item;
        const rarity = i.rarity;
        const scientistName = data.scientist_name || 'Colony Scientist';
        const qty = data.total_quantity;

        // Shard extraction yields LESS than scientific value (science > shards)
        const payoutMultipliers = { common: 0.5, uncommon: 0.75, rare: 1, legendary: 0 };
        const multiplier = payoutMultipliers[rarity] || 0.5;
        let shardPayoutAll = Math.floor(data.total_value * multiplier);
        // Apply equipment bonuses (Research Lab, Cryo Storage) to preview
        if (typeof discoveryValueMult !== 'undefined' && discoveryValueMult > 1.0) shardPayoutAll = Math.floor(shardPayoutAll * discoveryValueMult);
        if (typeof bioDiscoveryValueMult !== 'undefined' && i.item_type === 'biological' && bioDiscoveryValueMult > 1.0) shardPayoutAll = Math.floor(shardPayoutAll * bioDiscoveryValueMult);
        const shardPayoutOne = qty > 1 ? Math.floor(shardPayoutAll / qty) : shardPayoutAll;
        const svBonusAll = Math.floor(shardPayoutAll * 0.50);
        const svBonusOne = Math.floor(shardPayoutOne * 0.50);
        const svLabel = svBonusAll > 0 ? ` + ${svBonusAll} SV` : '';

        // Cryptic legendary messages (Zelda-style hints - obscured references to something in the colony)
        const legendaryHints = [
            "The secret lies where pilgrims gather to trade...",
            "Something sleeps beneath the red dust. This artifact knows the way.",
            "When the twin moons align, the place of commerce will reveal its truth.",
            "I hear whispers... coordinates etched in ancient crystal.",
            "This belongs to something not yet built. The structure that waits holds the answer.",
            "The artifact hums a frequency. Something in the building between worlds responds.",
            "Three keys, three locks, one door. The merchant's hall remembers.",
            "Not all who wander Mars are lost. This artifact has been waiting.",
            "The crystal contains a map to nowhere... and everywhere. Seek where shards change hands.",
            "I've seen this symbol before. In dreams. In the shadow of the place we gather."
        ];

        // Cryptic rare messages (hint at hidden messages in shard exchanges - deep easter egg)
        const rareHints = [
            "Strange... when I touch this discovery, I sense... <em>words</em>. As if every exchange carries a whisper we cannot hear.",
            "There's something encoded here. Not in the crystal—in the giving. Every transfer leaves an echo.",
            "The shards remember. Every time they change hands, something invisible passes between.",
            "I keep hearing fragments... phrases that make no sense. The red planet speaks in riddles when we trade.",
            "This one vibrates differently. As if it's been part of something... a chain of hands, a chain of words.",
            "The discovery pulses when shards move between us. There's meaning written in the exchange itself.",
            "Words in the ether. Invisible ink on invisible paper. The ledger never forgets.",
            "Every time a shard passes from one pilgrim to another, a payload we cannot see travels with it.",
            "The ancients left messages in the currency itself. In the moment of exchange. We just haven't learned to read them.",
            "I sense... poetry? Mathematics? Something written in the spaces between hands. Between giving and receiving."
        ];

        // Build action based on rarity
        let action = null;
        let effects = null;

        if (rarity === 'legendary') {
            // Legendary: BLOCKED - cryptic Zelda-style hint
            const hint = legendaryHints[Math.floor(Math.random() * legendaryHints.length)];
            effects = `<div class="rarity-text-legendary" style="font-style:italic;line-height:1.6;">
                "${hint}"
                <div style="margin-top:12px;font-size:11px;opacity:0.6;">${scientistName} stares into the distance, transfixed.</div>
            </div>`;
        } else if (rarity === 'rare') {
            // Rare: Allow but with rotating cryptic warnings hinting at transaction messages (deep easter egg)
            const hint = rareHints[Math.floor(Math.random() * rareHints.length)];
            const isTrailConsumable = ['biological', 'mineral'].includes(i.item_type);
            const trailBoostNote = isTrailConsumable ? `
            <div class="trail-boost-note" style="margin-top:8px;padding:8px 10px;background:rgba(16,185,129,0.1);border-left:3px solid #10b981;font-size:12px;color:#ccc;">
                <strong style="color:#10b981;">${icon('tab_map')} Alternative:</strong> Use this discovery in <a href="/crew" style="color:#10b981;">Crew → Trails</a> to boost trail building speed (+8-15%). Also destroys the item.
            </div>` : '';
            effects = `<div class="rarity-text-rare" style="font-style:italic;line-height:1.6;">
                "${hint}"
                <div style="margin-top:8px;opacity:0.7;">${scientistName} seems troubled but willing to proceed.</div>
            </div>
            <div class="sv-tradeoff-note" style="margin-top:12px;padding:8px 10px;background:rgba(255,180,80,0.1);border-left:3px solid #ffb450;font-size:12px;color:#ccc;">
                <strong style="color:#ffb450;">${icon('warning_alert')} Trade-off:</strong> Extracting destroys the discovery. You'll gain shards + bonus SV but lose the item permanently.
            </div>${trailBoostNote}`;
            action = {
                label: qty > 1 ? `${icon('warning_alert')} Extract All ${qty}× (${shardPayoutAll} Shards${svLabel})` : `${icon('warning_alert')} Extract (${shardPayoutAll} Shards${svLabel})`,
                className: 'btn-warning',
                onClick: () => confirmExtraction(id, qty, shardPayoutAll, i.item_name, 'rare', true, svBonusAll),
                secondaryAction: qty > 1 ? { label: `Extract 1× (${shardPayoutOne})`, onClick: () => confirmExtraction(id, 1, shardPayoutOne, i.item_name, 'rare', false, svBonusOne) } : null,
                tertiaryAction: qty > 1 ? { label: `Extract Some…`, onClick: () => promptCustomExtractQty(id, qty, i.item_name, 'rare', shardPayoutOne, Math.floor(shardPayoutOne * 0.50)) } : null
            };
        } else if (rarity === 'uncommon') {
            // Uncommon: 0.75x payout with flavor text + SV warning
            const isTrailConsumable = ['biological', 'mineral'].includes(i.item_type);
            const trailBoostNote = isTrailConsumable ? `
            <div class="trail-boost-note" style="margin-top:8px;padding:8px 10px;background:rgba(16,185,129,0.1);border-left:3px solid #10b981;font-size:12px;color:#ccc;">
                <strong style="color:#10b981;">${icon('tab_map')} Alternative:</strong> Use this discovery in <a href="/crew" style="color:#10b981;">Crew → Trails</a> to boost trail building speed (+8-15%). Also destroys the item.
            </div>` : '';
            effects = `<div class="rarity-text-uncommon" style="font-style:italic;line-height:1.6;">
                "A bit tougher to crack than the common discoveries. I'll need to borrow some equipment from the base, but we can extract ${qty > 1 ? shardPayoutAll : shardPayoutOne} shards."
                <div style="margin-top:8px;opacity:0.7;">— ${scientistName}</div>
            </div>
            <div class="sv-tradeoff-note" style="margin-top:12px;padding:8px 10px;background:rgba(255,180,80,0.1);border-left:3px solid #ffb450;font-size:12px;color:#ccc;">
                <strong style="color:#ffb450;">${icon('warning_alert')} Trade-off:</strong> Extracting destroys the discovery. You'll gain shards + bonus SV but lose the item permanently.
            </div>${trailBoostNote}`;
            action = {
                label: qty > 1 ? `${icon('microscope_lab')} Extract All ${qty}× (${shardPayoutAll} Shards${svLabel})` : `${icon('microscope_lab')} Extract (${shardPayoutAll} Shards${svLabel})`,
                className: 'btn-success',
                onClick: () => confirmExtraction(id, qty, shardPayoutAll, i.item_name, 'uncommon', true, svBonusAll),
                secondaryAction: qty > 1 ? { label: `Extract 1× (${shardPayoutOne})`, onClick: () => confirmExtraction(id, 1, shardPayoutOne, i.item_name, 'uncommon', false, svBonusOne) } : null,
                tertiaryAction: qty > 1 ? { label: `Extract Some…`, onClick: () => promptCustomExtractQty(id, qty, i.item_name, 'uncommon', shardPayoutOne, Math.floor(shardPayoutOne * 0.50)) } : null
            };
        } else {
            // Common: 0.5x payout with flavor text + SV warning
            const isTrailConsumable = ['biological', 'mineral'].includes(i.item_type);
            const trailBoostNote = isTrailConsumable ? `
            <div class="trail-boost-note" style="margin-top:8px;padding:8px 10px;background:rgba(16,185,129,0.1);border-left:3px solid #10b981;font-size:12px;color:#ccc;">
                <strong style="color:#10b981;">${icon('tab_map')} Alternative:</strong> Use this discovery in <a href="/crew" style="color:#10b981;">Crew → Trails</a> to boost trail building speed (+6-12%). Also destroys the item.
            </div>` : '';
            effects = `<div class="rarity-text-common" style="font-style:italic;line-height:1.6;">
                "Standard extraction procedure—${qty > 1 ? shardPayoutAll : shardPayoutOne} shards ready for harvest."
                <div style="margin-top:8px;opacity:0.7;">— ${scientistName}</div>
            </div>
            <div class="sv-tradeoff-note" style="margin-top:12px;padding:8px 10px;background:rgba(255,180,80,0.1);border-left:3px solid #ffb450;font-size:12px;color:#ccc;">
                <strong style="color:#ffb450;">${icon('warning_alert')} Trade-off:</strong> Extracting destroys the discovery. You'll gain shards + bonus SV but lose the item permanently.
            </div>${trailBoostNote}`;
            action = {
                label: qty > 1 ? `${icon('microscope_lab')} Extract All ${qty}× (${shardPayoutAll} Shards${svLabel})` : `${icon('microscope_lab')} Extract (${shardPayoutAll} Shards${svLabel})`,
                className: 'btn-success',
                onClick: () => confirmExtraction(id, qty, shardPayoutAll, i.item_name, 'common', true, svBonusAll),
                secondaryAction: qty > 1 ? { label: `Extract 1× (${shardPayoutOne})`, onClick: () => confirmExtraction(id, 1, shardPayoutOne, i.item_name, 'common', false, svBonusOne) } : null,
                tertiaryAction: qty > 1 ? { label: `Extract Some…`, onClick: () => promptCustomExtractQty(id, qty, i.item_name, 'common', shardPayoutOne, Math.floor(shardPayoutOne * 0.50)) } : null
            };
        }

        ItemDetailModal.show({
            name: i.item_name,
            image: i.image_url,
            category: `<span class="rarity-badge rarity-${rarity}">${rarity.toUpperCase()}</span> ${i.item_type || 'Discovery'}`,
            description: i.description,
            stats: [
                { label: 'Quantity', value: `${qty}×` },
                { label: 'Scientific Value', value: i.base_scientific_value || '-' },
                { label: 'Weight', value: `${(i.weight_kg || 0).toFixed(1)} kg` },
                { label: 'Shard Yield', value: rarity === 'legendary' ? '—' : (qty > 1 ? `${shardPayoutOne} each / ${shardPayoutAll} total` : `${shardPayoutAll}`) },
                { label: 'SV Bonus', value: rarity === 'legendary' ? '—' : `+${svBonusAll} SV (50%)` }
            ],
            effects: effects,
            action: action
        });
    }).catch(() => { showToast('Error loading discovery', 'error'); });
};

// Bug #1125: "Extract Some" — let captain pick a custom quantity to extract.
// Opens a small modal asking for N, validates against the available stack qty,
// then re-uses confirmExtraction with the chosen N.
function promptCustomExtractQty(discoveryItemId, maxQty, itemName, rarity, perItemShards, perItemSv) {
    if (maxQty < 2) return;  // No point if there's only 1
    const raw = window.prompt(
        `How many "${itemName}" do you want to extract?\n\nYou have ${maxQty} available. Each yields ${perItemShards} shards + ${perItemSv} SV.\n\nEnter a number between 1 and ${maxQty}:`,
        String(Math.min(maxQty, 5))
    );
    if (raw == null) return;  // user cancelled
    const n = parseInt(raw, 10);
    if (isNaN(n) || n < 1 || n > maxQty) {
        showToast(`Please enter a number between 1 and ${maxQty}`, 'error');
        return;
    }
    const totalShards = perItemShards * n;
    const totalSv = perItemSv * n;
    confirmExtraction(discoveryItemId, n, totalShards, itemName, rarity, false, totalSv, n);
}
window.promptCustomExtractQty = promptCustomExtractQty;

// Confirm extraction with SV trade-off warning using in-game modal
// Bug #1131: svBonus must be passed in so the confirm button shows "Extract (X Shards + Y SV)"
// Bug #1125: customQty (optional) — when set, extracts exactly that many instead of all-or-1
function confirmExtraction(discoveryItemId, quantity, shardPayout, itemName, rarity, extractAll, svBonus, customQty) {
    if (svBonus === undefined || svBonus === null) svBonus = Math.floor(shardPayout * 0.50);
    const rarityQuotes = {
        rare: [
            `This... this is monumentally significant. Extracting ${itemName} with a heavy heart.`,
            `Such potential for research in ${itemName}... reduced to energy currency.`,
            `A discovery that could rewrite our understanding. Shard extraction authorized.`,
            `Conflicted. Pure research versus immediate energy needs.`,
            `The researcher in me weeps, but the shards from ${itemName} are yours.`,
            `Rare find. So much lost in this simple energy conversion.`,
            `${itemName} whispers its most guarded secrets as the shards release.`,
            `Scientifically invaluable. Yet protocol demands shard harvesting.`,
            `The whispers fade when I begin extraction. Whatever message ${itemName} carries will be lost forever.`,
            `Archaeological significance immense. But you're the captain.`
        ],
        uncommon: [
            `Unusual resonance frequency on ${itemName}. This one is... different.`,
            `Compression patterns suggest a complex origin. Fascinating!`,
            `These atomic bonds are NOT standard protocol. Extracting carefully.`,
            `Energy fluctuations suggest a non-standard formation process.`,
            `Asymmetric molecular structure. Mars keeps surprising us!`,
            `Spectral analysis on ${itemName} indicates something extraordinary.`,
            `A bit tougher to crack, but the shards are ready for harvest.`,
            `Intriguing molecular variance detected during extraction!`,
            `Not your standard Sepolia. ${itemName} has character.`,
            `Energy resonance beyond predicted parameters. Incredible!`
        ],
        common: [
            `Another Martian mystery catalogued! The shards are yours.`,
            `Mars never gets old! Extracting ${itemName} now.`,
            `Even 'common' finds make my research heart race.`,
            `Textbook extraction. Yet Mars always has surprises.`,
            `Routine, but never boring. Mars is an endless puzzle.`,
            `Data logged. Shard harvested. Scientific curiosity: satiated.`,
            `Crystalline structures aligned. Standard procedure, extraordinary world.`,
            `Each crystal tells a story. Extracting this one for you.`,
            `Processing complete. Another fragment of our red planet's secrets.`,
            `Standard extraction procedure. The shards are yours for the taking.`
        ]
    };
    const quotes = rarityQuotes[rarity] || rarityQuotes.common;
    const quote = `"${quotes[Math.floor(Math.random() * quotes.length)]}"`;

    const qtyLabel = extractAll && quantity > 1 ? `${quantity}× ` : '';

    ItemDetailModal.show({
        name: `Extract ${qtyLabel}${itemName}?`,
        image: null,
        category: `<span class="rarity-badge rarity-${rarity}">${rarity.toUpperCase()}</span> Confirm Extraction`,
        description: quote,
        stats: [
            { label: 'Discoveries', value: extractAll ? quantity : 1 },
            { label: 'Shards Received', value: shardPayout.toLocaleString() },
            { label: 'SV Bonus', value: `+${svBonus} SV` },
        ],
        effects: `<div class="sv-tradeoff-note" style="padding:8px 10px;background:rgba(255,180,80,0.1);border-left:3px solid #ffb450;font-size:12px;color:#ccc;">
            <strong style="color:#ffb450;">Trade-off:</strong> Extracting destroys the discovery. You'll gain shards + bonus SV but lose the item permanently.
        </div>`,
        action: {
            label: svBonus > 0 ? `Extract (${shardPayout.toLocaleString()} Shards + ${svBonus} SV)` : `Extract (${shardPayout.toLocaleString()} Shards)`,
            className: 'btn-warning',
            // Bug #1125: pass customQty so backend extracts exactly that many
            onClick: () => analyzeDiscovery(discoveryItemId, quantity, shardPayout, extractAll, customQty || null)
        }
    });
}
window.confirmExtraction = confirmExtraction;


// Analyze discovery - extract shards
//   extractAll: true     → all discoveries
//   extractAll: false    → 1 discovery (legacy "Extract 1×")
//   quantityToExtract: N → exactly N (Bug #1125 "Extract Some")
async function analyzeDiscovery(discoveryItemId, _quantity, value, extractAll = true, quantityToExtract = null) {
    const btn = document.getElementById('mmActionBtn');
    if (btn) { btn.disabled = true; btn.innerHTML = `${icon('microscope_lab')} Analyzing...`; }
    const secondaryBtn = document.getElementById('mmActionBtn2');
    if (secondaryBtn) secondaryBtn.disabled = true;

    try {
        const data = await apiPost('/api/discovery/analyze', {
                discovery_item_id: discoveryItemId,
                extract_all: extractAll,
                ...(quantityToExtract ? { quantity_to_extract: quantityToExtract } : {})
        });

        if (data.success) {
            ItemDetailModal.hide();
            // Build message with bonus info if applicable
            let msg = `Extracted ${data.shards_received.toFixed(0)} Shards from ${data.quantity_analyzed} discover${data.quantity_analyzed > 1 ? 'ies' : 'y'}!`;
            if (data.bonus_applied && data.discovery_value_mult > 1.0) {
                const bonusPct = ((data.discovery_value_mult - 1) * 100).toFixed(0);
                // Show specific bonus type - Cryo Storage for bio, Research Lab for general
                if (data.bio_bonus_applied) {
                    msg += ` (Cryo Storage +${bonusPct}%)`;
                } else {
                    msg += ` (Research Lab +${bonusPct}%)`;
                }
            }
            if (data.sv_awarded > 0) msg += ` + ${data.sv_awarded} SV`;
            showToast(msg, 'success', `${icon('microscope_lab')} Analysis Complete`);
            // Update balance display - use new_balance if provided, otherwise adjust by received
            if (data.new_balance !== undefined) {
                setBalance(data.new_balance);
            } else {
                adjustBalance(data.shards_received);
            }
            if (data.sv_awarded > 0 && typeof adjustSV === 'function') adjustSV(data.sv_awarded);
            // Refresh inventory after short delay
            setTimeout(() => location.reload(), 2000);
        } else {
            showToast(data.error || 'Analysis failed', 'error');
            if (btn) { btn.disabled = false; btn.innerHTML = `${icon('microscope_lab')} Extract`; }
        }
    } catch (e) {
        showToast('Network error', 'error');
        if (btn) { btn.disabled = false; btn.innerHTML = `${icon('microscope_lab')} Extract`; }
    }
}
window.analyzeDiscovery = analyzeDiscovery;
