"""Проверка админ-API: запускает временный сервер на своей БД и прогоняет сценарий."""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

PORT = "8931"
BASE = "http://127.0.0.1:" + PORT


def call(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def main():
    tmp = tempfile.mkdtemp(prefix="ss-admin-")
    env = dict(os.environ, PORT=PORT, HOST="127.0.0.1",
               DB_PATH=str(Path(tmp) / "test.db"), ADMIN_NAMES="DevQA",
               SMTP_DRY_RUN="1", PYTHONIOENCODING="utf-8")
    log_path = str(Path(tmp) / "server.log")
    log_file = open(log_path, "w", encoding="utf-8")
    srv = subprocess.Popen([sys.executable, str(Path(__file__).parent / "app.py")], env=env,
                           stdout=log_file, stderr=subprocess.STDOUT)
    try:
        for _ in range(40):
            try:
                call("GET", "/api/health"); break
            except Exception:
                time.sleep(0.25)

        st, p = call("POST", "/api/register", {"name": "DevQA", "password": "devpass1"})
        print("register admin:", st, p.get("user", {}).get("admin"))
        at = p.get("token")
        st, p = call("POST", "/api/register", {"name": "Player1", "password": "pass123"})
        print("register user:", st, p.get("user", {}).get("admin"))
        pt = p.get("token")
        call("POST", "/api/score", {"score": 100}, token=pt)

        print("stats as user:", call("GET", "/api/admin/stats", token=pt)[0])
        print("users as user:", call("GET", "/api/admin/users", token=pt)[0])
        print("stats no token:", call("GET", "/api/admin/stats")[0])
        st, p = call("GET", "/api/admin/stats", token=at)
        print("stats as admin:", st, p)
        st, p = call("GET", "/api/admin/users?q=play", token=at)
        print("search 'play':", st, [u["name"] for u in p.get("users", [])])

        print("reset pass:", call("POST", "/api/admin/reset-password",
                                  {"name": "player1", "password": "newpass9"}, token=at))
        print("login old pass:", call("POST", "/api/login", {"name": "Player1", "password": "pass123"})[0])
        st, p = call("POST", "/api/login", {"name": "Player1", "password": "newpass9"})
        print("login new pass:", st)
        print("old session dead:", call("GET", "/api/me", token=pt)[0])

        print("edit stats:", call("POST", "/api/admin/edit-stats",
                                  {"name": "Player1", "best": 55, "games": 3}, token=at))
        st, p = call("POST", "/api/login", {"name": "Player1", "password": "newpass9"})
        pt = p.get("token")
        st, p = call("GET", "/api/me", token=pt)
        print("after edit:", st, {k: p["user"][k] for k in ("best", "games", "kills")})
        print("edit bad value:", call("POST", "/api/admin/edit-stats",
                                      {"name": "Player1", "best": -5}, token=at))
        print("edit no fields:", call("POST", "/api/admin/edit-stats",
                                      {"name": "Player1"}, token=at))
        print("edit missing user:", call("POST", "/api/admin/edit-stats",
                                         {"name": "Ghost", "best": 1}, token=at))

        print("self delete:", call("POST", "/api/admin/delete-user",
                                   {"name": "DevQA"}, token=at))
        print("delete user:", call("POST", "/api/admin/delete-user",
                                   {"name": "Player1"}, token=at))
        print("users after delete:", call("GET", "/api/admin/users", token=at))

        # --- Баны ---
        # Регистрируем нового игрока с IP из X-Forwarded-For (эмуляция прокси).
        def call_ip(method, path, body=None, ip=None):
            data = json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request(BASE + path, data=data, method=method)
            if data:
                req.add_header("Content-Type", "application/json")
            if ip:
                req.add_header("X-Forwarded-For", ip)
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status, json.loads(resp.read().decode())
            except urllib.error.HTTPError as exc:
                return exc.code, json.loads(exc.read().decode() or "{}")

        st, p = call_ip("POST", "/api/register", {"name": "Victim", "password": "pass123"},
                        ip="9.9.9.9")
        print("register victim:", st, "ip seen:", p.get("user", {}).get("name"))
        st, p = call("GET", "/api/admin/users?q=victim", token=at)
        print("victim ip in list:", p["users"][0]["ip"], "banned:", p["users"][0]["banned"])
        print("ban by name:", call("POST", "/api/admin/ban",
                                   {"name": "Victim", "reason": "читы", "days": 7}, token=at))
        print("ban dup:", call("POST", "/api/admin/ban", {"ip": "9.9.9.9"}, token=at))
        print("bans list:", call("GET", "/api/admin/bans", token=at))
        print("victim login while banned:", call_ip(
            "POST", "/api/login", {"name": "Victim", "password": "pass123"}, ip="9.9.9.9"))
        print("victim register from banned ip:", call_ip(
            "POST", "/api/register", {"name": "Victim2", "password": "pass123"}, ip="9.9.9.9"))
        st, p = call("GET", "/api/admin/users?q=victim", token=at)
        print("victim banned flag:", p["users"][0]["banned"])
        print("other ip ok:", call_ip(
            "POST", "/api/login", {"name": "Victim", "password": "pass123"}, ip="8.8.8.8")[0])
        print("unban:", call("POST", "/api/admin/unban", {"ip": "9.9.9.9"}, token=at))
        print("unban missing:", call("POST", "/api/admin/unban", {"ip": "1.2.3.4"}, token=at))
        print("victim login after unban:", call_ip(
            "POST", "/api/login", {"name": "Victim", "password": "pass123"}, ip="9.9.9.9")[0])
        print("ban as user:", call("POST", "/api/admin/ban", {"ip": "9.9.9.9"})[0])

        # --- Скачивания ---
        print("downloads list:", call("GET", "/api/downloads"))
        st, p = call("POST", "/api/download/hit", {"version": "v1.0", "format": "installer"}, token=None)
        print("hit v1.0 installer:", st, p.get("count"))
        st, p = call("POST", "/api/download/hit", {"version": "v1.0", "format": "installer"}, token=None)
        print("hit dup from same IP (rate-limited):", st)
        st, p = call("POST", "/api/download/hit", {"version": "v1.1", "format": "portable"}, token=None)
        print("hit v1.1 portable:", st, p.get("count"))
        st, p = call("GET", "/api/downloads")
        for d in p.get("downloads", []):
            print("  dl:", d["version"], d["format"], "=", d["count"])
        st, p = call("POST", "/api/download/hit", {"version": "v99", "format": "installer"}, token=None)
        print("bad version:", st, p.get("error"))

        # --- 2FA через email ---
        st, p = call_ip("POST", "/api/register",
                        {"name": "Alice", "password": "alicepw1", "email": "a@ex.com"}, ip="7.7.7.7")
        print("register alice:", st)
        st, p = call_ip("POST", "/api/login", {"name": "Alice", "password": "alicepw1"}, ip="7.7.7.7")
        alicet = p.get("token")
        print("alice login (no 2FA yet):", st, bool(alicet))
        print("enable 2FA:", call("POST", "/api/tfa/enable", {"password": "alicepw1"}, token=alicet))
        st, p = call_ip("POST", "/api/login", {"name": "Alice", "password": "alicepw1"}, ip="7.7.7.7")
        pending = p.get("pending_token", "")
        print("login 2FA step1:", st, p.get("tfa_required"), "email:", p.get("email"))
        print("verify wrong code:", call_ip("POST", "/api/tfa/verify",
                                            {"pending_token": pending, "code": "000000"}, ip="7.7.7.7"))
        # Достаём реальный код из лога сервера (SMTP_DRY_RUN).
        log_file.flush()
        code = ""
        with open(log_path, encoding="utf-8") as lf:
            import re as _re
            for line in lf:
                m = _re.search(r"код подтверждения входа: (\d{6})", line)
                if m:
                    code = m.group(1)
        print("code from server log:", bool(code))
        st, p = call_ip("POST", "/api/tfa/verify",
                        {"pending_token": pending, "code": code}, ip="7.7.7.7")
        print("verify right code:", st, bool(p.get("token")))
        print("tfa status:", call("GET", "/api/tfa/status", token=p.get("token")))
        print("reuse pending:", call_ip("POST", "/api/tfa/verify",
                                         {"pending_token": pending, "code": code}, ip="7.7.7.7")[0])
        print("disable 2FA:", call("POST", "/api/tfa/disable",
                                   {"password": "alicepw1"}, token=p.get("token")))
        st, presp = call_ip("POST", "/api/login", {"name": "Alice", "password": "alicepw1"}, ip="7.7.7.7")
        print("login after disable:", st)
        alice_token = presp.get("token")

        # --- Сообщения друзьям ---
        st, presp = call_ip("POST", "/api/login", {"name": "Victim", "password": "pass123"}, ip="8.8.8.8")
        vict = presp.get("token")
        print("alice->victim not friend:", call("POST", "/api/messages/send",
              {"target": "victim", "text": "privet"}, token=alice_token))
        print("victim add alice:", call("POST", "/api/friends/add",
                                        {"target": "alice"}, token=vict))
        print("alice send:", call("POST", "/api/messages/send",
                                  {"target": "victim", "text": "privet!"}, token=alice_token))
        print("victim read:", call("GET", "/api/messages?with=Alice", token=vict))
        print("victim reply:", call("POST", "/api/messages/send",
                                    {"target": "alice", "text": "hy"}, token=vict))
        st, p = call("GET", "/api/messages?with=Victim", token=alice_token)
        print("alice chat:", st, [(m["from"], m["text"]) for m in p.get("messages", [])])
        print("unread after read:", p.get("unread"))
        print("send too long:", call("POST", "/api/messages/send",
                                     {"target": "victim", "text": "x" * 1001}, token=alice_token)[0])

        # --- Назначение админ-прав ---
        st, p = call("GET", "/api/admin/users", token=at)
        print("alice admin before grant:", [u["admin"] for u in p.get("users", []) if u["name"] == "Alice"])
        print("alice grant (no rights -> 403):", call("POST", "/api/admin/rights/grant",
                                        {"name": "Victim"}, token=alice_token)[0])
        print("dev grant alice:", call("POST", "/api/admin/rights/grant",
                                       {"name": "Alice"}, token=at))
        st, p = call("GET", "/api/admin/users", token=at)
        print("alice admin after grant:", [u["admin"] for u in p.get("users", []) if u["name"] == "Alice"])
        print("alice stats with rights:", call("GET", "/api/admin/stats", token=alice_token)[0])
        print("ban victim by alice:", call("POST", "/api/admin/ban",
                                            {"name": "Victim", "reason": "test", "days": 1}, token=alice_token))
        print("dev revoke alice:", call("POST", "/api/admin/rights/revoke",
                                        {"name": "Alice"}, token=at))
        print("alice stats after revoke:", call("GET", "/api/admin/stats", token=alice_token)[0])
        print("revoke not granted:", call("POST", "/api/admin/rights/revoke",
                                          {"name": "Victim"}, token=at))
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except subprocess.TimeoutExpired:
            srv.kill()
        log_file.close()


if __name__ == "__main__":
    main()
