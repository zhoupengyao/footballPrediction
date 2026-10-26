# 每日操作手册

> 适用环境：Windows + PowerShell，项目目录 `D:\python_学习区\football`
> 最后更新：2026-10-25

---

## 关于盈利的现实预期（重要）

竞彩综合返奖率约 **73%**，市场抽水 27%。历史回测（五大联赛、含收盘赔率）ROI 约
**−7.6%**，说明当前模型在真实赔率口径下**尚未跑赢市场**。因此：

1. 本系统定位是**决策辅助 / 研究学习**，不保证盈利。
2. 模型输出的「价值选项（★）」是**统计上的 edge 信号**，不是稳赚指令。
3. 早盘 edge 尤其容易误报，务必以临场前 1–2 小时的最新快照为准。
4. 长期是否有效，用 `reconcile` 命令积累的投注台账（`data/processed/bet_ledger.parquet`）
   对账，别凭感觉。

> **Web 面板**：预测/对账完成后运行 `python scripts/export_web.py --check`，
> 再 `git push` 即可更新 GitHub Pages。完整说明见 [`web.md`](web.md)。

---

## 0. 每次打开终端先做这一步

```powershell
cd /d D:\python_学习区\football
$env:PYTHONIOENCODING="utf-8"
```

不设 `PYTHONIOENCODING` 的话，终端里的中文可能显示成乱码。
（报告文件本身是 UTF-8，不受影响。）

检查环境是否正常：

```powershell
python -m src.cli status
```

正常会打印依赖、模型、数据、快照的状态（模型的半全场/Elo/ML 是否已训练也会显示）。

---

## 1. 每天的核心流程（比赛日）

只有两步：**抓快照 → 预测**。想直接看「下什么」再跑一步 `recommend`（见第 6 节）。

```powershell
# 1) 抓取当天竞彩场次与赔率（含今明两期）
python -m src.cli fetch-jingcai --online

# 2) 预测（默认只跑第一期，自动跳过已开赛）
python -m src.cli predict

# 3) 候选筛选（可选：筛可靠价值注，分级+仓位；纸面，不构成盈利建议）
python -m src.cli recommend
```

耗时约 3 秒。结果在：

```
reports\predict_YYYYMMDD.md     # 人看
reports\predict_YYYYMMDD.json   # 程序/对账用
```

同一天重复运行会**覆盖**同名的报告；快照则**带时间戳各存一份**，不覆盖（见下）。

---

## 2. 流程时间线

**核心原则：早盘侦察，临场拍板。** 竞彩赔率一天内会变（尤其临场资金涌入后），
刚开售时的早盘赔率水位偏高、波动大，此时 `predict` 报出的 edge 容易是**误报**；
真正下决策要以**临场前 1–2 小时（阵容公布后）的最新赔率**为准。

| 时间 | 动作 | 说明 |
|---|---|---|
| 中午 / 下午（开售后） | `fetch-jingcai --online` → `predict` | **初筛侦察**，看模型关注哪些场次，不下结论 |
| 临场前 1–2 小时 | 再跑 `fetch-jingcai --online` → `predict` | **拍板**。快照带时间戳另存一份，不覆盖早盘的；`predict` 自动用最新快照 |
| 下决策前 | 对比早盘/临场两份快照 | 赔率走势（降水上盘、热度方向）作为额外参考 |
| 次日 | `reconcile` 对账 | 见第 9 节，自动算命中率/盈亏并写台账 |

```powershell
# 中午：侦察
python -m src.cli fetch-jingcai --online
python -m src.cli predict

# 临场（比如 17:30，阵容已公布）：拍板。快照另存 jc_odds_20261024_1730.json
python -m src.cli fetch-jingcai --online
python -m src.cli predict
```

> `predict` **不联网**。它只读磁盘上的快照，所以必须先 `fetch-jingcai`。
> 快照文件名带抓取时间（`jc_odds_YYYYMMDD_HHMM.json`），同一天多次抓取互不覆盖，
> `predict` 自动选最新一份。

