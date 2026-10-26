"""检查竞彩列表接口中各玩法赔率的填充情况。"""
import sys
from collections import Counter

import requests

sys.stdout.reconfigure(encoding="utf-8")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0"}
lst = requests.get(
    "https://webapi.sporttery.cn/gateway/uniform/football/getMatchListV1.qry?clientCode=3001",
    timeout=25, headers=UA).json()

mil = lst["value"]["matchInfoList"]
total = 0
filled = Counter()
samples = {}
for day in mil:
    for m in day["subMatchList"]:
        total += 1
        for o in m.get("oddsList", []):
            pc = o.get("poolCode")
            if pc == "HHAD":
                ok = bool(o.get("h")) and bool(o.get("goalLine"))
            else:
                ok = bool(o.get("h"))
            if ok:
                filled[pc] += 1
                if pc not in samples:
                    samples[pc] = (m["matchNumStr"], m["leagueAbbName"],
                                   m["homeTeamAbbName"], m["awayTeamAbbName"], o)

print("总场次:", total)
print("\n各玩法有赔率的场次数:")
for pc, n in filled.most_common():
    print(f"  {pc:<6} {n}/{total}")

print("\n== 各玩法样例 ==")
for pc, (num, lg, h, a, o) in samples.items():
    print(f"\n[{pc}] {num} {lg} {h} vs {a}")
    print("   ", {k: v for k, v in o.items() if v})

# 看看是否有其他字段含比分/总进球/半全场赔率
print("\n== 单场全部 key 再确认 ==")
m0 = mil[0]["subMatchList"][0]
print(sorted(m0.keys()))
