param(
    [switch]$SkipFetch,
    [switch]$NoPush,
    [string]$Message = ""
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not $SkipFetch) {
    Write-Host "==> 抓取竞彩快照" -ForegroundColor Cyan
    python -m src.cli fetch-jingcai --online
    if ($LASTEXITCODE -ne 0) { throw "fetch-jingcai 失败" }
}

Write-Host "==> 预测" -ForegroundColor Cyan
python -m src.cli predict
if ($LASTEXITCODE -ne 0) { throw "predict 失败" }

Write-Host "==> 候选筛选" -ForegroundColor Cyan
python -m src.cli recommend
if ($LASTEXITCODE -ne 0) { throw "recommend 失败" }

Write-Host "==> 导出站点数据" -ForegroundColor Cyan
python scripts/export_web.py --check
if ($LASTEXITCODE -ne 0) { throw "export_web 失败" }

Write-Host "==> 提交" -ForegroundColor Cyan
git add web/public/data reports
$pending = git diff --cached --name-only
if (-not $pending) {
    Write-Host "没有数据变更，跳过提交。" -ForegroundColor Yellow
    exit 0
}
$msg = if ($Message) { $Message } else { "data: pre-match $(Get-Date -Format 'yyyy-MM-dd HH:mm')" }
git commit -m $msg
if ($LASTEXITCODE -ne 0) { throw "git commit 失败" }

if (-not $NoPush) {
    Write-Host "==> 推送（触发 GitHub Pages）" -ForegroundColor Cyan
    git push
    if ($LASTEXITCODE -ne 0) { throw "git push 失败" }
}
Write-Host "完成。" -ForegroundColor Green
