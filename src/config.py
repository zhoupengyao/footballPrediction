"""配置加载与路径管理。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# 项目根目录（本文件所在目录的上一级）
# 可用 FOOTBALL_HOME 覆盖，便于在 CI / 容器 / 其他机器上运行。
_ENV_ROOT = os.environ.get("FOOTBALL_HOME", "").strip()
PROJECT_ROOT = (Path(_ENV_ROOT).expanduser().resolve()
                if _ENV_ROOT else Path(__file__).resolve().parent.parent)
CONFIG_DIR = PROJECT_ROOT / "config"


def _resolve_path(value: str | Path) -> Path:
    """把配置里的路径解析成绝对路径。

    相对路径按项目根目录解析，支持 ``~`` 与 ``${FOOTBALL_HOME}`` 形式的写法。
    这样 settings.yaml 可以在 Windows / Linux / GitHub Actions 共用。
    """
    text = str(value).strip()
    for prefix in ("${FOOTBALL_HOME}", "$FOOTBALL_HOME"):
        if text.startswith(prefix):
            text = str(PROJECT_ROOT) + text[len(prefix):]
            break
    p = Path(text).expanduser()
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p.resolve()


def _load_dotenv(path: Path | None = None) -> None:
    """极简 .env 加载（无第三方依赖）：把 KEY=VALUE 行注入环境变量（不覆盖已有值）。"""
    dotenv = path or (PROJECT_ROOT / ".env")
    if not dotenv.exists():
        return
    for line in dotenv.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, val)


# 启动即加载 .env（API key 等）
_load_dotenv()


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class Settings:
    """全局设置（settings.yaml）。"""

    def __init__(self, data: dict[str, Any]):
        self._d = data

    def __getitem__(self, key: str) -> Any:
        return self._d[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._d.get(key, default)

    @property
    def raw_dir(self) -> Path:
        return _resolve_path(self._d["paths"]["raw"])

    @property
    def processed_dir(self) -> Path:
        return _resolve_path(self._d["paths"]["processed"])

    @property
    def odds_dir(self) -> Path:
        return _resolve_path(self._d["paths"]["odds"])

    @property
    def cache_dir(self) -> Path:
        return _resolve_path(self._d["paths"]["cache"])

    @property
    def models_dir(self) -> Path:
        return _resolve_path(self._d["paths"]["models"])

    @property
    def reports_dir(self) -> Path:
        return _resolve_path(self._d["paths"]["reports"])

    @property
    def apifootball_key(self) -> str:
        """API key：优先环境变量，其次配置文件。"""
        return os.environ.get("API_SPORTS_KEY", "") or self._d["apifootball"].get("api_key", "")

    @property
    def edge_threshold(self) -> float:
        return float(self._d["value"]["edge_threshold"])

    @property
    def kelly_fraction(self) -> float:
        return float(self._d["value"]["kelly_fraction"])

    @property
    def max_stake_pct(self) -> float:
        return float(self._d["value"]["max_stake_pct"])

    @property
    def blend_weight(self) -> float:
        """模型概率与去水市场概率的混合权重（0~1）。"""
        return float(self._d["value"].get("blend_weight", 0.6))

    @property
    def min_odds(self) -> float:
        """价值投注的最低赔率阈值。"""
        return float(self._d["value"].get("min_odds", 1.30))

    @property
    def max_edge(self) -> float:
        """价值投注的 edge 上限（过滤异常值）。"""
        return float(self._d["value"].get("max_edge", 0.50))

    def recommend_for(self, risk: str | None = None) -> dict[str, Any]:
        """候选筛选配置（套用指定风险档位覆盖；risk=None 用默认档位）。"""
        d = dict(self._d.get("recommend", {}))
        profiles = d.pop("profiles", {})
        if risk is None:
            risk = d.get("risk", "conservative")
        d.update(profiles.get(risk, {}))
        d["risk"] = risk
        return d

    @property
    def recommend(self) -> dict[str, Any]:
        """候选筛选配置（已套用默认风险档位覆盖）。"""
        return self.recommend_for(None)

    @property
    def random_seed(self) -> int:
        return int(self._d["training"]["random_seed"])

    @property
    def dc_half_life_days(self) -> float:
        return float(self._d["training"]["dc_half_life_days"])

    @property
    def shrinkage_prior(self) -> float:
        """Dixon-Coles 攻防强度的小样本收缩先验（场数，0=不收缩）。"""
        return float(self._d["training"].get("shrinkage_prior", 0.0))

    @property
    def elo_blend_weight(self) -> float:
        """Elo 与 Dixon-Coles 混合时 DC 的权重（0~1）。"""
        return float(self._d["training"].get("elo_blend_weight", 0.8))

    @property
    def ml_blend_weight(self) -> float:
        """LightGBM 与 DC+Elo 混合时 DC+Elo 的权重（0~1）。"""
        return float(self._d["training"].get("ml_blend_weight", 0.8))

    @property
    def lgbm_params(self) -> dict[str, Any]:
        return dict(self._d["training"]["lgbm"])

    @property
    def training_overrides(self) -> dict[str, dict[str, Any]]:
        """按联赛覆盖训练参数，如 UCL 的 years / half_life。"""
        return dict(self._d.get("training", {}).get("overrides", {}))

    @property
    def backtest_min_train_size(self) -> int:
        return int(self._d["backtest"]["min_train_size"])

    @property
    def backtest_refit_interval(self) -> int:
        return int(self._d["backtest"]["refit_interval"])

    def ensure_dirs(self) -> None:
        for path in (self.raw_dir, self.processed_dir, self.odds_dir,
                     self.cache_dir, self.models_dir, self.reports_dir):
            path.mkdir(parents=True, exist_ok=True)


class Leagues:
    """联赛分档配置（leagues.yaml）。"""

    def __init__(self, data: dict[str, Any]):
        self._d = data

    @property
    def tier1(self) -> dict[str, dict[str, Any]]:
        return self._d["tier1_footballdata"]

    @property
    def tier1_source(self) -> dict[str, Any]:
        return self._d["tier1_source"]

    @property
    def tier2(self) -> dict[str, dict[str, Any]]:
        return self._d["tier2_apifootball"]

    @property
    def tier2_by_div(self) -> dict[str, int]:
        """div 代码 -> API-Football 联赛 id（只含带 div 字段的条目）。"""
        return {info["div"]: int(k)
                for k, info in self.tier2.items() if "div" in info}

    @property
    def tier3(self) -> dict[str, Any]:
        return self._d["tier3_nationalteams"]

    @property
    def extra(self) -> dict[str, dict[str, Any]]:
        """额外赛事（数据源不在 football-data 镜像里，如欧冠）。"""
        return self._d.get("extra_competitions", {})

    @property
    def extra_datasets(self) -> list[str]:
        """额外赛事对应的 processed 数据集名（如 ucl_matches）。"""
        return [f"{c.lower()}_matches" for c in self.extra]

    @property
    def model_groups(self) -> dict[str, dict[str, Any]]:
        """跨联赛合并模型定义（如 EUR：欧战合并模型）。"""
        return self._d.get("model_groups", {})

    def model_members(self, key: str) -> list[str]:
        """key 对应模型的训练数据成员联赛；非组时返回 [key]。"""
        g = self.model_groups.get(key)
        return [str(m) for m in g["members"]] if g else [key]

    def model_key_for(self, div: str | None, available: Any = None) -> str | None:
        """预测 div 时应使用的模型键。

        div 属于某组的 covers 且该组模型可用（available 含其键，
        或 available=None 不做检查）时返回组键，否则原样返回 div。
        """
        if div is None:
            return None
        for key, g in self.model_groups.items():
            if div in g.get("covers", []):
                if available is None or key in available:
                    return key
        return div

    @property
    def jc_league_map(self) -> dict[str, str]:
        """竞彩中文联赛名 -> 我们的 div 代码。"""
        return self._d.get("jingcai_league_map", {})

    def jc_name_to_div(self, name: str) -> str | None:
        """把竞彩中文联赛名翻译成本项目 div 代码，未收录返回 None。"""
        return self.jc_league_map.get((name or "").strip())

    @property
    def markets(self) -> dict[str, Any]:
        return self._d["jingcai_markets"]

    @property
    def tier1_codes(self) -> list[str]:
        return list(self.tier1.keys())

    @property
    def tier2_ids(self) -> list[int]:
        return [int(k) for k in self.tier2.keys()]

    def name_of(self, code: str) -> str:
        info = (self.tier1.get(code) or self.extra.get(code)
                or self.model_groups.get(code))
        if info:
            return info["name"]
        for _id, t2 in self.tier2.items():
            if t2.get("div") == code:
                return t2["name"]
        return code

    def jc_common_tier1(self) -> list[str]:
        return [c for c, v in self.tier1.items() if v.get("jc_common")]


_settings: Settings | None = None
_leagues: Leagues | None = None


def get_settings(reload: bool = False) -> Settings:
    global _settings
    if _settings is None or reload:
        _settings = Settings(_load_yaml(CONFIG_DIR / "settings.yaml"))
    return _settings


def get_leagues(reload: bool = False) -> Leagues:
    global _leagues
    if _leagues is None or reload:
        _leagues = Leagues(_load_yaml(CONFIG_DIR / "leagues.yaml"))
    return _leagues
