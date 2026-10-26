import re, sys, json, requests
sys.stdout.reconfigure(encoding="utf-8")

H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.sporttery.cn/",
    "X-Requested-With": "XMLHttpRequest",
}
s = requests.Session(); s.headers.update(H)

urls = [
 "https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry?poolCode=had,hhad,crs,ttg,hafu&channel=c",
 "https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry?poolCode=had,hhad,crs,ttg,hafu&clientCode=3001",
 "https://webapi.sporttery.cn/gateway/uniform/football/getMatchOddsV1.qry?matchId=2042003&poolCode=had&clientCode=3001&termLimit=300",
 "https://webapi.sporttery.cn/gateway/uniform/football/getMatchListV1.qry?clientCode=3001&poolCode=had,hhad,crs,ttg,hafu",
]
for u in urls:
    try:
        r = s.get(u, timeout=20)
        ct = r.headers.get("Content-Type","")
        print("\n", r.status_code, "JSON" if "json" in ct else "html", u.split("gateway/")[1][:80])
        if "json" in ct:
            d = r.json()
            print("   success:", d.get("success"), d.get("errorMessage"))
            print("   ", json.dumps(d, ensure_ascii=False)[:400])
    except Exception as e:
        print("\nFAIL", type(e).__name__, str(e)[:90])

r = s.get("https://www.sporttery.cn/", timeout=25)
print("\n首页", r.status_code)
links = set(re.findall(r"href=[\"']([^\"']*(?:jc|football|kaijiang|match)[^\"']*)[\"']", r.text, re.I))
for l in sorted(links)[:25]:
    print("   ", l)
