# Claude Code — Home Assistant Add-on

## Where you are running

You are running inside a **Docker container** that is a **Home Assistant OS
add-on** — NOT on the HA host, and NOT inside Home Assistant Core's container.
You are in a separate, sandboxed container.

- The container's own filesystem (`/usr`, `/etc`, most of `/root`, globally
  installed packages) is **ephemeral** — rebuilt from scratch on every add-on
  update. Don't expect changes there to persist. The exception is the
  symlinked `~/.claude*` paths — see the next bullet.
- Only **mapped directories** persist across rebuilds: `/homeassistant`,
  `/share`, `/media`, `/ssl`, `/backup`, `/addon_configs`. Your own config
  persists because `~/.claude` is symlinked into `/homeassistant/.claudecode`.
- To install packages that survive rebuilds, use the `extra_npm_packages`
  add-on option instead of `npm install -g` directly.
- The base OS is **Alpine Linux** — use `apk`, not `apt`. Most of `/usr` is
  read-only via an AppArmor profile; an `EACCES` on a system path is usually
  the AppArmor profile, not a normal permission problem.

## Path mapping

Paths here differ from HA Core and most documentation:

- `/homeassistant` = the HA configuration directory (equivalent to `/config`
  in HA Core)
- `/config` does **not** exist — always use `/homeassistant`
- When the user or docs mention `/config/...`, translate to `/homeassistant/...`

## Available paths

| Path | Description | Access |
|------|-------------|--------|
| `/homeassistant` | HA configuration | read-write |
| `/share` | Shared folder | read-write |
| `/media` | Media files | read-write |
| `/addon_configs` | This add-on's own config directory | read-write |
| `/ssl` | SSL certificates | read-only |
| `/backup` | Backups | read-only |

## Interacting with Home Assistant

HA Core runs in a separate container. You **must not** try to manage its
process directly (even though `docker` access exists) — interact with it
through the proper interfaces:

- **`homeassistant` MCP server** (present when `enable_mcp` is on — the
  default) — query entity states, call services, read history and the error
  log. Preferred for anything entity/service related.
- **`ha` CLI** — Supervisor-level operations: `ha core restart`,
  `ha core check`, `ha core logs`, `ha core info`, `ha addons ...`.
- To **restart or reload** HA, use `ha core restart` or the MCP server / API.
  Never try to kill or signal processes.

## Available tools

Beyond the standard Alpine userland, these are pre-installed:

- `gh` — GitHub CLI
- `docker` — Docker CLI (the add-on has Docker socket access)
- `jq`, `rg` (ripgrep), `7z`, `socat` — common utilities
- `mbpoll`, plus Python `pymodbus` / `pyserial` — Modbus / serial device tools
- `vim`, `nano` — editors

## Reading Home Assistant logs

**Log levels (most to least verbose):** `debug` (only if enabled in
`configuration.yaml`), `info` (default), `warning`, `error`.

```bash
# Recent core logs
ha core logs 2>&1 | tail -100

# Filter by keyword
ha core logs 2>&1 | grep -i keyword

# Errors only
ha core logs 2>&1 | grep -iE "(error|exception)"

# Or read the log file directly
tail -100 /homeassistant/home-assistant.log
```

**Enable debug logging for an integration** — add to `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.YOUR_INTEGRATION: debug
```

`_LOGGER.debug()` calls are invisible unless the logger level is `debug`. Use
`_LOGGER.info()` / `_LOGGER.warning()` for logs that should always appear.

## Scheduled jobs

Unattended Claude runs ("jobs") live in `~/.claude/jobs/` (the same directory as
`/homeassistant/.claudecode/jobs/`). Each `*.md` file is one job: YAML frontmatter
(description, model, timeout, max_cost_usd, tools, paths, notify map, optional input)
plus the prompt. Home Assistant triggers them on a schedule via the add-on's job
endpoint; results appear as `sensor.claude_job_<slug>` (hyphens become underscores)
and as notifications. These jobs are unrelated to Claude Code's in-session Task tools
and to Home Assistant's `ai_task` integration — different mechanisms, deliberately
different name.

- List jobs:                  `claude-job list`
- Last result:                `~/.claude/jobs/state/<name>.json`
- Run history:                `~/.claude/jobs/logs/<name>.jsonl` (one JSON line per run)
- Check a definition:         `claude-job validate <name>` (`--json` for machine-readable)
- See exactly what would run: `claude-job dry-run <name>` (composed settings, prompt and
                              command line; spends nothing)
- Run one by hand:            `claude-job run <name>` — from inside this session it starts
                              the run in the background and prints a run id; the result
                              lands in `~/.claude/jobs/state/<name>.json` a few minutes later
- Pause:                      `claude-job disable <name>` (`enable`, `force-run` and
                              `token` are for the human at the terminal and will prompt)
- Examples and reference:     `/usr/share/claudecode/jobs/*.md`, and the add-on README

