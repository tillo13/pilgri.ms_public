/**
 * Signal Claim Cinematic — Phase 2.3b
 * 3-screen experience: Approach → Discovery → Aftermath
 * Mirrors static/js/first-contact.js (ARIA Bond reveal). Reuses window.FCaudio.
 */
(function() {
    'use strict';

    var data = JSON.parse(document.getElementById('scPageData').textContent);
    var CLAIM = data.claim;
    var APPROACH_LINES = data.approachLines || [];
    var REPLAY = data.replay || false;
    var audio = window.FCaudio || {};

    var T = {
        DUST_FADE: 500, HORIZON: 1500, FIRST_LINE: 2500,
        LINE_GAP: 2200, REVEAL: 1500, CONTINUE: 1500
    };

    var skipped = false;

    function $(sel) { return document.querySelector(sel); }
    function delay(ms) {
        return new Promise(function(r) {
            if (skipped) { r(); return; }
            setTimeout(r, ms);
        });
    }

    function skipCinematic() {
        skipped = true;
        var s1 = document.getElementById('screen1');
        s1.querySelector('.sc-dust').classList.add('visible');
        s1.querySelector('.sc-horizon').classList.add('visible');
        var btn = document.getElementById('btn-to-screen2');
        btn.style.opacity = '1';
        btn.style.pointerEvents = 'auto';
        var skipBtn = document.getElementById('btn-skip');
        if (skipBtn) skipBtn.style.display = 'none';
    }

    function showScreen(id) {
        document.querySelectorAll('.fc-screen').forEach(function(s) {
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

    async function runCinematic() {
        if (audio.startAmbientDrone) audio.startAmbientDrone();
        await delay(T.DUST_FADE);
        $('.sc-dust').classList.add('visible');
        $('.sc-horizon').classList.add('visible');

        await delay(T.HORIZON);
        if (audio.playOrbAppear) audio.playOrbAppear();

        await delay(T.FIRST_LINE);
        var textArea = $('.fc-text-area');

        for (var i = 0; i < APPROACH_LINES.length; i++) {
            var line = APPROACH_LINES[i];
            var el = document.createElement('div');
            el.className = 'fc-line' + (line.cls ? ' ' + line.cls : '');
            el.textContent = line.text;
            textArea.appendChild(el);
            await delay(80);
            el.classList.add('visible');

            if (line.sound === 'crackle' && audio.playStaticCrackle) audio.playStaticCrackle(1.8);
            else if (line.sound === 'glitch' && audio.playGlitch) audio.playGlitch();
            else if (audio.playLineReveal) audio.playLineReveal();

            await delay(T.LINE_GAP);
        }

        await delay(T.REVEAL);
        if (audio.playBondReveal) audio.playBondReveal();

        await delay(T.CONTINUE);
        document.getElementById('btn-to-screen2').style.opacity = '1';
        document.getElementById('btn-to-screen2').style.pointerEvents = 'auto';
        var skipBtn = document.getElementById('btn-skip');
        if (skipBtn) skipBtn.style.display = 'none';
    }

    document.addEventListener('DOMContentLoaded', function() {
        // ── Click-to-begin gate (Web Audio requires user gesture) ──
        var startScreen = document.createElement('div');
        startScreen.style.cssText = 'position:fixed;inset:0;z-index:999999;background:#000;display:flex;align-items:center;justify-content:center;cursor:pointer;';
        startScreen.innerHTML = '<div style="text-align:center;">' +
            '<div style="font-size:14px;letter-spacing:3px;text-transform:uppercase;color:rgba(255,255,255,0.3);margin-bottom:16px;">A signal has been claimed</div>' +
            '<div style="font-size:20px;color:rgba(255,170,80,0.85);font-weight:600;margin-bottom:24px;">Click anywhere to begin</div>' +
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

        document.getElementById('btn-skip').addEventListener('click', skipCinematic);
        document.getElementById('btn-to-screen2').addEventListener('click', function() { showScreen('screen2'); });
        document.getElementById('btn-to-screen3').addEventListener('click', function() { showScreen('screen3'); });

        document.getElementById('btn-final').addEventListener('click', async function() {
            var btn = document.getElementById('btn-final');
            btn.style.pointerEvents = 'none';
            if (audio.fadeOutAll) audio.fadeOutAll(1.5);
            document.getElementById('screen3').style.transition = 'opacity 1.5s ease';
            document.getElementById('screen3').style.opacity = '0';
            await delay(1500);
            window.location.href = '/';
        });
    });
})();
