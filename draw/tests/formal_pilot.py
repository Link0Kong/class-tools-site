"""Offline paper-pilot verifier for one synthetic equal-weight, no-replacement event."""
import copy
import hashlib
import json
from pathlib import Path

FIXTURE = Path(__file__).with_name("formal_pilot.json")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def commitment(spec):
    ids = [r["id"] for r in spec["members"]]
    if (not ids or len(set(ids)) != len(ids) or ids != sorted(ids)
            or spec["rule"] != "equal-without-replacement"
            or not 0 < spec["count"] <= len(ids)):
        raise ValueError("invalid locked roster or rules")
    return digest(spec)


def bounded(words, n):
    # Rejection sampling, using the largest multiple of n within the word domain.
    limit = 256 - 256 % n
    for word in words:
        if word < limit:
            return word % n
    raise ValueError("stream ended")


def order(spec, seed):
    def stream():
        counter = 0
        prefix = bytes.fromhex(commitment(spec)) + bytes.fromhex(seed)
        while True:
            yield from hashlib.sha256(prefix + counter.to_bytes(8, "big")).digest()
            counter += 1
    words = stream()
    ids = [r["id"] for r in spec["members"]]
    for i in range(len(ids) - 1, 0, -1):
        j = bounded(words, i + 1)
        ids[i], ids[j] = ids[j], ids[i]
    return ids[:spec["count"]]


def review(spec, witnessed, beacon, *, activity, sample_digest):
    if spec.get("v") != 1 or spec.get("algorithm") != "sha256-byte-fy-1":
        return "版本不支持", []
    if spec["activity"] != activity:
        return "活动不匹配", []
    if witnessed is None:
        return "见证材料不足", []
    if commitment(spec) != witnessed["commitment"]:
        return "承诺不一致", []
    if witnessed["announced"] >= witnessed["release"]:
        return "见证过晚", []
    if beacon is None:
        return "等待原定轮次", []
    if (beacon["source"], beacon["round"]) != (spec["source"], spec["round"]):
        return "来源或轮次错误", []
    if len(beacon["value"]) != 64 or digest(beacon) != sample_digest:
        return "样例材料损坏", []
    return "离线样例复算一致", order(spec, beacon["value"])


def run():
    v = json.loads(FIXTURE.read_text(encoding="utf8"))
    for key in ("first", "successor"):
        fixture = v[key]
        s, witness, beacon = (fixture[k] for k in ("manifest", "witness", "beacon"))
        check = lambda spec=s,w=witness,b=beacon: review(spec,w,b,activity=s["activity"],sample_digest=fixture["postRoundDigest"])
        assert check() == ("离线样例复算一致", fixture["result"])
        assert check(w=None)[0] == "见证材料不足"
        assert check(w=dict(witness,announced=witness["release"]))[0] == "见证过晚"
        assert check(b=None)[0] == "等待原定轮次"
        assert check(b=dict(beacon,round=s["round"] + 1))[0] == "来源或轮次错误"
        assert check(b=dict(beacon,value="00"*32))[0] == "样例材料损坏"
        assert check(dict(s,count=1))[0] == "承诺不一致"
        assert check(dict(s,algorithm="unknown"))[0] == "版本不支持"
        assert review(s,witness,beacon,activity="other",sample_digest=fixture["postRoundDigest"])[0] == "活动不匹配"
        swapped = copy.deepcopy(s)
        swapped["members"][0]["binding"] = "different"
        assert check(swapped)[0] == "承诺不一致"
        try:
            commitment(dict(s,members=s["members"]*2))
        except ValueError:
            pass
        else:
            raise AssertionError("duplicate ID was accepted")
    for size in range(2,9):
        limit = 256 - 256 % size
        assert [sum(x % size == i for x in range(limit)) for i in range(size)] == [limit//size]*size
    assert bounded(iter([255,255,128]),3) == 2
    exports = v["exports"]
    assert exports[0]["resultId"] == exports[1]["resultId"] == v["first"]["resultId"]
    assert exports[0]["digest"] == exports[1]["digest"] == digest(v["first"]["result"])
    assert v["successor"]["replaces"] == v["first"]["manifest"]["activity"]
    assert v["first"]["resultId"] != v["successor"]["resultId"]
    assert v["events"][-1]["supersededBy"] == v["successor"]["manifest"]["activity"]
    print("Passed offline fixture:", v["first"]["result"], "->", v["successor"]["result"])


if __name__ == "__main__":
    run()
