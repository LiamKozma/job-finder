#!/usr/bin/env sh
# Runs the job finder every morning at 8:00 via launchd (macOS). Remove with: sh scripts/schedule_mac.sh --remove
LABEL=com.jobfinder.daily
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
if [ "$1" = "--remove" ]; then launchctl unload "$PLIST" 2>/dev/null; rm -f "$PLIST"; echo "Removed."; exit 0; fi
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$REPO/run.sh</string><string>--new-first</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$REPO/data/last-run.log</string>
  <key>StandardErrorPath</key><string>$REPO/data/last-run.log</string>
</dict></plist>
PL
mkdir -p "$REPO/data"
launchctl unload "$PLIST" 2>/dev/null; launchctl load "$PLIST" && echo "Scheduled daily at 8:00."
