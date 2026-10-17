#!/bin/sh
# Claude Code PreToolUse hook (matcher: Bash) that runs the config-repo pre-commit check
# before every `git commit` Claude issues against /homeassistant. Shipped by the Claude
# Code add-on: /usr/share/claudecode/git/claude-precommit.sh (see README.md next to it).
#
# Wire it in ~/.claude/settings.json:
#   "hooks": { "PreToolUse": [ { "matcher": "Bash", "hooks": [ { "type": "command",
#     "command": "sh /usr/share/claudecode/git/claude-precommit.sh", "timeout": 120 } ] } ] }
#
# Reads the tool call JSON on stdin. Anything that is not a `git commit` passes. A commit
# is checked only when it targets the config repo — Claude's working directory is inside
# it, or the command names it — so commits in other repositories are never blocked by an
# unrelated broken config file. Exit 2 blocks the tool call and shows Claude the reason.
# `--no-verify` in the command skips the check (only when the user asked for that).
REPO=${HA_CONFIG_REPO:-/homeassistant}
HERE=$(cd "$(dirname "$0")" && pwd)
input=$(cat)
c=$(printf '%s' "$input" | jq -r '.tool_input.command // ""' 2>/dev/null)
cwd=$(printf '%s' "$input" | jq -r '.cwd // ""' 2>/dev/null)
case "$c" in *"git commit"*|*"git -C "*" commit"*) ;; *) exit 0 ;; esac
case "$c" in *--no-verify*) exit 0 ;; esac
case "$cwd/" in "$REPO"/*) ;; *) case "$c" in *"$REPO"*) ;; *) exit 0 ;; esac ;; esac
[ -d "$REPO/.git" ] || exit 0
out=$(cd "$REPO" && sh "$HERE/pre-commit" 2>&1) && exit 0
printf '%s\n' "$out" >&2
exit 2
