"""定位 Dixon-Coles 梯度卡在哪个参数上。"""
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
train = df[df["date"] >= df["date"].max() - pd.Timedelta(days=365 * 10)]
p = dc._prep(train, 180, 10, 0.01)
n, hi, ai, hg, ag, w, log_fact = (p["n"], p["hi"], p["ai"], p["hg"],
                                   p["ag"], p["w"], p["log_fact"])

p0 = np.concatenate([np.zeros(2*n), [np.log(2.7), np.log(1.25), 0.0]])
bounds = [(-4, 4)] * (2 * n) + [(-3, 4), (-1, 2), (-0.5, 0.5)]
args = (n, hi, ai, hg, ag, w, log_fact)

for maxiter in (2000, 5000, 10000):
    t0 = time.time()
    res = minimize(dc._fg, p0, args=args, jac=True, method="L-BFGS-B",
                   bounds=bounds, options={"maxiter": maxiter, "ftol": 1e-14})
    g = np.abs(res.jac)
    print(f"maxiter={maxiter:<6} nit={res.nit:<6} fun={res.fun:.10f} "
          f"|g|inf={g.max():.3e} {time.time()-t0:.2f}s")

# 卡住的参数
res = minimize(dc._fg, p0, args=args, jac=True, method="L-BFGS-B",
               bounds=bounds, options={"maxiter": 10000, "ftol": 1e-14})
g = np.abs(res.jac)
order = np.argsort(-g)[:8]
alpha, beta, mu, gamma, rho = dc._unpack(res.x, n)
teams = p["teams"]
print(f"\n最终 |g|inf = {g.max():.3e}")
print("梯度最大的 8 个参数:")
for i in order:
    if i < n:
        name = f"attack[{teams[i]}]"
    elif i < 2*n:
        name = f"defense[{teams[i-n]}]"
    else:
        name = ["log_mu", "log_gamma", "rho"][i-2*n]
    print(f"  {name:<28} |g|={g[i]:.3e}")

print(f"\nμ={mu:.5f} γ={gamma:.5f} ρ={rho:.6f}")

# 检查是否触及边界
x = res.x
lo = np.array([b[0] for b in bounds]); hi_b = np.array([b[1] for b in bounds])
on_bound = np.where((np.abs(x - lo) < 1e-6) | (np.abs(x - hi_b) < 1e-6))[0]
print(f"触及边界的参数个数: {len(on_bound)}")
for i in on_bound[:10]:
    if i < n: name = f"attack[{teams[i]}]"
    elif i < 2*n: name = f"defense[{teams[i-n]}]"
    else: name = ["log_mu", "log_gamma", "rho"][i-2*n]
    print(f"  {name:<28} x={x[i]:+.4f} bound=({bounds[i][0]},{bounds[i][1]})")
