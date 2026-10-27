"""竞彩赛果抓取/合并的离线测试（不联网）。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src.ingest import jingcai_results as R


def _row(**kwargs) -> dict:
    base = {
        "matchId": 2042231,
        "matchNumStr": "周日019",
        "matchDate": "2026-10-25",
        "leagueNameAbbr": "西甲",
        "homeTeam": "塞尔塔",
        "awayTeam": "贝蒂斯",
        "sectionsNo1": "0:0",
        "sectionsNo999": "0:0",
        "winFlag": "D",
    }
    base.update(kwargs)
    return base


def test_parse_score() -> None:
    assert R.parse_score("2:1") == (2, 1)
    assert R.parse_score(" 0 : 0 ") == (0, 0)
    assert R.parse_score("") is None
    assert R.parse_score("-") is None
    assert R.parse_score("延期") is None
    print("  ✓ 比分解析")


def test_parse_match() -> None:
    r = R.parse_match(_row())
    assert r is not None
    assert r.key == ("2026-10-25", "周日019")
    assert r.ft == "0:0" and r.ht == "0:0"
    assert r.league == "西甲" and r.home_cn == "塞尔塔"
    assert R.parse_match(_row(sectionsNo999="")) is None
    no_ht = R.parse_match(_row(sectionsNo1=""))
    assert no_ht is not None and no_ht.ht_home is None and no_ht.ht == ""
    assert R.parse_match(_row(matchDate="bad")) is None
    print("  ✓ 单场赛果解析")


def test_merge_fill_conflict_overwrite() -> None:
    existing = pd.DataFrame([
        # 已有手动比分，且与接口不同 -> 冲突
        {"date": "2026-10-25", "match_num": "周日001", "league": "英超",
         "home_cn": "A", "away_cn": "B", "ft_home": "1", "ft_away": "0",
         "ht_home": "1", "ht_away": "0"},
        # 已有空行 -> 补全
        {"date": "2026-10-25", "match_num": "周日002", "league": "西甲",
         "home_cn": "C", "away_cn": "D", "ft_home": "", "ft_away": "",
         "ht_home": "", "ht_away": ""},
    ], columns=R.RESULT_COLUMNS)

    new = [
        R.JcResult(None, "周日001", "2026-10-25", "英超", "A", "B", 2, 1, 1, 1),
        R.JcResult(None, "周日002", "2026-10-25", "西甲", "C", "D", 3, 3, 1, 2),
        R.JcResult(None, "周日003", "2026-10-25", "意甲", "E", "F", 0, 2, 0, 1),
    ]

    merged, stats, conflicts = R.merge_results(existing, new)
    assert stats == {"added": 1, "filled": 1, "updated": 0,
                     "unchanged": 0, "conflicts": 1}, stats
    assert len(merged) == 3
    by_num = {r["match_num"]: r for r in merged.to_dict(orient="records")}
    assert str(by_num["周日001"]["ft_home"]) == "1"  # 保留手动值
    assert str(by_num["周日002"]["ft_home"]) == "3"  # 补全
    assert str(by_num["周日003"]["ft_away"]) == "2"  # 新增
    assert conflicts[0]["match_num"] == "周日001"

    merged2, stats2, conflicts2 = R.merge_results(existing, new, overwrite=True)
    by_num2 = {r["match_num"]: r for r in merged2.to_dict(orient="records")}
    assert str(by_num2["周日001"]["ft_home"]) == "2", by_num2["周日001"]
    assert stats2["updated"] == 1 and not conflicts2, (stats2, conflicts2)
    print("  ✓ 默认补全/冲突保留，overwrite 覆盖")


def test_csv_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "results.csv"
        df = pd.DataFrame([
            {"date": "2026-10-25", "match_num": "周日001", "league": "英超",
             "home_cn": "A", "away_cn": "B", "ft_home": 2, "ft_away": 1,
             "ht_home": 1, "ht_away": 0},
            {"date": "2026-10-25", "match_num": "周日002", "league": "西甲",
             "home_cn": "C", "away_cn": "D", "ft_home": 0, "ft_away": 0,
             "ht_home": pd.NA, "ht_away": pd.NA},
        ], columns=R.RESULT_COLUMNS)
        for col in R.SCORE_COLUMNS:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

        R.write_results_csv(df, path)
        text = path.read_text(encoding="utf-8")
        assert "2,1,1,0" in text, text
        # 空半场写成空字段，而不是 nan / <NA>
        assert "0,0,," in text, text

        loaded = R.load_results_csv(path)
        assert len(loaded) == 2
        assert loaded.iloc[0]["date"] == "2026-10-25"
        assert loaded.iloc[1]["ht_home"] == ""
    print("  ✓ CSV 往返与空比分")


def test_prediction_dates() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "predict_20261024.json").write_text("{}", encoding="utf-8")
        (root / "predict_20261025.json").write_text("{}", encoding="utf-8")
        (root / "predict_not_a_date.json").write_text("{}", encoding="utf-8")
        assert R.prediction_dates(root) == ["2026-10-24", "2026-10-25"]
        assert R.latest_prediction_date(root) == "2026-10-25"
    print("  ✓ 预测日期发现")


def test_date_range() -> None:
    assert R.date_range("20261024", "20261026") == [
        "2026-10-24", "2026-10-25", "2026-10-26"]
    assert R.normalize_date("2026/10/25") == "2026-10-25"
    print("  ✓ 日期区间")


def main() -> int:
    print("== 测试：竞彩赛果抓取/合并 ==")
    test_parse_score()
    test_parse_match()
    test_merge_fill_conflict_overwrite()
    test_csv_roundtrip()
    test_prediction_dates()
    test_date_range()
    print("\n全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
