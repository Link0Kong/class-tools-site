"""All remotes in these tests are local bare repositories."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2]


class ScopeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.repo = base / "site"
        self.repo.mkdir()
        self.git("init", "-b", "master")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "test@example.invalid")
        self.remotes = []
        for name, domain in [("origin", "github.com"), ("gitee", "gitee.com")]:
            remote = base / (domain + ".git")
            self.git("init", "--bare", "-b", "master", str(remote))
            self.git("remote", "add", name, str(remote))
            self.remotes.append(remote)
        (self.repo / "deploy").mkdir()
        for name in ["sync_repos.py", "deploy/sync_scoped.py"]:
            shutil.copyfile(SOURCE / name, self.repo / name)
        self.put(".gitignore", "__pycache__/\n")
        self.put("with space.txt", "old")
        self.put("tools/tt.json", "{}")
        self.git("add", "-A")
        self.git("commit", "-m", "base")
        for name in ("origin", "gitee"):
            self.git("push", name, "master")
        self.put("with space.txt", "new fixture contents")

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo, stderr=subprocess.PIPE).strip()

    def put(self, name, content):
        path = self.repo / name
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text(content, encoding="utf8")

    def state(self):
        return (self.git("write-tree"), self.git("rev-parse", "HEAD"),
                *(self.git("--git-dir=" + str(r), "rev-parse", "master") for r in self.remotes))

    def invoke(self, *paths, code=None):
        command = [sys.executable, "-B", "deploy/sync_scoped.py", "-m", "test: scoped fixture", *paths]
        if code:
            command = [sys.executable, "-B", "-c", code]
        return subprocess.run(command, cwd=self.repo, capture_output=True, text=True, encoding="utf8",errors="replace")

    def reject(self, *paths, code=None):
        before = self.state()
        run = self.invoke(*paths, code=code)
        self.assertNotEqual(run.returncode, 0, run.stdout)
        self.assertEqual(before, self.state())

    def test_space(self):
        run = self.invoke("with space.txt")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(len(set(self.state()[1:])), 1)
        self.assertFalse(self.git("status", "--short"))

    def test_tracked_and_staged(self):
        self.put("tools/tt.json", "stale")
        self.reject("with space.txt")
        self.git("add", "tools/tt.json")
        self.reject("with space.txt")

    def test_untracked(self):
        self.put("unlisted", "extra")
        self.reject("with space.txt")

    def test_rename_both_names(self):
        self.git("mv", "tools/tt.json", "new.json")
        self.reject("with space.txt", "new.json")
        self.reject("with space.txt", "tools/tt.json")

    def test_late_untracked(self):
        self.reject(code="import sys; sys.path.insert(0,'deploy'); import sync_scoped as s; "
                    "s.sync.step=lambda *args: s.Path('late').touch(); "
                    "s.run(['with space.txt'], 'test: race fixture')")

    def test_sensitive_still_checked(self):
        self.put("forbidden.key", "placeholder")
        self.reject("with space.txt", "forbidden.key")

    def test_regular_entry(self):
        subprocess.run([sys.executable, "-B", "sync_repos.py", "test: original sync fixture"],
                       cwd=self.repo, stdout=subprocess.PIPE, check=True)
        self.assertEqual(len(set(self.state()[1:])), 1)


if __name__ == "__main__":
    unittest.main()
