"""回测指标：准确率、对数损失、Brier、校准、模拟投注 ROI。

统一的行格式（dict）——每场比赛一行：
    p_home / p_draw / p_away   模型概率（和为 1）
    actual                     实际结果 'H' / 'D' / 'A'
    odds_home/draw/away        可选，收盘赔率（含水位），用于 ROI

不依赖任何模型代码，便于单独测试。
"""
from __future__ import annotations

import math
from typing import Any, Sequence

RESULT_KEYS = ("H", "D", "A")
_EPS = 1e-12


def result_label(home_goals: float, away_goals: float) -> str:
    if home_goals > away_goals:
        return "H"
    if home_goals == away_goals:
        return "D"
    return "A"


def _probs(row: dict[str, Any]) -> tuple[float, float, float]:
    return (float(row["p_home"]), float(row["p_draw"]), float(row["p_away"]))


def _actual_index(row: dict[str, Any]) -> int:
    return RESULT_KEYS.index(row["actual"])


def accuracy(rows: Sequence[dict[str, Any]]) -> float:
    """胜平负 argmax 命中率。"""
    if not rows:
        return float("nan")
    hit = 0
    for r in rows:
        p = _probs(r)
        pred = RESULT_KEYS[max(range(3), key=lambda i: p[i])]
        hit += pred == r["actual"]
    return hit / len(rows)


def baseline_home_accuracy(rows: Sequence[dict[str, Any]]) -> float:
    """基准：永远猜主胜。"""
    if not rows:
        return float("nan")
    return sum(1 for r in rows if r["actual"] == "H") / len(rows)


def log_loss(rows: Sequence[dict[str, Any]]) -> float:
    """多分类对数损失（越小越好；随机猜 = ln3 ≈ 1.0986）。"""
    if not rows:
        return float("nan")
    s = 0.0
    for r in rows:
        p = _probs(r)[_actual_index(r)]
        s += -math.log(max(p, _EPS))
    return s / len(rows)


def brier(rows: Sequence[dict[str, Any]]) -> float:
    """多分类 Brier 分数（越小越好；随机猜 ≈ 0.667）。"""
    if not rows:
        return float("nan")
    s = 0.0
    for r in rows:
        p = _probs(r)
        idx = _actual_index(r)
        s += sum((p[i] - (1.0 if i == idx else 0.0)) ** 2 for i in range(3))
    return s / len(rows)


def calibration(rows: Sequence[dict[str, Any]], bins: int = 10) -> list[dict[str, Any]]:
    """校准表：按"最高概率"分箱，比较预测概率与实际命中率。

    返回每箱 {lo, hi, n, pred_mean, emp_freq}。
    """
    if not rows:
        return []
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    for r in rows:
        p = _probs(r)
        idx = max(range(3), key=lambda i: p[i])
        pmax = p[idx]
        b = min(int(pmax * bins), bins - 1)
        buckets[b].append((pmax, 1 if idx == _actual_index(r) else 0))
    out = []
    for i, b in enumerate(buckets):
        if not b:
            continue
        pred_mean = sum(x for x, _ in b) / len(b)
        emp = sum(y for _, y in b) / len(b)
        out.append({"lo": i / bins, "hi": (i + 1) / bins, "n": len(b),
                    "pred_mean": pred_mean, "emp_freq": emp})
    return out


def ece(rows: Sequence[dict[str, Any]], bins: int = 10) -> float:
    """期望校准误差（Expected Calibration Error）。

    ECE = Σ (n_b / N) · |预测概率均值 - 实际命中率|，分箱同 :func:`calibration`。
    越小越好；用于量化模型过度自信。Dixon-Coles 回测实测偏自信
    （低置信区间预测明显高于实际），ECE 可把这一偏差压成一个数。
    """
    cal = calibration(rows, bins=bins)
    n = len(rows)
    if not n or not cal:
        return float("nan")
    return float(sum(c["n"] / n * abs(c["pred_mean"] - c["emp_freq"]) for c in cal))


def _odds(row: dict[str, Any]) -> tuple[float, float, float]:
    def _one(key: str) -> float:
        v = row.get(key)
        if v is None:
            return 0.0
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.0
        return 0.0 if math.isnan(f) else f
    return (_one("odds_home"), _one("odds_draw"), _one("odds_away"))


def has_odds(rows: Sequence[dict[str, Any]]) -> bool:
    return any(_odds(r)[0] > 1.0 for r in rows)


def simulate_bets(rows: Sequence[dict[str, Any]],
                  ev_threshold: float = 0.0,
                  flat_stake: float = 1.0) -> dict[str, Any]:
    """按"模型 EV > 阈值"逐场平注投注，返回收益指标。

    EV = p_model * odds - 1。
    策略：对每个 EV 超阈值的选项下注（同一场可能有多个选项）。
    用原始赔率（含水位），因此这是**真实可下注**口径，不含去水捷径。
    """
    n_bets = staked = profit = hits = 0
    equity = [0.0]
    evs: list[float] = []
    for r in rows:
        if not has_odds([r]):
            continue
        p = _probs(r)
        o = _odds(r)
        idx = _actual_index(r)
        day_pnl = 0.0
        for i in range(3):
            if o[i] <= 1.0:
                continue
            ev = p[i] * o[i] - 1.0
            if ev <= ev_threshold:
                continue
            n_bets += 1
            staked += flat_stake
            evs.append(ev)
            if i == idx:
                profit += flat_stake * (o[i] - 1.0)
                hits += 1
                day_pnl += flat_stake * (o[i] - 1.0)
            else:
                profit -= flat_stake
                day_pnl -= flat_stake
        equity.append(equity[-1] + day_pnl)

    peak = -1e18
    max_dd = 0.0
    for v in equity:
        peak = max(peak, v)
        max_dd = max(max_dd, peak - v)

    return {
        "n_bets": n_bets,
        "staked": staked,
        "profit": profit,
        "roi": (profit / staked) if staked > 0 else float("nan"),
        "hit_rate": (hits / n_bets) if n_bets > 0 else float("nan"),
        "avg_ev": (sum(evs) / len(evs)) if evs else float("nan"),
        "max_drawdown": max_dd,
        "final_equity": equity[-1],
    }


def evaluate(rows: Sequence[dict[str, Any]],
             ev_threshold: float = 0.0,
             bins: int = 10) -> dict[str, Any]:
    """汇总一份完整的指标包。"""
    out: dict[str, Any] = {
        "n": len(rows),
        "accuracy": accuracy(rows),
        "baseline_home": baseline_home_accuracy(rows),
        "log_loss": log_loss(rows),
        "brier": brier(rows),
        "ece": ece(rows, bins=bins),
        "calibration": calibration(rows, bins=bins),
        "has_odds": has_odds(rows),
    }
    if out["has_odds"]:
        out["betting"] = simulate_bets(rows, ev_threshold=ev_threshold)
    return out
