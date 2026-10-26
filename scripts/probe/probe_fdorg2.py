"""列出 football-data.org 免费可访问的联赛。"""
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://api.football-data.org/v4"

r = requests.get(f"{BASE}/competitions", timeout=20)
comps = r.json().get("competitions", [])
print("免费可访问联赛数:", len(comps))

interesting = {
    "PL": "英超", "ELC": "英冠", "FL1": "法甲", "FL2": "法乙",
    "BL1": "德甲", "BL2": "德乙", "SA": "意甲", "SB": "意乙",
    "PD": "西甲", "SD": "西乙", "DED": "荷甲", "PPL": "葡超",
    "CL": "欧冠", "EL": "欧联", "WC": "世界杯", "EURO": "欧洲杯",
    "BSA": "巴甲", "MLS": "美职联", "AAL": "澳超", "JSL": "日职",
    "K1": "韩K", "CLI": "南美杯", "PEA": "秘鲁甲", "ARG": "阿甲",
    "PPL": "葡超", "BSB": "巴乙", "NLC": "", "ECT": "",
}
have = {c.get("code"): c for c in comps if c.get("code")}
print("\n== 竞彩相关联赛覆盖 ==")
for code, cn in interesting.items():
    if code in have:
        c = have[code]
        print(f"  ✓ {code:<5} {cn:<6} id={c['id']:<6} {c.get('name','')}")
    else:
        print(f"  ✗ {code:<5} {cn:<6} 不可用")

print("\n== 全部可用 code（前 80）==")
allcodes = sorted(have.keys())
print("  " + ", ".join(allcodes[:80]))
