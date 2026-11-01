/* ============================================
   SPACE SHOOTER — Account System
   Registration, login, profile, leaderboard
   All data stored in localStorage (no server)
   ============================================ */
(() => {
    'use strict';

    /* --- Storage helpers --- */
    const DB_KEY = 'ss_accounts';
    const STATS_KEY = 'ss_stats';

    function loadAccounts() {
        try { return JSON.parse(localStorage.getItem(DB_KEY)) || {}; } catch { return {}; }
    }
    function saveAccounts(acc) {
        localStorage.setItem(DB_KEY, JSON.stringify(acc));
    }

    /* --- Simple hash (not crypto, but enough for this) --- */
    function hash(str) {
        let h = 0;
        for (let i = 0; i < str.length; i++) {
            h = ((h << 5) - h) + str.charCodeAt(i);
            h |= 0;
        }
        return 'h' + Math.abs(h).toString(36);
    }

    /* --- UI elements --- */
    const profileBtn = document.getElementById('profile-btn');
    const modal = document.getElementById('auth-modal');
    const formsEl = document.getElementById('auth-forms');
    const profileEl = document.getElementById('auth-profile');
    const loginForm = document.getElementById('login-form');
    const regForm = document.getElementById('register-form');
    const tabLogin = document.getElementById('tab-login');
    const tabReg = document.getElementById('tab-register');
    const loginError = document.getElementById('login-error');
    const regError = document.getElementById('reg-error');

    /* --- Current session --- */
    let currentSession = null; // { name, created }

    function getSession() {
        try { return JSON.parse(sessionStorage.getItem('ss_session')); } catch { return null; }
    }
    function saveSession(s) {
        sessionStorage.setItem('ss_session', JSON.stringify(s));
    }
    function clearSession() {
        sessionStorage.removeItem('ss_session');
        currentSession = null;
    }

    /* --- Stats storage --- */
    function loadStats() {
        try { return JSON.parse(localStorage.getItem(STATS_KEY)) || {}; } catch { return {}; }
    }
    function saveStats(st) {
        localStorage.setItem(STATS_KEY, JSON.stringify(st));
    }
    function recordGame(score) {
        if (!currentSession) return;
        const st = loadStats();
        const u = st[currentSession.name] || { best: 0, games: 0, kills: 0 };
        u.best = Math.max(u.best, score);
        u.games++;
        u.kills += score;
        st[currentSession.name] = u;
        saveStats(st);
    }

    /* --- Open / close modal --- */
    function openModal() {
        modal.classList.remove('hidden');
        document.body.style.overflow = 'hidden';
        refreshUI();
    }
    function closeModal() {
        modal.classList.add('hidden');
        document.body.style.overflow = '';
    }

    /* --- Refresh UI based on session --- */
    function refreshUI() {
        const session = getSession();
        const accounts = loadAccounts();
        const btn = profileBtn;

        if (session && accounts[session.name]) {
            btn.textContent = '👤 ' + session.name;
            btn.setAttribute('data-logged', '1');
            currentSession = session;
            formsEl.classList.add('hidden');
            profileEl.classList.remove('hidden');
            document.getElementById('profile-name').textContent = session.name;
            document.getElementById('profile-avatar').textContent = session.name[0].toUpperCase();
            document.getElementById('profile-since').textContent = 'С ' + new Date(accounts[session.name].created).toLocaleDateString('ru-RU');

            const st = loadStats();
            const u = st[session.name] || { best: 0, games: 0, kills: 0 };
            document.getElementById('stat-best').textContent = u.best;
            document.getElementById('stat-games').textContent = u.games;
            document.getElementById('stat-kills').textContent = u.kills;

            // rank
            const all = Object.entries(st).map(([n, s]) => ({ name: n, best: s.best }));
            all.sort((a, b) => b.best - a.best);
            const rank = all.findIndex(x => x.name === session.name) + 1;
            document.getElementById('profile-rank').textContent = rank ? `Ранг: #${rank} из ${all.length}` : '';
        } else {
            btn.textContent = '👤 Войти';
            btn.removeAttribute('data-logged');
            currentSession = null;
            formsEl.classList.remove('hidden');
            profileEl.classList.add('hidden');
            loginForm.classList.remove('hidden');
            regForm.classList.add('hidden');
            tabLogin.classList.add('active');
            tabReg.classList.remove('active');
            loginError.textContent = '';
            regError.textContent = '';
        }

        updateLeaderboard();
        updateHUD();
    }

    /* --- Leaderboard --- */
    function updateLeaderboard() {
        const st = loadStats();
        const body = document.getElementById('lb-body');
        const empty = document.getElementById('lb-empty');
        const entries = Object.entries(st)
            .map(([n, s]) => ({ name: n, best: s.best }))
            .sort((a, b) => b.best - a.best)
            .slice(0, 10);

        body.innerHTML = '';
        if (entries.length === 0) {
            empty.style.display = '';
            return;
        }
        empty.style.display = 'none';

        const medals = ['🥇', '🥈', '🥉'];
        entries.forEach((e, i) => {
            const tr = document.createElement('div');
            tr.className = 'lb-row' + (currentSession && currentSession.name === e.name ? ' lb-row-current' : '');
            tr.innerHTML = `<span>${i < 3 ? medals[i] : (i + 1)}</span><span>${esc(e.name)}</span><span>${e.best}</span>`;
            body.appendChild(tr);
        });
    }

    function updateHUD() {
        const nameEl = document.getElementById('hud-name');
        if (nameEl) nameEl.textContent = currentSession ? currentSession.name : 'Гость';
    }

    function esc(s) {
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }

    /* --- Tabs --- */
    tabLogin.addEventListener('click', () => {
        tabLogin.classList.add('active');
        tabReg.classList.remove('active');
        loginForm.classList.remove('hidden');
        regForm.classList.add('hidden');
        loginError.textContent = '';
    });
    tabReg.addEventListener('click', () => {
        tabReg.classList.add('active');
        tabLogin.classList.remove('active');
        regForm.classList.remove('hidden');
        loginForm.classList.add('hidden');
        regError.textContent = '';
    });

    /* --- Login --- */
    loginForm.addEventListener('submit', e => {
        e.preventDefault();
        const name = document.getElementById('login-name').value.trim();
        const pass = document.getElementById('login-pass').value;
        loginError.textContent = '';

        if (!name || !pass) { loginError.textContent = 'Заполни все поля'; return; }

        const accounts = loadAccounts();
        if (!accounts[name]) { loginError.textContent = 'Аккаунт не найден'; return; }
        if (hash(pass) !== accounts[name].pass) { loginError.textContent = 'Неверный пароль'; return; }

        saveSession({ name, created: accounts[name].created });
        closeModal();
    });

    /* --- Register --- */
    regForm.addEventListener('submit', e => {
        e.preventDefault();
        const name = document.getElementById('reg-name').value.trim();
        const pass = document.getElementById('reg-pass').value;
        const pass2 = document.getElementById('reg-pass2').value;
        regError.textContent = '';

        if (name.length < 3 || name.length > 20) { regError.textContent = 'Ник: 3–20 символов'; return; }
        if (pass.length < 6) { regError.textContent = 'Пароль: минимум 6 символов'; return; }
        if (pass !== pass2) { regError.textContent = 'Пароли не совпадают'; return; }
        if (!/^[a-zA-Zа-яА-ЯёЁ0-9_]+$/.test(name)) { regError.textContent = 'Только буквы, цифры и _'; return; }

        const accounts = loadAccounts();
        if (accounts[name]) { regError.textContent = 'Этот ник уже занят'; return; }

        accounts[name] = { pass: hash(pass), created: Date.now() };
        saveAccounts(accounts);

        saveSession({ name, created: accounts[name].created });
        closeModal();
    });

    /* --- Logout --- */
    document.getElementById('logout-btn').addEventListener('click', () => {
        clearSession();
        refreshUI();
    });

    /* --- Close modal --- */
    modal.querySelectorAll('[data-close]').forEach(el => {
        el.addEventListener('click', closeModal);
    });
    modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && !modal.classList.contains('hidden')) closeModal(); });

    /* --- Profile button --- */
    profileBtn.addEventListener('click', () => {
        if (profileBtn.getAttribute('data-logged') === '1') {
            // Already logged in — open modal to profile
            refreshUI();
            openModal();
        } else {
            openModal();
        }
    });

    /* --- Init --- */
    refreshUI();

    /* --- Expose for demo.js --- */
    window.__ss = {
        getCurrent: () => currentSession,
        recordGame,
        getSession,
        refreshUI,
        updateLeaderboard
    };

    /* --- Listen for game-over events --- */
    document.addEventListener('ss:score', e => {
        updateLeaderboard();
    });
})();
