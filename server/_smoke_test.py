"""Быстрая проверка API аккаунтов без браузера."""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("SS_BASE", "http://127.0.0.1:8735")


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
    name = "Tester_" + str(int(time.time()))
    print("health:", call("GET", "/api/health"))
    print("register:", call("POST", "/api/register", {"name": name, "password": "secret123"}))
    status, payload = call("POST", "/api/login", {"name": name, "password": "secret123"})
    print("login:", status)
    token = payload.get("token")
    print("bad password:", call("POST", "/api/login", {"name": name, "password": "wrong"}))
    print("dup name:", call("POST", "/api/register", {"name": name.upper(), "password": "secret123"}))
    print("me:", call("GET", "/api/me", token=token))
    print("score 42:", call("POST", "/api/score", {"score": 42}, token=token))
    print("score 17:", call("POST", "/api/score", {"score": 17}, token=token))
    print("me no token:", call("GET", "/api/me"))
    print("leaderboard:", call("GET", "/api/leaderboard"))
    print("logout:", call("POST", "/api/logout", token=token))
    print("me after logout:", call("GET", "/api/me", token=token))


if __name__ == "__main__":
    sys.exit(main())
