"""对账逻辑的离线单元测试（合成数据，不联网、不依赖磁盘数据）。"""
from __future__ import annotations

import copy
import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src import reconcile as R


def _pred(match_num: str, home: str, away: str, div: str = "E0",
          had: dict | None = None, value_bets: list | None = None,
          goal_line: float | None = None, score: str = "1:0",
          score_top: list | None = None, hhad: dict | None = None,
          ttg: dict | None = None, hafu: list | None = None,
          layers: dict | None = None) -> dict:
    data = {
        "match_num": match_num, "match_date": "2026-10-18",
        "league": "英超", "div": div, "home_cn": home, "away_cn": away,
        "home_matched": home, "away_matched": away,
        "had": had or {"胜": 0.5, "平": 0.3, "负": 0.2},
        "score_most_likely": score,
        "hhad_goal_line": goal_line,
        "value_bets": value_bets or [],
    }
    if score_top is not None:
        data["score_top"] = score_top
    if hhad is not None:
        data["hhad"] = hhad
    if ttg is not None:
        data["ttg"] = ttg
    if hafu is not None:
        data["hafu_top"] = hafu
    if layers:
        data.update(layers)
    return data


def test_had_and_score() -> None:
    index = {("E0", "2026-10-18", R._norm("Arsenal"), R._norm("Everton")): (2, 0)}
    rows = R.reconcile_predictions(
        [_pred("T001", "Arsenal", "Everton",
               had={"胜": 0.6, "平": 0.25, "负": 0.15}, score="2:0")], index)
    r = rows[0]
    assert r["resolved"], "应有赛果"
    assert r["actual"] == "胜", r
    assert r["had_pred"] == "胜" and r["had_hit"] is True, r
    assert r["score_hit"] is True, r
    print("  ✓ HAD 命中与最可能比分命中判定正确")


def test_value_bet_pnl() -> None:
    index = {("E0", "2026-10-18", R._norm("Arsenal"), R._norm("Everton")): (3, 1)}
    bets = [
        {"market": "HAD", "option": "胜", "odds": 2.0, "model_prob": 0.6,
         "implied_prob": 0.5, "edge": 0.1, "ev": 0.2, "stake_pct": 0.02},
        {"market": "HAD", "option": "负", "odds": 6.0, "model_prob": 0.1,
         "implied_prob": 0.16, "edge": -0.06, "ev": -0.4, "stake_pct": 0.0},
    ]
    rows = R.reconcile_predictions([_pred("T001", "Arsenal", "Everton", value_bets=bets)],
                                   index)
    b = rows[0]["value_bets"]
    assert b[0]["hit"] is True and abs(b[0]["pnl_unit"] - 1.0) < 1e-9, b[0]
    assert b[1]["hit"] is False and abs(b[1]["pnl_unit"] - (-1.0)) < 1e-9, b[1]
    stats = R.summarize(rows)
    assert stats["n_bets"] == 2
    assert abs(stats["pnl_unit"] - 0.0) < 1e-9, stats
    print("  ✓ 价值选项盈亏与汇总计算正确")


def test_hhad_pnl() -> None:
    # 主队让 1 球（goal_line=-1），实际 2:0 -> 让球后 1:0 主队仍胜
    index = {("E0", "2026-10-18", R._norm("A"), R._norm("B")): (2, 0)}
    bets = [{"market": "HHAD", "option": "胜", "odds": 1.8, "model_prob": 0.5,
             "implied_prob": 0.5, "edge": 0.0, "ev": -0.1, "stake_pct": 0.01}]
    rows = R.reconcile_predictions(
        [_pred("T001", "A", "B", value_bets=bets, goal_line=-1.0)], index)
    b = rows[0]["value_bets"][0]
    assert b["hit"] is True, b
    # 实际 1:0（让球后）主队胜，但若让 2 球则走盘/负
    bets2 = [{"market": "HHAD", "option": "胜", "odds": 1.8, "model_prob": 0.5,
              "implied_prob": 0.5, "edge": 0.0, "ev": -0.1, "stake_pct": 0.01}]
    rows2 = R.reconcile_predictions(
        [_pred("T001", "A", "B", value_bets=bets2, goal_line=-2.0)], index)
    assert rows2[0]["value_bets"][0]["hit"] is False, rows2[0]
    print("  ✓ 让球胜平负盈亏判定正确")


