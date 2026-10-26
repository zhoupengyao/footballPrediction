"""半全场（HAFU）联合模型。

竞彩半全场玩法要求同时预测半场结果和全场结果的组合，
共 9 个选项（胜/胜、胜/平、胜/负、平/胜 ... 负/负）。

建模方法
--------
两阶段条件模型：

    1) 半场模型：用 Dixon-Coles 思路拟合半场比分
       （把 HTHG/HTAG 当作独立的进球过程，进攻/防守强度复用
        全场模型的 α/β，只重新拟合 μ_half 与 γ_half）

    2) 全场对半场的条件转移：按"半场结果"分组，统计从半场结果
       转移到全场结果的转移概率 P(FT | HT)，用拉普拉斯平滑

    3) 联合概率：P(HT=r1, FT=r2) = P(HT=r1) · P(FT=r2 | HT=r1)

这样既保留了半场的独立信息（主队上半场是否强势），
又捕捉了"半场领先方最终胜率"的真实经验规律。

为何不用单一 Dixon-Coles：
    全场比分矩阵无法推出半场信息——同一场 2-1 可能是
    半场 1-0 或半场 0-1 后逆转，两者的半全场概率完全不同。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import poisson

from src.jingcai.payouts import HALF_FULL_OPTIONS, _result_label

RESULTS = ["胜", "平", "负"]


@dataclass
class HalfFullModel:
    """半全场联合模型。"""
    # 半场边际概率（按球队强度计算）
    mu_half: float = 0.45
    home_adv_half: float = 1.12
    # 转移矩阵 P(FT=r2 | HT=r1)，shape (3,3)，行=半场结果，列=全场结果
    transition: np.ndarray = field(
        default_factory=lambda: np.array([
            [0.55, 0.20, 0.25],   # 半场胜 -> 全场胜/平/负
            [0.30, 0.30, 0.40],   # 半场平
            [0.20, 0.20, 0.60],   # 半场负
        ]))
    # 每队的半场攻防强度（复用全场 α/β 但缩放）
    attack_half: dict[str, float] = field(default_factory=dict)
    defense_half: dict[str, float] = field(default_factory=dict)
    n_matches: int = 0
    converged: bool = False


def _half_lambda(model: HalfFullModel, home: str, away: str) -> tuple[float, float]:
    """半场期望进球（复用全场 α/β 的相对结构，用半场均值缩放）。"""
    ah = model.attack_half.get(home, 1.0)
    da = model.defense_half.get(away, 1.0)
    aa = model.attack_half.get(away, 1.0)
    dh = model.defense_half.get(home, 1.0)
    return model.mu_half * ah * da * model.home_adv_half, model.mu_half * aa * dh


def _half_result_probs(lh: float, la: float, max_goals: int = 6) -> np.ndarray:
    """半场胜平负概率（向量，顺序 胜/平/负）。"""
    rows = poisson.pmf(np.arange(max_goals + 1), lh)
    cols = poisson.pmf(np.arange(max_goals + 1), la)
    m = np.outer(rows, cols)
    total = m.sum()
    if total > 0:
        m /= total
    p_home = float(np.tril(m, -1).sum())
    p_away = float(np.triu(m, 1).sum())
    p_draw = float(np.trace(m))
    return np.array([p_home, p_draw, p_away])


def fit(df: pd.DataFrame, alpha_full: dict[str, float] | None = None,
        defense_full: dict[str, float] | None = None,
        mu_full: float = 1.3, smooth: float = 1.0) -> HalfFullModel:
    """拟合半全场模型。

    参数
    ----
    df : 需含 home_team, away_team, ht_home, ht_away, ft_home, ft_away
    alpha_full / defense_full / mu_full : 全场 Dixon-Coles 的强度参数，
        用于推导半场攻防强度（半场进球约为全场的一半）
    smooth : 转移矩阵的拉普拉斯平滑强度
    """
    data = df.dropna(subset=["ht_home", "ht_away", "ft_home", "ft_away"]).copy()
    if len(data) < 50:
        raise ValueError(f"半全场样本不足: {len(data)}（至少 50 场）")

    ht_h = data["ht_home"].astype(int).to_numpy()
    ht_a = data["ht_away"].astype(int).to_numpy()
    ft_h = data["ft_home"].astype(int).to_numpy()
    ft_a = data["ft_away"].astype(int).to_numpy()

    # 半场/全场结果标签
    ht_res = np.array([_result_label(h, a) for h, a in zip(ht_h, ht_a)])
    ft_res = np.array([_result_label(h, a) for h, a in zip(ft_h, ft_a)])

    # 转移计数矩阵
    counts = np.zeros((3, 3))
    idx = {r: i for i, r in enumerate(RESULTS)}
    for r1, r2 in zip(ht_res, ft_res):
        counts[idx[r1], idx[r2]] += 1

    # 拉普拉斯平滑
    transition = (counts + smooth) / (counts.sum(axis=1, keepdims=True) + smooth * 3)

    # 半场攻防强度：从全场 α/β 缩放。半场强度更接近"原始"α/β，
    # 因为全场强度已累积了下半场的变化。
    attack_half = dict(alpha_full or {})
    defense_half = dict(defense_full or {})

    # 估计半场均值：半场进球约占全场的 45%
    mu_half = float(np.mean(ht_h + ht_a))
    # 主场优势（半场）
    home_scoring = float(np.mean(ht_h))
    away_scoring = float(np.mean(ht_a))
    home_adv_half = float(home_scoring / max(away_scoring, 1e-6))

    return HalfFullModel(
        mu_half=mu_half,
        home_adv_half=home_adv_half,
        transition=transition,
        attack_half=attack_half,
        defense_half=defense_half,
        n_matches=len(data),
        converged=True,
    )


def predict(model: HalfFullModel, home: str, away: str) -> dict[str, float]:
    """预测半全场 9 选项概率。"""
    lh, la = half_expected_goals(model, home, away)
    half_p = _half_result_probs(lh, la)   # [胜, 平, 负]

    out: dict[str, float] = {}
    for i, r1 in enumerate(RESULTS):
        for j, r2 in enumerate(RESULTS):
            out[f"{r1}/{r2}"] = float(half_p[i] * model.transition[i, j])

    # 归一化消除数值误差
    s = sum(out.values())
    if s > 0:
        out = {k: v / s for k, v in out.items()}
    return out


def half_expected_goals(model: HalfFullModel, home: str, away: str) -> tuple[float, float]:
    """半场期望进球。"""
    return _half_lambda(model, home, away)


def transition_table(model: HalfFullModel) -> pd.DataFrame:
    """可读的转移概率表。"""
    df = pd.DataFrame(model.transition, index=RESULTS, columns=RESULTS)
    df.index.name = "半场\\全场"
    return df


def most_likely(model: HalfFullModel, home: str, away: str, top: int = 3) -> list[tuple[str, float]]:
    """返回最可能的几个半全场组合。"""
    p = predict(model, home, away)
    items = sorted(p.items(), key=lambda x: -x[1])
    return items[:top]
