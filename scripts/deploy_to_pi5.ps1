param(
    [string]$PiUser = "pi",
    [string]$PiHost = "192.168.137.35",
    [string]$RemoteDir = "/home/pi/AIoT"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ArchivePath = Join-Path $env:TEMP "aiot_deploy_bundle.tar.gz"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "DONG GOI & DAY CODE + MODEL TU PC XUONG RASPBERRY PI 5 ($PiHost)" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

Push-Location $ProjectRoot
try {
    if (Test-Path $ArchivePath) { Remove-Item $ArchivePath -Force }

    Write-Host "[1/3] Nen backend, pipeline, scripts, data/processed, logs va models/artifacts..."
    $includePaths = @("backend", "pipeline", "scripts", "models/__init__.py", "models/training", "models/artifacts")
    if (Test-Path "data/processed/local_feature_windows.csv") {
        $includePaths += "data/processed/local_feature_windows.csv"
    }
    if (Test-Path "logs") {
        $includePaths += "logs"
    }
    & tar.exe `
        --exclude="__pycache__" `
        --exclude="*.pyc" `
        -czf $ArchivePath `
        @includePaths

    if (-not (Test-Path $ArchivePath)) {
        throw "Khong tao duoc file nen $ArchivePath"
    }
    $sizeMb = [math]::Round((Get-Item $ArchivePath).Length / 1MB, 2)
    Write-Host "      -> Kich thuoc goi trien khai: $sizeMb MB"

    Write-Host "[2/3] Copy goi trien khai len ${PiUser}@${PiHost}:/tmp/..."
    & scp.exe $ArchivePath "${PiUser}@${PiHost}:/tmp/aiot_deploy_bundle.tar.gz"
    if ($LASTEXITCODE -ne 0) {
        throw "Loi scp len Raspberry Pi 5. Hay kiem tra Pi 5 da bat nguon & ket noi mang chua."
    }

    Write-Host "[3/3] Giai nen tren Pi 5 & khoi dong lai iot_pipeline, iot_gateway..."
    $remoteCmd = "mkdir -p $RemoteDir && tar -xzf /tmp/aiot_deploy_bundle.tar.gz -C $RemoteDir && rm -f /tmp/aiot_deploy_bundle.tar.gz && chmod +x $RemoteDir/scripts/*.sh $RemoteDir/scripts/*.py && sudo systemctl restart iot_pipeline iot_gateway && sleep 2 && sudo systemctl status iot_pipeline iot_gateway --no-pager"
    & ssh.exe -t "${PiUser}@${PiHost}" $remoteCmd
    if ($LASTEXITCODE -ne 0) {
        throw "Loi giai nen hoac restart systemd services tren Pi 5."
    }

    Write-Host ""
    Write-Host "[THANH CONG] Da cap nhat Pi 5 va khoi dong lai Web Gateway (http://${PiHost}:8000)." -ForegroundColor Green
}
finally {
    if (Test-Path $ArchivePath) { Remove-Item $ArchivePath -Force -ErrorAction SilentlyContinue }
    Pop-Location
}

