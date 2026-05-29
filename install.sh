#!/bin/bash
# Code Explorer Agent Installer
# Supports macOS and Linux (Debian/Ubuntu, RHEL/Fedora, Arch)

set -e

REPO_URL="https://github.com/mcmillanb/code-explorer-agent.git"
INSTALL_DIR="$HOME/.local/share/ce-agent"
BIN_DIR="$HOME/.local/bin"
LOG_DIR="$HOME/.code-explorer"
SERVICE_NAME="ce-agent"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

echo "=== Code Explorer Agent Installation ==="

# 1. Detect OS
OS="$(uname -s)"
case "$OS" in
    Linux*)     PLATFORM=linux;;
    Darwin*)    PLATFORM=macos;;
    *)          error "Unsupported OS: $OS";;
esac

info "Detected platform: $PLATFORM"

# 2. Check and Install System Dependencies
install_linux_deps() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        case "$ID" in
            ubuntu|debian|pop|mint)
                info "Installing dependencies via apt..."
                sudo apt-get update -qq
                sudo apt-get install -y tmux python3 python3-venv python3-pip git curl
                ;;
            fedora|rhel|centos)
                info "Installing dependencies via dnf..."
                sudo dnf install -y tmux python3 python3-pip git curl
                ;;
            arch|manjaro)
                info "Installing dependencies via pacman..."
                sudo pacman -S --noconfirm tmux python python-pip git curl
                ;;
            *)
                warn "Unknown Linux distribution: $ID. Please ensure tmux, python3, and git are installed."
                ;;
        esac
    else
        warn "Could not determine Linux distribution. Please ensure tmux, python3, and git are installed."
    fi
}

install_macos_deps() {
    if ! command -v brew &> /dev/null; then
        warn "Homebrew not found. It is recommended for installing dependencies."
        warn "Please install Homebrew from https://brew.sh/ or manually install tmux and python3."
        # Attempt to proceed if they have them anyway
    else
        info "Installing dependencies via Homebrew..."
        brew install tmux python@3.11 git
    fi
}

if [ "$PLATFORM" = "macos" ]; then
    install_macos_deps
else
    install_linux_deps
fi

# Final check for critical commands
for cmd in tmux python3 git curl; do
    if ! command -v "$cmd" &> /dev/null; then
        error "$cmd is not installed and could not be automatically installed. Please install it and try again."
    fi
done

# 3. Setup Directories
mkdir -p "$INSTALL_DIR"
mkdir -p "$BIN_DIR"
mkdir -p "$LOG_DIR"

# 4. Clone or Update Repository
if [ -d "$INSTALL_DIR/repo" ]; then
    info "Updating existing repository in $INSTALL_DIR/repo..."
    cd "$INSTALL_DIR/repo"
    git pull
else
    # If we are already inside a repo (e.g. user downloaded install.sh into the repo)
    if [ -f "pyproject.toml" ] && grep -q "ce-agent" pyproject.toml; then
        info "Installing from current directory..."
        mkdir -p "$INSTALL_DIR/repo"
        cp -R . "$INSTALL_DIR/repo/"
        cd "$INSTALL_DIR/repo"
    else
        info "Cloning repository from $REPO_URL..."
        git clone "$REPO_URL" "$INSTALL_DIR/repo"
        cd "$INSTALL_DIR/repo"
    fi
fi

# 5. Create Virtual Environment and Install Package
info "Setting up Python virtual environment..."
python3 -m venv "$INSTALL_DIR/venv"
source "$INSTALL_DIR/venv/bin/activate"

info "Installing ce-agent package and dependencies..."
pip install --upgrade pip
pip install .

# 6. Create Wrapper Script
info "Creating wrapper script at $BIN_DIR/ce-agent..."
cat <<EOF > "$BIN_DIR/ce-agent"
#!/bin/bash
source "$INSTALL_DIR/venv/bin/activate"
exec ce-agent "\$@"
EOF
chmod +x "$BIN_DIR/ce-agent"

# 7. Add to PATH if necessary
update_path() {
    local shell_config="$1"
    if [ -f "$shell_config" ]; then
        if ! grep -q "$BIN_DIR" "$shell_config"; then
            info "Adding $BIN_DIR to $shell_config..."
            echo -e "\n# ce-agent path\nexport PATH=\"\$PATH:$BIN_DIR\"" >> "$shell_config"
        fi
    fi
}

if [ "$PLATFORM" = "macos" ]; then
    update_path "$HOME/.zshenv"
    update_path "$HOME/.bash_profile"
else
    update_path "$HOME/.bashrc"
    update_path "$HOME/.profile"
fi

# 8. Register Background Service
if [ "$PLATFORM" = "macos" ]; then
    PLIST_PATH="$HOME/Library/LaunchAgents/app.codeexplorer.agent.plist"
    info "Setting up macOS LaunchAgent at $PLIST_PATH..."
    
    mkdir -p "$(dirname "$PLIST_PATH")"
    cat <<EOF > "$PLIST_PATH"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>app.codeexplorer.agent</string>
    <key>ProgramArguments</key>
    <array>
      <string>$BIN_DIR/ce-agent</string>
      <string>daemon</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/ce-agent.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/ce-agent.stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
      <key>PATH</key>
      <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$BIN_DIR</string>
    </dict>
  </dict>
</plist>
EOF
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    launchctl load "$PLIST_PATH"
    info "Service started via launchctl."

else
    # Linux systemd user service
    if command -v systemctl &> /dev/null; then
        SERVICE_PATH="$HOME/.config/systemd/user/ce-agent.service"
        info "Setting up Linux systemd user service at $SERVICE_PATH..."
        
        mkdir -p "$(dirname "$SERVICE_PATH")"
        cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Code Explorer Agent Daemon
After=network.target

[Service]
ExecStart=$BIN_DIR/ce-agent daemon
Restart=always
StandardOutput=append:$LOG_DIR/ce-agent.stdout.log
StandardError=append:$LOG_DIR/ce-agent.stderr.log
Environment="PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$BIN_DIR"

[Install]
WantedBy=default.target
EOF
        systemctl --user daemon-reload
        systemctl --user enable ce-agent
        systemctl --user restart ce-agent
        info "Service started via systemd."
        warn "Note: You may need to run 'loginctl enable-linger \$USER' to keep the service running after logout."
    else
        warn "systemctl not found. Background service not configured."
    fi
fi

echo -e "\n${GREEN}=== Installation Complete! ===${NC}"
echo "ce-agent has been installed to $INSTALL_DIR"
echo "You can now use the 'ce-agent' command."
echo "Logs are available at $LOG_DIR"
echo "To test the installation, try: ce-agent token"

if ! echo "$PATH" | grep -q "$BIN_DIR"; then
    warn "Please restart your shell or run: export PATH=\"\$PATH:$BIN_DIR\""
fi
