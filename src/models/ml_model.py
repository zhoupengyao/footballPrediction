"""LightGBM 胜平负特征模型（作为 Dixon-Coles / Elo 之外的第三意见）。

输入 ``RollingFeatures`` 构造的无泄漏滚动特征，输出胜平负概率。
用 joblib 持久化（LightGBM 的 Booster 无法用 JSON 表达，属二进制模型，
这是与 DC/Elo 那些标量模型 JSON 持久化的刻意区别）。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Windows 上 loky 探测物理核数会触发无谓的 subprocess 警告；固定为 1 避免
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

from joblib import dump, load  # noqa: E402

HAD_KEYS = ["胜", "平", "负"]

# 默认 LightGBM 参数（与 settings.yaml 的 training.lgbm 对齐，可被覆盖）
DEFAULT_PARAMS = {
    "objective": "multiclass",
    "num_class": 3,
    "n_estimators": 400,
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_child_samples": 30,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "verbosity": -1,
    "n_jobs": 1,
    "random_state": 42,
}


class MLModel:
    """胜平负 LightGBM 分类器封装。"""

    def __init__(self, feature_cols: list[str] | None = None):
        self.feature_cols = list(feature_cols or [])
        self.clf: Any = None
        self.n_train: int = 0

    # ---- 训练 / 预测 ----
    def fit(self, X: pd.DataFrame, y: pd.Series, **params: Any) -> "MLModel":
        import lightgbm as lgb

        self.feature_cols = list(X.columns)
        p = dict(DEFAULT_PARAMS)
        p.update(params)
        self.clf = lgb.LGBMClassifier(**p)
        y_arr = y.to_numpy() if hasattr(y, "to_numpy") else y
        self.clf.fit(X, y_arr)
        self.n_train = int(len(X))
        return self

    def predict_proba(self, X: pd.DataFrame) -> dict[str, float] | None:
        """返回单行 {'胜','平','负'} 概率；未训练返回 None。"""
        if self.clf is None:
            return None
        X = X[self.feature_cols] if set(self.feature_cols).issubset(X.columns) else X
        p = self.clf.predict_proba(X)[0]
        return {"胜": float(p[0]), "平": float(p[1]), "负": float(p[2])}

    # ---- 持久化 ----
    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        dump(self, path)
        return path

    @staticmethod
    def load(path: str | Path) -> "MLModel":
        return load(path)


def save(model: MLModel, path: str | Path) -> Path:
    return model.save(path)


def load_model(path: str | Path) -> MLModel:
    return MLModel.load(path)
