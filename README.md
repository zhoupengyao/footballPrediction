# 竞彩足球预测管线（jingcai-predict）

基于 **Dixon-Coles 泊松模型 + Elo + LightGBM 特征模型** 的中国竞彩足球预测系统。
核心目标：用统计模型算出每场比赛的胜平负/比分/半全场等概率，与竞彩官方赔率
比对，找出「模型认为被低估」的价值投注选项，并用分数 Kelly 给出仓位建议。

> ⚠️ **现实预期**：竞彩综合返奖率约 73%（市场抽水 27%）。历史回测 ROI 约 −7.6%，
> 说明模型在真实赔率口径下尚未稳定跑赢市场。本系统定位是**决策辅助 / 研究学习**，
> 不保证盈利。请用 `reconcile` 命令积累投注台账、用数据说话。

## Web 面板（静态站）

仓库里包含一个 React + TypeScript + ECharts 的静态数据面板：

- 今日/历史比赛：HAD、让球、比分、总进球、半全场预测 + 实际结果 + 命中
- 命中分析：概率分箱校准、命中比分概率、覆盖漏斗、混淆矩阵、价值注 edge/赔率分析
- 纸面候选与台账：三档风险、Kelly 仓位、累计 ROI
- 回测与模型：校准曲线、资金曲线、分联赛指标
- 早盘/临场赔率对比

本地生成数据并预览：

```powershell
python scripts/export_web.py --check
cd web
npm install
npm run dev
```

部署与每日更新见 [`docs/web.md`](docs/web.md)。核心流程：

```text
本地 fetch/predict/reconcile → export_web.py → git push → GitHub Pages
```

> GitHub Pages 只托管静态文件；Python 模型和竞彩抓取仍在本机运行。

## 环境

- Windows + PowerShell
- Python 3.10+，依赖见 `requirements.txt`（或 `pyproject.toml`）

```powershell
cd D:\python_学习区\football
$env:PYTHONIOENCODING="utf-8"      # 避免终端中文乱码
pip install -r requirements.txt
python -m src.cli status           # 检查环境与数据状态
```

## 每日流程（比赛日）

```powershell
# 1) 抓取当天竞彩场次与赔率（快照带时间戳，可多次抓取对比早盘/临场）
python -m src.cli fetch-jingcai --online

# 2) 预测（只跑第一期，自动跳过已开赛）
python -m src.cli predict

# 3) 次日对账（写投注台账，统计命中率/ROI）
python -m src.cli reconcile

# 4) 候选筛选（可选：从预测里筛可靠价值注，分级 + 仓位；纸面，不构成盈利建议）
python -m src.cli recommend --bankroll 1000
```

结果在 `reports/predict_YYYYMMDD.{md,json}`，对账在 `reports/reconcile_YYYYMMDD.{md,json}`，
台账在 `data/processed/bet_ledger.parquet`。

## 命令一览

| 命令 | 说明 |
|---|---|
| `status` | 检查环境与数据状态 |
| `fetch-tier1 --online` | 下载/解析 football-data 镜像（5 大联赛） |
| `fetch-tier1-gh --online` | 从 jokecamp 镜像扩联赛覆盖（荷/比/葡/土/希/苏等） |
| `fetch-understat --online` | 下载 understat（比分+xG，补最新赛季） |
| `fetch-apifootball --online` | 下载 API-Football 赛果（巴甲/挪超/瑞超/芬超等） |
| `fetch-ucl/fetch-europa --online` | 下载欧冠/欧罗巴/欧协联（openfootball） |
| `fetch-jingcai --online` | 抓取竞彩开售场次与赔率快照 |
| `fetch-odds --online --via proxy` | 下载历史赔率（回测 ROI 用） |
| `train [--with-ml] [--shrinkage N]` | 训练 Dixon-Coles(+半全场+Elo[+LightGBM]) |
| `predict [--edge/--blend/--elo/--ml-weight]` | 预测并产出价值报告 |
| `recommend [--risk/--bankroll]` | 候选筛选（纸面）：筛可靠价值注，分级+仓位 |
| `backtest [--no-odds] [--shrinkage N]` | Walk-forward 回测 |
| `reconcile` | 对账：预测 vs 实际比分，写台账 |
| `doctor` | 诊断队名匹配，列出未匹配球队与候选 |
| `pipeline --online` | 一键 fetch → train → predict |

详见 `docs/daily_workflow.md`。

## 模型与预测链

预测时四层混合（每层权重均可调）：

```
Dixon-Coles  →  Elo（elo_blend_weight=0.8）→  LightGBM（ml_blend_weight=0.8）→  去水市场概率（blend_weight=0.6）
```

- **Dixon-Coles**（自研，解析梯度）：`λ_home = μ·α_home·β_away·γ`，含低比分 τ 修正、
  时间衰减、**小样本收缩**（empirical Bayes，`training.shrinkage_prior=8`）。
- **Elo**：从零实现的 Elo/Glicko，作为第二意见。
- **LightGBM**：13 维滚动特征（Elo 差、近 8 场进/失/积分、休息天数、近 8 场 xG），
  **无泄漏**逐场构造，作为第三意见（`train --with-ml` 启用）。
- 价值判断在混合后概率上进行（edge = 模型概率 − 去水隐含概率），带 `min_odds`/`max_edge` 过滤。

## 目录结构

```
config/          settings.yaml（参数）、leagues.yaml（联赛/数据源/队名映射）
src/
  cli.py         命令行入口
  pipeline.py    编排：数据 → 训练 → 预测 → 报告
  config.py      配置加载
  ingest/        数据接入（footballdata/jokecamp/understat/竞彩/openfootball/赔率）
  models/        dixon_coles、halffull、ml_model、persistence
  features/      elo、features（滚动特征）
  jingcai/       payouts（玩法概率映射）、team_names（队名匹配）
  backtest/      walk-forward 引擎 + 指标（含 ECE）
  reconcile.py   对账
data/            raw / processed / odds 快照 / models（gitignore 忽略）
reports/         预测与回测报告（md + json 双写）
docs/            操作手册
tests/           测试（`python tests/test_X.py` 直接运行）
scripts/         探索/诊断脚本（probe_*、diag_*、validate_*）
```

## 测试

```powershell
python tests/test_backtest.py
python tests/test_cli.py
python tests/test_analysis.py
python tests/test_europa.py
python tests/test_export_web.py
python tests/test_jingcai_results.py
python tests/test_jingcai_snapshot.py
python tests/test_ml.py
python tests/test_model_enhance.py
python tests/test_reconcile.py
python tests/test_ucl.py
python tests/test_value_filter.py
```

（每个测试文件都有 `main()`，直接 `python tests/test_X.py` 运行，不依赖 pytest。）

## 已知限制

- 数据覆盖：
  - 五大联赛 + understat 补最新赛季；
  - 欧冠/欧罗巴/欧协联（openfootball，2021-2024 四季）；
  - 挪超/瑞超/芬超/巴甲（API-Football，Free 计划仅 2022-2024 三季）。
  - 更多联赛可用 `fetch-tier1-gh`（荷/比/葡/土/希/苏，需 `doctor` 补别名）或
    `fetch-apifootball`（tier2，需在 `.env` 配 `API_SPORTS_KEY`）扩。
- 欧战（欧冠/欧罗巴/欧协联）与 tier2 联赛无历史赔率，只能回测准确率、算不了 ROI。
- 早盘 edge 易误报，请以临场前 1–2 小时的最新快照为准。

详见 `docs/daily_workflow.md` 的「已知限制」与 `docs/odds_gap.md`。