---

## 3. 「期」是什么，怎么选

竞彩接口按 **businessDate（销售日）** 分组，每期编号独立从 `001` 开始：

```
第 1 期：周三 2026-10-21   编号 周三001 … 周三013
第 2 期：周四 2026-10-22   编号 周四001 … 周四013
```

`predict --round` 提供三种模式：

| 参数 | 含义 |
|---|---|
| `--round first` | **默认**。取快照里最早的一期（今天抓就是今天这期） |
| `--round today` | 严格取 `businessDate == 今天` 的一期；没有则回退到 `first` |
| `--round all` | 两期全部预测（旧行为） |

```powershell
python -m src.cli predict                  # 只预测第一期
python -m src.cli predict --round today    # 严格只取今天那期
python -m src.cli predict --round all      # 今明两期都预测
```

终端会打印本期信息，例如：

```
本期：周三 2026-10-21（期号 261021），13/24 场
```

报告头部也会带一行 `- 期（销售日）：2026-10-21`。

> **注意**：如果今天这期已经全部开赛，`--round first` 会选出这些场次但全部被跳过，结果为 0 场。
> 想看明天那期，用 `--round all`（今天的会被跳过，明天的正常预测）。

### 只预测指定场次（--match-num / --team）

只关注某几场时，不必在长列表里肉眼找，直接指定：

```powershell
python -m src.cli predict --match-num 周六005           # 指定编号（也接受纯数字 005）
python -m src.cli predict --match-num 周六005 周六016   # 多个编号
python -m src.cli predict --team 曼城                    # 队名关键字，中英文皆可
python -m src.cli predict --team 皇马 阿森纳             # 多个关键字（命中任一即预测）
python -m src.cli predict --match-num 005 --team 波尔图  # 编号+队名可组合（同时满足）
```

规则：

- 编号支持全码（`周六005`）或纯数字后缀（`005`），多个编号之间是「或」。
- 队名是**子串匹配**、不区分大小写，命中主队或客队任一即保留
  （如 `--team 曼城` 命中「曼城」，`--team Madrid` 命中 `Real Madrid`；
  注意 `皇马` **不会**命中「皇家马德里」——子串匹配，用 `马德里`）。
- 指定编号/队名时**跨全部期查找**，`--round` 不生效（不必先猜它属于哪期）。
- 未命中会列出当前快照的全部编号，方便照抄。

---

## 4. 已开赛保护

默认会跳过开赛时间已过的场次，避免「赛后预测」：

```powershell
python -m src.cli predict                  # 默认跳过已开赛
python -m src.cli predict --include-started  # 强制预测（一般不要用）
```

被跳过的场次会在终端显示 `[跳过] 周三001 日职: 已开赛/结束 ...`。

---

## 5. 常用参数

### 预测

| 参数 | 默认 | 说明 |
|---|---|---|
| `--odds PATH` | 最新快照 | 指定某份快照 |
| `--leagues E0 D1` | 全部 | 只载入指定联赛的模型 |
| `--edge 0.05` | 0.05 | 价值投注的 edge 阈值 |
| `--max-stake 0.02` | 0.02 | 单场仓位上限（2%） |
| `--blend 0.6` | 0.6 | 市场混合权重（0=纯市场，1=纯模型） |
| `--elo 0.8` | 0.8 | DC 与 Elo 混合时 DC 权重（0=纯Elo，1=纯DC） |
| `--ml-weight 0.8` | 0.8 | DC+Elo 与 ML 混合时 DC+Elo 权重（0=纯ML，1=纯DC+Elo） |
| `--min-odds 1.3` | 1.3 | 价值投注最低赔率 |
| `--max-edge 0.5` | 0.5 | 价值投注 edge 上限（过滤异常） |
| `--crs-top 3` | 3 | 比分概率 Top N |
| `--include-started` | 关闭 | 连已开赛场次也预测 |
| `--round first\|today\|all` | first | 期筛选 |
| `--match-num 编号…` | 无 | 只预测指定编号场次（跨期查找，如 `周六005` 或 `005`） |
| `--team 关键字…` | 无 | 只预测含指定球队的场次（中英文子串匹配） |

