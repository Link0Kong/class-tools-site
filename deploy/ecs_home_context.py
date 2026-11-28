"""Install the workbench content service through the existing ECS Cloud Assistant channel."""

import argparse
import base64
import gzip
import hashlib
import json
import secrets
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import ecs_site
from home_context_app import ENGLISH_TYPOGRAPHY


DEPLOY = Path(__file__).resolve().parent
APP = DEPLOY / "home_context"
REGIONS = DEPLOY.parent.parent / "android-class-tools/app/src/main/assets/home_regions.tsv"
INSTALLED = APP / "install_on_ecs.py"
PART_SIZE = 10_000


def remote(script, label, timeout):
    status, code, output = ecs_site.run_script(script, timeout=timeout, wait=timeout + 45, label=label)
    if status != "Success" or str(code) != "0":
        raise RuntimeError(f"{label}: {status} ({code})\n{output or ''}")
    return output


def payload(regions, seed):
    paths = {
        "home_context_app.py": DEPLOY / "home_context_app.py",
        "task_ai_app.py": DEPLOY / "task_ai_app.py",
        "home_regions.tsv": regions,
    }
    for name in ("api.service", "daily.service", "daily.timer"):
        unit = "class-tools-home-context-" + name
        paths[unit] = APP / unit
    if seed:
        paths["content.json"] = seed
    content = {name: base64.b64encode(path.read_bytes()).decode("ascii") for name, path in paths.items()}
    return gzip.compress(json.dumps(content, separators=(",", ":")).encode("ascii"), mtime=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regions", type=Path, default=REGIONS)
    parser.add_argument("--reviewed-batch", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-bundle", action="store_true")
    mode.add_argument("--english-typography", choices=ENGLISH_TYPOGRAPHY)
    args = parser.parse_args()
    if args.english_typography:
        installer = INSTALLED.read_text(encoding="utf-8")
        script = (f"python3 -B - --english-typography {args.english_typography} <<'HOME_CONTEXT_INSTALL'\n"
                  f"{installer}\nHOME_CONTEXT_INSTALL\n")
        print(remote(script, "home-context-presentation", 30) or "")
        return 0
    archive = payload(args.regions, args.reviewed_batch)
    digest = hashlib.sha256(archive).hexdigest()
    encoded = base64.b64encode(archive).decode("ascii")
    parts = [encoded[i:i + PART_SIZE] for i in range(0, len(encoded), PART_SIZE)]
    if args.check_bundle:
        print(f"Bundle {digest}, {len(parts)} parts, {len(archive)} bytes")
        return 0
    stage = "/var/tmp/class-tools-home-context." + secrets.token_hex(8)

    def upload(item):
        index, part = item
        script = f"set -eu\ninstall -d -m 0700 {stage}\nprintf '%s' '{part}' > {stage}/{index:03d}.part\n"
        return remote(script, f"home-context-stage-{index}", 25)

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(upload, enumerate(parts)))
        python = INSTALLED.read_text(encoding="utf-8")
        script = (
            f"set -eu\n"
            f"python3 -B - '{stage}' '{digest}' <<'HOME_CONTEXT_INSTALL'\n"
            f"{python}\nHOME_CONTEXT_INSTALL\n"
        )
        print(remote(script, "home-context-install", 230) or "")
    finally:
        try:
            remote(f"set -eu\nif [ -d {stage} ]; then rm -f {stage}/*.part; rmdir {stage}; fi\n",
                   "home-context-stage-cleanup", 20)
        except RuntimeError as error:
            print(str(error), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

