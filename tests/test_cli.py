"""CLI / 管线离线冒烟测试。

覆盖：
    1. 模型持久化 JSON 往返一致
    2. train -> load_models 落盘可读
    3. predict 在赔率快照上跑通并产出报告

无需联网：复用 data/processed/tier1_matches.parquet 与 data/odds 快照。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import re

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src.config import get_settings
from src.models import dixon_coles as dc
from src.models.persistence import load_dc, save_dc

SETTINGS = get_settings()


def _synthetic() -> pd.DataFrame:
    """4 队循环赛的小样本，用于快速拟合。"""
    teams = ["Alpha", "Beta", "Gamma", "Delta"]
    rng = np.random.default_rng(42)
    rows = []
    date = pd.Timestamp("2025-08-01")
    for rnd in range(6):
        for i, h in enumerate(teams):
            for j, a in enumerate(teams):
                if i == j:
                    continue
                rows.append({
                    "home_team": h, "away_team": a,
                    "ft_home": int(rng.poisson(1.4)),
                    "ft_away": int(rng.poisson(1.1)),
                    "date": date,
                })
                date += pd.Timedelta(days=3)
    return pd.DataFrame(rows)


def test_persistence_roundtrip() -> None:
    df = _synthetic()
    model = dc.fit(df, half_life_days=180)

    path = SETTINGS.cache_dir / "_test_dc.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    save_dc(model, path)
    back = load_dc(path)

    assert back.teams == model.teams, "teams 不一致"
    assert abs(back.mu - model.mu) < 1e-9, "mu 不一致"
    assert abs(back.home_advantage - model.home_advantage) < 1e-9
    assert abs(back.rho - model.rho) < 1e-9
    for t in model.teams:
        assert abs(back.attack[t] - model.attack[t]) < 1e-9, f"attack[{t}] 不一致"
        assert abs(back.defense[t] - model.defense[t]) < 1e-9, f"defense[{t}] 不一致"
    # 载入后仍能预测
    pred = dc.predict_proba(back, "Alpha", "Beta")
    assert abs(pred["prob_home"] + pred["prob_draw"] + pred["prob_away"] - 1) < 1e-6
    path.unlink(missing_ok=True)
    print("  ✓ 持久化往返一致，且可预测")


def test_train_and_predict() -> None:
    from src.pipeline import (build_matcher, predict_matches, summarize,
                              train_leagues, write_report)

    # 只训练一个联赛的少量赛季，保证测试速度；save=False 避免覆盖生产模型
    models = train_leagues(leagues=["E0"], years=2, verbose=True, save=False)
    assert "E0" in models, "E0 训练失败"

    matcher = build_matcher()
    # 构造两场已知可匹配的英超对阵
    from src.ingest.jingcai_scraper import JcMatch
    matches = [
        JcMatch(match_id=1, match_num="T001", match_date="2026-10-16",
                match_time="20:00:00", league="英超", league_code="EPL",
                home_cn="阿森纳", away_cn="利物浦", home_en="ARS", away_en="LIV",
                home_rank="[1]", away_rank="[2]",
                had={"h": "2.00", "d": "3.40", "a": "3.60"},
                hhad={"h": "3.60", "d": "3.60", "a": "1.85",
                      "goalLine": "-1", "goalLineValue": "-1.00"}),
    ]
    rows = predict_matches(matches, models, matcher, edge_threshold=0.05)
    stats = summarize(rows)
    assert stats["total"] == 1
    assert stats["predicted"] == 1, f"应有 1 场可预测: {rows}"
    r = rows[0]
    assert r["home_matched"] == "Arsenal"
    assert abs(sum(r["had"].values()) - 1) < 1e-6
    assert r["score_most_likely"] and ":" in r["score_most_likely"]
    assert len(r["score_top"]) == 3, f"应有 Top3 比分: {r.get('score_top')}"
    assert r["score_top"][0]["prob"] >= r["score_top"][1]["prob"]
    assert abs(r["score_top"][0]["prob"] - r["score_most_likely_prob"]) < 1e-12

    # 开赛时间解析 + 已开赛跳过
    from datetime import datetime as _dt
    from src.pipeline import match_kickoff
    assert match_kickoff("2026-10-16", "20:00:00") == _dt(2026, 10, 16, 20, 0, 0)
    assert match_kickoff("2026-10-16", "") is None
    rows_skip = predict_matches(matches, models, matcher, edge_threshold=0.05,
                                skip_started=True, now=_dt(2026, 10, 17, 0, 0, 0))
    assert str(rows_skip[0]["skipped"]).startswith("已开赛"), rows_skip[0]
    rows_live = predict_matches(matches, models, matcher, edge_threshold=0.05,
                                skip_started=True, now=_dt(2026, 10, 16, 19, 0, 0))
    assert rows_live[0]["skipped"] is None, rows_live[0]

    md, js = write_report(rows, edge_threshold=0.05,
                          path_base=SETTINGS.cache_dir / "_test_report")
    assert md.exists() and js.exists(), "报告未生成"
    text = md.read_text(encoding="utf-8")
    assert "比分概率 Top3" in text
    assert re.search(r"\d+:\d+", text), "报告缺少比分"
    md.unlink(missing_ok=True)
    js.unlink(missing_ok=True)
    print("  ✓ train -> load -> predict -> report 跑通（含比分）")


def test_select_round() -> None:
    """按「期」筛选：first / today / all + 旧快照回退。"""
    from src.ingest.jingcai_scraper import JcMatch, select_round

    def mk(num: str, business_date: str) -> JcMatch:
        return JcMatch(
            match_id=1, match_num=num, match_date=business_date or "2026-10-21",
            match_time="20:00:00", league="英超", league_code="EPL",
            home_cn="A", away_cn="B", home_en="A", away_en="B",
            home_rank="", away_rank="",
            business_date=business_date, weekday=num[:2],
        )

    ms = [mk("周三001", "2026-10-21"), mk("周三002", "2026-10-21"),
          mk("周四001", "2026-10-22"), mk("周四002", "2026-10-22")]

    first, _ = select_round(ms, "first")
    assert len(first) == 2, first
    assert all(m.business_date == "2026-10-21" for m in first)
    assert [m.match_num for m in first] == ["周三001", "周三002"]

    today, _ = select_round(ms, "today", today="2026-10-22")
    assert [m.match_num for m in today] == ["周四001", "周四002"]

    # 今天没有对应期 -> 回退到最早一期
    fallback, _ = select_round(ms, "today", today="2026-10-30")
    assert [m.match_num for m in fallback] == ["周三001", "周三002"]

    everything, _ = select_round(ms, "all")
    assert len(everything) == 4

    # 旧快照没有 business_date：按编号前缀（周三/周四）回退取第一组
    old = [mk("周日014", ""), mk("周日015", ""), mk("周一001", "")]
    old_first, _ = select_round(old, "first")
    assert [m.match_num for m in old_first] == ["周日014", "周日015"]

    assert select_round([], "first") == ([], "")
    print("  ✓ 按期筛选 first/today/all + 旧快照回退")


def main() -> int:
    print("== 测试：模型持久化 ==")
    test_persistence_roundtrip()
    print("== 测试：按期筛选 ==")
    test_select_round()
    print("== 测试：训练+预测管线 ==")
    test_train_and_predict()
    print("\n全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
