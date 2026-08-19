# ============================================================
# 一键提交并推送到 GitHub（Windows PowerShell）
#
# 用法：
#   .\scripts\git_push.ps1                                  # 交互式输入提交信息
#   .\scripts\git_push.ps1 -Message "v1.10.1: 提取稳定性增强"  # 直接指定提交信息
#   .\scripts\git_push.ps1 -NoPush                           # 只提交，不推送
# ============================================================
param(
    [string]$Message = "",
    [switch]$NoPush
)

$ErrorActionPreference = "Stop"

# 回到仓库根目录（脚本位于 scripts/ 子目录）
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "==== 1/4 查看当前变更 ====" -ForegroundColor Cyan
git status --short
git --no-pager diff --stat
Write-Host ""

$hasChanges = (git status --porcelain | Measure-Object -Line).Lines
if ($hasChanges -eq 0) {
    Write-Host "没有待提交的变更。" -ForegroundColor Yellow
    exit 0
}

Write-Host "==== 2/4 暂存全部变更（按 .gitignore 忽略规则） ====" -ForegroundColor Cyan
git add -A
git status --short
Write-Host ""

if ([string]::IsNullOrWhiteSpace($Message)) {
    Write-Host "==== 输入提交信息（直接回车使用默认值） ====" -ForegroundColor Cyan
    $default = "v1.10.1: 提取稳定性增强 + MinerU 子进程隔离 + 模型缓存本地化"
    $input = Read-Host "提交信息"
    $Message = if ([string]::IsNullOrWhiteSpace($input)) { $default } else { $input }
    Write-Host ""
}

Write-Host "==== 3/4 提交 ====" -ForegroundColor Cyan
git commit -m $Message
if ($LASTEXITCODE -ne 0) {
    Write-Host "提交失败，已中止，不会推送。" -ForegroundColor Red
    exit 1
}

if ($NoPush) {
    Write-Host "`n已提交，跳过推送。" -ForegroundColor Green
    exit 0
}

Write-Host "`n==== 4/4 推送到 GitHub ====" -ForegroundColor Cyan
$branch = git branch --show-current
if ([string]::IsNullOrWhiteSpace($branch)) { $branch = "main" }
git push origin $branch
if ($LASTEXITCODE -ne 0) {
    Write-Host "`n推送失败，请检查网络/GitHub 凭据（可在 Windows 凭据管理器配置）。" -ForegroundColor Red
    exit 1
}

Write-Host "`n完成！已提交并推送到 origin/$branch。" -ForegroundColor Green
