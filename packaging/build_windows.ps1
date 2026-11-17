$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot

if ($env:OS -ne "Windows_NT") {
    throw "This packaging script must be run on Windows."
}

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw "Python 3.12 is required to build the installer. Install Python, then run this script again."
    }
    & py -3.12 -m venv (Join-Path $projectRoot ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Could not create the build virtual environment." }
}

$pythonVersion = & $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0 -or $pythonVersion.Trim() -ne "3.12") {
    throw "Python 3.12 is required in .venv to build this installer (found $pythonVersion)."
}

& $python -m pip install -e ".[build]"
if ($LASTEXITCODE -ne 0) { throw "Could not install BudgetApp's build dependencies." }

$versionLine = Select-String -Path (Join-Path $projectRoot "pyproject.toml") -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
if (-not $versionLine -or $versionLine.Line -notmatch '^version\s*=\s*"([^"]+)"') {
    throw "Could not read the application version from pyproject.toml."
}
$version = $Matches[1]

& $python -m PyInstaller --clean --noconfirm (Join-Path $PSScriptRoot "BudgetApp.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed to package BudgetApp." }

$innoSetup7Candidates = @(
    "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe"
)
$iscc = $innoSetup7Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) {
    $isccCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    $iscc = if ($isccCommand) { $isccCommand.Source } else { $null }
}

if (-not $iscc) {
    $innoSetup6Candidates = @(
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    )
    $iscc = $innoSetup6Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}

if (-not $iscc) {
    throw "Inno Setup 7 was not found. Install it from https://jrsoftware.org/inno-setup/downloads and rerun this script."
}

$installerDir = Join-Path $projectRoot "dist\installer"
New-Item -ItemType Directory -Force -Path $installerDir | Out-Null
& $iscc "/DAppVersion=$version" "/DSourceDir=$(Join-Path $projectRoot 'dist\BudgetApp')" "/O$installerDir" (Join-Path $PSScriptRoot "BudgetApp.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed to create the installer." }

Write-Host "Installer created in $installerDir"
