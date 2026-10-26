"""竞彩玩法概率映射：从比分矩阵推导全部竞彩玩法概率。

核心思路
--------
Dixon-Coles 输出 (max_goals+1)² 的比分概率矩阵（行=主队进球，
列=客队进球）。竞彩所有玩法都能从这个矩阵求和得到：

    胜平负      主胜/平/客胜三块求和
    让球胜平负  按**竞彩官方让球数**对每格施加让球后重算
    比分        直接读矩阵；竞彩含高比分归并桶（1+:胜/平/负）
    总进球      按进球数求和；竞彩含 7+ 桶
    半全场      需半场模型（本模块用条件近似，见 halffull.py）
    混合过关    各场概率连乘 + 相关性折扣

重要约定
--------
* 让球数**只用竞彩官方给定值**，模型绝不自定。
* 让球数为负表示主队让球（如 -1 = 主队让 1 球），
  为正表示主队受让（如 +1 = 主队受让 1 球）。
* 让球后按"让球后的净胜球"判定胜平负。
"""
from __future__ import annotations

from typing import Any

import numpy as np

# 竞彩总进球玩法的桶定义
TTG_BUCKETS = ["0", "1", "2", "3", "4", "5", "6", "7+"]
TTG_BUCKET_EDGES = [0, 1, 2, 3, 4, 5, 6, 7]  # 左闭右开，最后一个到 +inf

# 竞彩半全场玩法的 9 个选项
HALF_FULL_OPTIONS = [
    "胜/胜", "胜/平", "胜/负",
    "平/胜", "平/平", "平/负",
    "负/胜", "负/平", "负/负",
]

# 竞彩比分玩法的高比分归并桶
CRS_BUCKETS = ["1+:胜", "1+:平", "1+:负"]

MAX_SCORE = 5  # 竞彩比分玩法显式列出 0-0 到 5-5


def _result_label(h: int, a: int) -> str:
    if h > a:
        return "胜"
    if h == a:
        return "平"
    return "负"


def had_probabilities(matrix: np.ndarray) -> dict[str, float]:
    """胜平负概率（90 分钟）。"""
    p_home = float(np.tril(matrix, -1).sum())
    p_away = float(np.triu(matrix, 1).sum())
    p_draw = float(np.trace(matrix))
    return {"胜": p_home, "平": p_draw, "负": p_away}


def hhad_probabilities(matrix: np.ndarray, goal_line: float) -> dict[str, float]:
    """让球胜平负概率。

    参数
    ----
    matrix : 比分概率矩阵，行=主队进球，列=客队进球
    goal_line : 竞彩官方让球数。负=主队让球，正=主队受让。
                例：-1 表示主队让 1 球（即主队净胜球需 > 1 才算"胜"）
    """
    n = matrix.shape[0]
    # 让球后净胜球 = (主队进球 + 让球数) - 客队进球
    # goal_line 为负时主队让球，等价于主队进球先加上该值
    adj = float(goal_line)
    p = {"胜": 0.0, "平": 0.0, "负": 0.0}
    for h in range(n):
        for a in range(n):
            diff = (h + adj) - a
            if diff > 0:
                p["胜"] += float(matrix[h, a])
            elif diff == 0:
                p["平"] += float(matrix[h, a])
            else:
                p["负"] += float(matrix[h, a])
    return p


def total_goals_probabilities(total_goals_dist: dict[str, float]) -> dict[str, float]:
    """总进球概率（映射到竞彩 0..7+ 桶）。"""
    out = {b: 0.0 for b in TTG_BUCKETS}
    for k, v in total_goals_dist.items():
        if k == "7+":
            out["7+"] += float(v)
            continue
        try:
            i = int(k)
        except (TypeError, ValueError):
            continue
        if i >= 7:
            out["7+"] += float(v)
        else:
            out[str(i)] += float(v)
    return out


def correct_score_probabilities(matrix: np.ndarray) -> dict[str, float]:
    """比分概率，含竞彩的高比分归并桶。

    返回 key 形如 '0:0' .. '5:5'，外加 '1+:胜' / '1+:平' / '1+:负'。
    归并桶含义：主队进球 ≥ 1 且该桶结果成立，且比分不在 0-5 显式列出范围内。
    """
    n = min(matrix.shape[0], MAX_SCORE + 1)
    out: dict[str, float] = {}
    for h in range(n):
        for a in range(n):
            out[f"{h}:{a}"] = float(matrix[h, a])

    # 归并桶：主队进球 >= 1 且总比分超出显式范围（任一边 >= 6）
    rem = {"胜": 0.0, "平": 0.0, "负": 0.0}
    full = matrix.shape[0]
    for h in range(1, full):
        for a in range(full):
            if h >= 6 or a >= 6:
                rem[_result_label(h, a)] += float(matrix[h, a])

    for lab in ("胜", "平", "负"):
        out[f"1+:{lab}"] = rem[lab]
    return out


def all_market_probabilities(matrix: np.ndarray,
                             total_goals_dist: dict[str, float],
                             goal_line: float | None = None,
                             half_full: dict[str, float] | None = None) -> dict[str, Any]:
    """一次性输出全部竞彩玩法概率。"""
    out: dict[str, Any] = {
        "HAD": had_probabilities(matrix),
        "TTG": total_goals_probabilities(total_goals_dist),
        "CRS": correct_score_probabilities(matrix),
    }
    if goal_line is not None:
        out["HHAD"] = hhad_probabilities(matrix, goal_line)
    if half_full is not None:
        out["HAFU"] = half_full
    return out


