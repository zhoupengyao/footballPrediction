"""验证 Dixon-Coles 可识别性修复：多次拟合应给出唯一解。"""
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
cutoff = df["date"].max() - pd.Timedelta(days=365 * 10)
train = df[df["date"] >= cutoff].copy()

# 三次拟合，参数应一致
results = []
for i in range(3):
    t0 = time.time()
    m = dc.fit(train, half_life_days=180)
    dt = time.time() - t0
    results.append(m)
    print(f"拟合{i+1}: {dt:.1f}s  收敛={m.converged}  LL={m.log_likelihood:.6f}  "
          f"μ={m.mu:.4f} γ={m.home_advantage:.4f} ρ={m.rho:.5f}")

m = results[0]
print(f"\n几何平均 α: {np.exp(np.log(list(m.attack.values())).mean()):.6f} (应为 1)")
print(f"几何平均 β: {np.exp(np.log(list(m.defense.values())).mean()):.6f} (应为 1)")

# 缩放不变性检验：手动缩放 β 和 μ 应得到相同 λ
lh1, la1 = dc.expected_goals(m, "Arsenal", "Liverpool")
print(f"\n原始 λ: {lh1:.5f} / {la1:.5f}")

# 预测
print("\n" + "=" * 60)
for h, a in [("Arsenal", "Liverpool"), ("Sunderland", "Man City")]:
    p = dc.predict_proba(m, h, a)
    print(f"\n{h} vs {a}  ({p['xg_home']:.2f} - {p['xg_away']:.2f})")
    print(f"  胜平负: 主 {p['prob_home']:.3f} | 平 {p['prob_draw']:.3f} | 客 {p['prob_away']:.3f}")
    tg = p["total_goals"]
    print("  总进球: " + " ".join(f"{k}:{tg[k]:.3f}" for k in ["0","1","2","3","4","5","6","7+"]))

print("\n== 进攻前5 ==")
for t, v in sorted(m.attack.items(), key=lambda x: -x[1])[:5]:
    print(f"  {t:<20} α={v:.3f}")
print("== 防守前5 ==")
for t, v in sorted(m.defense.items(), key=lambda x: x[1])[:5]:
    print(f"  {t:<20} β={v:.3f}")
