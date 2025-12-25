#!/usr/bin/env bash
#
# Skills CLI Installer for macOS/Linux
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/kcchien/skills-cli/main/install.sh | bash
#
# Or with custom install directory:
#   curl -fsSL ... | bash -s -- --prefix ~/.local
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
INSTALL_DIR="${HOME}/.local/bin"
REPO_URL="https://github.com/kcchien/skills-cli"
BRANCH="main"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --prefix)
            INSTALL_DIR="$2/bin"
            shift 2
            ;;
        --repo)
            REPO_URL="$2"
            shift 2
            ;;
        --branch)
            BRANCH="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: install.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --prefix DIR    Install to DIR/bin (default: ~/.local)"
            echo "  --repo URL      Git repository URL"
            echo "  --branch NAME   Git branch (default: main)"
            echo "  -h, --help      Show this help"
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Check requirements
check_requirements() {
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
}

# Download and install
install_skills_cli() {
    info "Installing skills-cli..."

    # Create install directory
    mkdir -p "$INSTALL_DIR"

    # Create temporary directory
    TMP_DIR=$(mktemp -d)
    trap "rm -rf $TMP_DIR" EXIT

    # Download the script
    info "Downloading from $REPO_URL..."

    if command -v curl &>/dev/null; then
        curl -fsSL "${REPO_URL}/raw/${BRANCH}/skills_cli.py" -o "${TMP_DIR}/skills_cli.py"
    elif command -v wget &>/dev/null; then
        wget -q "${REPO_URL}/raw/${BRANCH}/skills_cli.py" -O "${TMP_DIR}/skills_cli.py"
    else
        error "curl or wget is required"
        exit 1
    fi

    # Make executable and install
    chmod +x "${TMP_DIR}/skills_cli.py"
    mv "${TMP_DIR}/skills_cli.py" "${INSTALL_DIR}/skills-cli"

    # Add shebang wrapper for better compatibility
    cat > "${INSTALL_DIR}/skills-cli" << 'WRAPPER'
#!/usr/bin/env python3
WRAPPER
    cat "${TMP_DIR}/skills_cli.py" >> "${INSTALL_DIR}/skills-cli" 2>/dev/null || \
        curl -fsSL "${REPO_URL}/raw/${BRANCH}/skills_cli.py" >> "${INSTALL_DIR}/skills-cli"

    chmod +x "${INSTALL_DIR}/skills-cli"

    success "Installed to ${INSTALL_DIR}/skills-cli"
}

# Update PATH if needed
update_path() {
    if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
        warn "$INSTALL_DIR is not in PATH"

        # Detect shell
        SHELL_NAME=$(basename "$SHELL")
        case "$SHELL_NAME" in
            bash)
                RC_FILE="$HOME/.bashrc"
                ;;
            zsh)
                RC_FILE="$HOME/.zshrc"
                ;;
            fish)
                RC_FILE="$HOME/.config/fish/config.fish"
                ;;
            *)
                RC_FILE=""
                ;;
        esac

        if [[ -n "$RC_FILE" ]]; then
            echo "" >> "$RC_FILE"
            echo "# Added by skills-cli installer" >> "$RC_FILE"
            echo "export PATH=\"\$PATH:$INSTALL_DIR\"" >> "$RC_FILE"
            info "Added to $RC_FILE"
            warn "Run 'source $RC_FILE' or restart your terminal"
        else
            warn "Add this to your shell config:"
            echo "  export PATH=\"\$PATH:$INSTALL_DIR\""
        fi
    fi
}

# Main
main() {
    echo ""
    echo "  Skills CLI Installer"
    echo "  ===================="
    echo ""

    check_requirements
    install_skills_cli
    update_path

    echo ""
    success "Installation complete!"
    echo ""
    echo "  Usage:"
    echo "    skills-cli list --repo https://github.com/anthropics/skills/tree/main/skills"
    echo "    skills-cli install --repo <url> --all"
    echo "    skills-cli --help"
    echo ""
}

main