### 抓取

```powershell
python -m src.cli fetch-jingcai --online            # 默认玩法池
python -m src.cli fetch-jingcai --online --pool had hhad crs
python -m src.cli fetch-jingcai                     # 不联网，只查看最新快照
```

---

## 6. 候选筛选（纸面，recommend 命令）

> ⚠️ **这不是「稳赚推荐」**。历史回测 ROI 为负（−3%~−9%），本功能定位是**风险筛选 + 纸面跟踪**，
> 帮你「少下、下得明白」，不构成盈利建议。

`recommend` 在 `predict` 的价值选项上做**过滤、分级、分配仓位**，输出候选清单：

```powershell
python -m src.cli recommend                    # 稳健档，输出候选 + 观察
python -m src.cli recommend --bankroll 1000    # 按本金算具体金额
python -m src.cli recommend --risk balanced    # 三档：conservative/balanced/aggressive
python -m src.cli recommend --match-num 周日012 --team 曼城
```

规则（默认稳健档，基于阶段 1 历史回测结论）：

- 只筛**胜平负（HAD）单关**；让球（HHAD）历史无赔率、未验证，一律只「观察」；
- 只在**历史唯一微正的 E0 英超**里推荐，其余联赛一律「观察」；
- 过滤：`edge ≥ 阈值`、`EV ≥ 5%`、赔率 1.50–6.00、模型概率 30%–70%；
- 分级：★★★（EV≥10%）、★★（EV 5–10%）、★ 观察（不下注）；
- 仓位：1/4 Kelly，单注 ≤2%，**日总 ≤5%（稳健）**，超出按比例缩。

输出：

```
reports\recommend_YYYYMMDD.{md,json}     # 候选清单 + 理由 + 过关参考
data\processed\recommendations.parquet   # 候选日志（纸面跟踪）
```

> 无 `--bankroll` 时只显示仓位百分比（纸面，不涉及金额）。
> 阈值与联赛/玩法白名单在 `config\settings.yaml` 的 `recommend` 段
> （`reliable_leagues` / `markets` / `profiles`）调整。

---

## 7. 训练与回测（不是每天做）

| 命令 | 建议频率 | 说明 |
|---|---|---|
| `python -m src.cli train` | 每周 / 每月 | 默认重训全部赛事（欧冠 10 年窗口；EUR 合并模型全部历史，约 100 秒） |
| `python -m src.cli backtest` | 改策略后 / 每月 | walk-forward 回测，几分钟 |
| `python -m src.cli fetch-tier1 --online` | 每月 | 更新历史比赛数据（5 大联赛，下载较大） |
| `python -m src.cli fetch-tier1-gh --online` | 每月 / 扩覆盖时 | 从 jokecamp 镜像扩荷/比/葡/土/希/苏等联赛（见第 10 节） |
| `python -m src.cli fetch-understat --online` | 每周 | 更新最新赛季比分+xG（补 football-data 镜像的赛季空窗） |
| `python -m src.cli fetch-apifootball --online` | 每月 / 扩覆盖时 | 下载 API-Football 赛果（巴甲/挪超/瑞超/芬超等 tier2） |
| `python -m src.cli fetch-ucl --online` | 每月 / 新赛季 | 更新欧冠数据（openfootball） |
| `python -m src.cli fetch-europa --online` | 每月 / 新赛季 | 更新欧罗巴 + 欧协联数据（openfootball） |
| `python -m src.cli doctor` | 扩覆盖后 / 出现「队名未匹配」时 | 诊断队名匹配，列出未匹配球队与候选 |
| `python -m src.cli pipeline --online` | **不建议日常用** | 会下载历史数据 + 重训 + 预测，很慢 |

