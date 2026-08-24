# ============================================================
# 数据库恢复导入脚本 (Windows PowerShell)
# 用法: .\scripts\restore_db.ps1 -BackupFile backups\latest_backup.sql
# 作用: 将备份的 SQL 文件导入到新的 PostgreSQL 数据库中
# ============================================================

param(
    [Parameter(Mandatory=$true)]
    [string]$BackupFile,
    [string]$ContainerName = "antibody-postgres",
    [string]$DbUser = "antibody",
    [string]$DbName = "antibody_map"
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $PSScriptRoot
$BackupPath = Resolve-Path $BackupFile

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
Write-Color "  数据库备份恢复" "Cyan"
Write-Color "============================================" "Cyan"
Write-Host ""

# 检查备份文件
if (-not (Test-Path $BackupPath)) {
    Write-Color "错误: 备份文件不存在: $BackupPath" "Red"
    exit 1
}
$fileSize = (Get-Item $BackupPath).Length / 1KB
Write-Color "备份文件: $BackupPath" "Green"
Write-Color "文件大小: $([math]::Round($fileSize, 2)) KB" "Green"
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

# 警告
Write-Color "" "Yellow"
Write-Color "警告: 此操作将覆盖数据库 $DbName 中的所有现有数据！" "Yellow"
Write-Color "" "Yellow"
$confirm = Read-Host "确认恢复? 输入 YES 继续"
if ($confirm -ne "YES") {
    Write-Color "已取消" "Yellow"
    exit 0
}

# 先断开所有连接并重建数据库
Write-Color "" "Yellow"
Write-Color "正在清理并重建数据库..." "Yellow"
docker exec -e PGPASSWORD=$DbPassword $ContainerName psql -U $DbUser -d postgres -c "DROP DATABASE IF EXISTS $DbName;" 2>&1 | Out-Null
docker exec -e PGPASSWORD=$DbPassword $ContainerName psql -U $DbUser -d postgres -c "CREATE DATABASE $DbName OWNER $DbUser;" 2>&1 | Out-Null
Write-Color "数据库已重建" "Green"

# 导入备份
Write-Color "正在导入备份，请稍候..." "Yellow"
Get-Content $BackupPath | docker exec -i -e PGPASSWORD=$DbPassword $ContainerName psql -U $DbUser -d $DbName

if ($LASTEXITCODE -eq 0) {
    Write-Color "" "Green"
    Write-Color "============================================" "Green"
    Write-Color "  数据库恢复成功！" "Green"
    Write-Color "============================================" "Green"
} else {
    Write-Color "" "Red"
    Write-Color "错误: 数据库恢复失败，退出码: $LASTEXITCODE" "Red"
    exit 1
}
