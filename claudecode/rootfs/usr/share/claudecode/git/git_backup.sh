#!/bin/sh
# Safety-net commit + push of the HA config directory, for changes made outside Claude
# sessions (UI edits, HACS updates, registry churn). Shipped by the Claude Code add-on:
# /usr/share/claudecode/git/git_backup.sh (see README.md next to it).
#
# Copy it to /homeassistant/shell/git_backup.sh and call it from Home Assistant:
#
#   shell_command:
#     git_backup: 'sh /config/shell/git_backup.sh'
#
# It runs INSIDE the HA Core container (which has git), so the path is /config there,
# not /homeassistant. Push auth comes from the repository's own config (a credential in
# the remote URL or a repo-local credential helper) — nothing in the HA Core container's
# home directory survives an HA update.
cd /config || exit 1

git add -A >/dev/null 2>&1

if ! git diff --cached --quiet; then
  git commit -m "Auto-backup: $(date '+%Y-%m-%d %H:%M')" >/dev/null 2>&1
fi

# Push even when nothing was committed: a no-op push is cheap and also delivers earlier
# commits whose push failed (network down).
git push origin HEAD 2>&1
