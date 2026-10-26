"""LightGBM 特征模型 + 滚动特征工程的离线单元测试（合成数据，无泄漏）。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src.features.features import FEATURE_COLS, RollingFeatures
from src.models.ml_model import MLModel


def _synthetic(n_rounds: int = 30) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    rows = []
    date = pd.Timestamp("2024-08-01")
    teams = ["A", "B", "C", "D"]
    for _ in range(n_rounds):
        for i, h in enumerate(teams):
            for j, a in enumerate(teams):
                if i == j:
                    continue
                rows.append({"home_team": h, "away_team": a,
                             "ft_home": int(rng.poisson(1.6)),
                             "ft_away": int(rng.poisson(1.1)),
                             "date": date})
                date += pd.Timedelta(days=3)
    return pd.DataFrame(rows)


def test_rolling_features_shape_and_labels() -> None:
    df = _synthetic()
    rf = RollingFeatures()
    X, y = rf.fit_features(df)
    assert X.shape == (len(df), len(FEATURE_COLS)), X.shape
    assert list(X.columns) == FEATURE_COLS
    assert set(y.unique()).issubset({0, 1, 2})
    # 标签与实际结果一致
    r0 = df.sort_values("date").iloc[0]
    idx = 0 if r0.ft_home > r0.ft_away else (1 if r0.ft_home == r0.ft_away else 2)
    assert y.iloc[0] == idx
    print(f"  ✓ 滚动特征 {X.shape}，标签与赛果一致")


def test_rolling_features_no_leakage() -> None:
    df = _synthetic().sort_values("date").reset_index(drop=True)
    rf_all = RollingFeatures()
    X, y = rf_all.fit_features(df)
    # 对每一场，fit_features 的特征应等于「只用其之前数据」手动构造的特征
    for i in (5, 15, 25, len(df) - 1):
        rf_manual = RollingFeatures()
        rf_manual.ingest(df.iloc[:i])
        f_manual = rf_manual.features_for(df.iloc[i].home_team,
                                          df.iloc[i].away_team, df.iloc[i].date)
        f_fit = X.iloc[i].tolist()
        assert np.allclose(f_manual, f_fit, equal_nan=True), (i, f_manual, f_fit)
    print("  ✓ 滚动特征无未来泄漏（第 i 场只用其之前数据）")


def test_ml_fit_predict_persist() -> None:
    df = _synthetic()
    rf = RollingFeatures()
    X, y = rf.fit_features(df)
    m = MLModel().fit(X, y, n_estimators=20)
    p = m.predict_proba(X.iloc[[0]])
    assert p is not None and abs(sum(p.values()) - 1.0) < 1e-6
    assert all(0.0 <= v <= 1.0 for v in p.values())
    # 持久化往返
    path = Path(sys.path[0]) / "data" / "cache" / "_test_ml.joblib"
    m.save(path)
    back = MLModel.load(path)
    p2 = back.predict_proba(X.iloc[[0]])
    assert abs(p["胜"] - p2["胜"]) < 1e-9
    path.unlink(missing_ok=True)
    print("  ✓ ML 拟合/预测/持久化往返一致")


def main() -> int:
    print("== 测试：滚动特征 ==")
    test_rolling_features_shape_and_labels()
    test_rolling_features_no_leakage()
    print("== 测试：LightGBM ==")
    test_ml_fit_predict_persist()
    print("\n全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
