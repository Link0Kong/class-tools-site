"""Refresh exact lookup keys from the public member fields of configured whole-class groups."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unicodedata


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def account_map(members: list[dict], platform: str) -> dict[str, str]:
    provider, field = ("qq", "uin") if platform == "QQ" else ("wx", "wxid")
    candidates: dict[str, set[str]] = {}
    for member in members:
        sid = str(member.get("sid") or "")
        if not re.fullmatch(r"[0-9]{1,20}", sid):
            continue
        for account in member.get(provider, []):
            key = str(account.get(field) or "")
            if key and str(account.get("matchBy") or "").split(":")[0] in {"name", "manual_alias", "alias"}:
                candidates.setdefault(key, set()).add(sid)
    return {key: next(iter(sids)) for key, sids in candidates.items() if len(sids) == 1}


def lookup_keys(people: list[dict], platform: str, owners: dict[str, str]) -> set[tuple[str, str]]:
    account_field, fields = ("uin", ("nick", "card")) if platform == "QQ" else ("wxid", ("nickname", "groupNickname"))
    pairs: set[tuple[str, str]] = set()
    for person in people:
        account = str(person.get(account_field) or "")
        sid = owners.get(account)
        if not sid:
            continue
        for field in fields:
            raw = person.get(field)
            if not isinstance(raw, str):
                continue
            name = unicodedata.normalize("NFC", raw.strip(" "))
            if not 1 <= len(name) <= 128 or name in (account, sid) or name.lower().startswith("wxid_"):
                continue
            if any(unicodedata.category(ch) == "Cc" for ch in name):
                continue
            pairs.add((sid, digest(name)))
    return pairs


def refresh(workspace: Path) -> None:
    runtime = workspace / "briefdesk"
    sys.path.insert(0, str(runtime / "scripts"))
    sys.path.insert(0, str(workspace / "web/deploy/cloudbase"))
    from sync_audience_rosters import qq_members, wx_members
    from apply_sql import API_VERSION, ENV_ID, NODE, TCB_BIN

    def execute(sql: str) -> None:
        body = json.dumps({"EnvId": ENV_ID, "Sql": sql})
        result = subprocess.run([NODE, TCB_BIN, "api", "tcb", "ExecutePGSql", "--api-version", API_VERSION,
                                 "--body", body, "--json"], capture_output=True, timeout=50)
        output = result.stdout.decode("utf-8-sig", errors="replace")
        response = json.loads(output[output.index("{"):])
        if result.returncode or "error" in response or "data" not in response or response["data"].get("Error"):
            raise RuntimeError("roster search database refresh failed")

    def read(name: str) -> dict:
        return json.loads((runtime / "data" / name).read_text(encoding="utf-8-sig"))

    groups = [g for g in read("group-audience.json")["groups"]
              if g.get("nature") == "全班" and g.get("vis") == "全体同学" and g.get("platform") in ("QQ", "微信")]
    members = read("class-identities.json")["members"]
    if not members or not groups:
        raise RuntimeError("class member or group configuration unavailable")
    owners = {p: account_map(members, p) for p in ("QQ", "微信")}
    if not all(owners.values()):
        raise RuntimeError("no verified class member mapping")
    allowed = set()
    count = 0
    failures = 0
    for group in groups:
        platform, gid = group["platform"], str(group["id"])
        source = digest(platform + ":" + gid)
        allowed.add(source)
        try:
            rows = (qq_members if platform == "QQ" else wx_members)(gid)
            if not isinstance(rows, list) or not rows:
                raise RuntimeError("group membership unavailable")
            pairs = lookup_keys(rows, platform, owners[platform])
            # Only validated student IDs and hex digests are transferred. Commit one complete group at a time.
            values = ",".join(f"('{sid}',decode('{key}','hex'))" for sid, key in sorted(pairs))
            sql = f"BEGIN; SELECT pg_advisory_xact_lock(hashtext('{source}')); DELETE FROM private.roster_search_keys WHERE source_key='{source}';"
            if values:
                sql += ("INSERT INTO private.roster_search_keys(source_key,sid,name_hash) "
                        f"SELECT '{source}',m.sid,v.h FROM (VALUES {values}) v(sid,h) "
                        "JOIN private.class_ids m ON m.sid=v.sid WHERE m.is_test IS NOT TRUE;")
            execute(sql + "COMMIT;")
            count += len(pairs)
        except Exception as exc:
            # Provider exceptions can contain group identifiers. Keep operator output aggregate-only.
            print(f"group refresh failed ({type(exc).__name__})", file=sys.stderr)
            failures += 1
    keep = ",".join(f"'{key}'" for key in sorted(allowed))
    execute(f"DELETE FROM private.roster_search_keys WHERE source_key NOT IN ({keep});")
    print(f"groups={len(groups)} refreshed={len(groups)-failures} lookup_keys={count}")
    if failures:
        raise RuntimeError("some class groups could not be refreshed")


if __name__ == "__main__":
    refresh(Path(__file__).resolve().parents[2])
