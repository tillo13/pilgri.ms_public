/* Colony Page - Discovery Details & Extraction */
/* Shared discovery functions are in discovery_utils.js */

// Show detailed modal for discoveries
function showDiscoveryDetails(discoveryItemId) {
    const discovery = allDiscoveries.find(d => d.discovery_item_id === discoveryItemId);
    if (!discovery) return;
    const stats = [];
    const rarityColors = { legendary: 'var(--color-mars)', rare: 'var(--color-sepolia)', uncommon: 'var(--color-success)', common: 'var(--text-muted)' };
    stats.push({ label: 'Rarity', value: `<span style="color: ${rarityColors[discovery.rarity]}">${discovery.rarity.toUpperCase()}</span>` });
    stats.push({ label: 'Type', value: discovery.item_type || 'Sample' });
    stats.push({ label: 'Quantity', value: (discovery.quantity || 1) + ' discover' + ((discovery.quantity || 1) !== 1 ? 'ies' : 'y') });
    stats.push({ label: '\u2500\u2500\u2500 VALUE \u2500\u2500\u2500', value: '' });
    const baseValue = discovery.base_scientific_value || discovery.enhanced_value;
    stats.push({ label: 'Base Value', value: Math.round(baseValue).toLocaleString() + ' shards' });
    stats.push({ label: 'Enhanced Value', value: Math.round(discovery.enhanced_value).toLocaleString() + ' shards' });
    if (discovery.base_scientific_value) {
        const svTotal = discovery.base_scientific_value * (discovery.quantity || 1);
        stats.push({ label: 'Science Value', value: svTotal.toLocaleString() + ' SV' });
    }
    if (discovery.enhanced_value > baseValue) {
        const bonusPct = ((discovery.enhanced_value / baseValue - 1) * 100).toFixed(0);
        stats.push({ label: 'Research Bonus', value: '+' + bonusPct + '% (Research Lab)' });
    }
    if ((discovery.quantity || 1) > 1) {
        const totalValue = discovery.enhanced_value * (discovery.quantity || 1);
        stats.push({ label: 'Total Value', value: Math.round(totalValue).toLocaleString() + ' shards' });
    }
    stats.push({ label: '\u2500\u2500\u2500 PHYSICAL \u2500\u2500\u2500', value: '' });
    stats.push({ label: 'Weight', value: (discovery.weight_kg || 0).toFixed(2) + ' kg' });
    if ((discovery.quantity || 1) > 1) {
        const totalWeight = (discovery.weight_kg || 0) * (discovery.quantity || 1);
        stats.push({ label: 'Total Weight', value: totalWeight.toFixed(2) + ' kg' });
    }
    stats.push({ label: '\u2500\u2500\u2500 LOCATION \u2500\u2500\u2500', value: '' });
    stats.push({ label: 'Found At', value: discovery.found_at_km.toFixed(1) + ' km from base' });
    stats.push({ label: 'Destination', value: discovery.destination_name });
    if (discovery.latitude !== undefined && discovery.longitude !== undefined) stats.push({ label: 'Coordinates', value: discovery.latitude.toFixed(4) + '\u00B0, ' + discovery.longitude.toFixed(4) + '\u00B0' });
    stats.push({ label: '\u2500\u2500\u2500 EXPEDITION \u2500\u2500\u2500', value: '' });
    if (discovery.expedition_name) stats.push({ label: 'Expedition', value: discovery.expedition_name });
    if (discovery.expedition_id) stats.push({ label: 'Expedition ID', value: '#' + discovery.expedition_id });
    if (discovery.sol) stats.push({ label: 'Sol', value: 'Sol ' + discovery.sol });
    stats.push({ label: '\u2500\u2500\u2500 TIMELINE \u2500\u2500\u2500', value: '' });
    if (discovery.discovered_at) {
        const discDate = new Date(discovery.discovered_at);
        stats.push({ label: 'Discovered', value: discDate.toLocaleDateString() + ' at ' + discDate.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) });
    }
    if (discovery.claimed_at) {
        const claimDate = new Date(discovery.claimed_at);
        stats.push({ label: 'Claimed', value: claimDate.toLocaleDateString() + ' at ' + claimDate.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) });
        const now = new Date();
        const diffMs = now - claimDate;
        const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
        if (diffDays > 0) stats.push({ label: 'In Collection', value: diffDays + ' day' + (diffDays !== 1 ? 's' : '') });
    }
    stats.push({ label: '\u2500\u2500\u2500 CATALOG \u2500\u2500\u2500', value: '' });
    stats.push({ label: 'Item ID', value: '#' + discovery.discovery_item_id });
    if (discovery.catalog_id) stats.push({ label: 'Catalog ID', value: discovery.catalog_id });
    let actionConfig = null;
    const qty = discovery.quantity || 1;
    if (discovery.rarity === 'common' || discovery.rarity === 'uncommon' || discovery.rarity === 'rare') {
        const payoutMult = discovery.rarity === 'common' ? 0.5 : discovery.rarity === 'uncommon' ? 0.75 : 1.0;
        let extractValueAll = Math.floor(discovery.enhanced_value * qty * payoutMult);
        let extractValueOne = Math.floor(discovery.enhanced_value * payoutMult);
        // Apply equipment bonuses (Research Lab, Cryo Storage) to preview
        if (discoveryValueMult > 1.0) { extractValueAll = Math.floor(extractValueAll * discoveryValueMult); extractValueOne = Math.floor(extractValueOne * discoveryValueMult); }
        if (discovery.item_type === 'biological' && bioDiscoveryValueMult > 1.0) { extractValueAll = Math.floor(extractValueAll * bioDiscoveryValueMult); extractValueOne = Math.floor(extractValueOne * bioDiscoveryValueMult); }
        const svBonusAll = Math.floor(extractValueAll * 0.50);
        const svLabelAll = svBonusAll > 0 ? ` + ${svBonusAll} SV` : '';
        const svLabelOne = Math.floor(extractValueOne * 0.50) > 0 ? ` + ${Math.floor(extractValueOne * 0.50)} SV` : '';
        actionConfig = {
            label: qty > 1 ? `Extract All ${qty}× (${extractValueAll.toLocaleString()} Shards${svLabelAll})` : `Extract (${extractValueAll.toLocaleString()} Shards${svLabelAll})`,
            className: 'btn-warning',
            onClick: () => confirmColonyExtraction(discovery, extractValueAll, true),
            secondaryAction: qty > 1 ? { label: `Extract 1× (${extractValueOne.toLocaleString()} Shards${svLabelOne})`, onClick: () => confirmColonyExtraction(discovery, extractValueOne, false) } : null,
            tertiaryAction: qty > 1 ? { label: `Shard Some…`, onClick: () => promptColonyCustomExtract(discovery, qty, extractValueOne) } : null
        };
    }
    ItemDetailModal.show({
        name: discovery.item_name, image: discovery.image_url || null,
        category: `<span style="color: ${rarityColors[discovery.rarity]}">&#9733; ${discovery.rarity.toUpperCase()}</span> DISCOVERY`,
        description: discovery.description || 'A discovery recovered from Mars.',
        stats: stats, action: actionConfig
    });
}

