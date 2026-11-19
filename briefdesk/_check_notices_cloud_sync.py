# -*- coding: utf-8 -*-
"""重建+同步后校验：本地 board-data ↔ 云端 public.notices 一致性。

只读云端；输出：总行数/auto 行/本地 43 组匹配情况、body 内附件（items）统计、
mergedSources/crossSource 下发、管理员列（override_json/hidden/edited_at/edited_by）现状。

跑法：G:\\ClassTools\\briefdesk\\venv\\Scripts\\python.exe -X utf8 G:\\ClassTools\\web\\briefdesk\\_check_notices_cloud_sync.py
"""
import json
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, r"G:\ClassTools\briefdesk\scripts")
import sync_power_cloud as sp  # noqa: E402

BOARD = Path(r"G:\ClassTools\briefdesk\data\board-data.json")
PREFIX = "[[CLASS_NOTICE_V1]]"


def main():
    board = json.loads(BOARD.read_text(encoding="utf-8"))
    groups = [g for g in (board.get("groups") or []) if isinstance(g, dict)]
    local_ids = [str(g.get("id")) for g in groups]
    base, key = sp.cb_config()
    token = sp.get_token(base, key, lambda m: None)
    st, rows = sp.cb_request(base, key, "notices?select=id,title,ts,hidden,edited_at,edited_by,"
                                        "override_json,archived,body&limit=500", token=token)
    if st != 200:
        print("cloud read failed:", st, str(rows)[:300])
        return 2
    active = [r for r in rows if not r.get("archived")]
    archived = [r for r in rows if r.get("archived")]
    print("cloud notices rows:", len(rows), "| active:", len(active), "| archived:", len(archived))
    auto = [r for r in active if str(r.get("id") or "").startswith("auto_")]
    print("active auto_ rows:", len(auto), "| other active rows:", len(active) - len(auto))
    auto_archived = [r for r in archived if str(r.get("id") or "").startswith("auto_")]
    print("archived auto_ rows:", len(auto_archived))
    cloud = {}
    for r in auto:
        body = str(r.get("body") or "")
        if not body.startswith(PREFIX):
            continue
        try:
            data = json.loads(body[len(PREFIX):])
        except Exception:
            continue
        gid = str(r.get("id"))[len("auto_"):]
        cloud[gid] = (r, data)
    print("active auto_ CLASS_NOTICE bodies:", len(cloud), "| local groups:", len(groups))

    missing = [gid for gid in local_ids if gid not in cloud]
    stale = [gid for gid in cloud if gid not in local_ids]
    print("local ids missing on cloud (active):", len(missing), missing[:8])
    print("stale active cloud ids (should be 0):", len(stale), stale[:8])

    def count_items(data):
        c = {}
        for it in data.get("items") or []:
            k = str(it.get("kind") or "?")
            c[k] = c.get(k, 0) + 1
        return c

    files = imgs = links = merged = cross = 0
    sample_archive = sample_wechat = sample_merged = None
    mism = []
    for gid in local_ids:
        if gid not in cloud:
            continue
        r, data = cloud[gid]
        c = count_items(data)
        files += c.get("file", 0)
        imgs += c.get("img", 0)
        links += c.get("link", 0)
        mss = data.get("mergedSources") or []
        if len(mss) > 1:
            merged += 1
            sample_merged = sample_merged or (gid, data.get("title"), [x.get("kind") for x in mss])
        if data.get("crossSource"):
            cross += 1
        for it in data.get("items") or []:
            if it.get("archive") and not sample_archive:
                sample_archive = (gid, data.get("title"), it["archive"].get("count"),
                                  [f.get("name") for f in (it["archive"].get("files") or [])][:3])
            if it.get("kind") == "img" and it.get("pending") and not sample_wechat:
                sample_wechat = (gid, data.get("title"), it.get("note"))
        # 管理员列：同步后应保持原值（此脚本只报告，不评判同步 writes）
    admin = {
        "override_json_non_null": sum(1 for r in rows if r.get("override_json")),
        "hidden_true": sum(1 for r in rows if r.get("hidden")),
        "edited_at_non_null": sum(1 for r in rows if r.get("edited_at")),
        "edited_by_non_null": sum(1 for r in rows if r.get("edited_by")),
    }
    print("body items: file=%d img=%d link=%d | merged cards=%d crossSource=%d" %
          (files, imgs, links, merged, cross))
    print("admin columns on cloud:", json.dumps(admin, ensure_ascii=False))
    print("sample archive:", sample_archive)
    print("sample wechat pending img:", sample_wechat)
    print("sample merged:", sample_merged)
    ok = (not missing) and len(cloud) >= len(groups) and files > 0 and imgs > 0 and merged >= 2 and cross >= 1
    print("RESULT:", "PASS" if ok else "CHECK")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
