"""解析竞彩官网赛程与赔率结构。"""
import json
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0"}
url = "https://webapi.sporttery.cn/gateway/uniform/football/getMatchListV1.qry?clientCode=3001"
d = requests.get(url, timeout=25, headers=UA).json()

v = d["value"]
print("value keys:", list(v.keys()))
mil = v.get("matchInfoList", [])
print("日期数:", len(mil))

day = mil[0]
print("\n== 单日 structure ==")
print("day keys:", list(day.keys()))
print("businessDate:", day.get("businessDate"), "subMatchList 场数:", len(day.get("subMatchList", [])))

m = day["subMatchList"][0]
print("\n== 单场全部字段 ==")
for k in sorted(m.keys()):
    val = m[k]
    if isinstance(val, (dict, list)):
        print(f"  {k}: {type(val).__name__}")
    else:
        print(f"  {k}: {val!r}")
