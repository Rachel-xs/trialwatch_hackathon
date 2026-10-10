#!/usr/bin/env bash
# Schedule run_daily.sh every day on this Mac (launchd). If the Mac is asleep at that time,
# launchd runs the job when it wakes up. Undo with: bash scripts/install_daily_mac.sh --uninstall
#
#   bash scripts/install_daily_mac.sh you@example.com            # every day at 07:13
#   HOUR=20 MINUTE=5 bash scripts/install_daily_mac.sh you@mail  # another time
#   SEARCH=1 bash scripts/install_daily_mac.sh you@mail          # with agent / coverage search
set -euo pipefail
LABEL=org.trialwatch.daily
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ "${1:-}" = "--uninstall" ]; then
  launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"; echo "removed $LABEL"; exit 0
fi

CONTACT="${1:?usage: bash scripts/install_daily_mac.sh you@example.com}"
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
HOUR="${HOUR:-7}"; MINUTE="${MINUTE:-13}"

case "$PROJECT" in
  "$HOME/Desktop"*|"$HOME/Documents"*|"$HOME/Downloads"*)
    echo "!! The project is in $PROJECT."
    echo "!! macOS blocks background jobs from reading Desktop, Documents and Downloads, so the daily run"
    echo "!! would fail with 'Operation not permitted'. Either move the project, e.g.:"
    echo "!!     mv \"$PROJECT\" ~/trialwatch && cd ~/trialwatch && bash scripts/install_daily_mac.sh $CONTACT"
    echo "!! or give /bin/bash Full Disk Access (System Settings > Privacy & Security > Full Disk Access)."
    if [ "${FORCE:-0}" != "1" ]; then echo "!! Re-run with FORCE=1 if you chose Full Disk Access."; exit 1; fi;;
esac

mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT/out/live/daily"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>-lc</string>
    <string>cd "$PROJECT" &amp;&amp; SEARCH=${SEARCH:-0} bash run_daily.sh "$CONTACT"</string>
  </array>
  <key>StartCalendarInterval</key><dict>
    <key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>$MINUTE</integer>
  </dict>
  <key>StandardOutPath</key><string>$PROJECT/out/live/daily/launchd.log</string>
  <key>StandardErrorPath</key><string>$PROJECT/out/live/daily/launchd.log</string>
</dict></plist>
PL
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "scheduled: every day at $(printf '%02d:%02d' "$HOUR" "$MINUTE"), project $PROJECT"
echo "run it once now to test:   launchctl kickstart gui/$(id -u)/$LABEL"
echo "logs:                      $PROJECT/out/live/daily/launchd.log and out/live/daily/<date>/run.log"
