"""从 understat 联赛页提取 season/league 下拉框的真实取值。"""
import re
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0"}

r = requests.get("https://understat.com/league/EPL", timeout=25, headers=UA)
t = r.text

for name in ("season", "league"):
    m = re.search(rf"<select[^>]*name=['\"]{name}['\"].*?</select>", t, re.S)
    if not m:
        print(f"select {name}: NOT FOUND")
        continue
    block = m.group(0)
    opts = re.findall(r"<option[^>]*value=['\"]([^'\"]*)['\"][^>]*>([^<]*)</option>", block)
    print(f"\n== select name={name} ==  ({len(opts)} options)")
    for v, label in opts[:12]:
        print(f"   value={v!r:<16} label={label.strip()!r}")
    if len(opts) > 12:
        print(f"   ... 共 {len(opts)} 个")
