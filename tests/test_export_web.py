"""站点导出层的离线测试（合成报告，不联网）。"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src import web_export as W


def _prediction(generated_at: str, had_home: float = 0.6) -> dict:
    return {
        "generated_at": generated_at,
        "edge_threshold": 0.05,
        "predictions": [
            {
                "match_id": 1001,
                "match_num": "周日001",
                "match_date": "2026-10-25",
                "match_time": "20:00:00",
                "league": "英超",
                "league_code": "E0",
                "business_date": "2026-10-25",
                "home_cn": "曼城",
                "away_cn": "阿森纳",
                "div": "E0",
                "skipped": None,
                "model": "E0",
                "home_matched": "Man City",
                "away_matched": "Arsenal",
                "had": {"胜": had_home, "平": 0.25, "负": round(1 - had_home - 0.25, 4)},
                "had_dc": {"胜": 0.55, "平": 0.3, "负": 0.15},
                "elo_had": {"胜": 0.5, "平": 0.28, "负": 0.22},
                "ml_had": {"胜": 0.7, "平": 0.2, "负": 0.1},
                "had_odds": {"胜": 2.0, "平": 3.4, "负": 3.8},
                "had_implied": {"胜": 0.5, "平": 0.2941, "负": 0.2632},
                "had_blended": {"胜": 0.56, "平": 0.2667, "负": 0.1733},
                "overround": 0.0573,
                "hhad_goal_line": -1.0,
                "hhad": {"胜": 0.45, "平": 0.3, "负": 0.25},
                "hhad_odds": {"胜": 2.1, "平": 3.2, "负": 3.4},
                "hhad_implied": {"胜": 1 / 2.1, "平": 1 / 3.2, "负": 1 / 3.4},
                "hhad_blended": {"胜": 0.47, "平": 0.3, "负": 0.23},
                "ttg": {"0": 0.05, "1": 0.15, "2": 0.25, "3": 0.25,
                        "4": 0.15, "5": 0.08, "6": 0.04, "7+": 0.03},
                "score_top": [
                    {"score": "2:1", "prob": 0.12},
                    {"score": "1:0", "prob": 0.11},
                    {"score": "2:0", "prob": 0.09},
                ],
                "score_most_likely": "2:1",
                "hafu_top": [["胜/胜", 0.3], ["平/胜", 0.15]],
                "xg_home": 1.8,
                "xg_away": 1.1,
                "value_bets": [{
                    "market": "HAD", "option": "胜", "odds": 2.0,
                    "model_prob": 0.56, "implied_prob": 0.5,
                    "edge": 0.06, "ev": 0.12, "stake_pct": 0.02,
                }],
            },
            {
                "match_id": 1002,
                "match_num": "周日002",
                "match_date": "2026-10-25",
                "match_time": "22:00:00",
                "league": "瑞超",
                "league_code": "SWE1",
                "business_date": "2026-10-25",
                "home_cn": "盖斯",
                "away_cn": "哥德堡",
                "div": "SWE1",
                "skipped": "未收录联赛: 瑞超",
                "home_matched": "",
                "away_matched": "",
            },
        ],
    }


def _build(tmp: Path, main_generated: str = "2026-10-25T23:00:00",
           archive_generated: str | None = "2026-10-25T18:00:00") -> Path:
    reports = tmp / "reports"
    reports.mkdir()
    (reports / "predict_20261025.json").write_text(
        json.dumps(_prediction(main_generated, had_home=0.2), ensure_ascii=False),
        encoding="utf-8")
    if archive_generated:
        archive = reports / "archive"
        archive.mkdir()
        (archive / "predict_20261025_180000.json").write_text(
            json.dumps(_prediction(archive_generated, had_home=0.6), ensure_ascii=False),
            encoding="utf-8")

    manual = tmp / "results.csv"
    manual.write_text(
        "date,match_num,league,home_cn,away_cn,ft_home,ft_away,ht_home,ht_away\n"
        "2026-10-25,周日001,英超,曼城,阿森纳,2,1,1,0\n",
        encoding="utf-8")
    out = tmp / "site"
    W.build_site_data(
        out_dir=out,
        reports_dir=reports,
        odds_dir=tmp / "odds",
        processed_dir=tmp / "processed",
        models_dir=tmp / "models",
        manual_path=manual,
        include_backtests=False,
        result_index={},
    )
    return out


def test_export_and_settlement() -> None:
    with tempfile.TemporaryDirectory() as d:
        out = _build(Path(d))
        history = json.loads((out / "history" / "2026-10-25.json").read_text(encoding="utf-8"))
        assert len(history) == 2, history
        match = next(m for m in history if m["match_num"] == "周日001")
        assert match["status"] == "settled", match
        assert match["prediction_timing"] == "pre_match", match
        assert match["result"]["ft"] == "2:1" and match["result"]["ht"] == "1:0", match
        assert match["result"]["had"] == "home", match
        assert match["result"]["hhad"] == "draw", match
        assert match["result"]["total_goals"] == "3", match
        assert match["result"]["half_full"] == "胜/胜", match

        m = match["prediction"]["markets"]
        assert m["HAD"]["predicted"] == "home" and m["HAD"]["hit"] is True, m["HAD"]
        assert m["HHAD"]["actual"] == "draw" and m["HHAD"]["hit"] is False, m["HHAD"]
        assert m["SCORE"]["top1_hit"] is True and m["SCORE"]["top3_hit"] is True, m["SCORE"]
        assert m["TOTAL_GOALS"]["actual"] == "3" and m["TOTAL_GOALS"]["hit"] is False, m["TOTAL_GOALS"]
        assert m["HALF_FULL"]["actual"] == "胜/胜" and m["HALF_FULL"]["hit"] is True, m["HALF_FULL"]
        assert all(v["hit"] is True for v in match["prediction"]["model_layers"].values()), match

        skipped = next(m for m in history if m["match_num"] == "周日002")
        assert skipped["status"] == "skipped" and skipped["prediction"] is None, skipped
        assert skipped["skip_reason"], skipped

        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["counts"]["matches"] == 2, manifest
        assert manifest["counts"]["settled"] == 1, manifest
        assert manifest["counts"]["skipped"] == 1, manifest

        perf = json.loads((out / "performance.json").read_text(encoding="utf-8"))
        assert perf["overall"]["stats_settled"] == 1, perf
        assert perf["overall"]["markets"]["HAD"]["accuracy"] == 1.0, perf

        count = W.check_output(out)
        assert count >= 5, count
    print("  ✓ 导出、结算、统计与 JSON 校验正确")


def test_archive_pre_match_wins() -> None:
    """主报告是赛后 23:00，归档是赛前 18:00，应选归档。"""
    with tempfile.TemporaryDirectory() as d:
        out = _build(Path(d), main_generated="2026-10-25T23:00:00",
                     archive_generated="2026-10-25T18:00:00")
        history = json.loads((out / "history" / "2026-10-25.json").read_text(encoding="utf-8"))
        match = next(m for m in history if m["match_num"] == "周日001")
        assert match["prediction_timing"] == "pre_match", match
        # 归档里的主胜概率 0.6，主报告里 0.2
        assert match["prediction"]["markets"]["HAD"]["probs"]["home"] == 0.6, match
        assert match["prediction"]["source"].endswith("predict_20261025_180000.json"), match
    print("  ✓ 优先使用开赛前最后一次归档")


def test_post_kickoff_excluded_from_stats() -> None:
    """只有赛后报告时，保留展示但不计入命中率。"""
    with tempfile.TemporaryDirectory() as d:
        out = _build(Path(d), main_generated="2026-10-25T23:00:00",
                     archive_generated=None)
        history = json.loads((out / "history" / "2026-10-25.json").read_text(encoding="utf-8"))
        match = next(m for m in history if m["match_num"] == "周日001")
        assert match["prediction_timing"] == "post_kickoff", match
        assert match["status"] == "settled", match
        perf = json.loads((out / "performance.json").read_text(encoding="utf-8"))
        assert perf["overall"]["stats_settled"] == 0, perf
        assert perf["overall"]["markets"]["HAD"]["n"] == 0, perf
    print("  ✓ 赛后补跑不计入命中率")


def test_group_by_match_date() -> None:
    """报告日期和比赛日期不同时，history 应按比赛日期归档。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        reports = tmp / "reports"
        reports.mkdir()
        data = _prediction("2026-10-24T18:00:00")
        for item in data["predictions"]:
            item["match_date"] = "2026-10-25"
            item["business_date"] = "2026-10-24"
        (reports / "predict_20261024.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")

        manual = tmp / "results.csv"
        manual.write_text(
            "date,match_num,league,home_cn,away_cn,ft_home,ft_away,ht_home,ht_away\n"
            "2026-10-25,周日001,英超,曼城,阿森纳,2,1,1,0\n",
            encoding="utf-8")
        out = tmp / "site"
        W.build_site_data(
            out_dir=out,
            reports_dir=reports,
            odds_dir=tmp / "odds",
            processed_dir=tmp / "processed",
            models_dir=tmp / "models",
            manual_path=manual,
            include_backtests=False,
            result_index={},
        )
        assert (out / "history" / "2026-10-25.json").exists()
        assert not (out / "history" / "2026-10-24.json").exists()
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["latest_match_date"] == "2026-10-25", manifest
        assert "2026-10-24" not in [d["date"] for d in manifest["dates"]], manifest
    print("  ✓ 按比赛日期归档，而不是报告日期")


def main() -> int:
    print("== 测试：站点导出 ==")
    test_export_and_settlement()
    test_archive_pre_match_wins()
    test_post_kickoff_excluded_from_stats()
    test_group_by_match_date()
    print("\n全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
