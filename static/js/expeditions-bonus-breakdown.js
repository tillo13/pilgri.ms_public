// ============================================================================
// EXPEDITIONS-BONUS-BREAKDOWN.JS — Active Bonus chip click handler.
//
// Each chip in the "Active Bonuses" panel has data-bonus-key="<effect_key>".
// Clicking a chip opens a MarsModal showing the per-source contribution rows
// pulled from /api/upgrade-effects/breakdown — captains see exactly which
// upgrade / building / tech / bond produced each +N%.
// ============================================================================

// Cache per source ('all' for /expeditions, 'tech' for the Lab/Research summary — bug #1482).
const _bonusBreakdownCache = {};

const LAYER_LABEL = {
    upgrade: 'Player Upgrades',
    infra:   'Infrastructure',
    tech:    'Tech Tree',
    bond:    'ARIA Fragment Bonds',
};

const LAYER_ORDER = ['upgrade', 'infra', 'tech', 'bond'];

const fmt = (n) => {
    const v = Number(n);
    if (Number.isNaN(v)) return String(n);
    return Math.abs(v) < 1 ? v.toFixed(3).replace(/0+$/, '').replace(/\.$/, '') : v.toFixed(2);
};

// Format a contribution value depending on the op tag
function formatContribution(value, op) {
    if (typeof value === 'boolean') return value ? 'ON' : 'OFF';
    const v = Number(value);
    if (op === 'add') return `+${(v * 100).toFixed(1)}%`;
    if (op === 'mult' || op === 'max_then_mult') return `×${v.toFixed(3)} (${v >= 1 ? '+' : '−'}${Math.abs((v - 1) * 100).toFixed(1)}%)`;
    return fmt(v);
}

function formatFinal(value, op) {
    if (typeof value === 'boolean') return value ? 'ON' : 'OFF';
    const v = Number(value || 0);
    if (op === 'add') return `+${(v * 100).toFixed(1)}%`;
    if (op === 'mult' || op === 'max_then_mult') return `${v.toFixed(3)}× (${v >= 1 ? '+' : '−'}${Math.abs((v - 1) * 100).toFixed(1)}%)`;
    return fmt(v);
}

function mergeBlurb(op) {
    switch (op) {
        case 'max_then_mult':
            return 'Within Player Upgrades and Infrastructure: <strong>max()</strong> wins (best level supersedes lower ones). Tech Tree: each tech counts once at its highest level, distinct techs <strong>add</strong> within a branch, then × across branches. ARIA Bonds: × on top. <strong>Final = max(upgrades) × max(infra) × tech × bond</strong>.';
        case 'mult':
            return 'Cost reductions <strong>stack multiplicatively</strong> across every source. <strong>Final = product of all rows</strong> (lower = better — a cost mult of 0.60 means you pay 60%, i.e. −40% off).';
        case 'add':
            return 'All contributions <strong>add together</strong> across every source. <strong>Final = sum of all rows</strong>.';
        case 'or':
            return 'Boolean flag — turns <strong>ON</strong> if any single source provides it. No stacking.';
        default:
            return '';
    }
}

async function loadBonusBreakdown(source) {
    source = source || 'all';
    if (_bonusBreakdownCache[source]) return _bonusBreakdownCache[source];
    try {
        const qs = source === 'tech' ? '?source=tech' : '';
        const r = await fetch('/api/upgrade-effects/breakdown' + qs, { credentials: 'same-origin' });
        const data = await r.json();
        if (data && data.success) {
            _bonusBreakdownCache[source] = data;
            return data;
        }
    } catch (e) {
        console.error('breakdown fetch failed', e);
    }
    return null;
}

