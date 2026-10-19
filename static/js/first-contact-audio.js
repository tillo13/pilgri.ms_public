/**
 * ARIA First Contact — Procedural Audio
 *
 * All sounds synthesized via Web Audio API — no files to load.
 * Ambient space drone, static crackle, glitch distortion, split crack, reveal tone.
 */
(function() {
    'use strict';

    let ctx = null;
    let masterGain = null;
    let ambientNodes = [];

    function initAudio() {
        if (ctx) return;
        ctx = new (window.AudioContext || window.webkitAudioContext)();
        masterGain = ctx.createGain();
        masterGain.gain.value = 0.6;
        masterGain.connect(ctx.destination);
    }

    // ── AMBIENT SPACE DRONE ──
    // Low rumble + ethereal high tone, fades in slowly
    function startAmbientDrone() {
        initAudio();
        const now = ctx.currentTime;

        // Deep sub-bass rumble (40Hz)
        const sub = ctx.createOscillator();
        sub.type = 'sine';
        sub.frequency.value = 40;
        const subGain = ctx.createGain();
        subGain.gain.setValueAtTime(0, now);
        subGain.gain.linearRampToValueAtTime(0.15, now + 4);
        sub.connect(subGain).connect(masterGain);
        sub.start();
        ambientNodes.push(sub, subGain);

        // Mid drone with slow LFO wobble (120Hz)
        const mid = ctx.createOscillator();
        mid.type = 'triangle';
        mid.frequency.value = 120;
        const midGain = ctx.createGain();
        midGain.gain.setValueAtTime(0, now);
        midGain.gain.linearRampToValueAtTime(0.06, now + 5);
        // LFO for wobble
        const lfo = ctx.createOscillator();
        lfo.type = 'sine';
        lfo.frequency.value = 0.3;
        const lfoGain = ctx.createGain();
        lfoGain.gain.value = 8;
        lfo.connect(lfoGain).connect(mid.frequency);
        lfo.start();
        mid.connect(midGain).connect(masterGain);
        mid.start();
        ambientNodes.push(mid, midGain, lfo, lfoGain);

        // Ethereal high shimmer (800Hz, very quiet)
        const high = ctx.createOscillator();
        high.type = 'sine';
        high.frequency.value = 800;
        const highGain = ctx.createGain();
        highGain.gain.setValueAtTime(0, now);
        highGain.gain.linearRampToValueAtTime(0.02, now + 6);
        // Slow volume tremolo
        const trem = ctx.createOscillator();
        trem.type = 'sine';
        trem.frequency.value = 0.15;
        const tremGain = ctx.createGain();
        tremGain.gain.value = 0.015;
        trem.connect(tremGain).connect(highGain.gain);
        trem.start();
        high.connect(highGain).connect(masterGain);
        high.start();
        ambientNodes.push(high, highGain, trem, tremGain);
    }

    // ── STATIC CRACKLE ──
    // Short burst of filtered noise — like radio static
    function playStaticCrackle(duration) {
        initAudio();
        duration = duration || 1.5;
        const now = ctx.currentTime;

        const bufferSize = ctx.sampleRate * duration;
        const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
        const data = buffer.getChannelData(0);

        // Crackly noise — random pops with gaps
        for (let i = 0; i < bufferSize; i++) {
            if (Math.random() < 0.08) {
                data[i] = (Math.random() * 2 - 1) * 0.6;
            } else {
                data[i] = (Math.random() * 2 - 1) * 0.02;
            }
        }

        const source = ctx.createBufferSource();
        source.buffer = buffer;

        // Bandpass filter to make it sound like radio static
        const filter = ctx.createBiquadFilter();
        filter.type = 'bandpass';
        filter.frequency.value = 3000;
        filter.Q.value = 0.8;

        const gain = ctx.createGain();
        gain.gain.setValueAtTime(0, now);
        gain.gain.linearRampToValueAtTime(0.25, now + 0.1);
        gain.gain.linearRampToValueAtTime(0.15, now + duration * 0.5);
        gain.gain.linearRampToValueAtTime(0, now + duration);

        source.connect(filter).connect(gain).connect(masterGain);
        source.start();
        source.stop(now + duration);
    }

    // ── ORB APPEAR TONE ──
    // Rising ethereal tone — ARIA waking up
    function playOrbAppear() {
        initAudio();
        const now = ctx.currentTime;

        // Rising sine sweep
        const osc = ctx.createOscillator();
        osc.type = 'sine';
        osc.frequency.setValueAtTime(200, now);
        osc.frequency.exponentialRampToValueAtTime(600, now + 2);

        const gain = ctx.createGain();
        gain.gain.setValueAtTime(0, now);
        gain.gain.linearRampToValueAtTime(0.12, now + 0.8);
        gain.gain.linearRampToValueAtTime(0.06, now + 1.5);
        gain.gain.linearRampToValueAtTime(0, now + 2.5);

        // Reverb-like effect with delay
        const delay = ctx.createDelay();
        delay.delayTime.value = 0.15;
        const fbGain = ctx.createGain();
        fbGain.gain.value = 0.3;

        osc.connect(gain).connect(masterGain);
        gain.connect(delay).connect(fbGain).connect(delay);
        fbGain.connect(masterGain);

        osc.start();
        osc.stop(now + 3);
    }

    // ── ARIA SPEAKS (subtle tone per line) ──
    // Soft crystalline ping when each line appears
    function playLineReveal() {
        initAudio();
        const now = ctx.currentTime;

        const osc = ctx.createOscillator();
        osc.type = 'sine';
        osc.frequency.value = 660 + Math.random() * 200;

        const gain = ctx.createGain();
        gain.gain.setValueAtTime(0.08, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.8);

        osc.connect(gain).connect(masterGain);
        osc.start();
        osc.stop(now + 0.8);
    }

    // ── GLITCH SOUND ──
    // Harsh distorted burst — ARIA detecting the anomaly
    function playGlitch() {
        initAudio();
        const now = ctx.currentTime;

        // Noise burst
        const bufferSize = ctx.sampleRate * 0.4;
        const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
        const data = buffer.getChannelData(0);
        for (let i = 0; i < bufferSize; i++) {
            data[i] = (Math.random() * 2 - 1);
        }
        const noise = ctx.createBufferSource();
        noise.buffer = buffer;

        // Distorted oscillator
        const osc = ctx.createOscillator();
        osc.type = 'sawtooth';
        osc.frequency.setValueAtTime(80, now);
        osc.frequency.exponentialRampToValueAtTime(2000, now + 0.15);
        osc.frequency.exponentialRampToValueAtTime(60, now + 0.35);

        // Waveshaper for distortion
        const shaper = ctx.createWaveShaper();
        const curve = new Float32Array(256);
        for (let i = 0; i < 256; i++) {
            const x = (i * 2) / 256 - 1;
            curve[i] = Math.tanh(x * 4);
        }
        shaper.curve = curve;

        const gain = ctx.createGain();
        gain.gain.setValueAtTime(0.3, now);
        gain.gain.linearRampToValueAtTime(0, now + 0.4);

        noise.connect(shaper).connect(gain).connect(masterGain);
        osc.connect(gain);

        noise.start();
        noise.stop(now + 0.4);
        osc.start();
        osc.stop(now + 0.4);
    }

    // ── SPLIT SOUND ──
    // Deep crack + resonance — the orb dividing in two
    function playSplit() {
        initAudio();
        const now = ctx.currentTime;

        // Impact crack
        const bufferSize = ctx.sampleRate * 0.3;
        const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
        const data = buffer.getChannelData(0);
        for (let i = 0; i < bufferSize; i++) {
            const t = i / ctx.sampleRate;
            data[i] = (Math.random() * 2 - 1) * Math.exp(-t * 15);
        }
        const crack = ctx.createBufferSource();
        crack.buffer = buffer;

        const crackGain = ctx.createGain();
        crackGain.gain.value = 0.4;
        crack.connect(crackGain).connect(masterGain);
        crack.start();

        // Deep resonance after the crack
        const res = ctx.createOscillator();
        res.type = 'sine';
        res.frequency.setValueAtTime(80, now + 0.05);
        res.frequency.exponentialRampToValueAtTime(40, now + 2);

        const resGain = ctx.createGain();
        resGain.gain.setValueAtTime(0.2, now + 0.05);
        resGain.gain.linearRampToValueAtTime(0, now + 2.5);

        res.connect(resGain).connect(masterGain);
        res.start(now + 0.05);
        res.stop(now + 2.5);

        // High crystal ring
        const ring = ctx.createOscillator();
        ring.type = 'sine';
        ring.frequency.value = 1200;
        const ringGain = ctx.createGain();
        ringGain.gain.setValueAtTime(0.1, now + 0.02);
        ringGain.gain.exponentialRampToValueAtTime(0.001, now + 2);
        ring.connect(ringGain).connect(masterGain);
        ring.start(now + 0.02);
        ring.stop(now + 2);
    }

    // ── BOND REVEAL ──
    // Triumphant chord — the moment of truth
    function playBondReveal() {
        initAudio();
        const now = ctx.currentTime;

        // Major chord: root + third + fifth + octave
        const freqs = [220, 277.18, 329.63, 440];
        freqs.forEach(function(freq, i) {
            const osc = ctx.createOscillator();
            osc.type = 'sine';
            osc.frequency.value = freq;

            const gain = ctx.createGain();
            const onset = now + i * 0.08;
            gain.gain.setValueAtTime(0, onset);
            gain.gain.linearRampToValueAtTime(0.08, onset + 0.3);
            gain.gain.linearRampToValueAtTime(0.04, onset + 2);
            gain.gain.linearRampToValueAtTime(0, onset + 4);

            osc.connect(gain).connect(masterGain);
            osc.start(onset);
            osc.stop(onset + 4);
        });

        // Shimmer layer
        const shimmer = ctx.createOscillator();
        shimmer.type = 'triangle';
        shimmer.frequency.value = 880;
        const shimGain = ctx.createGain();
        shimGain.gain.setValueAtTime(0, now + 0.2);
        shimGain.gain.linearRampToValueAtTime(0.03, now + 1);
        shimGain.gain.linearRampToValueAtTime(0, now + 4);
        shimmer.connect(shimGain).connect(masterGain);
        shimmer.start(now + 0.2);
        shimmer.stop(now + 4);
    }

    // ── ENTANGLEMENT HUM ──
    // Dual-frequency beat — two ARIAs resonating
    function playEntanglementHum() {
        initAudio();
        const now = ctx.currentTime;

        // Two close frequencies create a beat frequency effect
        const osc1 = ctx.createOscillator();
        osc1.type = 'sine';
        osc1.frequency.value = 220;
        const osc2 = ctx.createOscillator();
        osc2.type = 'sine';
        osc2.frequency.value = 223; // 3Hz beat

        const gain = ctx.createGain();
        gain.gain.setValueAtTime(0, now);
        gain.gain.linearRampToValueAtTime(0.06, now + 1);

        osc1.connect(gain).connect(masterGain);
        osc2.connect(gain);
        osc1.start();
        osc2.start();
        ambientNodes.push(osc1, osc2, gain);
    }

    // ── FADE OUT ALL ──
    function fadeOutAll(duration) {
        if (!ctx || !masterGain) return;
        const now = ctx.currentTime;
        masterGain.gain.linearRampToValueAtTime(0, now + (duration || 2));
    }

    // Export for first-contact.js to call
    window.FCaudio = {
        startAmbientDrone: startAmbientDrone,
        playStaticCrackle: playStaticCrackle,
        playOrbAppear: playOrbAppear,
        playLineReveal: playLineReveal,
        playGlitch: playGlitch,
        playSplit: playSplit,
        playBondReveal: playBondReveal,
        playEntanglementHum: playEntanglementHum,
        fadeOutAll: fadeOutAll,
        init: initAudio
    };
})();
