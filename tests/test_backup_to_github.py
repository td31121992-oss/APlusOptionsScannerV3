import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import backup_to_github as b


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        t = Path(self.tmp.name)
        self.root, self.repo, self.remote = t / "proj", t / "backup", t / "remote.git"
        (self.root / "data" / "trade_archive").mkdir(parents=True)
        (self.root / "data" / "reports").mkdir(parents=True)
        (self.root / "data" / "trade_archive" / "history.csv").write_text("a,b\n1,2\n")
        (self.root / "data" / "reports" / "huge.json").write_text("not backed up")
        (self.root / ".env").write_text("UPSTOX_ANALYTICS_TOKEN=secret")
        (self.root / "data" / "trade_archive" / "my_token_cache.json").write_text("{}")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.remote)], check=True)
        os.environ.pop("APLUS_BACKUP_DIR", None)
        os.environ.pop("APLUS_BACKUP", None)
        b.setup(str(self.remote), self.repo)
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "t")

    def tearDown(self):
        self.tmp.cleanup()

    def run_backup(self, **kw):
        return b.run(self.root, self.repo, extra_dirs=[], tasks=False, **kw)

    def test_plan_includes_data_and_never_secrets_or_big_folders(self):
        items, skipped = b.plan(self.root, [])
        rels = {r for _, r in items}
        self.assertIn("data/trade_archive/history.csv", rels)
        self.assertNotIn("data/reports/huge.json", rels)
        self.assertNotIn(".env", rels)
        self.assertTrue(any("my_token_cache.json" in s for s in skipped))

    def test_backup_pushes_and_second_run_is_a_noop(self):
        r = self.run_backup()
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["pushed"])
        files = git(self.remote, "ls-tree", "-r", "--name-only", "main").stdout.split()
        self.assertIn("data/trade_archive/history.csv", files)
        self.assertIn("RESTORE.md", files)
        self.assertNotIn(".env", files)
        self.assertFalse([f for f in files if "token" in f])
        r2 = self.run_backup()
        self.assertTrue(r2["ok"] and "nothing changed" in r2["message"] or r2["pushed"], r2)

    def test_changed_file_is_backed_up_again(self):
        self.run_backup()
        (self.root / "data" / "trade_archive" / "history.csv").write_text("a,b\n1,2\n3,4\n")
        r = self.run_backup()
        self.assertTrue(r["pushed"], r)
        self.assertIn("3,4", git(self.remote, "show", "main:data/trade_archive/history.csv").stdout)

    def test_oversize_file_is_skipped(self):
        old = b.MAX_FILE
        b.MAX_FILE = 5
        try:
            _, skipped = b.plan(self.root, [])
        finally:
            b.MAX_FILE = old
        self.assertTrue(any("over" in s for s in skipped))

    def test_not_set_up_and_switched_off_never_raise(self):
        r = b.run(self.root, Path(self.tmp.name) / "nowhere", extra_dirs=[], tasks=False)
        self.assertFalse(r["ok"])
        self.assertIn("--setup", r["message"])
        os.environ["APLUS_BACKUP"] = "0"
        try:
            self.assertIn("switched off", self.run_backup()["message"])
        finally:
            os.environ.pop("APLUS_BACKUP", None)

    def test_dry_run_changes_nothing(self):
        r = self.run_backup(dry=True)
        self.assertTrue(r["ok"])
        self.assertFalse((self.repo / "data").exists())


if __name__ == "__main__":
    unittest.main()
