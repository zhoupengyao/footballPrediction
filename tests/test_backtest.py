"""回测指标与引擎的离线单元测试（合成数据，不联网、不依赖磁盘数据）。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src.backtest import metrics as M
from src.backtest.engine import BacktestConfig, run_backtest, walk_forward


def test_metrics_core() -> None:
    rows = [
        {"p_home": 0.6, "p_draw": 0.25, "p_away": 0.15, "actual": "H",
         "odds_home": 2.0, "odds_draw": 3.5, "odds_away": 5.0},
        {"p_home": 0.5, "p_draw": 0.30, "p_away": 0.20, "actual": "D",
         "odds_home": 2.0, "odds_draw": 3.0, "odds_away": 4.0},
    ]
    assert abs(M.accuracy(rows) - 0.5) < 1e-9, "准确率应为 0.5"
    assert M.log_loss(rows) > 0
    assert 0 < M.brier(rows) < 1
    assert M.has_odds(rows)

    b = M.simulate_bets(rows, ev_threshold=0.0)
    # 第一场主胜 EV=0.2>0 且命中；第二场无 EV>0 选项
    assert b["n_bets"] == 1, f"应只下 1 注: {b}"
    assert abs(b["profit"] - 1.0) < 1e-9, f"净收益应为 +1: {b}"
    assert abs(b["roi"] - 1.0) < 1e-9, f"ROI 应为 1: {b}"
    print("  ✓ 指标函数（准确率/对数损失/Brier/模拟投注）正确")


def test_metrics_calibration() -> None:
    rows = [{"p_home": 0.9, "p_draw": 0.05, "p_away": 0.05, "actual": "H"}
            for _ in range(10)]
    cal = M.calibration(rows, bins=10)
    assert cal and cal[-1]["n"] == 10
    assert abs(cal[-1]["emp_freq"] - 1.0) < 1e-9
    print("  ✓ 校准表分箱正确")


def _synthetic(n_rounds: int = 60) -> pd.DataFrame:
    teams = ["A", "B", "C", "D"]
    rng = np.random.default_rng(0)
    rows = []
    date = pd.Timestamp("2024-08-01")
    for _ in range(n_rounds):
        for i, h in enumerate(teams):
            for j, a in enumerate(teams):
                if i == j:
                    continue
                rows.append({"league_code": "E0", "home_team": h, "away_team": a,
                             "ft_home": int(rng.poisson(1.4)),
                             "ft_away": int(rng.poisson(1.1)), "date": date})
                date += pd.Timedelta(days=1)
    return pd.DataFrame(rows)


def test_walk_forward_no_leak_and_rows() -> None:
    df = _synthetic(60)
    cfg = BacktestConfig(leagues=["E0"], years=None, min_train_size=100,
                         refit_interval=50)
    rows = walk_forward(df, cfg)
    assert rows, "walk-forward 应产生预测"
    # 第一场预测的日期必须晚于最小训练集最后一行的日期
    df_sorted = df.sort_values("date").reset_index(drop=True)
    assert rows[0]["date"] >= df_sorted.iloc[100]["date"].date().isoformat()
    assert set(rows[0]).issuperset({"p_home", "p_draw", "p_away", "actual"})
    for r in rows:
        assert abs(r["p_home"] + r["p_draw"] + r["p_away"] - 1) < 1e-9
    print(f"  ✓ walk-forward 产生 {len(rows)} 条预测，概率归一")


def test_run_backtest_report() -> None:
    from src.config import get_settings
    df = _synthetic(60)
    cfg = BacktestConfig(leagues=["E0"], years=None, min_train_size=100,
                         refit_interval=50)
    res = run_backtest(df, cfg)
    assert res["rows"], "回测应有结果"
    assert "accuracy" in res["overall"]
    from src.backtest.engine import write_backtest_report
    md, js = write_backtest_report(
        res, path_base=get_settings().cache_dir / "_test_backtest")
    assert md.exists() and js.exists()
    md.unlink(missing_ok=True)
    js.unlink(missing_ok=True)
    print("  ✓ 回测汇总与报告生成正常")


def main() -> int:
    print("== 测试：指标 ==")
    test_metrics_core()
    test_metrics_calibration()
    print("== 测试：引擎 ==")
    test_walk_forward_no_leak_and_rows()
    test_run_backtest_report()
    print("\n全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
