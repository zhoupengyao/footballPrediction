"""把本地报告导出成静态站点可直接读取的 JSON。

输出目录默认 ``web/public/data``，结构：

    manifest.json                 站点元信息、日期索引、联赛、数据源
    history/index.json            历史日期索引
    history/YYYY-MM-DD.json       每场比赛的预测 + 实际结果 + 五种玩法命中
    recommendations/YYYY-MM-DD.json  三档风险的候选/观察清单
    performance.json              累计命中率、价值注 ROI、分联赛、每日曲线
    backtests/index.json          回测索引
    backtests/{id}.json           回测汇总 + 资金曲线（不含逐场大数组）
    odds-diff/YYYY-MM-DD.json     同日多份快照的赔率变化

设计原则：
    - 只依赖报告文件，不重新训练/预测；
    - 所有 NaN/Infinity 转 null，前端 JSON.parse 不会失败；
    - 命中率只统计「赛前预测 + 已结算」场次，避免赛后信息污染；
    - 预测优先使用 reports/archive 里开赛前最后一次存档。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import PROJECT_ROOT, get_leagues, get_settings
from src.jingcai.team_names import _norm
from src.recommend import run_recommend
from src.reconcile import (had_result, half_full_result, hhad_result,
                           load_manual_results, load_result_index,
                           reconcile_predictions, total_goals_bucket)

TZ = timezone(timedelta(hours=8))
SCHEMA_VERSION = 1

DISCLAIMER = (
    "本页面仅用于统计研究与学习，不构成任何投注建议。"
    "竞彩返奖率约 73%，历史回测 ROI 为负，请勿据此重仓真钱。"
)

CN_OPTION = {"胜": "home", "平": "draw", "负": "away"}
OPTION_CN = {v: k for k, v in CN_OPTION.items()}

MARKET_KEYS = (
    "HAD", "HHAD", "SCORE_TOP1", "SCORE_TOP3",
    "TOTAL_GOALS", "HALF_FULL", "HAD_DC", "HAD_ELO", "HAD_ML",
)


# --------------------------------------------------------------------------- #
# 通用工具
# --------------------------------------------------------------------------- #
def _now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def _num(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _clean(value: Any) -> Any:
    """递归清理 NaN/Infinity，并把浮点保留 4 位。"""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, 4)
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return _clean(value.item())
        except (ValueError, TypeError):
            return str(value)
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(_clean(payload), ensure_ascii=False, indent=2,
                      allow_nan=False, default=str)
    path.write_text(text, encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=None)


def _kickoff(p: dict[str, Any]) -> datetime | None:
    date = str(p.get("match_date") or "").strip()[:10]
    if not date:
        return None
    clock = str(p.get("match_time") or "").strip()
    text = f"{date}T{clock}" if clock else date
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _kickoff_iso(p: dict[str, Any]) -> str | None:
    dt = _kickoff(p)
    return dt.isoformat(timespec="seconds") + "+08:00" if dt else None


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.name


def _match_key(p: dict[str, Any]) -> str | None:
    mid = p.get("match_id")
    if mid is not None:
        return f"id:{mid}"
    num = p.get("match_num")
    date = p.get("match_date")
    return f"num:{date}:{num}" if num else None


def _option_key(value: Any) -> str | None:
    text = str(value or "").strip()
    if text in ("home", "draw", "away"):
        return text
    return CN_OPTION.get(text)


def _had_probs(raw: Any) -> dict[str, float | None] | None:
    if not isinstance(raw, dict) or not raw:
        return None
    return {
        "home": _num(raw.get("胜", raw.get("home"))),
        "draw": _num(raw.get("平", raw.get("draw"))),
        "away": _num(raw.get("负", raw.get("away"))),
    }


def _had_odds(raw: Any) -> dict[str, float | None] | None:
    if not isinstance(raw, dict) or not raw:
        return None
    return {
        "home": _num(raw.get("home", raw.get("胜"))),
        "draw": _num(raw.get("draw", raw.get("平"))),
        "away": _num(raw.get("away", raw.get("负"))),
    }


def _top_key(probs: dict[str, Any] | None) -> str | None:
    if not probs:
        return None
    valid = {str(k): _num(v) for k, v in probs.items() if _num(v) is not None}
    if not valid:
        return None
    return max(valid, key=valid.get)


def _scores(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in raw or []:
        if isinstance(item, dict):
            score = item.get("score")
            prob = item.get("prob")
        elif isinstance(item, (list, tuple)) and item:
            score, prob = item[0], item[1] if len(item) > 1 else None
        else:
            continue
        if score is not None:
            out.append({"score": str(score), "prob": _num(prob)})
    return out


def _hafu(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in raw or []:
        if isinstance(item, dict):
            label = item.get("label") or item.get("name")
            prob = item.get("prob")
        elif isinstance(item, (list, tuple)) and item:
            label, prob = item[0], item[1] if len(item) > 1 else None
        else:
            continue
        if label is not None:
            out.append({"label": str(label), "prob": _num(prob)})
    return out


def _value_bets(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for b in raw or []:
        option = _option_key(b.get("option"))
        out.append({
            "market": b.get("market"),
            "option": option,
            "option_cn": OPTION_CN.get(option or "", b.get("option")),
            "odds": _num(b.get("odds")),
            "model_prob": _num(b.get("model_prob")),
            "implied_prob": _num(b.get("implied_prob")),
            "edge": _num(b.get("edge")),
            "ev": _num(b.get("ev")),
            "stake_pct": _num(b.get("stake_pct")),
            "hit": b.get("hit"),
            "pnl_unit": _num(b.get("pnl_unit")),
            "pnl_pct": _num(b.get("pnl_pct")),
        })
    return out


# --------------------------------------------------------------------------- #
# 读取预测文件并选择「赛前最后一次」
# --------------------------------------------------------------------------- #
def _load_prediction_files(reports_dir: Path) -> list[dict[str, Any]]:
    paths = sorted(reports_dir.glob("predict_*.json"))
    archive = reports_dir / "archive"
    if archive.exists():
        paths += sorted(archive.glob("predict_*.json"))
    files: list[dict[str, Any]] = []
    for path in paths:
        data = _read_json(path)
        if not data:
            continue
        preds = data.get("predictions") or []
        if not preds:
            continue
        match = re.search(r"predict_(\d{8})", path.stem)
        date_tag = match.group(1) if match else ""
        if not date_tag:
            first = preds[0]
            date_tag = str(first.get("business_date") or first.get("match_date") or "")
            date_tag = date_tag.replace("-", "")[:8]
        generated = _parse_dt(data.get("generated_at"))
        if generated is None:
            generated = datetime.fromtimestamp(path.stat().st_mtime)
        files.append({
            "path": path,
            "source": _rel(path),
            "date_tag": date_tag,
            "generated_at": generated,
            "predictions": preds,
        })
    return files


def _select_for_date(files: list[dict[str, Any]],
                     date_tag: str) -> list[dict[str, Any]]:
    """为每场比赛选一个预测版本。

    优先级：
        1. 开赛前生成的版本中，取最新的一份；
        2. 若没有开赛前的，取开赛后最早的一份，并标记 post_kickoff；
        3. 没有预测的，保留最新一条 skipped 记录用于展示原因。
    """
    chosen: dict[str, dict[str, Any]] = {}
    for f in files:
        if f["date_tag"] != date_tag:
            continue
        for p in f["predictions"]:
            key = _match_key(p)
            if not key:
                continue
            generated = f["generated_at"]
            kickoff = _kickoff(p)
            skipped = bool(p.get("skipped"))
            cur = chosen.get(key)

            def take(timing: str) -> None:
                chosen[key] = {
                    "p": p,
                    "meta": {
                        "source": f["source"],
                        "generated_at": generated.isoformat(timespec="seconds"),
                        "timing": timing,
                    },
                }

            if skipped:
                if cur is None or cur["meta"]["timing"] == "skipped":
                    take("skipped")
                continue
            if kickoff is not None and generated <= kickoff:
                if (cur is None or cur["meta"]["timing"] != "pre_match"
                        or generated >= _parse_dt(cur["meta"]["generated_at"])):
                    take("pre_match")
            else:
                timing = "post_kickoff" if kickoff is not None else "unknown"
                if cur is None or cur["meta"]["timing"] in ("post_kickoff", "unknown", "skipped"):
                    if cur is None or generated <= _parse_dt(cur["meta"]["generated_at"]):
                        take(timing)

    def sort_key(item: dict[str, Any]) -> tuple:
        kickoff = _kickoff(item["p"]) or datetime.max
        return (kickoff, str(item["p"].get("match_num") or ""))

    return sorted(chosen.values(), key=sort_key)


# --------------------------------------------------------------------------- #
# 单场记录
# --------------------------------------------------------------------------- #
def _result_obj(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "resolved": True,
        "ft": f"{r.get('ft_home')}:{r.get('ft_away')}",
        "ht": (f"{r.get('ht_home')}:{r.get('ht_away')}"
               if r.get("ht_home") is not None and r.get("ht_away") is not None else None),
        "had": _option_key(r.get("actual")),
        "hhad": _option_key(r.get("hhad_actual")),
        "total_goals": r.get("ttg_actual"),
        "half_full": r.get("half_full_actual"),
    }


def _result_only(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not raw:
        return None
    ft_h = raw.get("ft_home")
    ft_a = raw.get("ft_away")
    if ft_h is None or ft_a is None:
        return None
    ft_h, ft_a = int(ft_h), int(ft_a)
    ht_h, ht_a = raw.get("ht_home"), raw.get("ht_away")
    hhad = hhad_result(ft_h, ft_a, float(raw["hhad_goal_line"])) \
        if raw.get("hhad_goal_line") is not None else None
    return {
        "resolved": True,
        "ft": f"{ft_h}:{ft_a}",
        "ht": f"{ht_h}:{ht_a}" if ht_h is not None and ht_a is not None else None,
        "had": _option_key(had_result(ft_h, ft_a)),
        "hhad": _option_key(hhad) if hhad else None,
        "total_goals": total_goals_bucket(ft_h + ft_a),
        "half_full": half_full_result(ht_h, ht_a, ft_h, ft_a),
    }


def _prediction_obj(p: dict[str, Any], meta: dict[str, Any],
                    r: dict[str, Any] | None) -> dict[str, Any]:
    resolved = bool(r and r.get("resolved"))
    actual_score = f"{r['ft_home']}:{r['ft_away']}" if resolved else None
    score_top = _scores(p.get("score_top") or p.get("crs_top"))
    hafu_top = _hafu(p.get("hafu_top"))
    ttg = {str(k): _num(v) for k, v in (p.get("ttg") or {}).items()}

    had = {
        "available": bool(p.get("had")),
        "probs": _had_probs(p.get("had")),
        "odds": _had_odds(p.get("had_odds")),
        "implied": _had_probs(p.get("had_implied")),
        "blended": _had_probs(p.get("had_blended")),
        "predicted": _option_key(r.get("had_pred") if r else _top_key(p.get("had"))),
        "actual": _option_key(r.get("actual")) if resolved else None,
        "hit": r.get("had_hit") if resolved else None,
    }
    hhad = {
        "available": bool(p.get("hhad")),
        "line": _num(p.get("hhad_goal_line")),
        "probs": _had_probs(p.get("hhad")),
        "odds": _had_odds(p.get("hhad_odds")),
        "implied": _had_probs(p.get("hhad_implied")),
        "blended": _had_probs(p.get("hhad_blended")),
        "predicted": _option_key(r.get("hhad_pred") if r else _top_key(p.get("hhad"))),
        "actual": _option_key(r.get("hhad_actual")) if resolved else None,
        "hit": r.get("hhad_hit") if resolved else None,
    }
    score = {
        "available": bool(score_top),
        "top": score_top,
        "predicted": r.get("score_pred") if r else (p.get("score_most_likely")
                                                    or (score_top[0]["score"] if score_top else None)),
        "actual": actual_score,
        "top1_hit": r.get("score_hit") if resolved else None,
        "top3_hit": r.get("score_top3_hit") if resolved else None,
    }
    total_goals = {
        "available": bool(ttg),
        "probs": ttg,
        "predicted": r.get("ttg_pred") if r else _top_key(ttg),
        "actual": r.get("ttg_actual") if resolved else None,
        "hit": r.get("ttg_hit") if resolved else None,
    }
    half_full = {
        "available": bool(hafu_top),
        "top": hafu_top,
        "predicted": r.get("half_full_pred") if r else (hafu_top[0]["label"] if hafu_top else None),
        "actual": r.get("half_full_actual") if resolved else None,
        "hit": r.get("half_full_hit") if resolved else None,
    }

    layers: dict[str, Any] = {}
    layer_map = (("DC", "had_dc", "HAD_DC"),
                 ("Elo", "elo_had", "HAD_ELO"),
                 ("ML", "ml_had", "HAD_ML"))
    for name, pred_key, hit_key in layer_map:
        probs = _had_probs(p.get(pred_key))
        if not probs:
            continue
        pred = (r.get("layer_preds") or {}).get(hit_key) if r else None
        hit = (r.get("layer_hits") or {}).get(hit_key) if resolved else None
        layers[name] = {
            "probs": probs,
            "predicted": _option_key(pred),
            "hit": hit,
        }

    vbs = (r.get("value_bets") if resolved else p.get("value_bets")) or []
    return {
        "model": p.get("model"),
        "generated_at": meta["generated_at"],
        "timing": meta["timing"],
        "source": meta["source"],
        "xg": {"home": _num(p.get("xg_home")), "away": _num(p.get("xg_away"))},
        "confidence": {"home": p.get("conf_home"), "away": p.get("conf_away")},
        "markets": {
            "HAD": had,
            "HHAD": hhad,
            "SCORE": score,
            "TOTAL_GOALS": total_goals,
            "HALF_FULL": half_full,
        },
        "model_layers": layers,
        "value_bets": _value_bets(vbs),
    }


def _find_result_for_skipped(p: dict[str, Any],
                             manual: dict[tuple, dict[str, Any]],
                             index: dict[tuple, dict[str, Any]]) -> dict[str, Any] | None:
    date = str(p.get("match_date") or "")
    num = str(p.get("match_num") or "")
    raw = manual.get((date, num)) or manual.get((num,))
    if raw is None:
        key = (str(p.get("div")), date,
               _norm(p.get("home_matched", "")), _norm(p.get("away_matched", "")))
        raw = index.get(key)
    if raw is None:
        return None
    raw = dict(raw)
    raw.setdefault("hhad_goal_line", p.get("hhad_goal_line"))
    return _result_only(raw)


def _match_record(item: dict[str, Any],
                  settlement: dict[str, Any] | None,
                  skipped_result: dict[str, Any] | None,
                  leagues: Any) -> dict[str, Any]:
    p = item["p"]
    meta = item["meta"]
    div = p.get("div")
    kickoff = _kickoff(p)
    status = "skipped" if p.get("skipped") else (
        "settled" if settlement and settlement.get("resolved") else "pending")
    record: dict[str, Any] = {
        "id": str(p.get("match_id") or f"{p.get('match_date')}-{p.get('match_num')}"),
        "match_num": p.get("match_num"),
        "date": p.get("match_date"),
        "time": p.get("match_time"),
        "kickoff": _kickoff_iso(p),
        "league": {
            "div": div,
            "name": p.get("league") or (leagues.name_of(div) if div else ""),
            "code": p.get("league_code"),
        },
        "home": {"cn": p.get("home_cn"), "matched": p.get("home_matched")},
        "away": {"cn": p.get("away_cn"), "matched": p.get("away_matched")},
        "status": status,
        "skip_reason": p.get("skipped"),
        "prediction_timing": meta["timing"],
        "prediction": None,
        "result": None,
    }
    if kickoff is None:
        record["kickoff"] = None
    if p.get("skipped"):
        record["result"] = skipped_result
        return record

    record["prediction"] = _prediction_obj(p, meta, settlement)
    if settlement and settlement.get("resolved"):
        record["result"] = _result_obj(settlement)
    return record


# --------------------------------------------------------------------------- #
# 统计
# --------------------------------------------------------------------------- #
def _hit(record: dict[str, Any], market: str) -> bool | None:
    pred = record.get("prediction") or {}
    if market in ("HAD", "HHAD"):
        return (pred.get("markets", {}).get(market) or {}).get("hit")
    if market == "SCORE_TOP1":
        return (pred.get("markets", {}).get("SCORE") or {}).get("top1_hit")
    if market == "SCORE_TOP3":
        return (pred.get("markets", {}).get("SCORE") or {}).get("top3_hit")
    if market == "TOTAL_GOALS":
        return (pred.get("markets", {}).get("TOTAL_GOALS") or {}).get("hit")
    if market == "HALF_FULL":
        return (pred.get("markets", {}).get("HALF_FULL") or {}).get("hit")
    layer = {"HAD_DC": "DC", "HAD_ELO": "Elo", "HAD_ML": "ML"}.get(market)
    return (pred.get("model_layers", {}).get(layer) or {}).get("hit") if layer else None


def _market_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for market in MARKET_KEYS:
        vals = [v for v in (_hit(r, market) for r in records) if v is not None]
        hits = sum(1 for v in vals if v)
        n = len(vals)
        out[market] = {
            "n": n,
            "hits": hits,
            "accuracy": (hits / n) if n else None,
        }
    return out


def _value_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    bets = [b for r in records
            for b in (r.get("prediction") or {}).get("value_bets", [])
            if b.get("hit") is not None]
    n = len(bets)
    hits = sum(1 for b in bets if b.get("hit"))
    pnl_unit = sum(float(b.get("pnl_unit") or 0.0) for b in bets)
    pnl_pct = sum(float(b.get("pnl_pct") or 0.0) for b in bets)
    staked_pct = sum(float(b.get("stake_pct") or 0.0) for b in bets)
    return {
        "n": n,
        "hits": hits,
        "hit_rate": (hits / n) if n else None,
        "pnl_unit": round(pnl_unit, 4),
        "pnl_pct": round(pnl_pct, 6),
        "staked_pct": round(staked_pct, 6),
        "roi": (pnl_unit / n) if n else None,
    }


def _stats_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """只统计赛前预测且已结算的场次。"""
    return [r for r in records
            if r.get("status") == "settled"
            and r.get("prediction_timing") == "pre_match"]


def _date_summary(date: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    predicted = [r for r in records if r.get("status") != "skipped"]
    settled = [r for r in predicted if r.get("status") == "settled"]
    valid = _stats_records(records)
    return {
        "date": date,
        "total": len(records),
        "predicted": len(predicted),
        "settled": len(settled),
        "pending": sum(1 for r in predicted if r.get("status") == "pending"),
        "skipped": sum(1 for r in records if r.get("status") == "skipped"),
        "post_kickoff": sum(1 for r in predicted
                            if r.get("prediction_timing") == "post_kickoff"),
        "value_bets": sum(len((r.get("prediction") or {}).get("value_bets", []))
                          for r in predicted),
        "markets": _market_stats(valid),
        "value": _value_stats(valid),
    }


def _aggregate(all_records: list[dict[str, Any]],
               daily: list[dict[str, Any]],
               ledger_path: Path) -> dict[str, Any]:
    valid = _stats_records(all_records)
    predicted = [r for r in all_records if r.get("status") != "skipped"]
    by_league: dict[str, Any] = {}
    for rec in all_records:
        div = (rec.get("league") or {}).get("div") or "OTHER"
        by_league.setdefault(div, {"div": div, "name": (rec.get("league") or {}).get("name"),
                                   "records": []})["records"].append(rec)
    league_out = []
    for div, bucket in sorted(by_league.items()):
        recs = bucket["records"]
        v = _stats_records(recs)
        league_out.append({
            "div": div,
            "name": bucket["name"],
            "total": len(recs),
            "predicted": sum(1 for r in recs if r.get("status") != "skipped"),
            "settled": sum(1 for r in recs if r.get("status") == "settled"),
            "markets": _market_stats(v),
            "value": _value_stats(v),
        })

    ledger: list[dict[str, Any]] = []
    if ledger_path.exists():
        try:
            df = pd.read_parquet(ledger_path)
            if "date" in df.columns:
                df["date"] = df["date"].astype(str)
            ledger = _clean(df.to_dict(orient="records"))
        except Exception:  # noqa: BLE001
            ledger = []

    return {
        "generated_at": _now_iso(),
        "overall": {
            "total": len(all_records),
            "predicted": len(predicted),
            "settled": sum(1 for r in predicted if r.get("status") == "settled"),
            "pending": sum(1 for r in predicted if r.get("status") == "pending"),
            "skipped": sum(1 for r in all_records if r.get("status") == "skipped"),
            "post_kickoff": sum(1 for r in predicted
                                if r.get("prediction_timing") == "post_kickoff"),
            "stats_settled": len(valid),
            "markets": _market_stats(valid),
            "value": _value_stats(valid),
        },
        "by_league": league_out,
        "daily": daily,
        "ledger": ledger,
        "note": "命中率只统计赛前预测且已结算的场次；赛后补跑或已开赛预测不计入。",
    }


# --------------------------------------------------------------------------- #
# 推荐 / 赔率变化 / 回测
# --------------------------------------------------------------------------- #
def _recommendations(selected: list[dict[str, Any]], date: str,
                     settings: Any, official_path: Path) -> dict[str, Any]:
    rows = [item["p"] for item in selected if not item["p"].get("skipped")]
    risks = ["conservative", "balanced", "aggressive"]
    payload: dict[str, Any] = {
        "date": date,
        "generated_at": _now_iso(),
        "source": "derived",
        "risks": {},
    }
    for risk in risks:
        cfg = settings.recommend_for(risk)
        result = run_recommend(rows, cfg)
        payload["risks"][risk] = {
            "risk": risk,
            **result,
        }
    official = _read_json(official_path) if official_path.exists() else None
    if official:
        payload["official"] = official
    return payload


def _recommendation_index(date: str, payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"date": date, "risks": {}}
    for risk, result in payload.get("risks", {}).items():
        out["risks"][risk] = {
            "recommendations": len(result.get("recommendations", [])),
            "observations": len(result.get("observations", [])),
            "total_stake_pct": result.get("total_stake_pct", 0),
        }
    return out


def _odds_diff(odds_dir: Path) -> list[dict[str, Any]]:
    groups: dict[str, list[Path]] = {}
    for path in sorted(odds_dir.glob("jc_odds_*.json")):
        match = re.search(r"jc_odds_(\d{8})", path.stem)
        if match:
            groups.setdefault(match.group(1), []).append(path)

    out: list[dict[str, Any]] = []
    for date_tag, paths in groups.items():
        if len(paths) < 2:
            continue
        snaps = []
        for path in paths:
            data = _read_json(path)
            if isinstance(data, list):
                fetched = ""
                if data:
                    fetched = str(data[0].get("fetched_at") or "")
                snaps.append({"path": path, "fetched_at": fetched, "matches": data})
        if len(snaps) < 2:
            continue
        snaps.sort(key=lambda x: (_parse_dt(x["fetched_at"])
                                  or datetime.fromtimestamp(x["path"].stat().st_mtime)))
        first, last = snaps[0], snaps[-1]
        first_map = {str(m.get("match_id") or m.get("match_num")): m
                     for m in first["matches"]}
        diffs = []
        for m in last["matches"]:
            key = str(m.get("match_id") or m.get("match_num"))
            old = first_map.get(key)
            if not old:
                continue
            item: dict[str, Any] = {
                "match_num": m.get("match_num"),
                "match_id": m.get("match_id"),
                "home_cn": m.get("home_cn"),
                "away_cn": m.get("away_cn"),
                "had": {},
                "hhad": {},
            }
            for market, field in (("had", "had_odds"), ("hhad", "hhad_odds")):
                old_odds = old.get(field) or {}
                new_odds = m.get(field) or {}
                for option in ("home", "draw", "away"):
                    a, b = _num(old_odds.get(option)), _num(new_odds.get(option))
                    if a is None or b is None:
                        continue
                    item[market][option] = {
                        "from": a,
                        "to": b,
                        "delta": round(b - a, 4),
                        "delta_pct": round((b / a - 1) * 100, 2) if a else None,
                    }
            item["line"] = _num(m.get("hhad_goal_line"))
            diffs.append(item)
        if diffs:
            out.append({
                "date": f"{date_tag[:4]}-{date_tag[4:6]}-{date_tag[6:]}",
                "snapshots": [
                    {"file": s["path"].name, "fetched_at": s["fetched_at"]}
                    for s in snaps
                ],
                "matches": diffs,
            })
    return out


def _equity_curve(predictions: list[dict[str, Any]],
                  threshold: float = 0.0) -> list[dict[str, Any]]:
    if not predictions:
        return []
    step = max(1, len(predictions) // 400)
    curve: list[dict[str, Any]] = []
    equity = 0.0
    bets = 0
    for i, row in enumerate(predictions):
        probs = [_num(row.get("p_home")), _num(row.get("p_draw")), _num(row.get("p_away"))]
        odds = [_num(row.get("odds_home")), _num(row.get("odds_draw")), _num(row.get("odds_away"))]
        actual = row.get("actual")
        idx = {"H": 0, "D": 1, "A": 2}.get(actual, -1)
        day_pnl = 0.0
        for j in range(3):
            if probs[j] is None or odds[j] is None or odds[j] <= 1.0:
                continue
            ev = probs[j] * odds[j] - 1.0
            if ev <= threshold:
                continue
            bets += 1
            day_pnl += (odds[j] - 1.0) if j == idx else -1.0
        equity += day_pnl
        if i % step == 0 or i == len(predictions) - 1:
            curve.append({
                "i": i + 1,
                "date": row.get("date"),
                "equity": round(equity, 2),
                "bets": bets,
            })
    return curve


def _export_backtests(reports_dir: Path, out_dir: Path) -> list[dict[str, Any]]:
    index: list[dict[str, Any]] = []
    for path in sorted(reports_dir.glob("backtest_*.json")):
        data = _read_json(path)
        if not data or "overall" not in data:
            continue
        ident = path.stem.replace("backtest_", "")
        if ident and ident[0].isdigit():
            label = "全部联赛"
        else:
            label = ident.split("_")[0]
        overall = data.get("overall") or {}
        config = data.get("config") or {}
        curve = _equity_curve(data.get("predictions") or [],
                              float(config.get("ev_threshold") or 0.0))
        summary = {
            "id": ident,
            "label": label,
            "generated_at": data.get("generated_at"),
            "config": config,
            "overall": overall,
            "per_league": data.get("per_league") or {},
            "equity_curve": curve,
        }
        _write_json(out_dir / "backtests" / f"{ident}.json", summary)
        betting = overall.get("betting") or {}
        index.append({
            "id": ident,
            "label": label,
            "generated_at": data.get("generated_at"),
            "n": overall.get("n"),
            "accuracy": overall.get("accuracy"),
            "log_loss": overall.get("log_loss"),
            "brier": overall.get("brier"),
            "has_odds": overall.get("has_odds"),
            "roi": betting.get("roi"),
            "file": f"backtests/{ident}.json",
        })
    index.sort(key=lambda x: str(x.get("generated_at") or ""), reverse=True)
    _write_json(out_dir / "backtests" / "index.json", index)
    return index


# --------------------------------------------------------------------------- #
# 联赛与 manifest
# --------------------------------------------------------------------------- #
def _leagues(models_dir: Path) -> list[dict[str, Any]]:
    lg = get_leagues()
    out: dict[str, dict[str, Any]] = {}

    def add(div: str, name: str, country: str = "", tier: Any = None) -> None:
        out[div] = {
            "div": div,
            "name": name,
            "country": country,
            "tier": tier,
            "has_model": ((models_dir / div / "dc.json").exists()
                          or (div in ("UCL", "UEL", "CONF")
                              and (models_dir / "EUR" / "dc.json").exists())),
        }

    for div, info in lg.tier1.items():
        add(div, info.get("name", div), info.get("country", ""), info.get("tier"))
    for div, info in lg.extra.items():
        add(div, info.get("name", div), info.get("country", ""), 1)
    for div, info in lg.model_groups.items():
        add(div, info.get("name", div), "欧足联", 1)
    for _id, info in lg.tier2.items():
        if info.get("div"):
            add(info["div"], info.get("name", info["div"]), info.get("country", ""), 2)
    return sorted(out.values(), key=lambda x: (x["name"], x["div"]))


def _manifest(all_records: list[dict[str, Any]], daily: list[dict[str, Any]],
              sources: list[str], league_rows: list[dict[str, Any]]) -> dict[str, Any]:
    dates = [d["date"] for d in daily if d.get("date")]
    latest_match = max(dates) if dates else None
    pred_dates = [d["date"] for d in daily if d.get("predicted", 0) > 0]
    latest_pred = max(pred_dates) if pred_dates else None
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "site": {
            "name": "竞彩预测实验室",
            "tagline": "用数据看球 · 研究用途 · 不构成投注建议",
        },
        "latest_match_date": latest_match,
        "latest_prediction_date": latest_pred,
        "counts": {
            "matches": len(all_records),
            "predicted": sum(1 for r in all_records if r.get("status") != "skipped"),
            "settled": sum(1 for r in all_records if r.get("status") == "settled"),
            "pending": sum(1 for r in all_records if r.get("status") == "pending"),
            "skipped": sum(1 for r in all_records if r.get("status") == "skipped"),
            "value_bets": sum(len((r.get("prediction") or {}).get("value_bets", []))
                              for r in all_records),
            "dates": len(daily),
        },
        "dates": daily,
        "leagues": league_rows,
        "sources": sorted(set(sources)),
        "disclaimer": DISCLAIMER,
    }


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def build_site_data(out_dir: str | Path,
                    reports_dir: str | Path | None = None,
                    odds_dir: str | Path | None = None,
                    processed_dir: str | Path | None = None,
                    models_dir: str | Path | None = None,
                    manual_path: str | Path | None = None,
                    include_backtests: bool = True,
                    result_index: dict[tuple, dict[str, Any]] | None = None
                    ) -> dict[str, Any]:
    """生成完整站点数据，返回摘要（供 CLI 打印/测试断言）。"""
    settings = get_settings()
    reports = Path(reports_dir) if reports_dir else settings.reports_dir
    odds = Path(odds_dir) if odds_dir else settings.odds_dir
    processed = Path(processed_dir) if processed_dir else settings.processed_dir
    models = Path(models_dir) if models_dir else settings.models_dir
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    manual_file = Path(manual_path) if manual_path else (
        PROJECT_ROOT / "data" / "manual_results" / "results.csv")
    manual = load_manual_results(manual_file) if manual_file.exists() else {}
    index = result_index if result_index is not None else load_result_index()
    leagues = get_leagues()

    files = _load_prediction_files(reports)
    if not files:
        raise RuntimeError(f"没有找到预测报告: {reports}/predict_*.json")

    dates = sorted({f["date_tag"] for f in files if f["date_tag"]})
    all_records: list[dict[str, Any]] = []
    daily: list[dict[str, Any]] = []
    rec_index: list[dict[str, Any]] = []
    sources: list[str] = []

    for date_tag in dates:
        selected = _select_for_date(files, date_tag)
        if not selected:
            continue
        preds = [item["p"] for item in selected if not item["p"].get("skipped")]
        settled = {r["match_num"]: r for r in reconcile_predictions(preds, index, manual)}
        records = []
        for item in selected:
            p = item["p"]
            source = item["meta"]["source"]
            sources.append(source)
            settlement = settled.get(str(p.get("match_num"))) if not p.get("skipped") else None
            skipped_result = _find_result_for_skipped(p, manual, index) if p.get("skipped") else None
            records.append(_match_record(item, settlement, skipped_result, leagues))

        date = f"{date_tag[:4]}-{date_tag[4:6]}-{date_tag[6:]}"
        _write_json(out / "history" / f"{date}.json", records)
        summary = _date_summary(date, records)
        daily.append(summary)
        all_records.extend(records)

        rec_payload = _recommendations(
            selected, date, settings, reports / f"recommend_{date_tag}.json")
        _write_json(out / "recommendations" / f"{date}.json", rec_payload)
        rec_index.append(_recommendation_index(date, rec_payload))

    daily.sort(key=lambda x: x["date"])
    all_records.sort(key=lambda r: (str(r.get("date") or ""), str(r.get("kickoff") or "")))
    _write_json(out / "history" / "index.json", daily)
    _write_json(out / "recommendations" / "index.json", rec_index)

    diffs = _odds_diff(odds)
    for item in diffs:
        _write_json(out / "odds-diff" / f"{item['date']}.json", item)
    _write_json(out / "odds-diff" / "index.json",
                [{"date": d["date"],
                  "snapshots": len(d["snapshots"]),
                  "matches": len(d["matches"])} for d in diffs])

    backtest_index = _export_backtests(reports, out) if include_backtests else []
    performance = _aggregate(all_records, daily,
                             processed / "bet_ledger.parquet")
    _write_json(out / "performance.json", performance)

    league_rows = _leagues(models)
    manifest = _manifest(all_records, daily, sources, league_rows)
    _write_json(out / "manifest.json", manifest)

    return {
        "out": str(out),
        "dates": len(dates),
        "matches": len(all_records),
        "settled": manifest["counts"]["settled"],
        "recommendations": sum(r["risks"]["conservative"]["recommendations"]
                               for r in rec_index),
        "backtests": len(backtest_index),
        "odds_diff_dates": len(diffs),
        "manifest": manifest,
        "performance": performance,
    }


# --------------------------------------------------------------------------- #
# 校验与 CLI
# --------------------------------------------------------------------------- #
def check_output(out_dir: str | Path) -> int:
    out = Path(out_dir)
    if not (out / "manifest.json").exists():
        raise RuntimeError(f"缺少 manifest.json: {out}")
    count = 0

    def reject_constant(value: str) -> None:
        raise ValueError(f"非法 JSON 常量: {value}")

    for path in out.rglob("*.json"):
        json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
        count += 1
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="把本地预测/对账/回测报告导出为站点 JSON")
    parser.add_argument("--out", default="web/public/data",
                        help="输出目录（默认 web/public/data）")
    parser.add_argument("--reports", default=None, help="报告目录")
    parser.add_argument("--odds", default=None, help="赔率快照目录")
    parser.add_argument("--processed", default=None, help="processed 数据目录")
    parser.add_argument("--models", default=None, help="模型目录")
    parser.add_argument("--manual", default=None, help="手动赛果 CSV")
    parser.add_argument("--no-backtests", action="store_true",
                        help="不导出回测")
    parser.add_argument("--check", action="store_true",
                        help="导出后校验所有 JSON 可解析且无 NaN")
    args = parser.parse_args(argv)

    out = Path(args.out)
    if not out.is_absolute():
        out = PROJECT_ROOT / out
    summary = build_site_data(
        out_dir=out,
        reports_dir=args.reports,
        odds_dir=args.odds,
        processed_dir=args.processed,
        models_dir=args.models,
        manual_path=args.manual,
        include_backtests=not args.no_backtests,
    )
    if args.check:
        count = check_output(out)
        print(f"JSON 校验通过：{count} 个文件")

    print(f"导出完成：{summary['out']}")
    print(f"  日期：{summary['dates']}，比赛：{summary['matches']}，"
          f"已结算：{summary['settled']}")
    print(f"  候选注：{summary['recommendations']}，回测：{summary['backtests']}，"
          f"赔率对比日期：{summary['odds_diff_dates']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
