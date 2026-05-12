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
      // Show all three counters for visibility. Pilgrims has full reign —
      // we NEVER block the user. The Klein/Cloudflare numbers are upstream
      // soft caps shown for awareness; if we exceed them the upstream just
      // returns an error and we move on. Per Andy 2026-05-11.
      const order = ['pilgrims_api_key_calls', 'klein_4b_calls', 'cloudflare_neurons_shared_pool'];
      const labels = {
        pilgrims_api_key_calls: 'Pilgrims API key calls (real quota — 20K/day)',
        klein_4b_calls: 'Klein 4B edits today (upstream soft cap — informational)',
        cloudflare_neurons_shared_pool: 'Cloudflare neurons today (shared pool — informational)',
      };
      const informational = new Set(['klein_4b_calls', 'cloudflare_neurons_shared_pool']);
      bars.innerHTML = '';
      for (const k of order) {
        const c = caps[k];
        if (!c) continue;
        const isInfo = informational.has(k);
        const pct = Math.min(100, Math.round((c.used / c.limit) * 100));
        // Informational bars never go red/yellow — pilgrims doesn't enforce these.
        const color = isInfo ? 'var(--text-secondary)'
                     : pct >= 90 ? 'var(--color-danger)'
                     : pct >= 60 ? 'var(--color-warning)'
                     : 'var(--color-success)';
        const tag = isInfo ? ' <span class="kj-mini" style="opacity:0.7;">(not enforced)</span>' : '';
        // Per-consumer-app breakdown — which sibling project (galactica,
        // kindness_social, heathers_plate, etc.) contributed to this number.
        let perAppHtml = '';
        if (c.per_app && c.per_app.length) {
          const unit = k === 'cloudflare_neurons_shared_pool' ? ' neurons' : '';
          perAppHtml = '<div class="kj-cap-per-app">'
            + c.per_app.map(a => `<span class="kj-cap-chip"><strong>${a.app}</strong>: ${a.used.toLocaleString()}${unit}</span>`).join('')
            + '</div>';
        } else {
          perAppHtml = '<div class="kj-cap-per-app"><span class="kj-mini" style="opacity:0.6;">no calls today</span></div>';
        }
        const row = document.createElement('div');
        row.className = 'kj-cap-row';
        row.innerHTML = `
          <div class="kj-cap-head">
            <span class="kj-cap-name">${labels[k]}${tag}</span>
            <span class="kj-cap-val">${c.used.toLocaleString()} / ${c.limit.toLocaleString()} (${pct}%)</span>
          </div>
          <div class="kj-cap-bar"><div class="kj-cap-fill" style="width:${pct}%; background:${color};"></div></div>
          <div class="kj-mini">${c.note}</div>
          ${perAppHtml}`;
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

  // SSE reader for fetch+POST. Yields {event, data} objects as they arrive.
  async function* readSSE(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split('\n\n');
      buffer = chunks.pop();  // keep trailing partial event
      for (const chunk of chunks) {
        if (!chunk.trim()) continue;
        let event = 'message', dataLines = [];
        for (const line of chunk.split('\n')) {
          if (line.startsWith('event:')) event = line.slice(6).trim();
          else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
        }
        if (dataLines.length) {
          try { yield { event, data: JSON.parse(dataLines.join('\n')) }; }
          catch (e) { console.error('bad SSE chunk', e, chunk); }
        }
      }
    }
  }

  let btnTimerInterval = null;
  function startBtnTimer(btn) {
    const t0 = Date.now();
    const baseLabel = btn.dataset.baseLabel || btn.textContent;
    btn.dataset.baseLabel = baseLabel;
    if (btnTimerInterval) clearInterval(btnTimerInterval);
    btnTimerInterval = setInterval(() => {
      const ms = Date.now() - t0;
      btn.textContent = `⏱ ${(ms/1000).toFixed(1)}s — generating…`;
    }, 100);
  }
  function stopBtnTimer(btn, finalText) {
    if (btnTimerInterval) { clearInterval(btnTimerInterval); btnTimerInterval = null; }
    btn.textContent = finalText || btn.dataset.baseLabel || '▶ Generate (trace every step)';
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
    $('kj-status').textContent = 'Generating… results stream in stage by stage';
    $('kj-status').style.color = 'var(--text-secondary)';
    $('kj-generate').disabled = true;
    $('kj-save').disabled = true;
    last = { user_id: uid };
    startBtnTimer($('kj-generate'));

    // Show the result grid immediately and clear all per-stage panels so the
    // user can SCROLL and watch each one fill in as events arrive.
    $('kj-result').style.display = 'grid';
    $('kj-img').removeAttribute('src');
    $('kj-caption').textContent = '(waiting for first-pass caption…)';
    $('kj-used-size').textContent = '';
    $('kj-image-prompt-pinned').textContent = '(waiting for LLM synth…)';
    $('kj-llm-user-pinned').textContent = '(waiting for LLM synth…)';
    ['kj-pool','kj-pick','kj-llm-endpoint','kj-llm-backend','kj-llm-system','kj-llm-user',
     'kj-llm-attempts','kj-image-prompt','kj-caption-raw','kj-postproc','kj-klein-endpoint',
     'kj-klein-payload','kj-render-meta','kj-verify-vision-endpoint','kj-verify-vision-backend',
     'kj-verify-vision-ms','kj-verify-vision-prompt','kj-verify-vision-description',
     'kj-verify-caption-endpoint','kj-verify-caption-backend','kj-verify-caption-ms',
     'kj-verify-caption-system','kj-verify-caption-user','kj-verify-caption-attempts',
     'kj-verify-caption-raw','kj-verify-final-caption','kj-pipeline-log','kj-llm-raw-response',
     'kj-raw'].forEach(id => { const el = $(id); if (el) el.textContent = '…'; });
    $('kj-chosen-refs').innerHTML = '<div class="kj-mini">…</div>';
    $('kj-pipeline-bars').innerHTML = '<div class="kj-mini">streaming…</div>';
    $('kj-http-galactica').innerHTML = '<div class="kj-mini">…</div>';
    $('kj-http-llm-upstream').innerHTML = '<div class="kj-mini">…</div>';
    $('kj-http-verify-caption-upstream').innerHTML = '<div class="kj-mini">…</div>';
    $('kj-http-klein-upstream').innerHTML = '<div class="kj-mini">…</div>';

    // Live pipeline bars — append a row per stage as the event arrives so
    // the user can see in real time which step is slow.
    const liveStages = [];
    function pushLiveStage(stage, ms, meta) {
      liveStages.push({ stage, ms, ...meta });
      renderPipelineBars($('kj-pipeline-bars'), liveStages);
    }

    const t0 = Date.now();
    let response;
    try {
      response = await fetch('/api/admin/kumori-journal/generate-stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
    } catch (e) {
      $('kj-status').textContent = 'network error: ' + e;
      $('kj-status').style.color = 'var(--color-danger)';
      $('kj-generate').disabled = false;
      stopBtnTimer($('kj-generate'));
      return;
    }
    if (!response.ok) {
      $('kj-status').textContent = `❌ HTTP ${response.status}`;
      $('kj-status').style.color = 'var(--color-danger)';
      $('kj-generate').disabled = false;
      stopBtnTimer($('kj-generate'));
      return;
    }

    let gotError = null;
    try {
      for await (const { event, data } of readSSE(response)) {
        switch (event) {
          case 'start': {
            $('kj-status').textContent = '⏱ pipeline started…';
            break;
          }
          case 'pool': {
            $('kj-pool').textContent = fmt({
              pool_size_total: data.pool_size_total,
              pool_by_category: data.pool_by_category,
            });
            pushLiveStage('pool_build', data.ms, { total: data.pool_size_total });
            $('kj-status').textContent = `⏱ pool built (${data.ms}ms)…`;
            break;
          }
          case 'pick': {
            $('kj-pick').textContent = fmt({ N: data.N, mood: data.mood, composition: data.composition });
            renderRefs(data.chosen);
            Object.assign(last, { N: data.N, mood: data.mood, composition: data.composition, chosen: data.chosen });
            pushLiveStage('random_pick', data.ms, { N: data.N });
            $('kj-status').textContent = `⏱ picked N=${data.N} refs (${data.ms}ms)…`;
            break;
          }
          case 'llm_synth': {
            $('kj-llm-endpoint').textContent = data.endpoint;
            $('kj-llm-backend').textContent = data.backend;
            $('kj-llm-system').textContent = data.system_prompt;
            $('kj-llm-user').textContent = data.user_payload;
            $('kj-llm-attempts').textContent = fmt(data.attempts || []);
            $('kj-image-prompt').textContent = data.image_prompt;
            $('kj-caption-raw').textContent = data.aria_caption;
            $('kj-image-prompt-pinned').textContent = data.image_prompt;
            $('kj-llm-user-pinned').textContent = data.user_payload;
            $('kj-caption').textContent = data.aria_caption + '  (first-pass — final coming…)';
            $('kj-llm-raw-response').textContent = data.raw_response || '(empty)';
            renderHttpCalls($('kj-http-llm-upstream'),
                            (data.llm_debug_info && data.llm_debug_info.upstream_calls) || [],
                            'No upstream calls captured.');
            Object.assign(last, {
              image_prompt: data.image_prompt,
              aria_caption: data.aria_caption,
              llm_user_payload: data.user_payload,
              llm_backend_used: data.backend,
            });
            pushLiveStage('llm_synth', data.ms, { backend: data.backend, chars: (data.raw_response||'').length });
            $('kj-status').textContent = `⏱ LLM synth done via ${data.backend} (${data.ms}ms) — rendering image…`;
            break;
          }
          case 'klein_render': {
            $('kj-img').src = 'data:image/png;base64,' + data.image_b64;
            $('kj-used-size').textContent = `output size: ${data.used_size?.[0]}×${data.used_size?.[1]} · provider=${data.provider}`;
            $('kj-klein-endpoint').textContent = data.endpoint;
            $('kj-klein-payload').textContent = fmt({
              target_image_url: data.target_image_url,
              reference_image_urls: data.reference_image_urls,
              requested_width: data.used_size?.[0],
              requested_height: data.used_size?.[1],
            });
            $('kj-render-meta').textContent = fmt({ provider: data.provider, server_ms: data.server_ms, total_pipeline_ms: data.total_ms });
            renderHttpCalls($('kj-http-klein-upstream'),
                            (data.klein_debug_info && data.klein_debug_info.upstream_calls) || [],
                            'No upstream Klein calls captured.');
            Object.assign(last, { image_b64: data.image_b64, used_size: data.used_size });
            pushLiveStage('klein_render', data.total_ms, { provider: data.provider, used_size: data.used_size });
            $('kj-status').textContent = `⏱ Klein render done (${data.total_ms}ms) — verifying…`;
            break;
          }
          case 'vision': {
            $('kj-verify-vision-endpoint').textContent = data.endpoint;
            $('kj-verify-vision-backend').textContent = data.backend;
            $('kj-verify-vision-ms').textContent = data.ms + 'ms';
            $('kj-verify-vision-prompt').textContent = data.prompt;
            $('kj-verify-vision-description').textContent = data.description || '(empty)';
            pushLiveStage('vision_describe_rendered', data.ms, { backend: data.backend, chars: (data.description||'').length });
            $('kj-status').textContent = `⏱ vision read done via ${data.backend} (${data.ms}ms) — final caption…`;
            break;
          }
          case 'final_caption': {
            $('kj-verify-caption-endpoint').textContent = data.endpoint;
            $('kj-verify-caption-backend').textContent = data.backend;
            $('kj-verify-caption-ms').textContent = data.ms + 'ms';
            $('kj-verify-caption-system').textContent = data.system_prompt;
            $('kj-verify-caption-user').textContent = data.user_prompt;
            $('kj-verify-caption-attempts').textContent = fmt(data.attempts || []);
            $('kj-verify-caption-raw').textContent = data.raw_response || '(empty)';
            $('kj-verify-final-caption').textContent = data.final_aria_caption || '(none)';
            $('kj-caption').textContent = data.final_aria_caption || last.aria_caption || '';
            renderHttpCalls($('kj-http-verify-caption-upstream'), data.upstream_calls || [],
                            'No upstream final-caption LLM calls captured.');
            Object.assign(last, { final_aria_caption: data.final_aria_caption });
            pushLiveStage('final_caption_rewrite', data.ms, { backend: data.backend, chars: (data.final_aria_caption||'').length });
            $('kj-status').textContent = `⏱ final caption done via ${data.backend} (${data.ms}ms) — wrapping up…`;
            break;
          }
          case 'done': {
            $('kj-pipeline-log').textContent = fmt(data.pipeline_stage_log || []);
            renderPipelineBars($('kj-pipeline-bars'), data.pipeline_stage_log || []);
            renderHttpCalls($('kj-http-galactica'), data.galactica_to_kumori_http || [],
                            'No HTTP calls recorded.');
            Object.assign(last, { sol: data.sol });
            const dt = Date.now() - t0;
            $('kj-status').textContent = `✅ pipeline OK · client wall-clock ${(dt/1000).toFixed(1)}s · server total ${(data.pipeline_total_ms/1000).toFixed(1)}s`;
            $('kj-status').style.color = 'var(--color-success)';
            // Raw dump with image_b64 redacted
            const rawCopy = { ...last };
            if (rawCopy.image_b64) rawCopy.image_b64 = `<${rawCopy.image_b64.length} chars base64 — omitted>`;
            $('kj-raw').textContent = fmt({ ...rawCopy, pipeline_total_ms: data.pipeline_total_ms,
                                              pipeline_stage_log: data.pipeline_stage_log });
            break;
          }
          case 'error': {
            gotError = data.error || 'unknown';
            break;
          }
        }
      }
    } catch (e) {
      gotError = 'stream read failed: ' + e;
    }

    stopBtnTimer($('kj-generate'));
    $('kj-generate').disabled = false;
    if (gotError) {
      $('kj-status').textContent = `❌ ${gotError}`;
      $('kj-status').style.color = 'var(--color-danger)';
    } else {
      $('kj-save').disabled = false;
    }
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
