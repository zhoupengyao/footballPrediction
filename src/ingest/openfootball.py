"""openfootball 赛事数据接入（欧冠 / 欧罗巴 / 欧协联通用）。

数据源
------
openfootball/champions-league（public domain 的 football.txt 格式）::

    https://github.com/openfootball/champions-league
    <season>/cl.txt     欧冠
    <season>/el.txt     欧罗巴
    <season>/conf.txt   欧协联

本机无法直连 raw.githubusercontent.com，统一走 ghproxy.net 代理。

各赛事可用赛季（实测 404 情况）：
    UCL   2011-12 ~ 2025-26
    UEL   2021-22 ~ 2024-25（2025-26 暂缺，抓取时自动跳过）
    CONF  2021-22 ~ 2024-25（同上）

解析约定
--------
竞彩按 **90 分钟**结算，因此淘汰赛必须剔除加时和点球：

    普通:        2-3 (1-1)                  -> 90' 2-3, 半场 1-1
    加时:        4-1 a.e.t. (3-1, 1-0)      -> 90' 3-1, 半场 1-0
    点球:        4-2 pen. 1-0 a.e.t. (1-0, 1-0)
                                            -> 90' 1-0, 半场 1-0
    点球(无加时进球): 8-7 pen. 0-0 a.e.t. (0-0)
                                            -> 90' 0-0, 半场 0-0

即：括号里两段时，第一段是 90 分钟比分、第二段是半场比分；
只有一段时，那一段是半场比分（90 分钟比分取正文）。
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from src.config import get_settings
from src.ingest.ucl_names import RAW_TO_CANONICAL, normalize_team, strip_country

URL_TEMPLATE = (
    "https://ghproxy.net/https://raw.githubusercontent.com/"
    "openfootball/champions-league/master/{season}/{file}"
)
HEADERS = {"User-Agent": "Mozilla/5.0 (jingcai-predict)"}

# 赛事注册表：file=仓库内文件名，name=中文名，
# start/end=可用赛季起止（左闭右开，赛季标签如 2021-22）
COMPETITIONS: dict[str, dict[str, Any]] = {
    "UCL": {"file": "cl.txt", "name": "欧冠", "start": 2011, "end": 2026},
    "UEL": {"file": "el.txt", "name": "欧罗巴", "start": 2021, "end": 2026},
    "CONF": {"file": "conf.txt", "name": "欧协联", "start": 2021, "end": 2026},
}


def comp_name(comp: str) -> str:
    return COMPETITIONS[comp]["name"]


def dataset_name(comp: str) -> str:
    """processed 数据集文件名（不含扩展名），如 UCL -> ucl_matches。"""
    return f"{comp.lower()}_matches"


def default_seasons(comp: str) -> list[str]:
    spec = COMPETITIONS[comp]
    return [f"{y}-{str(y + 1)[2:]}" for y in range(spec["start"], spec["end"])]


# --------------------------------------------------------------------------- #
# 抓取 / 缓存
# --------------------------------------------------------------------------- #
def _cache_path(comp: str, season: str) -> Path:
    return get_settings().raw_dir / comp.lower() / f"season-{season}.txt"


def fetch_season(comp: str, season: str, force: bool = False,
                 timeout: int = 40, retries: int = 3) -> str:
    """下载单个赛季的赛事文件，缓存到 data/raw/{comp}/season-XXXX.txt。

    ghproxy 间歇性 RemoteDisconnected，连接错误重试最多 ``retries`` 次。
    """
    path = _cache_path(comp, season)
    if path.exists() and not force:
        return path.read_text(encoding="utf-8")

    url = URL_TEMPLATE.format(season=season, file=COMPETITIONS[comp]["file"])
    last_exc: Exception | None = None
    for _ in range(retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
        except requests.RequestException as exc:  # 连接中断，重试
            last_exc = exc
            continue
        if resp.status_code != 200:
            raise FileNotFoundError(
                f"{comp_name(comp)}数据不可用: {season}"
                f"（HTTP {resp.status_code}）\n  {url}"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(resp.text, encoding="utf-8")
        return resp.text
    raise ConnectionError(f"{comp_name(comp)} {season} 下载失败: {last_exc}")


def read_cached(comp: str, season: str) -> str | None:
    path = _cache_path(comp, season)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #
def _parse_pairs(text: str) -> list[tuple[int, int]]:
    return [(int(h), int(a)) for h, a in re.findall(r"(\d+)-(\d+)", text)]


def _parse_scores(h: int, a: int, tail: str) -> tuple[tuple[int, int], tuple[int, int] | None]:
    """返回 (90 分钟比分, 半场比分或 None)。"""
    paren = re.search(r"\(([^)]*)\)", tail)
    pairs = _parse_pairs(paren.group(1)) if paren else []

    if "pen." in tail:
        # 正文是点球比分；"pen." 后面是加时结束比分
        aet = re.search(r"pen\.\s*(\d+)-(\d+)", tail)
        et_final = (int(aet.group(1)), int(aet.group(2))) if aet else (h, a)
        ft90 = pairs[0] if len(pairs) >= 2 else et_final
        ht = pairs[-1] if pairs else None
    elif "a.e.t." in tail:
        ft90 = pairs[0] if len(pairs) >= 2 else (h, a)
        ht = pairs[-1] if pairs else None
    else:
        ft90 = (h, a)
        ht = pairs[0] if pairs else None

    return ft90, ht


def _infer_date(month: int, day: int, season_start: int,
                explicit_year: int | None,
                last_date: date | None) -> date | None:
    """推断日期行缺失的年份（跨年赛季）。"""
    if explicit_year is not None:
        year = explicit_year
    elif last_date is not None:
        candidates = [season_start, season_start + 1, season_start + 2]
        valid: list[tuple[date, int]] = []
        for y in candidates:
            try:
                d = date(y, month, day)
            except ValueError:
                continue
            if d >= last_date - timedelta(days=3):
                valid.append((d, y))
        year = min(valid)[1] if valid else season_start
    else:
        year = season_start if month >= 7 else season_start + 1

    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_season(text: str, season: str, verbose: bool = False,
                 comp: str = "UCL") -> list[dict[str, Any]]:
    """解析单个赛季，返回逐场记录（只保留 90 分钟比分）。"""
    season_start = int(season[:4])
    league_code = comp
    league_name = comp_name(comp)
    rows: list[dict[str, Any]] = []
    stage = ""
    current: date | None = None
    last: date | None = None
    unmapped: set[str] = set()

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("="):
            continue
        if stripped.startswith("▪"):
            stage = stripped.lstrip("▪").strip()
            continue

        dm = _DATE_RE.match(line)
        if dm:
            month = _MONTHS.get(dm.group(1))
            if month is None:
                continue
            explicit = int(dm.group(3)) if dm.group(3) else None
            current = _infer_date(month, int(dm.group(2)), season_start, explicit, last)
            if current is not None:
                last = current
            continue

        mm = _MATCH_RE.match(line)
        if not mm or current is None:
            continue

        home_raw = strip_country(mm.group("home"))
        away_raw = strip_country(mm.group("away"))
        if home_raw not in RAW_TO_CANONICAL:
            unmapped.add(home_raw)
        if away_raw not in RAW_TO_CANONICAL:
            unmapped.add(away_raw)

        ft90, ht = _parse_scores(int(mm.group("h")), int(mm.group("a")), mm.group("tail"))
        fh, fa = ft90
        rows.append({
            "date": pd.Timestamp(current),
            "home_team": normalize_team(home_raw),
            "away_team": normalize_team(away_raw),
            "ft_home": fh,
            "ft_away": fa,
            "ft_result": "H" if fh > fa else ("A" if fh < fa else "D"),
            "ht_home": ht[0] if ht else None,
            "ht_away": ht[1] if ht else None,
            "stage": stage,
            "season": season,
            "league_code": league_code,
            "league_name": league_name,
        })

    if unmapped and verbose:
        print(f"  [警告] {comp} {season} 有未归一化队名: {', '.join(sorted(unmapped))}")
    return rows


_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

_DATE_RE = re.compile(r"^\s+\w{3}\s+(\w{3})\s+(\d{1,2})(?:\s+(\d{4}))?\s*$")
_MATCH_RE = re.compile(
    r"^\s+(?:(\d{1,2}:\d{2})\s+)?(?P<home>.+?)\s+v\s+(?P<away>.+?)\s+"
    r"(?P<h>\d+)-(?P<a>\d+)(?P<tail>.*)$"
)


# --------------------------------------------------------------------------- #
# 数据集
# --------------------------------------------------------------------------- #
def build_dataset(comp: str, seasons: list[str] | None = None, online: bool = False,
                  force: bool = False, verbose: bool = True) -> pd.DataFrame:
    """抓取/读取缓存并解析成统一 schema 的 DataFrame。"""
    seasons = seasons or default_seasons(comp)
    frames: list[pd.DataFrame] = []

    for season in seasons:
        text = None
        # --force 只有配合 --online 才重新下载；否则仍读缓存
        if not (force and online):
            text = read_cached(comp, season)
        if text is None and online:
            try:
                text = fetch_season(comp, season, force=force)
            except Exception as exc:  # noqa: BLE001
                if verbose:
                    print(f"  [失败] {season}: {exc}")
                continue
        if text is None:
            if verbose:
                print(f"  [跳过] {season}: 无缓存（加 --online 抓取）")
            continue

        rows = parse_season(text, season, verbose=verbose, comp=comp)
        if verbose:
            print(f"  {season}: {len(rows)} 场")
        if rows:
            frames.append(pd.DataFrame(rows))

    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    return df.sort_values("date").reset_index(drop=True)


def save_dataset(df: pd.DataFrame, comp: str, name: str | None = None) -> Path:
    settings = get_settings()
    settings.ensure_dirs()
    path = settings.processed_dir / f"{name or dataset_name(comp)}.parquet"
    df.to_parquet(path, index=False)
    return path


def load_dataset(comp: str, name: str | None = None) -> pd.DataFrame:
    settings = get_settings()
    path = settings.processed_dir / f"{name or dataset_name(comp)}.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"数据集不存在: {path}\n"
            f"请先运行 python -m src.cli fetch-ucl/fetch-europa --online"
        )
    return pd.read_parquet(path)
