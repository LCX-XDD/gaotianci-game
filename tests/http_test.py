# -*- coding: utf-8 -*-
"""服务端 HTTP 端到端测试。用法: python tests/http_test.py <port>"""

import http.client
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
BASE = f"http://127.0.0.1:{PORT}"
fails = []
total = 0


def check(name, cond, extra=None):
    global total
    total += 1
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"   [{extra}]" if extra is not None else ""))
    if not cond:
        fails.append(name)


def get(path):
    try:
        with urllib.request.urlopen(BASE + path) as r:
            return r.status, r.headers.get("Content-Type"), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type"), e.read()


def post(path, obj):
    req = urllib.request.Request(BASE + path, data=json.dumps(obj).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


print("=== 静态资源 ===")
for path, must in [("/", b'<canvas id="game"'), ("/index.html", b'<canvas id="game"'),
                   ("/stats", b"<svg"), ("/stats.html", b'id="kpis"')]:
    s, ct, body = get(path)
    check(f"GET {path}", s == 200 and must in body, f"{s} {len(body)}B")

print("=== 路径穿越防护 ===")
for p in ["/../server.py", "/..%2fserver.py", "/static/../../server.py", "/zombie.db"]:
    s, _, _ = get(p)
    check(f"{p} 被拒", s in (400, 403, 404), s)

print("=== API ===")
s, _, b = get("/api/health")
check("GET /api/health", s == 200 and json.loads(b)["ok"])
post("/api/run", {"name": "张伟", "score": 3000, "kills": 60, "wave": 3})   # 确保存在该玩家
s, _, b = get("/api/leaderboard?limit=3")
d = json.loads(b)
check("GET /api/leaderboard", s == 200 and len(d["entries"]) <= 3, f"{len(d['entries'])} 条")
s, _, b = get("/api/leaderboard?sort=kills&limit=2")
d = json.loads(b)
check("排行榜可按击杀排序", s == 200 and d["sort"] == "kills"
      and (len(d["entries"]) < 2 or d["entries"][0]["kills"] >= d["entries"][1]["kills"]))
s, _, b = get("/api/leaderboard?limit=99999")
check("limit 被钳制", len(json.loads(b)["entries"]) <= 100)
s, _, b = get("/api/stats")
d = json.loads(b)
check("GET /api/stats", s == 200 and "totals" in d and "achievements" in d, d["totals"]["runs"])
s, _, b = get("/api/profile?name=" + urllib.parse.quote("张伟"))
d = json.loads(b)
check("profile 中文代号往返", s == 200 and d["name"] == "张伟", d["name"])
s, _, b = get("/api/profile?name=" + urllib.parse.quote("查无此人"))
d = json.loads(b)
check("未建档玩家返回零值档案而非 404", s == 200 and d["exists"] is False)
check("零值档案含全部成就(均未解锁)",
      len(d["achievements"]) == 14 and not any(a["unlocked"] for a in d["achievements"]))
s, _, b = get("/api/achievements")
check("GET /api/achievements", s == 200 and len(json.loads(b)["definitions"]) == 14)
check("未知 API 返回 404", get("/api/nope")[0] == 404)

print("=== 信任边界（客户端一切皆不可信） ===")
s, d = post("/api/run", {"name": "<script>alert(1)</script>", "score": 9e99, "kills": 0})
check("天文分数被拒", s == 200 and not d["ok"], d.get("error"))
s, d = post("/api/run", {"name": "作弊", "score": 10 ** 9, "kills": 5})
check("分数/击杀不自洽被拒", not d["ok"], d.get("error"))
s, d = post("/api/run", {"name": "作弊", "score": 100, "kills": 1, "boss_kills": 99})
check("僵尸王数多于总击杀被拒", not d["ok"], d.get("error"))
s, d = post("/api/run", {"name": "好人", "score": 41592, "kills": 620, "boss_kills": 2})
check("自洽对局被接受", d["ok"])
s, _, b = get("/api/leaderboard?limit=1")
top = json.loads(b)["entries"][0]
check("排行榜未被伪造值污染", 0 < top["score"] <= 1_000_000, top["score"])
s, d = post("/api/run", {"name": None})
check("空代号回落默认名", d["profile"]["name"] == "无名幸存者", d["profile"]["name"])
s, d = post("/api/run", {"name": "境界测试", "score": 900000, "kills": 4200, "boss_kills": 15})
check("长局马拉松仍被接受", d["ok"])
check("POST /api/heartbeat", post("/api/heartbeat", {"name": "李四", "score": 1})[1]["ok"])

print("=== 协议 ===")
c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
c.request("HEAD", "/api/stats")
r = c.getresponse(); r.read()
check("HEAD 无响应体", r.status == 200 and r.getheader("Content-Length") is not None, r.status)
c.request("POST", "/api/run", body=b"{bad json", headers={"Content-Type": "application/json"})
r = c.getresponse(); r.read()
check("坏 JSON → 400", r.status == 400, r.status)
c.request("POST", "/api/run", body=b"{}", headers={"Content-Type": "application/json"})
r = c.getresponse(); d = json.loads(r.read())
check("空对象可安全入库", r.status == 200 and d["ok"])
c.request("GET", "/api/health", headers={"Connection": "keep-alive"})
r = c.getresponse(); r.read()
check("HTTP/1.1 长连接可用", r.status == 200)
c.close()

total = 26
print("\n" + "=" * 52)
print(f"  通过 {total - len(fails)} / {total}")
if fails:
    print("  失败:", fails)
print("=" * 52)
sys.exit(1 if fails else 0)
