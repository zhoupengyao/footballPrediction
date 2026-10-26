"""P2-3 验证脚本：对比 DC / DC+Elo / DC+Elo+ML 在 E0 留出集上的预测质量。

无泄漏：模型只在 cut 之前的数据上训练；测试集特征只用训练期状态构造。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd

from src.pipeline import load_training_data
from src.models import dixon_coles as dc
from src.features import elo
from src.features.features import RollingFeatures
from src.models.ml_model import MLModel
from src.backtest import metrics as M
from src.jingcai import payouts as pay

LEAGUE = "E0"
CUT = "2025-08-01"

df = load_training_data()
sub = df[df.league_code == LEAGUE].sort_values("date").reset_index(drop=True)
train = sub[sub.date < CUT]
test = sub[sub.date >= CUT]
print(f"{LEAGUE}: 训练 {len(train)} 场, 测试 {len(test)} 场")

# 训练三个模型
dc_model = dc.fit(train, shrinkage_prior=8)
elo_model = elo.EloModel().fit(train)
rf = RollingFeatures()
X, y = rf.fit_features(train)
ml_model = MLModel().fit(X, y, n_estimators=300) if len(X) >= 300 else None

# 测试期滚动状态（只用训练期数据，无泄漏）
rf_test = RollingFeatures()
rf_test.ingest(train)


def eval_model(name, get_had):
    rows = []
    for r in test.itertuples(index=False):
        if r.home_team not in dc_model.attack or r.away_team not in dc_model.attack:
            continue
        p = get_had(r)
        rows.append({
            "p_home": p["胜"], "p_draw": p["平"], "p_away": p["负"],
            "actual": M.result_label(r.ft_home, r.ft_away),
        })
    ev = M.evaluate(rows)
    print(f"{name:<14} n={ev['n']:>4} acc={ev['accuracy']:.4f} "
          f"logloss={ev['log_loss']:.4f} brier={ev['brier']:.4f} ece={ev['ece']:.4f}")
    return ev


def dc_had(r):
    p = dc.predict_proba(dc_model, r.home_team, r.away_team)
    return {"胜": p["prob_home"], "平": p["prob_draw"], "负": p["prob_away"]}


def dc_elo_had(r):
    p = dc.predict_proba(dc_model, r.home_team, r.away_team)
    ep = elo_model.predict(r.home_team, r.away_team)
    dc_h = {"胜": p["prob_home"], "平": p["prob_draw"], "负": p["prob_away"]}
    elo_h = {"胜": ep["prob_home"], "平": ep["prob_draw"], "负": ep["prob_away"]}
    return pay.blend_probabilities(dc_h, elo_h, weight=0.8)


def dc_elo_ml_had(r):
    base = dc_elo_had(r)
    if ml_model is None:
        return base
    X = rf_test.feature_frame(r.home_team, r.away_team, r.date)
    ml_h = ml_model.predict_proba(X)
    if ml_h is None:
        return base
    return pay.blend_probabilities(base, ml_h, weight=0.8)


print("\n模型                     场次  准确率  对数损失  Brier   ECE")
print("-" * 60)
eval_model("DC(收缩)", dc_had)
eval_model("DC+Elo", dc_elo_had)
eval_model("DC+Elo+ML", dc_elo_ml_had)
