/**
 * EpicReveal — Reusable cinematic overlay for epic moments
 *
 * Usage:
 *   EpicReveal.show({
 *       title: 'ARIA BOND #1',
 *       lines: [
 *           { text: '*static crackle*', cls: 'static-crackle', sound: 'crackle' },
 *           { text: 'I just detected... myself?', sound: 'glitch' },
 *           { text: "That's impossible.", cls: 'emphasis' },
 *       ],
 *       image: 'https://storage.../bond_image.png',
 *       info: {
 *           label: 'Entangled Fragment: Herschel',
 *           name1: 'Captain Andy', name2: 'Captain Luke',
 *           detail: 'SOL 54109'
 *       },
 *       revelation: { label: 'ARIA MEMORY UNLOCKED', text: 'I detected...' },
 *       record: { url: 'https://sepolia.etherscan.io/tx/0x...', hash: '0x...' },
 *       actions: [
 *           { label: 'View in Colony', href: '/colony', cls: 'primary' },
 *           { label: 'Replay Cinematic', href: '/aria-first-contact/replay', cls: 'secondary' },
 *       ],
 *       onClose: function() { // cleanup }
 *   });
 */
window.EpicReveal = (function() {
    'use strict';

    // Timing constants (ms)
    var T = {
        STARS: 300,
        ORB: 800,
        FIRST_LINE: 1200,
        LINE_GAP: 1400,
        IMAGE: 800,
        INFO: 600,
        REVELATION: 600,
        RECORD: 400,
        ACTIONS: 400
    };

    var overlay = null;
    var audio = null;
    var skipped = false;
    var onCloseCb = null;

    function delay(ms) {
        if (skipped) return Promise.resolve();
        return new Promise(function(r) { setTimeout(r, ms); });
    }

    function initAudio() {
        // Always create our own audio context — FCaudio may not have all sounds
        // (e.g. golem sounds) and its context may be stale/suspended.
        try {
            var ctx = new (window.AudioContext || window.webkitAudioContext)();
            var master = ctx.createGain();
            master.gain.value = 0.8;
            master.connect(ctx.destination);

            audio = {
                playLineReveal: function() {
                    var osc = ctx.createOscillator();
                    var g = ctx.createGain();
                    osc.type = 'sine';
                    osc.frequency.value = 660 + Math.random() * 200;
                    g.gain.setValueAtTime(0.06, ctx.currentTime);
                    g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.6);
                    osc.connect(g); g.connect(master);
                    osc.start(); osc.stop(ctx.currentTime + 0.6);
                },
                playGlitch: function() {
                    var buf = ctx.createBuffer(1, ctx.sampleRate * 0.3, ctx.sampleRate);
                    var d = buf.getChannelData(0);
                    for (var i = 0; i < d.length; i++) d[i] = (Math.random() * 2 - 1) * 0.3;
                    var src = ctx.createBufferSource();
                    src.buffer = buf;
                    var g = ctx.createGain();
                    g.gain.setValueAtTime(0.15, ctx.currentTime);
                    g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.3);
                    src.connect(g); g.connect(master);
                    src.start();
                },
                playStaticCrackle: function() {
                    var buf = ctx.createBuffer(1, ctx.sampleRate * 1.2, ctx.sampleRate);
                    var d = buf.getChannelData(0);
                    for (var i = 0; i < d.length; i++) d[i] = Math.random() < 0.08 ? (Math.random() * 2 - 1) * 0.2 : 0;
                    var src = ctx.createBufferSource();
                    src.buffer = buf;
                    var g = ctx.createGain();
                    g.gain.setValueAtTime(0.1, ctx.currentTime);
                    g.gain.linearRampToValueAtTime(0, ctx.currentTime + 1.2);
                    src.connect(g); g.connect(master);
                    src.start();
                },
                playBondReveal: function() {
                    [220, 277.18, 329.63, 440].forEach(function(freq, i) {
                        var osc = ctx.createOscillator();
                        var g = ctx.createGain();
                        osc.type = 'sine';
                        osc.frequency.value = freq;
                        g.gain.setValueAtTime(0, ctx.currentTime + i * 0.008);
                        g.gain.linearRampToValueAtTime(0.08, ctx.currentTime + i * 0.008 + 0.1);
                        g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 3);
                        osc.connect(g); g.connect(master);
                        osc.start(ctx.currentTime + i * 0.008);
                        osc.stop(ctx.currentTime + 3);
                    });
                },
                startAmbientDrone: function() {
                    var osc = ctx.createOscillator();
                    var g = ctx.createGain();
                    osc.type = 'sine';
                    osc.frequency.value = 55;
                    g.gain.setValueAtTime(0, ctx.currentTime);
                    g.gain.linearRampToValueAtTime(0.04, ctx.currentTime + 3);
                    osc.connect(g); g.connect(master);
                    osc.start();
                    audio._drone = { osc: osc, gain: g };
                },
                // Golem sounds — earthy, stone, crystal
                playStoneGrind: function() {
                    // Low rumbling noise with bandpass = stone scraping
                    var buf = ctx.createBuffer(1, ctx.sampleRate * 0.8, ctx.sampleRate);
                    var d = buf.getChannelData(0);
                    for (var i = 0; i < d.length; i++) d[i] = (Math.random() * 2 - 1);
                    var src = ctx.createBufferSource(); src.buffer = buf;
                    var bp = ctx.createBiquadFilter(); bp.type = 'bandpass'; bp.frequency.value = 120; bp.Q.value = 2;
                    var g = ctx.createGain();
                    g.gain.setValueAtTime(0.2, ctx.currentTime);
                    g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.8);
                    src.connect(bp); bp.connect(g); g.connect(master); src.start();
                },
                playCrystalChime: function() {
                    // High shimmering tones = Sepolia crystal resonance
                    [1320, 1760, 2640].forEach(function(freq, i) {
                        var osc = ctx.createOscillator(); var g = ctx.createGain();
                        osc.type = 'sine'; osc.frequency.value = freq;
                        g.gain.setValueAtTime(0, ctx.currentTime + i * 0.05);
                        g.gain.linearRampToValueAtTime(0.06, ctx.currentTime + i * 0.05 + 0.05);
                        g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 2);
                        osc.connect(g); g.connect(master);
                        osc.start(ctx.currentTime + i * 0.05); osc.stop(ctx.currentTime + 2);
                    });
                },
                playDeepRumble: function() {
                    // Sub-bass hit = heavy stone footstep
                    var osc = ctx.createOscillator(); var g = ctx.createGain();
                    osc.type = 'triangle'; osc.frequency.value = 40;
                    osc.frequency.exponentialRampToValueAtTime(25, ctx.currentTime + 0.6);
                    g.gain.setValueAtTime(0.25, ctx.currentTime);
                    g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.6);
                    osc.connect(g); g.connect(master); osc.start(); osc.stop(ctx.currentTime + 0.6);
                },
                playGolemAwaken: function() {
                    // Rising chord: stone + crystal = golem comes alive
                    [55, 82.5, 110, 165, 660, 1320].forEach(function(freq, i) {
                        var osc = ctx.createOscillator(); var g = ctx.createGain();
                        osc.type = freq > 500 ? 'sine' : 'triangle';
                        osc.frequency.value = freq;
                        var startAt = ctx.currentTime + i * 0.15;
                        g.gain.setValueAtTime(0, startAt);
                        g.gain.linearRampToValueAtTime(freq > 500 ? 0.05 : 0.08, startAt + 0.2);
                        g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 4);
                        osc.connect(g); g.connect(master);
                        osc.start(startAt); osc.stop(ctx.currentTime + 4);
                    });
                },
                fadeOutAll: function(dur) {
                    master.gain.linearRampToValueAtTime(0, ctx.currentTime + (dur || 1));
                    if (audio._drone) {
                        audio._drone.osc.stop(ctx.currentTime + (dur || 1) + 0.1);
                    }
                }
            };
        } catch (e) {
            audio = {};
        }
    }

    function skipAll() {
        skipped = true;
        // Make everything visible immediately
        if (!overlay) return;
        overlay.querySelectorAll('.er-orb, .er-line, .er-image, .er-info, .er-revelation, .er-record, .er-actions, .er-stars')
            .forEach(function(el) { el.classList.add('visible'); });
    }

    function close() {
        if (!overlay) return;
        document.body.classList.remove('er-active');
        if (audio && audio.fadeOutAll) audio.fadeOutAll(0.5);
        overlay.style.transition = 'opacity 0.5s ease';
        overlay.style.opacity = '0';
        setTimeout(function() {
            if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
            overlay = null;
            skipped = false;
            audio = null;
            if (onCloseCb) onCloseCb();
        }, 500);
    }

    async function runSequence(opts) {
        var stars = overlay.querySelector('.er-stars');
        var orb = overlay.querySelector('.er-orb');
        var textArea = overlay.querySelector('.er-text-area');
        var hint = overlay.querySelector('.er-sound-hint');

        // Init audio on first interaction
        initAudio();
        if (audio && audio.startAmbientDrone) audio.startAmbientDrone();

        // Stars
        await delay(T.STARS);
        stars.classList.add('visible');
        if (hint) hint.classList.add('visible');

        // Orb appears
        await delay(T.ORB);
        orb.classList.add('visible');

        // Type out lines
        await delay(T.FIRST_LINE);
        if (hint) hint.classList.remove('visible');

        var lines = opts.lines || [];
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i];
            var el = document.createElement('div');
            el.className = 'er-line' + (line.cls ? ' ' + line.cls : '');
            el.textContent = line.text;
            textArea.appendChild(el);
            await delay(60);
            el.classList.add('visible');

            // Play sounds — maps line.sound to audio.playXxx()
            if (line.sound && audio) {
                var soundMap = {
                    crackle: 'playStaticCrackle',
                    glitch: 'playGlitch',
                    stoneGrind: 'playStoneGrind',
                    crystalChime: 'playCrystalChime',
                    deepRumble: 'playDeepRumble',
                    golemAwaken: 'playGolemAwaken',
                };
                var fn = soundMap[line.sound];
                if (fn && audio[fn]) {
                    audio[fn]();
                    if (line.sound === 'glitch') {
                        orb.classList.add('glitching');
                        await delay(400);
                        orb.classList.remove('glitching');
                    }
                }
            } else if (audio && audio.playLineReveal) {
                audio.playLineReveal();
            }
            await delay(T.LINE_GAP);
        }

        // Image reveal
        var img = overlay.querySelector('.er-image');
        if (img) {
            await delay(T.IMAGE);
            var revealFn = opts.revealSound && audio && audio[opts.revealSound] ? opts.revealSound : 'playBondReveal';
            if (audio && audio[revealFn]) audio[revealFn]();
            img.classList.add('visible');
        }

        // Info section
        var info = overlay.querySelector('.er-info');
        if (info) {
            await delay(T.INFO);
            info.classList.add('visible');
        }

        // Revelation
        var rev = overlay.querySelector('.er-revelation');
        if (rev) {
            await delay(T.REVELATION);
            rev.classList.add('visible');
        }

        // Permanent record
        var rec = overlay.querySelector('.er-record');
        if (rec) {
            await delay(T.RECORD);
            rec.classList.add('visible');
        }

        // Action buttons
        var acts = overlay.querySelector('.er-actions');
        if (acts) {
            await delay(T.ACTIONS);
            acts.classList.add('visible');
        }
    }

    function show(opts) {
        // Prevent duplicates
        if (overlay) close();
        skipped = false;
        onCloseCb = opts.onClose || null;

        // Build DOM
        var html = '<div class="er-stars"></div>';
        html += '<button class="er-close" title="Close">&times;</button>';
        html += '<div class="er-content">';

        // Orb
        html += '<div class="er-orb"></div>';

        // Text area (lines added dynamically)
        html += '<div class="er-text-area"></div>';

        // Image
        if (opts.image) {
            html += '<img class="er-image" src="' + opts.image + '" alt="Artifact">';
        }

        // Title
        if (opts.title) {
            html += '<div style="font-size: 16px; font-weight: 700; color: #06b6d4; margin: 4px 0; letter-spacing: 1px;">' + opts.title + '</div>';
        }

        // Info section — supports custom HTML via opts.info.html
        if (opts.info) {
            html += '<div class="er-info">';
            if (opts.info.html) {
                html += opts.info.html;
            } else {
                if (opts.info.label) html += '<div class="er-info-label">' + opts.info.label + '</div>';
                if (opts.info.name1 && opts.info.name2) {
                    html += '<div class="er-info-names"><span class="name">' + opts.info.name1 + '</span><span class="plus">+</span><span class="name">' + opts.info.name2 + '</span></div>';
                }
                if (opts.info.detail) html += '<div class="er-info-detail">' + opts.info.detail + '</div>';
            }
            html += '</div>';
        }

        // Revelation
        if (opts.revelation) {
            html += '<div class="er-revelation">';
            html += '<div class="er-revelation-label">' + (opts.revelation.label || 'UNLOCKED') + '</div>';
            html += '<div class="er-revelation-text">' + opts.revelation.text + '</div>';
            html += '</div>';
        }

        // Permanent record
        if (opts.record) {
            html += '<div class="er-record">';
            html += '<div class="er-record-label">Permanent Record</div>';
            if (opts.record.url) {
                html += '<a href="' + opts.record.url + '" target="_blank" rel="noopener">' + (opts.record.hash || 'View') + '</a>';
            }
            html += '<div class="er-record-note">Permanently inscribed. It can never be deleted.</div>';
            html += '</div>';
        }

        // Action buttons
        if (opts.actions && opts.actions.length) {
            html += '<div class="er-actions">';
            opts.actions.forEach(function(a) {
                var cls = a.cls === 'secondary' ? 'er-btn-secondary' : 'er-btn-primary';
                if (a.href) {
                    html += '<a href="' + a.href + '" class="er-btn ' + cls + '">' + a.label + '</a>';
                } else {
                    html += '<button class="er-btn ' + cls + '" onclick="EpicReveal.close()">' + a.label + '</button>';
                }
            });
            html += '</div>';
        }

        html += '</div>'; // .er-content

        // Sound hint
        html += '<div class="er-sound-hint">Turn sound up for the full experience</div>';

        // Create overlay
        overlay = document.createElement('div');
        overlay.className = 'er-overlay';
        overlay.innerHTML = html;
        document.body.appendChild(overlay);
        document.body.classList.add('er-active');

        // Fade in
        requestAnimationFrame(function() {
            overlay.classList.add('visible');
        });

        // Close button
        overlay.querySelector('.er-close').addEventListener('click', close);

        // Skip on double-click
        overlay.addEventListener('dblclick', function(e) {
            if (e.target.tagName === 'A' || e.target.tagName === 'BUTTON') return;
            skipAll();
        });

        // ESC to close
        var escHandler = function(e) {
            if (e.key === 'Escape') {
                close();
                document.removeEventListener('keydown', escHandler);
            }
        };
        document.addEventListener('keydown', escHandler);

        // Run the sequence
        runSequence(opts);
    }

    return { show: show, close: close };
})();
