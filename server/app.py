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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse, parse_qs

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
SESSION_TTL = 60 * 60 * 24 * 30  # 30 дней
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

# ------------------------------------------------------------------- почта
def send_email(to_email: str, subject: str, body: str) -> bool:
    """Отправить email через SMTP. Возвращает True при успехе."""
    if not SMTP_USER or not SMTP_PASS:
        print("SMTP не настроен — письмо не отправлено:", to_email, subject)
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
        print("Письмо отправлено:", to_email)
        return True
    except Exception as exc:
        print("Ошибка отправки письма:", exc)
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
                expires_at BIGINT  NOT NULL
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
            CREATE TABLE IF NOT EXISTS admin_logs (
                id         {id_type},
                admin_name TEXT   NOT NULL,
                action     TEXT   NOT NULL,
                target     TEXT   NOT NULL DEFAULT '',
                details    TEXT   NOT NULL DEFAULT '',
                created_at BIGINT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_users_best   ON users(best DESC);
            """
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
def create_session(conn: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    conn.execute(
        "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token, user_id, now, now + SESSION_TTL),
    )
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
    return token


def user_by_token(conn: sqlite3.Connection, token: str) -> sqlite3.Row | None:
    if not token:
        return None
    row = conn.execute(
        """SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token = ? AND s.expires_at > ?""",
        (token, int(time.time())),
    ).fetchone()
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
    return {
        "name": row["name"],
        "created": row["created_at"] * 1000,
        "best": row["best"],
        "games": row["games"],
        "kills": row["kills"],
        "rank": rank["rank"],
        "total": rank["total"],
        "admin": is_admin(row["name"]),
        "avatar": row["avatar"],
        "email": row["email"] if "email" in row.keys() else None,
        "friends": friends,
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
        # За прокси (Render, nginx) адрес сокета — это адрес прокси, поэтому
        # берём первый адрес из X-Forwarded-For, иначе лимит попыток был бы общим.
        forwarded = self.headers.get("X-Forwarded-For") or ""
        if forwarded:
            return forwarded.split(",")[0].strip()
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
        row = user_by_token(conn, self.session_token())
        if not row:
            raise ApiError(401, "Требуется вход")
        return row

    def require_admin(self, conn: sqlite3.Connection) -> sqlite3.Row:
        row = self.require_user(conn)
        if not is_admin(row["name"]):
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
                                "admin": is_admin(r["name"]),
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
            if len(password) < 6:
                raise ApiError(400, "Пароль: минимум 6 символов")
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
                token = create_session(conn, row["id"])
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
                token = create_session(conn, row["id"])
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
            data = self.read_json()
            email = str(data.get("email") or "").strip()
            if email and not EMAIL_RE.match(email):
                raise ApiError(400, "Некорректный email")
            with db() as conn:
                row = self.require_user(conn)
                conn.execute(
                    "UPDATE users SET email = ? WHERE id = ?",
                    (email if email else None, row["id"]),
                )
                row = conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
                self.send_json(200, {"user": user_payload(conn, row)})
            return

        if path == "/api/friends/add":
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
                now = int(time.time())
                # Дружба взаимная: одна запись на каждое направление.
                conn.execute(
                    "INSERT INTO friends (user_id, friend_id, created_at) VALUES (?, ?, ?)",
                    (me["id"], friend["id"], now),
                )
                conn.execute(
                    "INSERT INTO friends (user_id, friend_id, created_at) VALUES (?, ?, ?)",
                    (friend["id"], me["id"], now),
                )
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
                if len(password) < 6:
                    raise ApiError(400, "Пароль: минимум 6 символов")
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
                        raise ApiError(400, "Нельзя удалить собственный аккаунт")
                    if is_admin(row["name"]):
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
                            "SELECT last_ip, name FROM users WHERE name_key = ?", (target,)
                        ).fetchone()
                    if not row:
                        raise ApiError(404, "Игрок не найден")
                    if is_admin(row["name"]):
                        raise ApiError(403, "Нельзя заблокировать аккаунт разработчика")
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
                    # Защита: нельзя забанить IP, под которым работает любой админ.
                    admin_ips = {
                        r["last_ip"] for r in conn.execute(
                            "SELECT last_ip FROM users WHERE name_key IN ({})".format(
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
