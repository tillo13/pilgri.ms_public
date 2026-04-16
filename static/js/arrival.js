// ============================================================================
// ARRIVAL.JS - Character creation, mining, and deployment
// ============================================================================

let imageHistory = [], originalImageUrl = null;

// File Handling
function handleFile(file) {
    const reader = new FileReader();
    reader.onload = e => { const p = $('previewImage'); if (p) p.src = e.target.result; show('previewContainer'); setTimeout(() => processImage(file), 500); };
    reader.readAsDataURL(file);
}

async function processImage(file) {
    if (file.size > 30 * 1024 * 1024) { showError(`Image too large (${(file.size/1024/1024).toFixed(1)} MB). Max 30 MB.`); return; }
    try { showProcessing('Preparing your captain...'); const fd = new FormData(); fd.append('image', file); const r = await apiCall('/upload', { method: 'POST', body: fd }); hideProcessing(); handleImageResult(r); }
    catch (e) { hideProcessing(); showError(e.message); }
}

async function useDefaultImage() {
    try { showProcessing('Assigning your captain...'); const r = await apiCall('/random-default-leader'); hideProcessing(); handleImageResult(r); if (r.other_leaders?.length) showAlternativeLeaders(r.other_leaders); }
    catch (e) { hideProcessing(); showError(e.message); }
}

function handleImageResult(r) {
    const img = $('resultImage'); if (img) img.src = r.image_url;
    displayStats(r.stats); originalImageUrl = r.image_url; imageHistory = [r.image_url];
    const intro = $('creationIntro'); if (intro) intro.classList.add('hidden');
    show('resultContainer'); updateCommanderNavigation();
}

function showAlternativeLeaders(leaders) {
    const c = $('resultContainer'); if (!c) return;
    const existing = $('alternativeCarousel'); if (existing) existing.remove();
    c.insertAdjacentHTML('afterbegin', `<div id="alternativeCarousel" style="margin-bottom:20px;"><div class="story-panel" style="background:var(--bg-secondary);"><h4>Want a different captain?</h4><p class="help-text" style="margin-bottom:12px;">Click any portrait to switch, or upload your own.</p><div style="display:flex;gap:10px;overflow-x:auto;padding:10px 0;">${leaders.map(l => `<div onclick="switchToLeader('${l.id}')" style="cursor:pointer;flex-shrink:0;"><img src="${l.image_url}" style="width:100px;height:100px;object-fit:cover;border-radius:8px;border:2px solid var(--border-default);transition:all 0.2s;" onmouseover="this.style.borderColor='var(--color-primary)';this.style.transform='scale(1.05)'" onmouseout="this.style.borderColor='var(--border-default)';this.style.transform='scale(1)'"></div>`).join('')}</div></div></div>`);
}

async function switchToLeader(id) {
    try { showProcessing('Loading captain...'); const r = await apiCall(`/api/switch-leader/${id}`, { method: 'POST' }); hideProcessing(); const img = $('resultImage'); if (img) img.src = r.image_url; displayStats(r.stats); originalImageUrl = r.image_url; imageHistory = [r.image_url]; $('alternativeCarousel')?.scrollIntoView({ behavior: 'smooth' }); }
    catch (e) { hideProcessing(); showError(e.message); }
}

function updateCommanderNavigation() {
    $$('.nav-item, .breadcrumb-item').forEach(item => { const icon = item.querySelector('.nav-icon, .breadcrumb-icon'); if (icon?.textContent.trim().includes('👤')) { item.classList.add('completed'); const badge = item.querySelector('.nav-badge, .breadcrumb-badge'); if (badge) badge.textContent = '✓'; } });
}

// Stats
async function rerollStats() {
    try { showProcessing('Rolling new attributes...'); const r = await apiCall('/reroll-stats', { method: 'POST' }); hideProcessing(); displayStats(r.stats); }
    catch (e) { hideProcessing(); showError(e.message); }
}

function displayStats(stats) {
    setTimeout(() => { let total = 0; Object.entries(stats).forEach(([s, v]) => { const bar = $(s + 'Bar'), val = $(s + 'Value'); if (bar) bar.style.width = (v / 90) * 100 + '%'; if (val) val.textContent = v; total += v; }); const t = $('totalScore'); if (t) t.textContent = total; }, 200);
}

// Mining
async function triggerMining(e) {
    const btn = e.target; showProcessing('Mining asteroid for Shards...'); btn.disabled = true;
    try { const data = await apiPost('/api/asteroid_impact'); if (data.success) location.reload(); else { hideProcessing(); showError(data.error || 'Mining failed'); btn.disabled = false; } }
    catch (err) { hideProcessing(); showError('Network error: ' + err.message); btn.disabled = false; }
}

async function claimAdditionalCache(e) {
    const btn = e.target; btn.disabled = true; showProcessing('Searching for additional deposits...');
    try { await apiPost('/api/clear_session_wallet'); const data = await apiPost('/api/asteroid_impact'); if (data.success) { showToast('Found more Shards!', 'success', 'Additional Cache!'); setTimeout(() => location.reload(), 1500); } else { hideProcessing(); showError(data.error || 'No caches available'); btn.disabled = false; } }
    catch (err) { hideProcessing(); showError('Network error: ' + err.message); btn.disabled = false; }
}

