"""解析竞彩赔率池结构。"""
import json
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0"}
url = "https://webapi.sporttery.cn/gateway/uniform/football/getMatchListV1.qry?clientCode=3001"
d = requests.get(url, timeout=25, headers=UA).json()

mil = d["value"]["matchInfoList"]
m = mil[0]["subMatchList"][0]
print("== oddsList ==")
print(json.dumps(m["oddsList"], ensure_ascii=False, indent=1)[:1500])

print("\n== poolList ==")
print(json.dumps(m["poolList"], ensure_ascii=False, indent=1)[:2500])

# 统计所有场次的联赛与玩法
print("\n== 今日全部场次 ==")
leagues = set()
pools = set()
for day in mil:
    for mm in day["subMatchList"]:
        leagues.add(mm["leagueAbbName"])
        for p in mm.get("poolList", []):
            pools.add(p.get("poolCode"))
print("联赛:", sorted(leagues))
print("玩法池:", sorted(x for x in pools if x))
