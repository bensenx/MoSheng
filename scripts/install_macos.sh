#!/bin/bash
# MoSheng macOS Installer
# Creates a .app bundle and sets up the Python environment
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
APP_NAME="MoSheng"
APP_DIR="$PROJECT_DIR/dist/${APP_NAME}.app"
CONTENTS="$APP_DIR/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"

echo "🔮 MoSheng macOS Installer"
echo "=========================="
echo ""

# --- Check prerequisites ---
echo "📋 Checking prerequisites..."

if ! command -v python3 &>/dev/null; then
    echo "❌ Python 3 not found. Install from https://python.org or: brew install python"
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  ✅ Python $PYTHON_VERSION"

# Check for uv
if ! command -v uv &>/dev/null; then
    echo "  📦 Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
echo "  ✅ uv $(uv --version 2>/dev/null | head -1)"

# --- Setup venv ---
echo ""
echo "📦 Setting up Python environment..."
cd "$PROJECT_DIR"

if [ ! -d ".venv" ]; then
    uv venv
fi
uv pip install -e . 2>/dev/null || uv pip install -r pyproject.toml 2>/dev/null || true
echo "  ✅ Dependencies installed"

# --- Create .app bundle ---
echo ""
echo "🏗️  Building ${APP_NAME}.app..."

rm -rf "$APP_DIR"
mkdir -p "$MACOS" "$RESOURCES"

# Info.plist
cat > "$CONTENTS/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>MoSheng</string>
    <key>CFBundleDisplayName</key>
    <string>魔声 MoSheng</string>
    <key>CFBundleIdentifier</key>
    <string>com.mosheng.app</string>
    <key>CFBundleVersion</key>
    <string>1.1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.1.0</string>
    <key>CFBundleExecutable</key>
    <string>mosheng</string>
    <key>CFBundleIconFile</key>
    <string>icon</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
    <key>NSMicrophoneUsageDescription</key>
    <string>MoSheng needs microphone access for speech recognition.</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSUIElement</key>
    <false/>
</dict>
</plist>
PLIST

# Launcher script
cat > "$MACOS/mosheng" << LAUNCHER
#!/bin/bash
# MoSheng launcher
SCRIPT_DIR="\$(cd "\$(dirname "\$0")" && pwd)"
PROJECT_DIR="$PROJECT_DIR"

cd "\$PROJECT_DIR"

# Activate venv
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# Run the app
exec python3 main.py "\$@"
LAUNCHER
chmod +x "$MACOS/mosheng"

# Copy icon
if [ -f "$PROJECT_DIR/assets/icon.png" ]; then
    cp "$PROJECT_DIR/assets/icon.png" "$RESOURCES/icon.png"
    # Try to create .icns if sips is available
    if command -v sips &>/dev/null && command -v iconutil &>/dev/null; then
        ICONSET="$RESOURCES/icon.iconset"
        mkdir -p "$ICONSET"
        for size in 16 32 64 128 256 512; do
            sips -z $size $size "$PROJECT_DIR/assets/icon.png" --out "$ICONSET/icon_${size}x${size}.png" 2>/dev/null || true
            double=$((size * 2))
            sips -z $double $double "$PROJECT_DIR/assets/icon.png" --out "$ICONSET/icon_${size}x${size}@2x.png" 2>/dev/null || true
        done
        iconutil -c icns "$ICONSET" -o "$RESOURCES/icon.icns" 2>/dev/null || true
        rm -rf "$ICONSET"
        echo "  ✅ App icon created"
    fi
fi

echo "  ✅ ${APP_NAME}.app created at: $APP_DIR"

# --- Summary ---
echo ""
echo "✨ Installation complete!"
echo ""
echo "To launch MoSheng:"
echo "  1. Double-click: $APP_DIR"
echo "  2. Or from terminal: open '$APP_DIR'"
echo ""
echo "⚠️  First launch: macOS may ask for microphone & accessibility permissions."
echo "   Grant them in System Settings → Privacy & Security."
echo ""
echo "To move to Applications:"
echo "  cp -r '$APP_DIR' /Applications/"
