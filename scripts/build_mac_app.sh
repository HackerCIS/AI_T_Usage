#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/Namum.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/logos"
cp "$ROOT/mac/Info.plist" "$APP/Contents/Info.plist"
cp "$ROOT/assets/logos/"*.png "$APP/Contents/Resources/logos/"
swiftc -O -sdk "$(xcrun --show-sdk-path)" \
  -framework AppKit -framework WebKit \
  -o "$APP/Contents/MacOS/Namum" \
  "$ROOT/mac/Namum.swift"
codesign --force --sign - "$APP"
echo "built $APP"
