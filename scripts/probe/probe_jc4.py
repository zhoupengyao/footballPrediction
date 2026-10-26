"""探测竞彩完整赔率接口（CRS/TTG/HAFU）。"""
import json
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0"}

# 先拿到一个真实 matchId
lst = requests.get(
    "https://webapi.sporttery.cn/gateway/uniform/football/getMatchListV1.qry?clientCode=3001",
    timeout=25, headers=UA).json()
m = lst["value"]["matchInfoList"][0]["subMatchList"][0]
mid = m["matchId"]
print("sample matchId:", mid, m["matchNumStr"], m["homeTeamAbbName"], "vs", m["awayTeamAbbName"])

candidates = [
    f"https://webapi.sporttery.cn/gateway/uniform/football/getMatchOddsV1.qry?matchId={mid}&clientCode=3001",
    f"https://webapi.sporttery.cn/gateway/uniform/football/getMatchOddsV1.qry?matchId={mid}&poolCode=had,crs,ttg,hafu,hhad&clientCode=3001",
    f"https://webapi.sporttery.cn/gateway/jc/football/getMatchOddsV1.qry?matchId={mid}&poolCode=had,crs,ttg,hafu,hhad",
    f"https://webapi.sporttery.cn/gateway/uniform/football/getMatchInfoV1.qry?matchId={mid}&clientCode=3001",
    f"https://webapi.sporttery.cn/gateway/uniform/football/getMatchOddsV1.qry?businessDate=2026-10-16&clientCode=3001",
]

for url in candidates:
    try:
        r = requests.get(url, timeout=20, headers=UA)
        ct = r.headers.get("Content-Type", "")
        print(f"\n{r.status_code} {url.split('gateway/')[1][:70]}")
        if "json" in ct:
            d = r.json()
            print("  success:", d.get("success"), "err:", d.get("errorMessage"))
            s = json.dumps(d, ensure_ascii=False)
            print("  bytes(json):", len(s))
            print("  preview:", s[:600])
        else:
            print("  not json:", r.text[:120].replace("\n", " "))
    except Exception as e:
        print(f"\nFAIL {type(e).__name__}: {str(e)[:100]}")
