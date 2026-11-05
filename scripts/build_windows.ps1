$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "[1/5] Checking Windows architecture..."
if (-not [Environment]::Is64BitOperatingSystem) { throw "Only 64-bit Windows is supported by this build." }
if ($env:PROCESSOR_ARCHITECTURE -notin @("AMD64", "ARM64")) { throw "Unsupported processor architecture: $env:PROCESSOR_ARCHITECTURE" }

Write-Host "[2/5] Locating Python 3.12..."
$Python = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.12 --version *> $null
    if ($LASTEXITCODE -eq 0) { $Python = "py" }
}
if (-not $Python) {
    throw "Python 3.12 (64-bit) is required for the source-build path. Install it from https://www.python.org/downloads/windows/ and rerun START.bat. A prebuilt portable release will not need Python."
}

Write-Host "[3/5] Creating/updating isolated build environment..."
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create .venv." }
}
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip wheel
if ($LASTEXITCODE -ne 0) { throw "pip bootstrap failed." }
& $VenvPython -m pip install -e . pyinstaller
if ($LASTEXITCODE -ne 0) { throw "Application dependencies or PyInstaller installation failed." }

Write-Host "[4/5] Building desktop executable (onedir)..."
& $VenvPython -m PyInstaller --noconfirm --clean ecmwf_webp.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

Write-Host "[5/5] Checking generated executable..."
$Exe = Join-Path $RepoRoot "dist\ECMWFWebP\ECMWFWebP.exe"
if (-not (Test-Path $Exe)) { throw "Expected executable was not generated: $Exe" }
Write-Host "Build complete: $Exe"
Write-Host "Note: first-run database initialization and PostgreSQL provisioning are separate milestones; this build still uses the existing SQLite state store."
