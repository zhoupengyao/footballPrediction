"""对账：把预测报告与实际比分比对，产出命中率/对数损失/模拟盈亏，并写入投注台账。

支持五种玩法的逐场结算：
    HAD          胜平负
    HHAD         让球胜平负（使用预测时的让球线）
    SCORE        比分（Top1 + Top3）
    TOTAL_GOALS  总进球（0/1/.../7+ 桶）
    HALF_FULL    半全场（需要半场比分）

同时结算价值选项的命中与盈亏，并把价值选项追加到
``data/processed/bet_ledger.parquet``（长期 ROI / CLV 的唯一数据源）。

赛果来源：
    - 本地 processed parquet（tier1 / tier1_gh / understat / ucl / uel / conf /
      apifootball）
    - 手动 CSV（``--manual``），支持全场与半场比分，按 ``date + match_num`` 匹配

若赛果尚未落盘，对应场次标记为「无赛果（待补）」，不会伪造命中。
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
TTG_BUCKETS = ["0", "1", "2", "3", "4", "5", "6", "7+"]
_LABEL_TO_RESULT = {"胜": "H", "平": "D", "负": "A"}

# 结果来源：processed 数据集名 -> 是否需要用 understat 队名归一化
RESULT_SOURCES: dict[str, str] = {
    "tier1_matches": "plain",
    "tier1_gh_matches": "plain",
    "understat_matches": "understat",
    "ucl_matches": "plain",
    "uel_matches": "plain",
    "conf_matches": "plain",
    "apifootball_matches": "plain",
}

LEDGER_COLS = [
    "date", "match_num", "league", "div", "home_cn", "away_cn",
    "market", "option", "odds", "model_prob", "implied_prob", "edge",
    "ev", "stake_pct", "hit", "pnl_unit", "pnl_pct",
]


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
def _to_int(value: Any) -> int | None:
    """把 CSV / parquet 里的比分安全转成 int，缺失返回 None。"""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _top_key(probs: dict[str, Any] | None) -> str | None:
    """概率字典里概率最高的选项。"""
    if not probs:
        return None
    valid = {str(k): float(v) for k, v in probs.items()
             if v is not None and not pd.isna(v)}
    if not valid:
        return None
    return max(valid, key=valid.get)


def _score_list(items: Any) -> list[str]:
    """兼容 ``[{"score": "1:0"}]`` 与 ``[["1:0", 0.2]]`` 两种比分结构。"""
    out: list[str] = []
    for item in items or []:
        if isinstance(item, dict):
            s = item.get("score")
        elif isinstance(item, (list, tuple)) and item:
            s = item[0]
        else:
            s = None
        if s is not None:
            out.append(str(s))
    return out


def _hafu_label(items: Any) -> str | None:
    """半全场 Top1 标签，兼容 list/dict 两种结构。"""
    if not items:
        return None
    first = items[0]
    if isinstance(first, dict):
        return first.get("label") or first.get("name")
    if isinstance(first, (list, tuple)) and first:
        return str(first[0])
    return str(first)


def _fmt_acc(value: Any) -> str:
    try:
        f = float(value)
        if f != f:  # NaN
            return "—"
        return f"{f:.1%}"
    except (TypeError, ValueError):
        return "—"


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


def _unpack_result(value: Any) -> dict[str, int | None] | None:
    """兼容旧版 ``(ft_home, ft_away)`` 和新版字典/四元组。"""
    if value is None:
        return None
    if isinstance(value, dict):
        ft_h = _to_int(value.get("ft_home"))
        ft_a = _to_int(value.get("ft_away"))
        if ft_h is None or ft_a is None:
            return None
        return {
            "ft_home": ft_h,
            "ft_away": ft_a,
            "ht_home": _to_int(value.get("ht_home")),
            "ht_away": _to_int(value.get("ht_away")),
        }
    if isinstance(value, (tuple, list)):
        if len(value) >= 4:
            ft_h, ft_a, ht_h, ht_a = value[:4]
        elif len(value) == 2:
            ft_h, ft_a = value
            ht_h = ht_a = None
        else:
            return None
        ft_h, ft_a = _to_int(ft_h), _to_int(ft_a)
        if ft_h is None or ft_a is None:
            return None
        return {
            "ft_home": ft_h,
            "ft_away": ft_a,
            "ht_home": _to_int(ht_h),
            "ht_away": _to_int(ht_a),
        }
    return None


def load_result_index() -> dict[tuple, dict[str, int | None]]:
    """从本地 processed parquet 构建赛果索引。

    键：``(league_code, date, 归一化主队, 归一化客队)``
    值：``{"ft_home", "ft_away", "ht_home", "ht_away"}``
    """
    settings = get_settings()
    index: dict[tuple, dict[str, int | None]] = {}
    for name, kind in RESULT_SOURCES.items():
        path = settings.processed_dir / f"{name}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        need = ["league_code", "date", "home_team", "away_team", "ft_home", "ft_away"]
        if not all(c in df.columns for c in need):
            continue
        cols = list(need)
        for c in ("ht_home", "ht_away"):
            if c in df.columns:
                cols.append(c)
        df = df[cols].copy()
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
            index[key] = {
                "ft_home": int(r.ft_home),
                "ft_away": int(r.ft_away),
                "ht_home": _to_int(getattr(r, "ht_home", None)),
                "ht_away": _to_int(getattr(r, "ht_away", None)),
            }
    return index


def load_manual_results(path: str | Path) -> dict[tuple, dict[str, int | None]]:
    """读取手动赛果 CSV。

    必需列：``match_num, ft_home, ft_away``
    可选列：``date, league, home_cn, away_cn, ht_home, ht_away``

    优先用 ``(date, match_num)`` 匹配；没有 date 列时退回 ``(match_num,)``。
    ``ht_home/ht_away`` 用于半全场结算，缺失时半全场标记为「无法结算」。
    """
    df = pd.read_csv(path)
    if not {"match_num", "ft_home", "ft_away"}.issubset(df.columns):
        raise ValueError(
            "手动赛果 CSV 至少需要 match_num, ft_home, ft_away 三列；"
            "半全场请再加 ht_home, ht_away"
        )

    out: dict[tuple, dict[str, int | None]] = {}
    for r in df.itertuples(index=False):
        num = str(getattr(r, "match_num", "")).strip()
        ft_h = _to_int(getattr(r, "ft_home", None))
        ft_a = _to_int(getattr(r, "ft_away", None))
        if not num or ft_h is None or ft_a is None:
            continue
        payload = {
            "ft_home": ft_h,
            "ft_away": ft_a,
            "ht_home": _to_int(getattr(r, "ht_home", None)),
            "ht_away": _to_int(getattr(r, "ht_away", None)),
        }
        date = _norm_date(getattr(r, "date", ""))
        if date:
            # 有日期的行只按 (date, match_num) 存；不要再写 (match_num,)，
            # 否则 2026-10-27 的“周一003”会错误命中 2026-10-20 的同编号场次。
            out[(date, num)] = payload
        else:
            # 兼容旧版无 date 列的 CSV：只在这种情况下允许按编号回退。
            out[(num,)] = payload
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


def total_goals_bucket(total: int) -> str:
    return str(total) if total <= 6 else "7+"


def half_full_result(ht_home: int | None, ht_away: int | None,
                     ft_home: int, ft_away: int) -> str | None:
    if ht_home is None or ht_away is None:
        return None
    return f"{had_result(ht_home, ht_away)}/{had_result(ft_home, ft_away)}"


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
def _market_predictions(p: dict[str, Any]) -> dict[str, Any]:
    """从预测记录里抽出各玩法 Top1，供赛前展示和赛后命中对比。"""
    scores = _score_list(p.get("score_top") or p.get("crs_top"))
    score_top1 = p.get("score_most_likely") or (scores[0] if scores else None)
    layer_preds = {
        "HAD_DC": _top_key(p.get("had_dc")),
        "HAD_ELO": _top_key(p.get("elo_had")),
        "HAD_ML": _top_key(p.get("ml_had")),
    }
    return {
        "had_pred": _top_key(p.get("had")),
        "hhad_pred": _top_key(p.get("hhad")),
        "score_pred": score_top1,
        "score_top": scores,
        "ttg_pred": _top_key(p.get("ttg")),
        "half_full_pred": _hafu_label(p.get("hafu_top")),
        "layer_preds": {k: v for k, v in layer_preds.items() if v is not None},
    }


def reconcile_predictions(predictions: list[dict[str, Any]],
                          index: dict[tuple, dict[str, Any]],
                          manual: dict[tuple, dict[str, Any]] | None = None
                          ) -> list[dict[str, Any]]:
    """逐场比对，返回对账行列表（含五种玩法与价值注）。"""
    manual = manual or {}
    rows: list[dict[str, Any]] = []
    for p in predictions:
        div = p.get("div")
        date = p.get("match_date", "")
        hm = p.get("home_matched", "")
        am = p.get("away_matched", "")
        key = (str(div), _norm_date(date), _norm(hm), _norm(am))
        num = str(p.get("match_num", ""))
        mp = _market_predictions(p)
        gl = p.get("hhad_goal_line")

        raw_result = manual.get((_norm_date(date), num)) or manual.get((num,))
        if raw_result is None and key in index:
            raw_result = index[key]
        result = _unpack_result(raw_result)

        row: dict[str, Any] = {
            "match_num": num,
            "match_date": date,
            "league": p.get("league", ""),
            "div": div,
            "home_cn": p.get("home_cn", ""),
            "away_cn": p.get("away_cn", ""),
            "home_matched": hm,
            "away_matched": am,
            "resolved": False,
            "ft_home": None,
            "ft_away": None,
            "ht_home": None,
            "ht_away": None,
            "actual": None,
            "had": p.get("had") or {},
            "had_pred": mp["had_pred"],
            "had_hit": None,
            "score_pred": mp["score_pred"],
            "score_hit": None,
            "score_top": mp["score_top"],
            "score_top3_hit": None,
            "hhad_goal_line": gl,
            "hhad_pred": mp["hhad_pred"],
            "hhad_actual": None,
            "hhad_hit": None,
            "ttg_pred": mp["ttg_pred"],
            "ttg_actual": None,
            "ttg_hit": None,
            "half_full_pred": mp["half_full_pred"],
            "half_full_actual": None,
            "half_full_hit": None,
            "layer_preds": mp["layer_preds"],
            "layer_hits": {k: None for k in mp["layer_preds"]},
            "value_bets": [],
        }
        if result is None:
            rows.append(row)
            continue

        ft_h = int(result["ft_home"])
        ft_a = int(result["ft_away"])
        ht_h = result.get("ht_home")
        ht_a = result.get("ht_away")
        actual_had = had_result(ft_h, ft_a)
        actual_score = f"{ft_h}:{ft_a}"
        total = ft_h + ft_a
        actual_ttg = total_goals_bucket(total)
        actual_hf = half_full_result(ht_h, ht_a, ft_h, ft_a)
        actual_hhad = (hhad_result(ft_h, ft_a, float(gl))
                       if gl is not None else None)

        row.update({
            "resolved": True,
            "ft_home": ft_h,
            "ft_away": ft_a,
            "ht_home": ht_h,
            "ht_away": ht_a,
            "actual": actual_had,
            "hhad_actual": actual_hhad,
            "ttg_actual": actual_ttg,
            "half_full_actual": actual_hf,
        })

        if row["had_pred"] is not None:
            row["had_hit"] = row["had_pred"] == actual_had
        if row["score_pred"] is not None:
            row["score_hit"] = row["score_pred"] == actual_score
        if row["score_top"]:
            row["score_top3_hit"] = actual_score in row["score_top"]
        if row["hhad_pred"] is not None and actual_hhad is not None:
            row["hhad_hit"] = row["hhad_pred"] == actual_hhad
        if row["ttg_pred"] is not None:
            row["ttg_hit"] = row["ttg_pred"] == actual_ttg
        if row["half_full_pred"] is not None and actual_hf is not None:
            row["half_full_hit"] = row["half_full_pred"] == actual_hf
        for layer, layer_pred in row["layer_preds"].items():
            row["layer_hits"][layer] = layer_pred == actual_had

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


def _market_stat(rows: list[dict[str, Any]], hit_key: str,
                 pred_key: str | None = None) -> dict[str, Any]:
    subset = [r for r in rows if r.get(hit_key) is not None
              and (pred_key is None or r.get(pred_key) is not None)]
    hits = sum(1 for r in subset if r.get(hit_key))
    n = len(subset)
    return {
        "n": n,
        "hits": hits,
        "accuracy": (hits / n) if n else float("nan"),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    resolved = [r for r in rows if r.get("resolved")]
    n = len(resolved)
    had_hits = sum(1 for r in resolved if r.get("had_hit") is True)
    score_hits = sum(1 for r in resolved if r.get("score_hit") is True)

    # 对数损失（HAD，仅统计有概率的场次）
    ll = float("nan")
    ll_rows = [r for r in resolved if r.get("had")]
    if ll_rows:
        eps = 1e-12
        idx_map = {"胜": 0, "平": 1, "负": 2}
        total_ll = 0.0
        for r in ll_rows:
            had = r.get("had") or {}
            probs = [had.get("胜", 0.0), had.get("平", 0.0), had.get("负", 0.0)]
            actual_idx = idx_map.get(r.get("actual", "胜"), 0)
            total_ll += -np.log(max(float(probs[actual_idx]), eps))
        ll = total_ll / len(ll_rows)

    # 价值选项盈亏（单位注 + 按仓位）
    bets = [b for r in resolved for b in r.get("value_bets", [])]
    n_bets = len(bets)
    hits = sum(1 for b in bets if b.get("hit"))
    pnl_unit = sum(b.get("pnl_unit", 0.0) for b in bets)
    pnl_pct = sum(b.get("pnl_pct", 0.0) for b in bets)
    staked_pct = sum(b.get("stake_pct", 0.0) for b in bets)

    layer_hits = {
        layer: [r["layer_hits"][layer] for r in resolved
                if r.get("layer_hits", {}).get(layer) is not None]
        for layer in ("HAD_DC", "HAD_ELO", "HAD_ML")
    }
    layer_stats = {
        layer: {
            "n": len(vals),
            "hits": sum(1 for v in vals if v),
            "accuracy": (sum(1 for v in vals if v) / len(vals)) if vals else float("nan"),
        }
        for layer, vals in layer_hits.items()
    }

    markets = {
        "HAD": _market_stat(resolved, "had_hit", "had_pred"),
        "HHAD": _market_stat(resolved, "hhad_hit", "hhad_pred"),
        "SCORE_TOP1": _market_stat(resolved, "score_hit", "score_pred"),
        "SCORE_TOP3": _market_stat(resolved, "score_top3_hit", "score_top"),
        "TOTAL_GOALS": _market_stat(resolved, "ttg_hit", "ttg_pred"),
        "HALF_FULL": _market_stat(resolved, "half_full_hit", "half_full_pred"),
        **layer_stats,
    }

    return {
        "total": len(rows),
        "resolved": n,
        "unresolved": len(rows) - n,
        "had_accuracy": markets["HAD"]["accuracy"],
        "score_accuracy": markets["SCORE_TOP1"]["accuracy"],
        "log_loss": ll,
        "markets": markets,
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
    """把价值选项追加到投注台账（按 date+match_num+market+option 去重）。"""
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
            # 同键覆盖：修正赛果后重新对账时，旧的错误盈亏不能继续留在台账里。
            old = old[~old_key.isin(set(new_key))]
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
    markets = stats.get("markets", {})

    lines = [
        f"# 对账报告 {datetime.now().isoformat(timespec='seconds')}",
        "",
        f"- 场次总数：{stats['total']}，已出赛果：{stats['resolved']}，"
        f"待补：{stats['unresolved']}",
        f"- HAD 命中率：{_fmt_acc(stats.get('had_accuracy'))}",
        f"- HHAD 命中率：{_fmt_acc(markets.get('HHAD', {}).get('accuracy'))}",
        f"- 比分 Top1 命中率：{_fmt_acc(markets.get('SCORE_TOP1', {}).get('accuracy'))}，"
        f"Top3 命中率：{_fmt_acc(markets.get('SCORE_TOP3', {}).get('accuracy'))}",
        f"- 总进球命中率：{_fmt_acc(markets.get('TOTAL_GOALS', {}).get('accuracy'))}",
        f"- 半全场命中率：{_fmt_acc(markets.get('HALF_FULL', {}).get('accuracy'))}",
        f"- HAD 对数损失：{stats['log_loss']:.4f}",
        "",
        "## 逐场比对",
        "",
        "| 编号 | 联赛 | 对阵 | 比分 | 半场 | HAD | 命中 | HHAD | 命中 | "
        "比分Top1 | 命中 | Top3 | 总进球 | 命中 | 半全场 | 命中 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if not r.get("resolved"):
            lines.append(
                f"| {r['match_num']} | {r['league']} | "
                f"{r['home_cn']} vs {r['away_cn']} | 待补 | - | "
                f"{r.get('had_pred') or '-'} | - | {r.get('hhad_pred') or '-'} | - | "
                f"{r.get('score_pred') or '-'} | - | - | {r.get('ttg_pred') or '-'} | - | "
                f"{r.get('half_full_pred') or '-'} | - |"
            )
            continue
        score = f"{r['ft_home']}:{r['ft_away']}"
        ht = (f"{r['ht_home']}:{r['ht_away']}"
              if r.get("ht_home") is not None and r.get("ht_away") is not None else "-")

        def mark(v: Any) -> str:
            return "—" if v is None else ("✓" if v else "✗")

        lines.append(
            f"| {r['match_num']} | {r['league']} | {r['home_cn']} vs {r['away_cn']} "
            f"| {score} | {ht} | {r.get('had_pred') or '-'} | {mark(r.get('had_hit'))} "
            f"| {r.get('hhad_pred') or '-'} | {mark(r.get('hhad_hit'))} "
            f"| {r.get('score_pred') or '-'} | {mark(r.get('score_hit'))} "
            f"| {mark(r.get('score_top3_hit'))} | {r.get('ttg_pred') or '-'} "
            f"| {mark(r.get('ttg_hit'))} | {r.get('half_full_pred') or '-'} "
            f"| {mark(r.get('half_full_hit'))} |"
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
              f"- 下注数：{stats['n_bets']}，命中率：{_fmt_acc(stats.get('bet_hit_rate'))}",
              f"- 单位注净盈亏：{stats['pnl_unit']:+.2f}，ROI：{_fmt_acc(stats.get('roi_unit'))}",
              f"- 按建议仓位净盈亏（占资金比例）：{stats['pnl_pct']:+.4f}",
              "",
              "> 待补场次可运行 `fetch-understat --online` / `fetch-ucl --online` 更新赛果，",
              "> 或用 `--manual results.csv`（列：date, match_num, ft_home, ft_away, ht_home, ht_away）手动补录。"]

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
                  manual_path: str | Path | None = None,
                  date_tag: str | None = None) -> dict[str, Any]:
    predictions = load_predictions(json_path)
    if not predictions:
        raise RuntimeError(f"预测报告为空或无可用场次: {json_path}")
    index = load_result_index()
    manual = load_manual_results(manual_path) if manual_path else None
    rows = reconcile_predictions(predictions, index, manual)
    stats = summarize(rows)
    base = None
    if date_tag:
        base = get_settings().reports_dir / f"reconcile_{date_tag}"
    md, js = write_reconcile_report(rows, stats, path_base=base)
    ledger = append_ledger(rows)
    return {"rows": rows, "stats": stats, "md": md, "json": js, "ledger": ledger}
