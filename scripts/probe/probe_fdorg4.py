"""验证 football-data.org 是否提供半场比分。"""
import json
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://api.football-data.org/v4"

# 取英超本赛季已结束比赛
r = requests.get(f"{BASE}/competitions/PL/matches", params={"status": "FINISHED"}, timeout=30)
print("status:", r.status_code)
d = r.json()
ms = d.get("matches", [])
print("已结束场次:", len(ms))
if ms:
    m = ms[-1]
    print("\n== 单场字段 ==")
    print(sorted(m.keys()))
    print("\n== score 结构 ==")
    print(json.dumps(m.get("score"), ensure_ascii=False, indent=1))
    print("\n== 比赛信息 ==")
    print(m.get("homeTeam", {}).get("name"), m.get("score", {}).get("fullTime", {}).get("home"),
          "-", m.get("score", {}).get("fullTime", {}).get("away"),
          m.get("awayTeam", {}).get("name"))
    print("utcDate:", m.get("utcDate"))

# 检查赛程量
print("\n== 各联赛本赛季场次 ==")
for code in ["PL", "ELC", "BL2", "SA", "SB", "PD", "SD", "FL1", "FL2", "DED", "PPL",
             "BSA", "MLS", "AAL", "JJL", "J2L", "CL", "SCO", "TSL", "SSL"]:
    try:
        rr = requests.get(f"{BASE}/competitions/{code}/matches", params={"status": "FINISHED"}, timeout=25)
        n = len(rr.json().get("matches", [])) if rr.ok else f"ERR{rr.status_code}"
        print(f"  {code:<6} {n}")
    except Exception as e:
        print(f"  {code:<6} FAIL {type(e).__name__}")
