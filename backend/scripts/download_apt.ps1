# Download Debian .deb packages to local repo for fully offline backend build.
# Usage:
#   .\backend\scripts\download_apt.ps1
#
# Prereq: docker available inside WSL, network up.
# Notes:
#   - Uses the same base image (python:3.11-slim) and aliyun apt source as the
#     Dockerfile, so .deb versions match the build environment.
#   - Downloads grouped by the 3 apt layers of the Dockerfile:
#       main   = core system deps (build-essential/tesseract/mupdf-tools/curl)
#       mineru = MinerU runtime libs (libgl1/libglib2.0-0, only when INSTALL_MINERU=true)
#       pg     = postgresql-client (db backup client)
#   - After download, `docker compose build` can run fully offline.
#   - Re-run this script after upgrading the python:3.11-slim base image.

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
$AptCacheDir = "$ProjectRoot\backend\apt_cache"
New-Item -ItemType Directory -Force -Path "$AptCacheDir\main" | Out-Null
New-Item -ItemType Directory -Force -Path "$AptCacheDir\mineru" | Out-Null
New-Item -ItemType Directory -Force -Path "$AptCacheDir\pg" | Out-Null

# Windows path -> WSL mount path (E:\... -> /mnt/e/...; drive letter lowercased only)
$WslRoot = "/mnt/" + $ProjectRoot.Substring(0, 1).ToLower() + $ProjectRoot.Substring(2).Replace('\', '/')

$Groups = @(
    @{ Name = "main";   Packages = "build-essential libjpeg-dev zlib1g-dev libxml2-dev libxslt1-dev tesseract-ocr tesseract-ocr-chi-sim mupdf-tools curl" }
    @{ Name = "mineru"; Packages = "libgl1 libglib2.0-0" }
    @{ Name = "pg";     Packages = "postgresql-client" }
)

# Container script: switch to aliyun source -> download full .deb dependency
# tree per group into /apt_cache/<group>. Single-quoted here-string keeps
# bash vars literal; group content is injected via placeholder.
$ScriptTemplate = @'
set -e
sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources 2>/dev/null || true
apt-get update
__GROUPS__
echo "=== DONE ==="
for d in /apt_cache/*; do echo "group $d -> $(ls $d | wc -l) files"; done
'@

$GroupScripts = @()
foreach ($g in $Groups) {
    $GroupScripts += @"
rm -f /var/cache/apt/archives/*.deb
echo "=== downloading group: $($g.Name) ==="
apt-get install --download-only -y --no-install-recommends $($g.Packages)
mkdir -p /apt_cache/$($g.Name)
cp /var/cache/apt/archives/*.deb /apt_cache/$($g.Name)/
"@
}
$Script = $ScriptTemplate.Replace('__GROUPS__', ($GroupScripts -join "`n"))

# Write container script to a temp file (no BOM) to avoid PS->wsl quoting issues.
$tmpScript = Join-Path $env:TEMP "download_apt_container.sh"
[System.IO.File]::WriteAllText($tmpScript, $Script + "`n", (New-Object System.Text.UTF8Encoding($false)))
$tmpWsl = "/mnt/" + $tmpScript.Substring(0, 1).ToLower() + $tmpScript.Substring(2).Replace('\', '/')

# WSL-internal temp dir: Docker Desktop bind writes to /mnt/<drive> (DrvFs) are
# unreliable (reads ok, writes lost in container layer), so download into WSL
# ext4 path first, then copy back to the E: project dir.
$TmpAptWsl = "/tmp/apt_cache_dl"
wsl -d Ubuntu-22.04 -- mkdir -p $TmpAptWsl
wsl -d Ubuntu-22.04 -- rm -rf "$TmpAptWsl"/*
if ($LASTEXITCODE -ne 0) { throw "failed to reset temp dir" }

Write-Host "=== downloading apt packages (python:3.11-slim, aliyun source) ==="
wsl -d Ubuntu-22.04 -- docker run --rm `
    -v "${TmpAptWsl}:/apt_cache" `
    -v "${tmpWsl}:/dl.sh" `
    python:3.11-slim bash /dl.sh

if ($LASTEXITCODE -ne 0) {
    throw "apt package download failed, check network and retry"
}

# Copy .deb back to project dir (build context location on E:)
Write-Host "=== copying .deb to $AptCacheDir ==="
wsl -d Ubuntu-22.04 -- bash -c "cp -r $TmpAptWsl/main/* '$WslRoot/backend/apt_cache/main/' && cp -r $TmpAptWsl/mineru/* '$WslRoot/backend/apt_cache/mineru/' && cp -r $TmpAptWsl/pg/* '$WslRoot/backend/apt_cache/pg/'"
if ($LASTEXITCODE -ne 0) {
    throw "copy .deb to project dir failed"
}

$debs = Get-ChildItem "$AptCacheDir" -Recurse -Filter *.deb -ErrorAction SilentlyContinue
$count = @($debs).Count
$size = "{0:N2}" -f (($debs | Measure-Object -Property Length -Sum).Sum / 1MB)
Write-Host "=== DONE ==="
Write-Host "downloaded $count .deb files, ~$size MB"
Write-Host "dir: $AptCacheDir (main / mineru / pg)"
Write-Host "now you can run offline: docker compose build"
