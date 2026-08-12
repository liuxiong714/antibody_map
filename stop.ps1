# ============================================================
# Antibody Map 停止脚本 (Windows PowerShell)
# 用法: .\stop.ps1
# ============================================================

$BackendPort = 8080
$FrontendPort = 3000
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Color($text, $color = "White") {
    Write-Host $text -ForegroundColor $color
}

Write-Color "============================================" "Cyan"
Write-Color "  停止 Antibody Map 服务" "Cyan"
Write-Color "============================================" "Cyan"
Write-Host ""

# 停止 Docker Compose
if (Get-Command docker -ErrorAction SilentlyContinue) {
    if (Test-Path (Join-Path $ProjectDir "docker-compose.yml")) {
        Write-Color "停止 Docker 容器..." "Yellow"
        Push-Location $ProjectDir
        docker compose down
        Pop-Location
        Write-Color "Docker 容器已停止" "Green"
    }
}

# 停止占用端口的进程
function Stop-PortProcess($port, $name) {
    $procs = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
             Select-Object -ExpandProperty OwningProcess -Unique
    if ($procs) {
        foreach ($procId in $procs) {
            try {
                $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
                if ($proc) {
                    Write-Color "停止 $name 进程: $($proc.ProcessName) (PID $procId)" "Yellow"
                    Stop-Process -Id $procId -Force
                }
            } catch { }
        }
        Start-Sleep -Seconds 1
    } else {
        Write-Color "端口 $port ($name) 无运行中进程" "Gray"
    }
}

Stop-PortProcess $BackendPort "后端"
Stop-PortProcess $FrontendPort "前端"

# 清理所有 python/uvicorn 和 node/vite 相关进程（可选，谨慎使用）
# 只杀明显属于本项目的进程
$uvicorns = Get-Process -Name python -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -match "python" -and (Get-WmiObject Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine -match "uvicorn" }

Write-Host ""
Write-Color "============================================" "Green"
Write-Color "  服务已全部停止" "Green"
Write-Color "============================================" "Green"
