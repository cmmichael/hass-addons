"""The git-backed config kit (rootfs/usr/share/claudecode/git + the pre-commit hook in
rootfs/usr/local/share/claudecode/git-hooks): the .gitignore template keeps credentials out and
dashboards in, and the hook refuses what it documents — run by hand and as a real git hook."""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from testlib import SHARE_DIR

KIT = SHARE_DIR / "git"
HOOKS = SHARE_DIR.parents[1] / "local/share/claudecode/git-hooks"
HAVE_GIT = shutil.which("git") is not None


# Hermetic: no global/system git config (commit signing, a global hooksPath or excludesFile).
GIT_ENV = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")


def git(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check,
                          env=GIT_ENV)


def write(repo, rel, text="{}\n"):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


@unittest.skipUnless(HAVE_GIT, "git not installed")
class KitRepo(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="gitkit-"))
        self.addCleanup(shutil.rmtree, self.repo, True)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.name", "test")
        git(self.repo, "config", "user.email", "test@example.invalid")
        shutil.copy(KIT / "gitignore", self.repo / ".gitignore")

    def ignored(self, rel):
        return git(self.repo, "check-ignore", "-q", "--no-index", rel, check=False).returncode == 0

    def precommit(self, stage=True):
        if stage:
            git(self.repo, "add", "-A")
        return subprocess.run(["sh", str(HOOKS / "pre-commit")], cwd=self.repo, capture_output=True, text=True,
                              env=GIT_ENV)


class TestGitignoreTemplate(KitRepo):
    def test_credentials_are_ignored(self):
        for rel in ("secrets.yaml", "esphome/secrets.yaml", ".cloud/x", "claudecode_jobs.yaml",
                    ".storage/auth", ".storage/auth_provider.homeassistant", ".storage/core.config_entries",
                    ".storage/application_credentials", ".storage/mobile_app", ".storage/some_integration_token",
                    ".claudecode/.credentials.json", ".claudecode/.claude.json", ".claudecode/gh/hosts.yml",
                    ".claudecode/projects/p/memory/MEMORY.md", ".claudecode/jobs/state/x.json",
                    ".claudecode/jobs/logs/x.jsonl", ".claudecode/jobs/_notify.yaml",
                    ".claude/settings.local.json", "zigbee.db", "home-assistant_v2.db", "home-assistant_v2.db-wal",
                    "home-assistant.log", "ssl/server.key", "cert.pem",
                    "zigbee2mqtt/coordinator_backup.json", "zigbee2mqtt/configuration.yaml",
                    "SERVICE_ACCOUNT.json", "my-service-account-1234.json", ".google.token", "nest.conf",
                    ".env"):
            self.assertTrue(self.ignored(rel), rel)

    def test_valuable_files_are_tracked(self):
        for rel in ("configuration.yaml", "automations.yaml", "packages/a.yaml", ".storage/lovelace",
                    ".storage/lovelace.lovelace", ".storage/lovelace.any_new_dashboard", ".storage/lovelace_dashboards",
                    ".storage/lovelace_resources", ".storage/core.entity_registry", ".storage/input_boolean",
                    ".storage/person", ".claudecode/CLAUDE.user.md", ".claudecode/jobs/health-check.md",
                    ".claudecode/skills/s/SKILL.md", ".claude/settings.json", "esphome/device.yaml",
                    "www/app/settings.conf"):
            self.assertFalse(self.ignored(rel), rel)

    def test_backup_copies_win_over_the_storage_whitelist(self):
        for rel in (".storage/lovelace.lovelace.bak", ".storage/lovelace.x.bak2", ".storage/lovelace.x.bak-old",
                    "automations.yaml.bak", "scripts.yaml.orig"):
            self.assertTrue(self.ignored(rel), rel)


