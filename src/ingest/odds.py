"""历史赔率接入（football-data.co.uk 格式）。

背景与困境
----------
* 本机直连 ``www.football-data.co.uk`` 被拒（ConnectionError）。
* ``datasets/football-datasets`` 镜像**删掉了赔率列**（只有比分/统计）。
* 于是回测无法算 ROI。

解决路径
--------
GitHub 上的原始 dump 镜像仍含完整赔率列：
    repo  : jokecamp/FootballData
    path  : football-data.co.uk/{country}/{season}/{League}.csv
    列    : Div, Date, HomeTeam, AwayTeam, FTHG, FTAG, B365H/D/A, PSH/D/A, AvgH/D/A ...
    git 通  : api.github.com / codeload.github.com 可达（raw 被墙）
    范围  : 1993/94 – 2020/21

本模块把它规范化成 (league_code, date, home_team, away_team,
odds_home, odds_draw, odds_away)，并可按主键合并回比赛表用于 ROI。
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from src.config import get_settings

ODDS_REPO = "jokecamp/FootballData"
ODDS_SUBDIR = "football-data.co.uk"
TREE_URL = f"https://api.github.com/repos/{ODDS_REPO}/git/trees/master?recursive=1"
# 内容代理：raw.githubusercontent 被墙，但 ghproxy.net 可达（实测，无额度限制）
PROXY_TEMPLATES = (
    "https://ghproxy.net/https://raw.githubusercontent.com/{repo}/master/{path}",
    "https://raw.githubusercontent.com/{repo}/master/{path}",  # 直连（可能被墙，兜底）
)
# 我们关心的国家目录（其余跳过以加速）
TARGET_COUNTRIES = {"england", "germany", "spain", "italy", "france",
                    "netherlands", "belgium", "portulgal", "turkey",
                    "greece", "scotland"}
# 我们关心的 div 代码
TARGET_DIVS = {"E0", "D1", "SP1", "I1", "F1"}
# 赔率优先级：博彩公司 -> 平均
ODDS_PRIORITY = [
    ("B365H", "B365D", "B365A"),
    ("PSH", "PSD", "PSA"),
    ("AvgH", "AvgD", "AvgA"),
    ("BbAvH", "BbAvD", "BbAvA"),
]


def _http() -> requests.Session:
    s = requests.Session()
    s.headers["Accept"] = "application/vnd.github.v3+json"
    s.headers["User-Agent"] = "jingcai-predict/0.1"
    return s


# div -> 仓库内文件路径正则（football-data.co.uk/{国家} 下）
# 覆盖五大联赛及其二、三级联赛 + 荷/比/葡/土/希/苏（用于扩联赛覆盖）。
DIV_PATH_PATTERNS = {
    # 英格兰（有赛季子目录）
    "E0": r"^football-data\.co\.uk/england/([^/]+/)?Premier\.csv$",
    "E1": r"^football-data\.co\.uk/england/([^/]+/)?Championship\.csv$",
    "E2": r"^football-data\.co\.uk/england/([^/]+/)?League\s?1\.csv$",
    "E3": r"^football-data\.co\.uk/england/([^/]+/)?League\s?2\.csv$",
    # 德国
    "D1": r"^football-data\.co\.uk/germany/D1.*\.csv$",
    "D2": r"^football-data\.co\.uk/germany/D2.*\.csv$",
    # 西班牙
    "SP1": r"^football-data\.co\.uk/spain/SP1.*\.csv$",
    "SP2": r"^football-data\.co\.uk/spain/SP2.*\.csv$",
    # 意大利
    "I1": r"^football-data\.co\.uk/italy/I1.*\.csv$",
    "I2": r"^football-data\.co\.uk/italy/I2.*\.csv$",
    # 法国
    "F1": r"^football-data\.co\.uk/france/F1.*\.csv$",
    "F2": r"^football-data\.co\.uk/france/F2.*\.csv$",
    # 荷兰 / 比利时 / 葡萄牙(仓库目录拼作 portulgal) / 土耳其 / 希腊
    "N1": r"^football-data\.co\.uk/netherlands/N1.*\.csv$",
    "B1": r"^football-data\.co\.uk/belgium/B1.*\.csv$",
    "P1": r"^football-data\.co\.uk/portulgal/P1.*\.csv$",
    "T1": r"^football-data\.co\.uk/turkey/T1.*\.csv$",
    "G1": r"^football-data\.co\.uk/greece/G1.*\.csv$",
    # 苏格兰
    "SC0": r"^football-data\.co\.uk/scotland/SC0.*\.csv$",
    "SC1": r"^football-data\.co\.uk/scotland/SC1.*\.csv$",
    "SC2": r"^football-data\.co\.uk/scotland/SC2.*\.csv$",
    "SC3": r"^football-data\.co\.uk/scotland/SC3.*\.csv$",
}


def _rate_limit_remaining() -> int:
    try:
        d = _http().get("https://api.github.com/rate_limit", timeout=20).json()
        return int(d["resources"]["core"]["remaining"])
    except Exception:  # noqa: BLE001
        return 0


def fetch_odds_via_api(dest: Path | None = None,
                       divs: list[str] | None = None,
                       max_files: int | None = None) -> tuple[Path, int]:
    """按需从 GitHub API 拉取需要的赔率 CSV（受速率限制约束）。

    适合整包 zip 太慢时的替补：只取目标联赛文件。未认证额度约 60 次/小时，
    函数会按剩余额度自动截断，返回 (解压目录, 实际下载文件数)。
    """
    import base64
    import re

    settings = get_settings()
    dest = dest or (settings.raw_dir / "odds-dump")
    dest.mkdir(parents=True, exist_ok=True)

    want = divs or list(DIV_PATH_PATTERNS)
    session = _http()
    tree = session.get(
        f"https://api.github.com/repos/{ODDS_REPO}/git/trees/master?recursive=1",
        timeout=60).json().get("tree", [])
    pats = [re.compile(DIV_PATH_PATTERNS[d]) for d in want if d in DIV_PATH_PATTERNS]
    targets = [t for t in tree
               if t.get("type") == "blob"
               and any(p.match(t["path"]) for p in pats)]
    # 跳过已下载（支持增量补齐）
    targets = [t for t in targets if not (dest / t["path"]).exists()]

    budget = _rate_limit_remaining() - 2
    if max_files is not None:
        budget = min(budget, max_files)
    if budget <= 0:
        print("GitHub 速率额度不足，请稍后再试（未认证约 60 次/小时）。", flush=True)
        return dest, 0

    todo = targets[:budget]
    print(f"待下载 {len(targets)} 个文件，本次额度 {budget}，实际下载 {len(todo)}",
          flush=True)
    ok = 0
    for t in todo:
        try:
            b = session.get(t["url"], timeout=60).json()
            data = base64.b64decode(b["content"])
            p = dest / t["path"]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            ok += 1
            if ok % 10 == 0:
                print(f"  ...{ok}/{len(todo)}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"  [失败] {t['path']}: {type(e).__name__}", flush=True)
    print(f"API 方式下载完成：{ok}/{len(targets)} 个文件", flush=True)
    return dest, ok


def _select_targets(tree: list[dict], divs: list[str] | None) -> list[dict]:
    import re
    want = divs or list(DIV_PATH_PATTERNS)
    pats = [re.compile(DIV_PATH_PATTERNS[d]) for d in want if d in DIV_PATH_PATTERNS]
    return [t for t in tree
            if t.get("type") == "blob"
            and any(p.match(t["path"]) for p in pats)]


def fetch_odds_via_proxy(dest: Path | None = None,
                         divs: list[str] | None = None) -> tuple[Path, int]:
    """经内容代理（ghproxy.net）按需下载赔率 CSV。

    比 zip 稳、比 api 快（无 60 次/小时额度限制）：curl raw 文件即可。
    只取目标联赛文件，跳过已存在的（可增量）。
    """
    settings = get_settings()
    dest = dest or (settings.raw_dir / "odds-dump")
    dest.mkdir(parents=True, exist_ok=True)

    session = _http()
    tree = session.get(TREE_URL, timeout=60).json().get("tree", [])
    targets = _select_targets(tree, divs)
    print(f"目标文件 {len(targets)} 个，开始经代理下载...", flush=True)

    ok = skipped = 0
    for t in targets:
        path = t["path"]
        out = dest / path
        if out.exists():
            skipped += 1
            continue
        enc = path.replace(" ", "%20")
        data = None
        for tpl in PROXY_TEMPLATES:
            try:
                r = session.get(tpl.format(repo=ODDS_REPO, path=enc), timeout=60,
                                headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code == 200 and len(r.content) > 100:
                    data = r.content
                    break
            except Exception:  # noqa: BLE001
                continue
        if data is None:
            print(f"  [失败] {path}", flush=True)
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        ok += 1
        if ok % 10 == 0:
            print(f"  ...已下载 {ok} 个", flush=True)

    print(f"代理方式完成：新下载 {ok}，跳过已存在 {skipped}，共 {len(targets)}", flush=True)
    return dest, ok


def download_odds_dump(dest: Path | None = None, force: bool = False) -> Path:
    """一次性下载赔率镜像（codeload zipball）并解压到 data/raw/odds-dump/。

    注意：`raw.githubusercontent.com` 被墙，但 `codeload.github.com` 可达；
    仓库约 38MB+，下载较慢，故流式写盘并打印进度。
    """
    settings = get_settings()
    dest = dest or (settings.raw_dir / "odds-dump")
    marker = dest / ".download_complete"
    if marker.exists() and not force:
        print(f"赔率镜像已存在，跳过下载: {dest}")
        return dest

    settings.ensure_dirs()
    dest.mkdir(parents=True, exist_ok=True)
    zip_path = dest / "_dump.zip"

    ok = False
    for branch in ("master", "main"):
        url = f"https://codeload.github.com/{ODDS_REPO}/zip/refs/heads/{branch}"
        print(f"正在下载赔率镜像 {ODDS_REPO}（codeload，较慢）...", flush=True)
        try:
            resp = _http().get(url, timeout=60, stream=True)
            if resp.status_code != 200:
                print(f"  [{branch}] status={resp.status_code}", flush=True)
                continue
            done = 0
            milestone = 5 << 20
            with open(zip_path, "wb") as f:
                for chunk in resp.iter_content(1 << 16):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    if done >= milestone:
                        print(f"  ...已下载 {done / 1048576:.1f} MB", flush=True)
                        milestone += 5 << 20
            ok = True
            break
        except Exception as e:  # noqa: BLE001
            print(f"  [{branch}] 失败 {type(e).__name__}: {str(e)[:80]}", flush=True)

    if not ok:
        raise RuntimeError("下载赔率 dump 失败，请检查网络")

    print(f"下载完成 {zip_path.stat().st_size / 1048576:.1f} MB，解压中...", flush=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
    zip_path.unlink(missing_ok=True)
    marker.write_text("ok", encoding="utf-8")
    print(f"解压完成: {dest}", flush=True)
    return dest


def _read_csv(path: Path) -> pd.DataFrame:
    for enc in ("utf-8", "latin-1"):
        try:
            return pd.read_csv(path, encoding=enc, on_bad_lines="skip",
                               low_memory=False)
        except Exception:  # noqa: BLE001
            continue
    return pd.DataFrame()


def _pick_odds(df: pd.DataFrame) -> tuple[str, str, str] | None:
    for cols in ODDS_PRIORITY:
        if all(c in df.columns for c in cols):
            return cols
    return None


def load_odds(dump_root: Path | None = None,
              divs: list[str] | None = None) -> pd.DataFrame:
    """解析赔率 dump，返回规范化的赔率表。

    列：league_code, date, home_team, away_team, odds_home, odds_draw, odds_away, odds_source
    """
    settings = get_settings()
    dump_root = dump_root or (settings.raw_dir / "odds-dump")
    # 可能同时存在多个 football-data.co.uk 目录（手动按需取的 + 整包解压的），全部合并
    subdirs = [p for p in dump_root.rglob(ODDS_SUBDIR) if p.is_dir()]
    if not subdirs:
        raise FileNotFoundError(
            f"未找到 {ODDS_SUBDIR} 目录于 {dump_root}\n请先运行 python -m src.cli fetch-odds --online"
        )

    want = set(divs) if divs else TARGET_DIVS
    frames: list[pd.DataFrame] = []
    seen: set[str] = set()
    for subdir in subdirs:
        for country_dir in sorted(p for p in subdir.iterdir() if p.is_dir()):
            if country_dir.name.lower() not in TARGET_COUNTRIES:
                continue
            for csv in country_dir.rglob("*.csv"):
                key = str(csv.resolve())
                if key in seen:
                    continue
                seen.add(key)
                df = _read_csv(csv)
                if df.empty or "Div" not in df.columns:
                    continue
                df = df[df["Div"].isin(want)]
                if df.empty:
                    continue
                pick = _pick_odds(df)
                if pick is None:
                    continue
                out = pd.DataFrame({
                    "league_code": df["Div"],
                    "date": pd.to_datetime(df["Date"], dayfirst=True,
                                           format="mixed", errors="coerce"),
                    "home_team": df["HomeTeam"],
                    "away_team": df["AwayTeam"],
                    "odds_home": pd.to_numeric(df[pick[0]], errors="coerce"),
                    "odds_draw": pd.to_numeric(df[pick[1]], errors="coerce"),
                    "odds_away": pd.to_numeric(df[pick[2]], errors="coerce"),
                    "odds_source": pick[0][:-1] or pick[0],
                })
                frames.append(out)

    if not frames:
        return pd.DataFrame(columns=["league_code", "date", "home_team", "away_team",
                                     "odds_home", "odds_draw", "odds_away", "odds_source"])

    odds = pd.concat(frames, ignore_index=True)
    odds = odds.dropna(subset=["date", "home_team", "away_team",
                               "odds_home", "odds_draw", "odds_away"])
    odds = odds.drop_duplicates(subset=["league_code", "date", "home_team", "away_team"])
    return odds.sort_values(["league_code", "date"]).reset_index(drop=True)


# 队伍名个别不一致时的修补（本项目历史数据名 -> 赔率 dump 名）
TEAM_ALIASES = {
    "Man City": "Man City",
    "Man United": "Man United",
}


def merge_odds(matches: pd.DataFrame, odds: pd.DataFrame) -> pd.DataFrame:
    """按 (league_code, date, home_team, away_team) 合并赔率到比赛表。"""
    if odds.empty:
        return matches
    m = matches.copy()
    m["date"] = pd.to_datetime(m["date"]).dt.normalize()
    o = odds.copy()
    o["date"] = pd.to_datetime(o["date"]).dt.normalize()
    merged = m.merge(o, on=["league_code", "date", "home_team", "away_team"],
                     how="left")
    return merged


def odds_coverage(matches: pd.DataFrame) -> dict[str, Any]:
    """统计比赛表中带赔率的比例。"""
    total = len(matches)
    have = int(matches["odds_home"].notna().sum()) if "odds_home" in matches.columns else 0
    return {"total": total, "with_odds": have,
            "coverage": (have / total) if total else 0.0}


def save_odds(odds: pd.DataFrame, name: str = "historical_odds") -> Path:
    settings = get_settings()
    settings.ensure_dirs()
    path = settings.processed_dir / f"{name}.parquet"
    odds.to_parquet(path, index=False)
    return path


def load_odds_processed(name: str = "historical_odds") -> pd.DataFrame:
    settings = get_settings()
    path = settings.processed_dir / f"{name}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"赔率数据集不存在: {path}")
    return pd.read_parquet(path)


# --------------------------------------------------------------------------- #
# 比分解析（用于扩联赛覆盖）
# --------------------------------------------------------------------------- #
# 比分表用的列重命名（与 src/ingest/footballdata.py 的 RENAME_MAP 对齐）
_SCORE_RENAME = {
    "Div": "league_code",
    "Date": "date",
    "HomeTeam": "home_team",
    "AwayTeam": "away_team",
    "FTHG": "ft_home",
    "FTAG": "ft_away",
    "HTHG": "ht_home",
    "HTAG": "ht_away",
}


def load_matches_from_dump(dump_root: Path | None = None,
                           divs: list[str] | None = None) -> pd.DataFrame:
    """从赔率 dump（jokecamp/FootballData）解析**比分**，返回比赛表。

    jokecamp 镜像同时含比分与赔率，但本项目的 tier1 主数据源（datasets 镜像）
    只覆盖 5 大联赛。此函数把 dump 里更多国家的比分抽出来，用于扩大联赛覆盖。

    注意：dump 里同一联赛常有多个重叠的重复文件（如 ``F1 (1).csv``），
    解析后按 (league_code, date, home_team, away_team) 去重。

    返回列：league_code, date, home_team, away_team, ft_home, ft_away,
           ht_home(若有), ht_away(若有)
    """
    settings = get_settings()
    dump_root = dump_root or (settings.raw_dir / "odds-dump")
    subdirs = [p for p in dump_root.rglob(ODDS_SUBDIR) if p.is_dir()]
    if not subdirs:
        raise FileNotFoundError(
            f"未找到 {ODDS_SUBDIR} 目录于 {dump_root}\n请先运行 "
            f"python -m src.cli fetch-tier1-gh --online")

    want = set(divs) if divs else None
    frames: list[pd.DataFrame] = []
    seen: set[str] = set()
    for subdir in subdirs:
        for csv in subdir.rglob("*.csv"):
            key = str(csv.resolve())
            if key in seen:
                continue
            seen.add(key)
            df = _read_csv(csv)
            if df.empty or "Div" not in df.columns:
                continue
            need = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"]
            if not all(c in df.columns for c in need):
                continue
            cols = ["Div", "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"]
            for c in ("HTHG", "HTAG"):
                if c in df.columns:
                    cols.append(c)
            sub = df[cols].copy()
            if want:
                sub = sub[sub["Div"].isin(want)]
            if sub.empty:
                continue
            frames.append(sub)

    if not frames:
        return pd.DataFrame(columns=["league_code", "date", "home_team",
                                     "away_team", "ft_home", "ft_away"])

    out = pd.concat(frames, ignore_index=True)
    out = out.rename(columns=_SCORE_RENAME)
    out["date"] = pd.to_datetime(out["date"], dayfirst=True, format="mixed",
                                 errors="coerce")
    for c in ("ft_home", "ft_away", "ht_home", "ht_away"):
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.dropna(subset=["date", "home_team", "away_team", "ft_home", "ft_away"])
    out = out.drop_duplicates(subset=["league_code", "date", "home_team", "away_team"])
    return out.sort_values(["league_code", "date"]).reset_index(drop=True)


def save_matches(df: pd.DataFrame, name: str = "tier1_gh_matches") -> Path:
    """把 dump 解析出的比赛表落盘（与主 tier1_matches 分开，避免覆盖）。"""
    settings = get_settings()
    settings.ensure_dirs()
    path = settings.processed_dir / f"{name}.parquet"
    df.to_parquet(path, index=False)
    return path