function renderBreakdownBody(key, data, source) {
    const meta = (data.meta || {})[key] || { label: key, op: 'add' };
    const techOnly = (source || data.source) === 'tech';
    const rows = (data.breakdown || {})[key] || [];
    const finalVal = (data.finals || {})[key];

    if (!rows.length) {
        return `<div style="padding:14px;text-align:center;color:var(--text-muted);">
            No contributions tracked for <strong>${meta.label}</strong> yet.
            Build upgrades, infrastructure, complete research, or pick ARIA bond bonuses to start stacking this.
        </div>`;
    }

    // Group rows by layer
    const byLayer = {};
    rows.forEach(r => { (byLayer[r.layer] = byLayer[r.layer] || []).push(r); });

    let body = `<div class="mm-card-accent" style="text-align:center;">
        <div class="mm-section-label">${meta.label}</div>
        <div style="font-size:18px;font-weight:700;color:var(--text-primary);">${formatFinal(finalVal, meta.op)}</div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">Live aggregate from ${rows.length} contribution${rows.length === 1 ? '' : 's'}</div>
    </div>`;

    const stacksBlurb = techOnly
        ? 'Tech Tree only — each tech counts once at its <strong>highest level</strong>; distinct techs in a branch <strong>add</strong> their bonuses, then branches <strong>× multiply</strong>. Other sources (upgrades, infrastructure, ARIA bonds) are excluded here. See the Expeditions page for your full stacked rate.'
        : mergeBlurb(meta.op);
    body += `<div style="font-size:11px;color:var(--text-muted);margin:10px 2px 8px;line-height:1.55;">
        <strong style="color:var(--text-primary);">How this stacks:</strong> ${stacksBlurb}
    </div>`;

    body += `<div class="grid" style="grid-template-columns:1fr;gap:8px;">`;
    for (const layer of LAYER_ORDER) {
        const lst = byLayer[layer];
        if (!lst || !lst.length) continue;
        body += `<div style="border-left:3px solid var(--color-sepolia);padding:8px 12px;background:rgba(0,0,0,0.25);border-radius:0 6px 6px 0;">
            <div style="font-weight:600;font-size:12px;color:var(--color-sepolia);margin-bottom:6px;">${LAYER_LABEL[layer] || layer}</div>`;
        for (const r of lst) {
            body += `<div style="display:flex;justify-content:space-between;font-size:12px;padding:3px 0;border-top:1px solid rgba(255,255,255,0.04);">
                <span style="opacity:.9;">${r.source}</span>
                <span style="font-weight:600;color:var(--text-primary);">${formatContribution(r.value, meta.op)}</span>
            </div>`;
        }
        body += `</div>`;
    }
    body += `</div>`;

    body += `<div style="font-size:10.5px;color:var(--text-muted);margin-top:10px;line-height:1.55;opacity:.85;">
        Source of truth: <code>utilities/upgrades/effects.py</code> (aggregator) and
        <code>utilities/upgrades/breakdown.py</code> (this view).
    </div>`;

    return body;
}

window.openBonusBreakdown = function(ev, anchor) {
    if (ev) { ev.preventDefault(); ev.stopPropagation(); }
    const key = anchor && anchor.getAttribute('data-bonus-key');
    const highlight = anchor && anchor.getAttribute('data-bonus-highlight');
    // Bug #1482: Lab/Research chips set data-bonus-source="tech" so the modal shows
    // ONLY tech contributions + a tech-only final that matches the chip.
    const source = (anchor && anchor.getAttribute('data-bonus-source')) || 'all';
    if (!key) {
        // Legacy chip with no key — fall back to old jump-to-Colony behavior
        const url = '/colony?tab=assets' + (highlight ? `&highlight=${encodeURIComponent(highlight)}` : '');
        window.location.href = url;
        return false;
    }
    if (typeof MarsModal === 'undefined') return false;

    // Show a loading shell first, then swap in real content
    MarsModal.show({
        title: 'Bonus Breakdown',
        subtitle: '<span style="color:var(--text-muted)">Loading…</span>',
        icon: icon('microscope_lab'),
        width: 'md',
        body: `<div style="padding:30px;text-align:center;color:var(--text-muted);">Loading per-source contributions…</div>`,
        footer: `<button class="btn btn-primary mm-btn-full" onclick="MarsModal.hide()">Got it</button>`,
    });

    loadBonusBreakdown(source).then(data => {
        if (!data) {
            MarsModal.show({
                title: 'Bonus Breakdown',
                icon: icon('warning_alert'),
                width: 'md',
                body: `<div style="padding:20px;color:var(--text-muted);">Could not load breakdown right now. Try again in a moment.</div>`,
                footer: `<button class="btn btn-primary mm-btn-full" onclick="MarsModal.hide()">Got it</button>`,
            });
            return;
        }
        const meta = (data.meta || {})[key] || { label: key };
        const colonyUrl = '/colony?tab=assets' + (highlight ? `&highlight=${encodeURIComponent(highlight)}` : '');
        MarsModal.show({
            title: meta.label || 'Bonus Breakdown',
            subtitle: `<span style="color:var(--text-muted)">Where this number comes from</span>`,
            icon: icon('microscope_lab'),
            width: 'md',
            body: renderBreakdownBody(key, data, source),
            footer: `<div style="display:flex;gap:8px;width:100%;">
                <a href="${colonyUrl}" class="btn btn-secondary" style="flex:1;text-align:center;text-decoration:none;">View in Colony</a>
                <button class="btn btn-primary" onclick="MarsModal.hide()" style="flex:1;">Got it</button>
            </div>`,
        });
    });

    return false;
};
