"""候选筛选（纸面）：从预测结果中筛选、分级、分配仓位，产出可执行清单。

定位：**风险筛选 / 纸面跟踪**，不是「稳赚推荐」。历史回测 ROI 为负，
本模块帮你「少下、下得明白」，不构成盈利建议。

原则（对抗「准确率错觉」）：
    1. 默认只筛**胜平负（HAD）单关**；让球（HHAD）历史无赔率、未验证，只「观察」。
    2. 默认只筛**历史唯一微正的 E0 英超**；其余只「观察」。
    3. 单注 1/4 Kelly 上限 + 日总仓位上限，超出按比例缩。
    4. 候选注默认记为「纸面注」，用 reconcile 长期验证后再谈真钱。

数据来源：predict_matches 的输出 rows（含 value_bets）。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import get_settings
from src.jingcai import payouts as pay

TIER_LABEL = {3: "★★★ 高信心", 2: "★★ 中等", 1: "★ 观察"}

LOG_COLS = [
    "date", "match_num", "league", "div", "home_cn", "away_cn",
    "market", "option", "odds", "model_prob", "implied_prob", "edge",
    "ev", "stake_pct", "tier",
]


# --------------------------------------------------------------------------- #
# 过滤分级
# --------------------------------------------------------------------------- #
def _reason(item: dict[str, Any], reliable: set[str], cfg: dict[str, Any]) -> str:
    div = item["div"]
    if div not in reliable:
        return f"联赛 {div} 回测未明显超基准，仅观察"
    if not (float(cfg["min_odds"]) <= item["odds"] <= float(cfg["max_odds"])):
        return f"赔率 {item['odds']:.2f} 超出推荐区间，仅观察"
    p = item["model_prob"]
    if not (float(cfg["min_model_prob"]) <= p <= float(cfg["max_model_prob"])):
        return f"模型概率 {p:.0%} 超出区间，仅观察"
    if item["ev"] < 0.05:
        return f"EV 仅 {item['ev']:+.1%}，期望收益太低，仅观察"
    return (f"模型 {p:.0%} / 市场 {item['implied_prob']:.0%} → "
            f"edge +{item['edge']:.1%}，EV +{item['ev']:.1%}")


def classify(rows: list[dict[str, Any]],
             cfg: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """把 value_bets 过滤分级，返回 (可推荐候选, 观察)。"""
    min_edge = float(cfg["min_edge"])
    reliable = set(cfg.get("reliable_leagues", []))
    allowed_markets = set(cfg.get("markets", ["HAD", "HHAD"]))
    recs: list[dict[str, Any]] = []
    obs: list[dict[str, Any]] = []

    for r in rows:
        if r.get("skipped"):
            continue
        for b in r.get("value_bets", []):
            edge = float(b.get("edge", 0.0))
            if edge < min_edge:
                continue  # 低于该风险档位阈值，连观察都不列
            item = {
                "match_num": r.get("match_num", ""),
                "league": r.get("league", ""),
                "div": r.get("div", ""),
                "home_cn": r.get("home_cn", ""),
                "away_cn": r.get("away_cn", ""),
                "market": b.get("market", ""),
                "option": b.get("option", ""),
                "odds": float(b.get("odds", 0.0)),
                "model_prob": float(b.get("model_prob", 0.0)),
                "implied_prob": float(b.get("implied_prob", 0.0)),
                "edge": edge,
                "ev": float(b.get("ev", 0.0)),
            }
            # 玩法不在允许范围（默认只 HAD）-> 观察
            if item["market"] not in allowed_markets:
                item["tier"] = 1
                item["reason"] = (f"玩法 {item['market']} 未纳入候选（仅 "
                                  f"{'/'.join(sorted(allowed_markets))}），仅观察")
                obs.append(item)
                continue
            qualify = (
                item["div"] in reliable
                and float(cfg["min_odds"]) <= item["odds"] <= float(cfg["max_odds"])
                and float(cfg["min_model_prob"]) <= item["model_prob"] <= float(cfg["max_model_prob"])
                and item["ev"] >= 0.05  # 期望收益下限：EV 太低不值得占用仓位
            )
            if qualify:
                item["tier"] = 3 if item["ev"] >= 0.10 else 2
                item["reason"] = _reason(item, reliable, cfg)
                recs.append(item)
            else:
                item["tier"] = 1
                item["reason"] = _reason(item, reliable, cfg)
                obs.append(item)

    recs.sort(key=lambda x: (-x["ev"], -x["edge"]))
    obs.sort(key=lambda x: -x["edge"])
    return recs, obs


# --------------------------------------------------------------------------- #
# 仓位
# --------------------------------------------------------------------------- #
def allocate_stakes(recs: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """单注 1/4 Kelly 上限 + 日总仓位上限（超出按比例缩）。"""
    single_cap = float(cfg["single_stake_pct"])
    daily_cap = float(cfg["daily_stake_pct"])
    max_bets = int(cfg.get("max_bets", 5))

    recs = recs[:max_bets]
    for it in recs:
        it["stake_pct"] = pay.kelly_stake(
            it["edge"], it["odds"], it["model_prob"],
            kelly_fraction=0.25, max_stake_pct=single_cap)
    total = sum(it["stake_pct"] for it in recs)
    if total > daily_cap and total > 0:
        scale = daily_cap / total
        for it in recs:
            it["stake_pct"] *= scale
    return recs


# --------------------------------------------------------------------------- #
# 编排
# --------------------------------------------------------------------------- #
def run_recommend(rows: list[dict[str, Any]], cfg: dict[str, Any],
                  bankroll: float | None = None) -> dict[str, Any]:
    recs, obs = classify(rows, cfg)
    recs = allocate_stakes(recs, cfg)
    if bankroll:
        for it in recs:
            it["stake_amount"] = round(bankroll * it["stake_pct"], 2)
    total_pct = sum(it["stake_pct"] for it in recs)
    return {
        "recommendations": recs,
        "observations": obs,
        "total_stake_pct": total_pct,
        "risk": cfg.get("risk", "conservative"),
        "bankroll": bankroll,
    }


# --------------------------------------------------------------------------- #
# 报告 / 日志
# --------------------------------------------------------------------------- #
def _fmt(v: Any, nd: int = 3) -> str:
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return "-"


def write_report(result: dict[str, Any],
                 path_base: Path | None = None) -> tuple[Path, Path]:
    settings = get_settings()
    settings.ensure_dirs()
    ts = datetime.now().strftime("%Y%m%d")
    base = path_base or (settings.reports_dir / f"recommend_{ts}")
    md_path = base.with_suffix(".md")
    json_path = base.with_suffix(".json")
    md_path.parent.mkdir(parents=True, exist_ok=True)

    recs = result["recommendations"]
    obs = result["observations"]
    risk = result["risk"]
    bankroll = result.get("bankroll")

    lines = [
        f"# 候选筛选（纸面） {datetime.now().isoformat(timespec='seconds')}",
        "",
        "> ⚠️ **本清单是风险筛选，不构成盈利建议。** 历史回测 ROI 为负（−3%~−9%），",
        "> 默认只筛选 E0 英超的胜平负（历史唯一微正），且仅为「纸面跟踪」用途。",
        "> 请先用 `reconcile` 长期验证，勿据此重仓真钱。",
        "",
        f"- 风险档位：{risk}",
        f"- 候选注数：{len(recs)}，合计仓位 {result['total_stake_pct'] * 100:.2f}%"
        + (f"（¥{bankroll * result['total_stake_pct']:.0f} / 本金 ¥{bankroll:.0f}）"
           if bankroll else ""),
        "",
    ]
    if not bankroll:
        lines.append("> 未指定 `--bankroll`，仅显示仓位百分比（纸面，不涉及金额）。")
        lines.append("")

    if recs:
        lines += ["## 候选清单", "",
                  "| 级别 | 编号 | 联赛 | 对阵 | 玩法 | 选项 | 赔率 | 模型概率 | edge | EV | 仓位 |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for it in recs:
            stake_txt = f"{it['stake_pct'] * 100:.2f}%"
            if bankroll:
                stake_txt += f"（¥{it.get('stake_amount', 0):.0f}）"
            lines.append(
                f"| {TIER_LABEL[it['tier']]} | {it['match_num']} | {it['league']} "
                f"| {it['home_cn']} vs {it['away_cn']} | {it['market']} | {it['option']} "
                f"| {_fmt(it['odds'], 2)} | {_fmt(it['model_prob'])} "
                f"| {_fmt(it['edge'])} | {_fmt(it['ev'])} | {stake_txt} |"
            )
        lines += ["", "## 候选理由", ""]
        for it in recs:
            lines.append(
                f"- **{it['match_num']} {it['league']} {it['home_cn']} vs {it['away_cn']}** "
                f"{it['market']}「{it['option']}」：{it['reason']}")
        lines.append("")
    else:
        lines += ["## 候选清单", "",
                  "（今日无可纳入候选的注——未发现满足条件的 E0 胜平负价值机会）", ""]

    if obs:
        lines += ["## 观察（不下注）", "",
                  "| 编号 | 联赛 | 对阵 | 玩法 | 选项 | 赔率 | edge | 原因 |",
                  "|---|---|---|---|---|---|---|---|"]
        for it in obs:
            lines.append(
                f"| {it['match_num']} | {it['league']} | {it['home_cn']} vs {it['away_cn']} "
                f"| {it['market']} | {it['option']} | {_fmt(it['odds'], 2)} "
                f"| {_fmt(it['edge'])} | {it['reason']} |")
        lines.append("")

    # 过关参考（不推荐）
    if len(recs) >= 2:
        comb_odds = 1.0
        comb_prob = 1.0
        for it in recs[:2]:
            comb_odds *= it["odds"]
            comb_prob *= it["model_prob"]
        disc = pay.parlay_probabilities([it["model_prob"] for it in recs[:2]])
        ev = comb_prob * comb_odds - 1.0
        lines += ["## 过关参考（⚠️ 不推荐，抽水叠加）", "",
                  f"- 前 2 注组合赔率 {comb_odds:.2f}，模型概率 {comb_prob:.1%}，"
                  f"相关性折扣后 {disc:.1%}，EV {ev:+.1%}",
                  "- 竞彩过关每场叠加 ~27% 抽水，长期期望显著低于单关，仅作参考。",
                  ""]

    md_path.write_text("\n".join(lines), encoding="utf-8")
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "risk": risk,
        "bankroll": bankroll,
        "total_stake_pct": result["total_stake_pct"],
        "recommendations": result["recommendations"],
        "observations": result["observations"],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1,
                                    default=str), encoding="utf-8")
    return md_path, json_path


def log_recommendations(recs: list[dict[str, Any]],
                        path: Path | None = None) -> Path:
    """追加推荐到 data/processed/recommendations.parquet（纸面跟踪，按主键去重）。"""
    settings = get_settings()
    path = path or (settings.processed_dir / "recommendations.parquet")
    today = datetime.now().strftime("%Y-%m-%d")
    rows = [{**it, "date": today} for it in recs]
    new = pd.DataFrame(rows, columns=LOG_COLS)
    if new.empty:
        return path
    if path.exists():
        old = pd.read_parquet(path)
        key = ["date", "match_num", "market", "option"]
        if all(c in old.columns for c in key):
            old_key = old[key].astype(str).agg("|".join, axis=1)
            new_key = new[key].astype(str).agg("|".join, axis=1)
            new = new[~new_key.isin(set(old_key))]
        merged = pd.concat([old, new], ignore_index=True)
    else:
        merged = new
    merged.to_parquet(path, index=False)
    return path
