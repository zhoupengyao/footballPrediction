"""football-data.co.uk 数据接入层。

由于本机网络无法直连 football-data.co.uk（连接被拒），
改用 GitHub 上的每日自动同步镜像：
    https://github.com/datasets/football-datasets
该镜像源自 football-data.co.uk，含 2000/01 起五大联赛的
比分 / 半场比分 / 射门 / 角球 / 红黄牌数据。

注意：镜像不含赔率列，赔率需另行获取（见 docs/odds_gap.md）。
"""
from __future__ import annotations

import base64
import io
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from src.config import get_leagues, get_settings

REPO = "datasets/football-datasets"
ZIPBALL_URL = f"https://api.github.com/repos/{REPO}/zipball"

# football-data.co.uk div 代码 -> 镜像仓库目录名
DIV_TO_DIR = {
    "E0": "premier-league",
    "D1": "bundesliga",
    "SP1": "la-liga",
    "I1": "serie-a",
    "F1": "ligue-1",
}

# 统一 schema：镜像列名 -> 我们的规范列名
RENAME_MAP = {
    "Date": "date",
    "HomeTeam": "home_team",
    "AwayTeam": "away_team",
    "FTHG": "ft_home",
    "FTAG": "ft_away",
    "FTR": "ft_result",
    "HTHG": "ht_home",
    "HTAG": "ht_away",
    "HTR": "ht_result",
    "Referee": "referee",
    "HS": "shots_home",
    "AS": "shots_away",
    "HST": "sot_home",
    "AST": "sot_away",
    "HF": "fouls_home",
    "AF": "fouls_away",
    "HC": "corners_home",
    "AC": "corners_away",
    "HY": "yellow_home",
    "AY": "yellow_away",
    "HR": "red_home",
    "AR": "red_away",
}


def _http() -> requests.Session:
    s = requests.Session()
    s.headers["Accept"] = "application/vnd.github.v3+json"
    s.headers["User-Agent"] = "jingcai-predict/0.1"
    return s


def download_mirror(dest: Path, force: bool = False) -> Path:
    """一次性打包下载镜像仓库，解压到 data/raw/football-datasets/。"""
    marker = dest / ".download_complete"
    if marker.exists() and not force:
        print(f"镜像已存在，跳过下载: {dest}")
        return dest

    print("正在下载 football-datasets 镜像（一次性）...")
    s = _http()
    resp = s.get(ZIPBALL_URL, timeout=180, stream=True)
    resp.raise_for_status()

    data = resp.content
    print(f"  下载完成: {len(data) / 1024 / 1024:.2f} MB")

    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(dest)
        # zipball 根目录带 owner-repo-sha 前缀，记录下来供后续查找
        top = {n.split("/")[0] for n in zf.namelist()}
        print(f"  解压完成，顶层目录: {top}")

    marker.write_text("ok", encoding="utf-8")
    return dest


def _find_league_dir(root: Path, dirname: str) -> Path | None:
    """在解压结果中定位联赛目录（容忍 owner-repo-sha 前缀）。"""
    for p in root.rglob(dirname):
        if p.is_dir():
            return p
    return None


def _read_season_csv(path: Path) -> pd.DataFrame:
    """读取单个赛季 CSV，容忍编码与列名差异。"""
    for enc in ("utf-8", "latin-1"):
        try:
            df = pd.read_csv(path, encoding=enc, on_bad_lines="skip")
            break
        except Exception:
            continue
    else:
        return pd.DataFrame()

    # 只保留我们认识的列
    keep = [c for c in df.columns if c in RENAME_MAP]
    if not keep:
        return pd.DataFrame()
    df = df[keep].copy()
    df = df.rename(columns=RENAME_MAP)
    return df


def load_tier1(divs: list[str] | None = None, seasons: list[str] | None = None) -> pd.DataFrame:
    """从本地镜像加载 Tier 1 数据，返回统一 schema 的 DataFrame。"""
    settings = get_settings()
    root = settings.raw_dir / "football-datasets"
    if not root.exists():
        raise FileNotFoundError(
            f"镜像数据不存在: {root}\n请先运行 python -m src.cli fetch-tier1"
        )

    divs = divs or [d for d in DIV_TO_DIR if d in get_leagues().tier1]

    frames: list[pd.DataFrame] = []
    for div in divs:
        dirname = DIV_TO_DIR[div]
        league_dir = _find_league_dir(root, dirname)
        if league_dir is None:
            print(f"  [跳过] 未找到联赛目录: {dirname}")
            continue

        league_name = get_leagues().name_of(div)
        csvs = sorted(league_dir.glob("season-*.csv"))
        for csv in csvs:
            season_code = csv.stem.replace("season-", "")
            if seasons and season_code not in seasons:
                continue
            df = _read_season_csv(csv)
            if df.empty:
                continue
            df["league_code"] = div
            df["league_name"] = league_name
            df["season"] = season_code
            frames.append(df)

    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out = out.dropna(subset=["date", "home_team", "away_team", "ft_home", "ft_away"])
    out = out.sort_values(["league_code", "date"]).reset_index(drop=True)
    return out


def save_processed(df: pd.DataFrame, name: str = "tier1_matches") -> Path:
    settings = get_settings()
    settings.ensure_dirs()
    path = settings.processed_dir / f"{name}.parquet"
    df.to_parquet(path, index=False)
    return path


def load_processed(name: str = "tier1_matches") -> pd.DataFrame:
    """读取已落盘的 processed parquet（离线路径，避免重复解析镜像）。"""
    settings = get_settings()
    path = settings.processed_dir / f"{name}.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"processed 数据集不存在: {path}\n请先运行 python -m src.cli fetch-tier1 --online"
        )
    return pd.read_parquet(path)


if __name__ == "__main__":
    download_mirror(get_settings().raw_dir / "football-datasets")
    df = load_tier1()
    print(f"\n加载完成: {len(df)} 场")
    print(df.groupby("league_name").size().to_string())
