#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""丧尸围城 · 后端服务

纯 Python 标准库实现 (http.server + sqlite3),无需 pip install。
提供排行榜、存档、成就与全局统计,并托管 static/ 下的游戏本体。

启动:  python server.py            # 默认 http://127.0.0.1:8000
      python server.py --port 9000
      python server.py --open      # 启动后自动打开浏览器
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
# 测试用 ZS_DB 指向独立的库，避免污染真实战绩
DB_PATH = os.environ.get("ZS_DB") or os.path.join(BASE_DIR, "zombie.db")

MAX_BODY = 64 * 1024
WEAPON_IDS = ["pistol", "smg", "shotgun", "rifle", "launcher", "laser"]
ZOMBIE_IDS = ["walker", "runner", "jumper", "spitter", "fat", "boomer", "shield", "brute", "boss"]

# 服务端信任边界：客户端上报的一切都不可信，先钳到物理上可能的范围。
# 分数在游戏里只来自击杀(每只僵尸的经验值 × 连击倍率)，僵尸王经验最高 250，
# 连击倍率最高 ×4，所以单杀分数上限是 1000，取 1.1 倍余量。
MAX_SCORE = 1_000_000
MAX_KILLS = 200_000
MAX_XP_PER_KILL = 1100
SCORE_SLACK = 1_000

# ---------------------------------------------------------------- 成就定义

def _untouched(r):
    return r["duration"] >= 90 and (r["first_damage_at"] is None or r["first_damage_at"] >= 90)


ACHIEVEMENTS = [
    {"id": "first_blood",   "name": "初次猎杀", "icon": "🩸", "tier": "bronze",
     "desc": "一局内击杀至少 1 只僵尸", "check": lambda r: r["kills"] >= 1},
    {"id": "slayer_100",    "name": "百人斩",   "icon": "⚔️", "tier": "silver",
     "desc": "单局击杀 100 只僵尸", "check": lambda r: r["kills"] >= 100},
    {"id": "slayer_500",    "name": "尸山血海", "icon": "💀", "tier": "gold",
     "desc": "单局击杀 500 只僵尸", "check": lambda r: r["kills"] >= 500},
    {"id": "gunner_15",     "name": "军火专家", "icon": "🔫", "tier": "gold",
     "desc": "任意枪械升到 15 级", "check": lambda r: r["max_weapon_level"] >= 15},
    {"id": "full_arsenal",  "name": "全副武装", "icon": "🎒", "tier": "silver",
     "desc": "单局集齐全部 6 把枪", "check": lambda r: r["weapon_count"] >= 6},
    {"id": "king_slayer",   "name": "弑　王",   "icon": "👑", "tier": "gold",
     "desc": "击杀僵尸王", "check": lambda r: r["boss_kills"] >= 1},
    {"id": "untouchable",   "name": "不　可　触", "icon": "🛡️", "tier": "platinum",
     "desc": "单局前 90 秒未受任何伤害", "check": _untouched},
    {"id": "grenadier",     "name": "手雷达人", "icon": "💣", "tier": "silver",
     "desc": "单局用手雷炸死 30 只僵尸", "check": lambda r: r["grenade_kills"] >= 30},
    {"id": "score_10k",     "name": "万分猎手", "icon": "🏅", "tier": "silver",
     "desc": "单局得分达到 10000", "check": lambda r: r["score"] >= 10000},
    {"id": "score_50k",     "name": "传　说",   "icon": "🏆", "tier": "platinum",
     "desc": "单局得分达到 50000", "check": lambda r: r["score"] >= 50000},
    {"id": "survivor_5m",   "name": "坚　守",   "icon": "⏱️", "tier": "silver",
     "desc": "单局存活 300 秒", "check": lambda r: r["duration"] >= 300},
    {"id": "lone_wolf",     "name": "孤胆英雄", "icon": "🐺", "tier": "gold",
     "desc": "单人模式得分达到 8000", "check": lambda r: r["player_count"] == 1 and r["score"] >= 8000},
    {"id": "dynamic_duo",   "name": "双人同心", "icon": "🤝", "tier": "gold",
     "desc": "双人模式单局击杀 300 只", "check": lambda r: r["player_count"] == 2 and r["kills"] >= 300},
    {"id": "globe_trotter", "name": "环球猎杀", "icon": "🌍", "tier": "platinum",
     "desc": "单局通关全部 3 张地图", "check": lambda r: r["maps_cleared"] >= 3},
]
ACH_BY_ID = {a["id"]: a for a in ACHIEVEMENTS}
TIER_ORDER = {"bronze": 0, "silver": 1, "gold": 2, "platinum": 3}

