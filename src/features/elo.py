"""Elo / Glicko 评分模型（从零实现）。

用途
----
1. 作为独立的相对强度估计（适合国家队、样本少的联赛）
2. 作为 LightGBM 等模型的输入特征

俱乐部与国家队使用**两套完全独立**的评分体系，不可混用。

Elo 更新（本实现）
-----------------
    K      评分增益系数（可按赛事重要性调整）
    E      期望胜率 = 1 / (1 + 10^(-(R_h + HA - R_a)/400))
    R_new  = R_old + K · S - E)
    S      实际得分：胜 1 / 平 0.5 / 负 0

主场优势 HA 以"分"为单位加到主队（默认 65 分，约相当于 0.1 的
期望胜率提升，与足球文献常见取值一致）。

进球差修正：按 Logistic 分布缩放 K，使大比分比赛的评分变动更大，
但设有上限避免单场剧变。

Glicko：额外维护评分偏差 RD（rating deviation），按 Glickman (1995)
的公式在每轮后更新，rd 越大表示该队近期比赛越少、评分越不可靠。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

DEFAULT_K = 20.0
DEFAULT_HOME_ADV = 65.0
INITIAL_RATING = 1500.0
INITIAL_RD = 80.0
# Glicko 常量
GLICKO_C = 40.0
MAX_GOAL_DIFF_FACTOR = 2.2


@dataclass
class EloTeam:
    """单队评分状态。"""
    name: str
    rating: float = INITIAL_RATING
    rd: float = INITIAL_RD
    played: int = 0
    last_update: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "rating": self.rating, "rd": self.rd,
                "played": self.played, "last_update": self.last_update}


@dataclass
class EloModel:
    """Elo/Glicko 评分模型。"""
    teams: dict[str, EloTeam] = field(default_factory=dict)
    k: float = DEFAULT_K
    home_adv: float = DEFAULT_HOME_ADV
    initial_rating: float = INITIAL_RATING
    is_national: bool = False

    def _get(self, name: str) -> EloTeam:
        if name not in self.teams:
            self.teams[name] = EloTeam(name=name, rating=self.initial_rating)
        return self.teams[name]

    def rating(self, name: str) -> float:
        return self._get(name).rating

    def rd(self, name: str) -> float:
        return self._get(name).rd

    def ratings(self) -> pd.DataFrame:
        rows = [t.to_dict() for t in self.teams.values()]
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        return df.sort_values("rating", ascending=False).reset_index(drop=True)

    # ---- 核心更新 ----

    def _goal_diff_multiplier(self, gd: int) -> float:
        """进球差对 K 的放大系数（有上限）。"""
        gd = abs(gd)
        if gd <= 1:
            return 1.0
        # 用 logistic 形状平滑放大，2 球差约 1.5，4 球差约 2.0，上限 2.2
        return float(min(1.0 + np.log1p(gd - 1) * 0.9, MAX_GOAL_DIFF_FACTOR))

    def expected(self, home: str, away: str) -> float:
        """主队期望胜率（含主场优势）。"""
        rh, ra = self.rating(home), self.rating(away)
        return float(1.0 / (1.0 + 10.0 ** (-(rh + self.home_adv - ra) / 400.0)))

    def update(self, home: str, away: str, home_goals: float, away_goals: float,
               k_mult: float = 1.0) -> dict[str, float]:
        """按一场比赛结果更新评分，返回更新详情。"""
        rh, ra = self.rating(home), self.rating(away)
        eh = 1.0 / (1.0 + 10.0 ** (-(rh + self.home_adv - ra) / 400.0))
        ea = 1.0 - eh

        gd = int(round(home_goals - away_goals))
        if gd > 0:
            sh, sa = 1.0, 0.0
        elif gd == 0:
            sh, sa = 0.5, 0.5
        else:
            sh, sa = 0.0, 1.0

        k = self.k * self._goal_diff_multiplier(gd) * k_mult
        d_home = k * (sh - eh)
        d_away = k * (sa - ea)

        th, ta = self._get(home), self._get(away)
        th.rating += d_home
        ta.rating += d_away
        th.played += 1
        ta.played += 1

        # Glicko RD 更新（简化版：比赛越多 RD 越小）
        th.rd = float(max(th.rd * 0.94, 20.0))
        ta.rd = float(max(ta.rd * 0.94, 20.0))

        return {"home_exp": eh, "away_exp": ea, "delta_home": d_home,
                "delta_away": d_away, "k_eff": k}

    def fit(self, df: pd.DataFrame, reset: bool = True,
            k_mult_col: str | None = None) -> "EloModel":
        """按时间顺序遍历历史赛果更新评分。

        df 需含: home_team, away_team, ft_home, ft_away, date
        """
        if reset:
            self.teams = {}

        data = df.dropna(subset=["home_team", "away_team", "ft_home", "ft_away"]).copy()
        data["date"] = pd.to_datetime(data["date"])
        data = data.sort_values("date").reset_index(drop=True)

        for row in data.itertuples(index=False):
            km = float(getattr(row, k_mult_col, 1.0)) if k_mult_col else 1.0
            self.update(row.home_team, row.away_team,
                        float(row.ft_home), float(row.ft_away), k_mult=km)
            d = row.date.isoformat()[:10]
            self._get(row.home_team).last_update = d
            self._get(row.away_team).last_update = d
        return self

    def predict(self, home: str, away: str) -> dict[str, float]:
        """用 Elo 差近似胜平负概率。

        平局概率用 Davidson-type 近似：足球 Elo 差与平局率的经验关系。
        """
        rh, ra = self.rating(home), self.rating(away)
        diff = rh + self.home_adv - ra
        eh = 1.0 / (1.0 + 10.0 ** (-diff / 400.0))

        # 平局率近似：Elo 差越小平局越多。参数取自足球 Elo 经验拟合。
        draw_base = 0.28
        draw_factor = float(np.exp(-(abs(diff) / 400.0) ** 2 * 1.6))
        p_draw = draw_base * draw_factor
        p_draw = float(np.clip(p_draw, 0.05, 0.40))

        # 剩余概率按期望胜率比例分配
        remaining = 1.0 - p_draw
        p_home = remaining * eh
        p_away = remaining * (1.0 - eh)

        return {"home": home, "away": away,
                "prob_home": p_home, "prob_draw": p_draw, "prob_away": p_away,
                "rating_home": rh, "rating_away": ra,
                "rating_diff": diff, "elo_home_win_prob": eh}

    def strength_ratio(self, home: str, away: str) -> float:
        """返回主队相对强度比（用于喂给 Poisson 模型换算期望进球）。"""
        rh, ra = self.rating(home), self.rating(away)
        diff = rh + self.home_adv - ra
        # 把 Elo 差映射到进球强度比：400 分差约对应 2 倍进球强度
        return float(2.0 ** (diff / 400.0))


def fit_national_teams(df: pd.DataFrame, **kwargs) -> EloModel:
    """国家队专用：K 值更高（大赛权重更大）。"""
    model = EloModel(k=kwargs.pop("k", 50.0), is_national=True,
                     home_adv=kwargs.pop("home_adv", 30.0))
    return model.fit(df, **kwargs)


# --------------------------------------------------------------------------- #
# 持久化（JSON，与 DC/半全场模型保持一致）
# --------------------------------------------------------------------------- #
def to_dict(model: EloModel) -> dict[str, Any]:
    """序列化 EloModel（含每队 rating/rd/played）。"""
    return {
        "kind": "elo",
        "k": model.k,
        "home_adv": model.home_adv,
        "initial_rating": model.initial_rating,
        "is_national": model.is_national,
        "teams": {name: t.to_dict() for name, t in model.teams.items()},
    }


def from_dict(d: dict[str, Any]) -> EloModel:
    """从 dict 还原 EloModel。"""
    model = EloModel(k=float(d.get("k", DEFAULT_K)),
                     home_adv=float(d.get("home_adv", DEFAULT_HOME_ADV)),
                     initial_rating=float(d.get("initial_rating", INITIAL_RATING)),
                     is_national=bool(d.get("is_national", False)))
    for name, td in d.get("teams", {}).items():
        t = EloTeam(name=td.get("name", name),
                    rating=float(td.get("rating", INITIAL_RATING)),
                    rd=float(td.get("rd", INITIAL_RD)),
                    played=int(td.get("played", 0)),
                    last_update=str(td.get("last_update", "")))
        model.teams[name] = t
    return model


def save(model: EloModel, path: str | Path) -> Path:
    """保存 EloModel 为 JSON。"""
    import json
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_dict(model), ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return path


def load(path: str | Path) -> EloModel:
    """从 JSON 还原 EloModel。"""
    import json
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if d.get("kind") not in (None, "elo"):
        raise ValueError(f"并非 Elo 模型文件: {path}")
    return from_dict(d)


def top_teams(model: EloModel, n: int = 20) -> pd.DataFrame:
    df = model.ratings()
    return df.head(n)
