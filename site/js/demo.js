/* ============================================
   SPACE SHOOTER — Playable browser demo
   Same sprites & mechanics as the pygame game
   ============================================ */
(() => {
    'use strict';

    const canvas = document.getElementById('game');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const W = canvas.width, H = canvas.height;

    const overlay   = document.getElementById('overlay');
    const startBtn  = document.getElementById('start-btn');
    const titleEl   = document.getElementById('overlay-title');
    const textEl    = document.getElementById('overlay-text');
    const scoreEl   = document.getElementById('hud-score');
    const bestEl    = document.getElementById('hud-best');
    const godEl     = document.getElementById('hud-god');

    const IMG = 'assets/img/';
    const keys = {};
    // Local best (guest); account best shown when logged in via __ss
    let best = +(localStorage.getItem('ss_best') || 0);
    bestEl.textContent = best;

    function currentBest() {
        const ss = window.__ss;
        if (ss && ss.getCurrent()) {
            try {
                const st = JSON.parse(localStorage.getItem('ss_stats')) || {};
                const u = st[ss.getCurrent().name];
                if (u) return u.best;
            } catch {}
        }
        return best;
    }
    function refreshBest() { bestEl.textContent = currentBest(); }
    refreshBest();

    /* --- Assets --- */
    const assets = { bg: null, player: null, laser: null, meteors: [] };
    let loaded = 0, total = 0;

    function load(src, cb) {
        total++;
        const im = new Image();
        im.onload = im.onerror = () => { if (++loaded === total) ready = true; };
        im.src = src;
        im.addEventListener('load', () => cb(im));
    }

    let ready = false;
    load(IMG + 'bg-nebula.png',    im => assets.bg = im);
    load(IMG + 'player.png',       im => assets.player = im);
    load(IMG + 'laser/laserRed07.png', im => assets.laser = im);
    for (let i = 1; i <= 20; i++) {
        const slot = i - 1;
        assets.meteors.push(null);
        load(IMG + `meteors/${i}.png`, im => assets.meteors[slot] = im);
    }

    /* --- Game state --- */
    let running = false, score = 0, god = false, raf = 0;
    let player, meteors, lasers, lastShot, lastTs;

    function reset() {
        score = 0; god = false;
        scoreEl.textContent = '0';
        godEl.classList.add('hidden');
        player = { x: W / 2, y: H - 45, w: 50, h: 50, speed: 480, r: 12 };
        lasers = [];
        lastShot = 0;
        meteors = Array.from({ length: 9 }, () => spawnMeteor());
    }

    function spawnMeteor() {
        const im = assets.meteors[Math.floor(Math.random() * assets.meteors.length)];
        if (!im) return { x: Math.random() * W, y: -80, w: 40, h: 40,
                          vx: rnd(-150, 150), vy: rnd(60, 320),
                          rot: 0, vrot: rnd(-120, 120), img: null, r: 20 };
        const w = im.width, h = im.height;
        return {
            x: Math.random() * (W - w), y: -h - 20, w, h,
            vx: rnd(-150, 150), vy: rnd(60, 320),
            rot: 0, vrot: rnd(-120, 120),
            img: im, r: Math.max(w, h) * 0.36
        };
    }

    const rnd = (a, b) => a + Math.random() * (b - a);

    /* --- Loop --- */
    function loop(ts) {
        if (!running) return;
        const dt = Math.min((ts - (lastTs || ts)) / 1000, 0.05);
        lastTs = ts;
        update(dt, ts);
        draw();
        raf = requestAnimationFrame(loop);
    }

    function update(dt, ts) {
        // player
        player.x += ((keys.ArrowRight || keys.KeyD) ? 1 : 0) * player.speed * dt;
        player.x -= ((keys.ArrowLeft  || keys.KeyA) ? 1 : 0) * player.speed * dt;
        if (player.x < -player.w / 2) player.x = W + player.w / 2;      // wrap like pygame
        if (player.x > W + player.w / 2) player.x = -player.w / 2;

        // shoot (delay 100 ms like the original)
        if (keys.Space && ts - lastShot > 100) {
            lastShot = ts;
            lasers.push({ x: player.x, y: player.y - 40, vy: -820 });
        }
        lasers = lasers.filter(l => (l.y += l.vy * dt) > -30);

        // meteors
        for (const m of meteors) {
            m.x += m.vx * dt;
            m.y += m.vy * dt;
            m.rot += m.vrot * dt;
            if (m.y > H + 40) Object.assign(m, spawnMeteor(), { y: -m.h - 20 });
            if (m.x > W + 50) m.x = -m.w - 10;
            if (m.x < -m.w - 50) m.x = W + 10;
        }

        // bullet vs meteor
        for (let i = lasers.length - 1; i >= 0; i--) {
            const l = lasers[i];
            for (const m of meteors) {
                const cx = m.x + m.w / 2, cy = m.y + m.h / 2;
                if (Math.hypot(l.x - cx, l.y - cy) < m.r + 6) {
                    lasers.splice(i, 1);
                    Object.assign(m, spawnMeteor());
                    score++;
                    scoreEl.textContent = score;
                    break;
                }
            }
        }

        // meteor vs player
        if (!god) {
            for (const m of meteors) {
                const cx = m.x + m.w / 2, cy = m.y + m.h / 2;
                if (Math.hypot(player.x - cx, player.y - cy) < m.r + player.r) return gameOver();
            }
        }
    }

    function draw() {
        if (assets.bg) {
            ctx.drawImage(assets.bg, 0, 0, W, H);
        } else {
            ctx.fillStyle = '#0a0a1a';
            ctx.fillRect(0, 0, W, H);
        }
        for (const m of meteors) {
            if (!m.img) continue;
            ctx.save();
            ctx.translate(m.x + m.w / 2, m.y + m.h / 2);
            ctx.rotate(m.rot * Math.PI / 180);
            ctx.drawImage(m.img, -m.w / 2, -m.h / 2);
            ctx.restore();
        }
        if (assets.laser) for (const l of lasers) ctx.drawImage(assets.laser, l.x - 5, l.y - 8);
        if (assets.player) {
            if (god) { ctx.save(); ctx.shadowColor = '#00d4ff'; ctx.shadowBlur = 25; }
            ctx.drawImage(assets.player, player.x - assets.player.width / 2,
                          player.y - assets.player.height / 2);
            if (god) ctx.restore();
        }
        // score, like the original game
        ctx.font = '45px Calibri, Arial, sans-serif';
        ctx.fillStyle = '#fff';
        ctx.fillText('Score:' + score, 15, 55);
    }

    /* --- State transitions --- */
    function start() {
        if (!ready) { setTimeout(start, 100); return; }
        reset();
        overlay.classList.add('hidden');
        running = true;
        lastTs = 0;
        cancelAnimationFrame(raf);
        raf = requestAnimationFrame(loop);
    }

    function gameOver() {
        running = false;
        // Record to account (if logged in) or local best (guest)
        if (window.__ss && window.__ss.getCurrent()) {
            window.__ss.recordGame(score);
        } else if (score > best) {
            best = score;
            localStorage.setItem('ss_best', best);
        }
        refreshBest();
        document.dispatchEvent(new CustomEvent('ss:score', { detail: { score } }));
        titleEl.textContent = 'Игра окончена';
        textEl.innerHTML = `Счёт: <b>${score}</b> · Рекорд: <b>${currentBest()}</b><br>Нажми «Играть», чтобы вернуться в бой`;
        startBtn.textContent = 'Играть снова';
        overlay.classList.remove('hidden');
        if (document.fullscreenElement) document.exitFullscreen();
    }

    /* --- Input --- */
    window.addEventListener('keydown', e => {
        if (['ArrowLeft', 'ArrowRight', 'Space'].includes(e.code)) {
            // scroll page only if demo is not in focus area
            if (isDemoVisible()) e.preventDefault();
        }
        keys[e.code] = true;
        if (running && e.code === 'Digit9') {           // God mode, like the original
            god = true;
            godEl.classList.remove('hidden');
        }
        if (running && e.code === 'Digit0') {
            god = false;
            godEl.classList.add('hidden');
        }
    });
    window.addEventListener('keyup', e => { keys[e.code] = false; });
    startBtn.addEventListener('click', start);

    function isDemoVisible() {
        const r = canvas.getBoundingClientRect();
        return r.top < innerHeight * 0.75 && r.bottom > innerHeight * 0.25;
    }

    /* --- Touch controls (mobile): drag = move, touch = fire --- */
    let touchX = null;
    canvas.addEventListener('touchstart', e => {
        e.preventDefault();
        if (!running) return;
        touchX = e.touches[0].clientX;
        keys.Space = true;
    }, { passive: false });
    canvas.addEventListener('touchmove', e => {
        e.preventDefault();
        if (!running || touchX === null) return;
        const dx = e.touches[0].clientX - touchX;
        touchX = e.touches[0].clientX;
        player.x += dx * (W / canvas.getBoundingClientRect().width);
    }, { passive: false });
    canvas.addEventListener('touchend', () => { touchX = null; keys.Space = false; });

    /* --- Fullscreen (Fullscreen API on the demo frame) --- */
    const frame = document.getElementById('demo-frame');
    const fsBtn = document.getElementById('fullscreen-btn');

    function toggleFullscreen() {
        if (document.fullscreenElement) {
            document.exitFullscreen();
        } else if (frame.requestFullscreen) {
            frame.requestFullscreen().catch(() => {});
        }
    }
    fsBtn.addEventListener('click', e => {
        e.stopPropagation();
        toggleFullscreen();
    });
    document.addEventListener('fullscreenchange', () => {
        const on = !!document.fullscreenElement;
        fsBtn.textContent = on ? '✕' : '⛶';
        fsBtn.title = on ? 'Выйти из полного экрана' : 'На весь экран';
        frame.classList.toggle('is-fullscreen', on);
        if (on && running === false && overlay.classList.contains('hidden') === false) {
            // still on start screen — keep overlay, just resized
        }
    });
    // Double click on canvas toggles fullscreen too
    canvas.addEventListener('dblclick', toggleFullscreen);
})();