def normalize_to_one(d: dict[str, float]) -> dict[str, float]:
    """归一化（去水）：使概率和为 1。"""
    s = float(sum(d.values()))
    if s <= 0:
        n = len(d)
        return {k: 1.0 / n for k in d}
    return {k: v / s for k, v in d.items()}


def implied_probabilities(odds: dict[str, float]) -> dict[str, float]:
    """赔率 → 去水隐含概率。

    竞彩赔率已含返奖率（约 73%），直接取 1/odds 之和大于 1，
    需按比例归一化以还原"市场认为的公平概率"。
    """
    valid = {k: v for k, v in odds.items() if v and v > 0}
    if not valid:
        return {k: 0.0 for k in odds}
    inv = {k: 1.0 / v for k, v in valid.items()}
    return normalize_to_one(inv)


def overround(odds: dict[str, float]) -> float:
    """赔率隐含的水位（返奖率倒数 - 1）。越小对玩家越有利。"""
    valid = [v for v in odds.values() if v and v > 0]
    if not valid:
        return float("nan")
    return float(sum(1.0 / v for v in valid) - 1.0)


def payout_ratio(odds: dict[str, float]) -> float:
    """实际返奖率 = 1 / (1 + overround)。"""
    o = overround(odds)
    return float(1.0 / (1.0 + o)) if np.isfinite(o) else float("nan")


def value_bets(model_probs: dict[str, float], odds: dict[str, float],
               edge_threshold: float = 0.05,
               min_odds: float = 0.0,
               max_edge: float = float("inf")) -> list[dict[str, Any]]:
    """找出有价值的选择。

    edge = 模型概率 - 去水隐含概率
    只返回 edge > 阈值的选项。

    过滤规则（针对模型过度自信导致的虚假 edge）：
        min_odds  : 低于该赔率的选项直接丢弃（低赔率无肉且波动小）
        max_edge  : 高于该 edge 的选项丢弃（异常高 edge 多为数据/队名错误）

    返回列表按 edge 降序，每项含:
        option, odds, model_prob, implied_prob, edge, ev
        ev = 期望收益率 = model_prob * odds - 1
    """
    imp = implied_probabilities(odds)
    out = []
    for opt, o in odds.items():
        if not o or o <= 0:
            continue
        if min_odds and o < min_odds:
            continue
        mp = float(model_probs.get(opt, 0.0))
        ip = float(imp.get(opt, 0.0))
        edge = mp - ip
        ev = mp * o - 1.0
        if edge <= edge_threshold:
            continue
        if max_edge is not None and edge > max_edge:
            continue
        out.append({
            "option": opt,
            "odds": o,
            "model_prob": mp,
            "implied_prob": ip,
            "edge": edge,
            "ev": ev,
        })
    out.sort(key=lambda x: -x["edge"])
    return out


def blend_probabilities(model_probs: dict[str, float],
                        market_probs: dict[str, float],
                        weight: float = 0.6) -> dict[str, float]:
    """把模型概率向去水市场概率收缩。

    p_final = weight * p_model + (1 - weight) * p_market，再归一化。
    weight=1 表示纯模型，weight=0 表示纯市场。

    用途：缓解 Dixon-Coles 的过度自信——回测显示模型在低置信区间系统性
    高估（预测 0.446 实际 0.364），与市场混合后 edge 会被按比例压缩，
    从而压制大部分虚假价值信号。
    """
    weight = max(0.0, min(1.0, float(weight)))
    if weight >= 1.0:
        return normalize_to_one(dict(model_probs))
    if weight <= 0.0:
        return normalize_to_one(dict(market_probs))
    keys = [k for k in model_probs if k in market_probs] or list(model_probs)
    blended = {k: weight * float(model_probs.get(k, 0.0))
               + (1 - weight) * float(market_probs.get(k, 0.0)) for k in keys}
    return normalize_to_one(blended)


def kelly_stake(ev_edge: float, odds: float, prob: float,
                kelly_fraction: float = 0.25,
                max_stake_pct: float = 0.02) -> float:
    """分数 Kelly 仓位（占总资金比例）。

    完整 Kelly：f* = (p·b - q) / b，其中 b = odds - 1，q = 1 - p
    本实现用分数 Kelly 降低波动，并设单场上限。

    返回值已限制在 [0, max_stake_pct]。
    """
    if odds <= 1.0 or prob <= 0.0:
        return 0.0
    b = odds - 1.0
    q = 1.0 - prob
    f_star = (prob * b - q) / b
    if f_star <= 0:
        return 0.0
    f = f_star * kelly_fraction
    return float(min(f, max_stake_pct))


def parlay_probabilities(single_probs: list[float],
                         correlation_discount: float = 0.03) -> float:
    """混合过关：各场概率连乘，并施加相关性折扣。

    同一轮次/同一联赛的比赛并非独立（红牌、天气、赛程等共享冲击），
    直接连乘会低估方差。这里对连乘结果施加折扣以提高保守性。

    correlation_discount: 每多一场额外扣减的比例（0.03 = 每场扣 3%）。
    """
    if not single_probs:
        return 0.0
    p = 1.0
    for x in single_probs:
        p *= float(x)
    # 折扣随注数增加（2 场扣 3%，3 场扣 6%...）
    n = len(single_probs)
    discount = 1.0 - correlation_discount * max(n - 1, 0)
    return float(max(p * discount, 0.0))


def parlay_odds(single_odds: list[float]) -> float:
    """过关组合赔率 = 各场赔率连乘。"""
    p = 1.0
    for o in single_odds:
        p *= float(o)
    return float(p)
