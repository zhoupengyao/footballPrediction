"""市场混合 / 价值过滤 / 校准误差 ECE 的单元测试。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src.jingcai import payouts as pay
from src.backtest import metrics as M


def test_blend() -> None:
    model = {"胜": 0.6, "平": 0.25, "负": 0.15}
    market = {"胜": 0.5, "平": 0.3, "负": 0.2}
    b = pay.blend_probabilities(model, market, weight=0.6)
    assert abs(sum(b.values()) - 1.0) < 1e-9, b
    assert abs(b["胜"] - 0.56) < 1e-9, b  # 0.6*0.6 + 0.4*0.5
    # weight=1 -> 纯模型
    assert abs(pay.blend_probabilities(model, market, 1.0)["胜"] - 0.6) < 1e-9
    # weight=0 -> 纯市场
    assert abs(pay.blend_probabilities(model, market, 0.0)["胜"] - 0.5) < 1e-9
    print("  ✓ 市场混合权重正确")


def test_value_filter() -> None:
    model = {"胜": 0.75, "平": 0.15, "负": 0.10}
    odds = {"胜": 1.10, "平": 4.0, "负": 6.0}
    # 不设过滤时，低赔率"胜"也会入选（edge 高但赔率低）
    vb_all = pay.value_bets(model, odds, edge_threshold=0.05)
    assert any(b["option"] == "胜" for b in vb_all)
    # min_odds=1.3 过滤掉"胜"(1.10)
    vb = pay.value_bets(model, odds, edge_threshold=0.05, min_odds=1.3)
    assert all(b["odds"] >= 1.3 for b in vb), vb
    assert not any(b["option"] == "胜" for b in vb)
    # max_edge 过滤异常高 edge
    vb2 = pay.value_bets(model, odds, edge_threshold=0.05, max_edge=0.30)
    assert all(b["edge"] <= 0.30 for b in vb2)
    print("  ✓ 价值投注 min_odds / max_edge 过滤正确")


def test_ece() -> None:
    # 完美校准：预测 0.8 的 10 场里 8 场命中 -> ECE 接近 0
    rows = []
    for i in range(10):
        rows.append({"p_home": 0.8, "p_draw": 0.1, "p_away": 0.1,
                     "actual": "H" if i < 8 else "D"})
    e = M.ece(rows, bins=10)
    assert e < 0.02, e
    # 过度自信：预测 0.9 但只有 5/10 命中 -> ECE 明显 > 0
    rows2 = [{"p_home": 0.9, "p_draw": 0.05, "p_away": 0.05,
              "actual": "H" if i < 5 else "D"} for i in range(10)]
    e2 = M.ece(rows2, bins=10)
    assert e2 > 0.3, e2
    # evaluate 汇总里包含 ece
    ev = M.evaluate(rows2)
    assert "ece" in ev and ev["ece"] > 0.3
    print("  ✓ ECE 校准误差计算正确")


def main() -> int:
    test_blend()
    test_value_filter()
    test_ece()
    print("\n全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
