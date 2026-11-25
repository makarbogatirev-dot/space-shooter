#!/usr/bin/env python3
"""Space Shooter — сервер аккаунтов.

Раздаёт статический сайт из ../site и JSON API поверх базы данных.
Пароли хранятся как PBKDF2-HMAC-SHA256 с индивидуальной солью, в открытом
виде не сохраняются нигде. Сессии — случайные токены в таблице sessions.

База: PostgreSQL, если задан DATABASE_URL (Render), иначе локальный SQLite —
файловая база на бесплатном тарифе Render обнуляется при каждом деплое.

Запуск:  python server/app.py
Переменные окружения:
    PORT         — порт (по умолчанию 8735)
    HOST         — адрес (по умолчанию 127.0.0.1, для деплоя 0.0.0.0)
    DATABASE_URL — postgres://... (Render); без него — SQLite в DB_PATH
    DB_PATH      — путь к файлу SQLite (по умолчанию server/data/accounts.db)
    ALLOWED_ORIGIN — значение Access-Control-Allow-Origin (по умолчанию *)
    ADMIN_NAMES  — ники через запятую, у которых есть права разработчика
                   (по умолчанию MakarB2026)
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import smtplib
import ssl
import sqlite3
import sys
import threading
import time
from email.mime.text import MIMEText
from base64 import b64encode
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, unquote, urlparse, parse_qs, urlencode
from urllib.request import Request, urlopen

BASE_DIR = Path(__file__).resolve().parent
SITE_DIR = (BASE_DIR.parent / "site").resolve()
DB_PATH = Path(os.environ.get("DB_PATH") or (BASE_DIR / "data" / "accounts.db")).resolve()
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

if DATABASE_URL:
    import psycopg2
    import psycopg2.extras
else:
    psycopg2 = None

PBKDF2_ITERATIONS = 200_000
SALT_BYTES = 16
SESSION_TTL = 60 * 60 * 24 * 30  # абсолютный максимум жизни сессии: 30 дней
SESSION_IDLE_TTL = 60 * 60 * 24 * 7  # «скольжение»: активная сессия живёт 7 дней
MAX_SESSIONS_PER_USER = 5          # сколько устройств может быть одновременно
PASSWORD_MIN = 8                   # минимальная длина пароля (с 24.11.2026)
MAX_BODY = 8 * 1024
NAME_RE = re.compile(r"^[A-Za-zА-Яа-яЁё0-9_]{3,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
AVATAR_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)
# Mailgun / Resend отправляют письма через HTTPS (порт 443). На бесплатном
# тарифе Render исходящий трафик на SMTP-порты 25/465/587 заблокирован,
# поэтому HTTP-API — единственный рабочий способ слать письма оттуда.
MAILGUN_API_KEY = os.environ.get("MAILGUN_API_KEY", "")
MAILGUN_DOMAIN = os.environ.get("MAILGUN_DOMAIN", "")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
MAIL_FROM = os.environ.get("MAIL_FROM", SMTP_FROM or "Space Shooter <no-reply@example.com>")
# Тестовый режим: письма не отправляются, а печатаются в stdout сервера.
SMTP_DRY_RUN = bool(os.environ.get("SMTP_DRY_RUN", ""))

# ------------------------------------------------------------------- скачивания
DOWNLOAD_VERSIONS = ("v1.0", "v1.1")
DOWNLOAD_FORMATS = ("installer", "portable", "source")
download_hits: dict[tuple[str, str, str], int] = {}

# ------------------------------------------------------------------- почта
def _post_form(url: str, headers: dict, fields: dict) -> tuple[int, str]:
    """Отправить form-urlencoded по HTTPS; вернуть (код ответа, текст)."""
    body = urlencode(fields).encode()
    req = Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    for key, value in headers.items():
        req.add_header(key, value)
    try:
        with urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode(errors="replace")[:300]
    except HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")[:300]
    except Exception as exc:  # noqa: BLE001
        return 0, repr(exc)


def _safe_print(*args, **kwargs):
    """Print с fallback на ASCII — для Windows-консолей без UTF-8."""
    try:
        print(*args, **kwargs)
    except (UnicodeEncodeError, UnicodeDecodeError):
        safe = [str(a).encode('ascii', 'replace').decode('ascii') for a in args]
        print(*safe, **kwargs)


def mail_status() -> str:
    """Как настроена почта: mailgun | resend | smtp | dry_run | none."""
    if SMTP_DRY_RUN:
        return "dry_run"
    if MAILGUN_API_KEY and MAILGUN_DOMAIN:
        return "mailgun"
    if RESEND_API_KEY:
        return "resend"
    if SMTP_USER and SMTP_PASS:
        return "smtp"
    return "none"


def send_email(to_email: str, subject: str, body: str) -> bool:
    """Отправить email (HTTP-API → SMTP). Возвращает True при успехе."""
    if SMTP_DRY_RUN:
        _safe_print(f"SMTP_DRY_RUN письмо -> {to_email} | {subject} | {body}", flush=True)
        return True
    # 1) Mailgun через HTTPS — работает на Render Free (SMTP-порты там закрыты).
    if MAILGUN_API_KEY and MAILGUN_DOMAIN:
        status, text = _post_form(
            f"https://api.mailgun.net/v3/{MAILGUN_DOMAIN}/messages",
            {"Authorization": "Basic " + b64encode(("api:" + MAILGUN_API_KEY).encode()).decode()},
            {"from": MAIL_FROM, "to": to_email, "subject": subject, "text": body},
        )
        if 200 <= status < 300:
            _safe_print("Письмо отправлено (mailgun):", to_email, flush=True)
            return True
        _safe_print(f"Mailgun ошибка {status}: {text}", flush=True)
        return False
    # 2) Resend через HTTPS.
    if RESEND_API_KEY:
        payload = json.dumps({"from": MAIL_FROM, "to": [to_email],
                              "subject": subject, "text": body}).encode()
        req = Request("https://api.resend.com/emails", data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer " + RESEND_API_KEY)
        try:
            with urlopen(req, timeout=15) as resp:
                if 200 <= resp.status < 300:
                    _safe_print("Письмо отправлено (resend):", to_email, flush=True)
                    return True
        except HTTPError as exc:
            _safe_print(f"Resend ошибка {exc.code}: {exc.read().decode(errors='replace')[:300]}", flush=True)
            return False
        except Exception as exc:  # noqa: BLE001
            _safe_print("Resend ошибка:", repr(exc), flush=True)
            return False
    # 3) Классический SMTP (работает локально и на платных тарифах хостинга).
    if not SMTP_USER or not SMTP_PASS:
        _safe_print("SMTP не настроен — письмо не отправлено:", to_email, subject, flush=True)
        return False
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
        msg["To"] = to_email
        ctx = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, to_email, msg.as_string())
        _safe_print("Письмо отправлено:", to_email, flush=True)
        return True
    except Exception as exc:  # noqa: BLE001
        _safe_print("Ошибка отправки письма:", repr(exc), flush=True)
        return False

# Права разработчика выдаются по нику, а не по флагу в базе: так их нельзя
# получить через API, и они переживают пересоздание базы на бесплатном тарифе.
ADMIN_NAMES = {
    n.strip().lower()
    for n in os.environ.get("ADMIN_NAMES", "MakarB2026").split(",")
    if n.strip()
}


def is_admin(name: str) -> bool:
    return name.lower() in ADMIN_NAMES


def is_admin_row(conn, row) -> bool:
    """Разработчик — из ADMIN_NAMES или назначенный через admin_rights."""
    if row["name"].lower() in ADMIN_NAMES:
        return True
    return conn.execute(
        "SELECT 1 FROM admin_rights WHERE user_id = ?", (row["id"],)
    ).fetchone() is not None


def mask_email(email: str) -> str:
    """a***@d***n.com — чтобы не светить чужой email целиком."""
    if not email or "@" not in email:
        return "—"
    local, _, domain = email.partition("@")
    head = local[0] + "***" if len(local) > 1 else "***"
    return f"{head}@{domain}"


# ------------------------------------------------------------------- 2FA
TFA_CODE_TTL = 10 * 60      # код живёт 10 минут
TFA_MAX_ATTEMPTS = 5


def tfa_enabled(conn, user_id: int) -> bool:
    row = conn.execute(
        "SELECT enabled FROM tfa WHERE user_id = ?", (user_id,)
    ).fetchone()
    return bool(row and row["enabled"])


def issue_tfa_code(conn, row) -> tuple[str, str]:
    """Генерирует 6-значный код, сохраняет хэш, создаёт pending-токен и шлёт письмо.

    Возвращает (pending_token, замаскированный email)."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    pending = secrets.token_urlsafe(24)
    now = int(time.time())
    code_hash = hash_password(code)
    # upsert: ON CONFLICT работает и в SQLite (3.24+), и в PostgreSQL.
    existing = conn.execute(
        "SELECT enabled FROM tfa WHERE user_id = ?", (row["id"],)
    ).fetchone()
    enabled = existing["enabled"] if existing else 1
    conn.execute(
        """INSERT INTO tfa (user_id, enabled, code_hash, code_expires, code_attempts, pending_token)
           VALUES (?, ?, ?, ?, 0, ?)
           ON CONFLICT(user_id) DO UPDATE SET
               code_hash = excluded.code_hash,
               code_expires = excluded.code_expires,
               code_attempts = 0,
               pending_token = excluded.pending_token""",
        (row["id"], enabled, code_hash, now + TFA_CODE_TTL, pending),
    )
    email = row["email"] if "email" in row.keys() else None
    sent = email and send_email(
        email,
        "Код входа в Space Shooter 🔐",
        f"Привет, {row['name']}!\n\n"
        f"Твой код подтверждения входа: {code}\n"
        "Код действует 10 минут. Если ты не входил — смени пароль.\n",
    )
    if not sent:
        raise ApiError(502, "Не удалось отправить код на почту. Попробуй позже.")
    return pending, mask_email(email)


