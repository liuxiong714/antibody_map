# ============================================================
# 数据库导出脚本 (Windows PowerShell)
# 用法: .\scripts\backup_db.ps1
# 作用: 将 PostgreSQL 中的数据导出为 SQL 文件，便于迁移到新电脑
# ============================================================

param(
    [string]$OutputDir = "backups",
    [string]$ContainerName = "antibody-postgres",
    [string]$DbUser = "antibody",
    [string]$DbName = "antibody_map"
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $PSScriptRoot
$FullOutputDir = Join-Path $ProjectDir $OutputDir

function Write-Color($text, $color = "White") {
    Write-Host $text -ForegroundColor $color
}

# 从 .env 读取数据库密码（禁止硬编码口令）
$envFile = Join-Path $ProjectDir ".env"
if (-not (Test-Path $envFile)) {
    Write-Color "错误: 未找到 $envFile，请先在项目根目录配置 .env（POSTGRES_PASSWORD）" "Red"
    exit 1
}
$DbPassword = (Get-Content $envFile | Where-Object { $_ -match '^\s*POSTGRES_PASSWORD=' } | Select-Object -First 1) -replace '^\s*POSTGRES_PASSWORD=', ''
$DbPassword = $DbPassword.Trim('"', "'", ' ')
if (-not $DbPassword) {
    Write-Color "错误: .env 中未配置 POSTGRES_PASSWORD" "Red"
    exit 1
}

Write-Color "============================================" "Cyan"
Write-Color "  数据库备份导出" "Cyan"
Write-Color "============================================" "Cyan"
Write-Host ""

# 检查 Docker
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Color "错误: 未检测到 Docker，请先安装 Docker Desktop" "Red"
    exit 1
}

# 检查容器是否运行
$container = docker ps --filter "name=$ContainerName" --format "{{.Names}}" 2>&1
if (-not $container -or $container -ne $ContainerName) {
    Write-Color "错误: 容器 '$ContainerName' 未运行，请先启动服务 (start.ps1)" "Red"
    exit 1
}
Write-Color "容器运行中: $ContainerName" "Green"

# 创建输出目录
if (-not (Test-Path $FullOutputDir)) {
    New-Item -ItemType Directory -Path $FullOutputDir | Out-Null
}

# 生成文件名（带时间戳）
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$dumpFile = "antibody_map_backup_$timestamp.sql"
$dumpPath = Join-Path $FullOutputDir $dumpFile

# 在容器内执行 pg_dump，输出到本地文件
Write-Color "正在导出数据库，请稍候..." "Yellow"
docker exec -e PGPASSWORD=$DbPassword $ContainerName pg_dump -U $DbUser -d $DbName --no-owner --no-privileges > $dumpPath

# 检查结果
if (Test-Path $dumpPath) {
    $size = (Get-Item $dumpPath).Length / 1KB
    if ($size -gt 1) {
        Write-Color "导出成功！" "Green"
        Write-Color "  文件: $dumpPath" "Green"
        Write-Color "  大小: $([math]::Round($size, 2)) KB" "Green"

        # 同时创建一份 latest 软链接/副本
        $latestPath = Join-Path $FullOutputDir "latest_backup.sql"
        Copy-Item $dumpPath $latestPath -Force
        Write-Color "  副本: $latestPath" "Green"
    } else {
        Write-Color "警告: 导出文件太小 ($([math]::Round($size, 2)) KB)，可能有问题" "Yellow"
    }
} else {
    Write-Color "错误: 导出失败，未找到输出文件" "Red"
    exit 1
}

Write-Host ""
Write-Color "提示: 请妥善保存备份文件，新电脑上使用 restore_db.ps1 恢复" "Yellow"
