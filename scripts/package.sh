#!/bin/bash
# Build and zip the plugin in the layout Decky's "Install plugin from ZIP" expects.
# The folder inside stays unversioned: Decky keys plugin settings by folder name.
set -euo pipefail
cd "$(dirname "$0")/.."
version="$(node -p 'require("./package.json").version')"
zipname="droid-deck-loader-v${version}.zip"
npm run build
rm -rf out && mkdir -p out/droid-deck-loader
cp -a plugin.json package.json main.py py_modules dist out/droid-deck-loader/
rm -f out/droid-deck-loader/dist/*.map
find out -name __pycache__ -type d -prune -exec rm -rf {} +
(cd out && zip -qr "${zipname}" droid-deck-loader)
echo "out/${zipname}"
