"""对账逻辑的离线单元测试（合成数据，不联网、不依赖磁盘数据）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src import reconcile as R


def _pred(match_num: str, home: str, away: str, div: str = "E0",
          had: dict | None = None, value_bets: list | None = None,
          goal_line: float | None = None, score: str = "1:0") -> dict:
    return {
        "match_num": match_num, "match_date": "2026-10-18",
        "league": "英超", "div": div, "home_cn": home, "away_cn": away,
        "home_matched": home, "away_matched": away,
        "had": had or {"胜": 0.5, "平": 0.3, "负": 0.2},
        "score_most_likely": score,
        "hhad_goal_line": goal_line,
        "value_bets": value_bets or [],
    }


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


def main() -> int:
    print("== 测试：对账 HAD/比分 ==")
    test_had_and_score()
    print("== 测试：价值选项盈亏 ==")
    test_value_bet_pnl()
    test_hhad_pnl()
    print("== 测试：无赛果/台账 ==")
    test_unresolved()
    test_ledger_dedup()
    print("\n全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
