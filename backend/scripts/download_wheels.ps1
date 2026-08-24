# 下载 Linux 兼容 wheel 包到本地仓库，用于后端离线构建
# 用法:
#   .\backend\scripts\download_wheels.ps1              # 仅下载主依赖
#   .\backend\scripts\download_wheels.ps1 -WithMineru   # 含 MinerU (torch ~2GB)
#
# 前置条件: Docker Desktop 运行中，docker 命令可用
# 下载后: 执行 docker compose build 即可离线安装

param(
    [switch]$WithMineru
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path "$PSScriptRoot\..\.."
$WheelDir = "$ProjectRoot\backend\wheels"
New-Item -ItemType Directory -Force -Path $WheelDir | Out-Null

Write-Host "=== 下载 requirements.txt wheels ==="
docker run --rm -v "${ProjectRoot}\backend:/backend" python:3.11-slim `
    pip download --no-cache-dir -r /backend/requirements.txt --dest /backend/wheels/

if ($LASTEXITCODE -ne 0) {
    Write-Warning "部分 wheel 下载失败，可重试"
}

if ($WithMineru) {
    Write-Host "=== 下载 requirements-mineru.txt wheels（含 torch ~2GB）==="
    docker run --rm -v "${ProjectRoot}\backend:/backend" python:3.11-slim `
        pip download --no-cache-dir -r /backend/requirements-mineru.txt --dest /backend/wheels/

    if ($LASTEXITCODE -ne 0) {
        Write-Warning "MinerU 部分 wheel 下载失败"
    }
}

$count = (Get-ChildItem "$WheelDir\*.whl" -ErrorAction SilentlyContinue).Count
$size = "{0:N2}" -f ((Get-ChildItem "$WheelDir\*.whl" -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum / 1GB)
Write-Host "=== 完成 ==="
Write-Host "共下载 $count 个 wheel 文件，总大小约 $size GB"
Write-Host "目录: $WheelDir"
Write-Host "现在可以执行 docker compose build 实现离线构建"