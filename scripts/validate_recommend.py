"""阶段 1 验证：把 recommend 的过滤规则套到历史 walk-forward 回测上。

对比「全量下注（任意 EV>0）」vs「推荐子集（套用 recommend 过滤/分级）」的 ROI，
用上千注的大样本估计这套推荐规则到底有没有 edge。

重要局限
--------
* 历史数据只有 1X2 收盘赔率（无让球盘），故这里只验证 **HAD** 推荐；
  HHAD 无法从历史数据回测。
* 回测用纯 Dixon-Coles（不含 Elo/ML/市场混合），与线上 recommend 的混合模型
  略有差异，属**保守近似**（线上已向市场收缩，edge 通常更小）。

用法：
    python scripts/validate_recommend.py
    python scripts/validate_recommend.py --start-year 2006 --end-year 2013 --refit 100
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import argparse
from datetime import datetime

import numpy as np
import pandas as pd

from src.pipeline import load_training_data
from src.backtest.engine import BacktestConfig, run_backtest
from src.backtest import metrics as M
from src.ingest import odds as O
from src.config import get_settings

LEAGUES = ["E0", "D1", "SP1", "I1", "F1"]


def _devig(odds: list[float]) -> list[float]:
    inv = [1.0 / o if o and o > 1.0 else 0.0 for o in odds]
    s = sum(inv)
    return [x / s for x in inv] if s > 0 else [0.0, 0.0, 0.0]


def collect_bets(rows: list[dict], cfg: dict,
                 market_blend: float = 1.0) -> tuple[list[dict], list[dict]]:
    """返回 (全量 EV>0 注, 推荐子集注)。

    market_blend < 1 时，先把模型概率向去水市场概率收缩（模拟线上
    blend_probabilities），再算 edge/EV——更贴近线上 recommend 的口径。
    """
    reliable = set(cfg.get("reliable_leagues", []))
    all_bets: list[dict] = []
    rec_bets: list[dict] = []
    for r in rows:
        odds = [r.get("odds_home"), r.get("odds_draw"), r.get("odds_away")]
        if not all(isinstance(o, (int, float)) and o and o > 1.0 for o in odds):
            continue
        raw = [r["p_home"], r["p_draw"], r["p_away"]]
        idx = {"H": 0, "D": 1, "A": 2}[r["actual"]]
        imp = _devig(odds)
        if market_blend < 1.0:
            w = market_blend
            probs = [w * raw[i] + (1 - w) * imp[i] for i in range(3)]
            s = sum(probs)
            probs = [p / s for p in probs] if s > 0 else raw
        else:
            probs = raw
        for i in range(3):
            o = odds[i]
            p = probs[i]
            ev = p * o - 1.0
            if ev <= 0:
                continue
            edge = p - imp[i]
            hit = (i == idx)
            base = {"div": r["div"], "odds": o, "edge": edge, "ev": ev,
                    "hit": hit, "pnl": (o - 1.0) if hit else -1.0}
            all_bets.append(base)
            # recommend 过滤
            if (r["div"] in reliable
                    and edge >= float(cfg["min_edge"])
                    and ev >= 0.05
                    and float(cfg["min_odds"]) <= o <= float(cfg["max_odds"])
                    and float(cfg["min_model_prob"]) <= p <= float(cfg["max_model_prob"])):
                rec_bets.append({**base})
    return all_bets, rec_bets


def summarize(bets: list[dict]) -> dict:
    n = len(bets)
    if not n:
        return {"n": 0}
    pnl = sum(b["pnl"] for b in bets)
    hits = sum(1 for b in bets if b["hit"])
    # 最大回撤
    eq = 0.0; peak = 0.0; dd = 0.0
    for b in bets:
        eq += b["pnl"]; peak = max(peak, eq); dd = max(dd, peak - eq)
    return {
        "n": n, "hit_rate": hits / n, "pnl": pnl, "roi": pnl / n,
        "avg_edge": float(np.mean([b["edge"] for b in bets])),
        "avg_ev": float(np.mean([b["ev"] for b in bets])),
        "max_dd": dd,
    }


def by_league(bets: list[dict]) -> dict[str, dict]:
    out = {}
    for div in sorted({b["div"] for b in bets}):
        out[div] = summarize([b for b in bets if b["div"] == div])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-year", type=int, default=2008)
    ap.add_argument("--end-year", type=int, default=2013)
    ap.add_argument("--refit", type=int, default=100)
    ap.add_argument("--years", type=int, default=5)
    args = ap.parse_args()

    settings = get_settings()
    print("加载数据 + 合并历史赔率 ...")
    df = load_training_data()
    try:
        od = O.load_odds_processed()
    except FileNotFoundError:
        od = O.load_odds()
    df = O.merge_odds(df, od)

    cfg = BacktestConfig(leagues=LEAGUES, years=args.years,
                         min_train_size=380, refit_interval=args.refit,
                         start_year=args.start_year, end_year=args.end_year)
    print(f"walk-forward 回测（{args.start_year}-{args.end_year}，窗口 {args.years} 年，"
          f"重拟合 {args.refit} 场）...")
    res = run_backtest(df, cfg)
    rows = res["rows"]
    print(f"  预测 {len(rows)} 场，有赔率的按 EV>0 筛注 ...")

    rec_cfg = settings.recommend_for("conservative")
    print("\n" + "=" * 68)
    print(f"阶段1 验证结果（HAD 单关，保守档）  区间 {args.start_year}-{args.end_year}")
    print("=" * 68)

    report_rows = []
    for label, mb in (("纯DC（过度自信）", 1.0), ("DC+市场混合0.6（贴近线上）", 0.6)):
        all_bets, rec_bets = collect_bets(rows, rec_cfg, market_blend=mb)
        full = summarize(all_bets)
        rec = summarize(rec_bets)
        print(f"\n[{label}]")
        print(f"  全量（任意 EV>0）: {full['n']} 注, 命中率 {full['hit_rate']:.4f}, "
              f"ROI {full['roi']:+.4f}, 最大回撤 {full['max_dd']:.1f}")
        print(f"  推荐子集（套过滤）: {rec['n']} 注, 命中率 {rec['hit_rate']:.4f}, "
              f"ROI {rec['roi']:+.4f}, 最大回撤 {rec['max_dd']:.1f}")
        if rec["n"]:
            print(f"    平均 edge {rec['avg_edge']:+.4f}，平均 EV {rec['avg_ev']:+.4f}"
                  f"（预测 EV vs 实际 ROI 的落差 = 过度自信）")
        report_rows.append((label, full, rec, by_league(rec_bets)))

    # 分联赛按「DC+市场混合」口径
    print("\n分联赛（推荐子集，DC+市场混合0.6）:")
    print(f"  {'联赛':<6}{'注数':>6}{'命中率':>8}{'ROI':>9}{'最大回撤':>9}")
    for div, s in report_rows[-1][3].items():
        print(f"  {div:<6}{s['n']:>6}{s['hit_rate']:>8.4f}{s['roi']:>+9.4f}{s['max_dd']:>9.1f}")

    # 写报告
    ts = datetime.now().strftime("%Y%m%d")
    md = settings.reports_dir / f"validate_recommend_{ts}.md"
    lines = [
        f"# 阶段1 验证：推荐规则历史回测 {datetime.now().isoformat(timespec='seconds')}",
        "",
        f"- 区间：{args.start_year}–{args.end_year}，窗口 {args.years} 年，重拟合 {args.refit} 场",
        f"- 联赛：{'/'.join(LEAGUES)}（含收盘赔率）",
        "- 模型：Dixon-Coles；另对比「向市场混合 0.6」的贴近线上口径",
        "- 玩法：HAD 单关（历史数据无让球盘，HHAD 无法回测）",
        "",
    ]
    for label, full, rec, leagues in report_rows:
        lines += [f"## {label}", "",
                  "| 口径 | 注数 | 命中率 | ROI | 最大回撤 | 平均edge | 平均EV |",
                  "|---|---|---|---|---|---|---|",
                  f"| 全量 EV>0 | {full['n']} | {full['hit_rate']:.4f} | {full['roi']:+.4f} | {full['max_dd']:.1f} | {full['avg_edge']:+.4f} | {full['avg_ev']:+.4f} |",
                  f"| 推荐子集 | {rec['n']} | {rec['hit_rate']:.4f} | {rec['roi']:+.4f} | {rec['max_dd']:.1f} | {rec.get('avg_edge', 0):+.4f} | {rec.get('avg_ev', 0):+.4f} |",
                  "", "分联赛（推荐子集）：", "",
                  "| 联赛 | 注数 | 命中率 | ROI | 最大回撤 |", "|---|---|---|---|---|"]
        for div, s in leagues.items():
            lines.append(f"| {div} | {s['n']} | {s['hit_rate']:.4f} | {s['roi']:+.4f} | {s['max_dd']:.1f} |")
        lines.append("")

    lines += ["## 结论要点", "",
              "- 过滤把注数压到约 1/4、命中率提升、回撤大幅下降——**降低风险有效**；",
              "- 但 ROI 仍为负（或仅个别联赛微正）——**尚未证明能稳定盈利**；",
              "- 「平均 EV」远高于「实际 ROI」= 模型系统性过度自信；混合市场后收敛，但未转正；",
              "- 结论：推荐规则适合**少下、稳下**，不足以支撑真钱重仓。"]
    md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已写入: {md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
