"""校验 Dixon-Coles 解析梯度的正确性。"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import approx_fprime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src.ingest.footballdata import load_tier1
from src.models import dixon_coles as dc

df = load_tier1(divs=["E0"])
cutoff = df["date"].max() - pd.Timedelta(days=365 * 4)
train = df[df["date"] >= cutoff].copy()

p = dc._prep(train, half_life_days=180, max_goals=10, min_weight=0.0)
n, hi, ai, hg, ag, w, log_fact = (p["n"], p["hi"], p["ai"], p["hg"],
                                   p["ag"], p["w"], p["log_fact"])
print(f"球队数 n={n}, 样本 {p['n_matches']}, 参数 {2*n+3}")

# 在随机扰动点校验（初值处部分梯度为 0，不适合校验）
rng = np.random.default_rng(42)
x0 = np.concatenate([
    rng.normal(0, 0.3, 2 * n),
    [np.log(2.7), np.log(1.2), -0.02],
])

f, g = dc._fg(x0, n, hi, ai, hg, ag, w, log_fact)
print(f"目标值 f={f:.6f}")

# 数值梯度（中心差分，步长 1e-6）
eps = 1e-6
g_num = np.zeros_like(x0)
for i in range(len(x0)):
    xp = x0.copy(); xp[i] += eps
    xm = x0.copy(); xm[i] -= eps
    fp, _ = dc._fg(xp, n, hi, ai, hg, ag, w, log_fact)
    fm, _ = dc._fg(xm, n, hi, ai, hg, ag, w, log_fact)
    g_num[i] = (fp - fm) / (2 * eps)

abs_err = np.abs(g - g_num)
rel_err = abs_err / np.maximum(np.abs(g_num), 1e-8)
print(f"\n最大绝对误差: {abs_err.max():.3e}")
print(f"最大相对误差: {rel_err.max():.3e}")
print(f"梯度范数(解析): {np.linalg.norm(g):.6f}")
print(f"梯度范数(数值): {np.linalg.norm(g_num):.6f}")

ok = abs_err.max() < 1e-5
print(f"\n梯度校验: {'通过 ✓' if ok else '失败 ✗'}")

# 分段校验：打印最不准的几项
order = np.argsort(-abs_err)[:5]
print("\n误差最大的 5 个参数:")
for i in order:
    name = (f"theta[{i}]" if i < n else
            f"phi[{i-n}]" if i < 2*n else
            ["log_mu", "log_gamma", "rho"][i - 2*n])
    print(f"  {name:<14} 解析={g[i]:+.6e}  数值={g_num[i]:+.6e}  绝对误差={abs_err[i]:.2e}")
