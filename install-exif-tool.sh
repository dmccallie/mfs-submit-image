#!/usr/bin/env bash
set -euo pipefail

EXIFTOOL_SITE="https://exiftool.org"
INSTALL_DIR="/usr/local/lib/exiftool"
BIN_LINK="/usr/local/bin/exiftool"

sudo apt-get update
sudo apt-get install -y curl perl

LATEST_VERSION=$(curl -fsSL https://exiftool.org/ver.txt)

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

cd "$TMP_DIR"

ARCHIVE="Image-ExifTool-${LATEST_VERSION}.tar.gz"
curl -fsSL "${EXIFTOOL_SITE}/${ARCHIVE}" -o "$ARCHIVE"
tar -xzf "$ARCHIVE"

EXTRACTED_DIR="Image-ExifTool-${LATEST_VERSION}"

sudo rm -rf "$INSTALL_DIR"
sudo mkdir -p "$INSTALL_DIR"
sudo cp -r "$EXTRACTED_DIR"/* "$INSTALL_DIR"

sudo tee "$BIN_LINK" >/dev/null <<'EOF'
#!/usr/bin/env bash
exec perl /usr/local/lib/exiftool/exiftool "$@"
EOF

sudo chmod +x "$BIN_LINK"

exiftool -ver
