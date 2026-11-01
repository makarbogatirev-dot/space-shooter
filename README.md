# Space Shooter — сайт и аккаунты

Статический сайт (`site/`) и сервер аккаунтов (`server/app.py`) в одном репозитории.

## Аккаунты

Сервер хранит пользователей в SQLite:

- пароль **не сохраняется** — в базе лежит только `PBKDF2-HMAC-SHA256`, 200 000 итераций, случайная соль 16 байт на каждого пользователя;
- вход выдаёт случайный токен сессии (30 дней), он лежит в `localStorage` браузера и передаётся в заголовке `Authorization: Bearer …`;
- ник хранится как есть и отдельно в нижнем регистре, поэтому `Nova` и `nova` — один аккаунт;
- рекорд, число игр и сбитых метеоритов пишутся на сервере, поэтому видны с любого устройства;
- защита от перебора: не более 12 попыток входа/регистрации с одного IP за 5 минут.

API:

| Метод | Путь | Что делает |
|---|---|---|
| `GET` | `/api/health` | проверка живости |
| `GET` | `/api/leaderboard?limit=10` | топ игроков по рекорду |
| `POST` | `/api/register` | `{name, password}` → `{token, user}` |
| `POST` | `/api/login` | `{name, password}` → `{token, user}` |
| `POST` | `/api/logout` | удаляет сессию |
| `GET` | `/api/me` | профиль по токену |
| `POST` | `/api/score` | `{score}` → обновлённый профиль |

## Локальный запуск

```bat
serve_site.bat
```

Сайт с аккаунтами: <http://localhost:8735>. База создаётся сама в `server/data/accounts.db`.
Нужен только Python 3.10+ — внешних зависимостей нет.

## Публикация

### Вариант 1: всё на одном хостинге (проще всего)

Залейте репозиторий на Render как Web Service:

- Build Command: `echo 'stdlib only - build not required'`
- Start Command: `python server/app.py`
- переменные окружения: `HOST=0.0.0.0`, `PORT=10000`
- `DB_PATH` — путь к файлу базы. По умолчанию `server/data/accounts.db` внутри проекта,
  но на бесплатном тарифе файловая система временная и база обнулится при
  переразвёртывании. Для постоянного хранения подключите диск (Disk) на `/var/data`
  и задайте `DB_PATH=/var/data/accounts.db`.

Файл `render.yaml` уже содержит эту конфигурацию. После деплоя сайт и аккаунты
работают по одному адресу, `site/js/config.js` менять не нужно.

### Вариант 2: сайт на GitHub Pages, сервер отдельно

1. Разверните сервер аккаунтов на Render/Railway/VPS (см. выше).
2. В `site/js/config.js` укажите его адрес:

```js
window.SS_API_BASE = 'https://space-shooter-accounts.onrender.com';
```

3. Запушьте — GitHub Pages подхватит изменение.

CORS на сервере открыт (`Access-Control-Allow-Origin: *`), cookie не используются,
поэтому такой вариант работает. Ограничить источник можно переменной
`ALLOWED_ORIGIN=https://makarbogatirev-dot.github.io`.

### Вариант 3: свой VPS

```bash
HOST=0.0.0.0 PORT=8000 DB_PATH=/srv/space-shooter/accounts.db python3 server/app.py
```

Перед ним поставьте nginx или Caddy с HTTPS — токены сессий должны идти по защищённому каналу.

## Структура

```
server/app.py     сервер: SQLite + API + раздача site/
site/             сам сайт (index.html, css/, js/, assets/)
site/js/config.js адрес API для фронтенда
serve_site.bat    локальный запуск
render.yaml       конфиг деплоя на Render
```
