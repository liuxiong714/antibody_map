# ============================================================
# Antibody Map 一键启动脚本 (Windows PowerShell)
# 用法: 右键 -> 使用 PowerShell 运行，或在终端执行 .\start.ps1
# ============================================================

$ErrorActionPreference = "Stop"

# ---- 配置 ----
$BackendPort = 8080
$FrontendPort = 3000
$FrontendUrl = "http://localhost:$FrontendPort"

# 项目根目录（脚本所在目录）
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $ProjectDir "backend"
$FrontendDir = Join-Path $ProjectDir "frontend"
$EnvFile = Join-Path $ProjectDir ".env"
$EnvExample = Join-Path $ProjectDir ".env.example"

# 颜色函数
function Write-Color($text, $color = "White") {
    Write-Host $text -ForegroundColor $color
}

Write-Color "============================================" "Cyan"
Write-Color "  Antibody Map 一键启动 (Windows)" "Cyan"
Write-Color "============================================" "Cyan"
Write-Host ""

# ---- 1. 检查已有服务 ----
Write-Color "[1/6] 检查已有服务..." "Yellow"

function Stop-PortProcess($port) {
    $procs = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
             Select-Object -ExpandProperty OwningProcess -Unique
    if ($procs) {
        foreach ($pid in $procs) {
            try {
                $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
                if ($proc) {
                    Write-Color "  关闭端口 $port 上的进程: $($proc.ProcessName) (PID $pid)" "DarkYellow"
                    Stop-Process -Id $pid -Force
                }
            } catch { }
        }
        Start-Sleep -Seconds 1
    }
}

Stop-PortProcess $BackendPort
Stop-PortProcess $FrontendPort

# ---- 2. 检查环境依赖 ----
Write-Color "[2/6] 检查环境依赖..." "Yellow"

# Python
try {
    $pythonVer = python --version 2>&1
    Write-Color "  Python: $pythonVer" "Green"
} catch {
    Write-Color "错误: 未找到 Python，请先安装 Python 3.10+" "Red"
    Write-Host "  下载: https://www.python.org/downloads/"
    exit 1
}

# Node.js / npm
try {
    $nodeVer = node --version 2>&1
    $npmVer = npm --version 2>&1
    Write-Color "  Node: $nodeVer" "Green"
    Write-Color "  npm:  $npmVer" "Green"
} catch {
    Write-Color "错误: 未找到 Node.js，请先安装 Node.js 20+" "Red"
    Write-Host "  下载: https://nodejs.org/"
    exit 1
}

# Docker
try {
    $dockerVer = docker --version 2>&1
    Write-Color "  Docker: $dockerVer" "Green"
} catch {
    Write-Color "警告: 未检测到 Docker，PostgreSQL/Redis/MinIO 将无法启动" "Yellow"
    Write-Host "  下载 Docker Desktop: https://www.docker.com/products/docker-desktop/"
    Write-Host "  如已有外部数据库，请忽略此警告并确保 .env 配置正确"
}

# ---- 3. 环境变量配置 ----
Write-Color "[3/6] 检查环境变量配置..." "Yellow"

if (-not (Test-Path $EnvFile)) {
    if (Test-Path $EnvExample) {
        Copy-Item $EnvExample $EnvFile
        Write-Color "  已从 .env.example 复制生成 .env" "Green"
        Write-Color "  请编辑 .env 文件，填入 LLM_API_KEY 等必要配置" "Yellow"
    } else {
        Write-Color "警告: 未找到 .env 和 .env.example，使用默认配置" "Yellow"
    }
} else {
    Write-Color "  .env 已存在" "Green"
}

# ---- 4. 安装依赖 ----
Write-Color "[4/6] 检查依赖安装..." "Yellow"

# 前端依赖
if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
    Write-Color "  安装前端依赖，请稍候..." "DarkYellow"
    Push-Location $FrontendDir
    npm install
    Pop-Location
    Write-Color "  前端依赖安装完成" "Green"
} else {
    Write-Color "  前端依赖已安装" "Green"
}

# 后端依赖（简单检查：尝试 import fastapi）
Push-Location $BackendDir
try {
    python -c "import fastapi" 2>&1 | Out-Null
    Write-Color "  后端依赖已安装" "Green"
} catch {
    Write-Color "  安装后端依赖，请稍候..." "DarkYellow"
    python -m pip install -r requirements.txt
    Write-Color "  后端依赖安装完成" "Green"
}
Pop-Location

