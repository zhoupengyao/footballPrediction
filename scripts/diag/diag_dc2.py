"""诊断解析梯度下的收敛终止原因。"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src.ingest.footballdata import load_tier1
from src.models import dixon_coles as dc

df = load_tier1(divs=["E0"])
cutoff = df["date"].max() - pd.Timedelta(days=365 * 10)
train = df[df["date"] >= cutoff].copy()
p = dc._prep(train, 180, 10, 0.01)
n, hi, ai, hg, ag, w, log_fact = (p["n"], p["hi"], p["ai"], p["hg"],
                                   p["ag"], p["w"], p["log_fact"])
print(f"n={n} 样本={p['n_matches']} 参数={2*n+3}")

p0 = np.concatenate([np.zeros(2*n), [np.log(2.7), np.log(1.25), 0.0]])
bounds = [(-4, 4)] * (2 * n) + [(-3, 4), (-1, 2), (-0.5, 0.5)]
args = (n, hi, ai, hg, ag, w, log_fact)

for ftol in (1e-12, 1e-14):
    t0 = time.time()
    res = minimize(dc._fg, p0, args=args, jac=True, method="L-BFGS-B",
                   bounds=bounds, options={"maxiter": 1000, "ftol": ftol})
    dt = time.time() - t0
    # 梯度无穷范数
    gmax = np.abs(res.jac).max()
    print(f"ftol={ftol:<8} success={res.success} nit={res.nit:<4} nfev={res.nfev:<4} "
          f"fun={res.fun:.8f} |g|inf={gmax:.2e} {dt:.2f}s")
    print(f"    {res.message}")

# maxls 影响（默认 20，线搜索失败会导致未收敛）
t0 = time.time()
res = minimize(dc._fg, p0, args=args, jac=True, method="L-BFGS-B",
               bounds=bounds, options={"maxiter": 1000, "ftol": 1e-12, "maxls": 50})
print(f"\nmaxls=50 success={res.success} nit={res.nit} fun={res.fun:.8f} "
      f"|g|inf={np.abs(res.jac).max():.2e} {time.time()-t0:.2f}s")
print(f"    {res.message}")

# 权重下有效样本量
print(f"\n权重和/有效样本量: {w.sum():.1f} / {len(w)}")
