// Admin / kumori ARIA journal test bench — bug #1457.
//
// Picks a captain → POST /api/admin/kumori-journal/generate → previews the
// rendered image + LLM-synthesized prompt + caption → optional save to the
// real /aria-album via POST /api/admin/kumori-journal/save.

(function () {
  const $ = (id) => document.getElementById(id);
  let last = null;  // last generate response, so the Save button can commit it

  async function loadCaptains() {
    const r = await fetch('/api/admin/kumori-journal/captains');
    const j = await r.json();
    if (!j.success) {
      $('kj-status').textContent = j.error || 'failed to load captains';
      return;
    }
    const sel = $('kj-captain');
    sel.innerHTML = '';
    for (const c of j.captains) {
      const opt = document.createElement('option');
      opt.value = c.id;
      opt.textContent = `[${c.id}] ${c.captain_name || '(no name)'} — ${c.email}`;
      sel.appendChild(opt);
    }
  }

  async function generate() {
    const uid = parseInt($('kj-captain').value || '0', 10);
    const force_min_n = parseInt($('kj-force-n').value || '0', 10);
    if (!uid) { $('kj-status').textContent = 'pick a captain'; return; }
    $('kj-status').textContent = 'Generating… (LLM synth + Klein render, ~8–12s)';
    $('kj-status').style.color = 'var(--text-secondary)';
    $('kj-generate').disabled = true;
    $('kj-save').disabled = true;
    last = null;
    const t0 = Date.now();
    let j;
    try {
      const r = await fetch('/api/admin/kumori-journal/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: uid, force_min_n })
      });
      j = await r.json();
    } catch (e) {
      $('kj-status').textContent = 'network error: ' + e;
      $('kj-status').style.color = 'var(--color-danger)';
      $('kj-generate').disabled = false;
      return;
    } finally {
      $('kj-generate').disabled = false;
    }
    const dt = Date.now() - t0;
    if (!j.success) {
      $('kj-status').textContent = `❌ ${j.error || 'failed'}`;
      $('kj-status').style.color = 'var(--color-danger)';
      return;
    }
    last = { ...j, user_id: uid };
    $('kj-status').textContent = `✅ generated in ${dt}ms · server render ${j.render_ms}ms`;
    $('kj-status').style.color = 'var(--color-success)';
    $('kj-img').src = 'data:image/png;base64,' + j.image_b64;
    $('kj-caption').textContent = j.aria_caption;
    $('kj-pick').textContent = JSON.stringify({
      sol: j.sol, N: j.N, mood: j.mood, composition: j.composition,
      chosen: j.chosen,
      pool_by_category: j.pool_by_category,
      pool_size_total: j.pool_size_total,
      used_size: j.used_size,
    }, null, 2);
    $('kj-prompt').textContent = j.image_prompt;
    $('kj-debug').textContent = JSON.stringify({
      llm_backend: j.llm_backend,
      llm_attempts: j.llm_attempts,
      render_provider: j.render_provider,
      render_ms: j.render_ms,
      render_total_ms: j.render_total_ms,
    }, null, 2);
    $('kj-result').style.display = 'grid';
    $('kj-save').disabled = false;
  }

  async function saveToAlbum() {
    if (!last) return;
    $('kj-status').textContent = 'Saving to ARIA Album…';
    $('kj-save').disabled = true;
    let j;
    try {
      const r = await fetch('/api/admin/kumori-journal/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: last.user_id,
          image_b64: last.image_b64,
          aria_caption: last.aria_caption,
          image_prompt: last.image_prompt,
          mood: last.mood,
          composition: last.composition,
          N: last.N,
          sol: last.sol,
          chosen: last.chosen,
        })
      });
      j = await r.json();
    } catch (e) {
      $('kj-status').textContent = 'save failed: ' + e;
      $('kj-status').style.color = 'var(--color-danger)';
      $('kj-save').disabled = false;
      return;
    }
    if (j.success) {
      $('kj-status').innerHTML = `✅ saved snapshot #${j.snapshot_id} · <a href="${j.gcs_url}" target="_blank">view image</a> · <a href="/aria-album" target="_blank">open ARIA Album</a>`;
      $('kj-status').style.color = 'var(--color-success)';
    } else {
      $('kj-status').textContent = `❌ save failed: ${j.error || 'unknown'}`;
      $('kj-status').style.color = 'var(--color-danger)';
      $('kj-save').disabled = false;
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    loadCaptains();
    $('kj-generate').addEventListener('click', generate);
    $('kj-save').addEventListener('click', saveToAlbum);
  });
})();
