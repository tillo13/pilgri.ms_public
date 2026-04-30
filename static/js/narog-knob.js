/* ============================================================================
 * narog-knob.js — Self-contained rotary knob component for the Narog Role Dial.
 *
 * Architecture follows francoisgeorgy/svg-knob's 4-layer pattern:
 *   1) Rocky bezel (irregular hewn polygon, deterministic per knob key)
 *   2) Scale ring (tick marks across a 270° sweep)
 *   3) Cursor (pointer + conic-gradient progress arc behind it)
 *   4) Readout (the % text in the lower face)
 *
 * Pure controller — no global state. Each knob is created via createKnob()
 * with its own value + onChange callback. Drag math is decoupled from chrome.
 *
 * Public API:
 *   window.NarogKnob.create({ container, key, value, locked, onChange,
 *                             unlockHint, ariaLabel })
 *     -> { setValue, setLocked, destroy, el }
 *
 * Visual sweep: -135° (0%) → +135° (100%), 270° total.
 * Mod-5 quantization is the controller's responsibility; this widget reports
 * raw percent and lets the caller decide how to round.
 * ========================================================================= */
(function (global) {
    'use strict';

    const SVG_NS = 'http://www.w3.org/2000/svg';
    const KNOB_MIN_ANGLE = -135;
    const KNOB_MAX_ANGLE = 135;
    const KNOB_SWEEP = KNOB_MAX_ANGLE - KNOB_MIN_ANGLE;  // 270
    const VIEWBOX = 140;
    const CENTER = 70;

    // -------- helpers ------------------------------------------------------
    function svg(tag, attrs) {
        const el = document.createElementNS(SVG_NS, tag);
        for (const k in attrs) el.setAttribute(k, attrs[k]);
        return el;
    }

    function seedFromString(s) {
        let h = 2166136261;
        for (let i = 0; i < s.length; i++) {
            h ^= s.charCodeAt(i);
            h = Math.imul(h, 16777619);
        }
        return h >>> 0;
    }
    function mulberry32(seed) {
        let t = seed >>> 0;
        return function () {
            t = (t + 0x6D2B79F5) >>> 0;
            let x = t;
            x = Math.imul(x ^ (x >>> 15), x | 1);
            x ^= x + Math.imul(x ^ (x >>> 7), x | 61);
            return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
        };
    }

    // Hewn-stone polygon: n points around (cx, cy) at avg radius r, jittered ±j
    function rockyPoly(cx, cy, r, n, j, rng) {
        const pts = [];
        for (let i = 0; i < n; i++) {
            const a = (i / n) * Math.PI * 2 - Math.PI / 2;
            const rr = r + (rng() - 0.5) * 2 * j;
            pts.push((cx + Math.cos(a) * rr).toFixed(2) + ',' +
                     (cy + Math.sin(a) * rr).toFixed(2));
        }
        return pts.join(' ');
    }

    function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
    function valueToAngle(v) { return KNOB_MIN_ANGLE + (v / 100) * KNOB_SWEEP; }
    function angleToValue(a) { return clamp((a - KNOB_MIN_ANGLE) / KNOB_SWEEP * 100, 0, 100); }

    // -------- chrome layers (each builds & returns its own SVG group) ------
    function buildBezel(rng) {
        const g = svg('g', { class: 'nk-bezel' });
        // Outer hewn rim
        g.appendChild(svg('polygon', {
            class: 'nk-bezel-outer',
            points: rockyPoly(CENTER, CENTER, 62, 24, 4, rng),
        }));
        // Mid stone ring
        g.appendChild(svg('polygon', {
            class: 'nk-bezel-mid',
            points: rockyPoly(CENTER, CENTER, 56, 22, 2.5, rng),
        }));
        // Smooth highlight ring on top
        g.appendChild(svg('circle', {
            cx: CENTER, cy: CENTER, r: 53, class: 'nk-bezel-rim',
        }));
        // Random rock chips around the rim
        const chipCount = 5 + Math.floor(rng() * 3);
        for (let i = 0; i < chipCount; i++) {
            const a = rng() * Math.PI * 2;
            const r = 60 + rng() * 4;
            const ccx = CENTER + Math.cos(a) * r;
            const ccy = CENTER + Math.sin(a) * r;
            const chipR = 2.5 + rng() * 2.5;
            g.appendChild(svg('polygon', {
                class: rng() < 0.5 ? 'nk-chip' : 'nk-chip-light',
                points: rockyPoly(ccx, ccy, chipR, 6, 1.2, rng),
            }));
        }
        return g;
    }

    function buildFace(rng) {
        const g = svg('g', { class: 'nk-face' });
        // Inner stone face (slightly irregular polygon)
        g.appendChild(svg('polygon', {
            class: 'nk-face-base',
            points: rockyPoly(CENTER, CENTER, 47, 28, 1.2, rng),
        }));
        // Top-left shine ellipse
        g.appendChild(svg('ellipse', {
            cx: CENTER - 10, cy: CENTER - 14, rx: 22, ry: 12,
            class: 'nk-face-shine',
        }));
        // Crystal veins — 2-3 thin curves
        const veinCount = 2 + Math.floor(rng() * 2);
        for (let i = 0; i < veinCount; i++) {
            const a0 = rng() * Math.PI * 2;
            const a1 = a0 + Math.PI + (rng() - 0.5) * 0.6;
            const r0 = 38 + rng() * 6, r1 = 38 + rng() * 6;
            const x0 = CENTER + Math.cos(a0) * r0, y0 = CENTER + Math.sin(a0) * r0;
            const x1 = CENTER + Math.cos(a1) * r1, y1 = CENTER + Math.sin(a1) * r1;
            const mx = CENTER + (rng() - 0.5) * 24, my = CENTER + (rng() - 0.5) * 24;
            g.appendChild(svg('path', {
                class: 'nk-vein',
                d: `M${x0.toFixed(1)} ${y0.toFixed(1)} Q${mx.toFixed(1)} ${my.toFixed(1)} ${x1.toFixed(1)} ${y1.toFixed(1)}`,
            }));
        }
        return g;
    }

    function buildScale() {
        const g = svg('g', { class: 'nk-scale' });
        // 21 ticks across the 270° sweep, every 4th major (every 20%)
        for (let i = 0; i <= 20; i++) {
            const t = i / 20;
            const angle = KNOB_MIN_ANGLE + t * KNOB_SWEEP;
            const rad = (angle - 90) * Math.PI / 180;
            const major = (i % 4 === 0);
            const r1 = 50, r2 = major ? 42 : 45;
            g.appendChild(svg('line', {
                x1: CENTER + Math.cos(rad) * r1,
                y1: CENTER + Math.sin(rad) * r1,
                x2: CENTER + Math.cos(rad) * r2,
                y2: CENTER + Math.sin(rad) * r2,
                class: major ? 'nk-tick nk-tick-major' : 'nk-tick',
            }));
        }
        return g;
    }

    // SVG arc path from -135° to (-135° + value%·270°), at radius r.
    // Used for the conic-style "filled" progress arc behind the pointer.
    function arcPath(value, r) {
        const v = clamp(value, 0, 100);
        if (v <= 0) return '';
        const startA = (KNOB_MIN_ANGLE - 90) * Math.PI / 180;
        const endA = (valueToAngle(v) - 90) * Math.PI / 180;
        const x1 = CENTER + Math.cos(startA) * r, y1 = CENTER + Math.sin(startA) * r;
        const x2 = CENTER + Math.cos(endA) * r,   y2 = CENTER + Math.sin(endA) * r;
        const large = (valueToAngle(v) - KNOB_MIN_ANGLE) > 180 ? 1 : 0;
        return `M${x1.toFixed(2)} ${y1.toFixed(2)} A${r} ${r} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
    }

    function buildCursor() {
        const g = svg('g', { class: 'nk-cursor' });
        // Filled progress arc (visual weight — the "gauge filling up" feel)
        g.appendChild(svg('path', {
            class: 'nk-arc',
            d: '',
            'fill': 'none',
        }));
        // Pointer line
        g.appendChild(svg('line', {
            class: 'nk-pointer',
            x1: CENTER, y1: CENTER, x2: CENTER, y2: 24,
        }));
        // Hub
        g.appendChild(svg('circle', {
            class: 'nk-hub',
            cx: CENTER, cy: CENTER, r: 7,
        }));
        g.appendChild(svg('circle', {
            class: 'nk-hub-bolt',
            cx: CENTER, cy: CENTER, r: 3,
        }));
        return g;
    }

    function buildReadout() {
        return svg('text', {
            class: 'nk-readout',
            x: CENTER, y: 108,
            'text-anchor': 'middle',
        });
    }

    // -------- public factory ----------------------------------------------
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

        if (!container) throw new Error('NarogKnob.create: container required');

        const rng = mulberry32(seedFromString(key || 'default'));

        // Outer wrapper: an SVG holds the chrome + a hidden range input for a11y
        const root = document.createElement('div');
        root.className = 'nk-root';
        root.dataset.key = key;
        root.dataset.locked = String(locked);

        // Hidden native range — keyboard + screen reader support
        const range = document.createElement('input');
        range.type = 'range';
        range.min = min; range.max = max; range.step = step;
        range.value = value;
        range.className = 'nk-range';
        range.setAttribute('aria-label', ariaLabel);
        root.appendChild(range);

        const svgEl = svg('svg', {
            class: 'nk-svg',
            viewBox: `0 0 ${VIEWBOX} ${VIEWBOX}`,
            tabindex: '-1',
        });
        svgEl.appendChild(buildBezel(rng));
        svgEl.appendChild(buildFace(rng));
        svgEl.appendChild(buildScale());
        const cursorG = buildCursor();
        svgEl.appendChild(cursorG);
        const readout = buildReadout();
        svgEl.appendChild(readout);
        root.appendChild(svgEl);
        container.appendChild(root);

        const arcEl = cursorG.querySelector('.nk-arc');
        const pointerEl = cursorG.querySelector('.nk-pointer');

        let currentValue = value;
        let dragging = false;

        function paint(v) {
            currentValue = clamp(v, min, max);
            const angle = valueToAngle(currentValue);
            // CSS custom property drives the active-knob glow + any css transitions
            root.style.setProperty('--nk-pct', currentValue);
            root.style.setProperty('--nk-active', currentValue > 0 ? 1 : 0);
            pointerEl.style.transform = `rotate(${angle}deg)`;
            arcEl.setAttribute('d', arcPath(currentValue, 50));
            readout.textContent = Math.round(currentValue) + '%';
            range.value = currentValue;
        }

        // --- drag math ---
        function angleFromEvent(e) {
            const rect = svgEl.getBoundingClientRect();
            const cx = rect.left + rect.width / 2;
            const cy = rect.top + rect.height / 2;
            const point = (e.touches && e.touches[0]) ? e.touches[0] : e;
            const dx = point.clientX - cx, dy = point.clientY - cy;
            // 0° = up, clockwise positive
            let deg = Math.atan2(dx, -dy) * 180 / Math.PI;
            return clamp(deg, KNOB_MIN_ANGLE, KNOB_MAX_ANGLE);
        }

        function emit(v) {
            // Quantize to step, clamp, fire onChange. Caller decides what to do
            // with it (e.g. apply rebalance across other knobs).
            const stepped = Math.round(v / step) * step;
            if (stepped !== currentValue && typeof onChange === 'function') {
                onChange(stepped, key);
            }
        }

        function handleMove(e) {
            if (!dragging) return;
            e.preventDefault();
            const v = angleToValue(angleFromEvent(e));
            paint(v);  // visual follow during drag (will be re-painted on commit)
            emit(v);
        }
        function handleUp() {
            if (!dragging) return;
            dragging = false;
            svgEl.classList.remove('dragging');
            document.removeEventListener('mousemove', handleMove);
            document.removeEventListener('mouseup', handleUp);
            document.removeEventListener('touchmove', handleMove);
            document.removeEventListener('touchend', handleUp);
        }
        function handleDown(e) {
            if (root.dataset.locked === 'true') return;  // locked → caller handles modal
            e.preventDefault();
            dragging = true;
            svgEl.classList.add('dragging');
            document.addEventListener('mousemove', handleMove);
            document.addEventListener('mouseup', handleUp);
            document.addEventListener('touchmove', handleMove, { passive: false });
            document.addEventListener('touchend', handleUp);
            // Click-to-jump: also commit the angle of where they pressed
            const v = angleToValue(angleFromEvent(e));
            paint(v);
            emit(v);
        }

        svgEl.addEventListener('mousedown', handleDown);
        svgEl.addEventListener('touchstart', handleDown, { passive: false });

        // Native range fallback (keyboard) — fires onChange via our same path
        range.addEventListener('input', () => {
            if (root.dataset.locked === 'true') return;
            const v = parseInt(range.value, 10) || 0;
            paint(v);
            emit(v);
        });

        // Initial paint
        paint(value);

        return {
            el: root,
            setValue(v) { paint(v); },
            setLocked(b) { root.dataset.locked = String(!!b); },
            destroy() { handleUp(); root.remove(); },
        };
    }

    global.NarogKnob = { create };
})(window);
