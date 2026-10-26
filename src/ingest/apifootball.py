"""API-Football (v3) 数据接入。

用于 football-data.co.uk / jokecamp 镜像都**没有**的联赛（巴甲、挪超、瑞超、
芬超等 tier2 联赛）。免费额度 100 次/天，按需抓取。

接口：https://v3.football.api-sports.io
认证：Header ``x-apisports-key: <key>``（key 走环境变量 API_SPORTS_KEY 或 .env）
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from src.config import get_settings

BASE = "https://v3.football.api-sports.io"

# API-Football 联赛 id -> 本项目 div 代码（竞彩常见开售的 tier2 联赛）
LEAGUE_TO_DIV: dict[int, str] = {
    103: "NOR1",  # 挪超 Eliteserien
    113: "SWE1",  # 瑞超 Allsvenskan
    244: "FIN1",  # 芬超 Veikkausliiga
    71:  "BRA1",  # 巴甲 Serie A
}

DIV_TO_LEAGUE: dict[str, int] = {v: k for k, v in LEAGUE_TO_DIV.items()}


def _headers() -> dict[str, str]:
    key = get_settings().apifootball_key
    if not key:
        raise RuntimeError(
            "未配置 API-Football key：请在 .env 里设置 API_SPORTS_KEY，"
            "或写入 settings.yaml 的 apifootball.api_key")
    return {"x-apisports-key": key, "Accept": "application/json"}


def _get(url: str, params: dict | None = None,
         retries: int = 3, interval: float = 1.0) -> dict:
    """带重试与限速的 GET（免费额度 100 次/天，间隔默认 1s）。"""
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            time.sleep(interval)
            r = requests.get(url, params=params, headers=_headers(), timeout=40)
            if r.status_code == 429:
                raise RuntimeError("已触发限流(429)，请稍后再试")
            r.raise_for_status()
            d = r.json()
            if d.get("errors"):
                raise RuntimeError(f"接口返回错误: {d['errors']}")
            return d
        except Exception as e:  # noqa: BLE001
            last_exc = e
            time.sleep(2 ** attempt * 2)
    raise RuntimeError(f"请求失败: {last_exc}")


def fetch_fixtures(league_id: int, season: int) -> list[dict]:
    """抓取某联赛某赛季的全部赛程（一次请求返回整季，含已完赛比分）。"""
    d = _get(f"{BASE}/fixtures", params={"league": league_id, "season": season})
    return d.get("response", [])


def fixtures_to_frame(fixtures: list[dict], league_code: str) -> pd.DataFrame:
    """把 fixtures 原始记录转成统一 schema 的比赛表（只保留已完赛的 90 分钟比分）。"""
    rows = []
    for f in fixtures:
        goals = f.get("goals") or {}
        if goals.get("home") is None or goals.get("away") is None:
            continue  # 未开赛/未完赛
        teams = f.get("teams") or {}
        home = (teams.get("home") or {}).get("name")
        away = (teams.get("away") or {}).get("name")
        date = (f.get("fixture") or {}).get("date")
        if not home or not away or not date:
            continue
        score = f.get("score") or {}
        ht = score.get("halftime") or {}
        rows.append({
            "league_code": league_code,
            "date": pd.to_datetime(date, utc=True).date().isoformat(),
            "home_team": home,
            "away_team": away,
            "ft_home": int(goals["home"]),
            "ft_away": int(goals["away"]),
            "ht_home": int(ht["home"]) if ht.get("home") is not None else None,
            "ht_away": int(ht["away"]) if ht.get("away") is not None else None,
            "season": int((f.get("league") or {}).get("season", 0)),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "home_team", "away_team", "ft_home", "ft_away"])
    return df.drop_duplicates(
        subset=["league_code", "date", "home_team", "away_team"]
    ).sort_values(["league_code", "date"]).reset_index(drop=True)


def build_dataset(divs: list[str] | None = None,
                  seasons: list[int] | None = None,
                  save: bool = True,
                  verbose: bool = True) -> pd.DataFrame:
    """抓取多个联赛多个赛季的赛果，返回合并后的比赛表。

    divs 为 None 时抓取 LEAGUE_TO_DIV 里全部联赛；seasons 为 None 时取
    近 6 个赛季（当前年往前推）。
    """
    import datetime

    want_divs = divs or list(LEAGUE_TO_DIV.values())
    if seasons is None:
        this_year = datetime.date.today().year
        seasons = list(range(this_year - 5, this_year + 1))  # 近 6 季

    frames: list[pd.DataFrame] = []
    for div in want_divs:
        lid = DIV_TO_LEAGUE[div]
        sub_frames: list[pd.DataFrame] = []
        for season in seasons:
            try:
                fixtures = fetch_fixtures(lid, season)
            except Exception as e:  # noqa: BLE001
                if verbose:
                    print(f"  [失败] {div}({lid}) {season}: {e}")
                continue
            df = fixtures_to_frame(fixtures, div)
            if verbose:
                print(f"  {div}({lid}) {season}: {len(df)} 场")
            if not df.empty:
                sub_frames.append(df)
        if sub_frames:
            frames.append(pd.concat(sub_frames, ignore_index=True))

    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames, ignore_index=True)
    if save:
        save_dataset(out)
    return out


def save_dataset(df: pd.DataFrame, name: str = "apifootball_matches") -> Path:
    settings = get_settings()
    settings.ensure_dirs()
    path = settings.processed_dir / f"{name}.parquet"
    df.to_parquet(path, index=False)
    return path


def load_dataset(name: str = "apifootball_matches") -> pd.DataFrame:
    settings = get_settings()
    path = settings.processed_dir / f"{name}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"数据集不存在: {path}")
    return pd.read_parquet(path)
