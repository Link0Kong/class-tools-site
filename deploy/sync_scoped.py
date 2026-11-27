"""Run the local dual-remote sync with an explicit list of permitted repository files."""
import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import sync_repos as sync


def outside_scope(allowed, git):
    changed = set()
    for args in (("diff", "--cached", "--no-renames", "--name-only", "-z"),
                 ("diff", "--no-renames", "--name-only", "-z"),
                 ("ls-files", "--others", "--exclude-standard", "-z")):
        changed.update(filter(None, git("--no-optional-locks", *args).stdout.split("\0")))
    unexpected = sorted(changed - allowed)
    if unexpected:
        sync.fail("范围外文件，暂存区保持原状：\n  " + "\n  ".join(unexpected))


def run(paths, message):
    allowed = set()
    for name in paths:
        rel = PurePosixPath(name.replace("\\", "/"))
        if (not rel.parts or rel.is_absolute() or ":" in rel.parts[0] or ".." in rel.parts
                or ".git" in rel.parts or (ROOT / rel).is_dir()):
            sync.fail("请传入仓库相对文件名：" + name)
        allowed.add(str(rel))
    git = sync.git
    index = Path(git("rev-parse", "--path-format=absolute", "--git-path", "index").stdout.strip())
    lock = index.with_name(index.name + ".lock")
    try:
        fd = os.open(lock, os.O_EXCL | os.O_CREAT | os.O_WRONLY)
    except FileExistsError:
        sync.fail("索引正由其他 Git 操作使用。")
    os.close(fd)
    locked = True
    original_env = sync.GIT_ENV
    original_args = sys.argv
    try:
        outside_scope(allowed, git)
        with tempfile.TemporaryDirectory(dir=index.parent) as tmp:
            copy_index = Path(tmp) / "index"
            shutil.copyfile(index, copy_index)
            private = dict(original_env, GIT_INDEX_FILE=str(copy_index), GIT_LITERAL_PATHSPECS="1")
            def guarded(*args, **kwargs):
                nonlocal locked
                if args[:2] == ("add", "-A") or args[0] == "commit":
                    sync.GIT_ENV = original_env
                    outside_scope(allowed, git)
                    if args[0] == "add":
                        # Existing or tracked paths can be passed to add, including staged deletes.
                        # An already staged delete has nothing left to add.
                        eligible = [p for p in sorted(allowed) if (ROOT / p).exists() or
                                    git("ls-files", "--error-unmatch", "--", p, check=False).returncode == 0]
                        if not eligible:
                            return git("rev-parse", "HEAD")
                        args = ("add", "-A", "--", *eligible)
                sync.GIT_ENV = private if locked else original_env
                result = git(*args, **kwargs)
                if args[0] == "commit" and result.returncode == 0:
                    shutil.copyfile(copy_index, lock)
                    os.replace(lock, index)
                    locked = False
                    sync.GIT_ENV = original_env
                return result
            sync.git = guarded
            sys.argv = [str(ROOT / "sync_repos.py"), message]
            sync.main()
    finally:
        sync.git = git
        sync.GIT_ENV = original_env
        sys.argv = original_args
        if locked:
            lock.unlink(missing_ok=True)


if __name__ == "__main__":
    sync.force_utf8_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-m", "--message", required=True)
    parser.add_argument("paths", nargs="+", metavar="FILE")
    opt = parser.parse_args()
    run(opt.paths, opt.message)
