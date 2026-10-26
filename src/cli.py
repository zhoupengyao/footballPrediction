"""命令行入口。

用法：
    python -m src.cli status
    python -m src.cli fetch-tier1 --online [--leagues E0 D1] [--seasons 2425 2526]
    python -m src.cli fetch-jingcai --online
    python -m src.cli train [--leagues E0 D1] [--years 5] [--half-life 180]
    python -m src.cli predict [--odds data/odds/jc_odds_20261016.json] [--edge 0.05] [--crs-top 3]
    python -m src.cli pipeline [--online] [--skip-fetch]

约定：fetch 阶段默认**离线**（复用已下载镜像 / 已保存快照），
只有显式加 ``--online`` 才会发起网络请求。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.config import PROJECT_ROOT, get_leagues, get_settings


def _fix_console_encoding() -> None:
    """Windows 控制台默认 GBK，强制 UTF-8 避免中文乱码。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #
def cmd_status(args: argparse.Namespace) -> int:
    """检查环境与数据状态。"""
    settings = get_settings()
    leagues = get_leagues()
    settings.ensure_dirs()

    print(f"项目根目录: {PROJECT_ROOT}")
    print()
    print("== 联赛配置 ==")
    t1 = leagues.tier1
    t2 = leagues.tier2
    print(f"Tier 1 (football-data.co.uk): {len(t1)} 个赛区")
    print(f"Tier 2 (API-Football):        {len(t2)} 个联赛")
    print(f"Tier 3 (eloratings.net):      {len(leagues.tier3['events'])} 类国家队赛事")
    extra = leagues.extra
    if extra:
        names = "、".join(f"{code} {info.get('name', '')}" for code, info in extra.items())
        print(f"额外赛事 (openfootball):      {len(extra)} 个（{names}）")
    print(f"竞彩常见开售 Tier1 联赛:       {len(leagues.jc_common_tier1())} 个")
    print(f"竞彩联赛名映射:               {len(leagues.jc_league_map)} 条")
    print()
    print("== 竞彩玩法 ==")
    for code, info in leagues.markets.items():
        print(f"  {code:<14} {info['name']}")
    print()

    print("== 数据状态 ==")
    raw_dir = settings.raw_dir
    processed_dir = settings.processed_dir
    raw_files = list(raw_dir.glob("**/*.csv")) if raw_dir.exists() else []
    processed_files = list(processed_dir.glob("**/*.parquet")) if processed_dir.exists() else []
    print(f"raw 数据文件:     {len(raw_files)}")
    print(f"processed 数据集: {len(processed_files)}")
    for p in sorted(processed_files):
        print(f"    {p.name}")
    snap = sorted(settings.odds_dir.glob("jc_odds_*.json")) if settings.odds_dir.exists() else []
    print(f"odds 快照:        {len(snap)} 份" + (f"（最新 {snap[-1].name}）" if snap else ""))

    print()
    print("== 已训练模型 ==")
    model_dirs = (sorted(p.name for p in settings.models_dir.iterdir() if p.is_dir())
                  if settings.models_dir.exists() else [])
    if model_dirs:
        for div in model_dirs:
            name = leagues.name_of(div)
            has_hf = (settings.models_dir / div / "halffull.json").exists()
            has_elo = (settings.models_dir / div / "elo.json").exists()
            has_ml = (settings.models_dir / div / "ml.joblib").exists()
            print(f"  {div:<5} {name:<8} 半全场={'有' if has_hf else '无'}  "
                  f"Elo={'有' if has_elo else '无'}  ML={'有' if has_ml else '无'}")
    else:
        print("  （无，请运行 python -m src.cli train）")

    print()
    print("== 依赖检查 ==")
    deps = [
        "pandas", "numpy", "scipy", "sklearn",
        "lightgbm", "xgboost", "requests", "yaml",
        "streamlit", "plotly",
    ]
    missing = []
    for name in deps:
        try:
            mod = __import__(name)
            ver = getattr(mod, "__version__", "?")
            print(f"  {name:<12} {ver}")
        except ImportError:
            print(f"  {name:<12} 缺失")
            missing.append(name)
    print()
    if missing:
        print(f"缺失依赖: {', '.join(missing)}")
        print("请运行: pip install -r requirements.txt")
        return 1
    print("骨架就绪。")
    return 0


# --------------------------------------------------------------------------- #
# fetch-tier1
# --------------------------------------------------------------------------- #
def cmd_fetch_tier1(args: argparse.Namespace) -> int:
    """下载/解析 football-data 镜像并落盘为 processed parquet。"""
    settings = get_settings()
    settings.ensure_dirs()
    mirror = settings.raw_dir / "football-datasets"

    from src.ingest.footballdata import (download_mirror, load_tier1,
                                         save_processed)

    if args.online:
        download_mirror(mirror, force=args.force)
    elif not mirror.exists():
        print(f"镜像不存在: {mirror}")
        print("离线模式无法继续，请加 --online 下载。")
        return 1
    else:
        print(f"离线模式，复用已下载镜像: {mirror}")

    df = load_tier1(divs=args.leagues, seasons=args.seasons)
    if df.empty:
        print("未加载到任何数据。")
        return 1
    # 过滤抓取时使用独立文件名，避免覆盖完整的 tier1_matches 主数据集
    name = args.name
    if name is None:
        name = "tier1_matches_filtered" if (args.leagues or args.seasons) else "tier1_matches"
    if name != "tier1_matches":
        print(f"提示：带过滤条件，写入 {name}.parquet（不覆盖主数据集）")
    path = save_processed(df, name=name)
    print(f"\n加载 {len(df)} 场，已保存: {path}")
    print(df.groupby("league_name").size().to_string())
    return 0


