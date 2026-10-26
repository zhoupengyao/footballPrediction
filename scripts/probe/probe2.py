"""探测 understat 的数据接口。"""
import re
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0"}

r = requests.get("https://understat.com/league/EPL", timeout=25, headers=UA)
t = r.text

print("== script src ==")
for m in re.finditer(r"<script[^>]*src=[\"']([^\"']+)", t):
    print("  ", m.group(1))

print("\n== 关键字位置 ==")
for kw in ["getDates", "datesData", "ajax", "fetch(", "axios", "getLeague", "jQuery", "$.post", "$.get"]:
    print(f"  {kw!r}: {t.find(kw)}")

print("\n== 表格/容器元素 ==")
for m in re.finditer(r"<table[^>]*id=[\"']([^\"']+)", t):
    print("   table id:", m.group(1))
for m in re.finditer(r"<div[^>]*id=[\"']([^\"']*(?:dates|matches|league|stats)[^\"']*)", t, re.I):
    print("   div id:", m.group(1))

print("\n== 页面内联 JS 尾部 1500 字符 ==")
print(t[-1500:])
