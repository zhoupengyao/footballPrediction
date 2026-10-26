"""快照时间戳与单场过滤测试（离线）。

覆盖：
    1. save_matches 带时间戳命名，同日多次抓取互不覆盖
    2. latest_snapshot 按日期+时间取最新；旧式无时间戳文件兼容（视作当天 00:00）
    3. filter_matches 按编号（全码/纯数字后缀）与队名（中英文子串）过滤
"""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src.ingest.jingcai_scraper import (JcMatch, filter_matches, latest_snapshot,
                                        save_matches, snapshot_key)


def _mk(num: str, home_cn: str, away_cn: str,
        home_en: str = "", away_en: str = "") -> JcMatch:
    return JcMatch(
        match_id=1, match_num=num, match_date="2026-10-24",
        match_time="19:30:00", league="欧罗巴", league_code="UEL",
        home_cn=home_cn, away_cn=away_cn, home_en=home_en, away_en=away_en,
        home_rank="", away_rank="",
    )


def test_snapshot_key() -> None:
    assert snapshot_key(Path("jc_odds_20261024_1300.json")) == ("20261024", "1300")
    # 旧式无时间戳视作 0000
    assert snapshot_key(Path("jc_odds_20261023.json")) == ("20261023", "0000")
    # 无法解析
    assert snapshot_key(Path("other.json")) == ("", "")
    print("  ✓ snapshot_key（时间戳/旧式/无法解析）")


def test_save_and_latest(tmp: Path) -> None:
    ms = [_mk("周六005", "波尔图", "皇家马德里")]
    # 同日两次抓取：早盘 + 临场，各存一份
    p_morning = save_matches(ms, now=datetime(2026, 10, 24, 13, 0), odds_dir=tmp)
    p_live = save_matches(ms, now=datetime(2026, 10, 24, 17, 30), odds_dir=tmp)
    assert p_morning.name == "jc_odds_20261024_1300.json"
    assert p_live.name == "jc_odds_20261024_1730.json"
    assert p_morning.exists() and p_live.exists(), "同日两份快照应并存"

    # 旧式无时间戳快照（前一天）
    old = tmp / "jc_odds_20261023.json"
    old.write_text("[]", encoding="utf-8")

    # 最新 = 今天 17:30 那份
    assert latest_snapshot(tmp) == p_live
    # 删掉临场份 → 回落到早盘份
    p_live.unlink()
    assert latest_snapshot(tmp) == p_morning
    # 再删 → 回落到旧式文件
    p_morning.unlink()
    assert latest_snapshot(tmp) == old
    # 空目录
    with tempfile.TemporaryDirectory() as d:
        assert latest_snapshot(Path(d)) is None
    print("  ✓ 保存时间戳命名 + latest_snapshot 取最新/回落")


def test_filter_matches() -> None:
    ms = [
        _mk("周六005", "波尔图", "皇家马德里", "Porto", "Real Madrid"),
        _mk("周六006", "利物浦", "AC米兰", "Liverpool", "AC Milan"),
        _mk("周日001", "拜仁", "多特蒙德", "Bayern", "Dortmund"),
    ]
    # 全码精确
    assert [m.match_num for m in filter_matches(ms, match_nums=["周六005"])] == ["周六005"]
    # 纯数字后缀
    assert [m.match_num for m in filter_matches(ms, match_nums=["006"])] == ["周六006"]
    # 多编号「或」
    assert len(filter_matches(ms, match_nums=["周六005", "周日001"])) == 2
    # 中文队名子串
    assert [m.match_num for m in filter_matches(ms, teams=["马德里"])] == ["周六005"]
    # 英文队名不区分大小写
    assert [m.match_num for m in filter_matches(ms, teams=["LIVERPOOL"])] == ["周六006"]
    # 命中主/客任一
    assert [m.match_num for m in filter_matches(ms, teams=["多特"])] == ["周日001"]
    # 编号与队名「与」
    assert filter_matches(ms, match_nums=["周六005"], teams=["利物浦"]) == []
    # 无过滤原样返回
    assert len(filter_matches(ms)) == len(ms)
    # 无命中
    assert filter_matches(ms, match_nums=["周六999"], teams=["不存在队"]) == []
    print("  ✓ filter_matches（编号全码/后缀/多值 + 队名中英文 + 与关系）")


def main() -> None:
    test_snapshot_key()
    with tempfile.TemporaryDirectory() as d:
        test_save_and_latest(Path(d))
    test_filter_matches()
    print("\n全部通过 ✓")


if __name__ == "__main__":
    main()