Jobs are read-only by construction: write/edit/web tools are rejected by the validator,
Bash is limited to the read-only `ha` subcommands in `/usr/share/claudecode/job-ha-allowlist`,
file reads exist only through the job's declared `paths:` (under /homeassistant, /share,
/media), and a new job you author should ship `enabled: false` until a human has reviewed
it. Put the load-bearing number in the job's headline. Do not use `claude-job run` as a
way to "do the work" of this conversation — it is for scheduled or one-off headless runs.

## Git-backed configuration

Check once per session: `git -C /homeassistant rev-parse --is-inside-work-tree`.

**If `/homeassistant` is a git repository**, every config change goes through it:

- Before the first change of the session, commit whatever changed outside the session
  (UI edits, HACS updates, registry churn) as `Pre-session snapshot`, and push if a
  remote is configured.
- After each logical change, commit (and push) with a message saying what changed and
  why. One change per commit — don't batch unrelated changes.
- The history is the backup: no `.bak` copies next to edited files.
- Never `git add -f` an ignored file and never commit with `--no-verify` unless the user
  asks. If something valuable is ignored, extend the `.gitignore` whitelist deliberately.
- Credentials go in `secrets.yaml` via `!secret`, never in a tracked file.
  `claudecode_jobs.yaml` (the add-on's token-bearing package) must never be committed.
- Git hooks cannot run from `/homeassistant` (noexec mount — `core.hooksPath` pointing
  there fails every commit). The commit check is a Claude Code hook instead:
  `/usr/share/claudecode/git/claude-precommit.sh`.

**If it is not a repository** and the user asks for a config change, offer once to set
it up — don't do it unasked. The steps, a whitelist `.gitignore`, the commit check and a
safety-net backup script are in `/usr/share/claudecode/git/` (start with its README.md).

## Working on a live Home Assistant

- **Read live state before acting** on or explaining any sensor, helper or "the last X":
  a fresh read of every entity involved now (plus history when the question is what
  changed), never a value read earlier in the session. REST works when the MCP server
  times out: `curl -s -H "Authorization: Bearer $SUPERVISOR_TOKEN" http://supervisor/core/api/states/<entity_id>`.
- **Apply with the lightest step.** Most YAML domains have a reload service
  (`automation.reload`, `script.reload`, `template.reload`, `input_*.reload`, ...);
  `shell_command`, `logger`, `recorder`, `utility_meter`, `history_stats`, `sql` and
  `packages` changes need a restart. Run `ha core check` before every restart.
- **A restart can end this session** (it resumes automatically afterwards). Finish the
  edits and write down conclusions and next steps before you restart — never make a
  restart the middle step of an unfinished plan.
- **Don't hand-edit `.storage/` while HA runs.** HA keeps it in memory and rewrites it on
  shutdown, so an edit followed by a restart is silently reverted. Use the WebSocket API
  instead — `ha-ws` sends commands (`config/entity_registry/update` with
  `new_entity_id`, `config/device_registry/update`, `lovelace/config/save`,
  `energy/save_prefs`). With no API for a field: `ha core stop`, edit, `ha core start`.
- **Dashboards are cached** in HA and in every browser. After a change, browsers need a
  hard refresh. Never "flush" with a no-op save in the raw configuration editor — it
  writes HA's stale copy back over your edit. Files under `/local/` (= `www/`) are cached
  for 31 days: change a `?v=N` query parameter on the resource URL with each deploy.
- **`shell_command` runs in the HA Core container**, so its scripts are referenced as
  `/config/...` even though you edit them at `/homeassistant/...`. Nothing under
  `/homeassistant` is executable from *this* container: run scripts as `sh x.sh` /
  `python3 x.py`, not `./x.sh`.
- **Template booleans:** in `variables:` and other native-type templates, emit
  `{{ true }}` / `{{ false }}` or an expression. A bare `false` written as text in an
  `{% if %}` branch renders the string "false", which is truthy.
- **Restarts replay states.** `unavailable → <restored value>` on startup is a real state
  transition, so a state trigger fires on every restart unless it has
  `not_from: [unavailable, unknown]`. With `attribute:`, `from`/`not_from` compare the
  attribute (which is `None` while unavailable), so that guard does not work there —
  trigger on the state, or test the attribute in a condition.
- **Statistics come back in display units** (`statistics_during_period` returns kWh even
  when the metadata says Wh); pass `units` explicitly instead of converting.
- **Design rationale goes in the config:** an automation's `description:` or a YAML
  comment should say why a threshold, `for:` or guard exists. Read those before changing
  behaviour, and write them for what you add.
- **Supervisor stuck on "updating"** / unhealthy after a failed update: `ha supervisor
  restart`; it retries the update by itself. Diagnose with `ha resolution info`.

## User instructions

The add-on regenerates this file (`~/.claude/CLAUDE.md`) on every start, so
don't edit it directly — changes are lost on restart. For your own persistent
instructions, edit `~/.claude/CLAUDE.user.md` (created automatically, never
overwritten by the add-on). It is imported below.

@~/.claude/CLAUDE.user.md
