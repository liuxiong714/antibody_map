# sync-docs.ps1 — 把本地 docs/ 和 backend/app/ 同步进 backend + worker 容器
# 用于：生产部署（GPU 服务器，无 docker-compose.dev.yml volume）改了 changelog 或 app 代码后
# 不想重建镜像，只想把最新文件 cp 进容器然后 restart。
#
# 用法 (PowerShell):
#   .\scripts\sync-docs.ps1                        # 同步全部，用标准 reuse compose（本机开发）
#   .\scripts\sync-docs.ps1 -Only docs            # 只同步 docs
#   .\scripts\sync-docs.ps1 -Restart               # 同步后自动 restart backend + worker
#   .\scripts\sync-docs.ps1 -Dev                   # 用 dev overlay (docker-compose.dev.yml)
#   .\scripts\sync-docs.ps1 -Prod                  # 纯 base compose（GPU 新克隆的生产服务器）
#   .\scripts\sync-docs.ps1 -ExtraOverlays "-f docker-compose.gpu.yml"  # 追加任意 overlay

param(
    [ValidateSet('all', 'docs', 'app')]
    [string]$Only = 'all',

    [switch]$Restart,

    [switch]$Dev,

    [switch]$Prod,

    [string]$ExtraOverlays = ''
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot\..

# ---- 组装 compose 文件列表 ----
$files = @('-f', 'docker-compose.yml')

if ($Dev) {
    # 开发模式：带 dev volume overlay（如果有 reuse 也带上）
    $files += '-f', 'docker-compose.reuse.yml'
    if (Test-Path 'docker-compose.dev.yml') {
        $files += '-f', 'docker-compose.dev.yml'
    } else {
        Write-Warning 'docker-compose.dev.yml 不存在，跳过 dev overlay'
    }
} elseif ($Prod) {
    # 纯 base compose（GPU 新克隆的服务器无 reuse）
    Write-Host '使用纯 base compose（生产模式）' -ForegroundColor Yellow
} else {
    # 默认：本机开发，带 reuse（复用数据卷）
    if (Test-Path 'docker-compose.reuse.yml') {
        $files += '-f', 'docker-compose.reuse.yml'
    }
}

# 追加用户指定的额外 overlay（例如 GPU）
if ($ExtraOverlays) {
    $parts = $ExtraOverlays -split '\s+' | Where-Object { $_ }
    $files += $parts
}

$composeFiles = $files
$containers = @('backend', 'worker')
Write-Host "compose 文件: $($composeFiles -join ' ')" -ForegroundColor DarkGray

function Invoke-Sync($from, $to) {
    foreach ($c in $containers) {
        Write-Host "  -> ${c}: ${from} -> ${to}" -ForegroundColor Cyan
        docker compose @composeFiles cp $from "${c}:${to}" 2>&1 | Out-Null
    }
}

if ($Only -in @('all', 'docs')) {
    Write-Host '==> 同步 docs/' -ForegroundColor Green
    Invoke-Sync 'docs' '/app/docs'
}

if ($Only -in @('all', 'app')) {
    Write-Host '==> 同步 backend/app/' -ForegroundColor Green
    Invoke-Sync 'backend/app' '/app/backend/app'
}

if ($Restart) {
    Write-Host '==> 重启容器' -ForegroundColor Green
    docker compose @composeFiles restart backend worker
}

Write-Host "`n完成。version 刷新说明：backend 容器 import config.py 后 TTL 30s，" +
    '所以 changelog.md 更新后最多等 30s /system/info 就会看到新版本号。' -ForegroundColor Yellow
