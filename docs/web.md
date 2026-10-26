# Web 面板维护手册

> 静态站：预测、对账、导出在本地完成，`git push` 后由 GitHub Pages 发布。
> 页面不连接数据库，也不在请求时运行 Python 模型。

## 1. 架构

```text
本地 Windows
  fetch-jingcai → predict → recommend
        │
        ├─ reports/predict_*.json
        ├─ reports/recommend_*.json
        ├─ reports/reconcile_*.json
        └─ data/manual_results/results.csv
        │
        ▼
  python scripts/export_web.py --check
        │
        ▼
  web/public/data/*.json        （提交到仓库）
        │
        ▼
  git push  →  GitHub Actions  →  npm build  →  GitHub Pages
```

关键原则：

- **只认赛前预测**：`predict` 会把每次报告归档到 `reports/archive/`，导出器优先使用开赛前最后一次存档。
- **赛后补跑不计入命中率**：报告生成时间晚于开赛时间的场次会标记 `post_kickoff`，只展示不统计。
- **没有结果就显示待补**：不会用预测值或猜测值填充实际比分。
- **单一写入者**：本地 push 数据后，不要再让 GitHub Actions 定时改数据，避免冲突。

## 2. 数据文件

| 文件 | 内容 |
|---|---|
| `web/public/data/manifest.json` | 站点元信息、日期索引、联赛、数据源、免责声明 |
| `web/public/data/history/index.json` | 每日场次/命中率索引 |
| `web/public/data/history/YYYY-MM-DD.json` | 每场比赛的预测 + 实际结果 + 五种玩法命中 |
| `web/public/data/recommendations/YYYY-MM-DD.json` | 三档风险候选/观察清单 |
| `web/public/data/performance.json` | 累计命中率、价值注 ROI、分联赛、台账 |
| `web/public/data/backtests/index.json` | 回测索引 |
| `web/public/data/backtests/{id}.json` | 回测汇总 + 校准 + 资金曲线 |
| `web/public/data/odds-diff/YYYY-MM-DD.json` | 同日多份快照的赔率变化 |

导出器会做三件事：

1. 中文键转成 `home/draw/away`，前端不用理解竞彩字段；
2. `NaN/Infinity` 全部转 `null`，避免 `JSON.parse` 失败；
3. 回测只保留汇总和资金曲线，不把几万条逐场数组发给浏览器。

## 3. 本地开发

```powershell
cd "D:\python_学习区\football"

# 生成/更新站点数据
$env:PYTHONIOENCODING="utf-8"
python scripts/export_web.py --check

# 前端
cd web
npm install        # 首次
npm run dev        # http://localhost:5173
npm run build      # 产物在 web/dist
npm run preview    # 预览 build 结果
```

Vite 会把 `web/public/data` 原样带到 `dist/data`，所以本地和线上读取路径一致。

## 4. 每日更新

### 赛前

```powershell
python -m src.cli fetch-jingcai --online
python -m src.cli predict
python -m src.cli recommend
python scripts/export_web.py --check

git add web/public/data reports
git commit -m "data: pre-match 2026-10-27"
git push
```

或使用脚本：

```powershell
.\scripts\pre_match.ps1
.\scripts\pre_match.ps1 -SkipFetch -NoPush
```

### 赛后 / 次日

1. 编辑 `data/manual_results/results.csv`，填全场 + 半场比分；
2. 对账并导出：

```powershell
python -m src.cli reconcile --date 20261027 --manual data/manual_results/results.csv
python scripts/export_web.py --check

git add data/manual_results web/public/data reports
git commit -m "results: 2026-10-27"
git push
```

或：

```powershell
.\scripts\settle_results.ps1 -Date 20261027
```

自动赛果能覆盖的联赛，也可以先跑：

```powershell
python -m src.cli fetch-understat --online
python -m src.cli fetch-ucl --online
python -m src.cli fetch-europa --online
# 需要 API_SPORTS_KEY，注意每日 100 次额度
python -m src.cli fetch-apifootball --online
```