# --------------------------------------------------------------------------- #
# fetch-ucl
# --------------------------------------------------------------------------- #
def cmd_fetch_ucl(args: argparse.Namespace) -> int:
    """下载/解析欧冠数据（openfootball）并落盘。"""
    settings = get_settings()
    settings.ensure_dirs()

    from src.ingest.ucl import DEFAULT_SEASONS, build_dataset, save_dataset

    seasons = args.seasons or DEFAULT_SEASONS
    print(f"抓取欧冠（{len(seasons)} 季，online={args.online}）...")
    df = build_dataset(seasons, online=args.online, force=args.force)
    if df.empty:
        print("未加载到欧冠数据。首次使用请加 --online。")
        return 1
    path = save_dataset(df)
    print(f"\n欧冠 {len(df)} 场，{df['season'].nunique()} 季，已保存: {path}")
    print(df.groupby("season").size().to_string())
    return 0


# --------------------------------------------------------------------------- #
# fetch-europa
# --------------------------------------------------------------------------- #
def cmd_fetch_europa(args: argparse.Namespace) -> int:
    """下载/解析欧罗巴 + 欧协联数据（openfootball）并落盘。"""
    from src.ingest.openfootball import (COMPETITIONS, build_dataset,
                                         default_seasons, save_dataset)

    settings = get_settings()
    settings.ensure_dirs()

    comps = list(args.comps or ["UEL", "CONF"])
    ok = True
    for comp in comps:
        spec = COMPETITIONS[comp]
        seasons = args.seasons or default_seasons(comp)
        print(f"抓取{spec['name']}（{comp}，{len(seasons)} 季，"
              f"online={args.online}）...")
        df = build_dataset(comp, seasons, online=args.online, force=args.force)
        if df.empty:
            print(f"  {comp}: 未加载到数据。首次使用请加 --online。")
            ok = False
            continue
        path = save_dataset(df, comp)
        print(f"  {comp} {len(df)} 场，{df['season'].nunique()} 季，"
              f"已保存: {path}")
        print(df.groupby("season").size().to_string())
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# fetch-understat
# --------------------------------------------------------------------------- #
def cmd_fetch_understat(args: argparse.Namespace) -> int:
    """下载/解析 understat 数据（比分 + xG 特征），用于补最新赛季。"""
    from src.ingest.understat import LEAGUE_MAP, fetch_all

    settings = get_settings()
    settings.ensure_dirs()

    if not args.online:
        p = settings.processed_dir / "understat_matches.parquet"
        if p.exists():
            import pandas as pd
            df = pd.read_parquet(p)
            print(f"离线模式，已有 understat 数据: {len(df)} 场，"
                  f"最新 {df['date'].max().date()}")
            return 0
        print("离线模式且无 understat 数据，请加 --online 下载。")
        return 1

    leagues = args.leagues or list(LEAGUE_MAP.keys())
    seasons = [int(s) for s in args.seasons] if args.seasons else None
    print(f"抓取 understat（联赛 {'/'.join(leagues)}，"
          f"赛季 {args.seasons or '默认 2014/15 起'}，online=True）...")
    matches, teams = fetch_all(seasons=seasons, leagues=leagues, save=True)
    if matches.empty:
        print("未抓取到 understat 数据。")
        return 1
    print(f"\nunderstat: {len(matches)} 场, {len(teams)} 队次特征")
    print(matches.groupby("league_code").size().to_string())
    return 0


# --------------------------------------------------------------------------- #
# fetch-tier1-gh
# --------------------------------------------------------------------------- #
def cmd_fetch_tier1_gh(args: argparse.Namespace) -> int:
    """从 jokecamp 镜像下载并解析更多联赛的比分（扩大联赛覆盖）。

    与 ``fetch-tier1``（datasets 镜像，仅 5 大联赛）互补：
    本命令从 jokecamp/FootballData 取荷/比/葡/土/希/苏 + 五大联赛二三级
    联赛的比分，落盘为 data/processed/tier1_gh_matches.parquet。
    """
    from src.ingest import odds as O

    settings = get_settings()
    settings.ensure_dirs()
    root = settings.raw_dir / "odds-dump"

    divs = args.leagues
    if args.online:
        # 经 ghproxy 代理按需下载目标联赛文件（复用 fetch-odds 的下载器）
        O.fetch_odds_via_proxy(root, divs=divs)
    elif not root.exists():
        print("离线模式且无赔率 dump，请加 --online 下载。")
        return 1
    else:
        print(f"离线模式，复用已下载 dump: {root}")

    df = O.load_matches_from_dump(root, divs=divs)
    if df.empty:
        print("未解析到比赛数据。")
        return 1
    path = O.save_matches(df)
    print(f"\n比赛 {len(df)} 场，已保存: {path}")
    print(df.groupby("league_code").agg(
        场次=("date", "size"), 起=("date", "min"), 止=("date", "max")).to_string())
    print("\n提示：这些联赛要能预测，还需在 src/jingcai/team_names.py 补中文别名，")
    print("可先运行 `python -m src.cli doctor` 看哪些球队未匹配。")
    return 0


# --------------------------------------------------------------------------- #
# fetch-apifootball
# --------------------------------------------------------------------------- #
def cmd_fetch_apifootball(args: argparse.Namespace) -> int:
    """下载 API-Football 赛果（巴甲/挪超/瑞超/芬超等 tier2 联赛）。"""
    from src.ingest import apifootball as AP

    settings = get_settings()
    settings.ensure_dirs()

    if not args.online:
        p = settings.processed_dir / "apifootball_matches.parquet"
        if p.exists():
            import pandas as pd
            df = pd.read_parquet(p)
            print(f"离线模式，已有 API-Football 数据: {len(df)} 场")
            print(df.groupby("league_code").size().to_string())
            return 0
        print("离线模式且无 API-Football 数据，请加 --online 下载。")
        return 1

    divs = args.leagues
    seasons = [int(s) for s in args.seasons] if args.seasons else None
    print(f"抓取 API-Football（div={'/'.join(divs or list(AP.LEAGUE_TO_DIV.values()))}"
          f"，season={seasons or '近6季'}）...")
    df = AP.build_dataset(divs=divs, seasons=seasons, save=True, verbose=True)
    if df.empty:
        print("未抓到任何赛果。")
        return 1
    path = AP.save_dataset(df)
    print(f"\n共 {len(df)} 场，已保存: {path}")
    print(df.groupby("league_code").agg(
        场次=("date", "size"), 起=("date", "min"), 止=("date", "max")).to_string())
    print("\n提示：这些联赛要能预测，还需补中文别名：")
    print("  python -m src.cli doctor   # 看哪些球队未匹配，补进 team_names.py 的 CN_TO_EN")
    return 0


