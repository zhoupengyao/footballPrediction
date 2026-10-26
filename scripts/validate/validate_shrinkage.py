"""P2 验证脚本：对比不同收缩先验在 UCL（欧战小样本）上的回测指标。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd

from src.pipeline import load_training_data
from src.models import dixon_coles as dc
from src.backtest import metrics as M

df = load_training_data()
sub = df[df.league_code == "UCL"].sort_values("date").reset_index(drop=True)
cut = sub.date.max() - pd.Timedelta(days=365 * 2)
train = sub[sub.date < cut]
test = sub[sub.date >= cut]
print(f"UCL 训练 {len(train)} 场, 测试 {len(test)} 场")


def evalfit(prior):
    m = dc.fit(train, half_life_days=540, shrinkage_prior=prior)
    rows = []
    for r in test.itertuples(index=False):
        if r.home_team not in m.attack or r.away_team not in m.attack:
            continue
        p = dc.predict_proba(m, r.home_team, r.away_team)
        rows.append({
            "p_home": p["prob_home"], "p_draw": p["prob_draw"],
            "p_away": p["prob_away"],
            "actual": M.result_label(r.ft_home, r.ft_away),
        })
    return M.evaluate(rows)


print("\n先验  | 场次 | 准确率 | 对数损失 | Brier  | ECE")
print("-" * 55)
for prior in [0, 4, 8, 12, 20]:
    ev = evalfit(prior)
    print(f"{prior:>4}  | {ev['n']:>4} | {ev['accuracy']:.4f} | "
          f"{ev['log_loss']:.4f} | {ev['brier']:.4f} | {ev['ece']:.4f}")
