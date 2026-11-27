"""Emit canonical test vectors into an explicit destination or validate the frozen digest."""
import argparse
import hashlib
import json
from pathlib import Path

DIGEST = "6bbd74410d67d83ef41ab768530b8c2ddd7f12eecd580e472942523ee1b1552c"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    options = parser.parse_args()
    data = json.loads(Path(__file__).with_name("v1.json").read_text(encoding="utf8"))
    raw = canonical(data)
    actual = hashlib.sha256(raw).hexdigest()
    if actual != DIGEST:
        raise SystemExit("fixture digest mismatch: " + actual)
    if options.out:
        options.out.write_bytes(raw)
    print(data["version"], len(data["cases"]), actual)
    for case in data["cases"]:
        print(case["id"], hashlib.sha256(canonical([case["remote"], case["local"]])).hexdigest())
