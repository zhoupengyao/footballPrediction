"""带 AJAX 头重试 understat getLeagueData。"""
import json
import sys
from urllib.parse import quote

import requests

sys.stdout.reconfigure(encoding="utf-8")

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0",
    "Referer": "https://understat.com/league/EPL",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

variants = [
    "https://understat.com/getLeagueData/EPL/2026",
    "https://understat.com/getLeagueData/EPL/2026/",
    "https://understat.com/getLeagueData/EPL/" + quote("2026/2027"),
]

for url in variants:
    try:
        r = requests.get(url, timeout=25, headers=UA)
        print(f"\n{r.status_code}  {url}  ct={r.headers.get('Content-Type')}")
        if r.ok and "json" in (r.headers.get("Content-Type") or ""):
            d = r.json()
            print("  type:", type(d).__name__)
            if isinstance(d, dict):
                print("  keys:", list(d.keys()))
        else:
            print("  body[:200]:", r.text[:200].replace("\n", " "))
    except Exception as e:
        print(f"\nFAIL {type(e).__name__}: {str(e)[:150]}  {url}")
