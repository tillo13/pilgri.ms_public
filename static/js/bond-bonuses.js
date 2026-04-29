// Bug #1402 — Fragment Bond bonus picker.
// Reads catalog from #bondBonusCatalog JSON block, wires .bond-bonus-pick-btn buttons,
// shows MarsModal with 6 options A–F (used codes greyed), POSTs to
// /api/aria-bond/<bond_id>/choose_bonus, reloads on success.
(function () {
  const dataEl = document.getElementById('bondBonusCatalog');
  if (!dataEl) return;
  let payload;
  try { payload = JSON.parse(dataEl.textContent); } catch (e) { return; }
  const catalog = payload.catalog || {};
  const usedCodes = new Set(payload.used_codes || []);

  function renderPickerBody(bondId, landmark) {
    const codes = ['A', 'B', 'C', 'D', 'E', 'F'];
    const cards = codes.map(code => {
      const spec = catalog[code];
      if (!spec) return '';
      const used = usedCodes.has(code);
      const disabled = used ? 'disabled' : '';
      const opacity = used ? '0.4' : '1';
      const cursor = used ? 'not-allowed' : 'pointer';
      const usedTag = used ? '<span style="font-size:10px; color:#ef4444; margin-left:6px;">(already chosen)</span>' : '';
      return `
        <button type="button" data-code="${code}" ${disabled}
                class="bond-bonus-option"
                style="display:flex; align-items:flex-start; gap:10px; text-align:left; padding:10px 12px; background:rgba(168,85,247,0.08); border:1px solid rgba(168,85,247,0.3); border-radius:8px; cursor:${cursor}; opacity:${opacity}; color:white;">
          <div style="font-size:22px; flex-shrink:0;">${spec.icon || ''}</div>
          <div style="flex:1; min-width:0;">
            <div style="font-size:13px; font-weight:700; color:#a855f7;">${spec.code}. ${spec.name}${usedTag}</div>
            <div style="font-size:11px; color:var(--text-secondary,#cbd5e1); margin-top:2px; line-height:1.4;">${spec.description}</div>
          </div>
        </button>`;
    }).join('');
    return `
      <div style="margin-bottom:10px; font-size:13px; color:var(--text-secondary,#cbd5e1);">
        Bond at <strong style="color:white;">${landmark}</strong>. Pick ONE permanent bonus. You can have at most 3 across all bonds, and never duplicates.
      </div>
      <div style="display:grid; grid-template-columns: 1fr; gap:8px;">${cards}</div>
      <div id="bondBonusError" style="color:#ef4444; font-size:12px; margin-top:10px; min-height:16px;"></div>`;
  }

  async function pickBonus(bondId, code) {
    const errEl = document.getElementById('bondBonusError');
    if (errEl) errEl.textContent = '';
    try {
      const res = await fetch(`/api/aria-bond/${bondId}/choose_bonus`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bonus_type: code })
      });
      const data = await res.json();
      if (!data.success) {
        if (errEl) errEl.textContent = data.error || 'Pick failed';
        return;
      }
      if (window.showToast) showToast(`Bonus chosen: ${data.bonus_name}`);
      if (window.MarsModal) MarsModal.hide();
      setTimeout(() => location.reload(), 400);
    } catch (e) {
      if (errEl) errEl.textContent = 'Network error: ' + e.message;
    }
  }

  function openPicker(bondId, landmark) {
    if (!window.MarsModal) {
      alert('Modal unavailable');
      return;
    }
    MarsModal.show({
      title: 'Choose a Fragment Bond Bonus',
      subtitle: 'Permanent. One per bond. +5% each.',
      body: renderPickerBody(bondId, landmark),
      width: '480px'
    });
    // Wire option clicks after the modal is in the DOM
    setTimeout(() => {
      document.querySelectorAll('.bond-bonus-option').forEach(btn => {
        if (btn.disabled) return;
        btn.addEventListener('click', () => pickBonus(bondId, btn.dataset.code));
      });
    }, 50);
  }

  document.querySelectorAll('.bond-bonus-pick-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      openPicker(parseInt(btn.dataset.bondId, 10), btn.dataset.landmark || '');
    });
  });
})();
