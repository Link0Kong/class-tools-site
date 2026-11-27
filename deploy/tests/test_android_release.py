"""Exercise both publication scripts against temporary ECS/OSS directories."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import android_release as release


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.ecs = self.root / "ecs"
        self.oss = self.root / "oss"
        self.local = self.root / "local"
        for folder in [self.ecs, self.oss, self.local]:
            folder.mkdir()
            (folder / "latest.json").write_bytes(b'{"versionCode":169}')
        self.old_name = "classtools-1.0.0-beta66.apk"
        (self.ecs / self.old_name).write_bytes(b"old")
        (self.oss / (self.old_name + ".bin")).write_bytes(b"old")
        self.apk = self.root / "signed.apk"
        self.apk.write_bytes(b"new signed bytes")
        self.args = ["--apk", str(self.apk), "--version-name", "1.0.0-beta66",
                     "--version-code", "170", "--notes", "previous version"]
        self.public_read = False
        self.corrupt = False
        self.fail_oss_manifest = False
        if os.name == "nt":
            self.bash = Path(os.environ["ProgramFiles"]) / "Git/bin/bash.exe"
            if not self.bash.is_file():
                self.skipTest("Git for Windows Bash is required")
        else:
            self.bash = shutil.which("bash")
            if not self.bash:
                self.skipTest("Bash is required")
        for obj, key, value in [
            (release, "ANDROID_DIR", str(self.local)), (release, "ECS_ANDROID", "ecs"),
            (release, "verify_app_entrypoints", lambda apk: None),
            (release, "oss_bucket", lambda: self), (release, "http_code", self.read_url),
            (release.ecs_site, "run_script", self.run_script),
        ]:
            patched = patch.object(obj, key, value)
            patched.start()
            self.addCleanup(patched.stop)

    def put_object_from_file(self, key, path, headers):
        shutil.copyfile(path, self.oss / Path(key).name)

    def put_object(self, key, raw, headers):
        self.assertTrue(self.public_read)
        self.assertEqual((self.ecs / "latest.json").read_bytes(), raw)
        if self.fail_oss_manifest:
            raise OSError("interrupted OSS write")
        (self.oss / Path(key).name).write_bytes(raw)

    def run_script(self, script, *, label, **kwargs):
        if label == "android-manifest":
            self.assertTrue(self.public_read)
        # Replace the remote curl binary with the local fixture's object download.
        curl = """curl() {
            local url="${!#}"
            while [[ "$1" != "-o" ]]; do shift; done
            cp -- "oss/${url##*/}" "$2"
        }
        """
        result = subprocess.run([str(self.bash), "-s"], cwd=self.root, input=curl + script,
                                capture_output=True, text=True, timeout=15)
        return ("Success" if result.returncode == 0 else "Failure",
                result.returncode, result.stdout + result.stderr)

    def read_url(self, url, method="GET", timeout=30):
        folder = self.ecs if url.startswith(release.ECS_PUBLIC + "/") else self.oss
        path = folder / url.rsplit("/", 1)[1]
        if not path.is_file():
            return 404, b""
        if folder == self.ecs and path.suffix == ".apk" and method == "GET":
            if self.corrupt:
                return 200, b"x" * self.apk.stat().st_size
            self.public_read = True
        return 200, path.read_bytes() if method == "GET" else b""

    def test_interrupted_mirror_write_can_retry_without_touching_historical_urls(self):
        self.fail_oss_manifest = True
        with self.assertRaises(OSError):
            release.main(self.args)
        self.assertEqual(json.loads((self.local / "latest.json").read_bytes())["versionCode"], 169)
        self.fail_oss_manifest = False
        self.public_read = False
        self.assertEqual(release.main(self.args), 0)
        raw = (self.local / "latest.json").read_bytes()
        name = "classtools-1.0.0-beta66-vc170.apk"
        self.assertEqual(json.loads(raw)["apkUrl"], release.ECS_PUBLIC + "/android/" + name)
        for folder, suffix in [(self.ecs, ""), (self.oss, ".bin")]:
            self.assertEqual((folder / "latest.json").read_bytes(), raw)
            self.assertEqual((folder / (name + suffix)).read_bytes(), self.apk.read_bytes())
            self.assertEqual((folder / (self.old_name + suffix)).read_bytes(), b"old")

    def test_invalid_public_download_preserves_both_manifests(self):
        self.corrupt = True
        with self.assertRaisesRegex(SystemExit, "APK"):
            release.main(self.args)
        for folder in [self.ecs, self.oss, self.local]:
            self.assertEqual((folder / "latest.json").read_bytes(), b'{"versionCode":169}')


if __name__ == "__main__":
    unittest.main()
