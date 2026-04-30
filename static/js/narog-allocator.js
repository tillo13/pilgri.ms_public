/* ============================================================================
 * narog-allocator.js — Horizontal allocation-bar widget for the Narog Role Dial.
 *
 * Replaces the rotary-knob primitive (knobs are for fine-tuning ONE value;
 * bars are for distributing a budget across N tasks at a glance).
 *
 * Each row is a draggable filled bar with a % readout. Drag anywhere on the
 * track to set; tap-to-jump on click without drag. Sum-to-100 rebalancing
 * across other unlocked rows is the caller's job (controller in crew-robot.js).
 *
 * Public API:
 *   window.NarogAllocator.create({ container, key, value, locked, ariaLabel,
 *                                  onChange, min, max, step })
 *     -> { setValue, setLocked, destroy, el }
 *
 * Layout per instance:
 *   <div class="na-bar-wrap">
 *     <input type="range" class="na-range">     ← hidden, for keyboard A11y
 *     <div class="na-track">
 *       <div class="na-fill"></div>             ← width set via --na-pct
 *       <div class="na-edge"></div>             ← glowing leading edge
 *     </div>
 *     <div class="na-readout">XX%</div>
 *   </div>
 * ========================================================================= */
(function (global) {
    'use strict';

    function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

    function create(opts) {
        const {
            container,
            key,
            value = 0,
            locked = false,
            onChange,
            ariaLabel = key,
            min = 0, max = 100, step = 5,
        } = opts;
        if (!container) throw new Error('NarogAllocator.create: container required');

        const wrap = document.createElement('div');
        wrap.className = 'na-bar-wrap';
        wrap.dataset.key = key;
        wrap.dataset.locked = String(locked);
        wrap.innerHTML = `
            <input type="range" class="na-range" min="${min}" max="${max}" step="${step}" value="${value}" aria-label="${ariaLabel} allocation"/>
            <div class="na-track" role="presentation">
                <div class="na-fill"></div>
                <div class="na-edge"></div>
            </div>
            <div class="na-readout">0%</div>
        `;
        container.appendChild(wrap);

        const range = wrap.querySelector('.na-range');
        const track = wrap.querySelector('.na-track');
        const readout = wrap.querySelector('.na-readout');

        let currentValue = value;
        let dragging = false;

        function paint(v) {
            currentValue = clamp(v, min, max);
            wrap.style.setProperty('--na-pct', currentValue);
            wrap.style.setProperty('--na-active', currentValue > 0 ? 1 : 0);
            readout.textContent = Math.round(currentValue) + '%';
            range.value = currentValue;
        }

        function pctFromEvent(e) {
            const rect = track.getBoundingClientRect();
            const point = (e.touches && e.touches[0]) ? e.touches[0] : e;
            const x = point.clientX - rect.left;
            return clamp(x / rect.width * 100, min, max);
        }

        function emit(rawPct) {
            const stepped = Math.round(rawPct / step) * step;
            if (stepped !== currentValue && typeof onChange === 'function') {
                onChange(stepped, key);
            }
        }

        function handleMove(e) {
            if (!dragging) return;
            e.preventDefault();
            const v = pctFromEvent(e);
            paint(v);  // immediate visual follow during drag
            emit(v);
        }
        function handleUp() {
            if (!dragging) return;
            dragging = false;
            wrap.classList.remove('is-dragging');
            document.removeEventListener('mousemove', handleMove);
            document.removeEventListener('mouseup', handleUp);
            document.removeEventListener('touchmove', handleMove);
            document.removeEventListener('touchend', handleUp);
        }
        function handleDown(e) {
            if (wrap.dataset.locked === 'true') return;  // caller handles modal
            e.preventDefault();
            dragging = true;
            wrap.classList.add('is-dragging');
            document.addEventListener('mousemove', handleMove);
            document.addEventListener('mouseup', handleUp);
            document.addEventListener('touchmove', handleMove, { passive: false });
            document.addEventListener('touchend', handleUp);
            const v = pctFromEvent(e);
            paint(v);
            emit(v);
        }

        track.addEventListener('mousedown', handleDown);
        track.addEventListener('touchstart', handleDown, { passive: false });

        // Keyboard via the hidden range input
        range.addEventListener('input', () => {
            if (wrap.dataset.locked === 'true') return;
            const v = parseInt(range.value, 10) || 0;
            paint(v);
            emit(v);
        });

        paint(value);

        return {
            el: wrap,
            setValue(v) { paint(v); },
            setLocked(b) { wrap.dataset.locked = String(!!b); },
            destroy() { handleUp(); wrap.remove(); },
        };
    }

    global.NarogAllocator = { create };
})(window);
