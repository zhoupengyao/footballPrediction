"""滚动特征工程：为 LightGBM 等模型构造无泄漏的逐场特征。

核心原则
--------
任何一场比赛的特征只用「该场之前」的数据，杜绝未来信息泄漏。
维护每队滚动状态（Elo 评分、近 K 场进球/失球/积分、近 K 场 xG、最近比赛日），
按时间顺序逐场「先取特征、后更新状态」。

用途
----
作为 Dixon-Coles / Elo 之外的**第三意见**，输入 LightGBM 输出胜平负概率，
再与 DC+Elo 的概率混合。
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

DEFAULT_K = 8            # 滚动窗口场数
DEFAULT_HOME_ADV = 65.0  # Elo 主场优势（分）
DEFAULT_K_ELO = 20.0     # Elo 更新系数
MAX_REST = 30.0          # 休息天数上限（避免极端值）

# 固定特征列（顺序固定，保证 fit / predict 一致）
FEATURE_COLS = [
    "elo_diff",
    "home_gf", "home_ga", "home_pts",
    "away_gf", "away_ga", "away_pts",
    "home_rest", "away_rest",
    "home_xg", "home_xga", "away_xg", "away_xga",
]

# 标签：0=主胜 H，1=平 D，2=客胜 A
RESULT_LABELS = ["H", "D", "A"]


@dataclass
class _TeamState:
    elo: float = 1500.0
    gf: deque = field(default_factory=lambda: deque(maxlen=DEFAULT_K))
    ga: deque = field(default_factory=lambda: deque(maxlen=DEFAULT_K))
    pts: deque = field(default_factory=lambda: deque(maxlen=DEFAULT_K))
    xgf: deque = field(default_factory=lambda: deque(maxlen=DEFAULT_K))
    xga: deque = field(default_factory=lambda: deque(maxlen=DEFAULT_K))
    last_date: pd.Timestamp | None = None


def _elo_expected(home_elo: float, away_elo: float, home_adv: float) -> float:
    return 1.0 / (1.0 + 10.0 ** (-(home_elo + home_adv - away_elo) / 400.0))


def _goal_diff_k(gd: float) -> float:
    gd = abs(gd)
    if gd <= 1:
        return 1.0
    return min(1.0 + np.log1p(gd - 1) * 0.9, 2.2)


def _result_index(fth: float, fta: float) -> int:
    if fth > fta:
        return 0
    if fth == fta:
        return 1
    return 2


def _mean(d: deque) -> float:
    return float(np.mean(list(d))) if d else float("nan")


def _as_date(v: Any) -> pd.Timestamp | None:
    ts = pd.to_datetime(v, errors="coerce")
    return None if pd.isna(ts) else ts


class RollingFeatures:
    """逐场滚动特征构造器（无泄漏）。

    用法（训练）::

        rf = RollingFeatures()
        X, y = rf.fit_features(df)   # 逐场「先取特征、后更新」，df 需按日期排序

    用法（预测）::

        rf = RollingFeatures()
        rf.ingest(history_df)                     # 灌入截至今日的全部历史
        feats = rf.features_for(home, away, date) # 新场次特征
    """

    def __init__(self, k: int = DEFAULT_K, home_adv: float = DEFAULT_HOME_ADV,
                 k_elo: float = DEFAULT_K_ELO):
        self.k = k
        self.home_adv = home_adv
        self.k_elo = k_elo
        self.state: dict[str, _TeamState] = {}
        self.has_xg = False
        # 用 maxlen=k 的 deque 需要重建（k 可改）
        self._state_factory = lambda: _TeamState(
            gf=deque(maxlen=k), ga=deque(maxlen=k), pts=deque(maxlen=k),
            xgf=deque(maxlen=k), xga=deque(maxlen=k))

    def _get(self, name: str) -> _TeamState:
        if name not in self.state:
            self.state[name] = self._state_factory()
        return self.state[name]

    # ---- 更新 ----
    def _ingest(self, home: str, away: str, fth: float, fta: float,
                date: pd.Timestamp | None, xg_h: float, xg_a: float) -> None:
        hs, as_ = self._get(home), self._get(away)
        # Elo 更新
        eh = _elo_expected(hs.elo, as_.elo, self.home_adv)
        ea = 1.0 - eh
        gd = float(fth) - float(fta)
        sh = 1.0 if gd > 0 else (0.5 if gd == 0 else 0.0)
        sa = 1.0 - sh
        k = self.k_elo * _goal_diff_k(gd)
        hs.elo += k * (sh - eh)
        as_.elo += k * (sa - ea)
        # 进球/失球/积分滚动
        hs.gf.append(float(fth)); hs.ga.append(float(fta))
        as_.gf.append(float(fta)); as_.ga.append(float(fth))
        pts_h = 3.0 if gd > 0 else (1.0 if gd == 0 else 0.0)
        hs.pts.append(pts_h); as_.pts.append(3.0 - pts_h if gd != 0 else 1.0)
        # xG 滚动（仅在有 xG 数据时）
        if not (np.isnan(xg_h) or np.isnan(xg_a)):
            self.has_xg = True
            hs.xgf.append(float(xg_h)); hs.xga.append(float(xg_a))
            as_.xgf.append(float(xg_a)); as_.xga.append(float(xg_h))
        # 最近比赛日
        if date is not None:
            hs.last_date = date
            as_.last_date = date

    # ---- 特征 ----
    def _features(self, home: str, away: str, date: pd.Timestamp | None) -> list[float]:
        hs, as_ = self._get(home), self._get(away)
        elo_diff = (hs.elo + self.home_adv) - as_.elo

        def rest(s: _TeamState) -> float:
            if s.last_date is None or date is None:
                return MAX_REST
            return float(min((date - s.last_date).days, MAX_REST))

        feats = [
            float(elo_diff),
            _mean(hs.gf), _mean(hs.ga), _mean(hs.pts),
            _mean(as_.gf), _mean(as_.ga), _mean(as_.pts),
            rest(hs), rest(as_),
            _mean(hs.xgf), _mean(hs.xga), _mean(as_.xgf), _mean(as_.xga),
        ]
        return feats

    # ---- 对外 ----
    def fit_features(self, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
        """按时间顺序逐场生成特征与标签（无泄漏）。df 需含
        home_team, away_team, ft_home, ft_away, date（可选 xg_home/xg_away）。"""
        data = df.dropna(subset=["home_team", "away_team", "ft_home", "ft_away"]).copy()
        data["date"] = pd.to_datetime(data["date"], errors="coerce")
        data = data.sort_values("date").reset_index(drop=True)
        rows: list[list[float]] = []
        labels: list[int] = []
        for r in data.itertuples(index=False):
            xg_h = float(getattr(r, "xg_home", np.nan) or np.nan)
            xg_a = float(getattr(r, "xg_away", np.nan) or np.nan)
            feats = self._features(r.home_team, r.away_team, r.date)
            rows.append(feats)
            labels.append(_result_index(r.ft_home, r.ft_away))
            self._ingest(r.home_team, r.away_team, r.ft_home, r.ft_away,
                         r.date, xg_h, xg_a)
        X = pd.DataFrame(rows, columns=FEATURE_COLS)
        return X, pd.Series(labels, name="result")

    def ingest(self, df: pd.DataFrame) -> None:
        """灌入历史赛果（不产出特征），供预测前准备状态。"""
        data = df.dropna(subset=["home_team", "away_team", "ft_home", "ft_away"]).copy()
        data["date"] = pd.to_datetime(data["date"], errors="coerce")
        data = data.sort_values("date")
        for r in data.itertuples(index=False):
            xg_h = float(getattr(r, "xg_home", np.nan) or np.nan)
            xg_a = float(getattr(r, "xg_away", np.nan) or np.nan)
            self._ingest(r.home_team, r.away_team, r.ft_home, r.ft_away,
                         r.date, xg_h, xg_a)

    def features_for(self, home: str, away: str, date: Any) -> list[float]:
        return self._features(home, away, _as_date(date))

    def feature_frame(self, home: str, away: str, date: Any) -> pd.DataFrame:
        """返回单行 DataFrame（列名对齐 FEATURE_COLS），供模型预测。"""
        return pd.DataFrame([self.features_for(home, away, date)],
                            columns=FEATURE_COLS)
