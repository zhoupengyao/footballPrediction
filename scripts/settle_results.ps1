param(
    [string]$Date = "",
    [switch]$SkipFetch,
    [switch]$SkipResultsFetch,
    [switch]$NoPush,
    [string]$Message = ""
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not $Date) {
    $latest = Get-ChildItem reports\predict_*.json | Sort-Object Name | Select-Object -Last 1
    if (-not $latest) { throw "没有预测报告，请先运行 predict" }
    $Date = $latest.BaseName -replace "^predict_", ""
    Write-Host "未指定 -Date，使用最新预测日期：$Date" -ForegroundColor Yellow
}

if (-not $SkipResultsFetch) {
    Write-Host "==> 抓取竞彩官方赛果" -ForegroundColor Cyan
    python scripts/fetch_results.py --date $Date
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "竞彩赛果抓取失败，继续使用本地/手动赛果。"
    }
}

if (-not $SkipFetch) {
    foreach ($cmd in @("fetch-understat", "fetch-ucl", "fetch-europa", "fetch-apifootball")) {
        Write-Host "==> 更新赛果：$cmd" -ForegroundColor Cyan
        python -m src.cli $cmd --online
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "$cmd 失败（可能是网络/额度/密钥问题），继续。"
        }
    }
}

Write-Host "==> 对账（手动赛果 + 本地自动赛果）" -ForegroundColor Cyan
python -m src.cli reconcile --date $Date --manual data/manual_results/results.csv
if ($LASTEXITCODE -ne 0) { throw "reconcile 失败" }

Write-Host "==> 导出站点数据" -ForegroundColor Cyan
python scripts/export_web.py --check
if ($LASTEXITCODE -ne 0) { throw "export_web 失败" }

Write-Host "==> 提交" -ForegroundColor Cyan
git add data/manual_results web/public/data reports
$pending = git diff --cached --name-only
if (-not $pending) {
    Write-Host "没有数据变更，跳过提交。" -ForegroundColor Yellow
    exit 0
}
$msg = if ($Message) { $Message } else { "results: $Date" }
git commit -m $msg
if ($LASTEXITCODE -ne 0) { throw "git commit 失败" }

if (-not $NoPush) {
    Write-Host "==> 推送（触发 GitHub Pages）" -ForegroundColor Cyan
    git push
    if ($LASTEXITCODE -ne 0) { throw "git push 失败" }
}
Write-Host "完成。" -ForegroundColor Green
