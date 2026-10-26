"""打印竞彩各玩法赔率的真实结构。"""
import json
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://www.sporttery.cn/",
    "X-Requested-With": "XMLHttpRequest",
}
u = ("https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry"
     "?poolCode=had,hhad,crs,ttg,hafu&clientCode=3001")
d = requests.get(u, timeout=30, headers=H).json()
m = d["value"]["matchInfoList"][0]["subMatchList"][0]

print("比赛:", m["leagueAbbName"], m["matchNumStr"], m["homeTeamAbbName"], "vs", m["awayTeamAbbName"])
print("排名:", m["homeRank"], m["awayRank"])
print("英文缩写:", m["homeTeamAbbEnName"], m["awayTeamAbbEnName"], "leagueCode:", m["leagueCode"])

for key in ("had", "hhad", "ttg", "hafu", "crs"):
    v = m.get(key)
    print(f"\n===== {key} ===== type={type(v).__name__}")
    print(json.dumps(v, ensure_ascii=False, indent=1)[:1600])
