param(
    [string]$DistPath,
    [string]$WorkPath
)

$ErrorActionPreference = "Stop"
$env:PYTHONDONTWRITEBYTECODE = "1"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path $projectRoot

$specPath = Join-Path $projectRoot "copyer.spec"
$icoPath = Join-Path $projectRoot "app_icon.ico"
$projectPython = Join-Path $projectRoot ".conda_env\python.exe"
$projectLibraryBin = Join-Path $projectRoot ".conda_env\Library\bin"

if (!(Test-Path $icoPath)) {
    Write-Error "app_icon.ico not found in project root."
    exit 1
}

if (!(Test-Path $specPath)) {
    Write-Error "copyer.spec not found in project root."
    exit 1
}

if (Test-Path $projectPython) {
    $pythonExecutable = $projectPython
    if (Test-Path $projectLibraryBin) {
        $projectEnvironmentRoot = Split-Path -Parent $projectPython
        $systemDirectory = [Environment]::GetFolderPath("System")
        $env:PATH = "$projectLibraryBin;$projectEnvironmentRoot;$systemDirectory;$env:SystemRoot"
        $env:PYTHONNOUSERSITE = "1"
    }
} else {
    Write-Error "Project Python not found. Create .conda_env and install requirements.txt first."
    exit 1
}

& $pythonExecutable (Join-Path $projectRoot "tools\fetch_exiftool.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$pyInstallerArguments = @("--noconfirm", "--clean")
if ($DistPath) {
    $pyInstallerArguments += @("--distpath", $DistPath)
}
if ($WorkPath) {
    $pyInstallerArguments += @("--workpath", $WorkPath)
}
$pyInstallerArguments += $specPath

& $pythonExecutable -m PyInstaller @pyInstallerArguments
$buildExitCode = $LASTEXITCODE
if ($buildExitCode -ne 0) { exit $buildExitCode }

$releaseVersion = & $pythonExecutable -c "from copyer_version import APP_VERSION; print(APP_VERSION)"
$releaseDist = if ($DistPath) { $DistPath } else { Join-Path $projectRoot "dist" }
$releaseDirectory = Join-Path $releaseDist "copyer-$releaseVersion"
& $pythonExecutable (Join-Path $projectRoot "tools\collect_licenses.py") $releaseDirectory
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $pythonExecutable (Join-Path $projectRoot "tools\verify_package.py") $releaseDirectory
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
exit 0