def test_unresolved() -> None:
    rows = R.reconcile_predictions([_pred("T002", "X", "Y")], {})
    assert rows[0]["resolved"] is False, rows[0]
    stats = R.summarize(rows)
    assert stats["resolved"] == 0 and stats["unresolved"] == 1
    assert stats["n_bets"] == 0
    print("  ✓ 无赛果场次标记为待补")


def test_ledger_dedup(tmp=None) -> None:
    index = {("E0", "2026-10-18", R._norm("A"), R._norm("B")): (1, 0)}
    bets = [{"market": "HAD", "option": "胜", "odds": 2.0, "model_prob": 0.6,
             "implied_prob": 0.5, "edge": 0.1, "ev": 0.2, "stake_pct": 0.02}]
    rows = R.reconcile_predictions([_pred("T001", "A", "B", value_bets=bets)], index)
    lr = R.ledger_rows(rows)
    assert len(lr) == 1 and lr[0]["hit"] is True
    print("  ✓ 台账行展开正确")


def test_all_markets() -> None:
    """五种玩法 + 模型分层一次结算。"""
    index = {("E0", "2026-10-18", R._norm("A"), R._norm("B")): {
        "ft_home": 3, "ft_away": 1, "ht_home": 1, "ht_away": 1,
    }}
    pred = _pred(
        "T010", "A", "B",
        had={"胜": 0.6, "平": 0.25, "负": 0.15},
        score="3:1",
        score_top=[{"score": "3:1", "prob": 0.2},
                   {"score": "2:1", "prob": 0.15},
                   {"score": "2:0", "prob": 0.1}],
        goal_line=-1.0,
        hhad={"胜": 0.5, "平": 0.3, "负": 0.2},
        ttg={"0": 0.05, "1": 0.1, "2": 0.15, "3": 0.2,
             "4": 0.3, "5": 0.15, "6": 0.05, "7+": 0.0},
        hafu=[["平/胜", 0.2], ["胜/胜", 0.15]],
        layers={
            "had_dc": {"胜": 0.55, "平": 0.3, "负": 0.15},
            "elo_had": {"胜": 0.45, "平": 0.3, "负": 0.25},
            "ml_had": {"胜": 0.7, "平": 0.2, "负": 0.1},
        },
    )
    r = R.reconcile_predictions([pred], index)[0]
    assert r["resolved"], r
    assert r["actual"] == "胜" and r["had_hit"] is True, r
    assert r["hhad_actual"] == "胜" and r["hhad_hit"] is True, r
    assert r["score_hit"] is True and r["score_top3_hit"] is True, r
    assert r["ttg_actual"] == "4" and r["ttg_hit"] is True, r
    assert r["half_full_actual"] == "平/胜" and r["half_full_hit"] is True, r
    assert r["layer_hits"] == {"HAD_DC": True, "HAD_ELO": True, "HAD_ML": True}, r

    stats = R.summarize([r])
    for market in ("HAD", "HHAD", "SCORE_TOP1", "SCORE_TOP3",
                   "TOTAL_GOALS", "HALF_FULL", "HAD_DC", "HAD_ELO", "HAD_ML"):
        assert stats["markets"][market]["n"] == 1, (market, stats["markets"])
        assert stats["markets"][market]["accuracy"] == 1.0, (market, stats["markets"])
    print("  ✓ 五种玩法与模型分层结算正确")


def test_manual_csv_with_ht_and_date() -> None:
    """手动 CSV 支持半场比分，并按 date+match_num 区分不同日期。"""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "results.csv"
        path.write_text(
            "date,match_num,ft_home,ft_away,ht_home,ht_away\n"
            "2026-10-18,T001,2,1,1,1\n"
            "2026-10-19,T001,0,0,0,0\n",
            encoding="utf-8",
        )
        manual = R.load_manual_results(path)
        assert manual[("2026-10-18", "T001")]["ft_home"] == 2
        assert manual[("2026-10-19", "T001")]["ft_home"] == 0
        assert manual[("2026-10-18", "T001")]["ht_home"] == 1

        rows = R.reconcile_predictions([_pred("T001", "A", "B",
                                              hafu=[["平/胜", 0.2]])], {}, manual)
        assert rows[0]["ft_home"] == 2 and rows[0]["ft_away"] == 1, rows[0]
        assert rows[0]["half_full_actual"] == "平/胜", rows[0]
        assert rows[0]["half_full_hit"] is True, rows[0]
    print("  ✓ 手动 CSV 的半场比分与跨日期匹配正确")


