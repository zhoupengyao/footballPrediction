# 赔率数据缺口（odds gap）

> 回答一个问题：**回测能不能算 ROI？** 以及赔率从哪来。

## 1. 问题

价值投注（value bet）是否盈利，只有用**真实收盘赔率**回测才算得出来。
但项目里长期缺赔率，导致回测只能算「准确率」，算不出「收益」。原因：

1. **本地直连被墙**：`www.football-data.co.uk` 请求直接 `ConnectionError`。
2. **datasets 镜像删了赔率列**：`datasets/football-datasets` 只保留比分/统计，
   列头为 `Date,HomeTeam,AwayTeam,FTHG,FTAG,...`，**没有** B365/PS/Avg 赔率。
3. **`docs/odds_gap.md` 一直不存在**——本文件补上。

## 2. 数据源实测（本机 2026-10）

| 来源 | 可达性 | 含赔率 | 结论 |
|---|---|---|---|
| football-data.co.uk 直连 | ❌ 被墙 | ✅ | 不可用 |
| `datasets/football-datasets` | ✅ 已有 | ❌ | 只能训练 |
| `footballcsv/mirror.footballdata` | ❌ raw 被墙 | ❌（已剥离，仅比分） | 无赔率 |
| jsDelivr / statically / githack | ❌ 连接重置 | — | 不可用 |
| **`ghproxy.net`（raw 代理）** | ✅ 可达 | ✅ | **推荐** |
| **`jokecamp/FootballData`（API/tree）** | ✅ api 可达 | ✅ | 取文件清单 |

关键：`raw.githubusercontent.com` / jsDelivr 被墙，但 `ghproxy.net` 可代理 raw、
`api.github.com` 可取文件清单。
`jokecamp/FootballData/football-data.co.uk/{国家}/...` 保留完整赔率列
（`B365H/D/A`、`PSH/D/A`、`AvgH/D/A`）；赔率从 2002 年起才有。

## 3. 三种取数方式

### 3.1 代理按需（`--via proxy`，推荐，默认）
```
python -m src.cli fetch-odds --online --via proxy
```
- 用 GitHub tree API 取一次文件清单，再经 `ghproxy.net` 逐个下载目标联赛 CSV。
- **无 60 次/小时额度限制**，实测 112 个文件（5 联赛全史）一次拉完、速度快。
- 跳过已存在文件，可增量补齐。

### 3.2 API 按需（`--via api`）
```
python -m src.cli fetch-odds --online --via api --leagues E0
```
- 走 GitHub blobs API；受限 **约 60 次/小时**，每文件 1 次请求。
- 适合代理不可用时的兜底（如设了 GitHub token 则额度升到 5000/小时）。

### 3.3 整包（`--via zip`）
```
python -m src.cli fetch-odds --online --via zip
```
- 走 `codeload.github.com` 下载 46.7 MB zipball。
- ⚠️ 实测**不支持 Range（无法断点/并行）**，本机持续速率仅 ~25 KB/s，
  且会在 ~20 MB 处被 `ChunkedEncodingError` 掐断 → **不推荐**。

## 4. 合并与使用

- 规范化列：`league_code, date, home_team, away_team, odds_home, odds_draw, odds_away, odds_source`
- 解析优先级：`B365` → `PS` → `Avg` → `BbAv`（取第一个存在的三列）
- 主键合并：`(league_code, date, home_team, away_team)`，左连接 → `merge_odds()`
- 落盘：`data/processed/historical_odds.parquet`
- 回测默认自动合并；`--no-odds` 可关闭。

## 5. 实测覆盖（`fetch-odds --via proxy` 全量）

| 联赛 | 赔率条数 | 起始 | 截止 |
|---|---|---|---|
| E0 英超 | 6870 | 2002-08 | 2021-01 |
| D1 德甲 | 3371 | 2002-08 | 2013-12 |
| F1 法甲 | 4002 | 2002-08 | 2013-12 |
| I1 意甲 | 3948 | 2002-09 | 2013-12 |
| SP1 西甲 | 3963 | 2002-08 | 2013-12 |

- 更早赛季（1993–2002）原始文件**没有** B365 等赔率列。
- 非英超四国在仓库中只有到 2013-12 的文件；**5 联赛的共同赔率窗口为 2002–2013**。

## 6. 已知局限

1. **时间范围**：非英超四国赔率止于 2013-12，英超止于 2021-01。回测 ROI
   反映的是对应年代的市场，不能直接外推到今天。
2. **赔率口径**是各公司收盘赔率（`B365` 等，含水位），**不是竞彩赔率**
   （竞彩返奖约 73%）。竞彩口径的 ROI 需靠逐日积累 `data/odds/jc_odds_*.json`。
3. **队名对齐**：两侧同源，多数精确匹配；个别改名会匹配失败、赔率为空。
4. **覆盖**：`datasets` 镜像只有 5 个联赛有比赛数据，故只有这 5 个联赛能回测。

## 7. 后续可选

- **逐日积累竞彩快照**：`fetch-jingcai --online` 每天跑一次，一年后即可回测竞彩真实口径。
- **GitHub token**：设置后额度升到 5000/小时，`--via api` 可一次取全 4 个联赛。
- **换源**：改 `settings.yaml → odds.source_repo` 即可切换镜像。