# --------------------------------------------------------------------------- #
# fetch-jingcai
# --------------------------------------------------------------------------- #
def cmd_fetch_jingcai(args: argparse.Namespace) -> int:
    """抓取竞彩开售场次并保存赔率快照。"""
    settings = get_settings()
    settings.ensure_dirs()

    from src.ingest.jingcai_scraper import (fetch_today, latest_snapshot,
                                            save_matches, to_dataframe)

    if not args.online:
        snap = latest_snapshot()
        if snap is None:
            print("离线模式且无历史快照，请加 --online 抓取。")
            return 1
        print(f"离线模式，使用最新快照: {snap}")
        return 0

    pool = ",".join(args.pool) if args.pool else "had,hhad,crs,ttg,hafu"
    print(f"抓取竞彩（poolCode={pool}）...")
    matches = fetch_today(pool_codes=pool)
    if not matches:
        print("未抓到场次。")
        return 1
    df = to_dataframe(matches)
    path = save_matches(matches)
    print(f"\n抓到 {len(matches)} 场，已保存快照: {path}")
    print(df.groupby("league").size().to_string())
    return 0


# --------------------------------------------------------------------------- #
# train
# --------------------------------------------------------------------------- #
def cmd_train(args: argparse.Namespace) -> int:
    """逐联赛训练 Dixon-Coles(含半全场) 并落盘。"""
    from src.pipeline import train_leagues

    if args.years is None or args.half_life is None:
        print("开始训练（未指定的参数按 settings.yaml / 联赛覆盖生效）...")
    else:
        print(f"开始训练（近 {args.years} 赛季，半衰期 {args.half_life} 天）...")
    models = train_leagues(leagues=args.leagues, years=args.years,
                           half_life=args.half_life,
                           shrinkage_prior=args.shrinkage,
                           with_ml=args.with_ml)
    if not models:
        print("没有联赛训练成功。")
        return 1
    settings = get_settings()
    print(f"\n完成 {len(models)} 个联赛，模型目录: {settings.models_dir}")
    return 0


# --------------------------------------------------------------------------- #
# predict
# --------------------------------------------------------------------------- #
def _snapshot_age_days(path) -> int | None:
    """从 jc_odds_YYYYMMDD.json 文件名推断快照距今天数。"""
    import re
    from datetime import date, datetime

    m = re.search(r"jc_odds_(\d{8})", Path(path).name)
    if not m:
        return None
    try:
        d = datetime.strptime(m.group(1), "%Y%m%d").date()
    except ValueError:
        return None
    return (date.today() - d).days


def cmd_predict(args: argparse.Namespace) -> int:
    """加载模型 + 赔率快照，产出预测与价值报告。"""
    from src.ingest.jingcai_scraper import (filter_matches, latest_snapshot,
                                            load_matches, select_round)
    from src.pipeline import (archive_report, build_matcher, load_models,
                              predict_matches, summarize, write_report)

    settings = get_settings()
    settings.ensure_dirs()

    models = load_models(leagues=args.leagues)
    if not models:
        print("没有可用模型，请先运行 python -m src.cli train")
        return 1
    print(f"已载入模型: {', '.join(sorted(models))}")

    if args.odds:
        odds_path = Path(args.odds)
    else:
        odds_path = latest_snapshot()
    if odds_path is None or not Path(odds_path).exists():
        print("没有赔率快照，请先运行 python -m src.cli fetch-jingcai --online")
        return 1
    matches = load_matches(odds_path)
    print(f"赔率快照: {odds_path}（{len(matches)} 场）")
    age = _snapshot_age_days(odds_path)
    if age is not None and age > 0:
        print(f"⚠️  注意：该快照是 {age} 天前的，可能已过期。"
              f"获取今日数据请运行: python -m src.cli fetch-jingcai --online")

    total_loaded = len(matches)
    match_nums = getattr(args, "match_num", None)
    teams = getattr(args, "team", None)
    if match_nums or teams:
        # 指定场次：跨全部期查找（不受 --round 限制）
        all_matches = matches
        matches = filter_matches(matches, match_nums=match_nums, teams=teams)
        cond = " + ".join(filter(None, [
            f"编号 {'/'.join(match_nums)}" if match_nums else "",
            f"球队 {'/'.join(teams)}" if teams else "",
        ]))
        print(f"指定场次：{cond}，命中 {len(matches)}/{total_loaded} 场")
        if not matches:
            nums = [m.match_num for m in all_matches]
            preview = "、".join(nums[:20]) + ("……" if len(nums) > 20 else "")
            print(f"⚠️  未找到匹配场次。当前快照编号：{preview}")
            return 1
    elif args.round != "all":
        matches, round_label = select_round(matches, mode=args.round)
        print(f"本期：{round_label}，{len(matches)}/{total_loaded} 场")
    elif total_loaded:
        print(f"本期：全部（{total_loaded} 场）")

    matcher = build_matcher()
    blend = args.blend if args.blend is not None else settings.blend_weight
    elo_w = args.elo if args.elo is not None else settings.elo_blend_weight
    ml_w = args.ml_weight if args.ml_weight is not None else settings.ml_blend_weight
    min_odds = args.min_odds if args.min_odds is not None else settings.min_odds
    max_edge = args.max_edge if args.max_edge is not None else settings.max_edge
    rows = predict_matches(matches, models, matcher,
                           edge_threshold=args.edge,
                           max_stake_pct=args.max_stake,
                           crs_top=args.crs_top,
                           skip_started=not args.include_started,
                           blend_weight=blend,
                           elo_blend_weight=elo_w,
                           ml_blend_weight=ml_w,
                           min_odds=min_odds,
                           max_edge=max_edge)
    stats = summarize(rows)
    report_dates = sorted({
        str(getattr(m, "business_date", "") or getattr(m, "match_date", ""))[:10]
        for m in matches
    } - {""})
    date_tag = report_dates[0].replace("-", "") if report_dates else None
    md_path, json_path = write_report(rows, edge_threshold=args.edge,
                                      generated_at=date_tag)
    archive_path = archive_report(json_path)

    if stats["predicted"] == 0:
        started = sum(1 for r in rows
                      if str(r.get("skipped") or "").startswith("已开赛"))
        if started:
            print(f"⚠️  {started} 场已开赛被跳过。请先运行 "
                  f"fetch-jingcai --online 获取新快照；"
                  f"如确需强制预测，加 --include-started。")

    print(f"\n预测完成：可预测 {stats['predicted']}/{stats['total']}，"
          f"跳过 {stats['skipped']}，含价值 {stats['with_value']}")
    for r in rows:
        if r.get("skipped"):
            print(f"  [跳过] {r['match_num']} {r['league']}: {r['skipped']}")
            continue
        had = r["had"]
        score = r.get("score_most_likely")
        sp = r.get("score_most_likely_prob")
        score_txt = (f" 比分 {score}({sp * 100:.1f}%)"
                     if score is not None and sp is not None else "")
        print(f"  {r['match_num']} {r['league']} {r['home_cn']} vs {r['away_cn']}"
              f"{score_txt} | 胜{had['胜']:.3f} 平{had['平']:.3f} 负{had['负']:.3f}")
        for b in r.get("value_bets", []):
            print(f"      ★ {b['market']} {b['option']} "
                  f"edge={b['edge']:.3f} EV={b['ev']:.3f} "
                  f"仓位={b['stake_pct'] * 100:.2f}%")
    print(f"\n报告已写入:\n  {md_path}\n  {json_path}\n归档: {archive_path}")
    return 0


