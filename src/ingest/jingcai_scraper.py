"""中国竞彩官网数据接入。

接口：webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry
    - 一次返回全部玩法赔率（HAD/HHAD/TTG/HAFU/CRS）
    - 含官方让球数（hhad.goalLine）、联赛排名、英文队名缩写
    - 需要 X-Requested-With 头，否则被 WAF 拦截（返回 567）

补充接口：getMatchListV1.qry?clientCode=3001
    - 返回未来 4 天全部开售场次，含 HAD/HHAD 赔率
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from src.config import get_settings

BASE = "https://webapi.sporttery.cn/gateway/uniform/football"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.sporttery.cn/",
    "Origin": "https://www.sporttery.cn",
    "X-Requested-With": "XMLHttpRequest",
}

# 竞彩比分玩法的高比分归并桶：s1sh/s1sd/s1sa 表示"主队进1+球且结果为胜/平/负"
CRS_SCORE_MAX = 5  # s00s00 .. s05s05 的最大单边进球

# 总进球桶：s0..s7，s7 表示 7+
TTG_BUCKETS = ["0", "1", "2", "3", "4", "5", "6", "7+"]


def _f(val: Any) -> float | None:
    """安全转 float，空串返回 None。"""
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


@dataclass
class JcMatch:
    """一場竞彩开售比赛。"""
    match_id: int
    match_num: str          # 周五001
    match_date: str         # 2026-10-16
    match_time: str         # 17:00:00
    league: str             # 澳超
    league_code: str        # AD1
    home_cn: str
    away_cn: str
    home_en: str
    away_en: str
    home_rank: str
    away_rank: str
    # 玩法赔率（原始 dict）
    had: dict = field(default_factory=dict)
    hhad: dict = field(default_factory=dict)
    ttg: dict = field(default_factory=dict)
    hafu: dict = field(default_factory=dict)
    crs: dict = field(default_factory=dict)
    fetched_at: str = ""
    # 期（销售日）信息：接口按 businessDate 分组，每组独立编号
    business_date: str = ""   # 期所属销售日，如 2026-10-21
    weekday: str = ""         # 周三
    match_num_date: str = ""  # 期号，如 261021
    match_week: str = ""      # 周三（接口 matchWeek）

    # ---- 派生属性 ----

    @property
    def hhad_goal_line(self) -> float | None:
        """竞彩官方让球数（如 -1 表示主队让 1 球，+1 表示受让 1 球）。"""
        return _f(self.hhad.get("goalLineValue")) or _f(self.hhad.get("goalLine"))

    def had_odds(self) -> dict[str, float]:
        """胜平负赔率 {'home':2.12, 'draw':3.47, 'away':2.71}"""
        return {
            "home": _f(self.had.get("h")) or 0.0,
            "draw": _f(self.had.get("d")) or 0.0,
            "away": _f(self.had.get("a")) or 0.0,
        }

    def hhad_odds(self) -> dict[str, float]:
        """让球胜平负赔率（已含官方让球）。"""
        return {
            "home": _f(self.hhad.get("h")) or 0.0,
            "draw": _f(self.hhad.get("d")) or 0.0,
            "away": _f(self.hhad.get("a")) or 0.0,
        }

    def ttg_odds(self) -> dict[str, float]:
        """总进球赔率，key 为 '0'..'7+'。"""
        out = {}
        for i, bucket in enumerate(TTG_BUCKETS):
            out[bucket] = _f(self.ttg.get(f"s{i}")) or 0.0
        return out

    def hafu_odds(self) -> dict[str, float]:
        """半全场赔率，key 形如 '胜/胜'。"""
        mapping = {
            "hh": "胜/胜", "hd": "胜/平", "ha": "胜/负",
            "dh": "平/胜", "dd": "平/平", "da": "平/负",
            "ah": "负/胜", "ad": "负/平", "aa": "负/负",
        }
        return {label: _f(self.hafu.get(code)) or 0.0
                for code, label in mapping.items()}

    def crs_odds(self) -> dict[str, float]:
        """比分赔率，key 形如 '1:1'，高比分归并到 '1+:胜' 等桶。"""
        out: dict[str, float] = {}
        for h in range(CRS_SCORE_MAX + 1):
            for a in range(CRS_SCORE_MAX + 1):
                v = _f(self.crs.get(f"s{h:02d}s{a:02d}"))
                if v:
                    out[f"{h}:{a}"] = v
        # 高比分归并桶
        for suffix, label in (("sh", "1+:胜"), ("sd", "1+:平"), ("sa", "1+:负")):
            v = _f(self.crs.get(f"s1s{suffix}"))
            if v:
                out[label] = v
        return out

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["had_odds"] = self.had_odds()
        d["hhad_odds"] = self.hhad_odds()
        d["hhad_goal_line"] = self.hhad_goal_line
        d["ttg_odds"] = self.ttg_odds()
        d["hafu_odds"] = self.hafu_odds()
        d["crs_odds"] = self.crs_odds()
        return d


def _get(url: str, params: dict | None = None, retries: int = 3) -> dict:
    """带重试与限速的 GET。"""
    settings = get_settings()
    interval = float(settings["jingcai"].get("request_interval", 3.0))
    timeout = int(settings["jingcai"].get("timeout", 15))

    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            time.sleep(interval)
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            if r.status_code == 567:
                raise RuntimeError("被 WAF 拦截(567)，需调整请求频率或头信息")
            r.raise_for_status()
            ct = r.headers.get("Content-Type", "")
            if "json" not in ct:
                raise RuntimeError(f"非 JSON 响应: {ct}")
            d = r.json()
            if not d.get("success"):
                raise RuntimeError(f"接口返回失败: {d.get('errorMessage')}")
            return d
        except Exception as e:  # noqa: BLE001
            last_exc = e
            wait = 2 ** attempt * 2
            print(f"  请求失败({e})，{wait}s 后重试 {attempt + 1}/{retries}")
            time.sleep(wait)
    raise RuntimeError(f"请求最终失败: {last_exc}")


def fetch_today(pool_codes: str = "had,hhad,crs,ttg,hafu") -> list[JcMatch]:
    """抓取当日（及未来数日）全部竞彩开售场次。"""
    url = f"{BASE}/getMatchCalculatorV1.qry"
    d = _get(url, {"poolCode": pool_codes, "clientCode": "3001"})

    now = datetime.now().isoformat(timespec="seconds")
    matches: list[JcMatch] = []
    for day in d.get("value", {}).get("matchInfoList", []):
        grp_business = day.get("businessDate", "")
        grp_weekday = day.get("weekday", "")
        grp_num_date = day.get("matchNumDate", "")
        for m in day.get("subMatchList", []):
            matches.append(JcMatch(
                match_id=int(m.get("matchId", 0)),
                match_num=m.get("matchNumStr", ""),
                match_date=m.get("matchDate", ""),
                match_time=m.get("matchTime", ""),
                league=m.get("leagueAbbName", ""),
                league_code=m.get("leagueCode", ""),
                home_cn=m.get("homeTeamAbbName", ""),
                away_cn=m.get("awayTeamAbbName", ""),
                home_en=m.get("homeTeamAbbEnName", ""),
                away_en=m.get("awayTeamAbbEnName", ""),
                home_rank=m.get("homeRank", ""),
                away_rank=m.get("awayRank", ""),
                had=m.get("had", {}) or {},
                hhad=m.get("hhad", {}) or {},
                ttg=m.get("ttg", {}) or {},
                hafu=m.get("hafu", {}) or {},
                crs=m.get("crs", {}) or {},
                fetched_at=now,
                business_date=m.get("businessDate") or grp_business,
                weekday=grp_weekday or m.get("matchWeek", ""),
                match_num_date=m.get("matchNumDate") or grp_num_date,
                match_week=m.get("matchWeek", ""),
            ))
    return matches


def save_matches(matches: list[JcMatch], name: str | None = None,
                 now: datetime | None = None,
                 odds_dir: Path | None = None) -> Path:
    """保存快照到 data/odds/，文件名带时间戳（jc_odds_YYYYMMDD_HHMM.json）。

    同一天多次抓取（早盘/临场）各存一份，互不覆盖，保留赔率走势。
    `now`/`odds_dir` 可注入（测试用），默认取当前时间与配置目录。
    """
    settings = get_settings()
    settings.ensure_dirs()
    ts = now or datetime.now()
    name = name or f"jc_odds_{ts.strftime('%Y%m%d_%H%M')}.json"
    path = Path(odds_dir or settings.odds_dir) / name
    payload = [m.to_dict() for m in matches]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_matches(path: str | Path) -> list[JcMatch]:
    """从快照 JSON 还原 JcMatch 列表（含全部玩法原始赔率）。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out: list[JcMatch] = []
    for d in data:
        out.append(JcMatch(
            match_id=int(d.get("match_id", 0)),
            match_num=d.get("match_num", ""),
            match_date=d.get("match_date", ""),
            match_time=d.get("match_time", ""),
            league=d.get("league", ""),
            league_code=d.get("league_code", ""),
            home_cn=d.get("home_cn", ""),
            away_cn=d.get("away_cn", ""),
            home_en=d.get("home_en", ""),
            away_en=d.get("away_en", ""),
            home_rank=d.get("home_rank", ""),
            away_rank=d.get("away_rank", ""),
            had=d.get("had", {}) or {},
            hhad=d.get("hhad", {}) or {},
            ttg=d.get("ttg", {}) or {},
            hafu=d.get("hafu", {}) or {},
            crs=d.get("crs", {}) or {},
            fetched_at=d.get("fetched_at", ""),
            business_date=d.get("business_date", ""),
            weekday=d.get("weekday", ""),
            match_num_date=d.get("match_num_date", ""),
            match_week=d.get("match_week", ""),
        ))
    return out


