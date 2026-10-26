"""模型持久化：以 JSON 存取 Dixon-Coles 与半全场模型。

为何用 JSON 而非 pickle
-----------------------
Dixon-Coles 打分只需 mu / home_advantage / rho 与每队的 attack/defense
字典，全部是可读标量；半全场模型只需一个 3x3 转移矩阵。用 JSON 存
安全、可读、跨 Python 版本稳定，且不必导入 pickle。

目录约定
--------
    data/models/{div}/dc.json
    data/models/{div}/halffull.json
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from src.models.dixon_coles import DixonColesResult
from src.models.halffull import HalfFullModel


def save_dc(model: DixonColesResult, path: str | Path) -> Path:
    """保存 Dixon-Coles 模型为 JSON。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": "dixon_coles",
        "teams": list(model.teams),
        "mu": model.mu,
        "home_advantage": model.home_advantage,
        "rho": model.rho,
        "attack": model.attack,
        "defense": model.defense,
        "n_matches": model.n_matches,
        "log_likelihood": model.log_likelihood,
        "converged": model.converged,
        "half_life_days": model.half_life_days,
        "fitted_at": model.fitted_at,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return path


def load_dc(path: str | Path) -> DixonColesResult:
    """从 JSON 还原 Dixon-Coles 模型。"""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if d.get("kind") not in (None, "dixon_coles"):
        raise ValueError(f"并非 Dixon-Coles 模型文件: {path}")
    teams = list(d["teams"])
    attack = {k: float(v) for k, v in d["attack"].items()}
    defense = {k: float(v) for k, v in d["defense"].items()}
    return DixonColesResult(
        teams=teams,
        mu=float(d["mu"]),
        home_advantage=float(d["home_advantage"]),
        rho=float(d["rho"]),
        attack=attack,
        defense=defense,
        n_matches=int(d["n_matches"]),
        log_likelihood=float(d["log_likelihood"]),
        converged=bool(d["converged"]),
        half_life_days=float(d["half_life_days"]),
        fitted_at=d.get("fitted_at", ""),
        _att_arr=np.array([attack[t] for t in teams], dtype=float),
        _def_arr=np.array([defense[t] for t in teams], dtype=float),
        _idx={t: i for i, t in enumerate(teams)},
    )


def save_hf(model: HalfFullModel, path: str | Path) -> Path:
    """保存半全场模型为 JSON。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": "halffull",
        "mu_half": model.mu_half,
        "home_adv_half": model.home_adv_half,
        "transition": np.asarray(model.transition, dtype=float).tolist(),
        "attack_half": model.attack_half,
        "defense_half": model.defense_half,
        "n_matches": model.n_matches,
        "converged": model.converged,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return path


def load_hf(path: str | Path) -> HalfFullModel:
    """从 JSON 还原半全场模型。"""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if d.get("kind") not in (None, "halffull"):
        raise ValueError(f"并非半全场模型文件: {path}")
    return HalfFullModel(
        mu_half=float(d["mu_half"]),
        home_adv_half=float(d["home_adv_half"]),
        transition=np.array(d["transition"], dtype=float),
        attack_half={k: float(v) for k, v in d["attack_half"].items()},
        defense_half={k: float(v) for k, v in d["defense_half"].items()},
        n_matches=int(d["n_matches"]),
        converged=bool(d["converged"]),
    )
