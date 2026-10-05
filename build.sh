#!/usr/bin/env bash
# Build "dist/Karaoke Grabber.app" with PyInstaller.
# Run from the project root with the venv activated:  ./build.sh
# (run.sh does that for you.)
set -euo pipefail

APP_NAME="Karaoke Grabber"
BUNDLE_ID="com.mstahl302.karaokegrabber"
VERSION="$(python -c 'import karaokegrab; print(karaokegrab.__version__)')"
APP="dist/${APP_NAME}.app"
PLIST="${APP}/Contents/Info.plist"

rm -rf build dist "${APP_NAME}.spec"

# arm64 only: this is an Apple Silicon Mac and the app is for personal use.
pyinstaller \
  --name "$APP_NAME" \
  --windowed \
  --icon assets/icon.icns \
  --osx-bundle-identifier "$BUNDLE_ID" \
  --target-arch arm64 \
  --noconfirm \
  --log-level WARN \
  main.py

# Version and app-menu name in Info.plist, then re-sign (ad hoc), since
# editing the plist breaks PyInstaller's signature.
plutil -replace CFBundleShortVersionString -string "$VERSION" "$PLIST"
plutil -replace CFBundleVersion -string "$VERSION" "$PLIST"
plutil -replace CFBundleDisplayName -string "$APP_NAME" "$PLIST"
plutil -replace NSHumanReadableCopyright -string "MIT License" "$PLIST"
codesign --force --deep --sign - "$APP"

rm -rf build "${APP_NAME}.spec"
echo
echo "Built: ${APP}  (version ${VERSION})"
echo "Run it:  open \"${APP}\""