# --------------------------------------------------------------------------- #
# recommend
# --------------------------------------------------------------------------- #
def cmd_recommend(args: argparse.Namespace) -> int:
    """候选筛选（纸面）：从预测中筛可靠价值注，分级 + 仓位（不构成盈利建议）。"""
    from src.ingest.jingcai_scraper import (filter_matches, latest_snapshot,
                                            load_matches, select_round)
    from src.pipeline import (build_matcher, load_models, predict_matches)
    from src.recommend import log_recommendations, run_recommend, write_report

    settings = get_settings()
    settings.ensure_dirs()

    models = load_models(leagues=args.leagues)
    if not models:
        print("没有可用模型，请先运行 python -m src.cli train")
        return 1

    if args.odds:
        odds_path = Path(args.odds)
    else:
        odds_path = latest_snapshot()
    if odds_path is None or not Path(odds_path).exists():
        print("没有赔率快照，请先运行 python -m src.cli fetch-jingcai --online")
        return 1
    matches = load_matches(odds_path)

    if args.match_num or args.team:
        matches = filter_matches(matches, match_nums=args.match_num, teams=args.team)
        if not matches:
            print("未找到匹配场次。")
            return 1
    elif args.round != "all":
        matches, _ = select_round(matches, mode=args.round)

    matcher = build_matcher()
    blend = args.blend if args.blend is not None else settings.blend_weight
    elo_w = args.elo if args.elo is not None else settings.elo_blend_weight
    ml_w = args.ml_weight if args.ml_weight is not None else settings.ml_blend_weight
    rows = predict_matches(matches, models, matcher,
                           edge_threshold=args.edge,
                           max_stake_pct=args.max_stake,
                           crs_top=args.crs_top,
                           skip_started=not args.include_started,
                           blend_weight=blend,
                           elo_blend_weight=elo_w,
                           ml_blend_weight=ml_w)

    cfg = settings.recommend_for(args.risk)
    result = run_recommend(rows, cfg, bankroll=args.bankroll)
    md, js = write_report(result)
    log_recommendations(result["recommendations"])

    recs = result["recommendations"]
    print("\n⚠️  本清单是风险筛选（纸面），不构成盈利建议；历史回测 ROI 为负。")
    print(f"\n候选筛选（{cfg['risk']}，仅 {'/'.join(cfg.get('markets', ['HAD']))}）："
          f"{len(recs)} 注，合计仓位 {result['total_stake_pct'] * 100:.2f}%"
          + (f"（¥{args.bankroll * result['total_stake_pct']:.0f}）"
             if args.bankroll else ""))
    for it in recs:
        stake = f"{it['stake_pct'] * 100:.2f}%"
        if args.bankroll:
            stake += f"（¥{it.get('stake_amount', 0):.0f}）"
        print(f"  {it['tier']}★ {it['match_num']} {it['league']} "
              f"{it['home_cn']} vs {it['away_cn']} | {it['market']} {it['option']} "
              f"@{it['odds']:.2f} edge={it['edge']:.3f} EV={it['ev']:.3f} 仓位={stake}")
    if result["observations"]:
        print(f"\n观察（不下注）：{len(result['observations'])} 条，详见报告")
    print(f"\n报告已写入:\n  {md}\n  {js}")
    print("⚠️  仅为纸面候选，请用 reconcile 长期验证，勿据此重仓真钱。")
    return 0


