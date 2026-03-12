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