```powershell
# 只重训某几个联赛
python -m src.cli train --leagues E0 SP1 --years 5

# 调整小样本收缩先验（默认取 settings.yaml 的 training.shrinkage_prior=8）
python -m src.cli train --leagues E0 --shrinkage 12

# 额外训练 LightGBM 特征模型（第三意见，较慢，可选）
python -m src.cli train --leagues E0 --with-ml

# 欧冠（自动使用 10 年窗口 / 540 天半衰期）
python -m src.cli train --leagues UCL

# 欧战合并模型（五大联赛+欧冠+欧罗巴+欧协联合并数据、全部历史，约 100 秒）
python -m src.cli train --leagues EUR

# 回测（默认按联赛配置；E0 为 5 年窗口、EV 阈值 0）
python -m src.cli backtest --leagues E0 --start-year 2010 --end-year 2013

# 对比不同收缩先验的回测
python -m src.cli backtest --leagues E0 --start-year 2024 --no-odds --shrinkage 0
python -m src.cli backtest --leagues E0 --start-year 2024 --no-odds --shrinkage 8

# 欧冠回测（自动 10 年 / 540 天；无历史赔率，只能算准确率）
python -m src.cli backtest --leagues UCL --no-odds

# 欧战合并模型回测（全部历史窗口；组内成员合并成一次 walk-forward）
python -m src.cli backtest --leagues EUR --start-year 2024 --no-odds

# 一键流程（谨慎使用）
python -m src.cli pipeline --online --round first
```

模型落盘位置：

```
data\models\{E0,D1,SP1,I1,F1,UCL,UEL,CONF,EUR}\dc.json         # Dixon-Coles
data\models\{E0,D1,SP1,I1,F1,UCL,UEL,CONF,EUR}\halffull.json   # 半全场
data\models\{E0,D1,SP1,I1,F1,UCL,UEL,CONF,EUR}\elo.json        # Elo（第二意见）
data\models\{E0,D1,SP1,I1,F1,UCL,UEL,CONF,EUR}\ml.joblib       # LightGBM（第三意见，--with-ml 才有）
```

> **预测时的模型路由**：欧罗巴/欧协联/欧冠场次默认都用 `EUR` 合并模型
> （`EUR` 不存在时自动回落到该赛事自己的模型）；五大联赛内战仍用各自模型。

### 模型与混合链

每场比赛的胜平负概率是**四层混合**得到的（权重均可调）：

```
Dixon-Coles ──► 与 Elo 混合 ──► 与 LightGBM 混合 ──► 与去水市场概率混合
                (--elo 0.8)      (--ml-weight 0.8)     (--blend 0.6)
```

- **Dixon-Coles**：泊松比分模型，含时间衰减 + 小样本收缩（`train --shrinkage`）。
- **Elo**：第二意见，缓解 DC 的过度自信。
- **LightGBM**：13 维滚动特征（Elo 差、近 8 场进/失/积分、休息天数、近 8 场 xG），
  第三意见；仅 `train --with-ml` 训练后才有，否则该层自动跳过。
- 混合方向：越靠右越「保守」——价值判断在**混合后**的概率上进行，
  因此混合越多、报出的价值场越少但越可靠（回测 ECE 校准误差随混合下降）。

`predict` 报告 JSON 里每场都带 `had_dc / elo_had / ml_had / had`（最终）字段，可自查各层贡献。

回测报告：

```
reports\backtest_{联赛}_{YYYYMMDD}.md
reports\backtest_{联赛}_{YYYYMMDD}.json
```

欧冠 walk-forward 实测（1617 场）：准确率 **56.7%**（主胜基准 47.5%），对数损失 **1.093**。
EUR 合并模型回测实测（2024 起 400 场）：准确率 **49.3%**（基准 38.3%），对数损失 **1.011**。

---

## 8. 数据与文件位置

