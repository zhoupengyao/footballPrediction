"""诊断 Dixon-Coles 收敛状态。"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import gammaln

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src.ingest.footballdata import load_tier1
from src.models import dixon_coles as dc

df = load_tier1(divs=["E0"])
cutoff = df["date"].max() - pd.Timedelta(days=365 * 10)
train = df[df["date"] >= cutoff].copy()

data = train.dropna(subset=["home_team", "away_team", "ft_home", "ft_away", "date"]).copy()
data["date"] = pd.to_datetime(data["date"])
teams = sorted(set(data["home_team"]) | set(data["away_team"]))
n = len(teams)
idx = {t: i for i, t in enumerate(teams)}
hi = np.array([idx[t] for t in data["home_team"]])
ai = np.array([idx[t] for t in data["away_team"]])
hg = np.clip(data["ft_home"].to_numpy(float), 0, 10)
ag = np.clip(data["ft_away"].to_numpy(float), 0, 10)
log_fact = gammaln(hg + 1) + gammaln(ag + 1)
last = data["date"].max()
days = (last - data["date"]).dt.total_seconds() / 86400.0
w = np.power(0.5, days / 180.0).to_numpy()

p0 = np.concatenate([np.zeros(n), np.zeros(n),
                     [np.log(max(hg.mean() + ag.mean(), 0.5))],
                     [np.log(1.25)], [0.0]])
bounds = [(-4, 4)] * (2 * n) + [(-3, 4), (-1, 2), (-0.5, 0.5)]
args = (n, hi, ai, hg, ag, w, log_fact)

for maxiter in (500, 1000, 3000):
    res = minimize(dc._fg, p0, args=args, jac=True, method="L-BFGS-B",
                   bounds=bounds, options={"maxiter": maxiter, "ftol": 1e-12,
                                           "maxfun": maxiter * 30})
    print(f"maxiter={maxiter:<6} success={res.success}  nit={res.nit:<5} nfev={res.nfev:<5} "
          f"fun={res.fun:.6f}")
    print(f"    status={res.status}  msg={str(res.message)[:90]}")

# 检查梯度量级（L-BFGS-B 的 ftol 判据）
res = minimize(dc._fg, p0, args=args, jac=True, method="L-BFGS-B",
               bounds=bounds, options={"maxiter": 3000, "ftol": 1e-12, "maxfun": 90000})
f = lambda p: dc._fg(p, *args)[0]
eps = 1e-6
g = np.zeros_like(res.x)
for i in (2 * n, 2 * n + 1, 2 * n + 2):  # 只查 mu/gamma/rho 三个全局参数
    p1 = res.x.copy(); p1[i] += eps
    p2 = res.x.copy(); p2[i] -= eps
    g[i] = (f(p1) - f(p2)) / (2 * eps)
print(f"\n最终 fun={res.fun:.8f}")
print(f"全局参数梯度: mu={g[2*n]:.3e} gamma={g[2*n+1]:.3e} rho={g[2*n+2]:.3e}")
print(f"rho = {res.x[2*n+2]:.5f}")