// Confirmation step before extraction
function confirmColonyExtraction(discovery, shardPayout, extractAll = true, quantityToExtract = null) {
    const qty = discovery.quantity || 1;
    const extractQty = quantityToExtract || (extractAll ? qty : 1);
    const quotes = [
        'Another Martian mystery catalogued! The shards are yours.',
        'Mars never gets old! Processing extraction now.',
        'Data logged. Shard harvested. Scientific curiosity: satiated.',
        'Each crystal tells a story. Extracting this one for you.',
        'Standard extraction procedure. The shards are yours for the taking.'
    ];
    const quote = quotes[Math.floor(Math.random() * quotes.length)];

    ItemDetailModal.show({
        name: `Extract ${extractQty > 1 ? extractQty + '× ' : ''}${discovery.item_name}?`,
        image: discovery.image_url || null,
        category: `<span style="color: ${discovery.rarity === 'uncommon' ? 'var(--color-success)' : 'var(--text-muted)'}">${discovery.rarity.toUpperCase()}</span> Confirm Extraction`,
        description: `"${quote}"`,
        stats: [
            { label: 'Discoveries', value: extractQty },
            { label: 'Shards Received', value: shardPayout.toLocaleString() },
            { label: 'SV Bonus', value: `+${Math.floor(shardPayout * 0.50)} SV` },
        ],
        effects: `<div style="padding:8px 10px;background:rgba(255,180,80,0.1);border-left:3px solid #ffb450;font-size:12px;color:#ccc;">
            <strong style="color:#ffb450;">Trade-off:</strong> Extracting destroys the discovery. You'll gain shards + bonus SV but lose the item permanently.
        </div>`,
        action: {
            label: `Extract (${shardPayout.toLocaleString()} Shards)`,
            className: 'btn-warning',
            onClick: () => extractColonyDiscovery(discovery.discovery_item_id, shardPayout, extractAll, quantityToExtract)
        }
    });
}

// Bug #1125: "Shard Some" — pick a custom quantity to extract from colony discoveries
function promptColonyCustomExtract(discovery, maxQty, perItemShards) {
    if (maxQty < 2) return;
    const raw = window.prompt(
        `How many "${discovery.item_name}" do you want to extract?\n\nYou have ${maxQty} available. Each yields ${perItemShards.toLocaleString()} shards.\n\nEnter a number between 1 and ${maxQty}:`,
        String(Math.min(maxQty, 5))
    );
    if (raw == null) return;
    const n = parseInt(raw, 10);
    if (isNaN(n) || n < 1 || n > maxQty) {
        showToast(`Please enter a number between 1 and ${maxQty}`, 'error');
        return;
    }
    const totalShards = perItemShards * n;
    confirmColonyExtraction(discovery, totalShards, false, n);
}

// Extract discovery for shards (extractAll: true = all stacked, false = just one)
async function extractColonyDiscovery(discoveryItemId, expectedValue, extractAll = true, quantityToExtract = null) {
    const btn = document.getElementById('mmActionBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Extracting...'; }
    try {
        const body = { discovery_item_id: discoveryItemId, extract_all: extractAll };
        if (quantityToExtract != null) body.quantity_to_extract = quantityToExtract;
        const response = await fetch('/api/discovery/analyze', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const data = await response.json();
        if (data.success) {
            ItemDetailModal.hide();
            let extractMsg = `Extracted ${data.shards_received.toFixed(0)} Shards!`;
            if (data.sv_awarded > 0) extractMsg += ` + ${data.sv_awarded} SV`;
            showToast(extractMsg, 'success', 'Extraction Complete');
            if (typeof currentBalance !== 'undefined') { currentBalance += data.shards_received; updateBalanceDisplay(); }
            if (data.sv_awarded > 0 && typeof adjustSV === 'function') adjustSV(data.sv_awarded);
            setTimeout(() => location.reload(), 1500);
        } else {
            showToast(data.error || 'Extraction failed', 'error');
            if (btn) { btn.disabled = false; btn.textContent = `Extract for ${expectedValue.toLocaleString()} Shards`; }
        }
    } catch (e) {
        showToast('Network error', 'error');
        if (btn) { btn.disabled = false; btn.textContent = `Extract for ${expectedValue.toLocaleString()} Shards`; }
    }
}
