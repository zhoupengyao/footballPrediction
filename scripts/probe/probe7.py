"""检查 understat getLeagueData 返回结构。"""
import json
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0",
    "Referer": "https://understat.com/league/EPL",
    "X-Requested-With": "XMLHttpRequest",
}

r = requests.get("https://understat.com/getLeagueData/EPL/2026", timeout=30, headers=UA)
d = r.json()
print("top keys:", list(d.keys()))
for k, v in d.items():
    print(f"  {k}: {type(v).__name__} len={len(v)}")

# dates 数组：逐场比赛
dates = d.get("dates") or []
print(f"\n== dates: {len(dates)} 场 ==")
if dates:
    print("keys:", list(dates[0].keys()))
    sample = dates[-1]
    print("\n最后一场原始:")
    print(json.dumps(sample, ensure_ascii=False, indent=1)[:900])

# teams 结构
teams = d.get("teams") or {}
tid = list(teams.keys())[0]
print(f"\n== teams['{tid}'] keys: {list(teams[tid].keys())}")
hist = teams[tid].get("history", [])
print(f"   history 场次: {len(hist)}")
if hist:
    print("   history[0] keys:", list(hist[0].keys()))
    print("   history[0]:", json.dumps(hist[0], ensure_ascii=False)[:400])
