param(
    [string]$DistPath,
    [string]$WorkPath
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path $projectRoot

$specPath = Join-Path $projectRoot "copyer-1.3.3.spec"
$icoPath = Join-Path $projectRoot "app_icon.ico"
$projectPython = Join-Path $projectRoot ".conda_env\python.exe"
$projectLibraryBin = Join-Path $projectRoot ".conda_env\Library\bin"

if (!(Test-Path $icoPath)) {
    Write-Error "app_icon.ico not found in project root."
    exit 1
}

if (!(Test-Path $specPath)) {
    Write-Error "copyer-1.3.3.spec not found in project root."
    exit 1
}

if (Test-Path $projectPython) {
    $pythonExecutable = $projectPython
    if (Test-Path $projectLibraryBin) {
        $env:PATH = "$projectLibraryBin;$env:PATH"
    }
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (!$pythonCommand) {
        Write-Error "Python not found. Create .conda_env or add Python to PATH."
        exit 1
    }
    $pythonExecutable = $pythonCommand.Source
}

$pyInstallerArguments = @("--noconfirm", "--clean")
if ($DistPath) {
    $pyInstallerArguments += @("--distpath", $DistPath)
}
if ($WorkPath) {
    $pyInstallerArguments += @("--workpath", $WorkPath)
}
$pyInstallerArguments += $specPath

& $pythonExecutable -m PyInstaller @pyInstallerArguments
