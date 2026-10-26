"""验证 Dixon-Coles 实现：拟合英超并做预测。"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src.ingest.footballdata import load_tier1
from src.models import dixon_coles as dc

df = load_tier1(divs=["E0"])
print(f"英超样本: {len(df)} 场, {df['date'].min().date()} -> {df['date'].max().date()}")

# 用近 10 个赛季拟合
cutoff = df["date"].max() - pd.Timedelta(days=365 * 10)
train = df[df["date"] >= cutoff].copy()
print(f"训练集(近10季): {len(train)} 场, {train['home_team'].nunique()} 队")

t0 = time.time()
model = dc.fit(train, half_life_days=180)
print(f"\n拟合耗时: {time.time() - t0:.1f}s")
print(dc.model_summary(model, top=8))

# 预测一场
print("\n" + "=" * 60)
for h, a in [("Arsenal", "Liverpool"), ("Sunderland", "Man City"), ("Burnley", "Wolves")]:
    p = dc.predict_proba(model, h, a)
    print(f"\n{h} vs {a}")
    print(f"  期望进球: {p['xg_home']:.2f} - {p['xg_away']:.2f}")
    print(f"  胜平负: 主 {p['prob_home']:.3f} | 平 {p['prob_draw']:.3f} | 客 {p['prob_away']:.3f}")
    print(f"  合计: {p['prob_home']+p['prob_draw']+p['prob_away']:.4f}")
    tg = p["total_goals"]
    print("  总进球: " + "  ".join(f"{k}:{tg[k]:.3f}" for k in ["0", "1", "2", "3", "4", "5", "6", "7+"]))

# 校验：概率和为 1，比分矩阵非负
print("\n== 数值校验 ==")
m = dc.score_matrix(model, "Arsenal", "Liverpool")
print(f"  比分矩阵形状 {m.shape}, 和={m.sum():.6f}, 最小值={m.min():.2e}")
print(f"  矩阵和 vs 1 偏差: {abs(m.sum()-1):.2e}")
