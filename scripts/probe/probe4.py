"""测试 understat getLeagueData 接口。"""
import json
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0"}

for league, season in [("EPL", "2026"), ("EPL", "2025"), ("EPL", "2024")]:
    url = f"https://understat.com/getLeagueData/{league}/{season}"
    try:
        r = requests.get(url, timeout=25, headers=UA)
        print(f"\n[{league} {season}] status={r.status_code} bytes={len(r.content)} ct={r.headers.get('Content-Type')}")
        if r.ok:
            d = r.json()
            print("  top-level type:", type(d).__name__)
            if isinstance(d, dict):
                print("  keys:", list(d.keys())[:6])
                # 常见结构：dates / teams / players
                for k in ("dates", "teams", "players"):
                    if k in d:
                        v = d[k]
                        print(f"    {k}: {type(v).__name__} len={len(v)}")
            elif isinstance(d, list):
                print("  list len:", len(d))
                print("  sample:", json.dumps(d[0], ensure_ascii=False)[:400])
    except Exception as e:
        print(f"\n[{league} {season}] FAIL {type(e).__name__}: {str(e)[:150]}")
