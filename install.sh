#!/usr/bin/env bash
#
# Skills CLI Installer for macOS/Linux
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/kcchien/skills-cli/main/install.sh | bash
#
# Or with custom options:
#   curl -fsSL ... | bash -s -- --user    # Install to user site-packages
#

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }

# Default values
REPO_URL="https://github.com/kcchien/skills-cli.git"
USER_INSTALL=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --user)
            USER_INSTALL=true
            shift
            ;;
        --repo)
            REPO_URL="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: install.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --user        Install to user site-packages (no sudo)"
            echo "  --repo URL    Git repository URL"
            echo "  -h, --help    Show this help"
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Header
echo ""
echo "  Skills CLI Installer"
echo "  ===================="
echo ""

# Check requirements
info "Checking requirements..."

# Check Python
if command -v python3 &>/dev/null; then
    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
    PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

    if [[ $PYTHON_MAJOR -lt 3 ]] || [[ $PYTHON_MAJOR -eq 3 && $PYTHON_MINOR -lt 10 ]]; then
        error "Python 3.10+ required, found $PYTHON_VERSION"
        exit 1
    fi
    success "Python $PYTHON_VERSION"
else
    error "Python 3.10+ is required but not found"
    exit 1
fi

# Check Git
if command -v git &>/dev/null; then
    GIT_VERSION=$(git --version | awk '{print $3}')
    success "Git $GIT_VERSION"
else
    error "Git is required but not found"
    exit 1
fi

# Check pip
if ! python3 -m pip --version &>/dev/null; then
    error "pip is required but not found"
    exit 1
fi

# Install via pip
info "Installing skills-cli via pip..."

PIP_ARGS="install --upgrade --no-cache-dir"
if [[ "$USER_INSTALL" == true ]]; then
    PIP_ARGS="$PIP_ARGS --user"
fi

if python3 -m pip $PIP_ARGS "git+${REPO_URL}" 2>&1; then
    success "Installed successfully"
else
    error "Installation failed"
    exit 1
fi

# Verify installation
if command -v skills-cli &>/dev/null; then
    INSTALLED_PATH=$(command -v skills-cli)
    success "Installed to $INSTALLED_PATH"
else
    # Check if installed to user bin
    USER_BIN="$HOME/.local/bin"
    if [[ -f "$USER_BIN/skills-cli" ]]; then
        success "Installed to $USER_BIN/skills-cli"
        if [[ ":$PATH:" != *":$USER_BIN:"* ]]; then
            warn "$USER_BIN is not in PATH"

            # Detect shell
            SHELL_NAME=$(basename "$SHELL")
            case "$SHELL_NAME" in
                bash) RC_FILE="$HOME/.bashrc" ;;
                zsh)  RC_FILE="$HOME/.zshrc" ;;
                fish) RC_FILE="$HOME/.config/fish/config.fish" ;;
                *)    RC_FILE="" ;;
            esac

            if [[ -n "$RC_FILE" ]] && [[ -f "$RC_FILE" ]]; then
                echo "" >> "$RC_FILE"
                echo "# Added by skills-cli installer" >> "$RC_FILE"
                echo "export PATH=\"\$PATH:$USER_BIN\"" >> "$RC_FILE"
                info "Added to $RC_FILE"
                warn "Run 'source $RC_FILE' or restart your terminal"
            else
                warn "Add this to your shell config:"
                echo "  export PATH=\"\$PATH:$USER_BIN\""
            fi
        fi
    fi
fi

echo ""
success "Installation complete!"
echo ""
echo "  Usage:"
echo "    skills-cli list"
echo "    skills-cli install --all"
echo "    skills-cli --help"
echo ""