def _round_key(m: JcMatch) -> str:
    """一期的标识：优先 business_date；旧快照回退到编号前缀（周三/周四）。"""
    if m.business_date:
        return m.business_date
    prefix = (m.match_num or "")[:2]
    return f"prefix:{prefix}"


def _round_label(ms: list[JcMatch]) -> str:
    m = ms[0]
    weekday = m.weekday or (m.match_num[:2] if m.match_num else "")
    date = m.business_date or "未知日期"
    label = f"{weekday} {date}".strip() if weekday else date
    if m.match_num_date:
        label += f"（期号 {m.match_num_date}）"
    return label


def select_round(matches: list[JcMatch], mode: str = "first",
                 today: str | None = None) -> tuple[list[JcMatch], str]:
    """按「期」筛选比赛。

    mode:
        first : 最早的一期（默认）
        today : business_date 等于今天的一期；没有则回退 first
        all   : 全部
    返回 (筛选后的比赛, 期的可读描述)。
    """
    if not matches:
        return [], ""
    if mode == "all":
        return list(matches), "全部"

    groups: dict[str, list[JcMatch]] = {}
    order: list[str] = []
    for m in matches:
        key = _round_key(m)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(m)

    if mode == "today":
        day = today or datetime.now().strftime("%Y-%m-%d")
        if day in groups:
            return groups[day], _round_label(groups[day])
        # 没有今天这一期：回退到最早一期

    def sort_key(key: str) -> tuple:
        if key.startswith("prefix:"):
            return (1, order.index(key), key)
        return (0, key, key)

    first_key = min(order, key=sort_key)
    return groups[first_key], _round_label(groups[first_key])