# ---------------------------------------------------------------- 数据库

_local = threading.local()
WRITE_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  name              TEXT    NOT NULL UNIQUE,
  created_at        TEXT    NOT NULL,
  last_seen         TEXT    NOT NULL,
  best_score        INTEGER NOT NULL DEFAULT 0,
  best_kills        INTEGER NOT NULL DEFAULT 0,
  best_wave         INTEGER NOT NULL DEFAULT 0,
  best_map_name     TEXT    NOT NULL DEFAULT '',
  total_score       INTEGER NOT NULL DEFAULT 0,
  total_kills       INTEGER NOT NULL DEFAULT 0,
  total_runs        INTEGER NOT NULL DEFAULT 0,
  total_time        REAL    NOT NULL DEFAULT 0,
  unlocked_weapons  TEXT    NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS runs (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  player_id         INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
  score             INTEGER NOT NULL,
  kills             INTEGER NOT NULL,
  wave              INTEGER NOT NULL,
  map_index         INTEGER NOT NULL DEFAULT 0,
  map_name          TEXT    NOT NULL DEFAULT '',
  duration          REAL    NOT NULL DEFAULT 0,
  player_count      INTEGER NOT NULL DEFAULT 1,
  maps_cleared      INTEGER NOT NULL DEFAULT 0,
  boss_kills        INTEGER NOT NULL DEFAULT 0,
  grenade_kills     INTEGER NOT NULL DEFAULT 0,
  max_weapon_level  INTEGER NOT NULL DEFAULT 1,
  created_at        TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_score  ON runs(score DESC);
CREATE INDEX IF NOT EXISTS idx_runs_player ON runs(player_id);
CREATE TABLE IF NOT EXISTS run_weapons (
  run_id    INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  weapon_id TEXT    NOT NULL,
  level     INTEGER NOT NULL DEFAULT 1,
  kills     INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (run_id, weapon_id)
);
CREATE TABLE IF NOT EXISTS run_zombies (
  run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  ztype  TEXT    NOT NULL,
  kills  INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (run_id, ztype)
);
CREATE TABLE IF NOT EXISTS player_achievements (
  player_id   INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
  ach_id      TEXT    NOT NULL,
  unlocked_at TEXT    NOT NULL,
  PRIMARY KEY (player_id, ach_id)
);
"""


def db():
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


def close_db():
    """关闭当前线程的数据库连接（测试用完要删库文件时必须先调）。"""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def init_db():
    with WRITE_LOCK:
        db().executescript(SCHEMA)
        db().commit()


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------- 输入清洗

def clamp(v, lo, hi, default=0):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return default
    if n != n or n in (float("inf"), float("-inf")):
        return default
    return int(max(lo, min(hi, n)))


def clean_name(raw):
    s = re.sub(r"[\x00-\x1f<>&\"']", "", str(raw or "")).strip()
    return s[:16] if s else "无名幸存者"


def clean_run(payload):
    p = payload if isinstance(payload, dict) else {}

    weapons, seen = [], set()
    for item in (p.get("weapons") or [])[:12]:
        if not isinstance(item, dict):
            continue
        wid = str(item.get("id", ""))
        if wid not in WEAPON_IDS or wid in seen:
            continue
        seen.add(wid)
        weapons.append({
            "id": wid,
            "level": clamp(item.get("level"), 1, 15, 1),
            "kills": clamp(item.get("kills"), 0, 1_000_000),
        })

    zombies = []
    zmap = p.get("zombies")
    if isinstance(zmap, dict):
        for zid, cnt in list(zmap.items())[:16]:
            if zid in ZOMBIE_IDS:
                zombies.append({"type": zid, "kills": clamp(cnt, 0, 1_000_000)})

    fda = p.get("first_damage_at")
    try:
        fda = float(fda) if fda is not None else None
        if fda is not None and (fda != fda or fda < 0):
            fda = None
        if fda is not None:
            fda = min(fda, 100_000.0)
    except (TypeError, ValueError):
        fda = None

    return {
        "name": clean_name(p.get("name")),
        "score": clamp(p.get("score"), 0, MAX_SCORE),
        "kills": clamp(p.get("kills"), 0, MAX_KILLS),
        "wave": clamp(p.get("wave"), 0, 9999),
        "map_index": clamp(p.get("map_index"), 0, 99),
        "map_name": re.sub(r"[\x00-\x1f<>&\"']", "", str(p.get("map_name") or ""))[:24],
        "duration": clamp(p.get("duration"), 0, 86_400),
        "player_count": 2 if clamp(p.get("player_count"), 1, 2, 1) == 2 else 1,
        "maps_cleared": clamp(p.get("maps_cleared"), 0, 9999),
        "boss_kills": clamp(p.get("boss_kills"), 0, 9999),
        "grenade_kills": clamp(p.get("grenade_kills"), 0, 1_000_000),
        "max_weapon_level": clamp(p.get("max_weapon_level"), 1, 15, 1),
        "weapon_count": len(weapons),
        "first_damage_at": fda,
        "weapons": weapons,
        "zombies": zombies,
    }


# ---------------------------------------------------------------- 业务逻辑

def validate_run(r):
    """拒绝内部不自洽的战绩。分数只可能来自击杀，所以这条不变量对真实对局恒成立。

    注意：这不是反作弊。客户端全程可控，服务端只能挡住明显伪造的值；
    要真正防作弊需要服务端回放/校验战斗过程。
    """
    if r["score"] > r["kills"] * MAX_XP_PER_KILL + SCORE_SLACK:
        return f"score {r['score']} 与击杀数 {r['kills']} 不匹配"
    if r["boss_kills"] > r["kills"]:
        return "僵尸王击杀数超过总击杀数"
    return None


def get_or_create_player(conn, name):
    row = conn.execute("SELECT * FROM players WHERE name = ?", (name,)).fetchone()
    if row:
        return row
    conn.execute(
        "INSERT INTO players (name, created_at, last_seen) VALUES (?, ?, ?)",
        (name, now_iso(), now_iso()),
    )
    return conn.execute("SELECT * FROM players WHERE name = ?", (name,)).fetchone()


def ach_list(unlocked):
    return [
        {"id": a["id"], "name": a["name"], "icon": a["icon"], "tier": a["tier"], "desc": a["desc"],
         "unlocked": a["id"] in unlocked, "unlocked_at": unlocked.get(a["id"])}
        for a in sorted(ACHIEVEMENTS, key=lambda a: TIER_ORDER[a["tier"]])
    ]


def empty_profile(name):
    """新玩家尚未建档：返回零值档案而非 404 —— 对局客户端来说这是正常状态。"""
    return {
        "name": name, "exists": False,
        "best_score": 0, "best_kills": 0, "best_wave": 0, "best_map_name": "",
        "total_score": 0, "total_kills": 0, "total_runs": 0, "total_time": 0.0,
        "created_at": None, "unlocked_weapons": [],
        "achievements": ach_list({}), "achievement_count": 0,
    }


def profile_payload(conn, player_id, name):
    prow = conn.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
    arows = conn.execute(
        "SELECT ach_id, unlocked_at FROM player_achievements WHERE player_id = ?", (player_id,)
    ).fetchall()
    unlocked = {r["ach_id"]: r["unlocked_at"] for r in arows}
    return {
        "name": name, "exists": True,
        "best_score": prow["best_score"],
        "best_kills": prow["best_kills"],
        "best_wave": prow["best_wave"],
        "best_map_name": prow["best_map_name"],
        "total_score": prow["total_score"],
        "total_kills": prow["total_kills"],
        "total_runs": prow["total_runs"],
        "total_time": round(prow["total_time"], 1),
        "created_at": prow["created_at"],
        "unlocked_weapons": json.loads(prow["unlocked_weapons"]),
        "achievements": ach_list(unlocked),
        "achievement_count": len(unlocked),
    }


def submit_run(payload):
    r = clean_run(payload)
    problem = validate_run(r)
    if problem:
        return {"ok": False, "error": problem, "rejected": True}
    with WRITE_LOCK:
        conn = db()
        with conn:
            prow = get_or_create_player(conn, r["name"])
            pid = prow["id"]
            created = now_iso()
            cur = conn.execute(
                """INSERT INTO runs (player_id, score, kills, wave, map_index, map_name,
                       duration, player_count, maps_cleared, boss_kills, grenade_kills,
                       max_weapon_level, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (pid, r["score"], r["kills"], r["wave"], r["map_index"], r["map_name"],
                 r["duration"], r["player_count"], r["maps_cleared"], r["boss_kills"],
                 r["grenade_kills"], r["max_weapon_level"], created),
            )
            run_id = cur.lastrowid

            for w in r["weapons"]:
                conn.execute(
                    "INSERT INTO run_weapons (run_id, weapon_id, level, kills) VALUES (?,?,?,?)",
                    (run_id, w["id"], w["level"], w["kills"]),
                )
            for z in r["zombies"]:
                conn.execute(
                    "INSERT INTO run_zombies (run_id, ztype, kills) VALUES (?,?,?)",
                    (run_id, z["type"], z["kills"]),
                )

            # 成就判定
            known = {row["ach_id"] for row in conn.execute(
                "SELECT ach_id FROM player_achievements WHERE player_id = ?", (pid,))}
            new_ach = []
            for a in ACHIEVEMENTS:
                if a["id"] in known:
                    continue
                try:
                    ok = bool(a["check"](r))
                except Exception:
                    ok = False
                if ok:
                    conn.execute(
                        "INSERT OR IGNORE INTO player_achievements (player_id, ach_id, unlocked_at) VALUES (?,?,?)",
                        (pid, a["id"], created),
                    )
                    known.add(a["id"])
                    new_ach.append({"id": a["id"], "name": a["name"], "icon": a["icon"],
                                    "tier": a["tier"], "desc": a["desc"]})

            # 存档: 合并历史最佳与全局累计
            unlocked = set(json.loads(prow["unlocked_weapons"]))
            unlocked.update(w["id"] for w in r["weapons"])
            better = r["score"] > prow["best_score"]
            conn.execute(
                """UPDATE players SET
                     last_seen = ?, total_score = total_score + ?, total_kills = total_kills + ?,
                     total_runs = total_runs + 1, total_time = total_time + ?,
                     best_score = MAX(best_score, ?), best_kills = MAX(best_kills, ?),
                     best_wave = MAX(best_wave, ?), best_map_name = ?, unlocked_weapons = ?
                   WHERE id = ?""",
                (created, r["score"], r["kills"], r["duration"],
                 r["score"], r["kills"], r["wave"],
                 r["map_name"] if better else prow["best_map_name"],
                 json.dumps(sorted(unlocked)), pid),
            )
            rank = conn.execute(
                "SELECT COUNT(*) + 1 FROM runs WHERE score > ?", (r["score"],)
            ).fetchone()[0]
            beat_best = better

    return {
        "ok": True,
        "run_id": run_id,
        "rank": rank,
        "personal_best": beat_best,
        "new_achievements": new_ach,
        "profile": profile_payload(db(), pid, r["name"]),
    }


def heartbeat(payload):
    name = clean_name((payload or {}).get("name"))
    p = payload if isinstance(payload, dict) else {}
    score = clamp(p.get("score"), 0, MAX_SCORE)
    kills = clamp(p.get("kills"), 0, MAX_KILLS)
    wave = clamp(p.get("wave"), 0, 9999)
    map_name = re.sub(r"[\x00-\x1f<>&\"']", "", str(p.get("map_name") or ""))[:24]
    with WRITE_LOCK:
        conn = db()
        with conn:
            prow = get_or_create_player(conn, name)
            conn.execute(
                """UPDATE players SET last_seen = ?,
                     best_score = MAX(best_score, ?), best_kills = MAX(best_kills, ?),
                     best_wave = MAX(best_wave, ?),
                     best_map_name = CASE WHEN ? > best_score THEN ? ELSE best_map_name END
                   WHERE id = ?""",
                (now_iso(), score, kills, wave, score, map_name, prow["id"]),
            )
    return {"ok": True, "saved": True}


def leaderboard(limit=20, sort="score"):
    col = {"score": "r.score", "kills": "r.kills", "wave": "r.wave"}.get(sort, "r.score")
    rows = db().execute(
        f"""SELECT r.id, p.name, r.score, r.kills, r.wave, r.map_name, r.duration,
                   r.player_count, r.max_weapon_level, r.created_at
            FROM runs r JOIN players p ON p.id = r.player_id
            ORDER BY {col} DESC, r.id ASC LIMIT ?""",
        (int(limit),),
    ).fetchall()
    return {"sort": sort, "entries": [dict(row) for row in rows]}


def global_stats():
    conn = db()
    totals = conn.execute(
        """SELECT COUNT(*) AS runs, COALESCE(SUM(kills),0) AS kills,
                  COALESCE(SUM(score),0) AS score, COALESCE(SUM(duration),0) AS seconds,
                  COALESCE(MAX(score),0) AS best_score,
                  COALESCE(SUM(boss_kills),0) AS boss_kills,
                  COALESCE(SUM(grenade_kills),0) AS grenade_kills
           FROM runs"""
    ).fetchone()
    players = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]

    weapons = conn.execute(
        """SELECT weapon_id, COUNT(*) AS runs, COALESCE(SUM(kills),0) AS kills,
                  COALESCE(MAX(level),1) AS best_level,
                  ROUND(AVG(level),2) AS avg_level
           FROM run_weapons GROUP BY weapon_id ORDER BY kills DESC"""
    ).fetchall()

    zombies = conn.execute(
        "SELECT ztype, COALESCE(SUM(kills),0) AS kills FROM run_zombies GROUP BY ztype ORDER BY kills DESC"
    ).fetchall()

    daily = conn.execute(
        """SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS runs,
                  COALESCE(SUM(kills),0) AS kills, COALESCE(MAX(score),0) AS best_score
           FROM runs GROUP BY day ORDER BY day DESC LIMIT 14"""
    ).fetchall()

    top_players = conn.execute(
        """SELECT name, best_score, best_kills, best_wave, total_kills, total_runs
           FROM players ORDER BY best_score DESC LIMIT 10"""
    ).fetchall()

    ach_counts = conn.execute(
        "SELECT ach_id, COUNT(*) AS n FROM player_achievements GROUP BY ach_id"
    ).fetchall()
    ach_map = {row["ach_id"]: row["n"] for row in ach_counts}

    return {
        "totals": {
            "runs": totals["runs"], "players": players, "kills": totals["kills"],
            "score": totals["score"], "hours": round(totals["seconds"] / 3600, 2),
            "best_score": totals["best_score"], "boss_kills": totals["boss_kills"],
            "grenade_kills": totals["grenade_kills"],
        },
        "weapons": [dict(row) for row in weapons],
        "zombies": [dict(row) for row in zombies],
        "daily": [dict(row) for row in reversed(daily)],
        "top_players": [dict(row) for row in top_players],
        "achievements": [
            {"id": a["id"], "name": a["name"], "icon": a["icon"], "tier": a["tier"],
             "desc": a["desc"], "unlocked_by": ach_map.get(a["id"], 0)}
            for a in sorted(ACHIEVEMENTS, key=lambda a: (TIER_ORDER[a["tier"]], a["id"]))
        ],
    }


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "ZombieSiege/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    # --- 响应工具 ---
    def _send(self, status, body: bytes, ctype="application/json; charset=utf-8", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, status=200):
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _err(self, status, msg):
        self._json({"ok": False, "error": msg}, status)

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if n <= 0 or n > MAX_BODY:
            return None
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    def _query(self):
        from urllib.parse import urlparse, parse_qs
        return parse_qs(urlparse(self.path).query)

    # --- 路由 ---
    def do_GET(self):
        from urllib.parse import urlparse
        path = urlparse(self.path).path
        try:
            if path == "/api/health":
                return self._json({"ok": True, "service": "zombie-siege", "time": now_iso()})
            if path == "/api/leaderboard":
                q = self._query()
                limit = clamp((q.get("limit") or ["20"])[0], 1, 100, 20)
                sort = (q.get("sort") or ["score"])[0]
                return self._json(leaderboard(limit, sort))
            if path == "/api/stats":
                return self._json(global_stats())
            if path == "/api/profile":
                q = self._query()
                name = clean_name((q.get("name") or [""])[0])
                row = db().execute("SELECT id FROM players WHERE name = ?", (name,)).fetchone()
                if not row:
                    return self._json(empty_profile(name))
                return self._json(profile_payload(db(), row["id"], name))
            if path == "/api/achievements":
                return self._json({"definitions": [
                    {"id": a["id"], "name": a["name"], "icon": a["icon"],
                     "tier": a["tier"], "desc": a["desc"]} for a in ACHIEVEMENTS]})
            if path in ("/", "/index.html"):
                return self._serve_file("index.html")
            if path == "/stats":
                return self._serve_file("stats.html")
            return self._serve_file(path.lstrip("/"))
        except BrokenPipeError:
            pass
        except Exception as exc:  # noqa: BLE001
            self.log_message("GET %s failed: %r", path, exc)
            try:
                self._err(500, "internal error")
            except Exception:
                pass

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        from urllib.parse import urlparse
        path = urlparse(self.path).path
        try:
            if path == "/api/run":
                body = self._read_json()
                if body is None:
                    return self._err(400, "invalid JSON body")
                return self._json(submit_run(body))
            if path == "/api/heartbeat":
                return self._json(heartbeat(self._read_json()))
            return self._err(404, "unknown endpoint")
        except BrokenPipeError:
            pass
        except Exception as exc:  # noqa: BLE001
            self.log_message("POST %s failed: %r", path, exc)
            try:
                self._err(500, "internal error")
            except Exception:
                pass

    # --- 静态文件 ---
    def _serve_file(self, rel):
        if ".." in rel.replace("\\", "/").split("/"):
            return self._err(403, "forbidden")
        full = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not full.startswith(STATIC_DIR + os.sep) or not os.path.isfile(full):
            return self._err(404, "not found")
        import mimetypes
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as fh:
            self._send(200, fh.read(), ctype)


def main():
    ap = argparse.ArgumentParser(description="丧尸围城 后端服务")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    args = ap.parse_args()

    init_db()
    url = f"http://{args.host}:{args.port}/"
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    print("=" * 58)
    print("  丧尸围城 · 后端服务已启动")
    print(f"  游戏入口   {url}")
    print(f"  统计面板   {url}stats")
    print(f"  数据库     {DB_PATH}")
    print("  Ctrl+C 停止")
    print("=" * 58)
    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止...")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
