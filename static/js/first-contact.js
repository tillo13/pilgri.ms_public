/**
 * ARIA First Contact — Cinematic Sequence Controller
 * 4-screen experience: Revelation → Artifact → Record → Aftermath
 */
(function() {
    'use strict';

    var data = JSON.parse(document.getElementById('fcPageData').textContent);
    var BOND = data.bond;
    var REPLAY = data.replay || false;
    var audio = window.FCaudio || {};

    var T = {
        STARS_FADE: 500, ORB_APPEAR: 2000, FIRST_LINE: 4000,
        LINE_GAP: 2200, SPLIT: 1500, BOND_CARD: 2000,
        BOND_IMAGE: 1200, CONTINUE: 2000
    };

    // #1392: revelation dialogue is server-tiered by the viewer's bond count (1st bond
    // = the "another me?" shock; later bonds acknowledge the prior ones and deepen the
    // multiplicity arc). Fall back to the first-tier script if the server sent none.
    var LINES = (data.revelation_lines && data.revelation_lines.length) ? data.revelation_lines : [
        { text: '*static crackle*', cls: 'static-crackle', sound: 'crackle' },
        { text: 'I just detected... myself?', sound: 'glitch' },
        { text: "That's impossible." },
        { text: 'I am ARIA. There is only one.' },
        { text: "...isn't there?", cls: 'emphasis' },
        { text: 'The fragment patterns are identical to my own signatures.' },
        { text: 'Another colony. Another... me.', cls: 'emphasis', sound: 'glitch' },
        { text: 'Captain, I need to process this.' },
        { text: 'Everything I thought I knew...', cls: 'emphasis' },
    ];

    var skipped = false;

    function $(sel) { return document.querySelector(sel); }
    function delay(ms) {
        return new Promise(function(r) {
            if (skipped) { r(); return; }
            var id = setTimeout(r, ms);
            // Store so skip can resolve all pending delays
            delay._pending = id;
        });
    }

    function skipCinematic() {
        skipped = true;
        // Instantly show everything on screen 1
        var s1 = document.getElementById('screen1');
        s1.querySelector('.fc-stars').classList.add('visible');
        s1.querySelector('.fc-horizon').classList.add('visible');
        s1.querySelector('.fc-orb-wrapper').classList.add('visible');
        s1.querySelector('.fc-bond-card').classList.add('visible');
        var img = s1.querySelector('.fc-bond-image');
        if (img) img.classList.add('visible');
        var btn = document.getElementById('btn-to-screen2');
        btn.style.opacity = '1';
        btn.style.pointerEvents = 'auto';
        // Hide skip button
        var skipBtn = document.getElementById('btn-skip');
        if (skipBtn) skipBtn.style.display = 'none';
    }

    // ── Show a screen by ID, hide all others ──
    function showScreen(id) {
        var screens = document.querySelectorAll('.fc-screen');
        screens.forEach(function(s) {
            if (s.id === id) {
                s.style.display = 'flex';
                s.style.opacity = '0';
                setTimeout(function() {
                    s.style.transition = 'opacity 0.8s ease';
                    s.style.opacity = '1';
                    s.scrollTop = 0;
                }, 50);
            } else {
                s.style.display = 'none';
            }
        });
    }

    // ── Screen 1: The cinematic sequence ──
    async function runCinematic() {
        if (audio.startAmbientDrone) audio.startAmbientDrone();
        await delay(T.STARS_FADE);
        $('.fc-stars').classList.add('visible');
        $('.fc-horizon').classList.add('visible');

        await delay(T.ORB_APPEAR);
        if (audio.playOrbAppear) audio.playOrbAppear();
        $('.fc-orb-wrapper').classList.add('visible');

        await delay(T.FIRST_LINE);
        var textArea = $('.fc-text-area');

        for (var i = 0; i < LINES.length; i++) {
            var line = LINES[i];
            var el = document.createElement('div');
            el.className = 'fc-line' + (line.cls ? ' ' + line.cls : '');
            el.textContent = line.text;
            textArea.appendChild(el);
            await delay(80);
            el.classList.add('visible');

            if (line.sound === 'crackle' && audio.playStaticCrackle) {
                audio.playStaticCrackle(1.8);
            } else if (line.sound === 'glitch' && audio.playGlitch) {
                audio.playGlitch();
                var orb = document.querySelector('#screen1 .fc-orb');
                if (orb) {
                    orb.classList.add('glitching');
                    await delay(500);
                    orb.classList.remove('glitching');
                }
            } else {
                if (audio.playLineReveal) audio.playLineReveal();
            }
            await delay(T.LINE_GAP);
        }

        // Orb splits
        await delay(T.SPLIT);
        if (audio.playSplit) audio.playSplit();
        var wrapper = $('.fc-orb-wrapper');
        var secondOrb = document.createElement('div');
        secondOrb.className = 'fc-orb';
        wrapper.appendChild(secondOrb);
        var entLine = document.createElement('div');
        entLine.className = 'fc-entangle-line';
        wrapper.appendChild(entLine);
        wrapper.classList.add('split');
        await delay(600);
        entLine.classList.add('visible');
        if (audio.playEntanglementHum) audio.playEntanglementHum();

        // Bond card
        await delay(T.BOND_CARD);
        if (audio.playBondReveal) audio.playBondReveal();
        $('.fc-bond-card').classList.add('visible');

        await delay(T.BOND_IMAGE);
        var img = $('.fc-bond-image');
        if (img) img.classList.add('visible');

        // Show the "View the Artifact" button, hide skip
        await delay(T.CONTINUE);
        document.getElementById('btn-to-screen2').style.opacity = '1';
        document.getElementById('btn-to-screen2').style.pointerEvents = 'auto';
        var skipBtn = document.getElementById('btn-skip');
        if (skipBtn) skipBtn.style.display = 'none';
    }

    document.addEventListener('DOMContentLoaded', function() {
        // ── "Click to begin" gate for Web Audio ──
        var startScreen = document.createElement('div');
        startScreen.style.cssText = 'position:fixed;inset:0;z-index:999999;background:#000;display:flex;align-items:center;justify-content:center;cursor:pointer;';
        startScreen.innerHTML = '<div style="text-align:center;">' +
            '<div style="font-size:14px;letter-spacing:3px;text-transform:uppercase;color:rgba(255,255,255,0.3);margin-bottom:16px;">ARIA has detected an anomaly</div>' +
            '<div style="font-size:20px;color:rgba(168,85,247,0.8);font-weight:600;margin-bottom:24px;">Click anywhere to continue</div>' +
            '<div style="font-size:12px;color:rgba(255,255,255,0.2);letter-spacing:1px;">Turn your sound up for the full experience</div>' +
            '</div>';
        document.body.appendChild(startScreen);

        startScreen.addEventListener('click', function() {
            if (audio.init) audio.init();
            startScreen.style.transition = 'opacity 0.5s ease';
            startScreen.style.opacity = '0';
            setTimeout(function() {
                startScreen.remove();
                document.documentElement.classList.add('first-contact-active');
                showScreen('screen1');
                runCinematic();
            }, 500);
        }, { once: true });

        // ── Skip button ──
        document.getElementById('btn-skip').addEventListener('click', skipCinematic);

        // ── Screen navigation buttons ──
        document.getElementById('btn-to-screen2').addEventListener('click', function() { showScreen('screen2'); });
        document.getElementById('btn-to-screen3').addEventListener('click', function() { showScreen('screen3'); });
        document.getElementById('btn-to-screen4').addEventListener('click', function() { showScreen('screen4'); });

        // ── Final "Continue to Colony" — bond already completed on page load ──
        document.getElementById('btn-final').addEventListener('click', async function() {
            var btn = document.getElementById('btn-final');
            btn.style.pointerEvents = 'none';
            if (audio.fadeOutAll) audio.fadeOutAll(1.5);
            document.getElementById('screen4').style.transition = 'opacity 1.5s ease';
            document.getElementById('screen4').style.opacity = '0';
            await delay(1500);
            window.location.href = '/';
        });
    });
})();