def filter_matches(matches: list[JcMatch],
                   match_nums: list[str] | None = None,
                   teams: list[str] | None = None) -> list[JcMatch]:
    """按编号/队名过滤出指定场次。

    match_nums: 编号列表，如 ["周六005"]；也接受纯数字 "005"（后缀匹配）。
    teams: 队名关键字列表，中英文皆可，子串不区分大小写，命中主/客队任一即保留。
    两类条件之间是「与」关系，同类多个值之间是「或」关系。
    都为 None/空时返回原列表。
    """
    out = list(matches)
    if match_nums:
        wanted = [n.strip() for n in match_nums if n.strip()]

        def num_hit(m: JcMatch) -> bool:
            for n in wanted:
                if m.match_num == n:
                    return True
                # 纯数字后缀匹配："005" 命中 "周六005"
                if n.isdigit() and m.match_num.endswith(n):
                    return True
            return False

        out = [m for m in out if num_hit(m)]
    if teams:
        keys = [t.strip().lower() for t in teams if t.strip()]

        def team_hit(m: JcMatch) -> bool:
            fields = (m.home_cn, m.away_cn, m.home_en, m.away_en)
            return any(k in f.lower() for k in keys for f in fields if f)

        out = [m for m in out if team_hit(m)]
    return out


def snapshot_key(path: Path) -> tuple[str, str]:
    """从文件名解析 (日期, 时间)，用于排序。

    支持两种命名：
        jc_odds_20261024_1300.json -> ("20261024", "1300")
        jc_odds_20261023.json      -> ("20261023", "0000")  # 旧式无时间戳
    解析失败的排最前。
    """
    m = re.match(r"jc_odds_(\d{8})(?:_(\d{4}))?", Path(path).name)
    if not m:
        return ("", "")
    return (m.group(1), m.group(2) or "0000")


def latest_snapshot(odds_dir: Path | None = None) -> Path | None:
    """返回 data/odds 下最新的 jc_odds_*.json（按日期+时间戳排序），没有则 None。

    旧式无时间戳快照视作当天 00:00，同日新快照（带时间戳）优先。
    """
    settings = get_settings()
    odds_dir = odds_dir or settings.odds_dir
    if not Path(odds_dir).exists():
        return None
    files = [f for f in Path(odds_dir).glob("jc_odds_*.json")
             if snapshot_key(f)[0]]
    if not files:
        return None
    return max(files, key=snapshot_key)


def to_dataframe(matches: list[JcMatch]) -> pd.DataFrame:
    """展开为扁平 DataFrame，便于分析。"""
    rows = []
    for m in matches:
        had = m.had_odds()
        hhad = m.hhad_odds()
        row = {
            "match_id": m.match_id,
            "match_num": m.match_num,
            "match_date": m.match_date,
            "match_time": m.match_time,
            "league": m.league,
            "league_code": m.league_code,
            "home_cn": m.home_cn,
            "away_cn": m.away_cn,
            "home_en": m.home_en,
            "away_en": m.away_en,
            "home_rank": m.home_rank,
            "away_rank": m.away_rank,
            "hhad_goal_line": m.hhad_goal_line,
            "had_home": had["home"],
            "had_draw": had["draw"],
            "had_away": had["away"],
            "hhad_home": hhad["home"],
            "hhad_draw": hhad["draw"],
            "hhad_away": hhad["away"],
        }
        rows.append(row)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    ms = fetch_today()
    print(f"抓取到 {len(ms)} 场")
    df = to_dataframe(ms)
    print(df.groupby("league").size().to_string())
    print()
    print(df.head(10).to_string(index=False))
    p = save_matches(ms)
    print(f"\n已保存快照: {p}")
