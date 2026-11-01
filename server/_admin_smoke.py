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
               DB_PATH=str(Path(tmp) / "test.db"), ADMIN_NAMES="DevQA")
    srv = subprocess.Popen([sys.executable, str(Path(__file__).parent / "app.py")], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except subprocess.TimeoutExpired:
            srv.kill()


if __name__ == "__main__":
    main()
