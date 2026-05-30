/* Collection Codex (Bug #1160) — Discoveries-tab sub-view toggle + fire-once
   milestone reveal. The codex grid is server-rendered (Jinja from discovery_codex);
   this file only handles the To-Claim/Collection toggle and the one-time
   category/full-codex completion celebration. */

function switchDiscoveryView(view) {
    document.querySelectorAll('.discovery-view-toggle .dv-btn').forEach(function (b) {
        b.classList.toggle('active', b.dataset.view === view);
    });
    var finds = document.getElementById('dv-finds');
    var codex = document.getElementById('dv-codex');
    if (finds) finds.style.display = (view === 'finds') ? '' : 'none';
    if (codex) codex.style.display = (view === 'codex') ? '' : 'none';
}
window.switchDiscoveryView = switchDiscoveryView;

(function () {
    // localStorage flag is ONLY "have I shown the animation" — the DB codex_milestones
    // table is the source of truth for what's awarded, so losing this flag merely
    // re-shows a cinematic, never re-grants SV. Survives reloads (claim runs a
    // background tx + the page may reload mid-flight). Mirrors research.html's pattern.
    var SEEN_KEY = 'pilgrims_codex_seen_v1';

    function getSeen() {
        try { return new Set(JSON.parse(localStorage.getItem(SEEN_KEY) || '[]')); }
        catch (e) { return new Set(); }
    }
    function markSeen(set) {
        try { localStorage.setItem(SEEN_KEY, JSON.stringify(Array.from(set))); } catch (e) {}
    }

    function revealCategory(m) {
        if (typeof MarsModal === 'undefined') return;
        MarsModal.show({
            title: m.name,
            subtitle: 'Codex Category Complete',
            icon: '🏆',
            theme: 'success',
            badge: 'CATEGORY COMPLETE',
            width: 'md',
            dismissOnBackdrop: false,
            dismissOnEscape: false,
            body: '<div class="mm-aria" style="text-align:center; font-size:15px;">You\'ve collected every specimen in this category, Captain.</div>'
                + '<div class="mm-card" style="text-align:center;"><strong style="color:var(--color-sepolia);">+' + m.sv + ' SV</strong> awarded</div>',
            footer: '<button class="btn btn-primary mm-btn-full" onclick="MarsModal.hide()">Continue</button>'
        });
    }

    function revealTotal(m) {
        if (typeof EpicReveal !== 'undefined') {
            EpicReveal.show({
                title: m.name,
                lines: [
                    { text: 'Every specimen. Every category. The complete record of Mars.', cls: 'aria' },
                    { text: 'No captain before you has held it all at once.', cls: 'aria' }
                ],
                revelation: { label: 'CODEX COMPLETE', text: m.name + ' — +' + m.sv + ' SV' },
                actions: [
                    { label: 'View Codex', href: '/colony?tab=discoveries&view=codex' },
                    { label: 'Continue', cls: 'secondary' }
                ]
            });
        } else {
            revealCategory(m); // graceful fallback if the cinematic engine isn't loaded
        }
    }

    // Deep-link: /colony?tab=discoveries&view=codex (or #codex) opens the Collection view.
    function maybeOpenCodexFromUrl() {
        try {
            var p = new URLSearchParams(window.location.search);
            if (p.get('view') === 'codex' || window.location.hash === '#codex') {
                switchDiscoveryView('codex');
            }
        } catch (e) {}
    }

    document.addEventListener('DOMContentLoaded', function () {
        maybeOpenCodexFromUrl();
        var data;
        try { data = JSON.parse(document.getElementById('colonyPageData').textContent); }
        catch (e) { return; }
        var earned = (data && data.codexEarned) || [];
        if (!earned.length) return;

        var seen = getSeen();
        var fresh = earned.filter(function (m) { return !seen.has(m.key); });
        if (!fresh.length) return;

        // Show ONE reveal per load (prioritize the once-ever full-codex moment) so a
        // rare multi-complete can't stack modals; the grid shows the rest. DB already
        // awarded the SV — this is purely the animation gate.
        var headline = fresh.find(function (m) { return m.key === 'total_all'; }) || fresh[0];
        setTimeout(function () {
            if (headline.key === 'total_all') revealTotal(headline);
            else revealCategory(headline);
            // Mark seen ONLY after the reveal actually fires — if the captain navigates
            // away within this window the milestone stays unseen and re-fires next visit
            // (SV is unaffected; the DB already granted it).
            fresh.forEach(function (m) { seen.add(m.key); });
            markSeen(seen);
        }, 900);
    });
})();
