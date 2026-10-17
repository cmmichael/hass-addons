"""The git-backed config kit (rootfs/usr/share/claudecode/git + the pre-commit hook in
rootfs/usr/local/share/claudecode/git-hooks): the .gitignore template keeps credentials out and
dashboards in, and the hook refuses what it documents — run by hand and as a real git hook."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from testlib import SHARE_DIR

KIT = SHARE_DIR / "git"
HOOKS = SHARE_DIR.parents[1] / "local/share/claudecode/git-hooks"
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

    def precommit(self, stage=True):
        if stage:
            git(self.repo, "add", "-A")
        return subprocess.run(["sh", str(HOOKS / "pre-commit")], cwd=self.repo, capture_output=True, text=True)


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

    def test_unstaged_broken_file_does_not_block(self):
        write(self.repo, "automations.yaml", "- id: a\n  alias: [unclosed\n")
        git(self.repo, "add", "configuration.yaml")
        r = git(self.repo, "commit", "-q", "-m", "x", check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
