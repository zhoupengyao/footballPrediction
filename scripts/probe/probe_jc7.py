"""从竞彩官网 JS 中提取赔率接口的真实参数名。"""
import re
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 找竞彩赛果/赔率页面的 js
r = requests.get("https://www.sporttery.cn/jc/jsk/", timeout=25, headers=H)
print("page status:", r.status_code, "bytes:", len(r.content))
t = r.text

scripts = re.findall(r"<script[^>]*src=[\"']([^\"']+)", t)
print("scripts:", len(scripts))
for s in scripts[:20]:
    print("  ", s)

# 搜索内联或引用里的接口路径
print("\n== 页面内 .qry 接口 ==")
for m in set(re.findall(r"[\"']([^\"']*\.qry[^\"']*)[\"']", t)):
    print("  ", m)

print("\n== 含 odds / Odds 的字符串 ==")
for m in set(re.findall(r"[\"']([^\"']*[Oo]dds[^\"']*)[\"']", t)):
    print("  ", m[:120])
