"""P2 模型增强（小样本收缩 / Elo 融合）的离线单元测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src.models import dixon_coles as dc
from src.features import elo
from src.jingcai import payouts as pay


def _synthetic(n_rounds: int = 40) -> pd.DataFrame:
    """一个强队 + 若干弱队，其中强队打满全场、弱队只打几场。"""
    rng = np.random.default_rng(0)
    rows = []
    date = pd.Timestamp("2024-08-01")
    teams = ["Strong", "WeakA", "WeakB", "WeakC", "WeakD", "WeakE"]
    for _ in range(n_rounds):
        # 强队 vs 各弱队（强队主客轮换）
        for i, w in enumerate(teams[1:]):
            home = w if i % 2 else "Strong"
            away = "Strong" if i % 2 else w
            rows.append({"home_team": home, "away_team": away,
                         "ft_home": int(rng.poisson(2.2 if home == "Strong" else 0.6)),
                         "ft_away": int(rng.poisson(0.6 if home == "Strong" else 2.2)),
                         "date": date})
        # 弱队之间偶尔打一场
        if _ % 5 == 0:
            rows.append({"home_team": "WeakC", "away_team": "WeakD",
                         "ft_home": int(rng.poisson(1.0)),
                         "ft_away": int(rng.poisson(1.0)), "date": date})
        date += pd.Timedelta(days=7)
    return pd.DataFrame(rows)


def test_shrinkage_pulls_toward_mean() -> None:
    df = _synthetic()
    m0 = dc.fit(df, shrinkage_prior=0.0)
    m_big = dc.fit(df, shrinkage_prior=1e9)  # 极端收缩 -> 全部趋近均值
    # 极端收缩下，所有队攻防强度都趋近 1.0（联赛均值）
    for t in m_big.attack:
        assert abs(m_big.attack[t] - 1.0) < 0.05, (t, m_big.attack[t])
        assert abs(m_big.defense[t] - 1.0) < 0.05, (t, m_big.defense[t])
    # 不收缩时，强队与弱队强度应明显分化
    strong_att = m0.attack.get("Strong", 1.0)
    weak_att = m0.attack.get("WeakA", 1.0)
    assert strong_att > weak_att, (strong_att, weak_att)
    print("  ✓ 小样本收缩：极端先验下强度趋近均值，无收缩时强/弱队分化")


def test_shrinkage_small_sample_more_shrunk() -> None:
    df = _synthetic()
    m0 = dc.fit(df, shrinkage_prior=0.0)
    m8 = dc.fit(df, shrinkage_prior=8.0)
    # 强队（场次多）几乎不变；弱队（场次少）明显向 1.0 靠拢
    def dist_to_one(d, t):
        return abs(d.get(t, 1.0) - 1.0)

    for t in ["WeakA", "WeakB"]:
        d0 = dist_to_one(m0.attack, t)
        d8 = dist_to_one(m8.attack, t)
        assert d8 < d0, (t, d0, d8)  # 收缩后更接近均值
    # 强队收缩幅度远小于弱队
    s0 = dist_to_one(m0.attack, "Strong")
    s8 = dist_to_one(m8.attack, "Strong")
    assert abs(s8 - s0) < 0.2, (s0, s8)
    print("  ✓ 场次越少收缩越强，强队几乎不变")


def test_elo_persistence_roundtrip() -> None:
    df = _synthetic()
    model = elo.EloModel().fit(df)
    path = Path(sys.path[0]) / "data" / "cache" / "_test_elo.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    elo.save(model, path)
    back = elo.load(path)
    assert set(back.teams) == set(model.teams)
    for t in model.teams:
        assert abs(back.rating(t) - model.rating(t)) < 1e-9
    p1 = model.predict("Strong", "WeakA")
    p2 = back.predict("Strong", "WeakA")
    assert abs(p1["prob_home"] - p2["prob_home"]) < 1e-9
    path.unlink(missing_ok=True)
    print("  ✓ Elo 持久化往返一致且可预测")


def test_dc_elo_blend() -> None:
    dc_had = {"胜": 0.6, "平": 0.25, "负": 0.15}
    elo_had = {"胜": 0.75, "平": 0.12, "负": 0.13}
    b = pay.blend_probabilities(dc_had, elo_had, weight=0.8)
    assert abs(b["胜"] - (0.8 * 0.6 + 0.2 * 0.75)) < 1e-9, b
    assert abs(sum(b.values()) - 1.0) < 1e-9
    print("  ✓ DC 与 Elo 混合正确（0.8/0.2）")


def test_villareal_typo_unified() -> None:
    """回归：'Villareal' 拼写错误应归并为 'Villarreal'，不被错配到单 l。"""
    from src.pipeline import load_training_data, _unify_team_names
    from src.jingcai.team_names import TeamMatcher, build_known_names_from_data

    df = load_training_data()
    names = set(df["home_team"]) | set(df["away_team"])
    assert "Villareal" not in names, "拼写错误 Villareal 应已被归并"
    assert "Villarreal" in names

    m = TeamMatcher(build_known_names_from_data(df))
    r = m.match("比利亚雷", "VIL")
    assert r.matched_name == "Villarreal", r
    print("  ✓ Villareal 拼写归并 + 别名精确命中")


def main() -> int:
    print("== 测试：小样本收缩 ==")
    test_shrinkage_pulls_toward_mean()
    test_shrinkage_small_sample_more_shrunk()
    print("== 测试：Elo 持久化 ==")
    test_elo_persistence_roundtrip()
    print("== 测试：DC-Elo 混合 ==")
    test_dc_elo_blend()
    print("== 测试：队名拼写归并 ==")
    test_villareal_typo_unified()
    print("\n全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
