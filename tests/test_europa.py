"""欧罗巴/欧协联接入与 EUR 合并模型测试（离线）。

覆盖：
    1. el.txt 解析：league_code=UEL、90 分钟比分规则
    2. 配置：欧罗巴/欧协联竞彩映射、EUR 模型组路由
    3. uel/conf 数据集完整性
    4. load_training_data 合并三项欧战
    5. EUR 训练（组成员合并、years=null 窗口）+ 预测路由
    6. EUR 缺席时回落到 UCL 自有模型
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src.config import get_leagues
from src.ingest.openfootball import (dataset_name, default_seasons,
                                     parse_season as of_parse)

SAMPLE = """= UEFA Europa League 2023/24

▪ Group, Matchday 1
  Thu Sep 21 2023
    18:45  Rangers FC (SCO)        v Servette FC (SUI)      1-0 (0-0)
    21:00  AC Milan (ITA)          v AS Roma (ITA)          2-3 (1-2)

▪ Knockout, Final
  Wed May 22
    21:00  Atalanta (ITA)          v Bayer Leverkusen (GER) 3-0 (2-0)
"""


def test_parse_el() -> None:
    rows = of_parse(SAMPLE, "2023-24", comp="UEL")
    assert len(rows) == 3, rows
    assert {r["league_code"] for r in rows} == {"UEL"}
    assert {r["league_name"] for r in rows} == {"欧罗巴"}
    assert (rows[0]["ft_home"], rows[0]["ft_away"]) == (1, 0)
    assert (rows[0]["ht_home"], rows[0]["ht_away"]) == (0, 0)
    # 半场比分与 90 分钟比分不同
    assert (rows[1]["ft_home"], rows[1]["ht_home"]) == (2, 1)
    # 队名归一化：Servette FC / Bayer Leverkusen
    assert rows[0]["away_team"] == "Servette"
    assert rows[2]["away_team"] == "Leverkusen"
    # 默认 comp=UCL 保持兼容
    assert of_parse(SAMPLE, "2023-24")[0]["league_code"] == "UCL"
    print("  ✓ el.txt 解析（league_code / 90 分钟 / 归一化）")


def test_config_routing() -> None:
    lg = get_leagues()
    assert lg.jc_name_to_div("欧罗巴") == "UEL"
    assert lg.jc_name_to_div("欧协联") == "CONF"
    assert lg.name_of("UEL") == "欧罗巴"
    assert lg.name_of("CONF") == "欧协联"
    assert lg.name_of("EUR") == "欧战(合并)"

    members = lg.model_members("EUR")
    for code in ("E0", "D1", "SP1", "I1", "F1", "UCL", "UEL", "CONF"):
        assert code in members, f"{code} 应是 EUR 成员"
    assert "WC" not in members and "EC" not in members, "国家队不参与俱乐部合并模型"
    # 非组代码原样返回
    assert lg.model_members("UCL") == ["UCL"]

    # 路由：欧战 div -> EUR（若 EUR 已训练），否则回落
    assert lg.model_key_for("UCL", available={"E0", "EUR"}) == "EUR"
    assert lg.model_key_for("UEL", available={"E0", "EUR"}) == "EUR"
    assert lg.model_key_for("CONF", available={"EUR"}) == "EUR"
    assert lg.model_key_for("UCL", available={"UCL"}) == "UCL"
    assert lg.model_key_for("E0", available={"E0", "EUR"}) == "E0"
    assert lg.model_key_for(None) is None

    # openfootball 注册表与数据集名
    assert dataset_name("UEL") == "uel_matches"
    assert "2021-22" in default_seasons("UEL")
    print("  ✓ 配置：竞彩映射 / EUR 模型组 / 路由")


def test_datasets() -> None:
    import pandas as pd

    from src.config import get_settings
    root = get_settings().processed_dir
    frames: list[pd.DataFrame] = []
    for comp in ("UEL", "CONF"):
        path = root / f"{dataset_name(comp)}.parquet"
        if not path.exists():
            print(f"  [跳过] 未抓取 {comp}")
            continue
        df = pd.read_parquet(path)
        assert len(df) > 100, f"{comp} 数据太少: {len(df)}"
        assert set(df["league_code"]) == {comp}
        assert df.duplicated(["date", "home_team", "away_team"]).sum() == 0
        # 变音符号队名必须已归一化（中文别名按 ASCII 对齐）
        non_ascii = [n for n in set(df["home_team"]) | set(df["away_team"])
                     if any(ord(c) > 127 for c in n)]
        assert not non_ascii, f"{comp} 仍有未归一化队名: {non_ascii[:5]}"
        frames.append(df)
    if frames:
        print(f"  ✓ uel/conf 数据集完整（{', '.join(str(len(f)) for f in frames)} 场）")


def test_load_training_data_merges() -> None:
    from src.pipeline import load_training_data
    df = load_training_data()
    codes = set(df["league_code"].dropna().unique())
    for c in ("E0", "D1", "SP1", "I1", "F1"):
        assert c in codes, f"缺 {c}"
    if {"UCL", "UEL", "CONF"} <= codes:
        print(f"  ✓ 训练数据已合并（{len(df)} 场，codes={sorted(codes)}）")
    else:
        print(f"  [部分] 欧战数据未齐（codes={sorted(codes)}），"
              f"先跑 fetch-ucl / fetch-europa")


def test_train_predict_eur() -> None:
    from src.ingest.jingcai_scraper import JcMatch
    from src.pipeline import (build_matcher, load_training_data, predict_matches,
                              train_leagues)

    # years=1 缩小窗口以加速测试（组成员合并逻辑不受影响）
    models = train_leagues(leagues=["EUR"], years=1, save=False, verbose=False)
    assert "EUR" in models, "EUR 训练失败"
    attack = models["EUR"]["dc"].attack
    # 组成员合并：五大联赛 + 欧战的队都在
    for team in ("Man City", "Bayern Munich", "Real Madrid"):
        assert team in attack, f"合并模型缺 {team}"

    matcher = build_matcher(load_training_data())
    match = JcMatch(
        match_id=1, match_num="周四004", match_date="2026-10-23",
        match_time="03:00:00", league="欧罗巴", league_code="UEC",
        home_cn="尤文图斯", away_cn="雷恩",
        home_en="JUV", away_en="REN", home_rank="", away_rank="",
        had={"h": "1.60", "d": "3.80", "a": "5.50"},
        hhad={"h": "2.30", "d": "3.40", "a": "2.90",
              "goalLine": "-1", "goalLineValue": "-1.00"},
    )
    rows = predict_matches([match], models, matcher, edge_threshold=0.05,
                           skip_started=False)
    r = rows[0]
    assert not r.get("skipped"), r.get("skipped")
    assert r["div"] == "UEL", r
    assert r["model"] == "EUR", f"应路由到 EUR 模型，实际 {r['model']}"
    assert r["score_most_likely"] and ":" in r["score_most_likely"]
    assert abs(sum(r["had"].values()) - 1) < 1e-6
    print("  ✓ EUR 训练 + 欧罗巴预测路由（div=UEL, model=EUR）")


def test_fallback_ucl() -> None:
    """EUR 缺席时，欧冠场次回落到 UCL 自有模型。"""
    from src.ingest.jingcai_scraper import JcMatch
    from src.pipeline import build_matcher, load_training_data, predict_matches
    from src.models import dixon_coles as dc

    # 极小合成模型（只为验证路由，不验证数值）：凑够最小样本 20 场
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(7)
    teams = ["Arsenal", "PSV Eindhoven", "Chelsea", "Ajax"]
    rows_df = pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=30, freq="7D"),
        "home_team": [teams[i % 4] for i in range(30)],
        "away_team": [teams[(i + 1) % 4] for i in range(30)],
        "ft_home": rng.integers(0, 5, 30),
        "ft_away": rng.integers(0, 5, 30),
    })
    model = dc.fit(rows_df, half_life_days=540)
    models = {"UCL": {"dc": model, "hf": None}}
    matcher = build_matcher(load_training_data())
    match = JcMatch(
        match_id=2, match_num="周三001", match_date="2026-10-21",
        match_time="20:00:00", league="欧冠", league_code="UCL",
        home_cn="阿森纳", away_cn="埃因霍温",
        home_en="ARS", away_en="PSV", home_rank="", away_rank="",
        had={"h": "1.70", "d": "3.70", "a": "4.60"},
        hhad={"h": "2.50", "d": "3.50", "a": "2.70",
              "goalLine": "-1", "goalLineValue": "-1.00"},
    )
    out = predict_matches([match], models, matcher, skip_started=False)[0]
    assert not out.get("skipped"), out.get("skipped")
    assert out["div"] == "UCL"
    assert out["model"] == "UCL", "无 EUR 时应回落 UCL"
    print("  ✓ EUR 缺席时回落 UCL 模型")


def main() -> int:
    print("== 测试：欧罗巴解析 ==")
    test_parse_el()
    print("== 测试：配置路由 ==")
    test_config_routing()
    print("== 测试：数据集完整性 ==")
    test_datasets()
    print("== 测试：训练数据合并 ==")
    test_load_training_data_merges()
    print("== 测试：EUR 训练+预测路由 ==")
    test_train_predict_eur()
    print("== 测试：UCL 回落 ==")
    test_fallback_ucl()
    print("\n全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
