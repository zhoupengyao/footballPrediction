"""对账：把预测报告与实际比分比对，产出命中率/对数损失/模拟盈亏，并写入投注台账。

解决的问题（docs/daily_workflow.md 第 8 节）：此前无 `reconcile` 命令，
命中率与 ROI 只能手动统计。本模块补上自动化对账：

    1. 读取 reports/predict_YYYYMMDD.json（仅非 skip 场次）
    2. 从本地历史数据（tier1 / understat / 欧冠 / 欧罗巴 / 欧协联）查实际比分
    3. 逐场比对：HAD 命中、最可能比分、价值选项的盈亏
    4. 输出 reports/reconcile_YYYYMMDD.{md,json}，并把价值选项追加到
       data/processed/bet_ledger.parquet（长期 ROI / CLV 的唯一数据源）

赛果来源为本地 parquet；若赛果尚未落盘（如最新一轮还没 fetch），
对应场次会被标记为「无赛果（待补）」，可配合 `--manual scores.csv` 手动补录。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.config import get_settings
from src.jingcai.team_names import _norm

HAD_KEYS = ["胜", "平", "负"]
_LABEL_TO_RESULT = {"胜": "H", "平": "D", "负": "A"}

# 结果来源：processed 数据集名 -> 是否需要用 understat 队名归一化
RESULT_SOURCES: dict[str, str] = {
    "tier1_matches": "plain",
    "understat_matches": "understat",
    "ucl_matches": "plain",
    "uel_matches": "plain",
    "conf_matches": "plain",
}

LEDGER_COLS = [
    "date", "match_num", "league", "div", "home_cn", "away_cn",
    "market", "option", "odds", "model_prob", "implied_prob", "edge",
    "ev", "stake_pct", "hit", "pnl_unit", "pnl_pct",
]


# --------------------------------------------------------------------------- #
# 读取预测
# --------------------------------------------------------------------------- #
def load_predictions(json_path: str | Path) -> list[dict[str, Any]]:
    """读取预测报告 JSON，返回**非 skip**的场次记录列表。"""
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    preds = data.get("predictions", [])
    return [p for p in preds if not p.get("skipped")]


# --------------------------------------------------------------------------- #
# 结果查询
# --------------------------------------------------------------------------- #
def _norm_date(v: Any) -> str:
    ts = pd.to_datetime(v, errors="coerce")
    return ts.strftime("%Y-%m-%d") if not pd.isna(ts) else ""


def load_result_index() -> dict[tuple, tuple[int, int]]:
    """从本地 processed parquet 构建 (league_code, date, home, away) -> (ft_home, ft_away)。

    home/away 已做归一化（去空格/点号/小写），便于跨源对齐。
    """
    settings = get_settings()
    index: dict[tuple, tuple[int, int]] = {}
    for name, kind in RESULT_SOURCES.items():
        path = settings.processed_dir / f"{name}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        need = ["league_code", "date", "home_team", "away_team", "ft_home", "ft_away"]
        if not all(c in df.columns for c in need):
            continue
        df = df[need].copy()
        if kind == "understat":
            from src.ingest.understat import normalize_team
            df["home_team"] = df["home_team"].map(normalize_team)
            df["away_team"] = df["away_team"].map(normalize_team)
        # 只保留有真实比分的行
        df = df.dropna(subset=["ft_home", "ft_away"])
        for r in df.itertuples(index=False):
            key = (str(r.league_code), _norm_date(r.date),
                   _norm(r.home_team), _norm(r.away_team))
            if key in index:
                continue
            index[key] = (int(r.ft_home), int(r.ft_away))
    return index


def load_manual_results(path: str | Path) -> dict[tuple, tuple[int, int]]:
    """手动补录赛果：CSV 需含 match_num, ft_home, ft_away（可选 league, home_cn, away_cn）。

    返回 {match_num: (ft_home, ft_away)} 与 {match_num: None} 之外的直接按编号合并。
    """
    df = pd.read_csv(path)
    out: dict[tuple, tuple[int, int]] = {}
    for r in df.itertuples(index=False):
        num = str(getattr(r, "match_num", ""))
        if not num:
            continue
        try:
            out[(num,)] = (int(r.ft_home), int(r.ft_away))  # type: ignore[dict-item]
        except (TypeError, ValueError):
            continue
    return out


# --------------------------------------------------------------------------- #
# 判定
# --------------------------------------------------------------------------- #
def had_result(ft_home: int, ft_away: int) -> str:
    if ft_home > ft_away:
        return "胜"
    if ft_home == ft_away:
        return "平"
    return "负"


def hhad_result(ft_home: int, ft_away: int, goal_line: float) -> str:
    diff = (ft_home + goal_line) - ft_away
    if diff > 0:
        return "胜"
    if diff == 0:
        return "平"
    return "负"


def bet_won(market: str, option: str, ft_home: int, ft_away: int,
            goal_line: float | None) -> bool:
    if market == "HAD":
        return had_result(ft_home, ft_away) == option
    if market == "HHAD":
        gl = goal_line if goal_line is not None else 0.0
        return hhad_result(ft_home, ft_away, gl) == option
    return False


# --------------------------------------------------------------------------- #
# 对账主流程
# --------------------------------------------------------------------------- #
def reconcile_predictions(predictions: list[dict[str, Any]],
                          index: dict[tuple, tuple[int, int]],
                          manual: dict[tuple, tuple[int, int]] | None = None
                          ) -> list[dict[str, Any]]:
    """逐场比对，返回对账行列表。"""
    manual = manual or {}
    rows: list[dict[str, Any]] = []
    for p in predictions:
        div = p.get("div")
        date = p.get("match_date", "")
        hm = p.get("home_matched", "")
        am = p.get("away_matched", "")
        key = (str(div), date, _norm(hm), _norm(am))
        num_key = (str(p.get("match_num", "")),)

        ft = None
        if num_key in manual:
            ft = manual[num_key]
        elif key in index:
            ft = index[key]

        row: dict[str, Any] = {
            "match_num": p.get("match_num", ""),
            "match_date": date,
            "league": p.get("league", ""),
            "div": div,
            "home_cn": p.get("home_cn", ""),
            "away_cn": p.get("away_cn", ""),
            "home_matched": hm,
            "away_matched": am,
            "ft_home": None,
            "ft_away": None,
            "actual": None,
            "had_pred": None,
            "had_hit": None,
            "had": p.get("had") or {},
            "score_pred": p.get("score_most_likely"),
            "score_hit": None,
            "value_bets": [],
        }
        if ft is None:
            row["resolved"] = False
            rows.append(row)
            continue

        ft_h, ft_a = int(ft[0]), int(ft[1])
        row["resolved"] = True
        row["ft_home"] = ft_h
        row["ft_away"] = ft_a
        row["actual"] = had_result(ft_h, ft_a)

        had = p.get("had") or {}
        if had:
            row["had_pred"] = max(had, key=had.get) if had else None
            row["had_hit"] = row["had_pred"] == row["actual"]

        sp = p.get("score_most_likely")
        if sp:
            try:
                ph, pa = sp.split(":")
                row["score_hit"] = (int(ph) == ft_h and int(pa) == ft_a)
            except (ValueError, TypeError):
                row["score_hit"] = None

        gl = p.get("hhad_goal_line")
        bets = []
        for b in p.get("value_bets", []):
            won = bet_won(b.get("market", ""), b.get("option", ""),
                          ft_h, ft_a, gl)
            odds = float(b.get("odds", 0.0) or 0.0)
            stake = float(b.get("stake_pct", 0.0) or 0.0)
            pnl_unit = (odds - 1.0) if won else -1.0
            bets.append({
                **b,
                "hit": won,
                "pnl_unit": pnl_unit,
                "pnl_pct": pnl_unit * stake,
            })
        row["value_bets"] = bets
        rows.append(row)
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    resolved = [r for r in rows if r.get("resolved")]
    n = len(resolved)
    had_hits = sum(1 for r in resolved if r.get("had_hit") is True)
    score_hits = sum(1 for r in resolved if r.get("score_hit") is True)

    # 对数损失（HAD）
    ll = float("nan")
    if n:
        eps = 1e-12
        idx_map = {"胜": 0, "平": 1, "负": 2}
        total = 0.0
        for r in resolved:
            had = r.get("had") or {}
            if not had:
                continue
            probs = [had.get("胜", 0.0), had.get("平", 0.0), had.get("负", 0.0)]
            actual_idx = idx_map.get(r["actual"], 0)
            total += -np.log(max(probs[actual_idx], eps))
        ll = total / n if n else float("nan")

    # 价值选项盈亏（单位注 + 按仓位）
    bets = [b for r in resolved for b in r.get("value_bets", [])]
    n_bets = len(bets)
    hits = sum(1 for b in bets if b.get("hit"))
    pnl_unit = sum(b.get("pnl_unit", 0.0) for b in bets)
    pnl_pct = sum(b.get("pnl_pct", 0.0) for b in bets)
    staked_pct = sum(b.get("stake_pct", 0.0) for b in bets)

    return {
        "total": len(rows),
        "resolved": n,
        "unresolved": len(rows) - n,
        "had_accuracy": (had_hits / n) if n else float("nan"),
        "score_accuracy": (score_hits / n) if n else float("nan"),
        "log_loss": ll,
        "n_bets": n_bets,
        "bet_hit_rate": (hits / n_bets) if n_bets else float("nan"),
        "pnl_unit": pnl_unit,
        "pnl_pct": pnl_pct,
        "roi_unit": (pnl_unit / n_bets) if n_bets else float("nan"),
        "staked_pct": staked_pct,
    }


# --------------------------------------------------------------------------- #
# 台账
# --------------------------------------------------------------------------- #
def ledger_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把对账结果展开成台账行（每条价值选项一行）。"""
    out: list[dict[str, Any]] = []
    for r in rows:
        if not r.get("resolved"):
            continue
        for b in r.get("value_bets", []):
            out.append({
                "date": r.get("match_date"),
                "match_num": r.get("match_num"),
                "league": r.get("league"),
                "div": r.get("div"),
                "home_cn": r.get("home_cn"),
                "away_cn": r.get("away_cn"),
                "market": b.get("market"),
                "option": b.get("option"),
                "odds": b.get("odds"),
                "model_prob": b.get("model_prob"),
                "implied_prob": b.get("implied_prob"),
                "edge": b.get("edge"),
                "ev": b.get("ev"),
                "stake_pct": b.get("stake_pct"),
                "hit": b.get("hit"),
                "pnl_unit": b.get("pnl_unit"),
                "pnl_pct": b.get("pnl_pct"),
            })
    return out


