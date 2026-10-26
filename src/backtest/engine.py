"""Walk-forward 回测引擎。

流程
----
对每个联赛按时间顺序滚动：
    1. 用「当前时点之前」的数据拟合 Dixon-Coles（可限定滚动窗口年限）
    2. 预测紧接着的 refit_interval 场，记录概率 / 实际结果 / 赔率
    3. 前进一个 block，重新拟合

关键原则：**任何一场比赛的预测都只用它之前的数据**，杜绝未来信息泄漏。

若数据带收盘赔率列（odds_home/draw/away），则额外产出模拟投注 ROI。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from src.backtest import metrics as M
from src.config import get_leagues, get_settings
from src.models import dixon_coles as dc

ODDS_COLS = ("odds_home", "odds_draw", "odds_away")


@dataclass
class BacktestConfig:
    leagues: list[str] | None = None
    years: int | None = 5          # 训练窗口回溯年数；None 表示用全部历史
    min_train_size: int = 380
    refit_interval: int = 50
    half_life: float = 180.0
    shrinkage_prior: float = 0.0   # 小样本收缩先验（场数），0=不收缩
    ev_threshold: float = 0.0
    max_test: int | None = None    # 每联赛最多回测场次（调试用）
    start_year: int | None = None  # 只回测该年及以后的比赛（训练仍用其之前的历史）
    end_year: int | None = None    # 只回测该年及以前的比赛


def _clean_odds(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return float("nan")
    return f


def walk_forward(sub: pd.DataFrame, cfg: BacktestConfig) -> list[dict[str, Any]]:
    """对单个联赛做 walk-forward，返回逐场预测记录。"""
    sub = sub.dropna(subset=["home_team", "away_team", "ft_home", "ft_away",
                             "date"]).sort_values("date").reset_index(drop=True)
    n = len(sub)
    rows: list[dict[str, Any]] = []
    if n <= cfg.min_train_size:
        return rows

    has_odds = all(c in sub.columns for c in ODDS_COLS)

    # 确定回测起点：既不小于 min_train_size，也不早于 start_year
    start = cfg.min_train_size
    if cfg.start_year is not None:
        after = sub.index[sub["date"] >= pd.Timestamp(f"{cfg.start_year}-01-01")]
        if len(after):
            start = max(start, int(after[0]))
    end_ts = (pd.Timestamp(f"{cfg.end_year}-12-31")
              if cfg.end_year is not None else None)

    while start < n:
        block = sub.iloc[start:start + cfg.refit_interval]
        if block.empty:
            break
        cut = block["date"].iloc[0]
        if end_ts is not None and cut > end_ts:
            break
        train = sub.iloc[:start]
        if cfg.years:
            train = train[train["date"] >= cut - pd.Timedelta(days=365 * cfg.years)]
        if len(train) < 100:
            start += cfg.refit_interval
            continue

        try:
            model = dc.fit(train, half_life_days=cfg.half_life,
                           shrinkage_prior=cfg.shrinkage_prior)
        except Exception:  # noqa: BLE001
            start += cfg.refit_interval
            continue

        for r in block.itertuples(index=False):
            p = dc.predict_proba(model, r.home_team, r.away_team)
            row: dict[str, Any] = {
                "div": getattr(r, "league_code", ""),
                "date": pd.Timestamp(r.date).date().isoformat(),
                "home_team": r.home_team,
                "away_team": r.away_team,
                "p_home": p["prob_home"],
                "p_draw": p["prob_draw"],
                "p_away": p["prob_away"],
                "actual": M.result_label(r.ft_home, r.ft_away),
            }
            if has_odds:
                row["odds_home"] = _clean_odds(getattr(r, "odds_home"))
                row["odds_draw"] = _clean_odds(getattr(r, "odds_draw"))
                row["odds_away"] = _clean_odds(getattr(r, "odds_away"))
            rows.append(row)

        start += cfg.refit_interval
        if cfg.max_test and len(rows) >= cfg.max_test:
            break
    return rows


def run_backtest(df: pd.DataFrame, cfg: BacktestConfig) -> dict[str, Any]:
    """对多个联赛跑回测，返回汇总结果。

    ``cfg.leagues`` 里若含模型组键（如 EUR），按其成员联赛合并数据
    做**单次** walk-forward（即合并模型的回测）。
    """
    leagues = cfg.leagues or sorted(df["league_code"].dropna().unique())
    lg = get_leagues()
    per_rows: dict[str, list[dict[str, Any]]] = {}
    per_metrics: dict[str, dict[str, Any]] = {}
    all_rows: list[dict[str, Any]] = []

    for div in leagues:
        sub = df[df["league_code"].isin(lg.model_members(div))]
        rows = walk_forward(sub, cfg)
        if not rows:
            continue
        per_rows[div] = rows
        per_metrics[div] = M.evaluate(rows, ev_threshold=cfg.ev_threshold)
        all_rows.extend(rows)

    return {
        "config": cfg,
        "per_league": per_metrics,
        "per_league_rows": per_rows,
        "overall": M.evaluate(all_rows, ev_threshold=cfg.ev_threshold),
        "rows": all_rows,
    }


# --------------------------------------------------------------------------- #
# 报告
# --------------------------------------------------------------------------- #
def _f(v: Any, nd: int = 4) -> str:
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return "-"


def write_backtest_report(result: dict[str, Any],
                          path_base: Path | None = None) -> tuple[Path, Path]:
    """双写 Markdown + JSON 回测报告。"""
    import json

    settings = get_settings()
    settings.ensure_dirs()
    cfg: BacktestConfig = result["config"]
    ts = datetime.now().strftime("%Y%m%d")
    tag = "-".join(cfg.leagues) if cfg.leagues else "all"
    base = (Path(path_base) if path_base
            else settings.reports_dir / f"backtest_{tag}_{ts}")
    md_path = base.with_suffix(".md")
    json_path = base.with_suffix(".json")
    md_path.parent.mkdir(parents=True, exist_ok=True)

    leagues = get_leagues()
    overall = result["overall"]

    lines: list[str] = [
        f"# Walk-forward 回测报告 {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## 配置",
        "",
        f"- 训练窗口：{cfg.years if cfg.years else '全部历史'} 年",
        f"- 回测区间：{cfg.start_year or '起始'} – {cfg.end_year or '最新'} 年",
        f"- 最小训练集：{cfg.min_train_size} 场",
        f"- 重拟合间隔：{cfg.refit_interval} 场",
        f"- 半衰期：{cfg.half_life} 天",
        f"- 小样本收缩先验：{cfg.shrinkage_prior} 场",
        f"- EV 阈值：{cfg.ev_threshold}",
        f"- 是否含赔率：{'是' if overall['has_odds'] else '否'}",
        "",
        "## 总体指标",
        "",
        "| 指标 | 数值 |",
        "|---|---|",
        f"| 样本场次 | {overall['n']} |",
        f"| 准确率 | {_f(overall['accuracy'],4)} |",
        f"| 基准(全主胜) | {_f(overall['baseline_home'],4)} |",
        f"| 对数损失 | {_f(overall['log_loss'],4)} |",
        f"| Brier | {_f(overall['brier'],4)} |",
        f"| ECE(校准误差) | {_f(overall.get('ece'),4)} |",
    ]
    if overall["has_odds"]:
        b = overall["betting"]
        lines += [
            f"| 下注数 | {b['n_bets']} |",
            f"| 总投入 | {_f(b['staked'],1)} |",
            f"| 净收益 | {_f(b['profit'],1)} |",
            f"| ROI | {_f(b['roi'],4)} |",
            f"| 命中率 | {_f(b['hit_rate'],4)} |",
            f"| 最大回撤 | {_f(b['max_drawdown'],1)} |",
        ]

    lines += ["", "## 分联赛", "",
              "| 联赛 | 场次 | 准确率 | 基准 | 对数损失 | Brier | ROI |",
              "|---|---|---|---|---|---|---|"]
    for div, m in sorted(result["per_league"].items()):
        roi = "-"
        if m["has_odds"]:
            roi = _f(m["betting"]["roi"], 4)
        lines.append(
            f"| {div}({leagues.name_of(div)}) | {m['n']} | {_f(m['accuracy'],4)} "
            f"| {_f(m['baseline_home'],4)} | {_f(m['log_loss'],4)} "
            f"| {_f(m['brier'],4)} | {roi} |"
        )

    lines += ["", "## 校准表（最高概率分箱）", "",
              "| 预测概率区间 | 样本 | 平均预测 | 实际命中 |",
              "|---|---|---|---|"]
    for c in overall["calibration"]:
        lines.append(f"| [{_f(c['lo'],1)}, {_f(c['hi'],1)}) | {c['n']} "
                     f"| {_f(c['pred_mean'],3)} | {_f(c['emp_freq'],3)} |")

    lines += ["", "> 说明：对数损失 < 1.0986 优于随机；Brier < 0.667 优于随机；",
              "> ECE 越接近 0 校准越好（模型过度自信时 ECE 偏高）。",
              "> ROI 仅在含收盘赔率时给出，且为**含水位**的真实可下注口径。"]

    md_path.write_text("\n".join(lines), encoding="utf-8")

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config": {
            "leagues": cfg.leagues, "years": cfg.years,
            "min_train_size": cfg.min_train_size,
            "refit_interval": cfg.refit_interval,
            "half_life": cfg.half_life, "ev_threshold": cfg.ev_threshold,
            "shrinkage_prior": cfg.shrinkage_prior,
            "start_year": cfg.start_year, "end_year": cfg.end_year,
        },
        "overall": overall,
        "per_league": result["per_league"],
        "predictions": result["rows"],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1,
                                    default=str), encoding="utf-8")
    return md_path, json_path
