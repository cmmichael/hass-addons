# Keeping Claude Code updates across add-on restarts

> A proposal for the add-on to stop losing the Claude Code release it has already updated to every time it restarts. Nothing is built yet. The decision it asks for is whether to keep the update as a **cached package that is reinstalled at boot** (recommended, no AppArmor change) or as an **executable copy on `/data`** (simpler, but a security-profile change). It also explains why rebuilding the image more often is not the answer, and reports that add-on releases today do not refresh Claude Code at all, because of Docker's build cache.

_status: proposal, for the maintainer's decision · 2026-10-28 · follows #45 (apply_claude_updates) and #46_

## The problem

Claude Code updates itself in the background. On this add-on it runs `npm` over `/usr/local/lib/node_modules/@anthropic-ai/claude-code`, which the AppArmor profile has allowed since con.10. That directory is in the container layer, and every add-on restart recreates the container. The Dockerfile's health-check comment says so, and Supervisor removes the container when it stops it. So every restart throws the update away:

1. **The fallback.** The add-on comes back on the release the image verified at build time (`/etc/claude-code-version`), however old that is.
2. **The re-download.** Claude Code downloads the newest release again. The platform package is about 130 MB compressed and 275 MB unpacked.
3. **The old session.** Since #45, the idle-update watcher moves the session onto the new release once it is idle. Until then the session runs the build's release. Without #45, it runs that release until the next manual restart.

Measured on the reference install (con.20, built 2026-09-18 with 2.1.276):

| | |
| --- | --- |
| Releases between the build and today | 34 in 39 days (2.1.276 → 2.1.312) |
| Updates downloaded by one container since its last start (26 Oct) | 3 (2.1.310, 2.1.311, 2.1.312), each ~130 MB |
| What the next restart would come back on | 2.1.276, 36 releases old |
| Offline reinstall of 2.1.312 from a warm npm cache | 7.3 s, no network |

The cost is not dramatic per restart. But it recurs: on every restart, the session goes back up to a month into the past, and the same 130 MB comes down again. The AVX history in `install-claude.sh` adds one requirement to any fix: a remembered release must still be checked before it is trusted, because a release that runs today can be replaced by one that does not.

## What already exists