// Mars Location
function generateMarsLocation() {
    $('mars-lat').textContent = 'Scanning...'; $('mars-lon').textContent = 'Scanning...'; $('landmark-info').innerHTML = '<span style="opacity:0.7;">Analyzing surface data...</span>';
    apiGet('/api/arrival/mars_location').then(data => {
        if (data.success) {
            const c = data.coordinates, l = data.landmarks;
            setTimeout(() => { $('mars-lat').textContent = c.latitude.toFixed(4); $('mars-lon').textContent = c.longitude.toFixed(4); }, 300);
            if (l?.length) { setTimeout(() => { $('landmark-info').innerHTML = l.slice(0, 3).map((m, i) => `<div style="margin-bottom:${i < 2 ? '10px' : '0'};padding-bottom:${i < 2 ? '10px' : '0'};border-bottom:${i < 2 ? '1px solid rgba(255,255,255,0.15)' : 'none'};"><div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;"><span style="font-size:16px;">${['🎯', '📍', '🗺️'][i]}</span>${m.link ? `<a href="${m.link}" target="_blank" rel="noopener" style="color:var(--text-inverse);text-decoration:none;border-bottom:1px dashed rgba(255,255,255,0.5);"><strong>${m.name}</strong></a>` : `<strong>${m.name}</strong>`}<span style="opacity:0.7;font-size:11px;">(${m.type})</span></div><div style="opacity:0.85;font-size:12px;padding-left:24px;">${m.distance_km.toFixed(1)} km • ${m.travel_days.toFixed(1)} days${m.diameter_km ? ` • ${m.diameter_km} km` : ''}</div></div>`).join(''); }, 600); }
            else setTimeout(() => { $('landmark-info').innerHTML = '⚠️ No major landmarks within 5000 km.<br><span style="opacity:0.8;">Uncharted territory!</span>'; }, 600);
        } else generateMockMarsLocation();
    }).catch(() => generateMockMarsLocation());
}

function generateMockMarsLocation() {
    $('mars-lat').textContent = (Math.random() * 180 - 90).toFixed(4); $('mars-lon').textContent = (Math.random() * 360).toFixed(4);
    const m = [{ name: 'Olympus Mons', type: 'Volcano', d: Math.random() * 3000 + 500, link: 'https://planetarynames.wr.usgs.gov/Feature/4390' }, { name: 'Valles Marineris', type: 'Canyon', d: Math.random() * 3000 + 800, link: 'https://planetarynames.wr.usgs.gov/Feature/6288' }, { name: 'Hellas Planitia', type: 'Basin', d: Math.random() * 3000 + 1200, link: 'https://planetarynames.wr.usgs.gov/Feature/2439' }];
    $('landmark-info').innerHTML = m.map((l, i) => `<div style="margin-bottom:${i < 2 ? '10px' : '0'};padding-bottom:${i < 2 ? '10px' : '0'};border-bottom:${i < 2 ? '1px solid rgba(255,255,255,0.15)' : 'none'};"><div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;"><span style="font-size:16px;">${['🎯', '📍', '🗺️'][i]}</span>${l.link ? `<a href="${l.link}" target="_blank" rel="noopener" style="color:var(--text-inverse);text-decoration:none;border-bottom:1px dashed rgba(255,255,255,0.5);"><strong>${l.name}</strong></a>` : `<strong>${l.name}</strong>`}<span style="opacity:0.7;font-size:11px;">(${l.type})</span></div><div style="opacity:0.85;font-size:12px;padding-left:24px;">${l.d.toFixed(0)} km • ${(l.d / 16).toFixed(1)} days</div></div>`).join('');
}

function startFreshJourney() {
    showProcessing('Resetting journey...');
    apiPost('/reset').then(data => { if (data.success) location.href = '/arrival/mining'; else { hideProcessing(); showError('Failed: ' + (data.error || 'Unknown')); } }).catch(e => { hideProcessing(); showError('Network error: ' + e.message); });
}

async function selectLeader(id) {
    try { showProcessing('Loading captain...'); await apiCall(`/api/switch-leader/${id}`, { method: 'POST' }); location.reload(); }
    catch (e) { hideProcessing(); showError(e.message); }
}

// Init
document.addEventListener('DOMContentLoaded', function() {
    console.log('🚀 Arrival initialized');
    const file = $('fileInput'), cam = $('cameraInput');
    if (file) file.onchange = e => { if (e.target.files[0]) handleFile(e.target.files[0]); };
    if (cam) cam.onchange = e => { if (e.target.files[0]) handleFile(e.target.files[0]); };
    if (typeof window.imageHistoryData !== 'undefined') { imageHistory = window.imageHistoryData.image_history || []; originalImageUrl = window.imageHistoryData.original_image_url; }
    $$('a[href^="/arrival/"]').forEach(l => l.onclick = function() { const h = this.getAttribute('href'); showProcessing(h.includes('crew') ? 'Accessing crew manifest...' : h.includes('deploy') ? 'Preparing for descent...' : h.includes('mining') ? 'Accessing cache...' : 'Loading...'); });
});
