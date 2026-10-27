"""命中分析/概率校准的离线测试（合成记录，不依赖网络）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src import analysis as A


def _record(num: str, p_home: float, actual: str, hit: bool,
            edge: float = 0.06, odds: float = 2.0) -> dict:
    probs = {
        "home": p_home,
        "draw": (1 - p_home) / 2,
        "away": (1 - p_home) / 2,
    }
    hhad_probs = {"home": 0.5, "draw": 0.3, "away": 0.2}
    return {
        "status": "settled",
        "prediction_timing": "pre_match",
        "date": "2026-10-25",
        "match_num": num,
        "league": {"div": "E0", "name": "英超"},
        "home": {"cn": "A"},
        "away": {"cn": "B"},
        "result": {"ft": "2:1", "ht": "1:0", "had": actual,
                   "hhad": "home", "total_goals": "3", "half_full": "胜/胜"},
        "prediction": {
            "markets": {
                "HAD": {"probs": probs, "predicted": "home",
                        "actual": actual, "hit": hit},
                "HHAD": {"probs": hhad_probs, "predicted": "home",
                         "actual": "home", "hit": True},
                "SCORE": {
                    "top": [{"score": "2:1", "prob": 0.2},
                            {"score": "1:1", "prob": 0.15}],
                    "predicted": "2:1", "actual": "2:1",
                    "top1_hit": True, "top3_hit": True,
                },
                "TOTAL_GOALS": {
                    "probs": {"2": 0.2, "3": 0.3, "4": 0.1},
                    "predicted": "3", "actual": "3", "hit": True,
                },
                "HALF_FULL": {
                    "top": [{"label": "胜/胜", "prob": 0.3}],
                    "predicted": "胜/胜", "actual": "胜/胜", "hit": True,
                },
            },
            "model_layers": {
                "DC": {"probs": probs, "predicted": "home", "hit": hit},
                "Elo": {"probs": probs, "predicted": "home", "hit": hit},
                "ML": {"probs": probs, "predicted": "home", "hit": hit},
            },
            "value_bets": [{
                "market": "HAD", "option": "home", "hit": hit,
                "edge": edge, "odds": odds, "pnl_unit": 1.0 if hit else -1.0,
            }],
        },
    }


def test_overall_and_bins() -> None:
    records = [
        _record("001", 0.35, "away", False, edge=0.06, odds=1.9),
        _record("002", 0.45, "home", True, edge=0.12, odds=3.5),
        _record("003", 0.55, "draw", False, edge=0.20, odds=5.0),
        _record("004", 0.65, "home", True, edge=0.08, odds=2.2),
    ]
    result = A.analyze_records(records)
    had = result["markets"]["HAD"]
    assert had["n"] == 4 and had["hits"] == 2, had
    assert had["accuracy"] == 0.5, had
    assert abs(had["avg_confidence"] - 0.5) < 1e-9, had
    assert had["confusion"]["home"] == {"home": 2, "draw": 1, "away": 1}, had
    assert abs(had["ece"] - 0.45) < 1e-9, had["ece"]

    bins = {b["label"]: b for b in had["bins"]}
    assert bins["30–40%"]["n"] == 1 and bins["30–40%"]["hits"] == 0, bins
    assert bins["40–50%"]["n"] == 1 and bins["40–50%"]["hits"] == 1, bins
    assert bins["50–60%"]["n"] == 1 and bins["50–60%"]["hits"] == 0, bins
    assert bins["60–70%"]["n"] == 1 and bins["60–70%"]["hits"] == 1, bins

    assert result["sample"]["pre_match_settled"] == 4, result["sample"]
    assert result["markets"]["SCORE"]["hits"] == 4, result["markets"]["SCORE"]
    assert result["layers"]["DC"]["n"] == 4, result["layers"]["DC"]
    print("  ✓ 总览、分箱、ECE、混淆矩阵")


def test_value_bins() -> None:
    records = [
        _record("001", 0.35, "away", False, edge=0.06, odds=1.9),
        _record("002", 0.45, "home", True, edge=0.12, odds=3.5),
        _record("003", 0.55, "draw", False, edge=0.20, odds=5.0),
    ]
    value = A.analyze_records(records)["value"]
    assert value["n"] == 3 and value["hits"] == 1, value
    edge_bins = {x["label"]: x for x in value["by_edge"]}
    assert edge_bins["5–10%"]["n"] == 1 and edge_bins["10–15%"]["n"] == 1, edge_bins
    odds_bins = {x["label"]: x for x in value["by_odds"]}
    assert odds_bins["<2.0"]["hits"] == 0, odds_bins
    assert odds_bins["3.0–4.0"]["hits"] == 1, odds_bins
    assert odds_bins["4.0+"]["n"] == 1, odds_bins
    print("  ✓ 价值注 edge / 赔率分箱")


def test_actual_rank_and_empty() -> None:
    records = [
        _record("001", 0.55, "home", True),
        _record("002", 0.45, "draw", False),
    ]
    had = A.analyze_records(records)["markets"]["HAD"]
    assert sum((had["actual_rank"] or {}).values()) == 2, had["actual_rank"]
    assert (had["actual_rank"] or {}).get("1") == 1, had["actual_rank"]

    empty = A.analyze_records([])
    assert empty["sample"]["pre_match_settled"] == 0
    assert empty["markets"]["HAD"]["n"] == 0
    assert all(b["n"] == 0 for b in empty["markets"]["HAD"]["bins"])
    print("  ✓ 实际排名与空样本")


def test_post_kickoff_excluded() -> None:
    rec = _record("001", 0.55, "home", True)
    rec["prediction_timing"] = "post_kickoff"
    result = A.analyze_records([rec])
    assert result["sample"]["pre_match_settled"] == 0
    assert result["sample"]["excluded_post_kickoff"] == 1
    print("  ✓ 开赛后补跑排除")


def test_score_hit_detail() -> None:
    """比分 Top3 组合：Top1 未中但 Top3 中也要算命中，并分析命中比分概率。"""
    a = _record("001", 0.35, "away", False)
    a["result"]["ft"] = "2:1"
    a["prediction"]["markets"]["SCORE"] = {
        "top": [{"score": "1:0", "prob": 0.20},
                {"score": "2:1", "prob": 0.12},
                {"score": "0:0", "prob": 0.08}],
        "predicted": "1:0", "actual": "2:1",
        "top1_hit": False, "top3_hit": True,
    }

    b = _record("002", 0.45, "home", True)
    b["result"]["ft"] = "2:1"
    b["prediction"]["markets"]["SCORE"] = {
        "top": [{"score": "2:1", "prob": 0.14},
                {"score": "1:0", "prob": 0.10},
                {"score": "0:1", "prob": 0.08}],
        "predicted": "2:1", "actual": "2:1",
        "top1_hit": True, "top3_hit": True,
    }

    c = _record("003", 0.55, "draw", False)
    c["result"]["ft"] = "3:0"
    c["prediction"]["markets"]["SCORE"] = {
        "top": [{"score": "1:0", "prob": 0.20},
                {"score": "2:0", "prob": 0.12},
                {"score": "0:1", "prob": 0.08}],
        "predicted": "1:0", "actual": "3:0",
        "top1_hit": False, "top3_hit": False,
    }

    score = A.analyze_records([a, b, c])["markets"]["SCORE"]
    assert score["label"] == "比分 Top3", score
    assert score["n"] == 3 and score["hits"] == 2, score
    assert abs(score["accuracy"] - 2 / 3) < 1e-9, score

    detail = score["hit_detail"]
    assert detail["n"] == 2, detail
    assert abs(detail["avg_actual_prob"] - 0.13) < 1e-9, detail
    bins = {x["label"]: x["n"] for x in detail["prob_bins"]}
    assert bins["10–15%"] == 2, bins
    ranks = {x["rank"]: x for x in detail["by_rank"]}
    assert ranks[1]["n"] == 1 and ranks[2]["n"] == 1, ranks
    assert abs(ranks[1]["avg_actual_prob"] - 0.14) < 1e-9, ranks
    assert abs(ranks[2]["avg_actual_prob"] - 0.12) < 1e-9, ranks
    assert detail["coverage"] == {"total": 3, "top1": 1, "top2": 2, "top3": 2}, detail
    assert len(detail["cases"]) == 2, detail
    print("  ✓ 比分 Top3 组合、命中比分概率、排名与覆盖漏斗")


def main() -> int:
    print("== 测试：命中分析/概率校准 ==")
    test_overall_and_bins()
    test_score_hit_detail()
    test_value_bins()
    test_actual_rank_and_empty()
    test_post_kickoff_excluded()
    print("\n全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