class TestPreCommit(KitRepo):
    def test_clean_repo_passes(self):
        write(self.repo, "configuration.yaml", "homeassistant:\n  name: x\napi_key: !secret k\nx: !include a.yaml\n")
        write(self.repo, ".storage/lovelace_dashboards", json.dumps(
            {"data": {"items": [{"id": "dashboard_new", "mode": "storage"}]}}))
        write(self.repo, ".storage/lovelace.dashboard_new")
        r = self.precommit()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_force_added_secret_is_refused(self):
        write(self.repo, "secrets.yaml", "k: v\n")
        git(self.repo, "add", "-f", "secrets.yaml")
        r = self.precommit(stage=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("secrets.yaml", r.stdout)

    def test_unignored_token_store_is_refused(self):
        (self.repo / ".gitignore").write_text("")          # a blacklist-less repo
        write(self.repo, ".storage/core.config_entries")
        r = self.precommit()
        self.assertEqual(r.returncode, 1)
        self.assertIn(".storage/core.config_entries", r.stdout)

    def test_ignored_dashboard_is_refused(self):
        with open(self.repo / ".gitignore", "a") as f:
            f.write("/.storage/lovelace.hidden\n")
        write(self.repo, ".storage/lovelace_dashboards", json.dumps(
            {"data": {"items": [{"id": "hidden", "mode": "storage"}, {"id": "y", "mode": "yaml"}]}}))
        write(self.repo, ".storage/lovelace.hidden")
        r = self.precommit()
        self.assertEqual(r.returncode, 1)
        self.assertIn(".storage/lovelace.hidden", r.stdout)

    def test_broken_yaml_and_json_are_refused(self):
        write(self.repo, "automations.yaml", "- id: a\n  alias: [unclosed\n")
        write(self.repo, ".storage/input_boolean", "{not json")
        r = self.precommit()
        self.assertEqual(r.returncode, 1)
        self.assertIn("YAML does not load: automations.yaml", r.stdout)
        self.assertIn("invalid JSON: .storage/input_boolean", r.stdout)

    def test_non_ascii_paths_are_checked(self):
        write(self.repo, "caf\u00e9.yaml", "a: [unclosed\n")
        write(self.repo, "\u03b6\u03b5\u03c3\u03c4\u03cc/secrets.yaml", "k: v\n")
        git(self.repo, "add", "-f", "\u03b6\u03b5\u03c3\u03c4\u03cc/secrets.yaml")
        r = self.precommit()
        self.assertEqual(r.returncode, 1)
        self.assertIn("YAML does not load: caf\u00e9.yaml", r.stdout)
        self.assertIn("  \u03b6\u03b5\u03c3\u03c4\u03cc/secrets.yaml", r.stdout)

    def test_credential_path_with_spaces_is_reported_whole(self):
        (self.repo / ".gitignore").write_text("")
        write(self.repo, "my keys/server *.key", "x\n")
        r = self.precommit()
        self.assertEqual(r.returncode, 1)
        self.assertIn("  my keys/server *.key\n", r.stdout)

    def test_private_key_under_any_name_is_refused(self):
        write(self.repo, "google/creds.json", json.dumps(
            {"private_key": "-----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----\n"}))
        write(self.repo, "custom_components/x/tests/fixture.txt", "-----BEGIN RSA PRIVATE KEY-----\n")
        r = self.precommit()
        self.assertEqual(r.returncode, 1)
        self.assertIn("  google/creds.json", r.stdout)
        self.assertNotIn("custom_components", r.stdout)

    def test_staged_content_is_checked_not_the_working_tree(self):
        write(self.repo, "automations.yaml", "- id: a\n  alias: [unclosed\n")
        git(self.repo, "add", "-A")
        write(self.repo, "automations.yaml", "- id: a\n")           # fixed, but not staged again
        r = self.precommit(stage=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("YAML does not load: automations.yaml", r.stdout)
        git(self.repo, "add", "-A")
        write(self.repo, "automations.yaml", "- id: a\n  alias: [half")  # HA mid-write, not staged
        r = self.precommit(stage=False)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_json_with_comments_is_accepted_outside_storage(self):
        jsonc = '\ufeff{\n  // comment\n  "a": "x // not a comment", /* block */\n  "b": [1, 2,],\n}\n'
        write(self.repo, ".vscode/settings.json", jsonc)
        r = self.precommit()
        self.assertEqual(r.returncode, 0, r.stdout)
        write(self.repo, ".vscode/settings.json", '{"a": // comment\n}')
        write(self.repo, ".storage/input_boolean", '{"a": 1, // comment\n"b": 2}')
        r = self.precommit()
        self.assertEqual(r.returncode, 1)
        self.assertIn("invalid JSON: .vscode/settings.json", r.stdout)
        self.assertIn("invalid JSON: .storage/input_boolean", r.stdout)

    def test_unreadable_dashboard_registry_is_refused(self):
        for text in ("{half", json.dumps({"data": {}})):
            write(self.repo, ".storage/lovelace_dashboards", text)
            r = self.precommit(stage=False)
            self.assertEqual(r.returncode, 1, text)
            self.assertIn("ignored-dashboard check did not run", r.stdout)
        write(self.repo, ".storage/lovelace_dashboards", json.dumps({"data": {"items": [{"mode": "storage"}]}}))
        self.assertEqual(self.precommit(stage=False).returncode, 0)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_dashboard_javascript(self):
        write(self.repo, "www/ok.html", """<html>
<SCRIPT>var a = 1;</SCRIPT>
<script type="x-shader/x-fragment">uniform float t; void main(){ gl_FragColor = vec4(t); }</script>
<script type="text/template"><div>{{ x }}</div></script>
<script type="module">import {a} from "./a.js"; export const b = a;</script>
<script type="importmap">{"imports": {"a": "./a.js"}}</script>
<script src="x.js"></script>
</html>""")
        write(self.repo, "www/mod.js", "import {a} from './a.js';\nexport const b = await a();\n")
        write(self.repo, "www/community/card/broken.js", "function (")
        r = self.precommit()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        write(self.repo, "www/bad.html", "<script>function ( {</script><script type='text/javascript'>}</script>")
        write(self.repo, "www/bad.js", "const a = ;\n")
        r = self.precommit()
        self.assertEqual(r.returncode, 1)
        self.assertIn("inline script does not parse: www/bad.html", r.stdout)
        self.assertIn("script #1", r.stdout)
        self.assertIn("JS does not parse: www/bad.js", r.stdout)

    def test_many_files_use_one_interpreter(self):
        for i in range(150):
            write(self.repo, f"packages/p{i}.yaml", f"input_boolean:\n  b{i}:\n    name: x\n")
        t = time.monotonic()
        r = self.precommit()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertLess(time.monotonic() - t, 15)   # a python3 per file took ~0.2 s each on a Pi

    def test_hacs_dirs_are_skipped(self):
        write(self.repo, "custom_components/x/broken.json", "{nope")
        r = self.precommit()
        self.assertEqual(r.returncode, 0, r.stdout)


class TestGitHook(KitRepo):
    """core.hooksPath -> the hooks dir. Copied to a temp dir first: the copy is what gets
    executed, so the suite also runs where the checkout itself is not exec-allowed."""
    def setUp(self):
        super().setUp()
        hooks = Path(tempfile.mkdtemp(prefix="gitkit-hooks-"))
        self.addCleanup(shutil.rmtree, hooks, True)
        shutil.copy(HOOKS / "pre-commit", hooks / "pre-commit")
        os.chmod(hooks / "pre-commit", 0o755)
        git(self.repo, "config", "core.hooksPath", str(hooks))
        write(self.repo, "configuration.yaml", "homeassistant:\n")

    def commit(self):
        git(self.repo, "add", "-A")
        return git(self.repo, "commit", "-q", "-m", "x", check=False)

    def test_clean_commit_goes_through(self):
        r = self.commit()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_broken_file_blocks_the_commit(self):
        write(self.repo, "automations.yaml", "- id: a\n  alias: [unclosed\n")
        r = self.commit()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("YAML does not load: automations.yaml", r.stdout + r.stderr)
        self.assertEqual(git(self.repo, "rev-list", "--all").stdout, "")

    def test_commit_a_sees_the_broken_file(self):
        self.assertEqual(self.commit().returncode, 0)
        write(self.repo, "configuration.yaml", "homeassistant: [unclosed\n")
        r = git(self.repo, "commit", "-q", "-a", "-m", "x", check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(len(git(self.repo, "rev-list", "--all").stdout.split()), 1)

    def test_unstaged_broken_file_does_not_block(self):
        write(self.repo, "automations.yaml", "- id: a\n  alias: [unclosed\n")
        git(self.repo, "add", "configuration.yaml")
        r = git(self.repo, "commit", "-q", "-m", "x", check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class TestGitBackup(KitRepo):
    def backup(self):
        env = dict(GIT_ENV, HA_CONFIG_DIR=str(self.repo))
        return subprocess.run(["sh", str(KIT / "git_backup.sh")], capture_output=True, text=True, env=env)

    def setUp(self):
        super().setUp()
        self.remote = Path(tempfile.mkdtemp(prefix="gitkit-remote-"))
        self.addCleanup(shutil.rmtree, self.remote, True)
        git(self.remote, "init", "-q", "--bare", "-b", "main")
        git(self.repo, "remote", "add", "origin", str(self.remote))
        write(self.repo, "configuration.yaml", "homeassistant:\n")

    def test_commits_and_pushes(self):
        r = self.backup()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Auto-backup", git(self.remote, "log", "--oneline", "main").stdout)

    def test_failed_add_is_not_reported_as_success(self):
        self.assertEqual(self.backup().returncode, 0)
        write(self.repo, "automations.yaml", "[]\n")
        (self.repo / ".git/index.lock").write_text("")        # a git killed mid-operation
        r = self.backup()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("git add failed", r.stdout)


if __name__ == "__main__":
    unittest.main()
