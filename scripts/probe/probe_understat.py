"""探测 understat.com 可用性与数据范围。"""
import json
import re
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

LEAGUES = {"EPL": "英超", "La Liga": "西甲", "Serie A": "意甲", "Bundesliga": "德甲", "Ligue 1": "法甲"}


def probe(code: str) -> None:
    r = requests.get(f"https://understat.com/league/{code}", timeout=25)
    print(f"[{code}] status={r.status_code} bytes={len(r.content)}")
    m = re.search(r"var datesData\s*=\s*JSON\.parse\('(.*?)'\)", r.text, re.S)
    if not m:
        print("  datesData NOT found")
        return
    raw = m.group(1).encode().decode("unicode_escape")
    data = json.loads(raw)
    dates = sorted({x["date"] for x in data})
    finished = [x for x in data if x.get("isResult")]
    print(f"  fixtures={len(data)}  finished={len(finished)}")
    print(f"  date range: {dates[0]} -> {dates[-1]}")
    # 抽样一场已完成比赛看字段
    if finished:
        sample = finished[-1]
        keys = list(sample.keys())
        print(f"  sample keys: {keys}")
        h = sample["h"]
        a = sample["a"]
        print(f"  sample: {h['title']} {h['goals']} - {a['goals']} {a['title']}")
        print(f"    xG home={h['xG']:.2f} away={a['xG']:.2f}")
        print(f"    date={sample['datetime']}")


if __name__ == "__main__":
    for code in LEAGUES:
        try:
            probe(code)
        except Exception as e:
            print(f"[{code}] FAIL {type(e).__name__}: {str(e)[:120]}")
        print()
