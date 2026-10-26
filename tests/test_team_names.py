"""测试队名匹配器：用今日竞彩场次 vs 历史数据队名。"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src.ingest.footballdata import load_tier1
from src.ingest.jingcai_scraper import fetch_today
from src.jingcai.team_names import TeamMatcher, build_known_names_from_data

hist = load_tier1()
names = build_known_names_from_data(hist)
print(f"历史数据队名: {len(names)} 个")

matcher = TeamMatcher(names)

jc = fetch_today()
print(f"今日竞彩 {len(jc)} 场\n")

print(f"{'编号':<8}{'联赛':<6}{'主队':<12}{'英文':<6}{'匹配':<22}{'置信':<8}{'分'}")
print("-" * 82)
total = 0
ok = 0
unmatched = []
for m in jc:
    for cn, en in ((m.home_cn, m.home_en), (m.away_cn, m.away_en)):
        r = matcher.match(cn, en)
        total += 1
        flag = "✓" if r.ok else "✗"
        if r.ok:
            ok += 1
        else:
            unmatched.append(f"{cn}({en})/{m.league}")
        print(f"{m.match_num:<8}{m.league:<6}{cn:<12}{en:<6}"
              f"{(r.matched_name or '-'):<22}{r.confidence:<8}{r.score:.2f} {flag}")

print("-" * 82)
print(f"匹配率: {ok}/{total} = {ok/total*100:.1f}%")
if unmatched:
    print(f"\n未匹配 ({len(unmatched)}):")
    for u in unmatched:
        print("  ", u)

# 按联赛看覆盖率
print("\n按联赛:")
from collections import defaultdict
by_league = defaultdict(lambda: [0, 0])
for m in jc:
    for cn, en in ((m.home_cn, m.home_en), (m.away_cn, m.away_en)):
        by_league[m.league][1] += 1
        if matcher.match(cn, en).ok:
            by_league[m.league][0] += 1
for lg, (a, b) in sorted(by_league.items(), key=lambda x: x[1][0]/max(x[1][1],1)):
    print(f"  {lg:<6} {a}/{b} = {a/b*100:.0f}%")
