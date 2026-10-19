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
            const data = await apiPost('/api/scientist/record-sv');
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
        const data = await apiPost('/api/scientist/reassign', {scientist_key: _pendingSwapKey});
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
        const data = await apiPost('/api/commander/rename', {name: newName});

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


async function saveCaptainNameFromServices() {
    const input = document.getElementById('captainNameInputServices');
    const newName = input.value.trim();
    if (!newName || newName.length < 1) { showToast('Name cannot be empty', 'error'); return; }
    if (newName.length > 30) { showToast('Name must be 30 characters or less', 'error'); return; }
    try {
        const data = await apiPost('/api/commander/rename', {name: newName});
        if (data.success) {
            document.getElementById('captainNameText').textContent = newName;
            const navName = document.getElementById('commanderNameText');
            if (navName) navName.textContent = newName;
            showToast('Captain renamed to ' + newName + '!', 'success');
        } else {
            showToast(data.error || 'Failed to update name', 'error');
        }
    } catch (e) { showToast('Network error', 'error'); }
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

function _highlightCaptainTab() {
    const btn = document.querySelector('[data-tab="captain"]');
    if (btn) {
        btn.style.animation = 'none'; btn.offsetHeight; // Force reflow
        btn.style.outline = '2px solid var(--color-success)';
        btn.style.outlineOffset = '2px';
        setTimeout(() => { btn.style.outline = ''; btn.style.outlineOffset = ''; }, 5000);
    }
}

async function purchaseShardInfusion() {
    MarsModal.show({
        title: 'Shard Infusion', badge: 'Confirm',
        body: '<div style="text-align:center;padding:8px 0;">' +
            '<p style="margin-bottom:12px;">Channel Sepolia energy into your captain. Each stat has a chance to gain <strong>+1</strong>.</p>' +
            '<p style="font-size:12px;color:var(--text-secondary);">Stats can only go up, never down. Higher stats have lower improvement chance.</p></div>',
        footer: '<button class="btn btn-primary mm-btn-full" id="mmActionBtn">Infuse Stats</button>',
        width: 'sm'
    });
    document.getElementById('mmActionBtn').onclick = async () => {
        MarsModal.show({ title: 'Infusing...', body: '<div style="text-align:center;padding:20px;color:var(--text-muted);">Channeling Sepolia energy...</div>', width: 'sm' });
        try {
            const data = await apiPost('/api/shop/reroll_stats');
            if (data.success) {
                // Build stat change display
                let statsHtml = '<div style="display:grid;gap:6px;margin:12px 0;">';
                const names = ['leadership', 'strategy', 'exploration', 'logistics', 'charisma'];
                names.forEach(s => {
                    const old_v = (data.old_stats || {})[s] || 0;
                    const new_v = (data.stats || {})[s] || old_v;
                    const changed = new_v > old_v;
                    statsHtml += `<div style="display:flex;justify-content:space-between;padding:4px 8px;background:${changed ? 'rgba(74,222,128,0.1)' : 'transparent'};border-radius:4px;">` +
                        `<span style="text-transform:capitalize;">${s}</span>` +
                        `<span style="font-weight:700;${changed ? 'color:var(--color-success);' : ''}">${old_v}${changed ? ' → ' + new_v + ' (+1)' : ' (no change)'}</span></div>`;
                });
                statsHtml += '</div>';
                const gained = data.total_gained || 0;
                const title = gained > 0 ? `${gained} Stat${gained > 1 ? 's' : ''} Improved!` : 'No Change';
                MarsModal.show({
                    title, badge: `Infusion #${data.infusion_number || '?'}`, theme: gained > 0 ? 'success' : 'warning',
                    body: statsHtml + `<p style="text-align:center;font-size:12px;color:var(--text-secondary);margin-top:8px;">Next infusion: ${(data.next_infusion_cost || 0).toLocaleString()} shards</p>`,
                    footer: '<button class="btn btn-primary mm-btn-full" onclick="MarsModal.hide();switchTab(\'captain\');">View Captain Stats</button>',
                    width: 'sm'
                });
                _highlightCaptainTab();
                setBalance(data.new_balance);
            } else {
                MarsModal.hide();
                showToast(data.error || 'Failed to infuse stats', 'error');
            }
        } catch (e) { MarsModal.hide(); showToast('Connection error', 'error'); }
    };
}

async function purchaseModifyAppearance() {
    const prompt = document.getElementById('modifyPrompt')?.value?.trim();
    if (!prompt) { showToast('Describe the change you want', 'error'); return; }
    MarsModal.show({
        title: 'Modify Appearance', badge: 'Confirm',
        body: `<div style="text-align:center;padding:8px 0;"><p>Your captain's appearance will be updated with:</p><p style="font-weight:700;color:var(--color-warning);margin:8px 0;">"${prompt}"</p><p style="font-size:12px;color:var(--text-secondary);">This takes a few seconds to generate. View the result on the Captain tab.</p></div>`,
        footer: '<button class="btn btn-primary mm-btn-full" id="mmActionBtn">Modify Captain</button>',
        width: 'sm'
    });
    document.getElementById('mmActionBtn').onclick = async () => {
        MarsModal.show({ title: 'Generating...', body: '<div style="text-align:center;padding:20px;color:var(--text-muted);">AI is updating your captain\'s appearance...</div>', width: 'sm' });
        try {
            const data = await apiPost('/api/shop/modify_character', { prompt });
            if (data.success) {
                MarsModal.show({
                    title: 'Appearance Updated!', badge: 'Complete', theme: 'success',
                    body: '<div style="text-align:center;padding:8px 0;"><p>Your captain has a new look. Switch to the <strong>Captain</strong> tab to see the changes.</p></div>',
                    footer: '<button class="btn btn-primary mm-btn-full" onclick="MarsModal.hide();switchTab(\'captain\');setTimeout(()=>location.reload(),300);">View Captain</button>',
                    width: 'sm'
                });
                _highlightCaptainTab();
            } else {
                MarsModal.hide();
                showToast(data.error || 'Failed to modify appearance', 'error');
            }
        } catch (e) { MarsModal.hide(); showToast('Connection error', 'error'); }
    };
}

async function purchaseVideoBriefing() {
    MarsModal.show({
        title: 'Mission Briefing Video', badge: 'Confirm',
        body: '<div style="text-align:center;padding:8px 0;"><p>Generate an animated mission briefing starring your captain.</p><p style="font-size:12px;color:var(--text-secondary);margin-top:8px;">Takes about 60 seconds. View the result on the Captain tab under Video.</p></div>',
        footer: '<button class="btn btn-primary mm-btn-full" id="mmActionBtn">Generate Video (90 shards)</button>',
        width: 'sm'
    });
    document.getElementById('mmActionBtn').onclick = async () => {
        MarsModal.show({ title: 'Generating Video...', body: '<div style="text-align:center;padding:20px;color:var(--text-muted);">Creating your mission briefing... this takes about 60 seconds.</div>', width: 'sm' });
        try {
            const data = await apiPost('/api/shop/generate_video');
            if (data.success) {
                MarsModal.show({
                    title: 'Video Ready!', badge: 'Complete', theme: 'success',
                    body: '<div style="text-align:center;padding:8px 0;"><p>Your mission briefing video is ready. Switch to the <strong>Captain</strong> tab and tap <strong>Video</strong> to watch it.</p></div>',
                    footer: '<button class="btn btn-primary mm-btn-full" onclick="MarsModal.hide();switchTab(\'captain\');setTimeout(()=>location.reload(),300);">View Video</button>',
                    width: 'sm'
                });
                _highlightCaptainTab();
            } else {
                MarsModal.hide();
                showToast(data.error || 'Failed to generate video', 'error');
            }
        } catch (e) { MarsModal.hide(); showToast('Connection error', 'error'); }
    };
}