# --------------------------------------------------------------------------- #
# pipeline
# --------------------------------------------------------------------------- #
def cmd_pipeline(args: argparse.Namespace) -> int:
    """一键串联：fetch(可选) -> train -> predict。"""
    if not args.skip_fetch:
        rc = cmd_fetch_tier1(argparse.Namespace(
            online=args.online, force=False,
            leagues=args.leagues, seasons=None, name=None))
        if rc != 0:
            return rc
        cmd_fetch_jingcai(argparse.Namespace(online=args.online, pool=None))
        wanted = set(args.leagues) if args.leagues else None
        if wanted is None or "UCL" in wanted or "EUR" in wanted:
            cmd_fetch_ucl(argparse.Namespace(online=args.online, force=False,
                                             seasons=None))
        if wanted is None or wanted & {"UEL", "CONF", "EUR"}:
            cmd_fetch_europa(argparse.Namespace(online=args.online, force=False,
                                                comps=None, seasons=None))

    rc = cmd_train(argparse.Namespace(leagues=args.leagues, years=args.years,
                                      half_life=args.half_life,
                                      shrinkage=args.shrinkage,
                                      with_ml=args.with_ml))
    if rc != 0:
        return rc
    return cmd_predict(argparse.Namespace(leagues=None, odds=args.odds,
                                          edge=args.edge, max_stake=args.max_stake,
                                          crs_top=args.crs_top,
                                          include_started=args.include_started,
                                          round=args.round,
                                          match_num=args.match_num,
                                          team=args.team,
                                          blend=args.blend,
                                          elo=args.elo,
                                          ml_weight=args.ml_weight,
                                          min_odds=args.min_odds,
                                          max_edge=args.max_edge))


# --------------------------------------------------------------------------- #
# fetch-odds
# --------------------------------------------------------------------------- #
def cmd_fetch_odds(args: argparse.Namespace) -> int:
    """下载/解析历史赔率 dump 并落盘。"""
    from src.ingest import odds as O

    settings = get_settings()
    settings.ensure_dirs()
    root = settings.raw_dir / "odds-dump"

    if args.online:
        if args.via == "api":
            O.fetch_odds_via_api(root, divs=args.leagues, max_files=args.max_files)
        elif args.via == "proxy":
            O.fetch_odds_via_proxy(root, divs=args.leagues)
        else:
            O.download_odds_dump(root, force=args.force)
    elif root.exists():
        print(f"离线模式，复用已下载赔率 dump: {root}")
    else:
        print("离线模式且无赔率 dump，请加 --online 下载。")
        return 1

    df = O.load_odds(root, divs=args.leagues)
    if df.empty:
        print("未解析到赔率数据。")
        return 1
    path = O.save_odds(df)
    print(f"\n赔率记录 {len(df)} 条，已保存: {path}")
    print(df.groupby("league_code").agg(
        场次=("date", "size"),
        起=("date", "min"), 止=("date", "max")).to_string())
    return 0


# --------------------------------------------------------------------------- #
# backtest
# --------------------------------------------------------------------------- #
def cmd_backtest(args: argparse.Namespace) -> int:
    """Walk-forward 回测并产出报告（含赔率时自动算 ROI）。"""
    from src.backtest import BacktestConfig, run_backtest, write_backtest_report
    from src.ingest import odds as O
    from src.pipeline import load_training_data

    df = load_training_data()
    if df.empty:
        print("训练数据为空，请先运行 fetch-tier1")
        return 1

    have_odds = False
    if not args.no_odds:
        od = None
        try:
            od = O.load_odds_processed()
        except FileNotFoundError:
            try:
                od = O.load_odds()
            except FileNotFoundError:
                od = None
        if od is not None and not od.empty:
            df = O.merge_odds(df, od)
            # 合并模型组（如 EUR）按成员联赛展开后检查赔率覆盖
            cov_leagues: list[str] | None = None
            if args.leagues:
                cov_leagues = []
                for code in args.leagues:
                    for m in get_leagues().model_members(code):
                        if m not in cov_leagues:
                            cov_leagues.append(m)
            cov = O.odds_coverage(df[df["league_code"].isin(cov_leagues)]
                                  if cov_leagues else df)
            have_odds = cov["with_odds"] > 0
            print(f"已合并赔率：{cov['with_odds']}/{cov['total']} "
                  f"({cov['coverage'] * 100:.1f}%) 场有赔率")
        else:
            print("未找到赔率数据，回测将只算准确率（无 ROI）。")

    settings = get_settings()
    years = args.years if args.years is not None else 5
    half_life = (args.half_life if args.half_life is not None
                 else float(settings.dc_half_life_days))
    # 单联赛/单模型组回测时套用训练覆盖
    # （如 UCL 的 10 年 / 540 天；EUR 的 years=null 即全部历史）
    if args.leagues and len(args.leagues) == 1:
        ov = settings.training_overrides.get(args.leagues[0], {})
        if args.years is None and "years" in ov:
            years = None if ov["years"] is None else int(ov["years"])
        if args.half_life is None and "half_life" in ov:
            half_life = float(ov["half_life"])

    cfg = BacktestConfig(
        leagues=args.leagues, years=years,
        min_train_size=args.min_train, refit_interval=args.refit,
        half_life=half_life, ev_threshold=args.ev,
        shrinkage_prior=(args.shrinkage if args.shrinkage is not None
                         else float(settings.shrinkage_prior)),
        max_test=args.max_test, start_year=args.start_year,
        end_year=args.end_year,
    )
    print(f"开始回测（窗口 {cfg.years or '全部'} 年，最小训练 {cfg.min_train_size}，"
          f"重拟合间隔 {cfg.refit_interval}）...")
    res = run_backtest(df, cfg)
    if not res["rows"]:
        print("回测无样本。")
        return 1

    md, js = write_backtest_report(res)
    overall = res["overall"]
    print(f"\n总体：{overall['n']} 场，准确率 {overall['accuracy']:.4f} "
          f"(基准 {overall['baseline_home']:.4f})，对数损失 {overall['log_loss']:.4f}")
    if overall["has_odds"]:
        b = overall["betting"]
        print(f"模拟投注：{b['n_bets']} 注，ROI {b['roi']:.4f}，"
              f"净收益 {b['profit']:.1f}，最大回撤 {b['max_drawdown']:.1f}")
    print(f"报告已写入:\n  {md}\n  {js}")
    return 0


