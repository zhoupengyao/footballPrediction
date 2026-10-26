"""探测中国竞彩官网接口。"""
import json
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0"}

# 竞彩已知公开接口
endpoints = [
    "https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry?poolCode=had",
    "https://webapi.sporttery.cn/gateway/jc/football/getMatchListV1.qry",
    "https://webapi.sporttery.cn/gateway/uniform/football/getMatchListV1.qry?clientCode=3001",
    "https://www.sporttery.cn/",
]

for url in endpoints:
    try:
        r = requests.get(url, timeout=20, headers=UA)
        print(f"\n{r.status_code}  {url}")
        print(f"  ct={r.headers.get('Content-Type')}  bytes={len(r.content)}")
        ct = r.headers.get("Content-Type", "")
        if "json" in ct:
            d = r.json()
            print("  keys:", list(d.keys()) if isinstance(d, dict) else type(d).__name__)
            print("  preview:", json.dumps(d, ensure_ascii=False)[:500])
        else:
            print("  body[:200]:", r.text[:200].replace("\n", " "))
    except Exception as e:
        print(f"\nFAIL {type(e).__name__}: {str(e)[:120]}")
        print(f"  {url}")
