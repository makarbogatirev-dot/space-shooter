/* ============================================
   SPACE SHOOTER — Account System (server-backed)
   Регистрация, вход, профиль и таблица лидеров
   работают через API сервера аккаунтов.
   Пароли хэшируются на сервере (PBKDF2-SHA256).
   ============================================ */
(() => {
    'use strict';

    /* --- Адрес API ---
       Если сайт открыт с сервера аккаунтов — используем тот же origin.
       Для статического хостинга задайте window.SS_API_BASE до подключения auth.js. */
    const API_BASE = (window.SS_API_BASE !== undefined
        ? String(window.SS_API_BASE)
        : (location.protocol === 'file:' ? 'http://127.0.0.1:8735' : '')
    ).replace(/\/+$/, '');

    const TOKEN_KEY = 'ss_token';

    /* --- Состояние --- */
    let user = null;      // { name, created, best, games, kills, rank, total }
    let token = localStorage.getItem(TOKEN_KEY) || '';
    let busy = false;

    /* --- UI элементы --- */
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
    const adminBtn = document.getElementById('admin-btn');

    /* --- Сетевой слой --- */
    async function api(path, { method = 'GET', body, auth = true } = {}) {
        const headers = {};
        if (body !== undefined) headers['Content-Type'] = 'application/json';
        if (auth && token) headers['Authorization'] = 'Bearer ' + token;

        let res;
        try {
            res = await fetch(API_BASE + path, {
                method,
                headers,
                body: body === undefined ? undefined : JSON.stringify(body)
            });
        } catch {
            throw new Error('Сервер аккаунтов недоступен');
        }

        let data = {};
        let isJson = false;
        try {
            data = await res.json();
            isJson = true;
        } catch { /* пустой или не-JSON ответ */ }

        if (!res.ok) {
            if (res.status === 401 && auth && token) clearToken();
            if (!isJson && (res.status === 404 || res.status === 405)) {
                // Статический хостинг (GitHub Pages) отвечает HTML-страницей 404.
                throw new Error('Сервер аккаунтов не подключён — укажите адрес API в js/config.js');
            }
            throw new Error(data.error || 'Ошибка сервера (' + res.status + ')');
        }
        return data;
    }

    function clearToken() {
        token = '';
        localStorage.removeItem(TOKEN_KEY);
    }

    function setToken(t) {
        token = t || '';
        if (token) localStorage.setItem(TOKEN_KEY, token);
        else localStorage.removeItem(TOKEN_KEY);
    }

    /* --- Модалка --- */
    function openModal() {
        modal.classList.remove('hidden');
        document.body.style.overflow = 'hidden';
        refreshUI();
    }
    function closeModal() {
        modal.classList.add('hidden');
        document.body.style.overflow = '';
    }

    /* --- Отрисовка --- */
    function refreshUI() {
        if (user) {
            profileBtn.textContent = '👤 ' + user.name;
            profileBtn.setAttribute('data-logged', '1');
            formsEl.classList.add('hidden');
            profileEl.classList.remove('hidden');

            document.getElementById('profile-name').textContent = user.name;
            document.getElementById('profile-avatar').textContent = user.name[0].toUpperCase();
            document.getElementById('profile-since').textContent =
                'С ' + new Date(user.created).toLocaleDateString('ru-RU');
            document.getElementById('stat-best').textContent = user.best;
            document.getElementById('stat-games').textContent = user.games;
            document.getElementById('stat-kills').textContent = user.kills;
            document.getElementById('profile-rank').textContent =
                user.rank && user.total ? `Ранг: #${user.rank} из ${user.total}` : '';
            adminBtn.classList.toggle('hidden', !user.admin);
        } else {
            profileBtn.textContent = '👤 Войти';
            profileBtn.removeAttribute('data-logged');
            formsEl.classList.remove('hidden');
            profileEl.classList.add('hidden');
            loginForm.classList.remove('hidden');
            regForm.classList.add('hidden');
            tabLogin.classList.add('active');
            tabReg.classList.remove('active');
            loginError.textContent = '';
            regError.textContent = '';
        }

        updateHUD();
        document.dispatchEvent(new CustomEvent('ss:auth', { detail: { user } }));
    }

    function updateHUD() {
        const nameEl = document.getElementById('hud-name');
        if (nameEl) nameEl.textContent = user ? user.name : 'Гость';
        const bestEl = document.getElementById('hud-best');
        if (bestEl) bestEl.textContent = user ? user.best : (localStorage.getItem('ss_best') || 0);
    }

    /* --- Таблица лидеров --- */
    async function updateLeaderboard() {
        const body = document.getElementById('lb-body');
        const empty = document.getElementById('lb-empty');
        if (!body) return;

        let entries = [];
        try {
            const data = await api('/api/leaderboard?limit=10', { auth: false });
            entries = data.entries || [];
        } catch (err) {
            body.innerHTML = '';
            empty.style.display = '';
            empty.textContent = err.message;
            return;
        }

        body.innerHTML = '';
        if (entries.length === 0) {
            empty.style.display = '';
            empty.textContent = 'Пока нет рекордов. Стань первым!';
            return;
        }
        empty.style.display = 'none';

        const medals = ['🥇', '🥈', '🥉'];
        entries.forEach((e, i) => {
            const row = document.createElement('div');
            row.className = 'lb-row' + (user && user.name === e.name ? ' lb-row-current' : '');
            const place = document.createElement('span');
            place.textContent = i < 3 ? medals[i] : String(i + 1);
            const nick = document.createElement('span');
            nick.textContent = e.name;
            const score = document.createElement('span');
            score.textContent = e.best;
            row.append(place, nick, score);
            body.appendChild(row);
        });
    }

    /* --- Вкладки --- */
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

    /* --- Вход --- */
    loginForm.addEventListener('submit', async e => {
        e.preventDefault();
        if (busy) return;
        const name = document.getElementById('login-name').value.trim();
        const pass = document.getElementById('login-pass').value;
        loginError.textContent = '';
        if (!name || !pass) { loginError.textContent = 'Заполни все поля'; return; }

        const btn = loginForm.querySelector('button[type=submit]');
        busy = true; btn.disabled = true; btn.textContent = 'Входим…';
        try {
            const data = await api('/api/login', {
                method: 'POST', body: { name, password: pass }, auth: false
            });
            setToken(data.token);
            user = data.user;
            loginForm.reset();
            closeModal();
            refreshUI();
            updateLeaderboard();
        } catch (err) {
            loginError.textContent = err.message;
        } finally {
            busy = false; btn.disabled = false; btn.textContent = 'Войти';
        }
    });

    /* --- Регистрация --- */
    regForm.addEventListener('submit', async e => {
        e.preventDefault();
        if (busy) return;
        const name = document.getElementById('reg-name').value.trim();
        const pass = document.getElementById('reg-pass').value;
        const pass2 = document.getElementById('reg-pass2').value;
        regError.textContent = '';

        if (name.length < 3 || name.length > 20) { regError.textContent = 'Ник: 3–20 символов'; return; }
        if (!/^[a-zA-Zа-яА-ЯёЁ0-9_]+$/.test(name)) { regError.textContent = 'Только буквы, цифры и _'; return; }
        if (pass.length < 6) { regError.textContent = 'Пароль: минимум 6 символов'; return; }
        if (pass !== pass2) { regError.textContent = 'Пароли не совпадают'; return; }

        const btn = regForm.querySelector('button[type=submit]');
        busy = true; btn.disabled = true; btn.textContent = 'Создаём…';
        try {
            const data = await api('/api/register', {
                method: 'POST', body: { name, password: pass }, auth: false
            });
            setToken(data.token);
            user = data.user;
            regForm.reset();
            closeModal();
            refreshUI();
            updateLeaderboard();
        } catch (err) {
            regError.textContent = err.message;
        } finally {
            busy = false; btn.disabled = false; btn.textContent = 'Создать аккаунт';
        }
    });

    /* --- Выход --- */
    document.getElementById('logout-btn').addEventListener('click', async () => {
        const t = token;
        clearToken();
        user = null;
        refreshUI();
        if (t) {
            try {
                await fetch(API_BASE + '/api/logout', {
                    method: 'POST', headers: { Authorization: 'Bearer ' + t }
                });
            } catch { /* сессия истечёт сама */ }
        }
    });

    /* --- Закрытие модалки --- */
    modal.querySelectorAll('[data-close]').forEach(el => el.addEventListener('click', closeModal));
    modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });
    document.addEventListener('keydown', e => {
        if (e.key !== 'Escape') return;
        if (!adminEditModal.classList.contains('hidden')) { adminEditModal.classList.add('hidden'); return; }
        if (!adminModal.classList.contains('hidden')) { closeAdminModals(); return; }
        if (!modal.classList.contains('hidden')) closeModal();
    });

    profileBtn.addEventListener('click', openModal);

    /* --- Запись очков --- */
    async function recordGame(score) {
        if (!user) return;
        try {
            const data = await api('/api/score', { method: 'POST', body: { score } });
            user = data.user;
            refreshUI();
            updateLeaderboard();
        } catch (err) {
            console.warn('Не удалось сохранить очки:', err.message);
        }
    }

    /* --- Инициализация --- */
    (async function init() {
        if (token) {
            try {
                const data = await api('/api/me');
                user = data.user;
            } catch {
                clearToken();
                user = null;
            }
        }
        refreshUI();
        updateLeaderboard();
    })();

    /* ============================================
       ПАНЕЛЬ РАЗРАБОТЧИКА
       ============================================ */
    const adminModal = document.getElementById('admin-modal');
    const adminEditModal = document.getElementById('admin-edit-modal');
    const adminStatsEl = document.getElementById('admin-stats');
    const adminSearch = document.getElementById('admin-search');
    const adminUsersEl = document.getElementById('admin-users');
    const adminEmpty = document.getElementById('admin-empty');
    const adminError = document.getElementById('admin-error');
    const editTitle = document.getElementById('admin-edit-title');
    let adminTarget = null;   // ник редактируемого игрока
    let searchTimer = null;

    function openAdminModal() {
        adminModal.classList.remove('hidden');
        adminError.textContent = '';
        loadAdminStats();
        loadAdminUsers();
        loadAdminBans();
    }
    function closeAdminModals() {
        adminModal.classList.add('hidden');
        adminEditModal.classList.add('hidden');
    }
    adminBtn.addEventListener('click', openAdminModal);
    adminModal.querySelectorAll('[data-close]').forEach(el => el.addEventListener('click', closeAdminModals));
    adminModal.addEventListener('click', e => { if (e.target === adminModal) closeAdminModals(); });
    adminEditModal.querySelectorAll('[data-close]').forEach(el => el.addEventListener('click', () => adminEditModal.classList.add('hidden')));
    adminEditModal.addEventListener('click', e => { if (e.target === adminEditModal) adminEditModal.classList.add('hidden'); });

    async function loadAdminStats() {
        try {
            const s = await api('/api/admin/stats');
            adminStatsEl.innerHTML = '';
            const cells = [
                [s.users, 'игроков'],
                [s.sessions, 'сессий'],
                [s.games, 'игр всего'],
                [s.kills, 'метеоритов'],
                [s.best, 'топ рекорд']
            ];
            for (const [value, label] of cells) {
                const el = document.createElement('div');
                el.className = 'admin-stat';
                const v = document.createElement('b');
                v.textContent = value;
                const l = document.createElement('span');
                l.textContent = label;
                el.append(v, l);
                adminStatsEl.appendChild(el);
            }
        } catch (err) {
            adminError.textContent = err.message;
        }
    }

    async function loadAdminUsers() {
        adminError.textContent = '';
        adminUsersEl.innerHTML = '';
        const q = adminSearch.value.trim();
        let users = [];
        try {
            const data = await api('/api/admin/users?q=' + encodeURIComponent(q));
            users = data.users || [];
        } catch (err) {
            adminEmpty.textContent = err.message;
            adminEmpty.style.display = '';
            return;
        }
        if (!users.length) {
            adminEmpty.textContent = 'Никого не найдено';
            adminEmpty.style.display = '';
            return;
        }
        adminEmpty.style.display = 'none';
        for (const u of users) {
            const tr = document.createElement('tr');
            const name = document.createElement('td');
            name.textContent = u.name + (u.admin ? ' ⚙' : '');
            const best = document.createElement('td'); best.textContent = u.best;
            const games = document.createElement('td'); games.textContent = u.games;
            const kills = document.createElement('td'); kills.textContent = u.kills;
            const since = document.createElement('td');
            since.textContent = new Date(u.created).toLocaleDateString('ru-RU');
            const ip = document.createElement('td');
            ip.textContent = u.banned ? '🚫 ' + (u.ip || '') : (u.ip || '—');
            const act = document.createElement('td');
            const edit = document.createElement('button');
            edit.type = 'button';
            edit.className = 'admin-row-edit';
            edit.textContent = 'Изменить';
            edit.addEventListener('click', () => openAdminEdit(u));
            act.appendChild(edit);
            tr.append(name, best, games, kills, since, ip, act);
            adminUsersEl.appendChild(tr);
        }
    }

    async function loadAdminBans() {
        const bansEl = document.getElementById('admin-bans');
        const bansEmpty = document.getElementById('admin-bans-empty');
        bansEl.innerHTML = '';
        let bans = [];
        try {
            const data = await api('/api/admin/bans');
            bans = data.bans || [];
        } catch (err) {
            bansEmpty.textContent = err.message;
            bansEmpty.style.display = '';
            return;
        }
        if (!bans.length) {
            bansEmpty.textContent = 'Блокировок нет';
            bansEmpty.style.display = '';
            return;
        }
        bansEmpty.style.display = 'none';
        for (const b of bans) {
            const tr = document.createElement('tr');
            const ip = document.createElement('td'); ip.textContent = b.ip;
            const reason = document.createElement('td'); reason.textContent = b.reason || '—';
            const by = document.createElement('td'); by.textContent = b.by || '—';
            const until = document.createElement('td');
            until.textContent = b.expires
                ? new Date(b.expires).toLocaleDateString('ru-RU')
                : 'навсегда';
            const users = document.createElement('td');
            users.textContent = (b.users || []).join(', ') || '—';
            const act = document.createElement('td');
            const unban = document.createElement('button');
            unban.type = 'button';
            unban.className = 'admin-row-edit';
            unban.textContent = 'Разбанить';
            unban.addEventListener('click', async () => {
                try {
                    await api('/api/admin/unban', { method: 'POST', body: { ip: b.ip } });
                    loadAdminBans();
                    loadAdminUsers();
                } catch (err) {
                    adminError.textContent = err.message;
                }
            });
            act.appendChild(unban);
            tr.append(ip, reason, by, until, users, act);
            bansEl.appendChild(tr);
        }
    }

    adminSearch.addEventListener('input', () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(loadAdminUsers, 300);
    });
    document.getElementById('admin-refresh').addEventListener('click', () => {
        loadAdminStats();
        loadAdminUsers();
        loadAdminBans();
    });

    /* --- Редактирование игрока --- */
    const adminTabStats = document.getElementById('admin-tab-stats');
    const adminTabPass = document.getElementById('admin-tab-pass');
    const adminTabBan = document.getElementById('admin-tab-ban');
    const adminTabDel = document.getElementById('admin-tab-del');
    const statsForm = document.getElementById('admin-stats-form');
    const passForm = document.getElementById('admin-pass-form');
    const banBlock = document.getElementById('admin-ban-block');
    const delBlock = document.getElementById('admin-del-block');

    function showAdminTab(which) {
        adminTabStats.classList.toggle('active', which === 'stats');
        adminTabPass.classList.toggle('active', which === 'pass');
        adminTabBan.classList.toggle('active', which === 'ban');
        adminTabDel.classList.toggle('active', which === 'del');
        statsForm.classList.toggle('hidden', which !== 'stats');
        passForm.classList.toggle('hidden', which !== 'pass');
        banBlock.classList.toggle('hidden', which !== 'ban');
        delBlock.classList.toggle('hidden', which !== 'del');
        document.getElementById('edit-stats-error').textContent = '';
        document.getElementById('edit-pass-error').textContent = '';
        document.getElementById('edit-ban-error').textContent = '';
        document.getElementById('edit-del-error').textContent = '';
    }
    adminTabStats.addEventListener('click', () => showAdminTab('stats'));
    adminTabPass.addEventListener('click', () => showAdminTab('pass'));
    adminTabBan.addEventListener('click', () => showAdminTab('ban'));
    adminTabDel.addEventListener('click', () => showAdminTab('del'));

    function openAdminEdit(u) {
        adminTarget = u;
        editTitle.textContent = 'Игрок: ' + u.name;
        document.getElementById('edit-best').value = u.best;
        document.getElementById('edit-games').value = u.games;
        document.getElementById('edit-kills').value = u.kills;
        document.getElementById('edit-pass').value = '';
        document.getElementById('ban-ip-text').textContent =
            u.ip ? 'IP игрока: ' + u.ip + (u.banned ? ' — уже заблокирован' : '')
                 : 'IP ещё не сохранён — игрок не входил после обновления сервера';
        document.getElementById('ban-reason').value = '';
        document.getElementById('admin-ban-btn').classList.toggle('hidden', !!u.banned);
        document.getElementById('admin-unban-btn').classList.toggle('hidden', !u.banned);
        showAdminTab('stats');
        adminEditModal.classList.remove('hidden');
    }

    statsForm.addEventListener('submit', async e => {
        e.preventDefault();
        if (!adminTarget || busy) return;
        const errEl = document.getElementById('edit-stats-error');
        errEl.textContent = '';
        const btn = statsForm.querySelector('button[type=submit]');
        busy = true; btn.disabled = true; btn.textContent = 'Сохраняем…';
        try {
            await api('/api/admin/edit-stats', {
                method: 'POST',
                body: {
                    name: adminTarget.name,
                    best: Number(document.getElementById('edit-best').value),
                    games: Number(document.getElementById('edit-games').value),
                    kills: Number(document.getElementById('edit-kills').value)
                }
            });
            adminEditModal.classList.add('hidden');
            loadAdminStats();
            loadAdminUsers();
            if (user && user.name === adminTarget.name) {
                const data = await api('/api/me');
                user = data.user;
                refreshUI();
            }
        } catch (err) {
            errEl.textContent = err.message;
        } finally {
            busy = false; btn.disabled = false; btn.textContent = 'Сохранить';
        }
    });

    passForm.addEventListener('submit', async e => {
        e.preventDefault();
        if (!adminTarget || busy) return;
        const errEl = document.getElementById('edit-pass-error');
        errEl.textContent = '';
        const btn = passForm.querySelector('button[type=submit]');
        busy = true; btn.disabled = true; btn.textContent = 'Меняем…';
        try {
            await api('/api/admin/reset-password', {
                method: 'POST',
                body: { name: adminTarget.name, password: document.getElementById('edit-pass').value }
            });
            adminEditModal.classList.add('hidden');
        } catch (err) {
            errEl.textContent = err.message;
        } finally {
            busy = false; btn.disabled = false; btn.textContent = 'Сменить пароль';
        }
    });

    document.getElementById('admin-delete-btn').addEventListener('click', async () => {
        if (!adminTarget || busy) return;
        const errEl = document.getElementById('edit-del-error');
        errEl.textContent = '';
        if (!confirm(`Удалить аккаунт «${adminTarget.name}» безвозвратно?`)) return;
        const btn = document.getElementById('admin-delete-btn');
        busy = true; btn.disabled = true; btn.textContent = 'Удаляем…';
        try {
            await api('/api/admin/delete-user', { method: 'POST', body: { name: adminTarget.name } });
            adminEditModal.classList.add('hidden');
            loadAdminStats();
            loadAdminUsers();
            updateLeaderboard();
        } catch (err) {
            errEl.textContent = err.message;
        } finally {
            busy = false; btn.disabled = false; btn.textContent = 'Удалить аккаунт';
        }
    });

    document.getElementById('admin-ban-btn').addEventListener('click', async () => {
        if (!adminTarget || busy) return;
        const errEl = document.getElementById('edit-ban-error');
        errEl.textContent = '';
        if (!adminTarget.ip) { errEl.textContent = 'У игрока нет сохранённого IP'; return; }
        const days = Number(document.getElementById('ban-days').value || 0);
        const btn = document.getElementById('admin-ban-btn');
        busy = true; btn.disabled = true; btn.textContent = 'Блокируем…';
        try {
            await api('/api/admin/ban', {
                method: 'POST',
                body: {
                    ip: adminTarget.ip,
                    reason: document.getElementById('ban-reason').value.trim(),
                    days
                }
            });
            adminTarget.banned = true;
            btn.classList.add('hidden');
            document.getElementById('admin-unban-btn').classList.remove('hidden');
            loadAdminBans();
            loadAdminUsers();
        } catch (err) {
            errEl.textContent = err.message;
        } finally {
            busy = false; btn.disabled = false; btn.textContent = 'Заблокировать IP';
        }
    });

    document.getElementById('admin-unban-btn').addEventListener('click', async () => {
        if (!adminTarget || busy) return;
        const errEl = document.getElementById('edit-ban-error');
        errEl.textContent = '';
        const btn = document.getElementById('admin-unban-btn');
        busy = true; btn.disabled = true;
        try {
            await api('/api/admin/unban', { method: 'POST', body: { ip: adminTarget.ip } });
            adminTarget.banned = false;
            btn.classList.add('hidden');
            document.getElementById('admin-ban-btn').classList.remove('hidden');
            loadAdminBans();
            loadAdminUsers();
        } catch (err) {
            errEl.textContent = err.message;
        } finally {
            busy = false; btn.disabled = false;
        }
    });

    /* --- Для demo.js --- */
    window.__ss = {
        getCurrent: () => user,
        recordGame,
        refreshUI,
        updateLeaderboard,
        apiBase: API_BASE
    };
})();