def verify_tfa_code(conn, user_id: int, code: str) -> bool:
    row = conn.execute(
        "SELECT code_hash, code_expires, code_attempts FROM tfa WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if not row or not row["code_hash"]:
        return False
    if int(row["code_expires"]) < int(time.time()):
        return False
    if int(row["code_attempts"]) >= TFA_MAX_ATTEMPTS:
        return False
    if not verify_password(code.strip(), row["code_hash"]):
        conn.execute(
            "UPDATE tfa SET code_attempts = code_attempts + 1 WHERE user_id = ?",
            (user_id,),
        )
        # Коммитим сразу: вызывающий код бросит 401, а context manager db()
        # откатил бы транзакцию — и счётчик попыток не рос бы никогда
        # (6-значный код можно было бы брутфорсить бесконечно).
        conn.commit()
        return False
    # Код использован — гасим его.
    conn.execute(
        "UPDATE tfa SET code_hash = '', code_expires = 0, code_attempts = 0, pending_token = '' WHERE user_id = ?",
        (user_id,),
    )
    return True

_db_lock = threading.Lock()


# ---------------------------------------------------------------- база данных
class PgAdapter:
    """Тонкая обёртка над psycopg2-соединением под sqlite3-интерфейс:
    conn.execute(sql, params) с плейсхолдерами «?», строки-словари."""

    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, params=()):
        cur = self.raw.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql.replace("?", "%s"), tuple(params))
        return cur

    def executescript(self, script: str) -> None:
        for stmt in script.split(";"):
            if stmt.strip():
                self.raw.cursor().execute(stmt)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()


def db_connect():
    if DATABASE_URL:
        return PgAdapter(psycopg2.connect(DATABASE_URL, connect_timeout=10))
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextlib.contextmanager
def db():
    """Соединение под глобальной блокировкой: SQLite + потоки сервера."""
    with _db_lock:
        conn = db_connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


# Скалярный максимум: в SQLite это MAX, в PostgreSQL — GREATEST.
FN_GREATEST = "GREATEST" if DATABASE_URL else "MAX"