# --------------------------------------------------------------------------- #
# reconcile
# --------------------------------------------------------------------------- #
def cmd_reconcile(args: argparse.Namespace) -> int:
    """对账：比对预测与实际比分，产出命中率/盈亏并写台账。"""
    from src.reconcile import run_reconcile

    if args.json:
        json_path = Path(args.json)
    else:
        settings = get_settings()
        if args.date:
            json_path = settings.reports_dir / f"predict_{args.date}.json"
        else:
            snaps = sorted(settings.reports_dir.glob("predict_*.json"))
            if not snaps:
                print("没有预测报告，请先运行 python -m src.cli predict")
                return 1
            json_path = snaps[-1]
    if not json_path.exists():
        print(f"预测报告不存在: {json_path}")
        return 1

    try:
        date_tag = (json_path.stem.replace("predict_", "")
                    if json_path.stem.startswith("predict_") else None)
        res = run_reconcile(json_path, manual_path=args.manual, date_tag=date_tag)
    except RuntimeError as e:
        print(f"对账失败: {e}")
        return 1

    s = res["stats"]
    print(f"对账完成：{s['resolved']}/{s['total']} 场有赛果，"
          f"HAD 命中率 {s['had_accuracy']:.4f}，对数损失 {s['log_loss']:.4f}")
    if s["n_bets"]:
        print(f"价值选项：{s['n_bets']} 注，命中率 {s['bet_hit_rate']:.4f}，"
              f"单位注 ROI {s['roi_unit']:+.4f}")
    if s["unresolved"]:
        print(f"⚠️  {s['unresolved']} 场无赛果，可 fetch-understat/fetch-ucl 更新，"
              f"或用 --manual scores.csv 补录")
    print(f"报告已写入:\n  {res['md']}\n  {res['json']}\n台账: {res['ledger']}")
    return 0


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #
def cmd_doctor(args: argparse.Namespace) -> int:
    """诊断队名匹配：列出未匹配/低置信球队并给出候选，帮助补别名。"""
    from src.ingest.jingcai_scraper import latest_snapshot, load_matches
    from src.pipeline import build_matcher

    settings = get_settings()
    settings.ensure_dirs()

    if args.odds:
        odds_path = Path(args.odds)
    else:
        odds_path = latest_snapshot()
    if odds_path is None or not Path(odds_path).exists():
        print("没有赔率快照，请先运行 python -m src.cli fetch-jingcai --online")
        return 1
    matches = load_matches(odds_path)
    print(f"赔率快照: {odds_path}（{len(matches)} 场）")

    matcher = build_matcher()
    issues = []
    seen: set[str] = set()
    for m in matches:
        # 只诊断已收录联赛（未收录联赛的球队即使匹配也会被跳过，属覆盖问题非队名问题）
        div = get_leagues().jc_name_to_div(getattr(m, "league", ""))
        if div is None:
            continue
        for cn, en in ((m.home_cn, m.home_en), (m.away_cn, m.away_en)):
            r = matcher.match(cn, en)
            if r.ok and r.confidence not in ("fuzzy", "none"):
                continue
            k = f"{m.match_num}|{cn}"
            if k in seen:
                continue
            seen.add(k)
            cands = matcher.suggest(cn, en, top=3)
            issues.append({
                "match_num": m.match_num, "league": m.league, "div": div,
                "team": cn, "en": en, "confidence": r.confidence,
                "matched": r.matched_name,
                "candidates": [f"{n}({s:.2f})" for n, s in cands],
            })

    matcher.save_cache()

    if not issues:
        print("\n✓ 所有已收录联赛的球队均已匹配（exact/alias/cache）。")
        return 0

    print(f"\n发现 {len(issues)} 个未匹配/低置信球队（仅已收录联赛）：\n")
    for it in issues:
        cands = " / ".join(it["candidates"]) if it["candidates"] else "（无相似英文候选，需补中文别名）"
        print(f"  {it['match_num']} {it['league']}({it['div']}) {it['team']} "
              f"(en={it['en']}, conf={it['confidence']})")
        print(f"      候选: {cands}")
    print("\n提示：把确认的映射补进 src/jingcai/team_names.py 的 CN_TO_EN，"
          "或确认数据源队名后重训。")
    return 0


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jingcai-predict",
        description="竞彩足球预测管线",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="检查环境与数据状态")
    p_status.set_defaults(func=cmd_status)

    p_t1 = sub.add_parser("fetch-tier1", help="下载/解析 football-data 并落盘")
    p_t1.add_argument("--online", action="store_true", help="联网下载镜像（否则用本地）")
    p_t1.add_argument("--force", action="store_true", help="强制重新下载镜像")
    p_t1.add_argument("--leagues", nargs="+", default=None, help="限定 div 代码，如 E0 D1")
    p_t1.add_argument("--seasons", nargs="+", default=None, help="限定赛季，如 2425 2526")
    p_t1.add_argument("--name", default=None, help="输出文件名（不含扩展名，默认自动）")
    p_t1.set_defaults(func=cmd_fetch_tier1)

    p_t1gh = sub.add_parser("fetch-tier1-gh",
                            help="从 jokecamp 镜像下载/解析更多联赛比分（扩覆盖）")
    p_t1gh.add_argument("--online", action="store_true", help="联网下载（否则用本地 dump）")
    p_t1gh.add_argument("--leagues", nargs="+", default=None,
                        help="限定 div 代码，如 N1 B1 P1 T1 G1 SC0 D2 F2")
    p_t1gh.set_defaults(func=cmd_fetch_tier1_gh)

    p_ucl = sub.add_parser("fetch-ucl", help="下载/解析欧冠数据（openfootball）")
    p_ucl.add_argument("--online", action="store_true", help="联网下载（否则用本地缓存）")
    p_ucl.add_argument("--force", action="store_true", help="强制重新下载")
    p_ucl.add_argument("--seasons", nargs="+", default=None,
                       help="限定赛季，如 2024-25 2025-26")
    p_ucl.set_defaults(func=cmd_fetch_ucl)

    p_eu = sub.add_parser("fetch-europa",
                          help="下载/解析欧罗巴+欧协联数据（openfootball）")
    p_eu.add_argument("--online", action="store_true", help="联网下载（否则用本地缓存）")
    p_eu.add_argument("--force", action="store_true", help="强制重新下载")
    p_eu.add_argument("--comps", nargs="+", choices=["UEL", "CONF"], default=None,
                      help="限定赛事（默认 UEL CONF）")
    p_eu.add_argument("--seasons", nargs="+", default=None,
                      help="限定赛季，如 2024-25 2025-26")
    p_eu.set_defaults(func=cmd_fetch_europa)

    p_us = sub.add_parser("fetch-understat", help="下载/解析 understat（比分+xG，补最新赛季）")
    p_us.add_argument("--online", action="store_true", help="联网下载（否则只查看本地）")
    p_us.add_argument("--leagues", nargs="+", default=None,
                      help="限定 understat 联赛，如 EPL Bundesliga")
    p_us.add_argument("--seasons", nargs="+", default=None,
                      help="限定赛季起始年，如 2025 2026")
    p_us.set_defaults(func=cmd_fetch_understat)

    p_af = sub.add_parser("fetch-apifootball",
                          help="下载 API-Football 赛果（巴甲/挪超/瑞超/芬超等 tier2）")
    p_af.add_argument("--online", action="store_true", help="联网下载（否则只查看本地）")
    p_af.add_argument("--leagues", nargs="+", default=None,
                      help="限定 div 代码，如 NOR1 SWE1 FIN1 BRA1")
    p_af.add_argument("--seasons", nargs="+", default=None,
                      help="限定赛季年，如 2023 2024 2025")
    p_af.set_defaults(func=cmd_fetch_apifootball)

    p_jc = sub.add_parser("fetch-jingcai", help="抓取竞彩场次并保存赔率快照")
    p_jc.add_argument("--online", action="store_true", help="联网抓取（否则用最新快照）")
    p_jc.add_argument("--pool", nargs="+", default=None,
                      help="玩法池，如 had hhad crs ttg hafu")
    p_jc.set_defaults(func=cmd_fetch_jingcai)

    p_train = sub.add_parser("train", help="训练 Dixon-Coles(含半全场) 并落盘")
    p_train.add_argument("--leagues", nargs="+", default=None, help="限定 div 代码")
    p_train.add_argument("--years", type=int, default=None,
                         help="训练使用近多少年（默认按联赛配置，一般 5）")
    p_train.add_argument("--half-life", type=float, default=None,
                         help="时间衰减半衰期(天)（默认按联赛配置）")
    p_train.add_argument("--shrinkage", type=float, default=None,
                         help="小样本收缩先验场数（默认取 settings.yaml 的 training.shrinkage_prior）")
    p_train.add_argument("--with-ml", action="store_true",
                         help="额外训练 LightGBM 特征模型（第三意见，较慢）")
    p_train.set_defaults(func=cmd_train)

    p_pred = sub.add_parser("predict", help="预测竞彩场次并产出价值报告")
    p_pred.add_argument("--odds", default=None, help="赔率快照 JSON；默认取最新")
    p_pred.add_argument("--leagues", nargs="+", default=None, help="限定载入的 div 代码")
    p_pred.add_argument("--edge", type=float, default=0.05, help="edge 阈值（默认 0.05）")
    p_pred.add_argument("--max-stake", type=float, default=0.02, help="单场仓位上限")
    p_pred.add_argument("--blend", type=float, default=None,
                        help="市场混合权重 0~1（默认取 settings.yaml 的 value.blend_weight）")
    p_pred.add_argument("--elo", type=float, default=None,
                        help="DC 与 Elo 混合时 DC 权重 0~1（默认取 settings.yaml 的 training.elo_blend_weight）")
    p_pred.add_argument("--ml-weight", type=float, default=None,
                        help="DC+Elo 与 ML 混合时 DC+Elo 权重 0~1（默认取 settings.yaml 的 training.ml_blend_weight）")
    p_pred.add_argument("--min-odds", type=float, default=None,
                        help="价值投注最低赔率（默认取 settings.yaml 的 value.min_odds）")
    p_pred.add_argument("--max-edge", type=float, default=None,
                        help="价值投注 edge 上限（默认取 settings.yaml 的 value.max_edge）")
    p_pred.add_argument("--crs-top", type=int, default=3, help="显示比分概率 Top N（默认 3）")
    p_pred.add_argument("--include-started", action="store_true",
                        help="连已开赛/已结束的场次也预测（默认跳过）")
    p_pred.add_argument("--round", choices=["first", "today", "all"], default="first",
                        help="按「期」筛选：first=最早一期(默认)，today=今天那期，all=全部")
    p_pred.add_argument("--match-num", nargs="+", default=None,
                        help="只预测指定编号场次，如 周六005 或 005（可多个，跨期查找）")
    p_pred.add_argument("--team", nargs="+", default=None,
                        help="只预测含指定球队的场次，中英文关键字子串匹配（可多个）")
    p_pred.set_defaults(func=cmd_predict)

    p_odds = sub.add_parser("fetch-odds", help="下载/解析历史赔率 dump 并落盘")
    p_odds.add_argument("--online", action="store_true", help="联网下载（否则用本地）")
    p_odds.add_argument("--via", choices=["proxy", "api", "zip"], default="proxy",
                        help="proxy=代理按需(推荐)；api=按需(受额度限制)；zip=整包(慢/易断)")
    p_odds.add_argument("--force", action="store_true", help="强制重新下载")
    p_odds.add_argument("--max-files", type=int, default=None, help="api 模式最多下载文件数")
    p_odds.add_argument("--leagues", nargs="+", default=None, help="限定 div 代码")
    p_odds.set_defaults(func=cmd_fetch_odds)

    p_bt = sub.add_parser("backtest", help="Walk-forward 回测并产出报告")
    p_bt.add_argument("--leagues", nargs="+", default=None, help="限定 div 代码")
    p_bt.add_argument("--years", type=int, default=None,
                      help="训练窗口年限（默认按联赛配置，一般 5）")
    p_bt.add_argument("--min-train", type=int, default=380, help="最小训练集场次")
    p_bt.add_argument("--refit", type=int, default=50, help="每多少场重拟合一次")
    p_bt.add_argument("--half-life", type=float, default=None,
                      help="时间衰减半衰期(天)（默认按联赛配置）")
    p_bt.add_argument("--shrinkage", type=float, default=None,
                      help="小样本收缩先验场数（默认取 settings.yaml 的 training.shrinkage_prior）")
    p_bt.add_argument("--ev", type=float, default=0.0, help="模拟投注 EV 阈值（默认 0）")
    p_bt.add_argument("--max-test", type=int, default=None, help="每联赛最多回测场次")
    p_bt.add_argument("--start-year", type=int, default=None, help="只回测该年起")
    p_bt.add_argument("--end-year", type=int, default=None, help="只回测到该年止")
    p_bt.add_argument("--no-odds", action="store_true", help="不合并赔率，只算准确率")
    p_bt.set_defaults(func=cmd_backtest)

    p_rec = sub.add_parser("reconcile", help="对账：预测 vs 实际比分，写投注台账")
    p_rec.add_argument("--json", default=None, help="预测报告 JSON；默认取最新一份")
    p_rec.add_argument("--date", default=None, help="按日期取 reports/predict_YYYYMMDD.json")
    p_rec.add_argument("--manual", default=None,
                       help="手动赛果 CSV（必须：match_num, ft_home, ft_away；"
                            "建议：date, ht_home, ht_away）")
    p_rec.set_defaults(func=cmd_reconcile)

    p_doc = sub.add_parser("doctor", help="诊断队名匹配，列出未匹配球队与候选")
    p_doc.add_argument("--odds", default=None, help="赔率快照 JSON；默认取最新")
    p_doc.set_defaults(func=cmd_doctor)

    p_rec2 = sub.add_parser("recommend", help="候选筛选（纸面）：筛可靠价值注，分级+仓位")
    p_rec2.add_argument("--odds", default=None, help="赔率快照 JSON；默认取最新")
    p_rec2.add_argument("--leagues", nargs="+", default=None, help="限定载入的 div 代码")
    p_rec2.add_argument("--edge", type=float, default=0.05, help="edge 阈值")
    p_rec2.add_argument("--max-stake", type=float, default=0.02, help="单注仓位上限")
    p_rec2.add_argument("--blend", type=float, default=None)
    p_rec2.add_argument("--elo", type=float, default=None)
    p_rec2.add_argument("--ml-weight", type=float, default=None)
    p_rec2.add_argument("--risk", choices=["conservative", "balanced", "aggressive"],
                        default=None, help="风险档位（默认取 settings.yaml）")
    p_rec2.add_argument("--bankroll", type=float, default=None, help="本金，用于算具体金额")
    p_rec2.add_argument("--crs-top", type=int, default=3)
    p_rec2.add_argument("--include-started", action="store_true")
    p_rec2.add_argument("--round", choices=["first", "today", "all"], default="first")
    p_rec2.add_argument("--match-num", nargs="+", default=None)
    p_rec2.add_argument("--team", nargs="+", default=None)
    p_rec2.set_defaults(func=cmd_recommend)

    p_pipe = sub.add_parser("pipeline", help="一键串联 fetch -> train -> predict")
    p_pipe.add_argument("--online", action="store_true", help="fetch 阶段联网")
    p_pipe.add_argument("--skip-fetch", action="store_true", help="跳过 fetch，仅 train+predict")
    p_pipe.add_argument("--leagues", nargs="+", default=None, help="限定 div 代码")
    p_pipe.add_argument("--years", type=int, default=None)
    p_pipe.add_argument("--half-life", type=float, default=None)
    p_pipe.add_argument("--shrinkage", type=float, default=None)
    p_pipe.add_argument("--with-ml", action="store_true")
    p_pipe.add_argument("--odds", default=None)
    p_pipe.add_argument("--edge", type=float, default=0.05)
    p_pipe.add_argument("--max-stake", type=float, default=0.02)
    p_pipe.add_argument("--blend", type=float, default=None)
    p_pipe.add_argument("--elo", type=float, default=None)
    p_pipe.add_argument("--ml-weight", type=float, default=None)
    p_pipe.add_argument("--min-odds", type=float, default=None)
    p_pipe.add_argument("--max-edge", type=float, default=None)
    p_pipe.add_argument("--crs-top", type=int, default=3)
    p_pipe.add_argument("--include-started", action="store_true")
    p_pipe.add_argument("--round", choices=["first", "today", "all"], default="first")
    p_pipe.add_argument("--match-num", nargs="+", default=None,
                        help="只预测指定编号场次（可多个）")
    p_pipe.add_argument("--team", nargs="+", default=None,
                        help="只预测含指定球队的场次（可多个）")
    p_pipe.set_defaults(func=cmd_pipeline)

    return parser


def main(argv: list[str] | None = None) -> int:
    _fix_console_encoding()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
