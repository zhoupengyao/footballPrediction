"""分析 understat 的 league.min.js 找数据接口。"""
import re
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0"}

url = "https://understat.com/js/league.min.js?t=1765269520"
r = requests.get(url, timeout=25, headers=UA)
print("status", r.status_code, "bytes", len(r.content))
js = r.text

# 找 ajax / post / get 调用
for pat in [r"\.ajax\(", r"\.post\(", r"\.get\(", r"url\s*:", r"data\s*:", r"'/\w+\"", r'"/\w+\"']:
    for m in re.finditer(pat, js):
        s = max(0, m.start() - 100)
        print(f"\n--- {pat} @ {m.start()} ---")
        print(js[s : m.start() + 200].replace("\n", " "))
        break

print("\n\n== 所有类似路径的字符串 ==")
paths = set(re.findall(r"[\"'](/[a-zA-Z][\w/]{2,40})[\"']", js))
for p in sorted(paths):
    print("  ", p)
