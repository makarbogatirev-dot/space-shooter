#!/usr/bin/env python3
"""Space Shooter — сервер аккаунтов.

Раздаёт статический сайт из ../site и JSON API поверх SQLite.
Пароли хранятся как PBKDF2-HMAC-SHA256 с индивидуальной солью, в открытом
виде не сохраняются нигде. Сессии — случайные токены в таблице sessions.

Запуск:  python server/app.py
Переменные окружения:
    PORT         — порт (по умолчанию 8735)
    HOST         — адрес (по умолчанию 127.0.0.1, для деплоя 0.0.0.0)
    DB_PATH      — путь к файлу БД (по умолчанию server/data/accounts.db)
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
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs

BASE_DIR = Path(__file__).resolve().parent
SITE_DIR = (BASE_DIR.parent / "site").resolve()
DB_PATH = Path(os.environ.get("DB_PATH") or (BASE_DIR / "data" / "accounts.db")).resolve()

PBKDF2_ITERATIONS = 200_000
SALT_BYTES = 16
SESSION_TTL = 60 * 60 * 24 * 30  # 30 дней
MAX_BODY = 8 * 1024
NAME_RE = re.compile(r"^[A-Za-zА-Яа-яЁё0-9_]{3,20}$")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "")

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
def db_connect() -> sqlite3.Connection:
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


def db_init() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL UNIQUE,      -- отображаемый ник
                name_key    TEXT    NOT NULL UNIQUE,      -- ник в нижнем регистре
                pass_hash   TEXT    NOT NULL,
                created_at  INTEGER NOT NULL,
                best        INTEGER NOT NULL DEFAULT 0,
                games       INTEGER NOT NULL DEFAULT 0,
                kills       INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token      TEXT    PRIMARY KEY,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_users_best   ON users(best DESC);
            """
        )


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
    return {
        "name": row["name"],
        "created": row["created_at"] * 1000,
        "best": row["best"],
        "games": row["games"],
        "kills": row["kills"],
        "rank": rank["rank"],
        "total": rank["total"],
        "admin": is_admin(row["name"]),
    }


def leaderboard(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    rows = conn.execute(
        "SELECT name, best FROM users WHERE best > 0 ORDER BY best DESC, name LIMIT ?",
        (limit,),
    ).fetchall()
    return [{"name": r["name"], "best": r["best"]} for r in rows]


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
        # Авторизация идёт через заголовок Authorization, cookie не используются,
        # поэтому "*" безопасен и позволяет держать сайт на GitHub Pages.
        if not self.headers.get("Origin"):
            return
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN or "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Max-Age", "86400")

    def send_json(self, status: int, payload: dict | list) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors_headers()
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

    def require_user(self, conn: sqlite3.Connection) -> sqlite3.Row:
        row = user_by_token(conn, self.bearer_token())
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
                    self.send_json(200, {
                        "users": [
                            {
                                "name": r["name"],
                                "created": r["created_at"] * 1000,
                                "best": r["best"],
                                "games": r["games"],
                                "kills": r["kills"],
                                "admin": is_admin(r["name"]),
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
                        "SELECT COUNT(*) FROM sessions WHERE expires_at > ?",
                        (int(time.time()),),
                    ).fetchone()[0]
                    self.send_json(200, {
                        "users": totals["users"],
                        "games": totals["games"],
                        "kills": totals["kills"],
                        "best": totals["best"],
                        "sessions": active,
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

            if not NAME_RE.match(name):
                raise ApiError(400, "Ник: 3–20 символов, буквы, цифры и _")
            if len(password) < 6:
                raise ApiError(400, "Пароль: минимум 6 символов")
            if len(password) > 200:
                raise ApiError(400, "Пароль слишком длинный")

            note_attempt(ip)
            with db() as conn:
                if conn.execute(
                    "SELECT 1 FROM users WHERE name_key = ?", (name.lower(),)
                ).fetchone():
                    raise ApiError(409, "Этот ник уже занят")
                conn.execute(
                    """INSERT INTO users (name, name_key, pass_hash, created_at)
                       VALUES (?, ?, ?, ?)""",
                    (name, name.lower(), hash_password(password), int(time.time())),
                )
                row = conn.execute("SELECT * FROM users WHERE name_key = ?", (name.lower(),)).fetchone()
                token = create_session(conn, row["id"])
                reset_attempts(ip)
                self.send_json(201, {"token": token, "user": user_payload(conn, row)})
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
                row = conn.execute("SELECT * FROM users WHERE name_key = ?", (name.lower(),)).fetchone()
                if not row or not verify_password(password, row["pass_hash"]):
                    raise ApiError(401, "Неверный ник или пароль")
                reset_attempts(ip)
                token = create_session(conn, row["id"])
                self.send_json(200, {"token": token, "user": user_payload(conn, row)})
            return

        if path == "/api/logout":
            token = self.bearer_token()
            with db() as conn:
                if token:
                    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            self.send_json(200, {"ok": True})
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
                conn.execute(
                    """UPDATE users
                       SET best = MAX(best, ?), games = games + 1, kills = kills + ?
                       WHERE id = ?""",
                    (score, score, row["id"]),
                )
                row = conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
                self.send_json(200, {"user": user_payload(conn, row)})
            return

        if path.startswith("/api/admin/"):
            data = self.read_json()
            target = str(data.get("name") or "").strip().lower()
            if not target:
                raise ApiError(400, "Укажите ник игрока")

            if path == "/api/admin/reset-password":
                password = str(data.get("password") or "")
                if len(password) < 6:
                    raise ApiError(400, "Пароль: минимум 6 символов")
                if len(password) > 200:
                    raise ApiError(400, "Пароль слишком длинный")
                with db() as conn:
                    self.require_admin(conn)
                    row = conn.execute(
                        "SELECT id FROM users WHERE name_key = ?", (target,)
                    ).fetchone()
                    if not row:
                        raise ApiError(404, "Игрок не найден")
                    conn.execute(
                        "UPDATE users SET pass_hash = ? WHERE id = ?",
                        (hash_password(password), row["id"]),
                    )
                    # Сбрасываем входы этого игрока — старый пароль больше не работает.
                    conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
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
                    self.require_admin(conn)
                    cur = conn.execute(
                        f"UPDATE users SET {sets} WHERE name_key = ?",
                        (*stats.values(), target),
                    )
                    if cur.rowcount == 0:
                        raise ApiError(404, "Игрок не найден")
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
                    conn.execute("DELETE FROM users WHERE id = ?", (row["id"],))
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
