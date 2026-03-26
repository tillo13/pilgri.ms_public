// ============================================================================
// CREW.JS - Captain Management, SV Ticker, Asset Management
// ============================================================================

/* ─── Full Image Modal ─── */
function showFullImage(src, title) {
    document.getElementById('crewModalImage').src = src;
    document.getElementById('crewModalTitle').textContent = title;
    document.getElementById('crewImageModal').style.display = 'flex';
}

/* ─── Live SV Ticker + Record SV ─── */
(function() {
    const accEl = document.getElementById('sci-sv-accumulated');
    if (!accEl) return;
    const rate = parseFloat(accEl.dataset.rate) || 0;
    if (rate <= 0) return;

    let current = parseFloat(accEl.dataset.base) || 0;
    const perSecond = rate / 3600;
    const tickEl = document.getElementById('sci-micro-tick');
    const harvestVal = document.getElementById('sci-harvest-val');
    const harvestRow = document.getElementById('sci-harvest-row');
    const totalEl = document.getElementById('sci-sv-total');
    const recordBtn = document.getElementById('record-sv-btn');
    let tickCount = 0;

    setInterval(function() {
        current += perSecond;
        tickCount++;
        accEl.textContent = current.toFixed(1);
        if (harvestVal) harvestVal.textContent = current.toFixed(1);
        // Enable button + un-dim row once >= 1
        if (current >= 1) {
            if (harvestRow) harvestRow.style.opacity = '1';
            if (recordBtn) recordBtn.disabled = false;
        }
        // Flash micro-increment every 3 seconds
        if (tickEl && tickCount % 3 === 0) {
            tickEl.textContent = '+' + perSecond.toFixed(4) + ' SV';
            tickEl.style.opacity = '1';
            setTimeout(function() { tickEl.style.opacity = '0'; }, 1800);
        }
    }, 1000);

    // Record SV action
    window.recordSV = async function() {
        if (recordBtn) { recordBtn.disabled = true; recordBtn.textContent = 'Recording...'; }
        try {
            const resp = await fetch('/api/scientist/record-sv', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
            const data = await resp.json();
            if (data.success) {
                showToast('Recorded ' + data.sv_recorded + ' SV', 'success');
                // Reset accumulated to 0, update total
                current = 0;
                accEl.textContent = '0.0';
                accEl.dataset.base = '0';
                if (harvestVal) harvestVal.textContent = '0.0';
                if (totalEl) totalEl.textContent = data.sv_available;
                if (harvestRow) harvestRow.style.opacity = '0.4';
                if (recordBtn) { recordBtn.textContent = 'Record SV'; recordBtn.disabled = true; }
            } else {
                showToast(data.error || 'Failed to record SV', 'error');
                if (recordBtn) { recordBtn.textContent = 'Record SV'; recordBtn.disabled = false; }
            }
        } catch (e) {
            showToast('Connection failed', 'error');
            if (recordBtn) { recordBtn.textContent = 'Record SV'; recordBtn.disabled = false; }
        }
    };
})();

/* ─── Scientist Swap ─── */
let _pendingSwapKey = null;

function showScientistSwapModal() {
    document.getElementById('scientist-swap-modal').style.display = 'block';
}

function confirmScientistSwap(key, name) {
    _pendingSwapKey = key;
    const sciData = JSON.parse(document.getElementById('scientistData').textContent);
    const currentKey = sciData.current ? sciData.current.key : null;
    // Use all_scientists for current too — it has _branch_bonuses populated
    const currentSci = currentKey ? sciData.all[currentKey] : null;
    const newSci = sciData.all[key];
    if (!newSci) return;

    // Branch key → display name mapping (power → Shard Generation per #1143)
    const branchNames = {power: 'Shard Generation', exploration: 'Exploration', vehicles: 'Vehicles', extraction: 'Extraction'};

    // Populate current scientist side
    if (currentSci) {
        document.getElementById('compare-current-img').src = currentSci.image_url;
        document.getElementById('compare-current-name').textContent = currentSci.name;
        document.getElementById('compare-current-specialty').textContent = currentSci.specialty;
        const cs = currentSci.stats;
        document.getElementById('compare-current-stats').innerHTML =
            `Nav: ${cs.navigation} &middot; Anl: ${cs.analysis}<br>Geo: ${cs.geology} &middot; Eng: ${cs.engineering}`;
        const cb = currentSci._branch_bonuses || {};
        document.getElementById('compare-current-bonuses').innerHTML =
            Object.entries(cb).map(([b, info]) => `${branchNames[b] || b.charAt(0).toUpperCase()+b.slice(1)}: ${info.label}`).join('<br>');
    }

    // Populate new scientist side
    document.getElementById('compare-new-img').src = newSci.image_url;
    document.getElementById('compare-new-name').textContent = newSci.name;
    document.getElementById('compare-new-specialty').textContent = newSci.specialty;
    const ns = newSci.stats;
    document.getElementById('compare-new-stats').innerHTML =
        `Nav: ${ns.navigation} &middot; Anl: ${ns.analysis}<br>Geo: ${ns.geology} &middot; Eng: ${ns.engineering}`;
    const nb = newSci._branch_bonuses || {};
    document.getElementById('compare-new-bonuses').innerHTML =
        Object.entries(nb).map(([b, info]) => `${branchNames[b] || b.charAt(0).toUpperCase()+b.slice(1)}: ${info.label}`).join('<br>');

    document.getElementById('scientist-confirm-modal').style.display = 'block';
}

async function executeScientistSwap() {
    if (!_pendingSwapKey) return;
    document.getElementById('scientist-confirm-modal').style.display = 'none';
    const errEl = document.getElementById('scientist-swap-error');
    errEl.style.display = 'none';

    try {
        const resp = await fetch('/api/scientist/reassign', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({scientist_key: _pendingSwapKey})
        });
        const data = await resp.json();
        if (data.success) {
            // Close modals immediately
            document.getElementById('scientist-swap-modal').style.display = 'none';
            let msg = 'Scientist reassigned!';
            if (data.sv_auto_recorded) msg += ` (${data.sv_auto_recorded} SV auto-recorded)`;
            if (typeof showToast === 'function') showToast(msg, 'success');
            // Hard reload to Scientist tab so new scientist is clearly visible
            setTimeout(() => { window.location.href = '/crew?tab=scientist'; }, 800);
        } else {
            errEl.textContent = data.error || 'Failed to reassign';
            errEl.style.display = 'block';
        }
    } catch (e) {
        errEl.textContent = 'Network error';
        errEl.style.display = 'block';
    }
    _pendingSwapKey = null;
}