| 内容 | 路径 |
|---|---|
| 当日赔率快照 | `data\odds\jc_odds_YYYYMMDD_HHMM.json`（旧快照为 `jc_odds_YYYYMMDD.json`） |
| 历史比赛数据 | `data\processed\tier1_matches.parquet` |
| 扩联赛比赛数据 | `data\processed\tier1_gh_matches.parquet`（`fetch-tier1-gh` 生成） |
| understat 比分+xG | `data\processed\understat_matches.parquet` |
| 欧冠历史数据 | `data\processed\ucl_matches.parquet` |
| 欧罗巴历史数据 | `data\processed\uel_matches.parquet` |
| 欧协联历史数据 | `data\processed\conf_matches.parquet` |
| 欧战原始缓存 | `data\raw\{ucl,uel,conf}\season-*.txt` |
| 历史赔率（回测用） | `data\processed\historical_odds.parquet` |
| 模型 | `data\models\<联赛>\{dc,halffull}.json` + `elo.json` + `ml.joblib` |
| 投注台账 | `data\processed\bet_ledger.parquet`（`reconcile` 追加） |
| 预测报告 | `reports\predict_YYYYMMDD.{md,json}` |
| 回测报告 | `reports\backtest_{联赛}_{YYYYMMDD}.{md,json}` |
| 对账报告 | `reports\reconcile_YYYYMMDD.{md,json}` |

快照文件名带**抓取时刻**（`jc_odds_20261024_1300.json`），同一天多次抓取**各存一份、互不覆盖**。
`predict` 默认自动取当天最新一份；要看早盘与临场的赔率走势，直接对比当天的多份快照 JSON 即可。
旧式无时间戳快照（`jc_odds_YYYYMMDD.json`）视作当天 00:00，仍会被正常识别。

---

## 9. 次日对账（reconcile 命令）

```powershell
python -m src.cli reconcile                  # 对最新预测报告对账
python -m src.cli reconcile --date 20261024   # 对指定日期的预测报告
python -m src.cli reconcile --manual scores.csv  # 手动补录赛果
```

`reconcile` 会：

1. 读取 `reports/predict_YYYYMMDD.json` 中**非跳过**场次；
2. 从本地历史数据（tier1 / understat / 欧冠 / 欧罗巴 / 欧协联）查实际比分；
3. 输出 `reports/reconcile_YYYYMMDD.{md,json}`（HAD 命中率、最可能比分命中率、
   对数损失、价值选项盈亏与 ROI）；
4. 把价值选项追加到 `data/processed/bet_ledger.parquet`（长期 ROI/CLV 唯一数据源）。

赛果尚未落盘的场次会标记「待补」——先跑
`python -m src.cli fetch-understat --online`（五大联赛）或
`fetch-ucl/fetch-europa --online`（欧战）更新赛果，再用 `--manual scores.csv`
（列：`match_num, ft_home, ft_away`）手动补录无法自动获取的场次。

```powershell
# 查看累计台账 ROI
python -c "import pandas as pd; d=pd.read_parquet('data/processed/bet_ledger.parquet'); print(d)"
```

---

## 10. 常见问题

**预测出 0 场**
- 快照过期，或本期场次已全部开赛。
- 重新 `fetch-jingcai --online`；仍为 0 就改用 `--round all` 看下一期。

**提示「未收录联赛」**
- 目前有模型的联赛：
  - 五大联赛：英超 E0、德甲 D1、西甲 SP1、意甲 I1、法甲 F1；
  - 欧战：**欧冠 UCL、欧罗巴 UEL、欧协联 CONF**（三者统一走 `EUR` 合并模型）；
  - tier2（走 API-Football）：**挪超 NOR1、瑞超 SWE1、芬超 FIN1、巴甲 BRA1**。
- 日职、日乙、韩K、澳超、中超、美职、荷甲、葡超、法乙等仍没有模型，会被跳过。
- 欧战里「没有任何历史数据」的球队会提示「球队无历史数据」并跳过
  （如实测的奈梅亨、克里特、利勒斯特——荷甲/希超/挪超不在数据源里）。
