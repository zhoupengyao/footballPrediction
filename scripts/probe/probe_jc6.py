"""尝试用完整浏览器头绕过竞彩 WAF 获取 CRS/TTG/HAFU 赔率。"""
import json
import sys
import time

import requests

sys.stdout.reconfigure(encoding="utf-8")

BASE_H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.sporttery.cn/jc/jsk/",
    "Origin": "https://www.sporttery.cn",
    "X-Requested-With": "XMLHttpRequest",
    "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

lst = requests.get(
    "https://webapi.sporttery.cn/gateway/uniform/football/getMatchListV1.qry?clientCode=3001",
    timeout=25, headers=BASE_H).json()
mil = lst["value"]["matchInfoList"]
m = mil[0]["subMatchList"][0]
mid = m["matchId"]
print("matchId:", mid)

urls = [
    f"https://webapi.sporttery.cn/gateway/uniform/football/getMatchOddsV1.qry?matchId={mid}&clientCode=3001",
    f"https://webapi.sporttery.cn/gateway/uniform/football/getMatchOddsV1.qry?businessDate=2026-10-16&clientCode=3001",
    "https://webapi.sporttery.cn/gateway/uniform/football/getMatchOddsV1.qry?matchIdList={}&poolCode=crs,ttg,hafu&clientCode=3001".format(mid),
    f"https://webapi.sporttery.cn/gateway/jc/football/getMatchOddsV1.qry?matchId={mid}&poolCode=had,hhad,crs,ttg,hafu",
    f"https://webapi.sporttery.cn/gateway/uniform/football/getMatchInfoV1.qry?matchId={mid}&clientCode=3001",
]

s = requests.Session()
s.headers.update(BASE_H)
for url in urls:
    try:
        r = s.get(url, timeout=20)
        ok = "json" in (r.headers.get("Content-Type") or "")
        print(f"\n{r.status_code} {'JSON' if ok else 'html'}  {url.split('gateway/')[1][:75]}")
        if ok:
            d = r.json()
            print("  success:", d.get("success"), d.get("errorMessage"))
            print("  ", json.dumps(d, ensure_ascii=False)[:700])
    except Exception as e:
        print(f"\nFAIL {type(e).__name__}: {str(e)[:90]}")
    time.sleep(2)
