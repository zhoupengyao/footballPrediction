"""抓取竞彩官方赛果并合并到 data/manual_results/results.csv。

用法：
    python scripts/fetch_results.py --date 20261025
    python scripts/fetch_results.py --start 20261018 --end 20261025
    python scripts/fetch_results.py --from-reports
    python scripts/fetch_results.py --date 20261025 --dry-run
    python scripts/fetch_results.py --date 20261025 --overwrite

默认只补缺失场次，不覆盖手动录入的比分；需要覆盖时加 --overwrite。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import PROJECT_ROOT, get_settings  # noqa: E402
from src.ingest.jingcai_results import (  # noqa: E402
    date_range,
    fetch_results,
    latest_prediction_date,
    load_results_csv,
    merge_results,
    normalize_date,
    prediction_dates,
    save_raw,
    write_results_csv,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="抓取竞彩官方赛果，写入 data/manual_results/results.csv")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--date", help="单日，YYYY-MM-DD 或 YYYYMMDD")
    group.add_argument("--from-reports", action="store_true",
                       help="抓取 reports/predict_*.json 里所有日期")
    parser.add_argument("--start", help="区间开始日期")
    parser.add_argument("--end", help="区间结束日期（默认等于开始）")
    parser.add_argument("--out", default="data/manual_results/results.csv",
                        help="输出 CSV（默认 data/manual_results/results.csv）")
    parser.add_argument("--raw-dir", default="data/raw/jingcai_results",
                        help="原始 JSON 保存目录")
    parser.add_argument("--no-raw", action="store_true", help="不保存原始 JSON")
    parser.add_argument("--overwrite", action="store_true",
                        help="用接口结果覆盖已有比分（默认保留手动值）")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不写文件")
    parser.add_argument("--page-size", type=int, default=100,
                        help="接口分页大小，默认 100")
    parser.add_argument("--delay", type=float, default=None,
                        help="请求间隔秒数，默认读取 settings.yaml（3 秒）")
    return parser.parse_args(argv)


def _resolve(path_text: str) -> Path:
    p = Path(path_text).expanduser()
    return p if p.is_absolute() else (PROJECT_ROOT / p)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = get_settings()
    reports_dir = settings.reports_dir

    if args.date:
        dates = [normalize_date(args.date)]
    elif args.from_reports:
        dates = prediction_dates(reports_dir)
        if not dates:
            print(f"没有找到预测报告: {reports_dir}/predict_*.json")
            return 1
    else:
        start = args.start or args.end or latest_prediction_date(reports_dir)
        if not start:
            print("请指定 --date / --start / --end，或先运行 predict 生成报告")
            return 1
        dates = date_range(start, args.end or start)

    out_path = _resolve(args.out)
    raw_dir = _resolve(args.raw_dir)

    print(f"抓取日期：{', '.join(dates)}")
    all_results = []
    for date in dates:
        try:
            results, payloads = fetch_results(
                date, date, page_size=args.page_size, delay=args.delay)
        except RuntimeError as e:
            print(f"[失败] {date}: {e}")
            return 1
        if not args.no_raw:
            raw_path = save_raw(payloads, date, date, raw_dir)
            print(f"  原始响应：{raw_path}")
        print(f"  {date}: 有效赛果 {len(results)} 场")
        all_results.extend(results)

    if not all_results:
        print("没有拿到任何有效赛果（可能比赛尚未结束，或接口暂时没有数据）。")
        return 0

    existing = load_results_csv(out_path)
    merged, stats, conflicts = merge_results(
        existing, all_results, overwrite=args.overwrite)

    print("\n合并结果：")
    for key, value in stats.items():
        labels = {
            "added": "新增", "filled": "补全", "updated": "覆盖",
            "unchanged": "未变", "conflicts": "冲突",
        }
        print(f"  {labels.get(key, key)}：{value}")

    if conflicts:
        print("\n冲突（默认保留手动值，加 --overwrite 可覆盖）：")
        for item in conflicts[:20]:
            print(f"  {item['date']} {item['match_num']}: "
                  f"手动 {item['manual']} / 接口 {item['api']}")
        if len(conflicts) > 20:
            print(f"  ……另有 {len(conflicts) - 20} 条")

    if args.dry_run:
        print("\n[dry-run] 未写入文件。")
    else:
        write_results_csv(merged, out_path)
        print(f"\n已写入：{out_path}（共 {len(merged)} 行）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