def db_init() -> None:
    id_type = "BIGSERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    with db() as conn:
        conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS users (
                id          {id_type},
                name        TEXT    NOT NULL UNIQUE,      -- отображаемый ник
                name_key    TEXT    NOT NULL UNIQUE,      -- ник в нижнем регистре
                pass_hash   TEXT    NOT NULL,
                created_at  BIGINT  NOT NULL,
                best        INTEGER NOT NULL DEFAULT 0,
                games       INTEGER NOT NULL DEFAULT 0,
                kills       INTEGER NOT NULL DEFAULT 0,
                avatar      TEXT
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token      TEXT    PRIMARY KEY,
                user_id    BIGINT  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at BIGINT  NOT NULL,
                expires_at BIGINT  NOT NULL,
                device     TEXT    NOT NULL DEFAULT '',
                last_seen  BIGINT  NOT NULL DEFAULT 0,
                fp         TEXT    NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS banned_ips (
                ip         TEXT    PRIMARY KEY,
                reason     TEXT    NOT NULL DEFAULT '',
                created_at BIGINT  NOT NULL,
                created_by TEXT    NOT NULL DEFAULT '',
                expires_at BIGINT                       -- NULL = бессрочно
            );
            CREATE TABLE IF NOT EXISTS friends (
                user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                friend_id  BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at BIGINT NOT NULL,
                PRIMARY KEY (user_id, friend_id)
            );
            CREATE TABLE IF NOT EXISTS friend_invites (
                id         {id_type},
                from_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                to_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at BIGINT NOT NULL,
                UNIQUE (from_id, to_id)
            );
            CREATE TABLE IF NOT EXISTS admin_logs (
                id         {id_type},
                admin_name TEXT   NOT NULL,
                action     TEXT   NOT NULL,
                target     TEXT   NOT NULL DEFAULT '',
                details    TEXT   NOT NULL DEFAULT '',
                created_at BIGINT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS downloads (
                id         {id_type},
                version    TEXT   NOT NULL DEFAULT 'v1.0',
                format     TEXT   NOT NULL DEFAULT 'installer',
                count      INTEGER NOT NULL DEFAULT 0,
                created_at BIGINT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tfa (
                user_id       BIGINT  NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                enabled       INTEGER NOT NULL DEFAULT 0,
                code_hash     TEXT    NOT NULL DEFAULT '',
                code_expires  BIGINT  NOT NULL DEFAULT 0,
                code_attempts INTEGER NOT NULL DEFAULT 0,
                pending_token TEXT    NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS messages (
                id         {id_type},
                from_id    BIGINT  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                to_id      BIGINT  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                text       TEXT    NOT NULL,
                read       INTEGER NOT NULL DEFAULT 0,
                created_at BIGINT  NOT NULL
            );
            CREATE TABLE IF NOT EXISTS admin_rights (
                user_id BIGINT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                granted_by BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at BIGINT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_users_best   ON users(best DESC);
            """
        )
        # Начальные записи для версий, если таблица пуста.
        if conn.execute("SELECT COUNT(*) AS cnt FROM downloads").fetchone()["cnt"] == 0:
            now = int(time.time())
            for version in ("v1.0", "v1.1"):
                for fmt in ("installer", "portable", "source"):
                    conn.execute(
                        "INSERT INTO downloads (version, format, count, created_at) VALUES (?, ?, 0, ?)",
                        (version, fmt, now),
                    )
        # Миграции для старых баз: колонки, добавленные после первого релиза.
        if DATABASE_URL:
            cols = {
                r["column_name"] for r in conn.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = 'users'"
                )
            }
        else:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
        for column in ("last_ip", "avatar", "email"):
            if column not in cols:
                conn.execute(f"ALTER TABLE users ADD COLUMN {column} TEXT")
        # Миграция sessions: колонки device/last_seen для списка устройств.
        if DATABASE_URL:
            s_cols = {
                r["column_name"] for r in conn.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = 'sessions'"
                )
            }
        else:
            s_cols = {r["name"] for r in conn.execute("PRAGMA table_info(sessions)")}
        if "device" not in s_cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN device TEXT NOT NULL DEFAULT ''")
        if "last_seen" not in s_cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN last_seen BIGINT NOT NULL DEFAULT 0")
        if "fp" not in s_cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN fp TEXT NOT NULL DEFAULT ''")


# ------------------------------------------------------------------- пароли
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, digest_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


# ------------------------------------------------------------------- сессии
def describe_ua(ua: str) -> str:
    """Человекочитаемое описание устройства по User-Agent браузера."""
    if not ua:
        return "Неизвестное устройство"
    ua_l = ua.lower()
    if "edg/" in ua_l:
        browser = "Edge"
    elif "opr/" in ua_l or "opera" in ua_l:
        browser = "Opera"
    elif "firefox/" in ua_l:
        browser = "Firefox"
    elif "chrome/" in ua_l or "crios/" in ua_l:
        browser = "Chrome"
    elif "safari/" in ua_l:
        browser = "Safari"
    else:
        browser = "Браузер"
    if "iphone" in ua_l:
        os_name = "iPhone"
    elif "ipad" in ua_l:
        os_name = "iPad"
    elif "android" in ua_l:
        os_name = "Android"
    elif "windows nt 10" in ua_l or "windows nt 11" in ua_l:
        os_name = "Windows"
    elif "windows" in ua_l:
        os_name = "Windows (старая)"
    elif "mac os x" in ua_l or "macintosh" in ua_l:
        os_name = "macOS"
    elif "linux" in ua_l:
        os_name = "Linux"
    else:
        os_name = ""
    return f"{browser} · {os_name}" if os_name else browser


def _ip_prefix(ip: str) -> str:
    """«Подсеть» клиента: IPv4 — первые 3 октета, IPv6 — /48.

    Привязываем сессию не к точному IP (мобильный оператор меняет его каждые
    несколько минут), а к подсети — так вход не слетает у честного игрока,
    но украденный токен с другого провайдера/страны уже не работает."""
    if ":" in ip:  # IPv6
        parts = ip.split("%")[0].split(":")
        return ":".join(parts[:3])
    parts = ip.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3])
    return ip


def device_fingerprint(ip: str, ua: str) -> str:
    """Отпечаток устройства = SHA-256 от подсети IP и User-Agent.

    Сессия принимается только с тем же отпечатком, что был при входе.
    Даже если кто-то узнает сам токен (утечка логов, XSS из localStorage),
    использовать его с другой машины/браузера не получится — сервер сожжёт
    такую сессию при первом же запросе."""
    raw = f"{_ip_prefix(ip)}|{ua[:200]}".encode("utf-8", "replace")
    return hashlib.sha256(raw).hexdigest()


def create_session(conn: sqlite3.Connection, user_id: int, ua: str = "",
                   ip: str = "") -> str:
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    fp = device_fingerprint(ip, ua) if ip else ""
    conn.execute(
        """INSERT INTO sessions (token, user_id, created_at, expires_at, device, last_seen, fp)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (token, user_id, now, now + SESSION_IDLE_TTL, describe_ua(ua)[:120], now, fp),
    )
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
    # Не больше MAX_SESSIONS_PER_USER активных сессий: самые старые вытесняем.
    # Фильтруем в Python, а не через «LIMIT -1 OFFSET n»: это синтаксис SQLite,
    # PostgreSQL на нём падает (LIMIT must not be negative).
    rows = conn.execute(
        "SELECT token FROM sessions WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    for r in rows[MAX_SESSIONS_PER_USER:]:
        conn.execute("DELETE FROM sessions WHERE token = ?", (r["token"],))
    return token


def user_by_token(conn: sqlite3.Connection, token: str,
                  fp: str = "") -> sqlite3.Row | None:
    """Находит пользователя по токену и сверяет отпечаток устройства.

    fp пустой — проверка отпечатка пропущена (для клиентов без IP-информации).
    Сессии, созданные до введения отпечатка (fp = '' в базе), работают, но
    при первом же запросе «дозapisывают» себе текущий отпечаток."""
    if not token:
        return None
    now = int(time.time())
    row = conn.execute(
        """SELECT u.*, s.fp AS session_fp, s.created_at AS session_created
           FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token = ? AND s.expires_at > ?""",
        (token, now),
    ).fetchone()
    if not row:
        return None
    session_fp = row["session_fp"] or ""
    if session_fp and fp and not hmac.compare_digest(session_fp, fp):
        # Токен украли/скопировали и используют с другой машины — сжигаем сессию.
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        # Коммитим сразу: дальше бросим 401, а db() откатил бы транзакцию,
        # и украденный токен остался бы жив.
        conn.commit()
        _safe_print("Сессия сожжена: отпечаток не совпал (токен, вероятно, украден)", flush=True)
        return None
    if not session_fp and fp:
        conn.execute("UPDATE sessions SET fp = ? WHERE token = ?", (fp, token))
    # Скользящий TTL: продлеваем до now + IDLE, но не дольше абсолютного
    # потолка created_at + SESSION_TTL.
    hard_stop = int(row["session_created"]) + SESSION_TTL
    new_expiry = min(now + SESSION_IDLE_TTL, hard_stop)
    if new_expiry > now:
        conn.execute("UPDATE sessions SET expires_at = ? WHERE token = ?", (new_expiry, token))
    return row


def user_payload(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    rank = conn.execute(
        "SELECT COUNT(*) + 1 AS rank, (SELECT COUNT(*) FROM users) AS total FROM users WHERE best > ?",
        (row["best"],),
    ).fetchone()
    # Загружаем друзей с их статистикой
    friend_rows = conn.execute(
        """SELECT u.name, u.best, u.avatar
           FROM friends f
           JOIN users u ON u.id = f.friend_id
           WHERE f.user_id = ?
           ORDER BY u.best DESC""",
        (row["id"],),
    ).fetchall()
    friends = [
        {"name": r["name"], "best": r["best"], "avatar": r["avatar"]}
        for r in friend_rows
    ]
    # Приглашения: входящие (нужно ответить) и исходящие (ждут ответа).
    invites_in = conn.execute(
        """SELECT u.name, u.best, u.avatar, i.created_at * 1000 AS created
           FROM friend_invites i JOIN users u ON u.id = i.from_id
           WHERE i.to_id = ? ORDER BY i.id DESC""",
        (row["id"],),
    ).fetchall()
    invites_out = conn.execute(
        """SELECT u.name, u.best, u.avatar, i.created_at * 1000 AS created
           FROM friend_invites i JOIN users u ON u.id = i.to_id
           WHERE i.from_id = ? ORDER BY i.id DESC""",
        (row["id"],),
    ).fetchall()
    unread = conn.execute(
        "SELECT COUNT(*) AS c FROM messages WHERE to_id = ? AND read = 0",
        (row["id"],),
    ).fetchone()["c"]
    return {
        "name": row["name"],
        "created": row["created_at"] * 1000,
        "best": row["best"],
        "games": row["games"],
        "kills": row["kills"],
        "rank": rank["rank"],
        "total": rank["total"],
        "admin": is_admin_row(conn, row),
        "avatar": row["avatar"],
        "email": row["email"] if "email" in row.keys() else None,
        "friends": friends,
        "invites_in": [dict(r) for r in invites_in],
        "invites_out": [dict(r) for r in invites_out],
        "unread": unread,
    }


def ban_for_ip(conn: sqlite3.Connection, ip: str) -> sqlite3.Row | None:
    """Активный бан для IP (NULL в expires_at = бессрочно)."""
    if not ip:
        return None
    return conn.execute(
        """SELECT * FROM banned_ips
           WHERE ip = ? AND (expires_at IS NULL OR expires_at > ?)""",
        (ip, int(time.time())),
    ).fetchone()


def require_not_banned(conn: sqlite3.Connection, ip: str) -> None:
    ban = ban_for_ip(conn, ip)
    if ban:
        until = ("до " + time.strftime("%d.%m.%Y %H:%M", time.localtime(ban["expires_at"]))
                 if ban["expires_at"] else "навсегда")
        reason = f" Причина: {ban['reason']}" if ban["reason"] else ""
        raise ApiError(403, f"Ваш IP заблокирован {until}.{reason}")


def log_admin_action(conn: sqlite3.Connection, admin_name: str, action: str,
                     target: str = "", details: str = "") -> None:
    """Журнал действий разработчика: кто, что, над кем и подробности."""
    conn.execute(
        """INSERT INTO admin_logs (admin_name, action, target, details, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (admin_name, action, target, details, int(time.time())),
    )


def leaderboard(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    rows = conn.execute(
        "SELECT name, best, avatar FROM users WHERE best > 0 ORDER BY best DESC, name LIMIT ?",
        (limit,),
    ).fetchall()
    return [{"name": r["name"], "best": r["best"], "avatar": r["avatar"]} for r in rows]


# ------------------------------------------------------- ограничение попыток
_attempts: dict[str, list[float]] = {}
_attempts_lock = threading.Lock()


def too_many_attempts(ip: str, limit: int = 20, window: float = 300.0) -> bool:
    now = time.time()
    with _attempts_lock:
        stamps = [t for t in _attempts.get(ip, []) if now - t < window]
        _attempts[ip] = stamps
        return len(stamps) >= limit


def note_attempt(ip: str) -> None:
    with _attempts_lock:
        _attempts.setdefault(ip, []).append(time.time())


def reset_attempts(ip: str) -> None:
    with _attempts_lock:
        _attempts.pop(ip, None)


# ------------------------------------------------------------------- HTTP
class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Handler(BaseHTTPRequestHandler):
    server_version = "SpaceShooterAccounts/1.0"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------ утилиты
    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def client_ip(self) -> str:
        # За прокси (Render, nginx) адрес сокета — это адрес прокси. В
        # X-Forwarded-For клиент может вписать что угодно, поэтому берём
        # ПОСЛЕДНИЙ адрес: его добавляет наш доверенный прокси (Render),
        # и подделать его со стороны браузера нельзя. Иначе лимит попыток
        # и привязка сессии к устройству обходились одной строчкой в curl.
        forwarded = self.headers.get("X-Forwarded-For") or ""
        if forwarded:
            return forwarded.split(",")[-1].strip()
        return self.client_address[0]

    def _cors_headers(self) -> None:
        origin = self.headers.get("Origin")
        if not origin:
            return
        # Разрешаем заголовок Authorization и куки-сессии. Cookie — HttpOnly и
        # SameSite=Lax, поэтому межсайтовый POST с чужого домена её не отправит
        # (защита от CSRF), а эхо Origin вместо "*" нужен, чтобы браузер
        # пропустил credentials при кросс-доменном запросе с GitHub Pages.
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN or origin)
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Max-Age", "86400")

    def send_json(self, status: int, payload: dict | list, cookies: list[str] = ()) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors_headers()
        for cookie in cookies:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "Некорректная длина тела запроса")
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ApiError(413, "Слишком большой запрос")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "Ожидается JSON")
        if not isinstance(data, dict):
            raise ApiError(400, "Ожидается JSON-объект")
        return data

    def bearer_token(self) -> str:
        header = self.headers.get("Authorization") or ""
        if header.lower().startswith("bearer "):
            return header[7:].strip()
        return ""

    def cookie_token(self) -> str:
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            name, _, value = part.strip().partition("=")
            if name == "ss_session":
                return unquote(value)
        return ""

    def session_token(self) -> str:
        # Заголовок приоритетнее: он есть у клиентов, которые его явно шлют;
        # куки — запасной путь для браузеров (и переживает чистку localStorage).
        return self.bearer_token() or self.cookie_token()

    @staticmethod
    def session_cookie(token: str) -> str:
        # HttpOnly — доступ только у сервера (защита от XSS), SameSite=Lax —
        # куки не уходит на POST-запросы с чужих сайтов (защита от CSRF).
        # Secure включён, т.к. API доступен только по HTTPS; на localhost без
        # него браузер всё равно примет куку.
        return (f"ss_session={quote(token)}; Path=/; Max-Age={SESSION_TTL}; "
                "HttpOnly; SameSite=Lax; Secure")

    @staticmethod
    def clear_cookie() -> str:
        return "ss_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax; Secure"

    def require_user(self, conn: sqlite3.Connection) -> sqlite3.Row:
        token = self.session_token()
        fp = device_fingerprint(self.client_ip(), self.headers.get("User-Agent") or "")
        row = user_by_token(conn, token, fp)
        if not row:
            raise ApiError(401, "Требуется вход")
        # Отмечаем активность сессии (не чаще раза в 10 минут).
        now = int(time.time())
        conn.execute(
            "UPDATE sessions SET last_seen = ? WHERE token = ? AND last_seen < ?",
            (now, token, now - 600),
        )
        return row

    def require_admin(self, conn: sqlite3.Connection) -> sqlite3.Row:
        row = self.require_user(conn)
        if not is_admin_row(conn, row):
            raise ApiError(403, "Недостаточно прав")
        return row

    # ------------------------------------------------------------- маршруты
    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.send_json(405, {"error": "Метод не поддерживается"})
        else:
            self.serve_static(parsed.path)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api_get(parsed.path, parse_qs(parsed.query))
        else:
            self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self.send_json(405, {"error": "Метод не поддерживается"})
            return
        try:
            self.handle_api_post(parsed.path)
        except ApiError as exc:
            self.send_json(exc.status, {"error": exc.message})
        except Exception as exc:  # noqa: BLE001 — не отдаём стек клиенту
            self.log_message("unhandled: %r", exc)
            self.send_json(500, {"error": "Внутренняя ошибка сервера"})

    def handle_api_get(self, path: str, query: dict) -> None:
        try:
            if path == "/api/health":
                self.send_json(200, {"ok": True})
                return
            if path == "/api/leaderboard":
                try:
                    limit = max(1, min(50, int((query.get("limit") or ["10"])[0])))
                except ValueError:
                    limit = 10
                with db() as conn:
                    self.send_json(200, {"entries": leaderboard(conn, limit)})
                return
            if path == "/api/me":
                with db() as conn:
                    row = self.require_user(conn)
                    self.send_json(200, {"user": user_payload(conn, row)})
                return
            if path == "/api/me/sessions":
                with db() as conn:
                    row = self.require_user(conn)
                    token = self.session_token()
                    sessions = conn.execute(
                        """SELECT created_at * 1000 AS created, expires_at * 1000 AS expires,
                                  device, last_seen * 1000 AS last_seen, token
                           FROM sessions WHERE user_id = ? ORDER BY last_seen DESC""",
                        (row["id"],),
                    ).fetchall()
                    out = []
                    for s in sessions:
                        d = dict(s)
                        # Токон не отдаём — только признак «это текущее устройство».
                        d["current"] = (d.pop("token") == token)
                        out.append(d)
                    self.send_json(200, {"sessions": out})
                return
            if path == "/api/messages":
                # Переписка с одним другом: ?with=ник. Также отдаём счётчик непрочитанных.
                with db() as conn:
                    me = self.require_user(conn)
                    peer_name = (query.get("with") or [""])[0].strip().lower()
                    if not peer_name:
                        unread = conn.execute(
                            "SELECT COUNT(*) AS c FROM messages WHERE to_id = ? AND read = 0",
                            (me["id"],),
                        ).fetchone()["c"]
                        self.send_json(200, {"unread": unread, "messages": []})
                        return
                    peer = conn.execute("SELECT id FROM users WHERE name_key = ?", (peer_name,)).fetchone()
                    if not peer:
                        raise ApiError(404, "Игрок не найден")
                    rows = conn.execute(
                        """SELECT m.from_id, u.name AS from_name, m.text,
                                  m.read, m.created_at * 1000 AS created
                           FROM messages m JOIN users u ON u.id = m.from_id
                           WHERE (m.from_id = ? AND m.to_id = ?)
                              OR (m.from_id = ? AND m.to_id = ?)
                           ORDER BY m.id ASC LIMIT 200""",
                        (me["id"], peer["id"], peer["id"], me["id"]),
                    ).fetchall()
                    # Отмечаем входящие как прочитанные.
                    conn.execute(
                        "UPDATE messages SET read = 1 WHERE to_id = ? AND from_id = ? AND read = 0",
                        (me["id"], peer["id"]),
                    )
                    unread = conn.execute(
                        "SELECT COUNT(*) AS c FROM messages WHERE to_id = ? AND read = 0",
                        (me["id"],),
                    ).fetchone()["c"]
                    self.send_json(200, {
                        "unread": unread,
                        "messages": [
                            {
                                "from": r["from_name"],
                                "mine": r["from_id"] == me["id"],
                                "text": r["text"],
                                "created": r["created"],
                            }
                            for r in rows
                        ],
                    })
                return
            if path == "/api/tfa/status":
                with db() as conn:
                    row = self.require_user(conn)
                    self.send_json(200, {"enabled": tfa_enabled(conn, row["id"])})
                return
            if path == "/api/mail/status":
                # Публичный флаг: настроена ли отправка писем (для подсказок в UI).
                status = mail_status()
                self.send_json(200, {"mail": status, "ready": status != "none"})
                return
            if path == "/api/admin/users":
                with db() as conn:
                    self.require_admin(conn)
                    search = (query.get("q") or [""])[0].strip().lower()
                    sql = """SELECT * FROM users
                             WHERE (? = '' OR name_key LIKE ?)
                             ORDER BY best DESC, name LIMIT 200"""
                    rows = conn.execute(sql, (search, f"%{search}%")).fetchall()
                    banned = {
                        r["ip"] for r in conn.execute(
                            "SELECT ip FROM banned_ips WHERE expires_at IS NULL OR expires_at > ?",
                            (int(time.time()),),
                        )
                    }
                    self.send_json(200, {
                        "users": [
                            {
                                "name": r["name"],
                                "created": r["created_at"] * 1000,
                                "best": r["best"],
                                "games": r["games"],
                                "kills": r["kills"],
                                "admin": is_admin_row(conn, r),
                                "ip": r["last_ip"] or "",
                                "banned": bool(r["last_ip"]) and r["last_ip"] in banned,
                            }
                            for r in rows
                        ]
                    })
                return
            if path == "/api/admin/bans":
                with db() as conn:
                    self.require_admin(conn)
                    rows = conn.execute(
                        """SELECT * FROM banned_ips
                           WHERE expires_at IS NULL OR expires_at > ?
                           ORDER BY created_at DESC LIMIT 200""",
                        (int(time.time()),),
                    ).fetchall()
                    self.send_json(200, {
                        "bans": [
                            {
                                "ip": r["ip"],
                                "reason": r["reason"],
                                "created": r["created_at"] * 1000,
                                "by": r["created_by"],
                                "expires": r["expires_at"] * 1000 if r["expires_at"] else None,
                                "users": [
                                    u["name"] for u in conn.execute(
                                        "SELECT name FROM users WHERE last_ip = ?", (r["ip"],)
                                    )
                                ],
                            }
                            for r in rows
                        ]
                    })
                return
            if path == "/api/admin/stats":
                with db() as conn:
                    self.require_admin(conn)
                    totals = conn.execute(
                        """SELECT COUNT(*) AS users,
                                  COALESCE(SUM(games), 0) AS games,
                                  COALESCE(SUM(kills), 0) AS kills,
                                  COALESCE(MAX(best), 0) AS best
                           FROM users"""
                    ).fetchone()
                    active = conn.execute(
                        "SELECT COUNT(*) AS n FROM sessions WHERE expires_at > ?",
                        (int(time.time()),),
                    ).fetchone()["n"]
                    self.send_json(200, {
                        "users": totals["users"],
                        "games": totals["games"],
                        "kills": totals["kills"],
                        "best": totals["best"],
                        "sessions": active,
                    })
                return
            if path == "/api/admin/logs":
                with db() as conn:
                    self.require_admin(conn)
                    rows = conn.execute(
                        """SELECT * FROM admin_logs
                           ORDER BY created_at DESC LIMIT 200"""
                    ).fetchall()
                    self.send_json(200, {
                        "logs": [
                            {
                                "admin": r["admin_name"],
                                "action": r["action"],
                                "target": r["target"],
                                "details": r["details"],
                                "created": r["created_at"] * 1000,
                            }
                            for r in rows
                        ]
                    })
                return
            if path == "/api/downloads":
                with db() as conn:
                    rows = conn.execute(
                        """SELECT version, format, count
                           FROM downloads
                           ORDER BY version DESC, format"""
                    ).fetchall()
                    self.send_json(200, {
                        "downloads": [
                            {"version": r["version"], "format": r["format"], "count": r["count"]}
                            for r in rows
                        ]
                    })
                return
            self.send_json(404, {"error": "Неизвестный метод API"})
        except ApiError as exc:
            self.send_json(exc.status, {"error": exc.message})
        except Exception as exc:  # noqa: BLE001
            self.log_message("unhandled: %r", exc)
            self.send_json(500, {"error": "Внутренняя ошибка сервера"})

    def handle_api_post(self, path: str) -> None:
        ip = self.client_ip()

        if path == "/api/register":
            if too_many_attempts(ip):
                raise ApiError(429, "Слишком много попыток. Попробуйте позже.")
            data = self.read_json()
            name = str(data.get("name") or "").strip()
            password = str(data.get("password") or "")
            email = str(data.get("email") or "").strip()

            if not NAME_RE.match(name):
                raise ApiError(400, "Ник: 3–20 символов, буквы, цифры и _")
            if len(password) < PASSWORD_MIN:
                raise ApiError(400, f"Пароль: минимум {PASSWORD_MIN} символов")
            if len(password) > 200:
                raise ApiError(400, "Пароль слишком длинный")
            if email and not EMAIL_RE.match(email):
                raise ApiError(400, "Некорректный email")

            note_attempt(ip)
            with db() as conn:
                require_not_banned(conn, ip)
                if conn.execute(
                    "SELECT 1 FROM users WHERE name_key = ?", (name.lower(),)
                ).fetchone():
                    raise ApiError(409, "Этот ник уже занят")
                conn.execute(
                    """INSERT INTO users (name, name_key, pass_hash, created_at, last_ip, email)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (name, name.lower(), hash_password(password), int(time.time()), ip,
                     email if email else None),
                )
                row = conn.execute("SELECT * FROM users WHERE name_key = ?", (name.lower(),)).fetchone()
                token = create_session(conn, row["id"], self.headers.get("User-Agent") or "", ip)
                reset_attempts(ip)
                if email:
                    send_email(
                        email,
                        "Добро пожаловать в Space Shooter! 🚀",
                        f"Привет, {name}!\n\n"
                        "Твой аккаунт в Space Shooter успешно создан.\n"
                        "Заходи на сайт, играй в демо и соревнуйся с друзьями за лучший рекорд!\n\n"
                        "Если это был не ты — смени пароль в профиле или напиши разработчику.",
                    )
                self.send_json(201, {"token": token, "user": user_payload(conn, row)},
                               cookies=[self.session_cookie(token)])
            return

        if path == "/api/login":
            if too_many_attempts(ip):
                raise ApiError(429, "Слишком много попыток. Попробуйте позже.")
            data = self.read_json()
            name = str(data.get("name") or "").strip()
            password = str(data.get("password") or "")
            if not name or not password:
                raise ApiError(400, "Заполните все поля")

            note_attempt(ip)
            with db() as conn:
                require_not_banned(conn, ip)
                row = conn.execute("SELECT * FROM users WHERE name_key = ?", (name.lower(),)).fetchone()
                if not row or not verify_password(password, row["pass_hash"]):
                    raise ApiError(401, "Неверный ник или пароль")
                reset_attempts(ip)
                conn.execute("UPDATE users SET last_ip = ? WHERE id = ?", (ip, row["id"]))

                # --- 2FA ---
                if tfa_enabled(conn, row["id"]):
                    # Пароль верный — шлём код на email.
                    pending, masked = issue_tfa_code(conn, row)
                    self.send_json(200, {"tfa_required": True, "pending_token": pending, "email": masked})
                    return

                # 2FA не включён — сразу даём сессию.
                token = create_session(conn, row["id"], self.headers.get("User-Agent") or "", ip)
                self.send_json(200, {"token": token, "user": user_payload(conn, row)},
                               cookies=[self.session_cookie(token)])
            return

        if path == "/api/logout":
            token = self.session_token()
            with db() as conn:
                if token:
                    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            self.send_json(200, {"ok": True}, cookies=[self.clear_cookie()])
            return

        if path == "/api/download/hit":
            # Счётчик скачиваний: не требует входа, по одному засчитыванию на IP в час.
            data = self.read_json()
            version = str(data.get("version") or "").strip()
            fmt = str(data.get("format") or "").strip()
            if version not in DOWNLOAD_VERSIONS or fmt not in DOWNLOAD_FORMATS:
                raise ApiError(400, "Неизвестная версия или формат")
            key = (ip, version, fmt)
            now = int(time.time())
            if download_hits.get(key, 0) > now - 3600:
                raise ApiError(429, "Уже учтено")
            download_hits[key] = now
            with db() as conn:
                row = conn.execute(
                    "SELECT id, count FROM downloads WHERE version = ? AND format = ?",
                    (version, fmt),
                ).fetchone()
                if not row:
                    conn.execute(
                        "INSERT INTO downloads (version, format, count, created_at) VALUES (?, ?, 1, ?)",
                        (version, fmt, now),
                    )
                    count = 1
                else:
                    conn.execute("UPDATE downloads SET count = count + 1 WHERE id = ?", (row["id"],))
                    count = row["count"] + 1
            self.send_json(200, {"count": count})
            return

        if path == "/api/score":
            data = self.read_json()
            try:
                score = int(data.get("score"))
            except (TypeError, ValueError):
                raise ApiError(400, "Очко должно быть целым числом")
            if score < 0 or score > 1_000_000:
                raise ApiError(400, "Недопустимое значение очков")

            with db() as conn:
                row = self.require_user(conn)
                require_not_banned(conn, ip)
                conn.execute(
                    f"""UPDATE users
                       SET best = {FN_GREATEST}(best, ?), games = games + 1, kills = kills + ?
                       WHERE id = ?""",
                    (score, score, row["id"]),
                )
                row = conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
                self.send_json(200, {"user": user_payload(conn, row)})
            return

        if path == "/api/me/avatar":
            data = self.read_json()
            avatar = str(data.get("avatar") or "").strip().lstrip("#")
            if avatar == "":  # пустая строка — сброс к цвету по нику
                with db() as conn:
                    row = self.require_user(conn)
                    conn.execute("UPDATE users SET avatar = NULL WHERE id = ?", (row["id"],))
                    row = conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
                    self.send_json(200, {"user": user_payload(conn, row)})
                return
            if len(avatar) == 3:  # короткая форма #f0a -> #ff00aa
                avatar = avatar[0] * 2 + avatar[1] * 2 + avatar[2] * 2
            if not re.fullmatch(r"[0-9a-fA-F]{6}", avatar):
                raise ApiError(400, "Аватар: HEX-цвет, например ff00aa или #f0a")
            avatar = "#" + avatar.lower()
            with db() as conn:
                row = self.require_user(conn)
                conn.execute("UPDATE users SET avatar = ? WHERE id = ?", (avatar, row["id"]))
                row = conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
                self.send_json(200, {"user": user_payload(conn, row)})
            return

        if path == "/api/me/email":
            # Смена email — только с текущим паролем: иначе украденная сессия
            # дала бы злоумышленнику полный контроль (новый email = сброс пароля).
            # На СТАРЫЙ адрес уходит предупреждение, если он был.
            data = self.read_json()
            email = str(data.get("email") or "").strip()
            current = str(data.get("current") or "")
            if email and not EMAIL_RE.match(email):
                raise ApiError(400, "Некорректный email")
            with db() as conn:
                row = self.require_user(conn)
                if not verify_password(current, row["pass_hash"]):
                    raise ApiError(401, "Текущий пароль неверен")
                old_email = row["email"] if "email" in row.keys() else None
                conn.execute(
                    "UPDATE users SET email = ? WHERE id = ?",
                    (email if email else None, row["id"]),
                )
                if old_email and old_email != email:
                    send_email(
                        old_email,
                        "Email в Space Shooter изменён ⚠️",
                        f"Привет, {row['name']}!\n\n"
                        f"Email твоего аккаунта изменён с {old_email} на {email or '(удалён)'}, "
                        "пароль был введён верно.\n"
                        "Если это был не ты — срочно смени пароль: сделать это можно прямо в профиле.\n",
                    )
                row = conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
                self.send_json(200, {"user": user_payload(conn, row)})
            return

        if path == "/api/me/password":
            # Смена собственного пароля: текущий пароль обязателен,
            # остальные сессии завершаются, текущая остаётся.
            data = self.read_json()
            current = str(data.get("current") or "")
            new_pass = str(data.get("new") or "")
            if len(new_pass) < PASSWORD_MIN or len(new_pass) > 200:
                raise ApiError(400, f"Новый пароль: минимум {PASSWORD_MIN} символов")
            with db() as conn:
                row = self.require_user(conn)
                if not verify_password(current, row["pass_hash"]):
                    raise ApiError(401, "Текущий пароль неверен")
                if current == new_pass:
                    raise ApiError(400, "Новый пароль совпадает с текущим")
                conn.execute(
                    "UPDATE users SET pass_hash = ? WHERE id = ?",
                    (hash_password(new_pass), row["id"]),
                )
                keep = self.session_token()
                if keep:
                    conn.execute(
                        "DELETE FROM sessions WHERE user_id = ? AND token <> ?",
                        (row["id"], keep),
                    )
                else:
                    conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
                email = row["email"] if "email" in row.keys() else None
                notified = False
                if email:
                    notified = send_email(
                        email,
                        "Пароль в Space Shooter изменён 🔑",
                        f"Привет, {row['name']}!\n\n"
                        "Твой пароль был изменён. Все остальные устройства разлогинены.\n"
                        "Если это был не ты — срочно смени пароль ещё раз или напиши разработчику.\n",
                    )
                row = conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
                self.send_json(200, {"user": user_payload(conn, row), "notified": notified})
            return

        if path == "/api/friends/add":
            # Отправляет приглашение в друзья (прямое добавление убрано).
            data = self.read_json()
            target = str(data.get("target") or "").strip().lower()
            if not target:
                raise ApiError(400, "Укажите ник друга")
            with db() as conn:
                me = self.require_user(conn)
                if me["name_key"] == target:
                    raise ApiError(400, "Нельзя добавить себя")
                friend = conn.execute(
                    "SELECT id FROM users WHERE name_key = ?", (target,)
                ).fetchone()
                if not friend:
                    raise ApiError(404, "Игрок не найден")
                if conn.execute(
                    "SELECT 1 FROM friends WHERE user_id = ? AND friend_id = ?",
                    (me["id"], friend["id"]),
                ).fetchone():
                    raise ApiError(409, "Уже в друзьях")
                if conn.execute(
                    """SELECT 1 FROM friend_invites
                       WHERE (from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?)""",
                    (me["id"], friend["id"], friend["id"], me["id"]),
                ).fetchone():
                    raise ApiError(409, "Приглашение уже отправлено")
                conn.execute(
                    "INSERT INTO friend_invites (from_id, to_id, created_at) VALUES (?, ?, ?)",
                    (me["id"], friend["id"], int(time.time())),
                )
            self.send_json(200, {"ok": True, "invited": True})
            return

        if path == "/api/friends/invite/accept":
            data = self.read_json()
            target = str(data.get("target") or "").strip().lower()
            if not target:
                raise ApiError(400, "Укажите ник игрока")
            with db() as conn:
                me = self.require_user(conn)
                peer = conn.execute(
                    """SELECT u.id FROM friend_invites i JOIN users u ON u.id = i.from_id
                       WHERE i.to_id = ? AND u.name_key = ?""",
                    (me["id"], target),
                ).fetchone()
                if not peer:
                    raise ApiError(404, "Приглашение не найдено")
                now = int(time.time())
                # Дружба взаимная: одна запись на каждое направление.
                conn.execute(
                    """INSERT INTO friends (user_id, friend_id, created_at) VALUES (?, ?, ?)
                       ON CONFLICT(user_id, friend_id) DO NOTHING""",
                    (me["id"], peer["id"], now),
                )
                conn.execute(
                    """INSERT INTO friends (user_id, friend_id, created_at) VALUES (?, ?, ?)
                       ON CONFLICT(user_id, friend_id) DO NOTHING""",
                    (peer["id"], me["id"], now),
                )
                conn.execute(
                    """DELETE FROM friend_invites
                       WHERE (from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?)""",
                    (peer["id"], me["id"], me["id"], peer["id"]),
                )
            self.send_json(200, {"ok": True})
            return

        if path == "/api/friends/invite/decline":
            data = self.read_json()
            target = str(data.get("target") or "").strip().lower()
            if not target:
                raise ApiError(400, "Укажите ник игрока")
            with db() as conn:
                me = self.require_user(conn)
                cur = conn.execute(
                    """DELETE FROM friend_invites
                       WHERE to_id = ? AND from_id = (SELECT id FROM users WHERE name_key = ?)""",
                    (me["id"], target),
                )
                if cur.rowcount == 0:
                    raise ApiError(404, "Приглашение не найдено")
            self.send_json(200, {"ok": True})
            return

        if path == "/api/friends/invite/cancel":
            # отзыв отправленного приглашения
            data = self.read_json()
            target = str(data.get("target") or "").strip().lower()
            if not target:
                raise ApiError(400, "Укажите ник игрока")
            with db() as conn:
                me = self.require_user(conn)
                cur = conn.execute(
                    """DELETE FROM friend_invites
                       WHERE from_id = ? AND to_id = (SELECT id FROM users WHERE name_key = ?)""",
                    (me["id"], target),
                )
                if cur.rowcount == 0:
                    raise ApiError(404, "Приглашение не найдено")
            self.send_json(200, {"ok": True})
            return

        if path == "/api/friends/remove":
            data = self.read_json()
            target = str(data.get("target") or "").strip().lower()
            if not target:
                raise ApiError(400, "Укажите ник друга")
            with db() as conn:
                me = self.require_user(conn)
                friend = conn.execute(
                    "SELECT id FROM users WHERE name_key = ?", (target,)
                ).fetchone()
                if not friend:
                    raise ApiError(404, "Игрок не найден")
                cur = conn.execute(
                    "DELETE FROM friends WHERE user_id = ? AND friend_id = ?",
                    (me["id"], friend["id"]),
                )
                conn.execute(
                    "DELETE FROM friends WHERE user_id = ? AND friend_id = ?",
                    (friend["id"], me["id"]),
                )
                if cur.rowcount == 0:
                    raise ApiError(404, "Этого игрока нет в друзьях")
            self.send_json(200, {"ok": True})
            return

        if path == "/api/messages/send":
            # Сообщение другу (взаимная дружба обязательна).
            data = self.read_json()
            target = str(data.get("target") or "").strip().lower()
            text = str(data.get("text") or "").strip()
            if not target:
                raise ApiError(400, "Укажите получателя")
            if not text or len(text) > 1000:
                raise ApiError(400, "Сообщение: 1–1000 символов")
            with db() as conn:
                me = self.require_user(conn)
                friend = conn.execute(
                    """SELECT u.id FROM friends f JOIN users u ON u.id = f.friend_id
                       WHERE f.user_id = ? AND u.name_key = ?""",
                    (me["id"], target),
                ).fetchone()
                if not friend:
                    raise ApiError(404, "Игрок не найден в друзьях")
                conn.execute(
                    "INSERT INTO messages (from_id, to_id, text, read, created_at) VALUES (?, ?, ?, 0, ?)",
                    (me["id"], friend["id"], text, int(time.time())),
                )
            self.send_json(200, {"ok": True})
            return

        if path == "/api/tfa/verify":
            # Второй шаг входа: pending_token + 6-значный код из письма.
            data = self.read_json()
            pending = str(data.get("pending_token") or "")
            code = str(data.get("code") or "").strip()
            if not pending or not re.fullmatch(r"\d{6}", code):
                raise ApiError(400, "Введите 6-значный код из письма")
            if too_many_attempts(ip):
                raise ApiError(429, "Слишком много попыток. Попробуйте позже.")
            note_attempt(ip)
            with db() as conn:
                row = conn.execute(
                    """SELECT u.* FROM tfa t JOIN users u ON u.id = t.user_id
                       WHERE t.pending_token = ?""",
                    (pending,),
                ).fetchone()
                if not row:
                    raise ApiError(400, "Сессия подтверждения не найдена. Войдите заново.")
                if not verify_tfa_code(conn, row["id"], code):
                    raise ApiError(401, "Неверный или просроченный код")
                reset_attempts(ip)
                token = create_session(conn, row["id"], self.headers.get("User-Agent") or "", ip)
                self.send_json(200, {"token": token, "user": user_payload(conn, row)},
                               cookies=[self.session_cookie(token)])
            return

        if path == "/api/tfa/enable":
            # Включить 2FA: нужен пароль; код приходит на email, подтверждение — /api/tfa/confirm.
            data = self.read_json()
            password = str(data.get("password") or "")
            with db() as conn:
                row = self.require_user(conn)
                if not verify_password(password, row["pass_hash"]):
                    raise ApiError(401, "Неверный пароль")
                email = row["email"] if "email" in row.keys() else None
                if not email:
                    raise ApiError(400, "Сначала добавьте email в профиле")
                pending, masked = issue_tfa_code(conn, row)
            self.send_json(200, {"pending_token": pending, "email": masked})
            return

        if path == "/api/tfa/confirm":
            # Подтверждение включения 2FA кодом из письма.
            data = self.read_json()
            pending = str(data.get("pending_token") or "")
            code = str(data.get("code") or "").strip()
            if not pending or not re.fullmatch(r"\d{6}", code):
                raise ApiError(400, "Введите 6-значный код из письма")
            with db() as conn:
                row = self.require_user(conn)
                tfa_row = conn.execute(
                    "SELECT user_id FROM tfa WHERE user_id = ? AND pending_token = ?",
                    (row["id"], pending),
                ).fetchone()
                if not tfa_row:
                    raise ApiError(400, "Сессия подтверждения не найдена. Начните заново.")
                if not verify_tfa_code(conn, row["id"], code):
                    raise ApiError(401, "Неверный или просроченный код")
                conn.execute("UPDATE tfa SET enabled = 1 WHERE user_id = ?", (row["id"],))
            self.send_json(200, {"ok": True, "enabled": True})
            return

        if path == "/api/tfa/disable":
            data = self.read_json()
            password = str(data.get("password") or "")
            with db() as conn:
                row = self.require_user(conn)
                if not verify_password(password, row["pass_hash"]):
                    raise ApiError(401, "Неверный пароль")
                conn.execute(
                    """UPDATE tfa SET enabled = 0, code_hash = '', code_expires = 0,
                              code_attempts = 0, pending_token = ''
                       WHERE user_id = ?""",
                    (row["id"],),
                )
            self.send_json(200, {"ok": True, "enabled": False})
            return

        if path.startswith("/api/admin/rights"):
            # Назначение/снятие админ-прав (только для разработчиков).
            data = self.read_json()
            target = str(data.get("name") or "").strip().lower()
            if not target:
                raise ApiError(400, "Укажите ник игрока")
            with db() as conn:
                admin = self.require_admin(conn)
                row = conn.execute(
                    "SELECT id, name FROM users WHERE name_key = ?", (target,)
                ).fetchone()
                if not row:
                    raise ApiError(404, "Игрок не найден")
                if row["id"] == admin["id"]:
                    raise ApiError(400, "Нельзя изменить собственные права")
                if path == "/api/admin/rights/grant":
                    if is_admin_row(conn, row):
                        raise ApiError(409, "Игрок уже разработчик")
                    conn.execute(
                        """INSERT INTO admin_rights (user_id, granted_by, created_at)
                           VALUES (?, ?, ?)
                           ON CONFLICT(user_id) DO NOTHING""",
                        (row["id"], admin["id"], int(time.time())),
                    )
                    log_admin_action(conn, admin["name"], "grant-admin", row["name"],
                                     "выданы права разработчика")
                else:  # revoke
                    cur = conn.execute("DELETE FROM admin_rights WHERE user_id = ?", (row["id"],))
                    if cur.rowcount == 0:
                        raise ApiError(404, "У игрока нет назначенных прав")
                    log_admin_action(conn, admin["name"], "revoke-admin", row["name"],
                                     "права разработчика сняты")
            self.send_json(200, {"ok": True})
            return

        if path == "/api/me/export":
            # GDPR: выгрузка всех данных игрока в JSON.
            with db() as conn:
                row = self.require_user(conn)
                friends = conn.execute(
                    """SELECT u.name, u.best FROM friends f
                       JOIN users u ON u.id = f.friend_id
                       WHERE f.user_id = ? ORDER BY u.best DESC""",
                    (row["id"],),
                ).fetchall()
                export = {
                    "exported_at": int(time.time()) * 1000,
                    "account": {
                        "name": row["name"],
                        "created": row["created_at"] * 1000,
                        "email": row["email"],
                        "avatar": row["avatar"],
                    },
                    "stats": {
                        "best": row["best"],
                        "games": row["games"],
                        "kills": row["kills"],
                    },
                    "friends": [{"name": f["name"], "best": f["best"]} for f in friends],
                    "sessions": conn.execute(
                        """SELECT created_at * 1000 AS created, expires_at * 1000 AS expires
                           FROM sessions WHERE user_id = ?""",
                        (row["id"],),
                    ).fetchall(),
                    "note": "Пароли не экспортируются — они хранятся только как необратимые хэши.",
                }
                export["sessions"] = [dict(s) for s in export["sessions"]]
            self.send_json(200, export)
            return

        if path == "/api/me/delete":
            # GDPR: безвозвратное удаление собственного аккаунта (нужен пароль).
            data = self.read_json()
            password = str(data.get("password") or "")
            with db() as conn:
                row = self.require_user(conn)
                if not verify_password(password, row["pass_hash"]):
                    raise ApiError(401, "Неверный пароль")
                conn.execute("DELETE FROM users WHERE id = ?", (row["id"],))
            self.send_json(200, {"ok": True}, cookies=[self.clear_cookie()])
            return

        if path.startswith("/api/admin/"):
            data = self.read_json()
            target = str(data.get("name") or "").strip().lower()

            if path in ("/api/admin/ban", "/api/admin/unban"):
                pass  # этим эндпоинтам нужен IP (или ник для поиска IP), проверка ниже
            elif not target:
                raise ApiError(400, "Укажите ник игрока")

            if path == "/api/admin/reset-password":
                password = str(data.get("password") or "")
                if len(password) < PASSWORD_MIN:
                    raise ApiError(400, f"Пароль: минимум {PASSWORD_MIN} символов")
                if len(password) > 200:
                    raise ApiError(400, "Пароль слишком длинный")
                with db() as conn:
                    admin = self.require_admin(conn)
                    row = conn.execute(
                        "SELECT id, name, email FROM users WHERE name_key = ?", (target,)
                    ).fetchone()
                    if not row:
                        raise ApiError(404, "Игрок не найден")
                    conn.execute(
                        "UPDATE users SET pass_hash = ? WHERE id = ?",
                        (hash_password(password), row["id"]),
                    )
                    # Сбрасываем входы этого игрока — старый пароль больше не работает.
                    conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
                    log_admin_action(conn, admin["name"], "reset-password", row["name"],
                                     "все сессии сброшены")
                    # Уведомляем по email, если он есть
                    if row["email"]:
                        send_email(
                            row["email"],
                            "Твой пароль в Space Shooter изменён 🔑",
                            f"Привет, {row['name']}!\n\n"
                            f"Пароль твоего аккаунта был изменён администратором.\n"
                            f"Если это был не ты — срочно свяжись с поддержкой!\n\n"
                            f"(Инициировал: {admin['name']})",
                        )
                self.send_json(200, {"ok": True})
                return

            if path == "/api/admin/edit-stats":
                stats = {}
                for field in ("best", "games", "kills"):
                    if field in data:
                        try:
                            value = int(data[field])
                        except (TypeError, ValueError):
                            raise ApiError(400, f"Поле «{field}» должно быть целым числом")
                        if value < 0 or value > 1_000_000:
                            raise ApiError(400, f"Поле «{field}»: 0–1000000")
                        stats[field] = value
                if not stats:
                    raise ApiError(400, "Нет полей для изменения")
                sets = ", ".join(f"{k} = ?" for k in stats)
                with db() as conn:
                    admin = self.require_admin(conn)
                    before = conn.execute(
                        "SELECT name, best, games, kills FROM users WHERE name_key = ?",
                        (target,),
                    ).fetchone()
                    if not before:
                        raise ApiError(404, "Игрок не найден")
                    conn.execute(
                        f"UPDATE users SET {sets} WHERE name_key = ?",
                        (*stats.values(), target),
                    )
                    log_admin_action(
                        conn, admin["name"], "edit-stats", before["name"],
                        f"было best={before['best']} games={before['games']} kills={before['kills']}"
                        f" -> стало {', '.join(f'{k}={v}' for k, v in stats.items())}",
                    )
                self.send_json(200, {"ok": True})
                return

            if path == "/api/admin/delete-user":
                with db() as conn:
                    admin = self.require_admin(conn)
                    row = conn.execute(
                        "SELECT id, name FROM users WHERE name_key = ?", (target,)
                    ).fetchone()
                    if not row:
                        raise ApiError(404, "Игрок не найден")
                    if row["id"] == admin["id"]:
                        raise ApiError(400, "Нельзя удалить самого себя")
                    if is_admin_row(conn, row):
                        raise ApiError(403, "Нельзя удалить аккаунт разработчика")
                    conn.execute("DELETE FROM users WHERE id = ?", (row["id"],))
                    log_admin_action(conn, admin["name"], "delete-user", row["name"],
                                     "аккаунт, статистика и сессии удалены")
                self.send_json(200, {"ok": True})
                return

            if path == "/api/admin/ban":
                ip = str(data.get("ip") or "").strip()
                if not ip and target:
                    # Бан по нику: берём IP, с которого игрок заходил последним.
                    with db() as peek:
                        row = peek.execute(
                            "SELECT id, last_ip, name FROM users WHERE name_key = ?", (target,)
                        ).fetchone()
                        if row is not None and is_admin_row(peek, row):
                            raise ApiError(403, "Нельзя заблокировать аккаунт разработчика")
                    if not row:
                        raise ApiError(404, "Игрок не найден")
                    if not row["last_ip"]:
                        raise ApiError(400, "У игрока нет сохранённого IP — он ещё не входил")
                    ip = row["last_ip"]
                if not ip:
                    raise ApiError(400, "Укажите ник или IP")
                reason = str(data.get("reason") or "").strip()[:200]
                try:
                    days = int(data.get("days") or 0)
                except (TypeError, ValueError):
                    raise ApiError(400, "Срок бана: целое число дней (0 — навсегда)")
                if days < 0 or days > 3650:
                    raise ApiError(400, "Срок бана: 0–3650 дней")
                expires = int(time.time()) + days * 86400 if days else None
                with db() as conn:
                    admin = self.require_admin(conn)
                    # Защита: нельзя забанить IP, под которым работает любой админ
                    # (из ADMIN_NAMES или с назначенными правами).
                    admin_ips = {
                        r["last_ip"] for r in conn.execute(
                            """SELECT last_ip FROM users
                               WHERE name_key IN ({})
                                  OR id IN (SELECT user_id FROM admin_rights)""".format(
                                ", ".join("?" * len(ADMIN_NAMES))
                            ),
                            tuple(ADMIN_NAMES),
                        ) if r["last_ip"]
                    }
                    if ip in admin_ips:
                        raise ApiError(403, "Этот IP принадлежит аккаунту разработчика")
                    if ban_for_ip(conn, ip):
                        raise ApiError(409, "Этот IP уже заблокирован")
                    conn.execute(
                        """INSERT INTO banned_ips (ip, reason, created_at, created_by, expires_at)
                           VALUES (?, ?, ?, ?, ?)""",
                        (ip, reason, int(time.time()), admin["name"], expires),
                    )
                    # Бана сразу почувствовали: снимаем активные сессии игроков с этого IP.
                    conn.execute(
                        """DELETE FROM sessions WHERE user_id IN
                           (SELECT id FROM users WHERE last_ip = ?)""",
                        (ip,),
                    )
                    log_admin_action(conn, admin["name"], "ban",
                                     f"ip={ip}",
                                     f"reason={reason or '—'} days={days or '∞'}")
                self.send_json(200, {"ok": True, "ip": ip})
                return

            if path == "/api/admin/unban":
                ip = str(data.get("ip") or "").strip()
                if not ip:
                    raise ApiError(400, "Укажите IP")
                with db() as conn:
                    admin = self.require_admin(conn)
                    cur = conn.execute("DELETE FROM banned_ips WHERE ip = ?", (ip,))
                    if cur.rowcount == 0:
                        raise ApiError(404, "Такого бана нет")
                    log_admin_action(conn, admin["name"], "unban", f"ip={ip}", "")
                self.send_json(200, {"ok": True})
                return

        raise ApiError(404, "Неизвестный метод API")

    # ------------------------------------------------------------- статика
    def serve_static(self, raw_path: str) -> None:
        rel = unquote(raw_path.split("?", 1)[0]).lstrip("/")
        if rel in ("", "index.html"):
            target = SITE_DIR / "index.html"
        else:
            target = (SITE_DIR / rel).resolve()
            if not str(target).startswith(str(SITE_DIR)):
                self.send_json(403, {"error": "Доступ запрещён"})
                return

        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            body = b"404 Not Found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        ctype, _ = mimetypes.guess_type(str(target))
        ctype = ctype or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)


def main() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8735"))
    db_init()
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    print(f"Space Shooter: http://{host}:{port}")
    print(f"База данных: {DB_PATH}")
    print("Ctrl+C — остановить сервер")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nСервер остановлен")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