## 5. 手动赛果 CSV

`data/manual_results/results.csv`：

```csv
date,match_num,league,home_cn,away_cn,ft_home,ft_away,ht_home,ht_away
2026-10-27,周一001,英超,曼城,阿森纳,2,1,1,0
```

- `ft_home/ft_away`：HAD、HHAD、比分、总进球。
- `ht_home/ht_away`：半全场；缺失时半全场显示“无法结算”，不判负。
- 唯一键：`date + match_num`，不要只用 `match_num`（每周都会重复）。
- 只有 `predicted` 场次进入命中率；被跳过的比赛即使有赛果也不统计。

## 6. GitHub Pages 部署

1. 安装 Git（本机已装 2.56）：
   ```powershell
   winget install --id Git.Git -e
   ```
   如果官方源被墙，可用国内镜像下载 Git for Windows 安装包。
2. 初始化并提交（本仓库已完成）：
   ```powershell
   git init -b main
   git add .
   git commit -m "feat: web dashboard"
   ```
3. 在 GitHub 创建**公开仓库**，例如 `jingcai-predict`，然后：
   ```powershell
   git remote add origin https://github.com/<用户名>/jingcai-predict.git
   git push -u origin main
   ```
4. 仓库 **Settings → Pages → Source** 选择 **GitHub Actions**。
5. push 后 workflow `Deploy web to GitHub Pages` 自动构建，地址：
   ```text
   https://<用户名>.github.io/jingcai-predict/
   ```
6. 如需自定义域名：Pages → Custom domain，并在 DNS 添加 CNAME。

Workflow 会自动处理：

- 项目站点子路径：`VITE_BASE=/<repo>/`；
- 用户站点 `<user>.github.io`：`VITE_BASE=/`；
- `404.html`：SPA 深链接刷新不 404；
- `.nojekyll`：避免 Jekyll 忽略 `_` 开头的资源。

## 7. 常见问题

**页面空白 / 数据加载失败**
- 检查 `web/public/data/manifest.json` 是否存在；
- 检查浏览器控制台是否 404；
- 本地执行 `python scripts/export_web.py --check`；
- 如果刚 push，等待 Pages 部署完成并强制刷新（CDN 有缓存）。

**数据更新了但页面还是旧的**
- Vite 请求 manifest 时带 `?t=` 时间戳，其他 JSON 带 `?v=generated_at`；通常刷新即可；
- GitHub Pages CDN 可能缓存几分钟；
- 确认 workflow 成功，而不是只 push 了代码。

**命中率一直是 0 / 没有样本**
- 先确认赛果已录入并运行 `reconcile`；
- 检查 `reconcile_YYYYMMDD.json` 里 `stats.resolved` 是否大于 0；
- 检查预测报告生成时间是否早于开赛时间；赛后补跑会被排除。

**半全场无法结算**
- 手动 CSV 缺 `ht_home/ht_away`；
- 自动数据源里 understat 没有半场比分，需手动补。

**GitHub Actions 构建失败**
- 看 `Validate web and exporter` 和 `Deploy web` 的日志；
- 常见原因：`package-lock.json` 未提交、Node 版本过低、Vite base 不对；
- 本机先跑 `npm ci && npm run build` 复现。

## 8. 以后接 FastAPI

当前前端只依赖 `web/public/data` 的 schema。后续加 `api/` 时：

- FastAPI 读取同一份 JSON（或从 GitHub Raw 拉取并缓存）；
- 前端增加 `VITE_DATA_MODE=static|live`，页面组件不改；
- 管理端手动触发预测需要 Token 保护和任务队列，免费实例不适合长任务。

## 9. 安全与合规

- `.env` 已被 `.gitignore` 排除，API key 不要提交；
- `data/raw`、`data/processed`、`data/odds`、`*.joblib`、`reports/backtest_*.json` 不进入仓库；
- 公开仓库前确认没有个人信息或密钥；
- 页面必须保留免责声明：研究用途、不构成投注建议、历史 ROI 为负。
