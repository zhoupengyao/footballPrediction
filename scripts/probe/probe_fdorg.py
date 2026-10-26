"""探测 football-data.org 免费 API 的可达性与覆盖面。"""
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://api.football-data.org/v4"

r = requests.get("https://api.football-data.org/", timeout=20)
print("root status:", r.status_code)

# 无 key 情况下的联赛列表
try:
    r = requests.get(f"{BASE}/competitions", timeout=20)
    print("competitions:", r.status_code)
    if r.ok:
        d = r.json()
        comps = d.get("competitions", [])
        print("  联赛数:", len(comps))
        codes = sorted(c["code"] or c["id"] for c in comps)
        interesting = ["PL", "ELC", "BL1", "BL2", "SA", "SB", "PD", "SD", "FL1", "FL2",
                       "DED", "PPL", "CL", "WC", "EURO", "CLI", "BSA", "MLS", "AAL", "JSL", "K1"]
        have = {c.get("code") for c in comps}
        print("  竞彩相关覆盖:", [i for i in interesting if i in have])
        print("  缺失:", [i for i in interesting if i not in have])
    else:
        print("  body:", r.text[:300])
except Exception as e:
    print("competitions FAIL", type(e).__name__, str(e)[:150])

# 半场比分是否可得：取一场已结束比赛
print("\n== 半场比分测试 ==")
try:
    r = requests.get(f"{BASE}/matches", params={"status": "FINISHED"}, timeout=25)
    print("matches:", r.status_code)
    if r.ok:
        ms = r.json().get("matches", [])
        print("  场次:", len(ms))
        if ms:
            m = ms[0]
            print("  keys:", sorted(m.keys()))
            print("  score:", m.get("score"))
    else:
        print("  body:", r.text[:300])
except Exception as e:
    print("FAIL", type(e).__name__, str(e)[:150])
