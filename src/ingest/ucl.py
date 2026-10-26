"""欧冠数据接入（向后兼容封装）。

通用实现已迁移到 :mod:`src.ingest.openfootball`（支持 cl/el/conf 多赛事），
本模块保留原有签名，供既有测试与 fetch-ucl 调用。
"""
from __future__ import annotations

import pandas as pd

from src.ingest.openfootball import (
    HEADERS,
    URL_TEMPLATE,
    _infer_date,
    _parse_scores,
    build_dataset as _build,
    default_seasons,
    fetch_season,
    load_dataset as _load,
    parse_season,
    read_cached,
    save_dataset as _save,
)

DEFAULT_SEASONS = default_seasons("UCL")


def build_dataset(seasons: list[str] | None = None, online: bool = False,
                  force: bool = False, verbose: bool = True) -> pd.DataFrame:
    """抓取/读取欧冠并解析成统一 schema 的 DataFrame。"""
    return _build("UCL", seasons=seasons, online=online, force=force,
                  verbose=verbose)


def save_dataset(df: pd.DataFrame, name: str = "ucl_matches") -> "object":
    return _save(df, "UCL", name=name)


def load_dataset(name: str = "ucl_matches") -> pd.DataFrame:
    return _load("UCL", name=name)


__all__ = [
    "URL_TEMPLATE", "HEADERS", "DEFAULT_SEASONS",
    "fetch_season", "read_cached", "parse_season",
    "build_dataset", "save_dataset", "load_dataset",
    "_parse_scores", "_infer_date",
]
