"""端到端编排：把 ingest / models / jingcai 串成可复用流程。

对外提供三层能力，供 CLI、回测、可视化复用：
    load_training_data()          读取训练数据（优先 processed parquet，离线）
    build_matcher()               构造队名匹配器
    train_leagues()               逐联赛拟合 DC(+半全场) 并可落盘
    load_models()                 从 data/models 载入已训练模型
    predict_matches()             对竞彩场次做预测 + 价值判断
    write_report()                预测结果双写 Markdown + JSON
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import get_leagues, get_settings
from src.ingest.footballdata import load_processed, load_tier1, save_processed
from src.ingest.jingcai_scraper import TTG_BUCKETS
from src.jingcai import payouts as pay
from src.jingcai.team_names import (TeamMatcher, _norm,
                                    build_known_names_from_data,
                                    default_cache_path)
from src.models import dixon_coles as dc
from src.models import halffull
from src.models.persistence import load_dc, load_hf, save_dc, save_hf
from src.features import elo
from src.features import features as feat
from src.models import ml_model

# 无模型或未匹配时的占位
HAD_KEYS = ["胜", "平", "负"]

# 竞彩赔率字段 -> 胜平负标签
_ODDS_LABELS = {"home": "胜", "draw": "平", "away": "负"}

# 已知队名拼写错误/变体 -> 规范名（在统一队名时归并，避免实体分裂）
TEAM_TYPO_ALIASES = {
    "Villareal": "Villarreal",   # football-data 拼写错误
    "M'Gladbach": "M'gladbach",  # 统一撇号写法
}


# --------------------------------------------------------------------------- #
# 数据 / 匹配器
# --------------------------------------------------------------------------- #
def _unify_team_names(df: pd.DataFrame) -> pd.DataFrame:
    """合并同一队的拼写变体，避免实体分裂。

    跨数据源/跨赛季存在同一队的不同写法（实测如 ``M'Gladbach`` 34 场 vs
    ``M'gladbach`` 1006 场）：分裂后匹配器可能挑中**模型里没有**的那个拼写，
    导致「球队无历史数据」误跳过。统一取出现次数最多的拼写。

    另有已知拼写错误（如 football-data 里的 ``Villareal``）通过
    ``TEAM_TYPO_ALIASES`` 显式归并。
    """
    from collections import Counter

    if TEAM_TYPO_ALIASES:
        df = df.copy()
        for col in ("home_team", "away_team"):
            df[col] = df[col].replace(TEAM_TYPO_ALIASES)

    counts: Counter = Counter()
    for col in ("home_team", "away_team"):
        counts.update(df[col].dropna())
    best: dict[str, tuple[str, int]] = {}
    for name, n in counts.items():
        key = _norm(name)
        cur = best.get(key)
        if cur is None or n > cur[1] or (n == cur[1] and name < cur[0]):
            best[key] = (name, n)
    remap = {name: best[_norm(name)][0] for name in counts
             if name != best[_norm(name)][0]}
    if not remap:
        return df
    df = df.copy()
    df["home_team"] = df["home_team"].replace(remap)
    df["away_team"] = df["away_team"].replace(remap)
    return df


def load_training_data() -> pd.DataFrame:
    """优先读取 processed parquet；缺失时回落到镜像并顺手落盘。

    若已抓取额外赛事数据（ucl/uel/conf_matches.parquet），一并合并进来；
    并统一同一队的拼写变体（见 ``_unify_team_names``）。
    若已抓取 understat 数据（understat_matches.parquet），也把其中
    **已完成且不晚于今天**的五大联赛场次并入，用于补齐 football-data
    镜像缺失的最新赛季（镜像停在 2026-05，understat 可补到当前）。
    """
    try:
        df = load_processed("tier1_matches")
    except FileNotFoundError:
        df = load_tier1()
        if not df.empty:
            save_processed(df)

    extras: list[pd.DataFrame] = []
    for name in get_leagues().extra_datasets:
        try:
            sub = load_processed(name)
        except FileNotFoundError:
            continue
        if sub is not None and not sub.empty:
            extras.append(sub)
    if extras:
        df = pd.concat([df, *extras], ignore_index=True)

    # 扩联赛覆盖：jokecamp 镜像解析出的更多联赛比分（如荷甲/葡超/苏超等）
    gh = _load_tier1_gh_new(df)
    if gh is not None and not gh.empty:
        df = pd.concat([df, gh], ignore_index=True)

    u = _load_understat_new(df)
    if u is not None and not u.empty:
        df = pd.concat([df, u], ignore_index=True)

    af = _load_apifootball_new(df)
    if af is not None and not af.empty:
        df = pd.concat([df, af], ignore_index=True)

    df = _join_understat_xg(df)

    return _unify_team_names(df)


def _load_apifootball_new(df: pd.DataFrame) -> pd.DataFrame | None:
    """加载 API-Football 赛果（apifootball_matches），按主键去重后合并。"""
    try:
        af = load_processed("apifootball_matches")
    except FileNotFoundError:
        return None
    if af is None or af.empty:
        return None
    af = af.dropna(subset=["ft_home", "ft_away"]).copy()
    cols = ["league_code", "date", "home_team", "away_team", "ft_home", "ft_away"]
    for c in ("ht_home", "ht_away"):
        if c in af.columns:
            cols.append(c)
    af = af[[c for c in cols if c in af.columns]]
    if not df.empty:
        existing = set(zip(
            df["league_code"].astype(str),
            pd.to_datetime(df["date"]).dt.normalize().astype(str),
            df["home_team"].map(_norm),
            df["away_team"].map(_norm),
        ))

        def _is_new(r: pd.Series) -> bool:
            key = (str(r.league_code), pd.Timestamp(r.date).strftime("%Y-%m-%d"),
                   _norm(r.home_team), _norm(r.away_team))
            return key not in existing

        af = af[af.apply(_is_new, axis=1)]
    return af


def _join_understat_xg(df: pd.DataFrame) -> pd.DataFrame:
    """把 understat 的 xG 按主键左连接回比赛表（补全五大联赛 2014+ 的 xG）。

    understat 只有五大联赛+俄超 2014 起有 xG；tier1 主数据源无 xG 列，
    故这里单独左连接，未命中的行为 NaN（LightGBM 原生处理 NaN）。
    """
    from src.ingest.understat import normalize_team

    try:
        u = load_processed("understat_matches")
    except FileNotFoundError:
        return df
    u = u.dropna(subset=["xg_home", "xg_away"]).copy()
    if u.empty:
        return df
    u["home_team"] = u["home_team"].map(normalize_team)
    u["away_team"] = u["away_team"].map(normalize_team)
    u = u[["league_code", "date", "home_team", "away_team", "xg_home", "xg_away"]].copy()
    u["date"] = pd.to_datetime(u["date"]).dt.normalize()
    u = u.rename(columns={"date": "_d", "xg_home": "xg_home_u", "xg_away": "xg_away_u"})

    df = df.copy()
    df["_d"] = pd.to_datetime(df["date"]).dt.normalize()
    merged = df.merge(u, on=["league_code", "_d", "home_team", "away_team"],
                      how="left")
    if "xg_home" in merged.columns:
        merged["xg_home"] = merged["xg_home"].fillna(merged["xg_home_u"])
        merged["xg_away"] = merged["xg_away"].fillna(merged["xg_away_u"])
    else:
        merged["xg_home"] = merged["xg_home_u"]
        merged["xg_away"] = merged["xg_away_u"]
    merged = merged.drop(columns=["xg_home_u", "xg_away_u", "_d"])
    return merged


def _load_tier1_gh_new(df: pd.DataFrame) -> pd.DataFrame | None:
    """加载 jokecamp 镜像解析出的比赛表（tier1_gh_matches），
    按 (联赛, 日期, 归一化队名) 与现有数据去重，只补新增。"""
    try:
        gh = load_processed("tier1_gh_matches")
    except FileNotFoundError:
        return None
    if gh is None or gh.empty:
        return None
    gh = gh.dropna(subset=["ft_home", "ft_away"]).copy()
    need = ["league_code", "date", "home_team", "away_team", "ft_home", "ft_away"]
    gh = gh[[c for c in need if c in gh.columns]]
    if not df.empty:
        existing = set(zip(
            df["league_code"].astype(str),
            pd.to_datetime(df["date"]).dt.normalize().astype(str),
            df["home_team"].map(_norm),
            df["away_team"].map(_norm),
        ))

        def _is_new(r: pd.Series) -> bool:
            key = (str(r.league_code), pd.Timestamp(r.date).strftime("%Y-%m-%d"),
                   _norm(r.home_team), _norm(r.away_team))
            return key not in existing

        gh = gh[gh.apply(_is_new, axis=1)]
    return gh


def _load_understat_new(df: pd.DataFrame) -> pd.DataFrame | None:
    """加载 understat 中「已完成、不晚于今天、且主键不与现有数据重复」的场次。

    返回与 tier1 同 schema 的 DataFrame（只含训练所需列）；无数据返回 None。
    """
    from src.ingest.understat import normalize_team

    try:
        u = load_processed("understat_matches")
    except FileNotFoundError:
        return None
    if u is None or u.empty:
        return None

    u = u.dropna(subset=["ft_home", "ft_away"]).copy()
    if u.empty:
        return None
    # 防未来数据泄漏：只保留不晚于今天的已完赛场次
    today = pd.Timestamp.now().normalize()
    u["_d"] = pd.to_datetime(u["date"], errors="coerce")
    u = u[u["_d"].notna() & (u["_d"] <= today)]
    u["date"] = u["_d"]
    u = u.drop(columns=["_d"])
    # 只保留五大联赛（RUS1 等不在本项目覆盖内）
    tier1_codes = set(get_leagues().tier1)
    u = u[u["league_code"].isin(tier1_codes)]
    if u.empty:
        return None
    # 归一化队名到 football-data 口径
    u["home_team"] = u["home_team"].map(normalize_team)
    u["away_team"] = u["away_team"].map(normalize_team)
    cols = ["league_code", "date", "home_team", "away_team", "ft_home", "ft_away"]
    # xG 列（若有）一并保留，供特征模型使用；非 understat 行后续自动为 NaN
    for c in ("xg_home", "xg_away"):
        if c in u.columns:
            cols.append(c)
    u = u[cols]

    # 与现有数据按 (联赛, 日期, 归一化队名) 去重，只补新增
    if not df.empty:
        existing = set(zip(
            df["league_code"].astype(str),
            pd.to_datetime(df["date"]).dt.normalize().astype(str),
            df["home_team"].map(_norm),
            df["away_team"].map(_norm),
        ))

        def _is_new(r: pd.Series) -> bool:
            key = (str(r.league_code), pd.Timestamp(r.date).strftime("%Y-%m-%d"),
                   _norm(r.home_team), _norm(r.away_team))
            return key not in existing

        u = u[u.apply(_is_new, axis=1)]
    return u


def build_matcher(df: pd.DataFrame | None = None) -> TeamMatcher:
    """用历史数据中的队名构造队名匹配器（带匹配缓存）。"""
    df = load_training_data() if df is None else df
    return TeamMatcher(build_known_names_from_data(df),
                       cache_path=default_cache_path())


# --------------------------------------------------------------------------- #
# 训练 / 载入
# --------------------------------------------------------------------------- #
def train_leagues(leagues: list[str] | None = None,
                  years: int | None = None,
                  half_life: float | None = None,
                  shrinkage_prior: float | None = None,
                  with_ml: bool = False,
                  save: bool = True,
                  verbose: bool = True) -> dict[str, dict[str, Any]]:
    """逐联赛拟合 Dixon-Coles(+半全场+Elo[+ML])，返回 {div: {dc, hf, elo[, ml]}}。

    years / half_life / shrinkage_prior 为 None 时使用 settings.yaml 的默认值，
    并按 ``training.overrides`` 对特定联赛（如 UCL / EUR）单独覆盖；
    覆盖里 ``years: null`` 表示窗口跟数据走（用全部历史）。

    ``div`` 命中 leagues.yaml 的 ``model_groups``（如 EUR）时，
    按其 ``members`` 合并多个联赛的数据训练**一个**模型。

    除 DC 外，还拟合一个 Elo 模型（同窗口数据）作为第二意见；``with_ml=True``
    时再拟合一个 LightGBM 特征模型（滚动特征，第三意见），供预测时混合。
    """
    settings = get_settings()
    settings.ensure_dirs()
    data = load_training_data()
    if data.empty:
        raise RuntimeError("训练数据为空，请先运行 fetch-tier1")

    groups = get_leagues().model_groups
    if leagues is None:
        leagues = sorted(data["league_code"].dropna().unique())
        leagues += [g for g in groups if g not in leagues]

    overrides = settings.training_overrides
    global_years = 5
    global_half_life = float(settings.dc_half_life_days)
    global_shrink = float(settings.shrinkage_prior)

    result: dict[str, dict[str, Any]] = {}
    for div in leagues:
        if div in groups:
            members = [str(m) for m in groups[div]["members"]]
            sub = data[data["league_code"].isin(members)]
        else:
            sub = data[data["league_code"] == div]
        if sub.empty:
            if verbose:
                print(f"  [跳过] {div}: 无数据")
            continue

        ov = overrides.get(div, {})
        if years is not None:
            y = int(years)
        elif "years" in ov:
            y = None if ov["years"] is None else int(ov["years"])
        else:
            y = int(global_years)
        hl = (float(half_life) if half_life is not None
              else float(ov.get("half_life", global_half_life)))
        sh = (float(shrinkage_prior) if shrinkage_prior is not None
              else float(ov.get("shrinkage_prior", global_shrink)))
        min_matches = int(ov.get("min_matches", 100))

        if y is None:
            train = sub  # 窗口跟数据走：不限年限
        else:
            cutoff = sub["date"].max() - pd.Timedelta(days=365 * y)
            train = sub[sub["date"] >= cutoff]
        if len(train) < min_matches:
            if verbose:
                print(f"  [跳过] {div}: 样本不足 ({len(train)} 场)")
            continue
        try:
            dc_model = dc.fit(train, half_life_days=hl, shrinkage_prior=sh)
        except Exception as e:  # noqa: BLE001
            if verbose:
                print(f"  [失败] {div}: {e}")
            continue

        hf_model: halffull.HalfFullModel | None = None
        try:
            hf_model = halffull.fit(train,
                                    alpha_full=dc_model.attack,
                                    defense_full=dc_model.defense)
        except Exception as e:  # noqa: BLE001
            if verbose:
                print(f"  [半全场跳过] {div}: {e}")

        elo_model: elo.EloModel | None = None
        try:
            elo_model = elo.EloModel().fit(train)
        except Exception as e:  # noqa: BLE001
            if verbose:
                print(f"  [Elo跳过] {div}: {e}")

        ml_model_obj: ml_model.MLModel | None = None
        if with_ml:
            try:
                rf = feat.RollingFeatures()
                X_ml, y_ml = rf.fit_features(train)
                if len(X_ml) >= 300:
                    ml_model_obj = ml_model.MLModel().fit(X_ml, y_ml)
                elif verbose:
                    print(f"  [ML跳过] {div}: 样本不足 ({len(X_ml)} 场)")
            except Exception as e:  # noqa: BLE001
                if verbose:
                    print(f"  [ML失败] {div}: {e}")

        if save:
            save_dc(dc_model, settings.models_dir / div / "dc.json")
            if hf_model is not None:
                save_hf(hf_model, settings.models_dir / div / "halffull.json")
            if elo_model is not None:
                elo.save(elo_model, settings.models_dir / div / "elo.json")
            if ml_model_obj is not None:
                ml_model.save(ml_model_obj, settings.models_dir / div / "ml.joblib")

        result[div] = {"dc": dc_model, "hf": hf_model, "elo": elo_model,
                       "ml": ml_model_obj}
        if verbose:
            name = get_leagues().name_of(div)
            window = "全部历史" if y is None else f"近{y}年"
            print(f"  {div}({name}): {len(train)} 场, {window}/半衰期{hl:.0f}天, "
                  f"收缩{sh:.0f}场, 收敛={dc_model.converged}, "
                  f"LL={dc_model.log_likelihood:.1f}, "
                  f"半全场={'有' if hf_model else '无'}, "
                  f"Elo={'有' if elo_model else '无'}, "
                  f"ML={'有' if ml_model_obj else '无'}")
    return result


def load_models(leagues: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """从 data/models 载入已训练模型，返回 {div: {dc, hf}}。"""
    settings = get_settings()
    root = settings.models_dir
    if not root.exists():
        return {}
    if leagues is None:
        leagues = sorted(p.name for p in root.iterdir() if p.is_dir())

    out: dict[str, dict[str, Any]] = {}
    for div in leagues:
        dc_path = root / div / "dc.json"
        if not dc_path.exists():
            continue
        hf_path = root / div / "halffull.json"
        elo_path = root / div / "elo.json"
        ml_path = root / div / "ml.joblib"
        out[div] = {
            "dc": load_dc(dc_path),
            "hf": load_hf(hf_path) if hf_path.exists() else None,
            "elo": elo.load(elo_path) if elo_path.exists() else None,
            "ml": ml_model.load_model(ml_path) if ml_path.exists() else None,
        }
    return out


def list_trained() -> list[str]:
    """返回已训练模型的联赛代码列表。"""
    return sorted(load_models().keys())


# --------------------------------------------------------------------------- #
# 预测
# --------------------------------------------------------------------------- #
def _value_bets(model_probs: dict[str, float], odds: dict[str, float],
                edge_threshold: float, kelly_fraction: float,
                max_stake_pct: float, min_odds: float = 0.0,
                max_edge: float = float("inf")) -> list[dict[str, Any]]:
    """在单一玩法上计算价值选项（含建议仓位与过滤）。"""
    vb = pay.value_bets(model_probs, odds, edge_threshold=edge_threshold,
                        min_odds=min_odds, max_edge=max_edge)
    for b in vb:
        b["stake_pct"] = pay.kelly_stake(b["edge"], b["odds"], b["model_prob"],
                                         kelly_fraction, max_stake_pct)
    return vb


def _top_exact_scores(matrix, n: int = 3) -> list[dict[str, Any]]:
    """比分矩阵中概率最高的 n 个**精确**比分（排除 "1+:胜" 这类归并桶）。"""
    items = [(f"{h}:{a}", float(matrix[h, a]))
             for h in range(matrix.shape[0])
             for a in range(matrix.shape[1])]
    items.sort(key=lambda x: -x[1])
    return [{"score": s, "prob": p} for s, p in items[:n]]


def match_kickoff(date_str: Any, time_str: Any) -> datetime | None:
    """把竞彩的 match_date / match_time 解析成本地开赛时间。

    time 缺失时返回 None（视为未知，不据此跳过）。
    """
    if not date_str:
        return None
    if not time_str:
        return None
    text = f"{str(date_str).strip()} {str(time_str).strip()}"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def select_prediction_report(date_tag: str) -> Path | None:
    """为某个销售日选择「赛前最后一次」预测报告。

    优先从 reports/archive/ 与主报告里挑：
        1. 生成时间早于本场最早开赛时间的报告，取最新一份；
        2. 若没有赛前报告，取最早的一份赛后报告（仅展示，不应计入命中率）。

    这样即使赛后重跑 predict 覆盖了主报告，对账仍能使用赛前版本。
    """
    settings = get_settings()
    candidates = [settings.reports_dir / f"predict_{date_tag}.json"]
    archive = settings.reports_dir / "archive"
    if archive.exists():
        candidates += sorted(archive.glob(f"predict_{date_tag}_*.json"))

    best: Path | None = None
    best_score: tuple[float, float] | None = None
    for path in candidates:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        preds = [p for p in data.get("predictions", []) if not p.get("skipped")]
        if not preds:
            continue
        generated = data.get("generated_at")
        try:
            gen_dt = (datetime.fromisoformat(str(generated).replace("Z", "+00:00"))
                      .replace(tzinfo=None))
        except (TypeError, ValueError):
            gen_dt = datetime.fromtimestamp(path.stat().st_mtime)
        kickoffs = [k for k in (match_kickoff(p.get("match_date"),
                                              p.get("match_time")) for p in preds)
                    if k is not None]
        earliest = min(kickoffs) if kickoffs else None
        if earliest is None:
            score = (1.5, gen_dt.timestamp())
        elif gen_dt <= earliest:
            score = (2.0, gen_dt.timestamp())
        else:
            score = (0.0, -gen_dt.timestamp())
        if best_score is None or score > best_score:
            best, best_score = path, score
    return best





def predict_matches(matches: list, models: dict[str, dict[str, Any]],
                    matcher: TeamMatcher,
                    edge_threshold: float = 0.05,
                    kelly_fraction: float = 0.25,
                    max_stake_pct: float = 0.02,
                    crs_top: int = 3,
                    skip_started: bool = False,
                    blend_weight: float = 0.6,
                    elo_blend_weight: float = 0.8,
                    ml_blend_weight: float = 0.8,
                    min_odds: float = 1.30,
                    max_edge: float = 0.50,
                    now: datetime | None = None) -> list[dict[str, Any]]:
    """对一批竞彩场次做预测与价值判断。

    skip_started=True 时，开赛时间已过的场次会被标记 skipped（避免"赛后预测"）。
    开赛时间未知（缺 match_time）时不做跳过，交给其它校验。

    blend_weight：模型概率与去水市场概率的混合权重（0=纯市场，1=纯模型）。
    elo_blend_weight：Dixon-Coles 与 Elo 混合时 DC 的权重（0=纯Elo，1=纯DC）。
    ml_blend_weight：DC+Elo 与 LightGBM 混合时 DC+Elo 的权重（0=纯ML，1=纯DC+Elo）。
    顺序：DC 与 Elo 混合 → 与 ML 混合 → 与去水市场概率混合。
    价值判断在**混合后**的概率上进行，以缓解模型过度自信。

    返回逐场记录（dict）列表。未收录联赛 / 无模型 / 队名未匹配的场次
    仍会返回，但带 ``skipped`` 字段说明原因，不静默丢弃。
    """
    leagues = get_leagues()
    rows: list[dict[str, Any]] = []
    now = now or datetime.now()

    # ML 特征构造器缓存（惰性，仅当有 ML 模型时使用）
    _ml_data: pd.DataFrame | None = None
    _ml_builders: dict[str, feat.RollingFeatures] = {}

    def _get_ml_builder(key: str) -> feat.RollingFeatures:
        nonlocal _ml_data
        if key in _ml_builders:
            return _ml_builders[key]
        if _ml_data is None:
            _ml_data = load_training_data()
        members = leagues.model_members(key)
        sub = _ml_data[_ml_data["league_code"].isin(members)]
        rf = feat.RollingFeatures()
        rf.ingest(sub)
        _ml_builders[key] = rf
        return rf

    for m in matches:
        rec: dict[str, Any] = {
            "match_id": getattr(m, "match_id", None),
            "match_num": getattr(m, "match_num", ""),
            "match_date": getattr(m, "match_date", ""),
            "match_time": getattr(m, "match_time", ""),
            "league": getattr(m, "league", ""),
            "league_code": getattr(m, "league_code", ""),
            "business_date": getattr(m, "business_date", ""),
            "weekday": getattr(m, "weekday", ""),
            "match_num_date": getattr(m, "match_num_date", ""),
            "home_cn": getattr(m, "home_cn", ""),
            "away_cn": getattr(m, "away_cn", ""),
            "div": None,
            "skipped": None,
        }

        if skip_started:
            kickoff = match_kickoff(rec["match_date"], rec["match_time"])
            if kickoff is not None and kickoff <= now:
                rec["skipped"] = (f"已开赛/结束: {rec['match_date']} "
                                  f"{rec['match_time']}")
                rows.append(rec)
                continue

        div = leagues.jc_name_to_div(getattr(m, "league", ""))
        rec["div"] = div
        if div is None:
            rec["skipped"] = f"未收录联赛: {m.league}"
            rows.append(rec)
            continue
        # 欧战 div（UCL/UEL/CONF）路由到合并模型 EUR（若已训练），
        # 否则回落到该 div 自己的模型
        model_key = leagues.model_key_for(div, available=models)
        rec["model"] = model_key
        if model_key not in models:
            rec["skipped"] = f"无模型: {div}"
            rows.append(rec)
            continue

        rh = matcher.match(m.home_cn, getattr(m, "home_en", ""))
        ra = matcher.match(m.away_cn, getattr(m, "away_en", ""))
        rec.update({
            "home_matched": rh.matched_name,
            "away_matched": ra.matched_name,
            "conf_home": rh.confidence,
            "conf_away": ra.confidence,
        })
        if not (rh.ok and ra.ok):
            rec["skipped"] = f"队名未匹配: {m.home_cn}({rh.confidence})/{m.away_cn}({ra.confidence})"
            rows.append(rec)
            continue

        dc_model = models[model_key]["dc"]
        missing = [n for n in (rh.matched_name, ra.matched_name)
                   if n not in dc_model.attack]
        if missing:
            rec["skipped"] = f"球队无历史数据: {'/'.join(missing)}"
            rows.append(rec)
            continue

        hf_model = models[model_key].get("hf")
        pred = dc.predict_proba(dc_model, rh.matched_name, ra.matched_name)
        matrix = pred["score_matrix"]
        goal_line = m.hhad_goal_line

        hf_probs = (halffull.predict(hf_model, rh.matched_name, ra.matched_name)
                    if hf_model is not None else None)
        all_p = pay.all_market_probabilities(matrix, pred["total_goals"],
                                             goal_line=goal_line,
                                             half_full=hf_probs)

        had_model = {"胜": pred["prob_home"], "平": pred["prob_draw"],
                     "负": pred["prob_away"]}
        # Elo 第二意见：DC 与 Elo 先混合成「模型」概率
        elo_model = models[model_key].get("elo")
        elo_had: dict[str, float] | None = None
        if elo_model is not None:
            ep = elo_model.predict(rh.matched_name, ra.matched_name)
            elo_had = {"胜": ep["prob_home"], "平": ep["prob_draw"],
                       "负": ep["prob_away"]}
            had_model = pay.blend_probabilities(had_model, elo_had,
                                                weight=elo_blend_weight)
        # LightGBM 第三意见：与 DC+Elo 混合
        ml_obj = models[model_key].get("ml")
        ml_had: dict[str, float] | None = None
        if ml_obj is not None:
            rf = _get_ml_builder(model_key)
            X = rf.feature_frame(rh.matched_name, ra.matched_name,
                                 rec["match_date"])
            ml_had = ml_obj.predict_proba(X)
            if ml_had is not None:
                had_model = pay.blend_probabilities(had_model, ml_had,
                                                    weight=ml_blend_weight)
        had_odds = {_ODDS_LABELS[k]: v for k, v in m.had_odds().items()}
        had_implied = pay.implied_probabilities(had_odds)
        had_blended = pay.blend_probabilities(had_model, had_implied,
                                              weight=blend_weight)
        hhad_model = all_p.get("HHAD")
        hhad_odds = {_ODDS_LABELS[k]: v for k, v in m.hhad_odds().items()}
        hhad_implied = pay.implied_probabilities(hhad_odds) if hhad_model else {}
        hhad_blended = pay.blend_probabilities(hhad_model, hhad_implied,
                                               weight=blend_weight) if hhad_model else {}

        values: list[dict[str, Any]] = []
        # 价值判断在「混合后」的概率上进行，缓解过度自信导致的虚假 edge
        for market, mp, od in (("HAD", had_blended, had_odds),
                              ("HHAD", hhad_blended, hhad_odds)):
            if not mp:
                continue
            for b in _value_bets(mp, od, edge_threshold,
                                 kelly_fraction, max_stake_pct,
                                 min_odds=min_odds, max_edge=max_edge):
                b["market"] = market
                values.append(b)
        values.sort(key=lambda x: -x["edge"])

        crs = sorted(all_p["CRS"].items(), key=lambda x: -x[1])[:crs_top]
        score_top = _top_exact_scores(matrix, crs_top)
        hf_top = (sorted(hf_probs.items(), key=lambda x: -x[1])[:crs_top]
                  if hf_probs else [])

        rec.update({
            "xg_home": pred["xg_home"],
            "xg_away": pred["xg_away"],
            "had": had_model,
            "had_dc": {"胜": pred["prob_home"], "平": pred["prob_draw"],
                       "负": pred["prob_away"]},
            "elo_had": elo_had,
            "elo_blend_weight": elo_blend_weight,
            "ml_had": ml_had,
            "ml_blend_weight": ml_blend_weight,
            "had_odds": had_odds,
            "had_implied": had_implied,
            "had_blended": had_blended,
            "overround": pay.overround(had_odds),
            "hhad_goal_line": goal_line,
            "hhad": hhad_model,
            "hhad_odds": hhad_odds,
            "hhad_implied": hhad_implied,
            "hhad_blended": hhad_blended,
            "blend_weight": blend_weight,
            "ttg": all_p["TTG"],
            "crs_top": crs,
            "score_top": score_top,
            "score_most_likely": score_top[0]["score"] if score_top else None,
            "score_most_likely_prob": score_top[0]["prob"] if score_top else None,
            "hafu_top": hf_top,
            "value_bets": values,
        })
        rows.append(rec)

    return rows


# --------------------------------------------------------------------------- #
# 报告
# --------------------------------------------------------------------------- #
def summarize(rows: list[dict[str, Any]]) -> dict[str, int]:
    """统计预测覆盖情况。"""
    total = len(rows)
    skipped = sum(1 for r in rows if r.get("skipped"))
    predicted = total - skipped
    with_value = sum(1 for r in rows if r.get("value_bets"))
    return {"total": total, "predicted": predicted,
            "skipped": skipped, "with_value": with_value}


def _fmt(v: Any, nd: int = 3) -> str:
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return "-"


def write_report(rows: list[dict[str, Any]], edge_threshold: float,
                 path_base: Path | None = None,
                 generated_at: str | None = None) -> tuple[Path, Path]:
    """双写 Markdown（人读）+ JSON（机读）。返回 (md_path, json_path)。"""
    settings = get_settings()
    settings.ensure_dirs()
    ts = generated_at or datetime.now().strftime("%Y%m%d")
    base = Path(path_base) if path_base else settings.reports_dir / f"predict_{ts}"
    md_path = base.with_suffix(".md")
    json_path = base.with_suffix(".json")
    md_path.parent.mkdir(parents=True, exist_ok=True)

    stats = summarize(rows)
    generated = datetime.now().isoformat(timespec="seconds")

    lines: list[str] = [
        f"# 竞彩预测报告 {generated}",
        "",
        f"- 场次总数：{stats['total']}",
        f"- 可预测：{stats['predicted']}，跳过：{stats['skipped']}",
        f"- 含价值选项：{stats['with_value']}",
        f"- edge 阈值：{edge_threshold}",
    ]
    round_dates = sorted({str(r.get("business_date")) for r in rows
                          if r.get("business_date")})
    if round_dates:
        lines.append(f"- 期（销售日）：{', '.join(round_dates)}")
    lines += [
        "",
        "## 预测明细",
        "",
        "| 编号 | 联赛 | 对阵 | xG | 最可能比分 | 主胜 | 平 | 客胜 | 让球 | 让胜/让平/让负 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]

    for r in rows:
        if r.get("skipped"):
            continue
        had = r["had"]
        xg = f"{_fmt(r['xg_home'], 2)}-{_fmt(r['xg_away'], 2)}"
        score = r.get("score_most_likely")
        sp = r.get("score_most_likely_prob")
        score_txt = (f"{score} ({sp * 100:.1f}%)"
                     if score is not None and sp is not None else "-")
        hh = r.get("hhad")
        hh_txt = " / ".join(_fmt(hh[k]) for k in HAD_KEYS) if hh else "-"
        gl = r.get("hhad_goal_line")
        gl_txt = f"{gl:+.0f}" if gl is not None else "-"
        lines.append(
            f"| {r['match_num']} | {r['league']} | {r['home_cn']} vs {r['away_cn']} "
            f"| {xg} | {score_txt} | {_fmt(had['胜'])} | {_fmt(had['平'])} "
            f"| {_fmt(had['负'])} | {gl_txt} | {hh_txt} |"
        )

    lines += ["", "## 比分概率 Top3", "",
              "| 编号 | 联赛 | 对阵 | Top1 | Top2 | Top3 |",
              "|---|---|---|---|---|---|"]
    for r in rows:
        if r.get("skipped"):
            continue
        top = r.get("score_top") or []
        cells = [f"{t['score']} {t['prob'] * 100:.1f}%" for t in top]
        cells += ["-"] * (3 - len(cells))
        lines.append(
            f"| {r['match_num']} | {r['league']} | {r['home_cn']} vs {r['away_cn']} "
            f"| {cells[0]} | {cells[1]} | {cells[2]} |"
        )

    lines += ["", "## 半全场概率 Top3", "",
              "| 编号 | 联赛 | 对阵 | Top1 | Top2 | Top3 |",
              "|---|---|---|---|---|---|"]
    for r in rows:
        if r.get("skipped"):
            continue
        top = r.get("hafu_top") or []
        cells = [f"{label} {prob * 100:.1f}%" for label, prob in top]
        cells += ["-"] * (3 - len(cells))
        lines.append(
            f"| {r['match_num']} | {r['league']} | {r['home_cn']} vs {r['away_cn']} "
            f"| {cells[0]} | {cells[1]} | {cells[2]} |"
        )

    lines += ["", "## 总进球分布", "",
              "| 编号 | 联赛 | 对阵 | 期望总球 | 0球 | 1球 | 2球 | 3球 | 4球 | 5球 | 6球 | 7+ |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r.get("skipped"):
            continue
        ttg = r.get("ttg") or {}
        exp_goals = (r.get("xg_home") or 0) + (r.get("xg_away") or 0)
        cells = [f"{ttg.get(b, 0) * 100:.1f}%" for b in TTG_BUCKETS]
        lines.append(
            f"| {r['match_num']} | {r['league']} | {r['home_cn']} vs {r['away_cn']} "
            f"| {exp_goals:.2f} | " + " | ".join(cells) + " |"
        )

    lines += ["", "## 价值选项", ""]
    any_value = False
    for r in rows:
        vb = r.get("value_bets")
        if not vb:
            continue
        any_value = True
        lines.append(f"### {r['match_num']} {r['league']} "
                     f"{r['home_cn']} vs {r['away_cn']}  (div={r['div']})")
        lines.append("")
        lines.append("| 玩法 | 选项 | 赔率 | 模型概率 | 隐含概率 | edge | EV | 建议仓位 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for b in vb:
            lines.append(
                f"| {b['market']} | {b['option']} | {_fmt(b['odds'], 2)} "
                f"| {_fmt(b['model_prob'])} | {_fmt(b['implied_prob'])} "
                f"| {_fmt(b['edge'])} | {_fmt(b['ev'])} "
                f"| {_fmt(b['stake_pct'] * 100, 2)}% |"
            )
        lines.append("")
    if not any_value:
        lines.append("（无达到阈值的选择）")
        lines.append("")

    skipped = [r for r in rows if r.get("skipped")]
    if skipped:
        lines += ["## 跳过场次", ""]
        for r in skipped:
            lines.append(f"- {r['match_num']} {r['league']} "
                         f"{r['home_cn']} vs {r['away_cn']}：{r['skipped']}")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")

    payload = {
        "generated_at": generated,
        "edge_threshold": edge_threshold,
        "stats": stats,
        "predictions": rows,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1,
                                    default=str), encoding="utf-8")
    return md_path, json_path


def archive_report(json_path: str | Path,
                   archive_dir: Path | None = None) -> Path:
    """把一次预测报告复制到 reports/archive/，形成不可覆盖的历史版本。

    ``reports/predict_YYYYMMDD.json`` 同一天重跑会被覆盖；历史页必须使用
    **开赛前的最后一次存档**，否则赛后重跑会变成“用赛后信息预测过去”。

    归档文件名：``predict_YYYYMMDD_HHMMSS.json``，保留原始 ``generated_at``。
    """
    src = Path(json_path)
    settings = get_settings()
    target_dir = archive_dir or (settings.reports_dir / "archive")
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%H%M%S")
    dst = target_dir / f"{src.stem}_{stamp}.json"
    shutil.copy2(src, dst)
    return dst
