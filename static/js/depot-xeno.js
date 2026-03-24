/* Depot Page - Xenobiology Lab & Mars Conditions Help */

// Sanitize error messages - NEVER show blockchain/crypto terms to users
function sanitizeXenoError(msg) {
    if (!msg) return 'Unable to complete request. Please try again.';
    const lower = msg.toLowerCase();
    const blockedTerms = ['transaction', 'nonce', 'gas', 'blockchain', 'eth', 'wallet', 'hash', '0x', 'code', '-32'];
    if (blockedTerms.some(t => lower.includes(t))) {
        return 'Unable to complete request. Please try again.';
    }
    return msg;
}

// ============================================================================
// XENOBIOLOGY LAB MODAL
// ============================================================================
let xenoState = null;

async function openXenobiologyModal() {
    MarsModal.show({
        title: 'Xenobiology Lab',
        subtitle: 'Ancient Martian samples reveal secrets of captain enhancement',
        icon: '🧬',
        width: 'lg',
        body: '<div style="text-align:center; padding:30px; color:var(--text-muted);"><div class="xeno-spinner"></div>Initializing lab systems...</div>'
    });

    try {
        const r = await fetch('/api/xenobiology/status');
        const data = await r.json();
        if (!data.success) {
            showToast(sanitizeXenoError(data.error) || 'Failed to load research data', 'error');
            MarsModal.hide();
            return;
        }
        xenoState = data;
        renderXenobiologyContent(data);
    } catch (e) {
        showToast('Failed to connect to lab systems', 'error');
        MarsModal.hide();
    }
}

function renderXenobiologyContent(data) {
    const statNames = { leadership: 'Leadership', strategy: 'Strategy', exploration: 'Exploration', logistics: 'Logistics', charisma: 'Charisma' };

    let statsHtml = '';
    for (const [stat, info] of Object.entries(data.effective_stats)) {
        const canUpgrade = info.can_upgrade && data.research_points > 0;
        statsHtml += `
            <div class="xeno-stat-row">
                <div class="xeno-stat-name">${statNames[stat]}</div>
                <div class="xeno-stat-bars">
                    <div class="xeno-stat-base" style="width:${(info.base / 100) * 100}%"></div>
                    <div class="xeno-stat-bonus" style="width:${(info.bonus / 100) * 100}%"></div>
                </div>
                <div class="xeno-stat-value">${info.total} <span class="xeno-bonus-text">${info.bonus > 0 ? `(+${info.bonus})` : ''}</span></div>
                <button class="btn xeno-upgrade-btn" ${canUpgrade ? '' : 'disabled'} onclick="upgradeXenoStat('${stat}')">+1</button>
            </div>`;
    }

    const body = `
        <div class="mm-section-label">Run Experiment</div>
        <div class="mm-desc">Analyze Martian discoveries to extract research points. Costs escalate as understanding deepens.</div>
        <div class="mm-stats mm-stats-3">
            <div class="mm-stat" style="text-align:center;"><div class="mm-stat-value">${data.experiment_cost.toLocaleString()}</div><div class="mm-stat-label">Cost</div></div>
            <div class="mm-stat" style="text-align:center;"><div class="mm-stat-value">1-${data.max_roll}</div><div class="mm-stat-label">Roll Range</div></div>
            <div class="mm-stat" style="text-align:center;"><div class="mm-stat-value" style="color:var(--color-success);">${data.research_points}</div><div class="mm-stat-label">Points</div></div>
        </div>
        <button id="xenoRunExperiment" class="btn btn-experiment" onclick="runXenoExperiment()" ${data.can_afford ? '' : 'disabled'}>
            ${data.can_afford ? `Run Experiment (${data.experiment_cost.toLocaleString()} Shards)` : `Need ${data.experiment_cost.toLocaleString()} Shards`}
        </button>
        <hr class="mm-divider">
        <div class="mm-section-label">Enhance Captain</div>
        <div class="mm-desc">Spend research points to permanently enhance abilities. Each stat can gain up to +10 bonus.</div>
        <div class="xeno-stats-grid">${statsHtml}</div>
    `;

    MarsModal.update({ body });
}

async function runXenoExperiment() {
    const btn = document.getElementById('xenoRunExperiment');
    if (btn) { btn.disabled = true; btn.textContent = 'Analyzing...'; }

    try {
        const r = await fetch('/api/xenobiology/run_experiment', { method: 'POST' });
        const data = await r.json();
        if (data.success) {
            showToast(`Experiment complete! Gained ${data.points_gained} research point${data.points_gained > 1 ? 's' : ''} (rolled 1-${data.max_roll})`, 'success', 'Research', 5000);
            openXenobiologyModal();
        } else {
            showToast(sanitizeXenoError(data.error) || 'Experiment failed', 'error');
            if (btn) { btn.disabled = false; btn.textContent = 'Run Experiment'; }
        }
    } catch (e) {
        showToast('Connection error', 'error');
        if (btn) { btn.disabled = false; btn.textContent = 'Run Experiment'; }
    }
}

async function upgradeXenoStat(stat) {
    try {
        const r = await fetch('/api/xenobiology/upgrade_stat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ stat })
        });
        const data = await r.json();
        if (data.success) {
            showToast(`${stat.charAt(0).toUpperCase() + stat.slice(1)} upgraded to ${data.new_total} (+${data.new_bonus})`, 'success');
            openXenobiologyModal();
        } else {
            showToast(sanitizeXenoError(data.error) || 'Upgrade failed', 'error');
        }
    } catch (e) {
        showToast('Connection error', 'error');
    }
}

function closeXenobiologyModal() { MarsModal.hide(); }

// Mars Conditions Help Modal
function showConditionsHelp() {
    ItemDetailModal.show({
        name: 'Mars Atmospheric Conditions',
        image: null,
        category: `<img src="${DEPOT_ICONS.env_sun_power}" alt="" style="width: 16px; height: 16px; vertical-align: middle;"> Environmental Status`,
        description: 'Real-time atmospheric data affects your colony operations. These conditions are calculated based on Mars orbital mechanics and dust storm patterns.',
        stats: [
            { label: 'Solar Efficiency', value: 'Shard generation rate from solar arrays' },
            { label: 'Status', value: 'Current atmospheric clarity level' },
            { label: 'Sun Angle', value: 'Optimal range: 45-75° for best collection' },
            { label: 'Fee Multiplier', value: 'Transaction costs based on interference' }
        ],
        effects: `<div class="leading-relaxed text-sm">
            <div class="mb-8"><strong class="text-success">Clear Skies:</strong> 95-100% efficiency, 1.0× fees</div>
            <div class="mb-8"><strong class="text-mars">Dusty:</strong> 70-90% efficiency, 1.1-1.2× fees</div>
            <div class="mb-8"><strong class="text-danger">Dust Storm:</strong> 30-60% efficiency, 1.3-1.5× fees</div>
            <div class="text-primary italic mt-12">Conditions update in real-time as Mars rotates.</div>
        </div>`
    });
}
