# sync-docs.ps1 — 把本地 docs/ 和 backend/app/ 同步进 backend + worker 容器
# 用于：生产部署（GPU 服务器，无 docker-compose.dev.yml volume）改了 changelog 或 app 代码后
# 不想重建镜像，只想把最新文件 cp 进容器然后 restart。
#
# 用法 (PowerShell):
#   .\scripts\sync-docs.ps1                    # 同步全部 (docs + backend/app)
#   .\scripts\sync-docs.ps1 -Only docs        # 只同步 docs
#   .\scripts\sync-docs.ps1 -Restart          # 同步后自动 restart backend + worker
#
# 前提: docker compose -f docker-compose.yml -f docker-compose.reuse.yml up -d 已在运行

param(
    [ValidateSet('all', 'docs', 'app')]
    [string]$Only = 'all',

    [switch]$Restart
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot\..

$composeFiles = '-f', 'docker-compose.yml', '-f', 'docker-compose.reuse.yml'
$containers = @('backend', 'worker')

function Invoke-Sync($from, $to) {
    foreach ($c in $containers) {
        Write-Host "  -> ${c}: ${from} -> ${to}" -ForegroundColor Cyan
        docker compose @composeFiles cp $from "${c}:${to}" 2>&1 | Out-Null
    }
}

if ($Only -in @('all', 'docs')) {
    Write-Host "==> 同步 docs/" -ForegroundColor Green
    Invoke-Sync 'docs' '/app/docs'
}

if ($Only -in @('all', 'app')) {
    Write-Host "==> 同步 backend/app/" -ForegroundColor Green
    Invoke-Sync 'backend/app' '/app/backend/app'
}

if ($Restart) {
    Write-Host "==> 重启容器" -ForegroundColor Green
    docker compose @composeFiles restart backend worker
}

Write-Host "`n完成。version 刷新说明：backend 容器 import config.py 后 TTL 30s，" +
    "所以 changelog.md 更新后最多等 30s /system/info 就会看到新版本号。" -ForegroundColor Yellow
