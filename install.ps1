<#
.SYNOPSIS
    Quick installer for YUKI-ide on Windows.

.DESCRIPTION
    Clones the YUKI-ide repository, creates a Python virtual environment,
    installs the editor into it (editable), and creates launcher shims
    (stdedit, yuki, carl) on your User PATH.

    This is the Windows counterpart to install.sh (which delegates to
    `make install` / `carl install` — a flow that assumes a Unix venv
    layout and can't place symlinks on Windows).

.USAGE
    Save as install.ps1 and run:
        .\install.ps1

    Or, once this file lives at the repo root on the `main` branch:
        irm https://raw.githubusercontent.com/the-priyankaa/YUKI-ide/main/install.ps1 | iex
#>

$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/the-priyankaa/YUKI-ide.git"
$RepoDir = Join-Path $HOME "YUKI-ide"
$BinDir  = Join-Path $HOME ".local\bin"

function Write-Info  ($msg) { Write-Host "[info] $msg" -ForegroundColor Cyan }
function Write-ErrorMsg ($msg) { Write-Host "[error] $msg" -ForegroundColor Red }

# --- sanity checks ---------------------------------------------------------

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-ErrorMsg "git is not installed. Install it from https://git-scm.com/download/win and re-run."
    exit 1
}

$PythonCmd = $null
foreach ($candidate in @("python", "py")) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) { $PythonCmd = $cmd.Source; break }
}
if (-not $PythonCmd) {
    Write-ErrorMsg "Python 3.9+ is not installed. Install it from https://www.python.org/downloads/ and re-run."
    exit 1
}

$verOutput = & $PythonCmd -c "import sys; print('%d.%d' % sys.version_info[:2])"
$verParts = $verOutput.Trim().Split('.')
if (([int]$verParts[0] -lt 3) -or ([int]$verParts[0] -eq 3 -and [int]$verParts[1] -lt 9)) {
    Write-ErrorMsg "Python 3.9+ required, found $verOutput"
    exit 1
}

# --- clone ------------------------------------------------------------------

if (Test-Path $RepoDir) {
    Write-Info "Directory '$RepoDir' already exists, skipping clone."
} else {
    Write-Info "Cloning $RepoUrl ..."
    git clone $RepoUrl $RepoDir
}

$CoreDir = Join-Path $RepoDir "core"
if (-not (Test-Path $CoreDir)) {
    Write-ErrorMsg "Expected directory not found: $CoreDir"
    exit 1
}
Set-Location $CoreDir

# --- venv ---------------------------------------------------------------

$VenvDir = Join-Path $CoreDir ".venv"
if (Test-Path $VenvDir) {
    Write-Info "venv already present: $VenvDir"
} else {
    Write-Info "Creating venv: $VenvDir"
    & $PythonCmd -m venv $VenvDir
}

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-ErrorMsg "venv creation failed: $VenvPython not found"
    exit 1
}

Write-Info "Installing editor into venv (editable) ..."
& $VenvPython -m pip install -e . --quiet
if ($LASTEXITCODE -ne 0) {
    Write-ErrorMsg "pip install failed (exit $LASTEXITCODE)"
    exit 1
}

# --- launcher shims -------------------------------------------------------

New-Item -ItemType Directory -Path $BinDir -Force | Out-Null

$Launchers = @("stdedit", "yuki", "carl")
$created = @()
foreach ($name in $Launchers) {
    $target = Join-Path $VenvDir "Scripts\$name.exe"
    if (Test-Path $target) {
        $shim = Join-Path $BinDir "$name.cmd"
        "@echo off`r`n`"$target`" %*" | Set-Content -Encoding ascii $shim
        Write-Info "created $shim -> $target"
        $created += $name
    }
}

if ($created.Count -eq 0) {
    Write-ErrorMsg "no launcher scripts found in the venv - was pip install successful?"
    exit 1
}

# --- PATH -----------------------------------------------------------------

$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($UserPath -notlike "*$BinDir*") {
    $newPath = if ([string]::IsNullOrEmpty($UserPath)) { $BinDir } else { "$UserPath;$BinDir" }
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    $env:Path = "$env:Path;$BinDir"
    Write-Info "Added $BinDir to your User PATH. Open a new terminal for it to take effect everywhere."
} else {
    Write-Info "$BinDir already on PATH."
}

Write-Info "Done. Launch the editor with any of:"
foreach ($name in $created) { Write-Host "      $name path\to\project_or_file" }
