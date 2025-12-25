#
# Skills CLI Installer for Windows
#
# Usage (PowerShell):
#   irm https://raw.githubusercontent.com/user/skills-cli/main/install.ps1 | iex
#
# Or with custom install directory:
#   $env:INSTALL_DIR = "C:\Tools"; irm ... | iex
#

param(
    [string]$InstallDir = "$env:LOCALAPPDATA\skills-cli",
    [string]$RepoUrl = "https://github.com/user/skills-cli",
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"

# Colors
function Write-Info { Write-Host "[INFO] $args" -ForegroundColor Blue }
function Write-Success { Write-Host "[OK] $args" -ForegroundColor Green }
function Write-Warn { Write-Host "[WARN] $args" -ForegroundColor Yellow }
function Write-Err { Write-Host "[ERROR] $args" -ForegroundColor Red }

Write-Host ""
Write-Host "  Skills CLI Installer"
Write-Host "  ===================="
Write-Host ""

# Check Python
Write-Info "Checking requirements..."

try {
    $pythonVersion = python --version 2>&1
    if ($pythonVersion -match "Python (\d+)\.(\d+)") {
        $major = [int]$Matches[1]
        $minor = [int]$Matches[2]
        if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
            Write-Err "Python 3.10+ required, found $pythonVersion"
            exit 1
        }
        Write-Success "Python $major.$minor"
    }
} catch {
    Write-Err "Python 3.10+ is required but not found"
    Write-Err "Download from: https://www.python.org/downloads/"
    exit 1
}

# Check Git
try {
    $gitVersion = git --version
    Write-Success $gitVersion
} catch {
    Write-Err "Git is required but not found"
    Write-Err "Download from: https://git-scm.com/download/win"
    exit 1
}

# Create install directory
Write-Info "Installing to $InstallDir..."
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# Download the script
Write-Info "Downloading from $RepoUrl..."

$scriptUrl = "$RepoUrl/raw/$Branch/skills_cli.py"
$scriptPath = Join-Path $InstallDir "skills_cli.py"
$wrapperPath = Join-Path $InstallDir "skills-cli.cmd"

try {
    Invoke-WebRequest -Uri $scriptUrl -OutFile $scriptPath -UseBasicParsing
    Write-Success "Downloaded skills_cli.py"
} catch {
    Write-Err "Failed to download: $_"
    exit 1
}

# Create CMD wrapper
$wrapperContent = @"
@echo off
python "%~dp0skills_cli.py" %*
"@

Set-Content -Path $wrapperPath -Value $wrapperContent -Encoding ASCII
Write-Success "Created skills-cli.cmd wrapper"

# Update PATH
$currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($currentPath -notlike "*$InstallDir*") {
    Write-Info "Adding to PATH..."
    $newPath = "$currentPath;$InstallDir"
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    Write-Success "Added to user PATH"
    Write-Warn "Restart your terminal for PATH changes to take effect"
} else {
    Write-Success "Already in PATH"
}

# Optional: Install colorama for better colors
Write-Info "Installing optional dependencies..."
try {
    python -m pip install --quiet colorama 2>&1 | Out-Null
    Write-Success "Installed colorama for color support"
} catch {
    Write-Warn "Could not install colorama (optional)"
}

Write-Host ""
Write-Success "Installation complete!"
Write-Host ""
Write-Host "  Usage:"
Write-Host "    skills-cli list --repo https://github.com/anthropics/skills/tree/main/skills"
Write-Host "    skills-cli install --repo <url> --all"
Write-Host "    skills-cli --help"
Write-Host ""

# Refresh environment for current session
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
