// Admin / kumori ARIA journal DEBUG CONSOLE — bug #1457.
// Surfaces every prompt, endpoint, attempt, response. Designed for validation
// before nano_banana_pro cutover.

(function () {
  const $ = (id) => document.getElementById(id);
  let last = null;

  async function loadUsage() {
    const bars = $('kj-usage-bars');
    bars.innerHTML = '<div class="kj-mini">loading…</div>';
    try {
      const r = await fetch('/api/admin/kumori-journal/usage');
      const j = await r.json();
      if (!j.success) { bars.textContent = j.error || 'failed'; return; }
      const caps = j.caps || {};
      // Only show the REAL upstream limit (PILGRIMS_KUMORI_API_KEY 20K/day).
      // The other two ("Klein 4B 30/day", "Cloudflare neurons 10K shared pool")
      // were self-imposed soft caps — dropped per Andy 2026-05-11: pilgrims
      // gets full reign; anything beyond simply fails upstream and that's fine.
      const order = ['pilgrims_api_key_calls'];
      const labels = {
        pilgrims_api_key_calls: 'Pilgrims API key calls',
      };
      bars.innerHTML = '';
      for (const k of order) {
        const c = caps[k];
        if (!c) continue;
        const pct = Math.min(100, Math.round((c.used / c.limit) * 100));
        const color = pct >= 90 ? 'var(--color-danger)' : pct >= 60 ? 'var(--color-warning)' : 'var(--color-success)';
        const row = document.createElement('div');
        row.className = 'kj-cap-row';
        row.innerHTML = `
          <div class="kj-cap-head">
            <span class="kj-cap-name">${labels[k]}</span>
            <span class="kj-cap-val">${c.used.toLocaleString()} / ${c.limit.toLocaleString()} (${pct}%)</span>
          </div>
          <div class="kj-cap-bar"><div class="kj-cap-fill" style="width:${pct}%; background:${color};"></div></div>
          <div class="kj-mini">${c.note}</div>`;
        bars.appendChild(row);
      }
      $('kj-usage-rows').textContent = JSON.stringify(j.today_rows, null, 2);
    } catch (e) {
      bars.textContent = 'error: ' + e;
    }
  }

  async function loadCaptains() {
    const r = await fetch('/api/admin/kumori-journal/captains');
    const j = await r.json();
    if (!j.success) { $('kj-status').textContent = j.error || 'failed'; return; }
    const sel = $('kj-captain');
    sel.innerHTML = '';
    for (const c of j.captains) {
      const opt = document.createElement('option');
      opt.value = c.id;
      opt.textContent = `[${c.id}] ${c.captain_name || '(no name)'} — ${c.email}`;
      sel.appendChild(opt);
    }
  }

  function fmt(obj) { return JSON.stringify(obj, null, 2); }

  function renderHttpCalls(containerEl, calls, emptyMsg) {
    containerEl.innerHTML = '';
    if (!calls || !calls.length) {
      containerEl.innerHTML = `<div class="kj-mini">${emptyMsg || '(no calls)'}</div>`;
      return;
    }
    calls.forEach((c, i) => {
      const status = c.response_status ?? c.status ?? '?';
      const statusClass = (typeof status === 'number' && status < 400) ? 'kj-status-ok'
                        : (typeof status === 'number') ? 'kj-status-err' : 'kj-status-unk';
      const errBadge = c.error ? `<span class="kj-http-err">${c.error}</span>` : '';
      const card = document.createElement('details');
      card.className = 'kj-http-call';
      card.open = false;
      // Friendly summary in the <summary> tag
      const urlShort = (c.url || '').replace(/^https?:\/\//, '').slice(0, 80);
      card.innerHTML = `
        <summary>
          <span class="kj-http-idx">#${i+1}</span>
          <span class="kj-http-method">${c.method || '?'}</span>
          <span class="kj-http-url">${urlShort}</span>
          <span class="kj-http-status ${statusClass}">${status}</span>
          <span class="kj-http-ms">${c.ms ?? '?'}ms</span>
          ${errBadge}
        </summary>
        <div class="kj-http-body">
          <div class="kj-key">URL (full):</div>
          <div class="kj-val"><code>${c.url || ''}</code></div>
          <div class="kj-key">Request headers:</div>
          <pre>${fmt(c.request_headers || c.headers || {})}</pre>
          <div class="kj-key">Request body:</div>
          <pre>${fmt(c.request_body !== undefined ? c.request_body : (c.request || {}))}</pre>
          <div class="kj-key">Response status:</div>
          <div class="kj-val"><code>${status}</code> · ${c.response_size_bytes ? c.response_size_bytes + ' bytes' : ''}</div>
          <div class="kj-key">Response headers:</div>
          <pre>${fmt(c.response_headers || {})}</pre>
          <div class="kj-key">Response body:</div>
          <pre>${fmt(c.response_body !== undefined ? c.response_body : (c.response || {}))}</pre>
        </div>`;
      containerEl.appendChild(card);
    });
  }

  function renderPipelineBars(containerEl, stages) {
    containerEl.innerHTML = '';
    if (!stages || !stages.length) {
      containerEl.innerHTML = '<div class="kj-mini">(no stage log)</div>';
      return;
    }
    // Find max ms so we can scale bar widths
    const maxMs = Math.max(1, ...stages.map(s => Number(s.ms) || 0));
    const totalMs = stages.reduce((acc, s) => acc + (Number(s.ms) || 0), 0);
    const header = document.createElement('div');
    header.className = 'kj-mini';
    header.style.marginBottom = '6px';
    header.textContent = `Total wall-clock across all stages: ${totalMs}ms`;
    containerEl.appendChild(header);
    stages.forEach((s) => {
      const ms = Number(s.ms) || 0;
      const pct = Math.max(2, Math.round((ms / maxMs) * 100));
      const color = ms >= maxMs * 0.7 ? 'var(--color-danger)'
                  : ms >= maxMs * 0.4 ? 'var(--color-warning)'
                  : 'var(--color-success)';
      const meta = [];
      if (s.backend) meta.push(`backend=${s.backend}`);
      if (s.provider) meta.push(`provider=${s.provider}`);
      if (s.chars != null) meta.push(`${s.chars} chars`);
      if (s.output_bytes != null) meta.push(`${s.output_bytes} bytes`);
      if (s.used_size) meta.push(`${s.used_size[0]}×${s.used_size[1]}`);
      const row = document.createElement('div');
      row.className = 'kj-pipe-row';
      row.innerHTML = `
        <div class="kj-pipe-head">
          <span class="kj-pipe-stage">${s.stage || '?'}</span>
          <span class="kj-pipe-ms">${ms}ms</span>
        </div>
        <div class="kj-pipe-bar"><div class="kj-pipe-fill" style="width:${pct}%; background:${color};"></div></div>
        <div class="kj-mini">${meta.join(' · ') || ''}</div>`;
      containerEl.appendChild(row);
    });
  }

  function renderRefs(refs) {
    const grid = $('kj-chosen-refs');
    grid.innerHTML = '';
    if (!refs || !refs.length) {
      grid.innerHTML = '<div class="kj-mini">N=0 → no refs (pure landscape; Klein anchored on ARIA static portrait as safety target)</div>';
      return;
    }
    refs.forEach((c, i) => {
      const role = (i === 0) ? 'TARGET' : `REF ${i}`;
      const card = document.createElement('div');
      card.className = 'kj-ref-card';
      card.innerHTML = `
        <div class="kj-ref-head">
          <span class="kj-ref-tag">image ${i+1}</span>
          <span class="kj-ref-role">${role}</span>
        </div>
        <img src="${c.url}" alt="${c.category}" class="kj-ref-img">
        <div class="kj-ref-body">
          <div><strong>CATEGORY:</strong> ${c.category}</div>
          <div><strong>KIND:</strong> ${c.kind_tag || '?'}</div>
          <div class="kj-ref-role-text">${c.role_label}</div>
          <div class="kj-mini">${c.facts || ''}</div>
        </div>`;
      grid.appendChild(card);
    });
  }

  async function generate() {
    const uid = parseInt($('kj-captain').value || '0', 10);
    const force_min_n = parseInt($('kj-force-n').value || '0', 10);
    const preset = $('kj-preset').value || 'aria_journal';
    if (!uid) { $('kj-status').textContent = 'pick a captain'; return; }
    const body = { user_id: uid, force_min_n, preset };
    if (preset === '__custom__') {
      body.width = parseInt($('kj-custom-w').value || '1024', 10);
      body.height = parseInt($('kj-custom-h').value || '1024', 10);
    }
    $('kj-status').textContent = 'Generating… (build pool → roll → 1 LLM call → 1 Klein call, ~8–12s)';
    $('kj-status').style.color = 'var(--text-secondary)';
    $('kj-generate').disabled = true;
    $('kj-save').disabled = true;
    last = null;
    // Same processing overlay we use for page transitions — fast millisecond
    // timer so the user sees something live while the ~8-12s pipeline runs.
    if (typeof showProcessing === 'function') showProcessing('Generating ARIA journal entry…');
    const t0 = Date.now();
    let j;
    try {
      const r = await fetch('/api/admin/kumori-journal/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      j = await r.json();
    } catch (e) {
      $('kj-status').textContent = 'network error: ' + e;
      $('kj-status').style.color = 'var(--color-danger)';
      $('kj-generate').disabled = false;
      if (typeof hideProcessing === 'function') hideProcessing();
      return;
    } finally {
      $('kj-generate').disabled = false;
      if (typeof hideProcessing === 'function') hideProcessing();
    }
    const dt = Date.now() - t0;
    if (!j.success) {
      $('kj-status').textContent = `❌ ${j.error || 'failed'}`;
      $('kj-status').style.color = 'var(--color-danger)';
      return;
    }
    last = { ...j, user_id: uid };
    $('kj-status').textContent = `✅ pipeline OK · client wall-clock ${dt}ms · server klein ${j.render_ms}ms`;
    $('kj-status').style.color = 'var(--color-success)';

    // Rendered image + caption (use FINAL caption — the one that reconciled
    // picks against what Klein actually rendered)
    $('kj-img').src = 'data:image/png;base64,' + j.image_b64;
    $('kj-caption').textContent = j.final_aria_caption || j.aria_caption || '';
    $('kj-used-size').textContent = `output size: ${j.used_size?.[0]}×${j.used_size?.[1]} · sol ${j.sol} · N=${j.N} · mood=${j.mood} · composition="${j.composition}"`;

    // Pinned always-visible prompt + LLM input — duplicated from the trace
    // panel so you can scan dozens of combos without expanding collapsibles.
    $('kj-image-prompt-pinned').textContent = j.image_prompt || '';
    $('kj-llm-user-pinned').textContent = j.llm_user_payload || '';

    // Stage 1 — pool
    $('kj-pool').textContent = fmt({
      pool_size_total: j.pool_size_total,
      pool_by_category: j.pool_by_category,
    });

    // Stage 2 — pick
    $('kj-pick').textContent = fmt({
      N: j.N,
      mood: j.mood,
      composition: j.composition,
    });
    renderRefs(j.chosen);

    // Stage 3 — LLM synth
    $('kj-llm-endpoint').textContent = j.llm_endpoint;
    $('kj-llm-backend').textContent = j.llm_backend_used;
    $('kj-llm-system').textContent = j.llm_system_prompt || '(none)';
    $('kj-llm-user').textContent = j.llm_user_payload || '(none)';
    $('kj-llm-attempts').textContent = fmt(j.llm_attempts || []);
    $('kj-image-prompt').textContent = j.image_prompt || '';
    $('kj-caption-raw').textContent = j.aria_caption || '';
    $('kj-postproc').textContent = (j.post_process_notes || []).join(', ') || '(none)';

    // Stage 4 — Klein
    $('kj-klein-endpoint').textContent = j.klein_endpoint;
    $('kj-klein-payload').textContent = fmt({
      target_image_url: j.klein_target_image_url,
      reference_image_urls: j.klein_reference_image_urls,
      target_count: j.klein_target_count,
      ref_count: j.klein_ref_count,
      requested_width: j.used_size?.[0],
      requested_height: j.used_size?.[1],
    });
    $('kj-render-meta').textContent = fmt({
      provider: j.render_provider,
      server_ms: j.render_ms,
      total_pipeline_ms: j.render_total_ms,
    });

    // Stage 5 — Vision LLM describes the rendered image
    $('kj-verify-vision-endpoint').textContent = 'POST /api/v1/describe/describe';
    $('kj-verify-vision-backend').textContent = j.verification_vision_backend || '?';
    $('kj-verify-vision-ms').textContent = (j.verification_vision_ms ?? '?') + 'ms';
    $('kj-verify-vision-prompt').textContent = j.verification_vision_prompt || '(none)';
    $('kj-verify-vision-description').textContent = j.verification_vision_description || '(vision describe returned empty / failed)';

    // Stage 6 — Final caption LLM rewrite
    $('kj-verify-caption-endpoint').textContent = j.verification_caption_endpoint || 'POST /api/v1/llm/chat-resilient';
    $('kj-verify-caption-backend').textContent = j.verification_caption_llm_backend || '?';
    $('kj-verify-caption-ms').textContent = (j.verification_caption_ms ?? '?') + 'ms';
    $('kj-verify-caption-system').textContent = j.verification_caption_system_prompt || '(none)';
    $('kj-verify-caption-user').textContent = j.verification_caption_user_prompt || '(none)';
    $('kj-verify-caption-attempts').textContent = fmt(j.verification_caption_llm_attempts || []);
    $('kj-verify-caption-raw').textContent = j.verification_caption_raw || '(empty)';
    $('kj-verify-final-caption').textContent = j.final_aria_caption || '(none)';

    // Stage 7 — pipeline stage log with per-stage millisecond bars so the
    // slowest step is visually obvious.
    renderPipelineBars($('kj-pipeline-bars'), j.pipeline_stage_log || []);
    $('kj-pipeline-log').textContent = fmt(j.pipeline_stage_log || []);

    // Stage 8 — galactica → kumori HTTP (now includes 3 calls: synth LLM,
    // Klein edit, vision describe, final-caption LLM)
    renderHttpCalls($('kj-http-galactica'), j.galactica_to_kumori_http || [],
                    'No HTTP calls recorded — debug instrumentation may not be wired (check kumori_api_client.set_request_log).');

    // Stage 9 — kumori → LLM upstream (synthesis + final-caption rewrite)
    $('kj-llm-raw-response').textContent = j.llm_raw_response_text || '(not captured)';
    const llmUpstream = (j.llm_debug_info && j.llm_debug_info.upstream_calls) || [];
    renderHttpCalls($('kj-http-llm-upstream'), llmUpstream,
                    'No upstream synthesis LLM calls captured — kumori service may not have shipped the upstream_trace patch yet, or this LLM call hit a server-side cache.');
    const verifyCaptionUpstream = (j.verification_caption_llm_debug && j.verification_caption_llm_debug.upstream_calls) || [];
    renderHttpCalls($('kj-http-verify-caption-upstream'), verifyCaptionUpstream,
                    'No upstream final-caption LLM calls captured.');

    // Stage 10 — kumori → cloudflare (klein) upstream
    const kleinUpstream = (j.klein_debug_info && j.klein_debug_info.upstream_calls) || [];
    renderHttpCalls($('kj-http-klein-upstream'), kleinUpstream,
                    'No upstream Klein calls captured — kumori service may not have shipped the upstream_trace patch yet.');

    // Stage 11 — raw dump (with image_b64 redacted)
    const rawCopy = { ...j };
    rawCopy.image_b64 = `<${j.image_b64?.length || 0} chars base64 — omitted from raw view>`;
    $('kj-raw').textContent = fmt(rawCopy);

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
          aria_caption: last.final_aria_caption || last.aria_caption,
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
    loadUsage();
    $('kj-generate').addEventListener('click', async () => {
      await generate();
      loadUsage();  // refresh usage bars after each gen so we see the increment
    });
    $('kj-save').addEventListener('click', saveToAlbum);
    $('kj-usage-refresh').addEventListener('click', loadUsage);
    $('kj-preset').addEventListener('change', (e) => {
      $('kj-custom-size-row').style.display = (e.target.value === '__custom__') ? 'flex' : 'none';
    });
    $('kj-copy-prompt').addEventListener('click', () => {
      const txt = $('kj-image-prompt-pinned').textContent;
      navigator.clipboard.writeText(txt).then(() => {
        $('kj-copy-prompt').textContent = '✓ copied';
        setTimeout(() => $('kj-copy-prompt').textContent = '📋 copy', 1500);
      });
    });
  });
})();
