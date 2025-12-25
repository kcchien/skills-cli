#
# Skills CLI Installer for Windows
#
# Usage (PowerShell):
#   irm https://raw.githubusercontent.com/kcchien/skills-cli/main/install.ps1 | iex
#
# Or with custom options:
#   $env:USER_INSTALL = "true"; irm ... | iex    # Install to user site-packages
#

param(
    [string]$RepoUrl = "https://github.com/kcchien/skills-cli.git",
    [switch]$User = $false
)

$ErrorActionPreference = "Stop"

# Check for environment variable override
if ($env:USER_INSTALL -eq "true") {
    $User = $true
}

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

# Check pip
try {
    python -m pip --version | Out-Null
} catch {
    Write-Err "pip is required but not found"
    exit 1
}

# Install via pip
Write-Info "Installing skills-cli via pip..."

$pipArgs = @("install", "--upgrade")
if ($User) {
    $pipArgs += "--user"
}
$pipArgs += "git+$RepoUrl"

try {
    $output = python -m pip @pipArgs 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Installed successfully"
    } else {
        Write-Err "Installation failed"
        Write-Host $output
        exit 1
    }
} catch {
    Write-Err "Installation failed: $_"
    exit 1
}

# Install colorama for better colors (optional)
Write-Info "Installing optional dependencies..."
try {
    python -m pip install --quiet colorama 2>&1 | Out-Null
    Write-Success "Installed colorama for color support"
} catch {
    Write-Warn "Could not install colorama (optional)"
}

# Verify installation
$skillsCliPath = $null
try {
    $skillsCliPath = (Get-Command skills-cli -ErrorAction SilentlyContinue).Source
} catch {}

if ($skillsCliPath) {
    Write-Success "Installed to $skillsCliPath"
} else {
    # Check user Scripts folder
    $userScripts = Join-Path $env:APPDATA "Python\Python*\Scripts"
    $possiblePaths = Get-ChildItem $userScripts -ErrorAction SilentlyContinue |
                     Where-Object { Test-Path (Join-Path $_.FullName "skills-cli.exe") }

    if ($possiblePaths) {
        $scriptsPath = $possiblePaths[0].FullName
        Write-Success "Installed to $scriptsPath"

        # Check if in PATH
        if ($env:Path -notlike "*$scriptsPath*") {
            Write-Warn "$scriptsPath is not in PATH"
            Write-Info "Adding to user PATH..."

            $currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
            if ($currentPath -notlike "*$scriptsPath*") {
                $newPath = "$currentPath;$scriptsPath"
                [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
                Write-Success "Added to user PATH"
                Write-Warn "Restart your terminal for PATH changes to take effect"
            }
        }
    }
}

Write-Host ""
Write-Success "Installation complete!"
Write-Host ""
Write-Host "  Usage:"
Write-Host "    skills-cli list"
Write-Host "    skills-cli install --all"
Write-Host "    skills-cli --help"
Write-Host ""

# Refresh environment for current session
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
