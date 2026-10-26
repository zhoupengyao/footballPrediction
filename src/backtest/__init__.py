"""回测框架。

模块
----
metrics : 准确率 / 对数损失 / Brier / 校准 / 模拟投注 ROI
engine  : walk-forward 回测引擎与报告
"""
from src.backtest.engine import (BacktestConfig, run_backtest, walk_forward,
                                 write_backtest_report)
from src.backtest import metrics

__all__ = ["BacktestConfig", "run_backtest", "walk_forward",
           "write_backtest_report", "metrics"]
