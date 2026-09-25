#!/usr/bin/env sh
# macOS / Linux launcher
cd "$(dirname "$0")" && exec python3 -m jobfinder run "$@"