# ---- 5. 启动服务 ----
Write-Color "[5/6] 启动服务..." "Yellow"

# 启动 Docker Compose（如果有 docker）
if (Get-Command docker -ErrorAction SilentlyContinue) {
    if (Test-Path (Join-Path $ProjectDir "docker-compose.yml")) {
        Write-Color "  启动 Docker 基础设施 (PostgreSQL + Redis + MinIO)..." "DarkYellow"
        Push-Location $ProjectDir
        docker compose up -d
        Pop-Location
        Write-Color "  Docker 容器启动中..." "Green"
    }
}

# 启动后端
Write-Color "  启动后端 (端口 $BackendPort)..." "DarkYellow"
$backendJob = Start-Job -ScriptBlock {
    param($dir, $port)
    Set-Location $dir
    python -m uvicorn app.main:app --host 127.0.0.1 --port $port --reload
} -ArgumentList $BackendDir, $BackendPort
Write-Color "  后端已启动 (Job $($backendJob.Id))" "Green"

# 启动前端
Write-Color "  启动前端 (端口 $FrontendPort)..." "DarkYellow"
$frontendJob = Start-Job -ScriptBlock {
    param($dir, $port)
    Set-Location $dir
    npm run dev -- --port $port
} -ArgumentList $FrontendDir, $FrontendPort
Write-Color "  前端已启动 (Job $($frontendJob.Id))" "Green"

# ---- 6. 等待就绪 ----
Write-Color "[6/6] 等待服务就绪..." "Yellow"

function Test-Url($url, $timeoutSec = 60) {
    $endTime = (Get-Date).AddSeconds($timeoutSec)
    while ((Get-Date) -lt $endTime) {
        try {
            $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) { return $true }
        } catch { }
        Start-Sleep -Seconds 2
    }
    return $false
}

Write-Color "  等待后端就绪..." "DarkYellow"
$backendReady = Test-Url "http://localhost:$BackendPort/health" 60
if ($backendReady) {
    Write-Color "  后端就绪" "Green"
} else {
    Write-Color "  警告: 后端启动超时，请检查后端日志" "Yellow"
}

Write-Color "  等待前端就绪..." "DarkYellow"
$frontendReady = Test-Url $FrontendUrl 60
if ($frontendReady) {
    Write-Color "  前端就绪" "Green"
} else {
    Write-Color "  警告: 前端启动超时，请检查前端日志" "Yellow"
}

# ---- 完成 ----
Write-Host ""
Write-Color "============================================" "Green"
Write-Color "  服务启动完成！" "Green"
Write-Color "  前端页面: $FrontendUrl" "Green"
Write-Color "  后端文档: http://localhost:$BackendPort/docs" "Green"
Write-Color "============================================" "Green"
Write-Host ""
Write-Color "按 Ctrl+C 停止所有服务" "Yellow"
Write-Host ""

# 尝试打开浏览器
try {
    Start-Process $FrontendUrl
} catch { }

# 注册清理函数
$global:CleanupDone = $false
function Cleanup {
    if ($global:CleanupDone) { return }
    $global:CleanupDone = $true
    Write-Host ""
    Write-Color "正在停止服务..." "Yellow"
    try { Stop-Job $backendJob -Force; Remove-Job $backendJob -Force } catch { }
    try { Stop-Job $frontendJob -Force; Remove-Job $frontendJob -Force } catch { }
    Stop-PortProcess $BackendPort
    Stop-PortProcess $FrontendPort
    Write-Color "服务已停止" "Green"
}

# 捕获 Ctrl+C
[Console]::TreatControlCAsInput = $false
try {
    while ($true) {
        Start-Sleep -Seconds 1
        # 检查 job 状态
        $backendState = (Get-Job -Id $backendJob.Id -ErrorAction SilentlyContinue).State
        $frontendState = (Get-Job -Id $frontendJob.Id -ErrorAction SilentlyContinue).State
        if ($backendState -ne "Running" -and $frontendState -ne "Running") {
            Write-Color "所有服务已停止" "Yellow"
            break
        }
    }
} finally {
    Cleanup
}
