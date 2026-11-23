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
    const CONSENT_KEY = 'ss_cookie_consent';

    /* Согласие на куки: без него fetch не отправляет credentials, и браузер
       не сохраняет сессионную куку. Вход всё равно работает через заголовок
       Authorization и токен в localStorage. */
    function consentGranted() {
        return localStorage.getItem(CONSENT_KEY) === 'granted';
    }

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

    /* --- Цвета аватарок --- */
    const AVATAR_COLORS = [
        '#00d4ff','#ff4466','#00cc88','#ffaa00','#aa44ff',
        '#ff66aa','#00aaff','#ff8844','#44dd44','#ffdd44',
	'#ffffff'
    ];
    const DEFAULT_AVATAR_HUE = 220;

    function avatarColor(name, custom) {
        if (custom) return custom;
        let h = 0;
        for (let i = 0; i < name.length; i++) h += name.charCodeAt(i);
        return `hsl(${(h * 137.508) % 360}, 65%, 50%)`;
    }

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
                credentials: consentGranted() ? 'include' : 'omit',
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
            const avatarEl = document.getElementById('profile-avatar');
            const clr = avatarColor(user.name, user.avatar);
            avatarEl.textContent = user.name[0].toUpperCase();
            avatarEl.style.background = clr;
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
            nick.className = 'lb-nick';
            const dot = document.createElement('i');
            dot.className = 'lb-dot';
            dot.style.background = avatarColor(e.name, e.avatar);
            nick.append(dot, document.createTextNode(e.name));
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
            if (data.tfa_required) {
                // Второй шаг: код из письма.
                openTfaModal(data.pending_token, data.email);
                loginForm.reset();
                return;
            }
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
        const email = document.getElementById('reg-email').value.trim();
        regError.textContent = '';

        if (name.length < 3 || name.length > 20) { regError.textContent = 'Ник: 3–20 символов'; return; }
        if (!/^[a-zA-Zа-яА-ЯёЁ0-9_]+$/.test(name)) { regError.textContent = 'Только буквы, цифры и _'; return; }
        if (pass.length < 6) { regError.textContent = 'Пароль: минимум 6 символов'; return; }
        if (pass !== pass2) { regError.textContent = 'Пароли не совпадают'; return; }
        if (email && !/^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/.test(email)) { regError.textContent = 'Некорректный email'; return; }

        const btn = regForm.querySelector('button[type=submit]');
        busy = true; btn.disabled = true; btn.textContent = 'Создаём…';
        try {
            const data = await api('/api/register', {
                method: 'POST', body: { name, password: pass, email }, auth: false
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
                    method: 'POST',
                    credentials: consentGranted() ? 'include' : 'omit',
                    headers: { Authorization: 'Bearer ' + t }
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
        loadAdminLogs();
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
            // Колонка прав разработчика: выдать / снять (нельзя — себе).
            const rights = document.createElement('td');
            const isSelf = user && u.name.toLowerCase() === String(user.name).toLowerCase();
            if (isSelf) {
                rights.textContent = '—';
            } else {
                const rbtn = document.createElement('button');
                rbtn.type = 'button';
                rbtn.className = 'admin-row-edit ' + (u.admin ? 'revoke' : 'grant');
                rbtn.textContent = u.admin ? 'Снять' : 'Выдать';
                rbtn.title = u.admin
                    ? 'Снять права разработчика'
                    : 'Дать доступ к панели разработчика';
                rbtn.addEventListener('click', async () => {
                    const endpoint = u.admin ? '/api/admin/rights/revoke' : '/api/admin/rights/grant';
                    try {
                        await api(endpoint, { method: 'POST', body: { name: u.name } });
                        loadAdminUsers();
                    } catch (err) {
                        adminError.textContent = err.message;
                    }
                });
                rights.appendChild(rbtn);
            }
            const act = document.createElement('td');
            const edit = document.createElement('button');
            edit.type = 'button';
            edit.className = 'admin-row-edit';
            edit.textContent = 'Изменить';
            edit.addEventListener('click', () => openAdminEdit(u));
            act.appendChild(edit);
            tr.append(name, best, games, kills, since, ip, rights, act);
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
        loadAdminLogs();
    });

    const ACTION_LABELS = {
        'ban': '🚫 Бан',
        'unban': '✅ Разбан',
        'delete-user': '🗑 Удаление',
        'reset-password': '🔑 Смена пароля',
        'edit-stats': '✏️ Правка статистики'
    };

    async function loadAdminLogs() {
        const logsEl = document.getElementById('admin-logs');
        const logsEmpty = document.getElementById('admin-logs-empty');
        logsEl.innerHTML = '';
        let logs = [];
        try {
            const data = await api('/api/admin/logs');
            logs = data.logs || [];
        } catch (err) {
            logsEmpty.textContent = err.message;
            logsEmpty.style.display = '';
            return;
        }
        if (!logs.length) {
            logsEmpty.textContent = 'Действий пока не было';
            logsEmpty.style.display = '';
            return;
        }
        logsEmpty.style.display = 'none';
        for (const l of logs) {
            const tr = document.createElement('tr');
            const when = document.createElement('td');
            const d = new Date(l.created);
            when.textContent = d.toLocaleDateString('ru-RU') + ' ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
            const who = document.createElement('td'); who.textContent = l.admin;
            const act = document.createElement('td'); act.textContent = ACTION_LABELS[l.action] || l.action;
            const target = document.createElement('td'); target.textContent = l.target || '—';
            const details = document.createElement('td'); details.textContent = l.details || '—';
            details.title = l.details || '';
            tr.append(when, who, act, target, details);
            logsEl.appendChild(tr);
        }
    }

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

    /* --- Аватарка --- */
    const avatarPicker = document.getElementById('avatar-picker');
    const avatarSwatches = document.getElementById('avatar-swatches');
    const avatarReset = document.getElementById('avatar-reset');
    let pickerOpen = false;

    function openAvatarPicker() {
        pickerOpen = !pickerOpen;
        avatarPicker.classList.toggle('hidden', !pickerOpen);
    }
    document.getElementById('profile-avatar').addEventListener('click', openAvatarPicker);

    AVATAR_COLORS.forEach(clr => {
        const s = document.createElement('button');
        s.type = 'button';
        s.className = 'avatar-swatch';
        s.style.background = clr;
        s.title = clr;
        s.addEventListener('click', async () => {
            if (busy) return;
            busy = true;
            try {
                const data = await api('/api/me/avatar', {
                    method: 'POST', body: { avatar: clr }
                });
                user = data.user;
                refreshUI();
            } catch (err) {
                console.warn('Смена аватара:', err.message);
            } finally {
                busy = false;
            }
        });
        avatarSwatches.appendChild(s);
    });

    avatarReset.addEventListener('click', async () => {
        if (busy) return;
        busy = true;
        try {
            const data = await api('/api/me/avatar', {
                method: 'POST', body: { avatar: '' }
            });
            user = data.user;
            refreshUI();
        } catch (err) {
            console.warn('Сброс аватара:', err.message);
        } finally {
            busy = false;
        }
    });

    /* --- GDPR: экспорт и удаление аккаунта --- */
    document.getElementById('export-btn').addEventListener('click', async () => {
        const btn = document.getElementById('export-btn');
        if (busy || !user) return;
        busy = true; btn.disabled = true; btn.textContent = 'Выгружаем…';
        try {
            const data = await api('/api/me/export');
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'space-shooter-' + user.name + '.json';
            a.click();
            URL.revokeObjectURL(url);
        } catch (err) {
            loginError.textContent = err.message;
        } finally {
            busy = false; btn.disabled = false; btn.textContent = '📥 Мои данные';
        }
    });

    const delAccModal = document.getElementById('delete-account-modal');
    document.getElementById('delete-account-btn').addEventListener('click', () => {
        document.getElementById('delacc-pass').value = '';
        document.getElementById('delacc-error').textContent = '';
        delAccModal.classList.remove('hidden');
    });
    delAccModal.querySelectorAll('[data-close]').forEach(
        el => el.addEventListener('click', () => delAccModal.classList.add('hidden')));
    delAccModal.addEventListener('click', e => {
        if (e.target === delAccModal) delAccModal.classList.add('hidden');
    });

    document.getElementById('delacc-confirm').addEventListener('click', async () => {
        if (busy) return;
        const errEl = document.getElementById('delacc-error');
        errEl.textContent = '';
        const pass = document.getElementById('delacc-pass').value;
        if (!pass) { errEl.textContent = 'Введи пароль'; return; }
        const btn = document.getElementById('delacc-confirm');
        busy = true; btn.disabled = true; btn.textContent = 'Удаляем…';
        try {
            await api('/api/me/delete', { method: 'POST', body: { password: pass } });
            delAccModal.classList.add('hidden');
            closeModal();
            clearToken();
            user = null;
            refreshUI();
            updateLeaderboard();
        } catch (err) {
            errEl.textContent = err.message;
        } finally {
            busy = false; btn.disabled = false; btn.textContent = 'Удалить навсегда';
        }
    });

    /* --- Баннер согласия на куки --- */
    (function cookieBanner() {
        const banner = document.getElementById('cookie-banner');
        if (!banner) return;
        if (localStorage.getItem(CONSENT_KEY)) return;   // уже выбрано
        banner.classList.remove('hidden');
        document.getElementById('cookie-accept').addEventListener('click', () => {
            localStorage.setItem(CONSENT_KEY, 'granted');
            banner.classList.add('hidden');
        });
        document.getElementById('cookie-decline').addEventListener('click', () => {
            localStorage.setItem(CONSENT_KEY, 'declined');
            banner.classList.add('hidden');
        });
    })();

    /* --- Для demo.js --- */
    window.__ss = {
        getCurrent: () => user,
        recordGame,
        refreshUI,
        updateLeaderboard,
        apiBase: API_BASE
    };

    /* ============================================
       Счётчик скачиваний
       ============================================ */
    const downloadCounts = {};

    function formatCount(n) {
        if (n < 1000) return String(n);
        return n >= 1000000
            ? (n / 1000000).toFixed(1).replace(/\.0$/, '') + 'M'
            : (n / 1000).toFixed(0) + 'K';
    }

    function renderCounts() {
        document.querySelectorAll('.dl-count').forEach(el => {
            const key = el.getAttribute('data-key');
            if (key && key in downloadCounts) {
                const c = downloadCounts[key];
                el.textContent = '· ' + formatCount(c);
                el.removeAttribute('data-empty');
            } else {
                el.setAttribute('data-empty', '1');
                el.textContent = '';
            }
        });
    }

    async function loadDownloadCounts() {
        try {
            const data = await api('/api/downloads', { auth: false });
            for (const d of data.downloads) {
                downloadCounts[d.version + ':' + d.format] = d.count;
            }
            renderCounts();
        } catch {
            console.warn('Счётчик скачиваний недоступен');
        }
    }

    document.addEventListener('click', async (e) => {
        const link = e.target.closest('.dl-link');
        if (!link) return;
        const version = link.getAttribute('data-version');
        const format = link.getAttribute('data-format');
        if (!version || !format) return;
        try {
            await api('/api/download/hit', {
                method: 'POST',
                body: { version, format },
                auth: false
            });
            downloadCounts[version + ':' + format] = (downloadCounts[version + ':' + format] || 0) + 1;
            renderCounts();
        } catch {
            console.warn('Не удалось зафиксировать скачивание');
        }
    });

    loadDownloadCounts();

    /* ============================================
       2FA: модалка ввода кода
       ============================================ */
    const tfaModal = document.getElementById('tfa-modal');
    let tfaPending = '';
    let tfaMode = 'login';   // login — вход в аккаунт, enable — включение 2FA
    let tfaDone = null;      // колбэк после успешного подтверждения

    function openTfaModal(pending, emailMasked, mode, onDone) {
        if (!tfaModal) return;
        tfaPending = pending;
        tfaMode = mode || 'login';
        tfaDone = onDone || null;
        document.getElementById('tfa-title').textContent =
            tfaMode === 'enable' ? '🔐 Подтверждение 2FA' : '🔐 Подтверждение входа';
        document.getElementById('tfa-email').textContent =
            'Мы отправили 6-значный код на ' + emailMasked + '. Проверь входящие и спам.';
        document.getElementById('tfa-code').value = '';
        document.getElementById('tfa-msg').textContent = '';
        if (tfaMode === 'login') modal.classList.add('hidden');  // прячем модалку входа
        tfaModal.classList.remove('hidden');
        document.body.style.overflow = 'hidden';
        document.getElementById('tfa-code').focus();
    }

    function closeTfaModal() {
        if (!tfaModal) return;
        tfaModal.classList.add('hidden');
        document.body.style.overflow = '';
        if (tfaMode === 'login') modal.classList.remove('hidden');  // возвращаемся к форме входа
    }

    if (tfaModal) {
        tfaModal.querySelectorAll('[data-close]').forEach(el =>
            el.addEventListener('click', closeTfaModal));

        document.getElementById('tfa-submit').addEventListener('click', async () => {
            const msg = document.getElementById('tfa-msg');
            const code = document.getElementById('tfa-code').value.trim();
            msg.textContent = '';
            if (!/^\d{6}$/.test(code)) { msg.textContent = 'Введите 6-значный код из письма'; return; }
            const btn = document.getElementById('tfa-submit');
            btn.disabled = true; btn.textContent = 'Проверяем…';
            const path = tfaMode === 'enable' ? '/api/tfa/confirm' : '/api/tfa/verify';
            const auth = tfaMode === 'enable';
            try {
                const data = await api(path, {
                    method: 'POST',
                    body: { pending_token: tfaPending, code },
                    auth
                });
                const done = tfaDone;
                if (tfaMode === 'login') {
                    setToken(data.token);
                    user = data.user;
                    closeTfaModal();
                    closeModal();
                    refreshUI();
                    updateLeaderboard();
                } else {
                    closeTfaModal();
                    if (done) done(data);
                }
            } catch (err) {
                msg.textContent = err.message;
            } finally {
                btn.disabled = false; btn.textContent = 'Подтвердить';
            }
        });

        document.getElementById('tfa-code').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') document.getElementById('tfa-submit').click();
        });
    }

    /* ============================================
       Табы разделов профиля
       ============================================ */
    (function profileTabs() {
        const tabs = [
            ['ptab-friends', 'psec-friends'],
            ['ptab-security', 'psec-security'],
            ['ptab-privacy', 'psec-privacy']
        ];
        const btns = tabs.map(([id]) => document.getElementById(id));
        if (!btns[0]) return;
        tabs.forEach(([tabId, panelId], i) => {
            btns[i].addEventListener('click', () => {
                btns.forEach(b => b.classList.remove('active'));
                btns[i].classList.add('active');
                tabs.forEach(([, pid], j) => {
                    document.getElementById(pid).classList.toggle('hidden', j !== i);
                });
            });
        });
    })();

    /* ============================================
       Смена пароля в профиле
       ============================================ */
    (function passwordSection() {
        const curInput = document.getElementById('pass-current');
        const newInput = document.getElementById('pass-new');
        const saveBtn = document.getElementById('pass-save-btn');
        const msgEl = document.getElementById('pass-msg');
        if (!curInput || !saveBtn) return;

        async function submit() {
            msgEl.textContent = '';
            msgEl.style.color = '';
            const current = curInput.value;
            const next = newInput.value;
            if (!current) { msgEl.textContent = 'Введи текущий пароль'; return; }
            if (next.length < 6) { msgEl.textContent = 'Новый пароль: минимум 6 символов'; return; }
            saveBtn.disabled = true;
            try {
                await api('/api/me/password', {
                    method: 'POST', body: { current, new: next }, auth: true
                });
                curInput.value = '';
                newInput.value = '';
                msgEl.textContent = 'Пароль изменён ✓ (другие устройства разлогинены)';
                msgEl.style.color = '#00cc88';
                setTimeout(() => { msgEl.textContent = ''; msgEl.style.color = ''; }, 4000);
            } catch (err) {
                msgEl.textContent = err.message;
            } finally {
                saveBtn.disabled = false;
            }
        }

        saveBtn.addEventListener('click', submit);
        newInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
    })();

    /* ============================================
       Статус почты
       ============================================ */
    (function mailStatus() {
        const note = document.getElementById('mail-note');
        if (!note) return;
        async function load() {
            try {
                const data = await api('/api/mail/status', { auth: false });
                const labels = {
                    dry_run: '🧪 Тестовый режим (Dry Run)',
                    mailgun: '✅ Почта через Mailgun',
                    resend: '✅ Почта через Resend',
                    smtp: '✅ Почта через SMTP',
                    none: '⚠️ Почта не настроена — код 2FA не придёт'
                };
                note.textContent = labels[data.mail] || labels[data.mail];
                note.style.color = data.ready ? 'var(--clr-text)' : '#ffaa00';
            } catch {
                note.textContent = '⚠️ Почта не настроена — код 2FA не придёт';
                note.style.color = '#ffaa00';
            }
        }
        load();
    })();

    /* ============================================
       Email в профиле
       ============================================ */
    (function emailSection() {
        const emailInput = document.getElementById('profile-email');
        const emailSaveBtn = document.getElementById('email-save-btn');
        const emailMsg = document.getElementById('email-msg');
        if (!emailInput || !emailSaveBtn) return;

        emailSaveBtn.addEventListener('click', async () => {
            emailMsg.textContent = '';
            emailMsg.style.color = '';
            const email = emailInput.value.trim();
            if (email && !/^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/.test(email)) {
                emailMsg.textContent = 'Некорректный email';
                return;
            }
            emailSaveBtn.disabled = true;
            try {
                const data = await api('/api/me/email', {
                    method: 'POST', body: { email: email || '' }, auth: true
                });
                user = data.user;
                refreshUI();
                emailMsg.textContent = 'Сохранено ✓';
                emailMsg.style.color = '#00cc88';
                setTimeout(() => { emailMsg.textContent = ''; emailMsg.style.color = ''; }, 3000);
            } catch (err) {
                emailMsg.textContent = err.message;
            } finally {
                emailSaveBtn.disabled = false;
            }
        });
    })();

    /* ============================================
       2FA: включение/выключение в профиле
       ============================================ */
    (function tfaSettings() {
        const stateEl = document.getElementById('tfa-state');
        const toggleBtn = document.getElementById('tfa-toggle-btn');
        const passInput = document.getElementById('tfa-pass');
        const msgEl = document.getElementById('tfa-settings-msg');
        if (!stateEl || !toggleBtn) return;
        let enabled = false;

        async function loadStatus() {
            if (!user) { stateEl.textContent = 'Включается в профиле после входа'; return; }
            try {
                const data = await api('/api/tfa/status', { auth: true });
                enabled = data.enabled;
                stateEl.textContent = enabled
                    ? '✅ Включена — при входе код приходит на email'
                    : '⬜ Выключена — вход только по паролю';
                toggleBtn.textContent = enabled ? 'Выключить' : 'Включить';
            } catch {
                stateEl.textContent = '—';
            }
        }

        toggleBtn.addEventListener('click', async () => {
            msgEl.textContent = '';
            const password = passInput.value;
            if (!password) { msgEl.textContent = 'Введи пароль для подтверждения'; return; }
            toggleBtn.disabled = true;
            try {
                if (enabled) {
                    await api('/api/tfa/disable', { method: 'POST', body: { password }, auth: true });
                    passInput.value = '';
                    await loadStatus();
                } else {
                    const data = await api('/api/tfa/enable', { method: 'POST', body: { password }, auth: true });
                    // Код подтверждается в модалке, а не через prompt.
                    openTfaModal(data.pending_token, data.email, 'enable', async () => {
                        passInput.value = '';
                        msgEl.textContent = '2FA включена ✓';
                        msgEl.style.color = '#00cc88';
                        setTimeout(() => { msgEl.textContent = ''; msgEl.style.color = ''; }, 3000);
                        await loadStatus();
                    });
                }
            } catch (err) {
                msgEl.textContent = err.message;
            } finally {
                toggleBtn.disabled = false;
            }
        });

        document.addEventListener('ss:auth', () => { loadStatus(); });
        loadStatus();
    })();

    /* ============================================
       Друзья + сообщения
       ============================================ */
    function escHtml(s) {
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }

    (function friendsSection() {
        const addInput = document.getElementById('friend-add');
        const addBtn = document.getElementById('friend-add-btn');
        const listEl = document.getElementById('friends-list');
        const emptyEl = document.getElementById('friends-empty');
        const msgEl = document.getElementById('friend-msg');
        const inEl = document.getElementById('invites-in');
        const inEmpty = document.getElementById('invites-in-empty');
        const outEl = document.getElementById('invites-out');
        const outEmpty = document.getElementById('invites-out-empty');
        if (!addInput || !addBtn || !listEl) return;

        let tab = 'list';   // list | in | out

        function friendRow(f, buttons) {
            const clr = avatarColor(f.name, f.avatar);
            return '<li>' +
                '<span class="friend-avatar" style="background:' + clr + '">' +
                escHtml(f.name[0].toUpperCase()) + '</span>' +
                '<span class="friend-name">' + escHtml(f.name) + '</span>' +
                '<span class="friend-best">🏆 ' + f.best + '</span>' +
                buttons + '</li>';
        }

        function render() {
            const friends = (user && user.friends) || [];
            const invIn = (user && user.invites_in) || [];
            const invOut = (user && user.invites_out) || [];
            // Счётчик на табаке раздела и на подтабе входящих.
            const badge = document.getElementById('badge-friends');
            const badgeIn = document.getElementById('badge-in');
            const pending = invIn.length;
            if (badge) {
                const total = pending + ((user && user.unread) || 0);
                badge.textContent = String(total);
                badge.classList.toggle('hidden', total === 0);
            }
            if (badgeIn) {
                badgeIn.textContent = String(pending);
                badgeIn.classList.toggle('hidden', pending === 0);
            }
            listEl.innerHTML = friends.map(f => friendRow(f,
                '<button class="friend-chat" data-friend="' + escHtml(f.name) +
                '" type="button" title="Написать">✉</button>' +
                '<button class="friend-remove" data-friend="' + escHtml(f.name) +
                '" type="button" title="Удалить из друзей">✕</button>'
            )).join('');
            inEl.innerHTML = invIn.map(f => friendRow(f,
                '<button class="invite-accept" data-friend="' + escHtml(f.name) +
                '" type="button">Принять</button>' +
                '<button class="invite-decline" data-friend="' + escHtml(f.name) +
                '" type="button">Отклонить</button>'
            )).join('');
            outEl.innerHTML = invOut.map(f => friendRow(f,
                '<span class="invite-pending">ждёт ответа</span>' +
                '<button class="invite-decline" data-friend="' + escHtml(f.name) +
                '" type="button">Отозвать</button>'
            )).join('');
            emptyEl.classList.toggle('hidden', tab !== 'list' || friends.length > 0);
            inEmpty.classList.toggle('hidden', tab !== 'in' || invIn.length > 0);
            outEmpty.classList.toggle('hidden', tab !== 'out' || invOut.length > 0);
            for (const [el, on] of [[listEl, tab === 'list'], [inEl, tab === 'in'], [outEl, tab === 'out']])
                el.classList.toggle('hidden', !on);
            for (const [id, on] of [['itab-list', tab === 'list'], ['itab-in', tab === 'in'], ['itab-out', tab === 'out']])
                document.getElementById(id).classList.toggle('active', on);
        }

        async function reloadMe() {
            const data = await api('/api/me', { auth: true });
            user = data.user;
            refreshUI();
        }

        async function inviteAction(endpoint, name, btn) {
            msgEl.textContent = '';
            if (btn) btn.disabled = true;
            try {
                await api(endpoint, { method: 'POST', body: { target: name.toLowerCase() }, auth: true });
                await reloadMe();
            } catch (err) {
                msgEl.textContent = err.message;
                if (btn) btn.disabled = false;
            }
        }

        addBtn.addEventListener('click', async () => {
            msgEl.textContent = '';
            if (!user) { msgEl.textContent = 'Сначала войди в аккаунт'; return; }
            const target = addInput.value.trim().toLowerCase();
            if (!target) { msgEl.textContent = 'Укажите ник друга'; return; }
            addBtn.disabled = true;
            try {
                await api('/api/friends/add', { method: 'POST', body: { target }, auth: true });
                addInput.value = '';
                msgEl.style.color = '#00cc88';
                msgEl.textContent = 'Приглашение отправлено ✓';
                setTimeout(() => { msgEl.textContent = ''; msgEl.style.color = ''; }, 3000);
                await reloadMe();
            } catch (err) {
                msgEl.textContent = err.message;
            } finally {
                addBtn.disabled = false;
            }
        });

        for (const [id, key] of [['itab-list', 'list'], ['itab-in', 'in'], ['itab-out', 'out']]) {
            document.getElementById(id).addEventListener('click', () => { tab = key; render(); });
        }

        const panel = document.getElementById('psec-friends');
        panel.addEventListener('click', async (e) => {
            const btn = e.target.closest('.friend-remove, .friend-chat, .invite-accept, .invite-decline');
            if (!btn) return;
            const name = btn.getAttribute('data-friend');
            if (btn.classList.contains('friend-remove')) return inviteAction('/api/friends/remove', name, btn);
            if (btn.classList.contains('friend-chat')) return openChat(name);
            if (btn.classList.contains('invite-accept')) return inviteAction('/api/friends/invite/accept', name, btn);
            // Отозвать исходящее можно только у себя: удаляем через decline от имени автора.
            if (btn.classList.contains('invite-decline')) {
                const isOutgoing = tab === 'out';
                if (isOutgoing) return inviteAction('/api/friends/invite/cancel', name, btn);
                return inviteAction('/api/friends/invite/decline', name, btn);
            }
        });

        document.addEventListener('ss:auth', render);
        render();
    })();

    /* ============================================
       Чат с другом
       ============================================ */
    const chatModal = document.getElementById('chat-modal');
    let chatTarget = '';

    async function openChat(name) {
        if (!chatModal) return;
        chatTarget = name;
        document.getElementById('chat-peer').textContent = '✉ ' + name;
        document.getElementById('chat-list').innerHTML = '';
        document.getElementById('chat-input').value = '';
        modal.classList.add('hidden');
        chatModal.classList.remove('hidden');
        document.body.style.overflow = 'hidden';
        await loadChat();
    }

    async function loadChat() {
        const listEl = document.getElementById('chat-list');
        try {
            const data = await api('/api/messages?with=' + encodeURIComponent(chatTarget), { auth: true });
            listEl.innerHTML = '';
            const emptyEl = document.getElementById('chat-empty');
            emptyEl.classList.toggle('hidden', data.messages.length > 0);
            for (const m of data.messages) {
                const li = document.createElement('li');
                li.className = 'chat-msg' + (m.mine ? ' chat-mine' : '');
                li.innerHTML = '<span class="chat-author">' + (m.mine ? 'Ты' : escHtml(m.from)) +
                    '</span><span>' + escHtml(m.text) + '</span>';
                listEl.appendChild(li);
            }
            listEl.scrollTop = listEl.scrollHeight;
        } catch (err) {
            listEl.innerHTML = '<li class="chat-msg">' + escHtml(err.message) + '</li>';
        }
    }

    if (chatModal) {
        chatModal.querySelectorAll('[data-close]').forEach(el =>
            el.addEventListener('click', () => {
                chatModal.classList.add('hidden');
                document.body.style.overflow = '';
                modal.classList.remove('hidden');
            }));

        const sendBtn = document.getElementById('chat-send');
        const sendMsg = async () => {
            const input = document.getElementById('chat-input');
            const text = input.value.trim();
            if (!text) return;
            sendBtn.disabled = true;
            try {
                await api('/api/messages/send', {
                    method: 'POST', body: { target: chatTarget, text }, auth: true
                });
                input.value = '';
                await loadChat();
            } catch (err) {
                const listEl = document.getElementById('chat-list');
                const li = document.createElement('li');
                li.className = 'chat-msg';
                li.textContent = '⚠ ' + err.message;
                listEl.appendChild(li);
            } finally {
                sendBtn.disabled = false;
            }
        };
        sendBtn.addEventListener('click', sendMsg);
        document.getElementById('chat-input').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); sendMsg(); }
        });
    }

    /* ============================================
       Устройства (список активных сессий)
       ============================================ */
    (function devicesSection() {
        const toggleBtn = document.getElementById('devices-toggle');
        const listEl = document.getElementById('devices-list');
        if (!toggleBtn || !listEl) return;

        toggleBtn.addEventListener('click', async () => {
            const showing = !listEl.classList.contains('hidden');
            listEl.classList.toggle('hidden');
            toggleBtn.textContent = showing ? 'Показать устройства ▾' : 'Скрыть устройства ▴';
            if (showing) return;
            listEl.innerHTML = '<li>Загрузка…</li>';
            try {
                const data = await api('/api/me/sessions', { auth: true });
                listEl.innerHTML = '';
                const now = Date.now();
                for (const s of data.sessions) {
                    const ago = s.last_seen ? Math.round((now - s.last_seen) / 1000) : 0;
                    let agoStr = 'только что';
                    if (ago >= 60) agoStr = Math.floor(ago / 60) + ' мин назад';
                    if (ago >= 3600) agoStr = Math.floor(ago / 3600) + ' ч назад';
                    if (ago >= 86400) agoStr = Math.floor(ago / 86400) + ' дн назад';
                    const li = document.createElement('li');
                    li.innerHTML =
                        '<span class="' + (s.current ? 'device-current' : '') + '">' +
                        escHtml(s.device || 'Неизвестное устройство') +
                        (s.current ? ' ← ты здесь' : '') + '</span>' +
                        '<span class="device-meta">активен: ' + agoStr + '</span>';
                    listEl.appendChild(li);
                }
                if (data.sessions.length === 0) listEl.innerHTML = '<li>Нет активных сессий</li>';
            } catch (err) {
                listEl.innerHTML = '<li>' + escHtml(err.message) + '</li>';
            }
        });
    })();
})();