def append_ledger(rows: list[dict[str, Any]], ledger_path: Path | None = None) -> Path:
    """把价值选项追加到投注台账（按 match_num+market+option+date 去重）。"""
    settings = get_settings()
    path = ledger_path or (settings.processed_dir / "bet_ledger.parquet")
    new = pd.DataFrame(ledger_rows(rows), columns=LEDGER_COLS)
    if new.empty:
        return path
    if path.exists():
        old = pd.read_parquet(path)
        key_cols = ["date", "match_num", "market", "option"]
        if all(c in old.columns for c in key_cols):
            old_key = old[key_cols].astype(str).agg("|".join, axis=1)
            new_key = new[key_cols].astype(str).agg("|".join, axis=1)
            new = new[~new_key.isin(set(old_key))]
        merged = pd.concat([old, new], ignore_index=True)
    else:
        merged = new
    merged.to_parquet(path, index=False)
    return path


# --------------------------------------------------------------------------- #
# 报告
# --------------------------------------------------------------------------- #
def write_reconcile_report(rows: list[dict[str, Any]], stats: dict[str, Any],
                           path_base: Path | None = None) -> tuple[Path, Path]:
    settings = get_settings()
    settings.ensure_dirs()
    ts = datetime.now().strftime("%Y%m%d")
    base = path_base or (settings.reports_dir / f"reconcile_{ts}")
    md_path = base.with_suffix(".md")
    json_path = base.with_suffix(".json")

    lines = [
        f"# 对账报告 {datetime.now().isoformat(timespec='seconds')}",
        "",
        f"- 场次总数：{stats['total']}，已出赛果：{stats['resolved']}，"
        f"待补：{stats['unresolved']}",
        f"- HAD 命中率：{stats['had_accuracy']:.4f}（已出赛果场次）",
        f"- 最可能比分命中率：{stats['score_accuracy']:.4f}",
        f"- HAD 对数损失：{stats['log_loss']:.4f}",
        "",
        "## 逐场比对",
        "",
        "| 编号 | 联赛 | 对阵 | 实际比分 | HAD预测 | 命中 | 最可能比分 | 比分命中 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if not r.get("resolved"):
            lines.append(f"| {r['match_num']} | {r['league']} | "
                         f"{r['home_cn']} vs {r['away_cn']} | 待补 | - | - | - | - |")
            continue
        score = f"{r['ft_home']}:{r['ft_away']}"
        hit = "✓" if r.get("had_hit") else "✗"
        sh = "✓" if r.get("score_hit") else "✗"
        lines.append(
            f"| {r['match_num']} | {r['league']} | {r['home_cn']} vs {r['away_cn']} "
            f"| {score} | {r['had_pred']} | {hit} | {r['score_pred']} | {sh} |"
        )

    lines += ["", "## 价值选项盈亏", "",
              "| 编号 | 联赛 | 对阵 | 玩法 | 选项 | 赔率 | edge | 仓位 | 命中 | 盈亏(单位注) |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        for b in r.get("value_bets", []):
            hit = "✓" if b.get("hit") else "✗"
            lines.append(
                f"| {r['match_num']} | {r['league']} | {r['home_cn']} vs {r['away_cn']} "
                f"| {b['market']} | {b['option']} | {b.get('odds', 0):.2f} "
                f"| {b.get('edge', 0):.3f} | {b.get('stake_pct', 0) * 100:.2f}% "
                f"| {hit} | {b.get('pnl_unit', 0):+.2f} |"
            )
    if not any(r.get("value_bets") for r in rows):
        lines.append("（无价值选项）")

    lines += ["",
              f"## 汇总",
              "",
              f"- 下注数：{stats['n_bets']}，命中率：{stats['bet_hit_rate']:.4f}",
              f"- 单位注净盈亏：{stats['pnl_unit']:+.2f}，ROI：{stats['roi_unit']:+.4f}",
              f"- 按建议仓位净盈亏（占资金比例）：{stats['pnl_pct']:+.4f}",
              "",
              "> 待补场次可运行 `fetch-understat --online` / `fetch-ucl --online` 更新赛果，",
              "> 或用 `--manual scores.csv`（列：match_num, ft_home, ft_away）手动补录。"]

    md_path.write_text("\n".join(lines), encoding="utf-8")
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "stats": stats,
        "matches": rows,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1,
                                    default=str), encoding="utf-8")
    return md_path, json_path


# --------------------------------------------------------------------------- #
# 编排
# --------------------------------------------------------------------------- #
def run_reconcile(json_path: str | Path,
                  manual_path: str | Path | None = None) -> dict[str, Any]:
    predictions = load_predictions(json_path)
    if not predictions:
        raise RuntimeError(f"预测报告为空或无可用场次: {json_path}")
    index = load_result_index()
    manual = load_manual_results(manual_path) if manual_path else None
    rows = reconcile_predictions(predictions, index, manual)
    stats = summarize(rows)
    md, js = write_reconcile_report(rows, stats)
    ledger = append_ledger(rows)
    return {"rows": rows, "stats": stats, "md": md, "json": js, "ledger": ledger}