// Captain image/video toggle
function showCaptainImage() {
    document.getElementById('captainImageTab').style.display = 'flex';
    document.getElementById('captainVideoTab').style.display = 'none';
    document.getElementById('imageTabButton2').style.background = 'var(--color-primary)';
    document.getElementById('imageTabButton2').style.color = 'white';
    document.getElementById('videoTabButton2').style.background = 'var(--bg-tertiary)';
    document.getElementById('videoTabButton2').style.color = 'var(--text-secondary)';
}
function showCaptainVideo() {
    document.getElementById('captainImageTab').style.display = 'none';
    document.getElementById('captainVideoTab').style.display = 'flex';
    document.getElementById('videoTabButton2').style.background = 'var(--color-primary)';
    document.getElementById('videoTabButton2').style.color = 'white';
    document.getElementById('imageTabButton2').style.background = 'var(--bg-tertiary)';
    document.getElementById('imageTabButton2').style.color = 'var(--text-secondary)';
}

// Captain name editing
function editCaptainName() {
    document.getElementById('captainNameDisplay').style.display = 'none';
    document.getElementById('captainNameEdit').style.display = 'flex';
    document.getElementById('captainNameInput').focus();
    document.getElementById('captainNameInput').select();
}

function cancelCaptainEdit() {
    document.getElementById('captainNameEdit').style.display = 'none';
    document.getElementById('captainNameDisplay').style.display = 'flex';
}

async function saveCaptainName() {
    const input = document.getElementById('captainNameInput');
    const newName = input.value.trim();

    if (!newName || newName.length < 1) {
        showToast('Name cannot be empty', 'error');
        return;
    }
    if (newName.length > 30) {
        showToast('Name must be 30 characters or less', 'error');
        return;
    }

    try {
        const res = await fetch('/api/commander/rename', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name: newName})
        });
        const data = await res.json();

        if (data.success) {
            // Update all places where the name is displayed
            document.getElementById('captainNameText').textContent = newName;

            // Also update the nav bar commander name if it exists
            const navName = document.getElementById('commanderNameText');
            if (navName) navName.textContent = newName;

            // Update the quick status bar captain name
            const quickStatusName = document.querySelector('#captain-mission-card .text-sm.font-semibold');
            if (quickStatusName) quickStatusName.textContent = newName;

            cancelCaptainEdit();
            showToast('Captain name updated!', 'success');
        } else {
            showToast(data.error || 'Failed to update name', 'error');
        }
    } catch (e) {
        showToast('Network error', 'error');
    }
}


/* ─── Captain Management ─── */
const imageTabButton = document.getElementById('imageTabButton');
const videoTabButton = document.getElementById('videoTabButton');
const imageTab = document.getElementById('imageTab');
const videoTab = document.getElementById('videoTab');

