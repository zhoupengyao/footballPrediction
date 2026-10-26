"""候选筛选（纸面）逻辑的单元测试（合成数据，无网络/磁盘依赖）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src import recommend as R

# 最小推荐配置（与 settings.yaml 的 conservative 档对齐）
CFG = {
    "risk": "conservative",
    "min_edge": 0.06,
    "min_odds": 1.50,
    "max_odds": 6.00,
    "min_model_prob": 0.30,
    "max_model_prob": 0.70,
    "single_stake_pct": 0.02,
    "daily_stake_pct": 0.05,
    "max_bets": 3,
    "reliable_leagues": ["E0", "SP1"],
    "markets": ["HAD"],
}


def _row(div, bets):
    return {
        "match_num": "T001", "league": "联赛", "div": div,
        "home_cn": "A", "away_cn": "B", "skipped": None,
        "value_bets": bets,
    }


def _bet(market="HAD", option="胜", odds=2.0, mp=0.55, ip=0.45,
         edge=0.10, ev=0.10):
    return {"market": market, "option": option, "odds": odds,
            "model_prob": mp, "implied_prob": ip, "edge": edge, "ev": ev}


def test_classify_reliable_vs_unreliable() -> None:
    rows = [
        _row("E0", [_bet(edge=0.10, ev=0.12)]),   # 可靠联赛 + 高EV -> 推荐
        _row("FIN1", [_bet(edge=0.10, ev=0.12)]),  # 不可靠联赛 -> 观察
    ]
    recs, obs = R.classify(rows, CFG)
    assert len(recs) == 1 and recs[0]["div"] == "E0"
    assert len(obs) == 1 and obs[0]["div"] == "FIN1"
    print("  ✓ 可靠/不可靠联赛分级正确")


def test_classify_low_ev_to_observe() -> None:
    rows = [_row("E0", [_bet(edge=0.08, ev=0.02)])]  # edge 够但 EV 太低 -> 观察
    recs, obs = R.classify(rows, CFG)
    assert not recs and len(obs) == 1
    assert "EV" in obs[0]["reason"]
    print("  ✓ 低 EV 归为观察")


def test_classify_odds_prob_range() -> None:
    rows = [
        _row("E0", [_bet(odds=1.20, edge=0.10, ev=0.12)]),   # 低赔率 -> 观察
        _row("E0", [_bet(mp=0.15, edge=0.10, ev=0.12)]),     # 概率过低 -> 观察
    ]
    recs, obs = R.classify(rows, CFG)
    assert not recs and len(obs) == 2
    print("  ✓ 赔率/概率区间过滤正确")


def test_classify_market_filter() -> None:
    rows = [_row("E0", [_bet(market="HHAD", edge=0.12, ev=0.15)])]  # HHAD 未纳入 -> 观察
    recs, obs = R.classify(rows, CFG)
    assert not recs and len(obs) == 1
    assert "HHAD" in obs[0]["reason"]
    print("  ✓ 非白名单玩法（HHAD）归为观察")


def test_allocate_stakes_cap() -> None:
    # 3 注都触顶 2% -> 合计 6% > 日上限 5%，需按比例缩到 5%
    recs = [
        {"edge": 0.15, "odds": 2.5, "model_prob": 0.5, "ev": 0.25},
        {"edge": 0.12, "odds": 2.3, "model_prob": 0.5, "ev": 0.15},
        {"edge": 0.10, "odds": 2.1, "model_prob": 0.5, "ev": 0.10},
    ]
    out = R.allocate_stakes(recs, CFG)
    total = sum(x["stake_pct"] for x in out)
    assert abs(total - CFG["daily_stake_pct"]) < 1e-9, total
    assert all(x["stake_pct"] <= CFG["single_stake_pct"] + 1e-9 for x in out)
    print(f"  ✓ 日总仓位缩放（合计 {total:.4f}）")


def test_max_bets_limit() -> None:
    recs = [{"edge": 0.10 + i * 0.01, "odds": 2.0, "model_prob": 0.5,
             "ev": 0.10 + i * 0.01} for i in range(10)]
    out = R.allocate_stakes(recs, CFG)
    assert len(out) == CFG["max_bets"]
    print("  ✓ 最多候选注数限制")


def main() -> int:
    print("== 测试：分级过滤 ==")
    test_classify_reliable_vs_unreliable()
    test_classify_low_ev_to_observe()
    test_classify_odds_prob_range()
    test_classify_market_filter()
    print("== 测试：仓位 ==")
    test_allocate_stakes_cap()
    test_max_bets_limit()
    print("\n全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
