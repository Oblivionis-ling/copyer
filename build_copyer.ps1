$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path $projectRoot

$specPath = Join-Path $projectRoot "copyer-1.3.3.spec"
$icoPath = Join-Path $projectRoot "app_icon.ico"

if (!(Test-Path $icoPath)) {
    Write-Error "app_icon.ico not found in project root."
    exit 1
}

if (!(Test-Path $specPath)) {
    Write-Error "copyer-1.3.3.spec not found in project root."
    exit 1
}

python -m PyInstaller `
    --noconfirm `
    --clean `
    $specPath
