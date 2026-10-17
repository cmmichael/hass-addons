"""The git-backed config kit in rootfs/usr/share/claudecode/git: the .gitignore template keeps
credentials out and dashboards in, pre-commit refuses what it documents, and the Claude hook only
gates commits that target the config repo."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from testlib import SHARE_DIR

KIT = SHARE_DIR / "git"
HAVE_GIT = shutil.which("git") is not None


def git(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check)


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

    def precommit(self):
        return subprocess.run(["sh", str(KIT / "pre-commit")], cwd=self.repo, capture_output=True, text=True)


class TestGitignoreTemplate(KitRepo):
    def test_credentials_are_ignored(self):
        for rel in ("secrets.yaml", "esphome/secrets.yaml", ".cloud/x", "claudecode_jobs.yaml",
                    ".storage/auth", ".storage/auth_provider.homeassistant", ".storage/core.config_entries",
                    ".storage/application_credentials", ".storage/mobile_app", ".storage/some_integration_token",
                    ".claudecode/.credentials.json", ".claudecode/.claude.json", ".claudecode/gh/hosts.yml",
                    ".claudecode/projects/p/memory/MEMORY.md", ".claudecode/jobs/state/x.json",
                    ".claudecode/jobs/logs/x.jsonl", ".claudecode/jobs/_notify.yaml",
                    ".claude/settings.local.json", "zigbee.db", "home-assistant_v2.db", "home-assistant_v2.db-wal",
                    "home-assistant.log", "ssl/server.key", "cert.pem"):
            self.assertTrue(self.ignored(rel), rel)

    def test_valuable_files_are_tracked(self):
        for rel in ("configuration.yaml", "automations.yaml", "packages/a.yaml", ".storage/lovelace",
                    ".storage/lovelace.lovelace", ".storage/lovelace.any_new_dashboard", ".storage/lovelace_dashboards",
                    ".storage/lovelace_resources", ".storage/core.entity_registry", ".storage/input_boolean",
                    ".storage/person", ".claudecode/CLAUDE.user.md", ".claudecode/jobs/health-check.md",
                    ".claudecode/skills/s/SKILL.md", ".claude/settings.json"):
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
        r = self.precommit()
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

    def test_hacs_dirs_are_skipped(self):
        write(self.repo, "custom_components/x/broken.json", "{nope")
        r = self.precommit()
        self.assertEqual(r.returncode, 0, r.stdout)


class TestClaudeHook(KitRepo):
    def hook(self, command, cwd):
        env = dict(os.environ, HA_CONFIG_REPO=str(self.repo))
        return subprocess.run(["sh", str(KIT / "claude-precommit.sh")], input=json.dumps(
            {"tool_input": {"command": command}, "cwd": cwd}), capture_output=True, text=True, env=env)

    def setUp(self):
        super().setUp()
        write(self.repo, "automations.yaml", "- id: a\n  alias: [unclosed\n")

    def test_blocks_commit_in_config_repo(self):
        r = self.hook("git add -A && git commit -m x", str(self.repo))
        self.assertEqual(r.returncode, 2)
        self.assertIn("automations.yaml", r.stderr)

    def test_blocks_commit_naming_config_repo(self):
        self.assertEqual(self.hook(f"git -C {self.repo} commit -m x", "/somewhere/else").returncode, 2)

    def test_other_repos_and_commands_pass(self):
        self.assertEqual(self.hook("git commit -m x", "/somewhere/else").returncode, 0)
        self.assertEqual(self.hook("git status", str(self.repo)).returncode, 0)
        self.assertEqual(self.hook("git commit --no-verify -m x", str(self.repo)).returncode, 0)


if __name__ == "__main__":
    unittest.main()
