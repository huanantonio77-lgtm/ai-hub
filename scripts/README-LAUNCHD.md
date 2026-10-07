# Launchd scripts on macOS — TCC note

**Rule:** launchd agents CANNOT execute scripts located in TCC-protected paths:
`~/Desktop`, `~/Documents`, `~/Downloads` (and iCloud-synced dirs).
Symptom: `/bin/bash: ...: Operation not permitted`, `launchctl list` exit code 126.

**Fix (used in s203):** copy the script to `~/Library/LaunchAgents/ai-hub-scripts/`
and point `ProgramArguments[1]` there via PlistBuddy:

    NEW_DIR="$HOME/Library/LaunchAgents/ai-hub-scripts"
    mkdir -p "$NEW_DIR"
    cp scripts/<name>.sh "$NEW_DIR/<name>.sh"
    chmod 755 "$NEW_DIR/<name>.sh"
    /usr/libexec/PlistBuddy -c "Set :ProgramArguments:1 $NEW_DIR/<name>.sh" \
      "$HOME/Library/LaunchAgents/com.ai-hub.<name>.plist"
    launchctl bootout   gui/$(id -u)/com.ai-hub.<name> 2>/dev/null || true
    launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.ai-hub.<name>.plist"

**Note:** `scripts/<name>.sh` in-repo remains the canonical SOURCE.
After editing it, re-copy to `~/Library/LaunchAgents/ai-hub-scripts/`.

**Edit source → deploy:**
    cp scripts/<name>.sh "$HOME/Library/LaunchAgents/ai-hub-scripts/<name>.sh"
    chmod 755 "$HOME/Library/LaunchAgents/ai-hub-scripts/<name>.sh"
    # plist unchanged; next fire picks up the new content
