"""竞彩官方赛果抓取与 CSV 合并。

数据源（中国体育彩票竞彩网，未公开文档的公开 Web API）：

    https://webapi.sporttery.cn/gateway/uniform/football/getUniformMatchResultV1.qry

返回字段里：
    matchNumStr     竞彩编号，如 周日019
    matchDate       比赛日期
    leagueNameAbbr  联赛简称
    homeTeam        主队简称
    awayTeam        客队简称
    sectionsNo1     半场比分，如 0:0
    sectionsNo999   全场比分，如 3:2
    winFlag         H / D / A

本模块只做读取、解析和 CSV 合并；不训练模型，也不改预测报告。
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests

from src.config import get_settings

BASE = "https://webapi.sporttery.cn/gateway/uniform/football"
RESULT_URL = f"{BASE}/getUniformMatchResultV1.qry"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.sporttery.cn/jc/zqsgkj/",
    "Origin": "https://www.sporttery.cn",
    "X-Requested-With": "XMLHttpRequest",
}

RESULT_COLUMNS = [
    "date", "match_num", "league", "home_cn", "away_cn",
    "ft_home", "ft_away", "ht_home", "ht_away",
]
SCORE_COLUMNS = ["ft_home", "ft_away", "ht_home", "ht_away"]
_SCORE_RE = re.compile(r"^\s*(\d+)\s*:\s*(\d+)\s*$")


# --------------------------------------------------------------------------- #
# 日期 / 比分解析
# --------------------------------------------------------------------------- #
def normalize_date(value: Any) -> str:
    """把 20261025 / 2026-10-25 / 2026/10/25 统一成 YYYY-MM-DD。"""
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"无法识别日期: {value!r}（请用 YYYY-MM-DD 或 YYYYMMDD）")


def parse_score(value: Any) -> tuple[int, int] | None:
    """解析 '2:1'；空串、'-'、'延期' 返回 None。"""
    if value is None:
        return None
    m = _SCORE_RE.match(str(value))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def date_range(start: str, end: str | None = None) -> list[str]:
    start_d = datetime.strptime(normalize_date(start), "%Y-%m-%d")
    end_d = datetime.strptime(normalize_date(end or start), "%Y-%m-%d")
    if end_d < start_d:
        raise ValueError("结束日期不能早于开始日期")
    out = []
    cur = start_d
    while cur <= end_d:
        out.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return out


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclass
class JcResult:
    match_id: int | None
    match_num: str
    match_date: str
    league: str
    home_cn: str
    away_cn: str
    ft_home: int
    ft_away: int
    ht_home: int | None
    ht_away: int | None
    win_flag: str = ""
    raw: dict[str, Any] | None = None

    @property
    def key(self) -> tuple[str, str]:
        return self.match_date, self.match_num

    @property
    def ft(self) -> str:
        return f"{self.ft_home}:{self.ft_away}"

    @property
    def ht(self) -> str:
        if self.ht_home is None or self.ht_away is None:
            return ""
        return f"{self.ht_home}:{self.ht_away}"

    def to_row(self) -> dict[str, Any]:
        return {
            "date": self.match_date,
            "match_num": self.match_num,
            "league": self.league,
            "home_cn": self.home_cn,
            "away_cn": self.away_cn,
            "ft_home": self.ft_home,
            "ft_away": self.ft_away,
            "ht_home": self.ht_home,
            "ht_away": self.ht_away,
        }


def parse_match(row: dict[str, Any]) -> JcResult | None:
    """把接口的一行转成 JcResult；未开赛/无全场比分返回 None。"""
    ft = parse_score(row.get("sectionsNo999"))
    if ft is None:
        return None
    ht = parse_score(row.get("sectionsNo1"))
    match_num = str(row.get("matchNumStr") or row.get("matchNum") or "").strip()
    match_date_raw = row.get("matchDate")
    if not match_num or not match_date_raw:
        return None
    try:
        match_date = normalize_date(match_date_raw)
    except ValueError:
        return None
    match_id = row.get("matchId")
    try:
        match_id = int(match_id) if match_id is not None else None
    except (TypeError, ValueError):
        match_id = None
    return JcResult(
        match_id=match_id,
        match_num=match_num,
        match_date=match_date,
        league=str(row.get("leagueNameAbbr") or row.get("leagueName") or "").strip(),
        home_cn=str(row.get("homeTeam") or row.get("allHomeTeam") or "").strip(),
        away_cn=str(row.get("awayTeam") or row.get("allAwayTeam") or "").strip(),
        ft_home=ft[0],
        ft_away=ft[1],
        ht_home=ht[0] if ht else None,
        ht_away=ht[1] if ht else None,
        win_flag=str(row.get("winFlag") or "").strip(),
        raw=row,
    )


# --------------------------------------------------------------------------- #
# 接口请求
# --------------------------------------------------------------------------- #
def _request_page(start_date: str, end_date: str, page_no: int,
                  page_size: int = 100, delay: float | None = None,
                  session: requests.Session | None = None,
                  retries: int = 3) -> dict[str, Any]:
    settings = get_settings()
    interval = (float(delay) if delay is not None
                else float(settings["jingcai"].get("request_interval", 3.0)))
    timeout = int(settings["jingcai"].get("timeout", 15))
    sess = session or requests.Session()
    params = {
        "matchBeginDate": normalize_date(start_date),
        "matchEndDate": normalize_date(end_date),
        "leagueId": "",
        "pageSize": str(page_size),
        "pageNo": str(page_no),
        "isFix": "0",
        "matchPage": "1",
        "pcOrWap": "1",
    }
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            time.sleep(interval)
            r = sess.get(RESULT_URL, params=params, headers=HEADERS,
                         timeout=timeout)
            if r.status_code in (403, 567):
                raise RuntimeError(f"被竞彩 WAF 拦截({r.status_code})")
            r.raise_for_status()
            data = r.json()
            if not data.get("success"):
                raise RuntimeError(f"接口返回失败: {data.get('errorMessage')}")
            return data
        except Exception as e:  # noqa: BLE001
            last_exc = e
            wait = 2 ** attempt * 2
            print(f"  赛果请求失败({e})，{wait}s 后重试 {attempt + 1}/{retries}")
            time.sleep(wait)
    raise RuntimeError(f"赛果请求最终失败: {last_exc}")


def fetch_results(start_date: str, end_date: str | None = None,
                  page_size: int = 100, delay: float | None = None,
                  session: requests.Session | None = None
                  ) -> tuple[list[JcResult], list[dict[str, Any]]]:
    """抓取日期区间内的赛果，返回 (解析后的赛果, 原始分页响应)。"""
    start = normalize_date(start_date)
    end = normalize_date(end_date or start_date)
    sess = session or requests.Session()
    results: list[JcResult] = []
    payloads: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    page_no = 1
    pages = 1
    while page_no <= pages:
        data = _request_page(start, end, page_no, page_size=page_size,
                             delay=delay, session=sess)
        payloads.append({"page_no": page_no, "response": data})
        value = data.get("value") or {}
        rows = value.get("matchResult") or []
        try:
            pages = int(value.get("pages") or 0)
        except (TypeError, ValueError):
            pages = 0
        for row in rows:
            parsed = parse_match(row)
            if parsed is None:
                continue
            if parsed.key in seen:
                continue
            seen.add(parsed.key)
            results.append(parsed)
        if not rows or page_no >= pages:
            break
        page_no += 1
    return results, payloads


def save_raw(payloads: list[dict[str, Any]], start_date: str, end_date: str,
             out_dir: str | Path) -> Path:
    """把原始响应存到 data/raw（默认被 gitignore），便于排查。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    start = normalize_date(start_date)
    end = normalize_date(end_date or start_date)
    tag = start.replace("-", "") if start == end else f"{start.replace('-', '')}_{end.replace('-', '')}"
    path = out / f"jc_results_{tag}.json"
    path.write_text(json.dumps({
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "start_date": start,
        "end_date": end,
        "pages": payloads,
    }, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# CSV 读写 / 合并
# --------------------------------------------------------------------------- #
def empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=RESULT_COLUMNS)


def load_results_csv(path: str | Path) -> pd.DataFrame:
    """读取现有赛果 CSV；文件不存在或为空时返回空表。"""
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return empty_frame()
    df = pd.read_csv(p, dtype=str, keep_default_na=False)
    df.columns = [str(c).strip().lstrip("\ufeff") for c in df.columns]
    for col in RESULT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[RESULT_COLUMNS].copy()
    df["date"] = df["date"].map(lambda v: _safe_date(v))
    df["match_num"] = df["match_num"].astype(str).str.strip()
    for col in SCORE_COLUMNS:
        df[col] = df[col].map(lambda v: str(v).strip() if str(v).strip() else "")
    return df


def _safe_date(value: Any) -> str:
    try:
        return normalize_date(value)
    except ValueError:
        return str(value or "").strip()


def _score_int(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _filled_value(value: Any) -> bool:
    return _score_int(value) is not None


def _filled_pair(home: Any, away: Any) -> bool:
    return _filled_value(home) and _filled_value(away)


def _same_value(a: Any, b: Any) -> bool:
    ia, ib = _score_int(a), _score_int(b)
    if ia is not None and ib is not None:
        return ia == ib
    return str(a or "").strip() == str(b or "").strip()


def _same_score(a: Any, b: Any) -> bool:
    return parse_score(a) == parse_score(b)


def merge_results(existing: pd.DataFrame, new_results: Iterable[JcResult],
                  overwrite: bool = False
                  ) -> tuple[pd.DataFrame, dict[str, int], list[dict[str, Any]]]:
    """把新赛果合并进现有表。

    默认策略：
        - 新场次：追加；
        - 旧场次没有全场比分：补全；
        - 旧场次已有比分且与新结果相同：不变；
        - 旧场次已有比分且与新结果不同：保留旧值，记录冲突；
        - overwrite=True 时用新结果覆盖。
    """
    rows = existing.to_dict(orient="records") if not existing.empty else []
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (_safe_date(row.get("date")), str(row.get("match_num") or "").strip())
        if key[1]:
            by_key[key] = dict(row)

    stats = {"added": 0, "filled": 0, "updated": 0,
             "unchanged": 0, "conflicts": 0}
    conflicts: list[dict[str, Any]] = []

    for result in new_results:
        key = result.key
        new_row = result.to_row()
        old = by_key.get(key)
        if old is None:
            by_key[key] = new_row
            stats["added"] += 1
            continue
        old_ft_h = old.get("ft_home")
        old_ft_a = old.get("ft_away")
        if not _filled_pair(old_ft_h, old_ft_a):
            by_key[key] = new_row
            stats["filled"] += 1
            continue

        if (_same_value(old_ft_h, new_row["ft_home"])
                and _same_value(old_ft_a, new_row["ft_away"])):
            # 全场比分一致：只补缺失的半场/联赛/队名，不覆盖已有值。
            changed = False
            for col in ("ht_home", "ht_away"):
                if not _filled_value(old.get(col)) and _filled_value(new_row[col]):
                    old[col] = new_row[col]
                    changed = True
            for col in ("league", "home_cn", "away_cn"):
                if not str(old.get(col) or "").strip() and str(new_row.get(col) or "").strip():
                    old[col] = new_row[col]
                    changed = True
            if changed:
                by_key[key] = old
                stats["filled"] += 1
            else:
                stats["unchanged"] += 1
            continue

        if overwrite:
            by_key[key] = new_row
            stats["updated"] += 1
        else:
            stats["conflicts"] += 1
            conflicts.append({
                "date": key[0],
                "match_num": key[1],
                "manual": f"{old.get('ft_home')}:{old.get('ft_away')} "
                          f"(半场 {old.get('ht_home')}:{old.get('ht_away')})",
                "api": f"{result.ft} (半场 {result.ht or '—'})",
            })

    out = pd.DataFrame(list(by_key.values()), columns=RESULT_COLUMNS)
    if out.empty:
        return empty_frame(), stats, conflicts
    out["date"] = out["date"].map(_safe_date)
    out["match_num"] = out["match_num"].astype(str).str.strip()
    for col in SCORE_COLUMNS:
        out[col] = pd.to_numeric(out[col], errors="coerce").astype("Int64")
    out = out.sort_values(["date", "match_num"], kind="stable").reset_index(drop=True)
    return out, stats, conflicts


def write_results_csv(df: pd.DataFrame, path: str | Path) -> Path:
    """原子写入 CSV（UTF-8，无 BOM，空比分写成空字段）。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    out = df.copy()
    for col in RESULT_COLUMNS:
        if col not in out.columns:
            out[col] = pd.NA
    out = out[RESULT_COLUMNS]
    out.to_csv(tmp, index=False, encoding="utf-8")
    tmp.replace(p)
    return p


# --------------------------------------------------------------------------- #
# 日期辅助
# --------------------------------------------------------------------------- #
def prediction_dates(reports_dir: str | Path) -> list[str]:
    """从 reports/predict_*.json 提取所有可对账日期（YYYY-MM-DD）。"""
    out: set[str] = set()
    for path in Path(reports_dir).glob("predict_*.json"):
        match = re.search(r"predict_(\d{8})", path.stem)
        if match:
            try:
                out.add(normalize_date(match.group(1)))
            except ValueError:
                continue
    return sorted(out)


def latest_prediction_date(reports_dir: str | Path) -> str | None:
    dates = prediction_dates(reports_dir)
    return dates[-1] if dates else None