if (imageTabButton && videoTabButton) {
    imageTabButton.addEventListener('click', function() {
        imageTabButton.style.background = 'var(--color-primary)'; imageTabButton.style.color = 'white';
        videoTabButton.style.background = 'var(--bg-tertiary)'; videoTabButton.style.color = 'var(--text-primary)';
        imageTab.style.display = 'block'; videoTab.style.display = 'none';
    });
    videoTabButton.addEventListener('click', function() {
        videoTabButton.style.background = 'var(--color-primary)'; videoTabButton.style.color = 'white';
        imageTabButton.style.background = 'var(--bg-tertiary)'; imageTabButton.style.color = 'var(--text-primary)';
        videoTab.style.display = 'block'; imageTab.style.display = 'none';
    });
}

async function setActiveCommander(assetId, event) {
    event.stopPropagation();
    const card = event.target.closest('.commander-card');
    const newImageUrl = card.querySelector('img').src;
    showProcessing('Setting as active captain...');
    try {
        const response = await fetch(`/api/commander/set_primary/${assetId}`, { method: 'POST' });
        const data = await response.json();
        if (data.success) {
            // Update main display image
            const mainImage = document.getElementById('mainCommanderImage');
            if (mainImage) mainImage.src = newImageUrl;
            // Reload page to reflect all changes properly
            hideProcessing();
            showToast('Captain activated!', 'success', 'Active Captain Set', 2000);
            setTimeout(() => location.reload(), 1500);
        } else { hideProcessing(); showToast(data.error || 'Failed to set active captain', 'error', 'Activation Failed'); }
    } catch (error) { hideProcessing(); showToast(error.message, 'error', 'Network Error'); }
}

async function deleteAsset(assetId, assetType, event) {
    event.stopPropagation();
    showProcessing('Deleting...');
    try {
        const response = await fetch(`/api/asset/delete/${assetId}`, { method: 'POST' });
        const data = await response.json();
        if (data.success) {
            hideProcessing();
            const card = event.target.closest('.commander-card');
            if (card) { card.style.transition = 'opacity 0.3s'; card.style.opacity = '0'; setTimeout(() => card.remove(), 300); }
            showToast('Asset deleted', 'success', 'Deleted');
        } else { hideProcessing(); showToast(data.error || 'Delete failed', 'error'); }
    } catch (error) { hideProcessing(); showToast(error.message, 'error'); }
}

function toggleStatInfo(stat) {
    const infoEl = document.getElementById('info-' + stat);
    if (!infoEl) return;
    const isOpen = infoEl.style.display === 'block';
    // Close all
    document.querySelectorAll('.stat-info').forEach(el => el.style.display = 'none');
    document.querySelectorAll('.stat-pill').forEach(el => el.classList.remove('active'));
    // Open this one if it was closed
    if (!isOpen) {
        infoEl.style.display = 'block';
        infoEl.previousElementSibling.classList.add('active');
    }
}

// ============================================================================
// CAPTAIN SERVICES (Shard Infusion, Modify Appearance, Video Briefing)
// ============================================================================

async function purchaseShardInfusion() {
    if (!confirm('Infuse your captain with Sepolia energy? All stats will be rerolled randomly.')) return;
    try {
        const resp = await fetch('/api/shop/reroll_stats', { method: 'POST', headers: {'Content-Type': 'application/json'} });
        const data = await resp.json();
        if (data.success) {
            showToast('Stats infused! Your captain has new attributes.', 'success');
            setTimeout(() => location.reload(), 1500);
        } else {
            showToast(data.error || 'Failed to infuse stats', 'error');
        }
    } catch (e) { showToast('Connection error', 'error'); }
}

async function purchaseModifyAppearance() {
    const prompt = document.getElementById('modifyPrompt')?.value?.trim();
    if (!prompt) { showToast('Describe the change you want', 'error'); return; }
    if (!confirm('Modify your captain\'s appearance? This will generate a new image.')) return;
    try {
        showToast('Generating new appearance...', 'info');
        const resp = await fetch('/api/shop/modify_character', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ prompt })
        });
        const data = await resp.json();
        if (data.success) {
            showToast('New look generated! Reloading...', 'success');
            setTimeout(() => location.reload(), 1500);
        } else {
            showToast(data.error || 'Failed to modify appearance', 'error');
        }
    } catch (e) { showToast('Connection error', 'error'); }
}

async function purchaseVideoBriefing() {
    if (!confirm('Generate a mission briefing video? This costs 90 shards and takes about 60 seconds.')) return;
    try {
        showToast('Generating video... this takes about 60 seconds', 'info');
        const resp = await fetch('/api/shop/generate_video', {
            method: 'POST', headers: {'Content-Type': 'application/json'}
        });
        const data = await resp.json();
        if (data.success) {
            showToast('Video generated! Reloading...', 'success');
            setTimeout(() => location.reload(), 2000);
        } else {
            showToast(data.error || 'Failed to generate video', 'error');
        }
    } catch (e) { showToast('Connection error', 'error'); }
}