def test_missing_ht_marks_pending_half_full() -> None:
    """没有半场比分时，半全场应标记为无法结算，而不是判负。"""
    index = {("E0", "2026-10-18", R._norm("A"), R._norm("B")): (1, 0)}
    r = R.reconcile_predictions(
        [_pred("T011", "A", "B", hafu=[["胜/胜", 0.3]])], index)[0]
    assert r["half_full_actual"] is None, r
    assert r["half_full_hit"] is None, r
    stats = R.summarize([r])
    assert stats["markets"]["HALF_FULL"]["n"] == 0, stats
    print("  ✓ 缺半场比分时半全场不参与统计")


def test_manual_no_cross_date_fallback() -> None:
    """有日期的 CSV 不能再按 match_num 跨日期串场。"""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "results.csv"
        path.write_text(
            "date,match_num,league,home_cn,away_cn,ft_home,ft_away,ht_home,ht_away\n"
            "2026-10-20,周一003,意甲,A,B,0,3,0,2\n",
            encoding="utf-8",
        )
        manual = R.load_manual_results(path)
        assert ("周一003",) not in manual, manual

        p_wrong_date = _pred("周一003", "A", "B")
        p_wrong_date["match_date"] = "2026-10-27"
        rows = R.reconcile_predictions([p_wrong_date], {}, manual)
        assert rows[0]["resolved"] is False, rows[0]

        p_exact = _pred("周一003", "A", "B")
        p_exact["match_date"] = "2026-10-20"
        rows2 = R.reconcile_predictions([p_exact], {}, manual)
        assert rows2[0]["resolved"] is True, rows2[0]
        assert rows2[0]["ft_home"] == 0 and rows2[0]["ft_away"] == 3, rows2[0]
    print("  ✓ 手动赛果不跨日期串场")


def test_ledger_upsert() -> None:
    """同一 date+match_num+market+option 重新对账时应覆盖旧台账行。"""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "bet_ledger.parquet"
        base = {
            "date": "2026-10-27",
            "match_num": "周一003",
            "league": "西甲",
            "div": "SP1",
            "home_cn": "A",
            "away_cn": "B",
            "resolved": True,
            "value_bets": [{
                "market": "HAD", "option": "胜", "odds": 2.0,
                "model_prob": 0.5, "implied_prob": 0.4,
                "edge": 0.1, "ev": 0.2, "stake_pct": 0.02,
                "hit": False, "pnl_unit": -1.0, "pnl_pct": -0.02,
            }],
        }
        R.append_ledger([base], path)
        old = pd.read_parquet(path)
        assert len(old) == 1 and bool(old.iloc[0]["hit"]) is False

        fixed = copy.deepcopy(base)
        fixed["value_bets"][0].update(
            {"hit": True, "pnl_unit": 1.0, "pnl_pct": 0.02})
        R.append_ledger([fixed], path)
        new = pd.read_parquet(path)
        assert len(new) == 1, new
        assert bool(new.iloc[0]["hit"]) is True, new
        assert abs(float(new.iloc[0]["pnl_unit"]) - 1.0) < 1e-9, new
    print("  ✓ 台账同键覆盖更新")


def main() -> int:
    print("== 测试：对账 HAD/比分 ==")
    test_had_and_score()
    print("== 测试：价值选项盈亏 ==")
    test_value_bet_pnl()
    test_hhad_pnl()
    print("== 测试：五种玩法/手动赛果 ==")
    test_all_markets()
    test_manual_csv_with_ht_and_date()
    test_manual_no_cross_date_fallback()
    test_missing_ht_marks_pending_half_full()
    print("== 测试：台账 ==")
    test_ledger_dedup()
    test_ledger_upsert()
    print("== 测试：无赛果 ==")
    test_unresolved()
    print("\n全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