- **`auto_update_claude`, default off.** It runs `npm update -g` at boot, smoke-tests the result and rolls back to the build's release if it does not run. It goes to *latest*, not to the release this install had already moved onto. Its boot can spend up to 300 s in `npm` against the registry, which is why the health check's `start-period` is 900 s.
- **`apply_claude_updates` (#45).** It moves idle sessions onto whatever is installed. It only checks a release once it is installed, and it is not involved at boot.
- **Persistent storage.** `/data` is persistent and private to the add-on, with AppArmor `rwk` and no `x`. `/homeassistant` is persistent too, and execution there is deliberately denied.

## Option A: run the CLI from `/data`

Install Claude Code into a prefix on `/data`, for example `/data/claude-cli`, and put it first on `PATH`. Point `npm_config_prefix` at it, so that Claude's own updater updates it in place. Grant it `ix` in `apparmor.txt`.

- **For.** Updates survive by construction. There is no reinstall at boot and no new moving part.
- **Against.** It creates the first writable *and* executable location on persistent storage. Today a file planted in persistent storage, by a compromised session, a malicious MCP server or a tool run, cannot run after a restart. With this change, anything written to that prefix can. The profile's split between "persistent" and "executable" is the property this would give up.
- **Also.** The image's verified release stops being the fallback, so a remembered release that fails needs its own rollback path anyway. `/data` grows by about 275 MB per kept release, and `/data` is in Home Assistant backups unless it is excluded.

## Option B (recommended): remember the release, reinstall it from a cached package

Keep execution where it is, in the container layer under `/usr/local`. Persist only two things on `/data`: *which* release this install had moved onto, and the npm **cache** holding its package, which is not executable and need not be.

1. **The cache.** Set `npm_config_cache=/data/npm-cache` in the image environment. Claude's own updater and every `npm` the add-on runs then fill the cache on `/data` instead of the throwaway `/root/.npm`.
2. **Recording the release.** When the watcher from #45 has verified a release, meaning it answered `--version`, it writes that version to `/data/claudecode/cli-version`. Only checked releases are remembered.
3. **At boot,** a new step runs before `check_claude`:
   - If `cli-version` is newer than the build's release, run `npm install -g --offline @anthropic-ai/claude-code@<version>`. That took 7.3 s on the reference install, with no registry traffic.
   - Probe it with the existing `claude_responds`.
   - If the probe fails, or the cache misses, run `npm install -g @anthropic-ai/claude-code@$BUILT_VERSION`, the same rollback `maybe_update_claude` already has, and warn.
   - In every case the add-on boots, as every step does now.
4. **Pruning.** Keep the cache bounded to the remembered release and the build's release. Run `npm cache clean` for anything else after a successful boot install, or prune by package name. Add `/data/npm-cache` to `backup_exclude` in `config.yaml`, because it is a cache.

- **For.** No AppArmor change, and the "persistent is never executable" property stays. The fallback stays the image's verified release, and a remembered release is checked the same way as an updated one. A warm boot costs seconds, not a 130 MB download. If the registry is unreachable at boot, the remembered release still installs, which is better than today.
- **Against.**
  - A boot step of about 7 s on fast storage, and longer on an SD card. That is well inside the existing `start-period`.
  - One more file on `/data`.
  - The cache's size: about 130 MB per kept package, so about 260 MB.
  - It depends on `npm install --offline` honouring the cache for these packages. That was measured, but it is an npm behaviour, not a contract.
- **Relation to `auto_update_claude`.** Option B makes `auto_update_claude` mostly redundant. Claude's own updater keeps the release current while the add-on runs, and Option B carries it across restarts. The option could be kept to mean "also go to *latest* at boot", or deprecated.

## Option C: do nothing

Rely on add-on releases to raise the build's release, since each build installs the newest working release. That works only as often as the add-on is released and updated: today that is con.20 against 34 Claude Code releases. #45 already limits the damage to "an old release until the session is idle". This is a reasonable choice if the boot step in B is not wanted.

## Option D: rebuild the image more often ("just take latest at build")

`install-claude.sh` already installs the newest release that runs. There is no pin. So it is tempting to refresh the image instead: rebuild nightly, or on a schedule, and let each build take the newest release. Two facts argue against it.

**1. A rebuild does not reliably take the newest release.** Supervisor 2026.10.4 builds add-ons with `docker buildx build . --tag … --pull --build-arg BUILD_VERSION=… …` (`supervisor/apps/build.py`, `get_docker_args`). `--pull` refreshes the base image, and there is no `--no-cache`. `Rebuild` removes the image, but BuildKit's build cache is separate and survives that. In this Dockerfile, `RUN install-claude.sh` (line 109) comes before `ARG BUILD_VERSION` (line 196). Its cache key is therefore its parent layers plus the command text. Neither changes with an add-on release, nor with time. Unless the base image's digest has moved, the step comes back from cache, holding whatever Claude Code release the first build found.

The reference install shows it happening:

| File in the running con.20 image | Written |
| --- | --- |
| `/etc/claudecode-addon-version` (`1.2.65-con.20`, written by a `RUN` after `ARG BUILD_VERSION`) | 2026-10-18 03:30 |
| `/etc/claude-code-version` (`2.1.276`, written by `install-claude.sh`) | **2026-09-18** 03:31 |
| `/usr/share/ttyd/index.html` (the ttyd-client stage) | 2026-09-18 03:31 |

The con.20 image was built on 18 October. Its Claude Code layer is the one from the build a month earlier, so the add-on update installed 2.1.276. The newest release on 18 October was 2.1.302.

**Separate fix, whichever option is chosen.** Declare `ARG BUILD_VERSION` before `RUN install-claude.sh`; the later `RUN echo … > /etc/claudecode-addon-version` can keep using it. Every add-on release then re-resolves the newest working release at build time, as `install-claude.sh` intends. It costs one install per add-on release and changes nothing else. I can send it as its own small PR.

**2. A rebuild is a restart, and a heavy one.** Even with the cache fixed, refreshing by rebuild means stopping the add-on, so a live session or Remote Control connection is cut. It also rebuilds the whole image, the ttyd web client stage and the package installs included, to change one package. Option B gets the same result in about 7 s of boot time, with no extra restart and no network.

### A note on "stable"

npm carries three dist-tags for Claude Code, read 2026-10-28: `latest` 2.1.312, `next` 2.1.312, and `stable` 2.1.308. `stable` trails `latest` by a few releases. The build takes the newest version in the list, which is effectively `latest`, and Claude's background updater follows `latest` unless it is told otherwise. If the aim is fewer brand-new releases that turn out broken, the lever is the update channel:
- `install-claude.sh` could resolve the `stable` dist-tag first, still falling back to the newest working release;
- Claude Code's own `autoUpdatesChannel` setting could be set to `"stable"`.

That choice is independent of A, B, C or D, and works with any of them.

## Recommendation

Option B. It closes the gap without the one change, executable persistent storage, that this add-on's profile was written to prevent. It reuses the smoke test and rollback that already exist, and the release it reinstalls has already been checked by the watcher from #45.

If you agree, the implementation PR would cover:
- a `restore_claude_release` step in `claudecode-start`;
- one line in the watcher to record the release;
- the `npm_config_cache` environment variable and `backup_exclude` in `config.yaml`;
- README and CHANGELOG entries.

It would be verified the way #45 and #46 were. That means the harness, with a stubbed npm and a real offline install, plus a scenario table covering a warm cache, a cold cache, a remembered release that fails its probe, and no network.

## Open questions for the maintainer

0. **The `ARG BUILD_VERSION` fix** from Option D. It looks like a plain bug, since add-on releases do not refresh Claude Code today. May I send it separately?

1. **A, B, C or D?** (D is the rebuild option; I recommend B.)
2. **`auto_update_claude`.** Keep it with its present meaning, keep it as "also go to latest at boot", or deprecate it in favour of B?
3. **The cache.** Is `backup_exclude` for `/data/npm-cache` acceptable? Or should the cache live on `/data` only for the CLI, via a dedicated cache directory used only by the boot step and the updater's environment?
4. **Update channel.** Should the build and the background updater follow `stable` rather than `latest`? See the note under Option D.
