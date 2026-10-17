# Git-backed Home Assistant configuration

Version-controlling `/homeassistant` gives every change Claude makes a reviewable diff, a
one-command rollback and an off-box copy. This directory ships what that needs; nothing here
is installed automatically — the add-on never creates a repository or edits your files.

| File | What it is | Where it goes |
|---|---|---|
| `gitignore` | Whitelist-style `.gitignore` | `/homeassistant/.gitignore` (copy, then adapt) |
| `/usr/local/share/claudecode/git-hooks/pre-commit` | Credential, dashboard and syntax check | stays there; enabled with `core.hooksPath` |
| `git_backup.sh` | Commit + push for changes made outside Claude sessions | `/homeassistant/shell/git_backup.sh` |

## What the user does

Two things only the user can do on GitHub (or any git host):

1. Create an **empty, private** repository (no README, no licence — the first push fills it).
2. Create a **fine-grained personal access token** limited to that one repository, with
   *Contents: read and write*.

Then ask Claude to "set up git backup of my config to <repository URL>" and hand over the
token when asked. Claude asks for the name and email to commit under, and shows what the
first commit would contain before making it.

## What Claude does

Follow these steps only after the user asked for the setup, and show them the result of
step 3 before the first commit.

### 1. Create the repository

```sh
cd /homeassistant
git init -b main
# Identity must be repo-local: ~/.gitconfig lives in the add-on's ephemeral filesystem
# and the HA Core container (step 7) has none either.
git config user.name  "<name>"
git config user.email "<email>"
git config core.hooksPath /usr/local/share/claudecode/git-hooks
cp /usr/share/claudecode/git/gitignore .gitignore
```

`core.hooksPath` turns on the commit check for every commit made in this add-on, Claude's
and the user's at the terminal: it refuses a commit that would include a credential, leave
a storage dashboard ignored, or contain a YAML / JSON / Python / dashboard-JS file that
does not parse. The hook has to live under `/usr/local/`: the add-on's AppArmor profile
does not let it execute anything in `/homeassistant`, so a hook there (`.git/hooks/` or a
`core.hooksPath` inside the config directory) fails every commit with
`cannot exec … Permission denied`.

### 2. Adapt `.gitignore`

The template ignores everything that can hold a credential and treats `.storage/` and
`.claudecode/` as whitelists. Adapt it to the install:

- Add every file that holds a credential inline (some add-ons keep their YAML config in
  `/homeassistant`) — or better, move the credential to `secrets.yaml` and use `!secret`.
  Outside `.storage/` and `.claudecode/` the template is a blacklist: it knows the common
  cases (key files, token caches, Zigbee2MQTT, service-account JSON), not every add-on.
- Look at `ls .storage` and whitelist only what is valuable and token-free. Never whitelist
  `auth*`, `core.config_entries`, `application_credentials`, `cloud`, `mobile_app` or an
  integration's own token store.
- Keep the backup-file patterns at the bottom: git applies the last matching pattern, so
  `*.bak` above `!/.storage/lovelace.*` would re-include `.storage/lovelace.<id>.bak`.

### 3. Review what would be committed

```sh
git add -A
git status --short | less                      # every file of the first commit
git status --ignored --short | grep '^!!'      # what is being left out
# credential-looking keys in everything staged (YAML, JSON, conf ...), HACS code left out
git ls-files -z -- . ':!custom_components' ':!www/community' | xargs -0 -r rg -n -i \
  -e '(api_?key|password|passwd|token|secret|bearer|psk|network_key|private_key|\bkey)["'\'']?\s*[:=]' \
  -e 'PRIVATE KEY-----'
sh /usr/local/share/claudecode/git-hooks/pre-commit
```

Every hit from the `rg` line must be a `!secret` reference, moved into `secrets.yaml`, or
its file ignored before the first commit (ESPHome `encryption: key:`, a Zigbee
`network_key`, dashboard URLs with a token) — git history keeps a credential even after
the file is fixed.

### 4. First commit, private remote

```sh
git commit -m "Initial Home Assistant config"
git remote add origin https://<user>:<token>@github.com/<user>/<repo>.git
git push -u origin main
```

The token in the remote URL works from both containers that push (this add-on and HA
Core, step 7) — `gh auth login` persists in this add-on but HA Core cannot use it. The
cost: the token sits in `.git/config`, which is inside HA backups and readable by anything
with file access (scheduled jobs cannot read `.git/`). Hence the one-repository scope.
Never print `git remote -v` into notifications, logs or reports.

### 5. Session workflow

The add-on's `CLAUDE.md` tells Claude to work this way whenever `/homeassistant` is a
repository:

- Before the first change of a session, commit what changed outside the session (UI edits,
  HACS updates, registry churn) as `Pre-session snapshot` and push.
- After each logical change, commit and push with a message that says what changed and why.
  One change per commit.
- No `.bak` copies — the history is the backup.
- Never `git add -f` an ignored file and never `--no-verify`; extend the whitelist instead.

### 6. Safety net for changes outside sessions

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
`/config`, not `/homeassistant`. The hook path does not exist in that container, so git
skips the check there — the `.gitignore` alone keeps credentials out of these commits.
After installing an add-on or integration that writes into the config directory, look at
`git status` before the next backup runs. The script exits non-zero with git's message
when the add or commit fails; the push output is its normal result.

## What to expect

- `core.device_registry` / `core.entity_registry` change on every start (`modified_at`,
  `supported_features`). That noise in the diffs is normal.
- HACS-managed `custom_components/` and `www/community/` are tracked by default: large,
  but a restore then needs no re-download. Ignore them if the repository size matters.
- The check reads the staged content of every staged file, so a file that does not parse
  blocks the commit even when Claude's change did not touch it — typically a UI edit, or
  a file staged while HA or an add-on was half-way through writing it. Fix it or stage it
  again, or leave it out with `git restore --staged <file>`; `--no-verify` only when the
  user says so.

## Restoring from the repository

The repository is not a complete backup — HA's own backups are. What a clone does not bring
back:

- `.git/config`: the repo-local identity, `core.hooksPath` and the remote with its token
  (step 1 and 4 again, with a new token).
- `secrets.yaml` — keep a copy in a password manager.
- Every integration in `core.config_entries` — set them up again.
- Users (`.storage/auth`): `condition: user` rules in dashboards reference user ids. Keep
  a sanitized list of user ids and names (nothing else) in the repository so those rules
  can be re-pointed after a restore.
- Claude's own settings (`.claudecode/settings.json`, memory): ignored by the template
  because they can hold credentials. Whitelist a file deliberately if it is token-free.

## If a credential was committed

Rotate the credential first — once pushed, assume it is copied. Then `git rm --cached` the
file, add it to `.gitignore`, and purge it from history (`git filter-repo --path <file>
--invert-paths`, then force-push) if the repository ever left the machine. For the jobs
package token: `claude-job token rotate`.
