# 手动赛果录入

用于补充自动数据源拿不到的赛果。文件：`data/manual_results/results.csv`。

## 列说明

| 列 | 必需 | 说明 |
|---|---|---|
| `date` | 建议 | 比赛日期，格式 `YYYY-MM-DD`；用于区分不同日期的同编号场次 |
| `match_num` | 是 | 竞彩编号，如 `周日012` |
| `league` | 否 | 联赛中文名，仅便于阅读 |
| `home_cn` / `away_cn` | 否 | 中文队名，仅便于阅读 |
| `ft_home` / `ft_away` | 是 | 全场比分（主队、客队） |
| `ht_home` / `ht_away` | 半全场必需 | 半场比分；没有填则半全场显示“无法结算” |

## 示例

```csv
date,match_num,league,home_cn,away_cn,ft_home,ft_away,ht_home,ht_away
2026-10-27,周一001,英超,曼城,阿森纳,2,1,1,0
2026-10-27,周一002,瑞超,盖斯,哥德堡,1,1,0,1
```

## 录入后

```powershell
python -m src.cli reconcile --date 20261027 --manual data/manual_results/results.csv
python scripts/export_web.py --check
git add data/manual_results web/public/data reports
git commit -m "results: 2026-10-27"
git push
```

注意：
- 不要用 `match_num` 单独作为唯一键，`周一001` 每周都会重复；请保留 `date`。
- 没有半场比分时，半全场命中率不会把这批场次算进分母，不会误判为未命中。
- 赛果只影响 `predicted` 场次；被跳过的比赛即使有赛果，也不会进入命中率统计。