- 五大联赛球队即使没打过欧战也有数据了（如科莫、贝蒂斯），欧战场次不再因此跳过。

**扩大覆盖（荷甲/比甲/葡超/土超/希超/苏超等）**：

1. 下载数据：`python -m src.cli fetch-tier1-gh --online`（从 jokecamp 镜像取荷/比/葡/土/希/苏 + 二三级联赛比分）；
2. 补中文别名：`python -m src.cli doctor` 列出这些联赛里未匹配的球队，把确认的映射补进
   `src/jingcai/team_names.py` 的 `CN_TO_EN`（这是目前唯一需要手工的步骤）；
3. 训练：`python -m src.cli train`（新联赛的 div 代码见 `config\leagues.yaml`）。

**扩大 tier2 联赛（日职/韩K/澳超/中超/美职等走 API-Football）**：

1. 在 `config\leagues.yaml` 的 `tier2_apifootball` 给联赛加 `div` 字段，`jingcai_league_map` 加中文名映射；
2. `python -m src.cli fetch-apifootball --online`（需在 `.env` 配 `API_SPORTS_KEY`）；
3. 补中文别名 + `train`。注意 Free 计划只开放 **2022–2024** 三个赛季。

**快照是几天前的**
- 终端会打印 `⚠️ 注意：该快照是 N 天前的`。
- 旧快照仍可跑，但场次多半已开赛，会被跳过。

**终端中文乱码**
- 先执行 `$env:PYTHONIOENCODING="utf-8"`。

**同一天抓了两次，早先的赔率还在吗**
- 在。快照带时间戳另存（`jc_odds_20261024_1300.json`、`jc_odds_20261024_1730.json`），互不覆盖。
- `predict` 自动用最新那份；想对比早盘与临场赔率走势，对比当天多份快照 JSON 即可。

---

## 11. 已知限制

1. **五大联赛最新赛季靠 understat 补齐**（`fetch-understat --online`，截至其抓取日），
   其余联赛仍停在 football-data 镜像的 2025-26 赛季。understat 只覆盖五大联赛+俄超。
2. **tier2 联赛（挪超/瑞超/芬超/巴甲）走 API-Football，Free 计划只开放 2022–2024 三季**，
   且每日 100 次请求额度；更近的赛季需付费计划或换源。
2. **`fetch-tier1 --online` 走 GitHub zipball（约 46MB）**，实测可能在 20MB 左右断开，需要改走代理才稳定。
3. **对账（`reconcile`）依赖本地已落盘的赛果**：最新一轮若未 `fetch-understat/fetch-ucl`，
   会标记「待补」，需手动 `--manual` 补录或先更新赛果。
4. **早盘 edge 易误报**：刚开售时赔率水位偏高，`predict` 报出的价值场在临场前常缩水，
   请以临场前 1–2 小时的最新快照为准（快照已带时间戳，可对比走势）。
5. **回测 ROI 为负**（5 联赛 2005–2013 约 −7.6%），模型偏自信；现已加入市场混合
   （`value.blend_weight`）缓解过度自信，但价值投注仍需谨慎，用台账对账验证。
6. **欧战只覆盖 2021-2024 四季**（openfootball 的 `el.txt`/`conf.txt`，2020-21 与 2025-26、2026-27 均 404）；
   欧罗巴/欧协联**新赛季数据要等上游补全**，赛前记得 `fetch-europa --online` 试一次。
7. **欧战没有历史赔率**，`backtest --leagues UCL/UEL/CONF/EUR` 只能算准确率，算不了 ROI。
8. **荷甲、希超、挪超等不在数据源**（`fetch-tier1` 只入库了 5 大联赛），这些联赛的欧战球队
   （如奈梅亨、克里特、利勒斯特）没有参数，相关场次会被跳过。
9. **无国内数据、只有欧战数据的球队参数偏乐观**（如波兹南：仅靠欧协联小组赛样本，
   对手偏弱会抬高强度估值），此类场次的价值判断要打折看待。
