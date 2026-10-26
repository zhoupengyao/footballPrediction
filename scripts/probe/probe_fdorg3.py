"""在 football-data.org 全部联赛里搜日韩北欧等竞彩常见赛事。"""
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://api.football-data.org/v4"
r = requests.get(f"{BASE}/competitions", timeout=20)
comps = r.json().get("competitions", [])

kw = ["Japan", "Korea", "J.", "K League", "Sweden", "Norway", "Denmark", "Switzerland",
      "Austria", "Greece", "Turkey", "Scotland", "China", "Belgium", "Netherlands",
      "Mexico", "Argentina", "Colombia", "Chile", "Peru", "Uruguay", "Finland", "Poland",
      "Czech", "Romania", "Israel", "Saudi", "Egypt", "Morocco", "USA", "Canada"]

print("== 关键词搜索 ==")
for k in kw:
    hits = [c for c in comps if k.lower() in (c.get("name") or "").lower()]
    if hits:
        for c in hits:
            print(f"  {k:<12} -> {c.get('code') or c['id']:<8} id={c['id']:<6} {c.get('name')}")

print("\n== 全部 code（完整）==")
codes = sorted((c.get("code") or str(c["id"])) for c in comps)
print(", ".join(codes))
