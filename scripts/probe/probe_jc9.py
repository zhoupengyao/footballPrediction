"""解析竞彩 getMatchCalculatorV1 完整结构（含排名/赔率）。"""
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
mil = d["value"]["matchInfoList"]

total = 0
m0 = None
for day in mil:
    for m in day["subMatchList"]:
        total += 1
        if m0 is None and m.get("oddsList"):
            m0 = m
print("总场次:", total)

print("\n== 单场全部字段 ==")
for k in sorted(m0.keys()):
    v = m0[k]
    print(f"  {k}: {v!r}" if not isinstance(v, (list, dict)) else f"  {k}: {type(v).__name__} len={len(v)}")

print("\n== oddsList 各玩法 ==")
for o in m0.get("oddsList", []):
    pc = o.get("poolCode")
    if pc == "HHAD":
        print(f"  {pc:<6} goalLine={o.get('goalLine')!r:<8} h={o.get('h')} d={o.get('d')} a={o.get('a')}")
    else:
        print(f"  {pc:<6} odds={o.get('odds')!r}")
        if o.get("odds"):
            print(f"          detail={json.dumps(o, ensure_ascii=False)[:400]}")

print("\n== poolList ==")
print(json.dumps(m0.get("poolList"), ensure_ascii=False)[:800])
