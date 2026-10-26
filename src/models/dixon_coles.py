"""带解析梯度的 Dixon-Coles 拟合（从零实现）。

模型
----
每场比赛 i（主场）vs j（客场）的期望进球：

    λ_home = μ · α_i · β_j · γ
    λ_away = μ · α_j · β_i

其中 μ 为平均进球强度、α 进攻强度、β 防守强度（越大防守越差）、
γ 为主场优势。

进球数按独立 Poisson 建模，Dixon-Coles (1997) 用 τ 修正低比分的
联合分布偏差（仅 0-0 / 1-0 / 0-1 / 1-1 四格）：

    τ(x, y) =
        1 - λ_h·λ_a·ρ      x=0, y=0
        1 + λ_a·ρ          x=0, y=1
        1 + λ_h·ρ          x=1, y=0
        1 - ρ              x=1, y=1
        1                  其他

时间衰减：w_k = 0.5 ** (days_since / half_life)

可识别性：α 与 β 都需中心化，否则 μ 与 β 存在缩放自由度
（β→cβ、μ→μ/c 时 λ 不变）。实现为
    α = exp(θ - mean(θ))，β = exp(φ - mean(φ))

解析梯度：相比数值梯度（每次迭代需 n_params+1 次函数求值），
解析梯度只需 1 次，拟合提速约 50 倍。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import gammaln
from scipy.stats import poisson

# 比分矩阵最大维度（超过此比分归入最高桶）
MAX_GOALS = 10
DEFAULT_HALF_LIFE = 180.0


@dataclass
class DixonColesResult:
    """拟合结果。"""
    teams: list[str]
    mu: float
    home_advantage: float
    rho: float
    attack: dict[str, float]
    defense: dict[str, float]
    n_matches: int
    log_likelihood: float
    converged: bool
    half_life_days: float
    fitted_at: str = ""
    _att_arr: np.ndarray = field(default_factory=lambda: np.array([]))
    _def_arr: np.ndarray = field(default_factory=lambda: np.array([]))
    _idx: dict[str, int] = field(default_factory=dict)

    def strength(self, team: str) -> tuple[float, float]:
        """返回 (进攻强度 α, 防守强度 β)。"""
        return self.attack.get(team, 1.0), self.defense.get(team, 1.0)


def _tau(hg: np.ndarray, ag: np.ndarray, lh: np.ndarray,
         la: np.ndarray, rho: float) -> np.ndarray:
    """向量化的 DC 低比分修正因子。"""
    tau = np.ones_like(hg, dtype=float)
    m00 = (hg == 0) & (ag == 0)
    m01 = (hg == 0) & (ag == 1)
    m10 = (hg == 1) & (ag == 0)
    m11 = (hg == 1) & (ag == 1)
    tau[m00] = 1.0 - lh[m00] * la[m00] * rho
    tau[m01] = 1.0 + la[m01] * rho
    tau[m10] = 1.0 + lh[m10] * rho
    tau[m11] = 1.0 - rho
    return tau


def _unpack(params: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray, float, float, float]:
    """解包参数并施加中心化约束。"""
    theta = params[:n]
    phi = params[n:2 * n]
    log_mu = params[2 * n]
    log_gamma = params[2 * n + 1]
    rho = params[2 * n + 2]
    alpha = np.exp(theta - theta.mean())
    beta = np.exp(phi - phi.mean())
    return alpha, beta, float(np.exp(log_mu)), float(np.exp(log_gamma)), float(rho)


def _fg(params: np.ndarray, n: int, hi: np.ndarray, ai: np.ndarray,
        hg: np.ndarray, ag: np.ndarray, w: np.ndarray,
        log_fact: np.ndarray) -> tuple[float, np.ndarray]:
    """目标函数与其解析梯度（返回负对数似然，梯度指向下降方向）。"""
    alpha, beta, mu, gamma, rho = _unpack(params, n)

    lh = mu * alpha[hi] * beta[ai] * gamma
    la = mu * alpha[ai] * beta[hi]

    tau = _tau(hg, ag, lh, la, rho)
    if np.any(tau <= 0) or np.any(lh <= 0) or np.any(la <= 0):
        return 1e12, np.zeros_like(params)

    # 对数似然
    ll = hg * np.log(lh) - lh + ag * np.log(la) - la - log_fact + np.log(tau)
    f = -float(np.dot(w, ll))

    # --- τ 的偏导 ---
    dt_dlh = np.zeros_like(lh)
    dt_dla = np.zeros_like(la)
    dt_drho = np.zeros_like(lh)
    m00 = (hg == 0) & (ag == 0)
    m01 = (hg == 0) & (ag == 1)
    m10 = (hg == 1) & (ag == 0)
    m11 = (hg == 1) & (ag == 1)
    dt_dlh[m00] = -la[m00] * rho;  dt_dla[m00] = -lh[m00] * rho;  dt_drho[m00] = -lh[m00] * la[m00]
    dt_dla[m01] = rho;             dt_drho[m01] = la[m01]
    dt_dlh[m10] = rho;             dt_drho[m10] = lh[m10]
    dt_drho[m11] = -1.0

    # 对 λ 的有效梯度（含 τ 贡献），已乘权重
    u = w * (hg / lh - 1.0 + dt_dlh / tau)   # d(-LL)/d_lh 的相反方向系数
    v = w * (ag / la - 1.0 + dt_dla / tau)

    P = u * lh   # 主队进球侧贡献
    Q = v * la   # 客队进球侧贡献

    g = np.zeros_like(params)

    # μ、γ、ρ
    g[2 * n] = -float(np.sum(P + Q))            # d LL / d log_mu
    g[2 * n + 1] = -float(np.sum(P))            # d LL / d log_gamma
    g[2 * n + 2] = -float(np.sum(w * dt_drho / tau))  # d LL / d rho

    # α、β 梯度。两者在 λ 中的位置是交叉的：
    #   α_i 出现在 λ_h 的主队位、λ_a 的客队位
    #   β_i 出现在 λ_h 的客队位、λ_a 的主队位
    # 故 bincount 的索引需对调。
    G_att = np.bincount(hi, weights=P, minlength=n) + np.bincount(ai, weights=Q, minlength=n)
    G_def = np.bincount(ai, weights=P, minlength=n) + np.bincount(hi, weights=Q, minlength=n)
    g[:n] = -(G_att - G_att.mean())      # 中心化后的 θ 梯度
    g[n:2 * n] = -(G_def - G_def.mean())  # 中心化后的 φ 梯度

    return f, g


def _prep(df: pd.DataFrame, half_life_days: float, max_goals: int,
          min_weight: float) -> dict[str, Any]:
    """预处理训练数据：排序、索引化、时间权重、截断低权重样本。"""
    data = df.dropna(subset=["home_team", "away_team", "ft_home", "ft_away", "date"]).copy()
    data["date"] = pd.to_datetime(data["date"])
    data = data.sort_values("date").reset_index(drop=True)
    if len(data) < 20:
        raise ValueError(f"样本量不足: {len(data)} 场（至少需 20 场）")

    teams = sorted(set(data["home_team"]) | set(data["away_team"]))
    n = len(teams)
    idx = {t: i for i, t in enumerate(teams)}

    hi = np.array([idx[t] for t in data["home_team"]], dtype=int)
    ai = np.array([idx[t] for t in data["away_team"]], dtype=int)
    hg = np.clip(data["ft_home"].to_numpy(float), 0, max_goals)
    ag = np.clip(data["ft_away"].to_numpy(float), 0, max_goals)
    log_fact = gammaln(hg + 1) + gammaln(ag + 1)

    last = data["date"].max()
    days = (last - data["date"]).dt.total_seconds() / 86400.0
    w = np.power(0.5, days / max(half_life_days, 1.0)).to_numpy()

    # 时间衰减下，极老样本权重可忽略，剔除以加速（对结果影响 < min_weight）
    if min_weight > 0:
        keep = w >= min_weight
        # 保证每支球队仍有足够样本：只在整体剔除不会导致球队消失时生效
        if keep.sum() >= 100:
            kept_teams = set(data.loc[keep, "home_team"]) | set(data.loc[keep, "away_team"])
            if len(kept_teams) == len(teams):
                hi, ai, hg, ag, w, log_fact = hi[keep], ai[keep], hg[keep], ag[keep], w[keep], log_fact[keep]
                data = data.loc[keep].reset_index(drop=True)

    return {"teams": teams, "n": n, "idx": idx, "hi": hi, "ai": ai,
            "hg": hg, "ag": ag, "w": w, "log_fact": log_fact, "n_matches": len(data)}


def fit(df: pd.DataFrame, half_life_days: float = DEFAULT_HALF_LIFE,
        max_goals: int = MAX_GOALS, maxiter: int = 5000,
        min_weight: float = 0.01, grad_tol: float = 1e-4,
        shrinkage_prior: float = 0.0) -> DixonColesResult:
    """拟合 Dixon-Coles 模型。

    参数
    ----
    df : 需含 home_team, away_team, ft_home, ft_away, date
    half_life_days : 时间衰减半衰期（天）
    max_goals : 进球截断上限
    maxiter : 优化器最大迭代次数
    min_weight : 剔除权重低于此值的历史样本以加速（0 表示不剔除）
    grad_tol : 梯度无穷范数收敛阈值
    shrinkage_prior : 攻防强度的小样本收缩先验「场数」（empirical Bayes）。
        每队 θ/φ 向联赛均值收缩，收缩系数 s_i = n_i / (n_i + prior)，
        n_i 为该队出场数。0 表示不收缩。
        用于缓解样本少的球队（欧战新军、升班马）参数偏乐观的问题。

    说明
    ----
    时间衰减使似然面较平坦（有效样本量远小于名义样本量），
    scipy 的 success 标志依赖相对函数值判据，常在梯度已足够小
    时仍报未收敛。因此这里以梯度范数作为收敛判据。
    """
    from datetime import timezone

    p = _prep(df, half_life_days, max_goals, min_weight)
    n, hi, ai, hg, ag, w, log_fact = (
        p["n"], p["hi"], p["ai"], p["hg"], p["ag"], p["w"], p["log_fact"])

    p0 = np.concatenate([
        np.zeros(n), np.zeros(n),
        [np.log(max(hg.mean() + ag.mean(), 0.5))],
        [np.log(1.25)],
        [0.0],
    ])
    bounds = [(-4, 4)] * (2 * n) + [(-3, 4), (-1, 2), (-0.5, 0.5)]
    args = (n, hi, ai, hg, ag, w, log_fact)

    res = minimize(_fg, p0, args=args, jac=True, method="L-BFGS-B",
                   bounds=bounds, options={"maxiter": maxiter, "ftol": 1e-14})

    grad_max = float(np.abs(res.jac).max())
    converged = bool(res.success) or grad_max < grad_tol

    mu, gamma, rho = _unpack(res.x, n)[2:]
    if shrinkage_prior > 0:
        # 小样本收缩：θ/φ 向联赛均值(0)收缩
        theta = res.x[:n]
        phi = res.x[n:2 * n]
        theta = theta - theta.mean()
        phi = phi - phi.mean()
        counts = np.bincount(hi, minlength=n) + np.bincount(ai, minlength=n)
        s = counts / (counts + float(shrinkage_prior))
        alpha = np.exp(theta * s)
        beta = np.exp(phi * s)
    else:
        alpha, beta = _unpack(res.x, n)[:2]
    teams = p["teams"]

    return DixonColesResult(
        teams=teams,
        mu=mu,
        home_advantage=gamma,
        rho=rho,
        attack={teams[i]: float(alpha[i]) for i in range(n)},
        defense={teams[i]: float(beta[i]) for i in range(n)},
        n_matches=p["n_matches"],
        log_likelihood=-float(res.fun),
        converged=converged,
        half_life_days=half_life_days,
        fitted_at=pd.Timestamp.now(tz=timezone.utc).isoformat(),
        _att_arr=alpha, _def_arr=beta, _idx=p["idx"],
    )


def expected_goals(model: DixonColesResult, home: str, away: str) -> tuple[float, float]:
    """预测主客队期望进球。"""
    ah, dh = model.strength(home)
    aa, da = model.strength(away)
    return float(model.mu * ah * da * model.home_advantage), float(model.mu * aa * dh)


def score_matrix(model: DixonColesResult, home: str, away: str,
                 max_goals: int = MAX_GOALS) -> np.ndarray:
    """生成 (max_goals+1)² 比分概率矩阵（行=主队进球，列=客队进球）。"""
    lh, la = expected_goals(model, home, away)
    rows = poisson.pmf(np.arange(max_goals + 1), lh)
    cols = poisson.pmf(np.arange(max_goals + 1), la)
    m = np.outer(rows, cols)
    for x in range(min(2, max_goals + 1)):
        for y in range(min(2, max_goals + 1)):
            m[x, y] *= _tau(np.array([x]), np.array([y]),
                            np.array([lh]), np.array([la]), model.rho)[0]
    m = np.clip(m, 0, None)
    total = m.sum()
    m /= total if total > 0 else m.size
    return m


def predict_proba(model: DixonColesResult, home: str, away: str) -> dict[str, Any]:
    """输出胜平负概率、期望进球、总进球分布。"""
    m = score_matrix(model, home, away)
    lh, la = expected_goals(model, home, away)

    p_home = float(np.tril(m, -1).sum())
    p_away = float(np.triu(m, 1).sum())
    p_draw = float(np.trace(m))

    tg_len = m.shape[0] * 2 - 1
    total_goals = np.zeros(tg_len)
    for x in range(m.shape[0]):
        for y in range(m.shape[1]):
            total_goals[x + y] += m[x, y]

    tg = {str(i): float(total_goals[i]) for i in range(min(7, tg_len))}
    tg["7+"] = float(total_goals[7:].sum())

    return {"home": home, "away": away, "xg_home": lh, "xg_away": la,
            "prob_home": p_home, "prob_draw": p_draw, "prob_away": p_away,
            "total_goals": tg, "score_matrix": m}


def model_summary(model: DixonColesResult, top: int = 10) -> str:
    """可读的模型摘要。"""
    lines = [
        f"样本场次: {model.n_matches}",
        f"收敛: {model.converged}  对数似然: {model.log_likelihood:.1f}",
        f"平均进球强度 μ: {model.mu:.3f}",
        f"主场优势 γ: {model.home_advantage:.3f}",
        f"DC 修正 ρ: {model.rho:.4f}",
        f"半衰期: {model.half_life_days} 天",
        "", f"进攻最强 {top} 队:",
    ]
    for t, v in sorted(model.attack.items(), key=lambda x: -x[1])[:top]:
        lines.append(f"  {t:<24} α={v:.3f}")
    lines.append(f"\n防守最好 {top} 队 (β 越小越好):")
    for t, v in sorted(model.defense.items(), key=lambda x: x[1])[:top]:
        lines.append(f"  {t:<24} β={v:.3f}")
    return "\n".join(lines)
