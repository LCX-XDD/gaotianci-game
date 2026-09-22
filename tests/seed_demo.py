# -*- coding: utf-8 -*-
"""生成演示数据：多玩家、跨 14 天、分数与击杀数自洽。仅供本地查看统计面板用。"""
import datetime
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server

server.init_db()
random.seed(int(sys.argv[1]) if len(sys.argv) > 1 else 20260914)

NAMES = ["张伟", "李四", "老张", "王小明", "陈刀仔", "夜行者", "阿飞", "赵铁柱"]
MAPS = ["城市街区", "荒漠戈壁", "极地冰原"]
XP_CAP = 250  # 僵尸王经验，用于让 score 与 kills 自洽

for _ in range(46):
    pc = random.choice([1, 1, 2, 2, 2])
    kills = random.randint(8, 620)
    # 分数 = Σ 单只经验，均值取 40~250
    score = int(kills * random.uniform(40, XP_CAP))
    ws = random.sample(server.WEAPON_IDS, random.randint(1, 6))
    zs = random.sample(server.ZOMBIE_IDS, random.randint(3, 9))
    boss = random.randint(0, 2)
    payload = {
        "name": random.choice(NAMES),
        "score": score, "kills": kills,
        "wave": random.randint(1, 5), "map_index": random.randint(0, 2),
        "map_name": random.choice(MAPS),
        "duration": random.randint(90, 900), "player_count": pc,
        "maps_cleared": random.randint(0, 3), "boss_kills": boss,
        "grenade_kills": random.randint(0, min(60, kills)),
        "max_weapon_level": random.choice([1, 3, 5, 8, 10, 12, 15]),
        "first_damage_at": random.choice([None, 12, 30, 55, 90, 140]),
        "weapons": [{"id": w, "level": random.randint(1, 15), "kills": random.randint(0, 260)} for w in ws],
        "zombies": {z: random.randint(0, 400) for z in zs},
    }
    res = server.submit_run(payload)
    if not res.get("ok"):
        print("跳过被拒的一局:", res.get("error"))
        continue
    days = random.randint(0, 13)
    stamp = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat(timespec="seconds")
    with server.WRITE_LOCK:
        conn = server.db()
        with conn:
            conn.execute("UPDATE runs SET created_at=? WHERE id=?", (stamp, res["run_id"]))

st = server.global_stats()
t = st["totals"]
print(f"演示数据就绪: {t['runs']} 局 / {t['players']} 人 / {t['kills']} 击杀 / {t['hours']} 小时")
print(f"最高分 {t['best_score']} · 覆盖 {len(st['daily'])} 天 · 武器 {len(st['weapons'])} 种 · 僵尸 {len(st['zombies'])} 种")
