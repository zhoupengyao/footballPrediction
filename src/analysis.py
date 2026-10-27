"""命中分析与概率校准（纯函数，输入站点的 history 记录）。

回答两个问题：
    1. 各玩法到底对了多少？
    2. 模型给出的概率是否可信？命中集中在哪些概率区间？

只统计 ``status=settled`` 且 ``prediction_timing=pre_match`` 的场次，
避免用开赛后补跑的数据污染结论。
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any, Callable

OPTION_LABELS = {"home": "主胜", "draw": "平", "away": "客胜"}
MARKET_LABELS = {
    "HAD": "胜平负",
    "HHAD": "让球胜平负",
    "SCORE": "比分 Top3",
    "TOTAL_GOALS": "总进球",
    "HALF_FULL": "半全场",
}

# 每个玩法的概率分箱。不同玩法的置信度尺度差异很大：
# HAD 一般 30%–80%，比分 Top1 往往只有 5%–20%，不能用同一套固定分箱。
BIN_EDGES: dict[str, list[float]] = {
    "HAD": [0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0],
    "HHAD": [0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0],
    "TOTAL_GOALS": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 1.0],
    "HALF_FULL": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 1.0],
    "SCORE": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0],
    "LAYER": [0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0],
}

HIGH_CONF = {
    "HAD": 0.6, "HHAD": 0.6, "TOTAL_GOALS": 0.3,
    "HALF_FULL": 0.3, "SCORE": 0.4, "LAYER": 0.6,
}
LOW_CONF = {
    "HAD": 0.4, "HHAD": 0.4, "TOTAL_GOALS": 0.2,
    "HALF_FULL": 0.2, "SCORE": 0.3, "LAYER": 0.4,
}


# --------------------------------------------------------------------------- #
# 基础统计
# --------------------------------------------------------------------------- #
def wilson_ci(hits: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    """二项比例的 Wilson 95% 置信区间。"""
    if n <= 0:
        return None, None
    p = hits / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def _label(lo: float, hi: float) -> str:
    left = f"{round(lo * 100)}"
    right = "100" if hi >= 1.0 else f"{round(hi * 100)}"
    return f"{left}–{right}%"


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _settled(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        r for r in records
        if r.get("status") == "settled"
        and r.get("prediction_timing") == "pre_match"
        and r.get("prediction")
        and r.get("result")
    ]


def _display_option(value: Any) -> str:
    if value is None:
        return "—"
    return OPTION_LABELS.get(str(value), str(value))


def _record_base(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": r.get("date"),
        "match_num": r.get("match_num"),
        "league": (r.get("league") or {}).get("name"),
        "home": (r.get("home") or {}).get("cn"),
        "away": (r.get("away") or {}).get("cn"),
        "result": (r.get("result") or {}).get("ft"),
    }


# --------------------------------------------------------------------------- #
# 单个玩法
# --------------------------------------------------------------------------- #
def _bins(values: list[dict[str, Any]], edges: list[float]) -> list[dict[str, Any]]:
    """values 每项：confidence, hit, actual_prob。"""
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        subset = [v for v in values if lo <= (v["confidence"] or 0) < hi] \
            if hi < 1.0 else [v for v in values if lo <= (v["confidence"] or 0) <= 1.0]
        n = len(subset)
        hits = sum(1 for v in subset if v["hit"])
        preds = [v["confidence"] for v in subset if v["confidence"] is not None]
        actual_probs = [v["actual_prob"] for v in subset if v.get("actual_prob") is not None]
        avg_pred = _mean(preds)
        acc = (hits / n) if n else None
        ci_low, ci_high = wilson_ci(hits, n)
        out.append({
            "label": _label(lo, hi),
            "lo": lo,
            "hi": hi,
            "n": n,
            "hits": hits,
            "misses": n - hits,
            "accuracy": acc,
            "avg_pred": avg_pred,
            "avg_actual_prob": _mean(actual_probs),
            "gap": (acc - avg_pred) if (acc is not None and avg_pred is not None) else None,
            "ci_low": ci_low,
            "ci_high": ci_high,
        })
    return out


def _multi_class_scores(rows: list[dict[str, Any]], labels: list[str]) -> tuple[float | None, float | None]:
    """多分类 Brier + 对数损失；只对拥有完整概率分布的玩法计算。"""
    briers, losses = [], []
    for row in rows:
        probs = row.get("probs") or {}
        actual = row.get("actual")
        if actual not in labels or not probs:
            continue
        p_actual = probs.get(actual)
        if p_actual is None:
            continue
        p_actual = float(p_actual)
        briers.append(sum(
            (float(probs.get(label) or 0.0) - (1.0 if label == actual else 0.0)) ** 2
            for label in labels))
        losses.append(-math.log(max(p_actual, 1e-12)))
    return _mean(briers), _mean(losses)


def _rank_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        probs = row.get("probs") or {}
        actual = row.get("actual")
        if not probs or actual not in probs:
            continue
        order = sorted(probs, key=lambda k: float(probs.get(k) or 0.0), reverse=True)
        rank = order.index(actual) + 1
        counts[str(rank) if rank <= 3 else "other"] += 1
    return dict(counts)


def _confusion(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]] | None:
    keys = ["home", "draw", "away"]
    matrix = {a: {b: 0 for b in keys} for a in keys}
    seen = False
    for row in rows:
        pred = row.get("predicted")
        actual = row.get("actual")
        if pred in keys and actual in keys:
            matrix[pred][actual] += 1
            seen = True
    return matrix if seen else None


def _list_cases(rows: list[dict[str, Any]], threshold: float,
                high: bool, kind: str, predicted_display: Callable[[Any], str],
                actual_display: Callable[[Any], str]) -> list[dict[str, Any]]:
    cases = []
    for row in rows:
        conf = row.get("confidence")
        hit = row.get("hit")
        if conf is None or hit is None:
            continue
        if high and not (hit is False and conf >= threshold):
            continue
        if not high and not (hit is True and conf <= threshold):
            continue
        item = {
            **_record_base(row["record"]),
            "predicted": predicted_display(row.get("predicted")),
            "actual": actual_display(row.get("actual")),
            "confidence": conf,
            "actual_prob": row.get("actual_prob"),
            "hit": hit,
        }
        cases.append(item)
    cases.sort(key=lambda x: x["confidence"], reverse=high)
    return cases[:10]


def _analyze_market(
    records: list[dict[str, Any]],
    market_key: str,
    extractor: Callable[[dict[str, Any]], dict[str, Any] | None],
    *,
    bin_key: str | None = None,
    predicted_display: Callable[[Any], str] = _display_option,
    actual_display: Callable[[Any], str] = _display_option,
    labels_for_scores: list[str] | None = None,
    include_confusion: bool = False,
    include_rank: bool = False,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for record in records:
        item = extractor(record)
        if not item:
            continue
        confidence = item.get("confidence")
        hit = item.get("hit")
        if confidence is None or hit is None:
            continue
        rows.append({
            **item,
            "confidence": float(confidence),
            "hit": bool(hit),
            "record": record,
        })

    n = len(rows)
    hits = sum(1 for r in rows if r["hit"])
    confidences = [r["confidence"] for r in rows]
    actual_probs = [r["actual_prob"] for r in rows if r.get("actual_prob") is not None]
    edges = BIN_EDGES[bin_key or market_key]
    bins = _bins(rows, edges)
    nonempty = [b for b in bins if b["n"]]
    ece = (sum(b["n"] * abs((b["accuracy"] or 0) - (b["avg_pred"] or 0)) for b in nonempty) / n
           if n and nonempty else None)
    brier, log_loss = _multi_class_scores(rows, labels_for_scores or [])

    high_threshold = HIGH_CONF.get(bin_key or market_key, 0.6)
    low_threshold = LOW_CONF.get(bin_key or market_key, 0.4)
    return {
        "key": market_key,
        "label": MARKET_LABELS.get(market_key, market_key),
        "n": n,
        "hits": hits,
        "accuracy": (hits / n) if n else None,
        "avg_confidence": _mean(confidences),
        "avg_actual_prob": _mean(actual_probs),
        "ece": ece,
        "brier": brier,
        "log_loss": log_loss,
        "bins": bins,
        "actual_rank": _rank_counts(rows) if include_rank else None,
        "confusion": _confusion(rows) if include_confusion else None,
        "high_conf_threshold": high_threshold,
        "low_conf_threshold": low_threshold,
        "high_conf_wrong": _list_cases(
            rows, high_threshold, True, market_key, predicted_display, actual_display),
        "low_conf_hit": _list_cases(
            rows, low_threshold, False, market_key, predicted_display, actual_display),
    }


# --------------------------------------------------------------------------- #
# 各玩法提取器
# --------------------------------------------------------------------------- #
def _had_extractor(record: dict[str, Any]) -> dict[str, Any] | None:
    m = (record.get("prediction") or {}).get("markets", {}).get("HAD") or {}
    probs = m.get("probs") or {}
    predicted = m.get("predicted")
    actual = m.get("actual") or (record.get("result") or {}).get("had")
    if not predicted or predicted not in probs or m.get("hit") is None:
        return None
    return {
        "confidence": probs.get(predicted),
        "hit": m.get("hit"),
        "predicted": predicted,
        "actual": actual,
        "probs": probs,
        "actual_prob": probs.get(actual) if actual in probs else None,
    }


def _hhad_extractor(record: dict[str, Any]) -> dict[str, Any] | None:
    m = (record.get("prediction") or {}).get("markets", {}).get("HHAD") or {}
    probs = m.get("probs") or {}
    predicted = m.get("predicted")
    actual = m.get("actual") or (record.get("result") or {}).get("hhad")
    if not predicted or predicted not in probs or m.get("hit") is None:
        return None
    return {
        "confidence": probs.get(predicted),
        "hit": m.get("hit"),
        "predicted": predicted,
        "actual": actual,
        "probs": probs,
        "actual_prob": probs.get(actual) if actual in probs else None,
    }


def _ttg_extractor(record: dict[str, Any]) -> dict[str, Any] | None:
    m = (record.get("prediction") or {}).get("markets", {}).get("TOTAL_GOALS") or {}
    probs = m.get("probs") or {}
    predicted = m.get("predicted")
    actual = m.get("actual") or (record.get("result") or {}).get("total_goals")
    if not predicted or predicted not in probs or m.get("hit") is None:
        return None
    return {
        "confidence": probs.get(predicted),
        "hit": m.get("hit"),
        "predicted": predicted,
        "actual": actual,
        "probs": probs,
        "actual_prob": probs.get(actual) if actual in probs else None,
    }


def _half_full_extractor(record: dict[str, Any]) -> dict[str, Any] | None:
    m = (record.get("prediction") or {}).get("markets", {}).get("HALF_FULL") or {}
    top = m.get("top") or []
    predicted = m.get("predicted")
    actual = m.get("actual") or (record.get("result") or {}).get("half_full")
    if not predicted or not top or m.get("hit") is None:
        return None
    conf = next((float(x.get("prob")) for x in top if x.get("label") == predicted), None)
    if conf is None:
        conf = float(top[0].get("prob") or 0.0)
    actual_prob = next((float(x.get("prob")) for x in top if x.get("label") == actual), None)
    return {
        "confidence": conf,
        "hit": m.get("hit"),
        "predicted": predicted,
        "actual": actual,
        "probs": None,
        "actual_prob": actual_prob,
    }


def _score_extractor(record: dict[str, Any]) -> dict[str, Any] | None:
    m = (record.get("prediction") or {}).get("markets", {}).get("SCORE") or {}
    top = m.get("top") or []
    actual = m.get("actual") or (record.get("result") or {}).get("ft")
    scores = [str(x.get("score")) for x in top if x.get("score")]
    probs = [float(x.get("prob") or 0.0) for x in top if x.get("score")]
    if not scores or not actual:
        return None
    # 以实际比分是否落在三个预测比分中为准，不依赖上游缓存字段。
    hit = actual in scores
    # 三个比分是一个组合预测：组合概率 = 三个比分概率之和。
    confidence = min(1.0, sum(probs))
    actual_prob = None
    rank = None
    if actual in scores:
        idx = scores.index(actual)
        actual_prob = probs[idx]
        rank = idx + 1
    return {
        "confidence": confidence,
        "hit": bool(hit),
        "predicted": " / ".join(scores),
        "actual": actual,
        "probs": None,
        "actual_prob": actual_prob,
        "rank": rank,
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _score_hit_detail(records: list[dict[str, Any]]) -> dict[str, Any]:
    """比分 Top3 组合的补充分析。

    重点回答：三个比分里中了一个时，命中的那个比分本身被模型给了多少概率？
    """
    hits: list[dict[str, Any]] = []
    coverage = {1: 0, 2: 0, 3: 0}
    total = 0
    for record in records:
        m = (record.get("prediction") or {}).get("markets", {}).get("SCORE") or {}
        top = m.get("top") or []
        actual = m.get("actual") or (record.get("result") or {}).get("ft")
        scores = [str(x.get("score")) for x in top if x.get("score")]
        probs = [float(x.get("prob") or 0.0) for x in top if x.get("score")]
        if not scores or not actual:
            continue
        total += 1
        for k in (1, 2, 3):
            if actual in scores[:k]:
                coverage[k] += 1
        if actual not in scores:
            continue
        idx = scores.index(actual)
        p_actual = probs[idx]
        combo = min(1.0, sum(probs))
        item = {
            **_record_base(record),
            "top3": scores,
            "actual": actual,
            "p_actual": p_actual,
            "rank": idx + 1,
            "coverage": combo,
            "ratio": (p_actual / combo) if combo else None,
        }
        hits.append(item)

    actual_probs = [h["p_actual"] for h in hits]
    ratios = [h["ratio"] for h in hits if h["ratio"] is not None]
    prob_bins = []
    for lo, hi, label in (
        (0.0, 0.05, "<5%"),
        (0.05, 0.10, "5–10%"),
        (0.10, 0.15, "10–15%"),
        (0.15, 0.20, "15–20%"),
        (0.20, 1.01, "20%+"),
    ):
        subset = [h for h in hits if lo <= h["p_actual"] < hi]
        prob_bins.append({"label": label, "n": len(subset)})

    by_rank = []
    for rank in (1, 2, 3):
        subset = [h for h in hits if h["rank"] == rank]
        vals = [h["p_actual"] for h in subset]
        by_rank.append({
            "rank": rank,
            "n": len(subset),
            "avg_actual_prob": _mean(vals),
            "min_actual_prob": min(vals) if vals else None,
            "max_actual_prob": max(vals) if vals else None,
        })

    return {
        "n": len(hits),
        "avg_actual_prob": _mean(actual_probs),
        "median_actual_prob": _median(actual_probs),
        "min_actual_prob": min(actual_probs) if actual_probs else None,
        "max_actual_prob": max(actual_probs) if actual_probs else None,
        "prob_bins": prob_bins,
        "by_rank": by_rank,
        "ratio": {
            "avg": _mean(ratios),
            "min": min(ratios) if ratios else None,
            "max": max(ratios) if ratios else None,
        },
        "coverage": {
            "total": total,
            "top1": coverage[1],
            "top2": coverage[2],
            "top3": coverage[3],
        },
        "cases": sorted(hits, key=lambda x: (str(x.get("date") or ""),
                                             str(x.get("match_num") or ""))),
    }


# --------------------------------------------------------------------------- #
# 价值注 / 联赛 / 每日
# --------------------------------------------------------------------------- #
def _value_stats(bets: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(bets)
    hits = sum(1 for b in bets if b.get("hit"))
    pnl = sum(float(b.get("pnl_unit") or 0.0) for b in bets)
    return {
        "n": n,
        "hits": hits,
        "hit_rate": (hits / n) if n else None,
        "pnl_unit": pnl,
        "roi": (pnl / n) if n else None,
    }


def _value_analysis(records: list[dict[str, Any]]) -> dict[str, Any]:
    bets = []
    for record in records:
        for bet in (record.get("prediction") or {}).get("value_bets", []):
            if bet.get("hit") is None:
                continue
            bets.append({
                **bet,
                "date": record.get("date"),
                "match_num": record.get("match_num"),
                "home": (record.get("home") or {}).get("cn"),
                "away": (record.get("away") or {}).get("cn"),
            })

    def grouped(edges: list[tuple[float, float, str]],
                value: Callable[[dict[str, Any]], float | None]) -> list[dict[str, Any]]:
        out = []
        for lo, hi, label in edges:
            subset = [b for b in bets if value(b) is not None and lo <= float(value(b)) < hi]
            out.append({"label": label, **_value_stats(subset)})
        return out

    return {
        **_value_stats(bets),
        "by_edge": grouped(
            [(0.0, 0.05, "<5%"), (0.05, 0.10, "5–10%"),
             (0.10, 0.15, "10–15%"), (0.15, 10.0, "15%+")],
            lambda b: b.get("edge")),
        "by_odds": grouped(
            [(1.0, 2.0, "<2.0"), (2.0, 3.0, "2.0–3.0"),
             (3.0, 4.0, "3.0–4.0"), (4.0, 100.0, "4.0+")],
            lambda b: b.get("odds")),
    }


def _by_league(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        div = (record.get("league") or {}).get("div") or "OTHER"
        groups[div].append(record)
    out = []
    for div, recs in groups.items():
        market = _analyze_market(recs, "HAD", _had_extractor,
                                 labels_for_scores=["home", "draw", "away"])
        out.append({
            "div": div,
            "name": (recs[0].get("league") or {}).get("name") or div,
            "n": market["n"],
            "hits": market["hits"],
            "accuracy": market["accuracy"],
            "avg_confidence": market["avg_confidence"],
        })
    out.sort(key=lambda x: (-x["n"], x["name"] or ""))
    return [x for x in out if x["n"] > 0]


def _daily(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[str(record.get("date") or "")].append(record)
    out = []
    for date, recs in groups.items():
        market = _analyze_market(recs, "HAD", _had_extractor,
                                 labels_for_scores=["home", "draw", "away"])
        value = _value_analysis(recs)
        out.append({
            "date": date,
            "n": market["n"],
            "hits": market["hits"],
            "accuracy": market["accuracy"],
            "avg_confidence": market["avg_confidence"],
            "value_n": value["n"],
            "value_hits": value["hits"],
            "value_roi": value["roi"],
        })
    return sorted(out, key=lambda x: x["date"])


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #
def analyze_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    valid = _settled(records)
    markets = {
        "HAD": _analyze_market(valid, "HAD", _had_extractor,
                               labels_for_scores=["home", "draw", "away"],
                               include_confusion=True, include_rank=True),
        "HHAD": _analyze_market(valid, "HHAD", _hhad_extractor,
                                labels_for_scores=["home", "draw", "away"],
                                include_confusion=True, include_rank=True),
        "SCORE": _analyze_market(valid, "SCORE", _score_extractor),
        "TOTAL_GOALS": _analyze_market(
            valid, "TOTAL_GOALS", _ttg_extractor, include_rank=True,
            labels_for_scores=["0", "1", "2", "3", "4", "5", "6", "7+"]),
        "HALF_FULL": _analyze_market(valid, "HALF_FULL", _half_full_extractor),
    }
    markets["SCORE"]["hit_detail"] = _score_hit_detail(valid)

    layers: dict[str, Any] = {}
    for name in ("DC", "Elo", "ML"):
        def extractor(record: dict[str, Any], layer_name: str = name) -> dict[str, Any] | None:
            layer = ((record.get("prediction") or {}).get("model_layers") or {}).get(layer_name)
            if not layer:
                return None
            probs = layer.get("probs") or {}
            predicted = layer.get("predicted")
            actual = (record.get("result") or {}).get("had")
            if not predicted or predicted not in probs or layer.get("hit") is None:
                return None
            return {
                "confidence": probs.get(predicted),
                "hit": layer.get("hit"),
                "predicted": predicted,
                "actual": actual,
                "probs": probs,
                "actual_prob": probs.get(actual) if actual in probs else None,
            }
        layers[name] = _analyze_market(
            valid, "LAYER", extractor,
            bin_key="LAYER", labels_for_scores=["home", "draw", "away"])
        layers[name]["label"] = name

    return {
        "sample": {
            "pre_match_settled": len(valid),
            "dates": len({r.get("date") for r in valid}),
            "total_history": len(records),
            "excluded_post_kickoff": sum(
                1 for r in records
                if r.get("status") == "settled"
                and r.get("prediction_timing") != "pre_match"),
        },
        "markets": markets,
        "layers": layers,
        "value": _value_analysis(valid),
        "by_league": _by_league(valid),
        "daily": _daily(valid),
        "note": (
            "只统计赛前预测且已结算的场次。样本量较小时，概率区间结论仅作探索，"
            "不要据此优化阈值或重仓。"
        ),
    }
