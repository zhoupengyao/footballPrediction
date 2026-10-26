"""端到端测试：用 Dixon-Coles 预测今日竞彩场次，并与官方赔率比对。"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src.ingest.footballdata import load_tier1
from src.ingest.jingcai_scraper import fetch_today, to_dataframe
from src.jingcai import payouts as pay
from src.models import dixon_coles as dc
from src.models import halffull

# 竞彩联赛 -> 我们的联赛代码
JC_LEAGUE_TO_DIV = {
    "英超": "E0", "德甲": "D1", "西甲": "SP1", "意甲": "I1", "法甲": "F1",
    "英冠": "E1", "德乙": "D2", "法乙": "F2", "荷甲": "N1", "葡超": "P1",
}

print("正在抓取今日竞彩...")
jc = fetch_today()
jc_df = to_dataframe(jc)
print(f"今日开售 {len(jc_df)} 场，联赛: {sorted(jc_df['league'].unique())}")

print("\n正在拟合各联赛 Dixon-Coles 模型（近 5 赛季）...")
models: dict[str, dc.DixonColesResult] = {}
hf_models: dict[str, halffull.HalfFullModel] = {}
all_data = load_tier1()
for div in sorted(set(JC_LEAGUE_TO_DIV.values())):
    sub = all_data[all_data["league_code"] == div]
    if len(sub) < 300:
        continue
    cutoff = sub["date"].max() - pd.Timedelta(days=365 * 5)
    train = sub[sub["date"] >= cutoff]
    try:
        models[div] = dc.fit(train, half_life_days=180)
        try:
            hf_models[div] = halffull.fit(train,
                                          alpha_full=models[div].attack,
                                          defense_full=models[div].defense)
        except Exception as e:
            print(f"  {div} 半全场跳过: {e}")
        print(f"  {div} 拟合完成: {models[div].n_matches} 场, 收敛={models[div].converged}")
    except Exception as e:
        print(f"  {div} 拟合失败: {e}")

# 竞彩用中文队名，我们需要做名称匹配。这里演示：仅处理能匹配上的场次。
# 实际管线需要 team_name_mapping 模块。
print("\n" + "=" * 78)
print("预测演示（仅展示模型能力，队名匹配待 M4 完善）")
print("=" * 78)

div = "E0"
if div in models:
    m = models[div]
    hfm = hf_models.get(div)
    # 取该联赛历史中的两支队伍演示
    sample_teams = ["Arsenal", "Liverpool", "Man City", "Chelsea"]
    for h, a in [("Arsenal", "Liverpool"), ("Man City", "Chelsea")]:
        pred = dc.predict_proba(m, h, a)
        matrix = pred["score_matrix"]
        hf = halffull.predict(hfm, h, a) if hfm else None
        all_p = pay.all_market_probabilities(matrix, pred["total_goals"],
                                             goal_line=-1, half_full=hf)
        print(f"\n### {h} vs {a}  (xG {pred['xg_home']:.2f} - {pred['xg_away']:.2f})")
        print(f"  HAD 胜平负 : " + "  ".join(f"{k} {v:.3f}" for k, v in all_p["HAD"].items()))
        print(f"  HHAD 让-1  : " + "  ".join(f"{k} {v:.3f}" for k, v in all_p["HHAD"].items()))
        print(f"  TTG 总进球 : " + "  ".join(f"{k} {v:.3f}" for k, v in all_p["TTG"].items()))
        if hf:
            top3 = sorted(hf.items(), key=lambda x: -x[1])[:3]
            print(f"  HAFU 前3   : " + "  ".join(f"{k} {v:.3f}" for k, v in top3))
        crs = all_p["CRS"]
        top_crs = sorted(crs.items(), key=lambda x: -x[1])[:5]
        print(f"  CRS 比分前5: " + "  ".join(f"{k} {v:.3f}" for k, v in top_crs))

        # 演示：假设竞彩赔率，算价值
        demo_odds = {"胜": 1.80, "平": 3.60, "负": 4.20}
        vb = pay.value_bets(all_p["HAD"], demo_odds, edge_threshold=0.03)
        imp = pay.implied_probabilities(demo_odds)
        print(f"  假设赔率 {demo_odds} → 去水隐含: " +
              " ".join(f"{k} {v:.3f}" for k, v in imp.items()))
        print(f"  水位 {pay.overround(demo_odds):.4f}, 返奖率 {pay.payout_ratio(demo_odds):.4f}")
        if vb:
            for b in vb:
                stake = pay.kelly_stake(b["edge"], b["odds"], b["model_prob"])
                print(f"  ★ 有价值: {b['option']} edge={b['edge']:.3f} EV={b['ev']:.3f} "
                      f"建议仓位={stake*100:.2f}%")
        else:
            print("  无价值选择")
