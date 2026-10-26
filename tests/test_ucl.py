"""欧冠数据接入测试（离线）。

覆盖：
    1. cl.txt 解析：普通 / 加时 / 点球 / 无半场比分 / 跨年日期推断
    2. 队名归一化
    3. 队名匹配不被英文缩写前缀误导
    4. 已抓取的 ucl_matches.parquet 完整性
    5. UCL 训练 + 预测端到端
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src.ingest.ucl import parse_season, _parse_scores, load_dataset
from src.ingest.ucl_names import normalize_team, strip_country
from src.jingcai.team_names import TeamMatcher

SAMPLE = """= UEFA Champions League 2023/24

▪ Group, Matchday 1
  Tue Sep 19 2023
    18:45  AC Milan (ITA)          v Newcastle United FC (ENG)  0-0
    21:00  FC Bayern München (GER) v Manchester United FC (ENG)  4-3 (2-0)

▪ Finals, Round of 16
  Tue Mar 12
    21:00  Arsenal FC (ENG)        v FC Porto (POR)           4-2 pen. 1-0 a.e.t. (1-0, 1-0)

▪ Finals, Final
  Sat Jun 1
    21:00  Borussia Dortmund (GER) v Real Madrid CF (ESP)     0-2 (0-0)
"""


def test_parse_scores() -> None:
    # 普通：正文是 90 分钟比分，括号是半场
    assert _parse_scores(4, 3, " (2-0)") == ((4, 3), (2, 0))
    # 加时：括号两段 = (90', 半场)
    assert _parse_scores(4, 1, " a.e.t. (3-1, 1-0)") == ((3, 1), (1, 0))
    # 点球：正文是点球比分，括号两段 = (90', 半场)
    assert _parse_scores(4, 2, " pen. 1-0 a.e.t. (1-0, 1-0)") == ((1, 0), (1, 0))
    # 点球且加时无进球：只有一段括号
    assert _parse_scores(8, 7, " pen. 0-0 a.e.t. (0-0)") == ((0, 0), (0, 0))
    # 无括号（半场未知）
    assert _parse_scores(0, 0, "") == ((0, 0), None)
    print("  ✓ 比分解析（普通/加时/点球）")


def test_parse_season() -> None:
    rows = parse_season(SAMPLE, "2023-24")
    assert len(rows) == 4, rows
    assert [r["season"] for r in rows] == ["2023-24"] * 4
    assert (rows[0]["date"].month, rows[0]["date"].day) == (9, 19)
    assert rows[0]["date"].year == 2023
    assert rows[0]["ht_home"] is None  # 0-0 没有半场
    # 加时/点球只取 90 分钟
    ars = rows[2]
    assert (ars["ft_home"], ars["ft_away"]) == (1, 0)
    assert (ars["ht_home"], ars["ht_away"]) == (1, 0)
    # 跨年日期：6 月决赛应推断为次年
    final = rows[3]
    assert (final["date"].year, final["date"].month, final["date"].day) == (2024, 6, 1)
    print("  ✓ cl.txt 解析（含跨年日期）")


def test_names() -> None:
    assert strip_country("FC Bayern München (GER)") == "FC Bayern München"
    assert normalize_team("FC Bayern München (GER)") == "Bayern Munich"
    assert normalize_team("Real Madrid CF (ESP)") == "Real Madrid"
    assert normalize_team("Galatasaray SK (TUR)") == "Galatasaray"
    assert normalize_team("Sporting Clube de Portugal (POR)") == "Sporting Lisbon"
    assert normalize_team("PSV (NED)") == "PSV Eindhoven"
    print("  ✓ 队名归一化")


def test_matcher_no_false_prefix() -> None:
    # 只有 Viktoria Plzen 时，VIK 不能把「维京」吃掉
    m = TeamMatcher(["Viktoria Plzen", "Aston Villa"])
    r = m.match("维京", "VIK")
    assert r.matched_name != "Viktoria Plzen", r
    assert m.match("维拉", "ASV").matched_name == "Aston Villa"
    print("  ✓ 缩写前缀不误配（维京/维拉）")


def test_dataset_integrity() -> None:
    try:
        df = load_dataset()
    except FileNotFoundError:
        print("  [跳过] 未抓取欧冠数据")
        return
    assert len(df) > 1900, len(df)
    assert df["season"].nunique() >= 15
    assert df.duplicated(["date", "home_team", "away_team"]).sum() == 0
    bad = df[(df.ht_home.notna()) &
             ((df.ht_home > df.ft_home) | (df.ht_away > df.ft_away))]
    assert bad.empty, f"半场进球大于 90 分钟: {len(bad)} 行"
    assert set(df["league_code"]) == {"UCL"}
    print(f"  ✓ 数据集完整（{len(df)} 场 / {df['season'].nunique()} 季）")


def test_train_predict() -> None:
    from src.pipeline import (build_matcher, load_training_data, predict_matches,
                              train_leagues)
    from src.ingest.jingcai_scraper import JcMatch

    try:
        load_dataset()
    except FileNotFoundError:
        print("  [跳过] 未抓取欧冠数据")
        return

    models = train_leagues(leagues=["UCL"], save=False, verbose=False)
    assert "UCL" in models, "UCL 训练失败"

    matcher = build_matcher(load_training_data())
    match = JcMatch(
        match_id=1, match_num="周三005", match_date="2026-10-21",
        match_time="20:00:00", league="欧冠", league_code="UCL",
        home_cn="里尔", away_cn="加拉塔萨",
        home_en="LIL", away_en="GAL", home_rank="", away_rank="",
        had={"h": "1.81", "d": "3.65", "a": "3.30"},
        hhad={"h": "3.40", "d": "3.50", "a": "1.95",
              "goalLine": "-1", "goalLineValue": "-1.00"},
    )
    rows = predict_matches([match], models, matcher, edge_threshold=0.05,
                           skip_started=False)
    r = rows[0]
    assert not r.get("skipped"), r.get("skipped")
    assert r["div"] == "UCL"
    assert abs(sum(r["had"].values()) - 1) < 1e-6
    assert r["score_most_likely"] and ":" in r["score_most_likely"]
    print("  ✓ UCL 训练 + 预测跑通")


def main() -> int:
    print("== 测试：欧冠比分解析 ==")
    test_parse_scores()
    print("== 测试：欧冠赛季解析 ==")
    test_parse_season()
    print("== 测试：队名归一化 ==")
    test_names()
    print("== 测试：缩写前缀 ==")
    test_matcher_no_false_prefix()
    print("== 测试：数据集完整性 ==")
    test_dataset_integrity()
    print("== 测试：UCL 训练+预测 ==")
    test_train_predict()
    print("\n全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
