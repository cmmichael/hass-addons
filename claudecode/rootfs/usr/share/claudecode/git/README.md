# Git-backed Home Assistant configuration

Version-controlling `/homeassistant` gives every change Claude makes a reviewable diff, a
one-command rollback and an off-box copy. This directory ships what that needs; nothing here
is installed automatically — the add-on never creates a repository or edits your files.

| File | What it is | Where it goes |
|---|---|---|
| `gitignore` | Whitelist-style `.gitignore` | `/homeassistant/.gitignore` (copy, then adapt) |
| `pre-commit` | Credential, dashboard and syntax check | stays here; run with `sh` |
| `claude-precommit.sh` | Claude Code hook that runs `pre-commit` before Claude's commits | stays here; wired in `~/.claude/settings.json` |
| `git_backup.sh` | Commit + push for changes made outside Claude sessions | `/homeassistant/shell/git_backup.sh` |

Claude: follow these steps only after the user agreed to set this up, and show them the
result of step 3 before the first commit.

## 1. Create the repository

```sh
cd /homeassistant
git init -b main
# Identity must be repo-local: ~/.gitconfig lives in the add-on's ephemeral filesystem
# and the HA Core container (step 7) has none either.
git config user.name  "<name>"
git config user.email "<email>"
cp /usr/share/claudecode/git/gitignore .gitignore
```

## 2. Adapt `.gitignore`

The template ignores everything that can hold a credential and treats `.storage/` and
`.claudecode/` as whitelists. Adapt it to the install:

- Add every file that holds a credential inline (some add-ons keep their YAML config in
  `/homeassistant`) — or better, move the credential to `secrets.yaml` and use `!secret`.
- Look at `ls .storage` and whitelist only what is valuable and token-free. Never whitelist
  `auth*`, `core.config_entries`, `application_credentials`, `cloud`, `mobile_app` or an
  integration's own token store.
- Keep the backup-file patterns at the bottom: git applies the last matching pattern, so
  `*.bak` above `!/.storage/lovelace.*` would re-include `.storage/lovelace.<id>.bak`.

## 3. Review what would be committed

```sh
git add -A --dry-run | less                    # every file of the first commit
git status --ignored --short | grep '^!!'      # what is being left out
rg -n -i '(api_key|password|token|secret|bearer)\s*:' --glob '*.yaml' --glob '!secrets.yaml' .
sh /usr/share/claudecode/git/pre-commit
```

Every hit from the `rg` line must be a `!secret` reference or moved into `secrets.yaml`
before the first commit — git history keeps a credential even after the file is fixed.

## 4. First commit, private remote

```sh
git add -A && git commit -m "Initial Home Assistant config"
```

The remote must be a **private** repository. Push auth: a fine-grained personal access
token limited to that one repository (Contents: read and write), embedded in the remote URL:

```sh
git remote add origin https://<user>:<token>@github.com/<user>/<repo>.git
git push -u origin main
```

The URL form works from both containers that push (this add-on and HA Core, step 7) —
`gh auth login` persists in this add-on but HA Core cannot use it. The cost: the token sits
in `.git/config`, which is inside HA backups and readable by anything with file access
(scheduled jobs cannot read `.git/`). Hence the one-repository scope. Never print
`git remote -v` into notifications, logs or reports.

## 5. Claude's commit check

Add to `~/.claude/settings.json` (merge with any existing `hooks`):

```json
"hooks": { "PreToolUse": [ { "matcher": "Bash", "hooks": [ { "type": "command",
  "command": "sh /usr/share/claudecode/git/claude-precommit.sh", "timeout": 120,
  "statusMessage": "Checking config files before commit" } ] } ] }
```

Every `git commit` Claude runs against `/homeassistant` is then blocked (with the reason)
if it would commit a credential, leave a storage dashboard ignored, or include a YAML /
JSON / Python / dashboard-JS file that does not parse. Do **not** use `core.hooksPath` or
`.git/hooks/`: `/homeassistant` is noexec for this add-on, and git then fails every commit
with `cannot exec … Permission denied`.

## 6. Session workflow

The add-on's `CLAUDE.md` tells Claude to work this way whenever `/homeassistant` is a
repository:

- Before the first change of a session, commit what changed outside the session (UI edits,
  HACS updates, registry churn) as `Pre-session snapshot` and push.
- After each logical change, commit and push with a message that says what changed and why.
  One change per commit.
- No `.bak` copies — the history is the backup.
- Never `git add -f` an ignored file and never `--no-verify`; extend the whitelist instead.

## 7. Safety net for changes outside sessions

```sh
mkdir -p /homeassistant/shell
cp /usr/share/claudecode/git/git_backup.sh /homeassistant/shell/
```

```yaml
# configuration.yaml — shell_command has no reload service: needs a core restart
shell_command:
  git_backup: 'sh /config/shell/git_backup.sh'
```

```yaml
# automation: weekly is enough when Claude commits its own changes
- id: git_config_backup
  alias: Git config backup (safety net)
  triggers:
    - trigger: time
      at: "04:00:00"
  conditions:
    - condition: time
      weekday: [sun]
  actions:
    - action: shell_command.git_backup
  mode: single
```

`shell_command` runs inside the HA Core container, which has git: the path there is
`/config`, not `/homeassistant`. This commit bypasses the Claude hook — the whitelist
`.gitignore` is what keeps credentials out of it.

## What to expect

- `core.device_registry` / `core.entity_registry` change on every start (`modified_at`,
  `supported_features`). That noise in the diffs is normal.
- HACS-managed `custom_components/` and `www/community/` are tracked by default: large,
  but a restore then needs no re-download. Ignore them if the repository size matters.

## Restoring from the repository

The repository is not a complete backup — HA's own backups are. What it cannot bring back:

- `secrets.yaml` — keep a copy in a password manager.
- Every integration in `core.config_entries` — set them up again.
- Users (`.storage/auth`): `condition: user` rules in dashboards reference user ids. Keep
  a sanitized list of user ids and names (nothing else) in the repository so those rules
  can be re-pointed after a restore.

## If a credential was committed

Rotate the credential first — once pushed, assume it is copied. Then `git rm --cached` the
file, add it to `.gitignore`, and purge it from history (`git filter-repo --path <file>
--invert-paths`, then force-push) if the repository ever left the machine. For the jobs
package token: `claude-job token rotate`.
