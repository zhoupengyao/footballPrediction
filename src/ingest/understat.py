"""Understat 数据接入：五大联赛 + 俄超，含 xG 特征。

接口：https://understat.com/getLeagueData/{league}/{season}
    - 需要 X-Requested-With: XMLHttpRequest 头
    - season 为起始年，如 2026 表示 2026/27 赛季
    - dates 字段给出逐场比分 + xG；teams[*].history 给出逐队逐场 xG/xGA/PPDA/深层传球

用途：
    1. 补齐 GitHub 镜像缺失的当前赛季（2026/27）赛果
    2. 提供 xG / PPDA 等特征（仅五大联赛 + 俄超，2014/15 起）
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from src.config import get_settings

BASE = "https://understat.com"

# understat 联赛代码 -> 我们的联赛代码（对齐 football-data div）
LEAGUE_MAP = {
    "EPL": "E0",
    "Bundesliga": "D1",
    "La liga": "SP1",
    "Serie A": "I1",
    "Ligue 1": "F1",
    "RFPL": "RUS1",
}

# understat 队名（官方全名）-> 项目统一短名（与 football-data 镜像一致）。
# 只列与 football-data 写法不同的；完全一致的名字无需映射。
# 目的：让 understat 数据能按队名与 tier1 数据对齐（补当前赛季、对账用）。
UNDERSTAT_TO_CANONICAL: dict[str, str] = {
    # 英超
    "Manchester City": "Man City",
    "Manchester United": "Man United",
    "Newcastle United": "Newcastle",
    "Nottingham Forest": "Nott'm Forest",
    "Queens Park Rangers": "QPR",
    "West Bromwich Albion": "West Brom",
    "Wolverhampton Wanderers": "Wolves",
    # 德甲
    "Bayer Leverkusen": "Leverkusen",
    "Borussia Dortmund": "Dortmund",
    "Borussia M.Gladbach": "M'gladbach",
    "Eintracht Frankfurt": "Ein Frankfurt",
    "FC Cologne": "FC Koln",
    "FC Heidenheim": "Heidenheim",
    "Fortuna Duesseldorf": "Fortuna Dusseldorf",
    "Greuther Fuerth": "Greuther Furth",
    "Hamburger SV": "Hamburg",
    "Hannover 96": "Hannover",
    "Hertha Berlin": "Hertha",
    "Mainz 05": "Mainz",
    "Nuernberg": "Nurnberg",
    "RasenBallsport Leipzig": "RB Leipzig",
    "VfB Stuttgart": "Stuttgart",
    "St. Pauli": "St Pauli",
    "Arminia Bielefeld": "Bielefeld",
    # 西甲
    "Atletico Madrid": "Ath Madrid",
    "Athletic Club": "Ath Bilbao",
    "Celta Vigo": "Celta",
    "Deportivo La Coruna": "La Coruna",
    "Espanyol": "Espanol",
    "Racing Santander": "Santander",
    "Rayo Vallecano": "Vallecano",
    "Real Betis": "Betis",
    "Real Oviedo": "Oviedo",
    "Real Sociedad": "Sociedad",
    "Real Valladolid": "Valladolid",
    "Sporting Gijon": "Sp Gijon",
    "SD Huesca": "Huesca",
    # 意甲
    "AC Milan": "Milan",
    "Parma Calcio 1913": "Parma",
    "SPAL 2013": "Spal",
    # 法甲
    "Clermont Foot": "Clermont",
    "Paris Saint Germain": "Paris SG",
    "Saint-Etienne": "St Etienne",
    "GFC Ajaccio": "Ajaccio GFCO",
    "SC Bastia": "Bastia",
}


def normalize_team(name: str) -> str:
    """把 understat 队名转成项目统一短名；未收录时返回原名。"""
    return UNDERSTAT_TO_CANONICAL.get(name, name)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://understat.com/",
    "X-Requested-With": "XMLHttpRequest",
}


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_league_season(league: str, season: int, retries: int = 3) -> dict:
    """抓取单个联赛单赛季数据。"""
    url = f"{BASE}/getLeagueData/{league}/{season}"
    last: Exception | None = None
    for i in range(retries):
        try:
            time.sleep(1.5)
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            ct = r.headers.get("Content-Type", "")
            if "json" not in ct and "javascript" not in ct:
                raise RuntimeError(f"非 JSON 响应: {ct}")
            return r.json()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 ** i * 2)
    raise RuntimeError(f"抓取失败 {league}/{season}: {last}")


def matches_to_frame(data: dict, league_code: str, season: int) -> pd.DataFrame:
    """把 dates 数组展开为逐场 DataFrame。"""
    rows = []
    for m in data.get("dates", []):
        h = m.get("h", {}) or {}
        a = m.get("a", {}) or {}
        rows.append({
            "league_code": league_code,
            "season": season,
            "understat_id": m.get("id"),
            "date": m.get("datetime", "")[:10],
            "home_team": h.get("title"),
            "away_team": a.get("title"),
            "home_short": h.get("short_title"),
            "away_short": a.get("short_title"),
            "ft_home": _f((m.get("goals") or {}).get("h")),
            "ft_away": _f((m.get("goals") or {}).get("a")),
            "xg_home": _f((m.get("xG") or {}).get("h")),
            "xg_away": _f((m.get("xG") or {}).get("a")),
            "is_result": bool(m.get("isResult")),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    # 推导全场结果
    done = df["ft_home"].notna() & df["ft_away"].notna()
    df["ft_result"] = None
    df.loc[done & (df["ft_home"] > df["ft_away"]), "ft_result"] = "H"
    df.loc[done & (df["ft_home"] == df["ft_away"]), "ft_result"] = "D"
    df.loc[done & (df["ft_home"] < df["ft_away"]), "ft_result"] = "A"
    return df.sort_values("date").reset_index(drop=True)


def team_features_frame(data: dict, league_code: str, season: int) -> pd.DataFrame:
    """从 teams[*].history 提取逐队逐场特征（xG/xGA/PPDA/深层传球）。"""
    rows = []
    teams = data.get("teams", {}) or {}
    for tid, team in teams.items():
        title = team.get("title")
        for h in team.get("history", []) or []:
            ppda = h.get("ppda") or {}
            ppda_a = h.get("ppda_allowed") or {}
            rows.append({
                "league_code": league_code,
                "season": season,
                "team": title,
                "date": (h.get("date") or "")[:10],
                "is_home": h.get("h_a") == "h",
                "xg_for": _f(h.get("xG")),
                "xg_against": _f(h.get("xGA")),
                "npxg_for": _f(h.get("npxG")),
                "npxg_against": _f(h.get("npxGA")),
                "ppda_att": _f(ppda.get("att")),
                "ppda_def": _f(ppda.get("def")),
                "ppda_allowed_att": _f(ppda_a.get("att")),
                "ppda_allowed_def": _f(ppda_a.get("def")),
                "deep": _f(h.get("deep")),
                "deep_allowed": _f(h.get("deep_allowed")),
                "scored": _f(h.get("scored")),
                "missed": _f(h.get("missed")),
                "xpts": _f(h.get("xpts")),
                "result": h.get("result"),
                "cum_wins": _f(h.get("wins")),
                "cum_draws": _f(h.get("draws")),
                "cum_loses": _f(h.get("loses")),
                "cum_pts": _f(h.get("pts")),
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df.sort_values(["team", "date"]).reset_index(drop=True)


def fetch_all(seasons: list[int] | None = None,
              leagues: list[str] | None = None,
              save: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """抓取全部联赛赛季，返回 (逐场赛果, 逐队特征)。"""
    leagues = leagues or list(LEAGUE_MAP.keys())
    seasons = seasons or list(range(2014, 2027))  # 2014/15 .. 2026/27

    match_frames: list[pd.DataFrame] = []
    team_frames: list[pd.DataFrame] = []

    for lg in leagues:
        code = LEAGUE_MAP[lg]
        for season in seasons:
            try:
                data = fetch_league_season(lg, season)
            except Exception as e:  # noqa: BLE001
                print(f"  [跳过] {lg}/{season}: {e}")
                continue
            mf = matches_to_frame(data, code, season)
            tf = team_features_frame(data, code, season)
            if not mf.empty:
                match_frames.append(mf)
            if not tf.empty:
                team_frames.append(tf)
            print(f"  {code}/{season}: {len(mf)} 场, {len(tf)} 队次记录")

    matches = pd.concat(match_frames, ignore_index=True) if match_frames else pd.DataFrame()
    teams = pd.concat(team_frames, ignore_index=True) if team_frames else pd.DataFrame()

    if save and not matches.empty:
        settings = get_settings()
        settings.ensure_dirs()
        matches.to_parquet(settings.processed_dir / "understat_matches.parquet", index=False)
        teams.to_parquet(settings.processed_dir / "understat_team_features.parquet", index=False)
        print(f"\n已保存: understat_matches.parquet ({len(matches)})")
        print(f"已保存: understat_team_features.parquet ({len(teams)})")

    return matches, teams


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    # 先验证单赛季
    d = fetch_league_season("EPL", 2026)
    mf = matches_to_frame(d, "E0", 2026)
    tf = team_features_frame(d, "E0", 2026)
    print(f"EPL 2026/27: {len(mf)} 场 (已完成 {mf['is_result'].sum()}), {len(tf)} 队次")
    print(mf.head(5).to_string(index=False))
    print("\n最近已完成:")
    fin = mf[mf["is_result"]]
    print(fin.nlargest(5, "date")[["date", "home_team", "away_team", "ft_home", "ft_away", "xg_home", "xg_away"]].to_string(index=False))
