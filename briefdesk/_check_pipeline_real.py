# -*- coding: utf-8 -*-
"""v2.0.0 真实数据 e2e 冒烟（不覆盖正式产物）：builder 全流程 + 微信媒体采集空转。

跑法：G:\\ClassTools\\briefdesk\\venv\\Scripts\\python.exe -X utf8 briefdesk-plan\\_check_pipeline_real.py
"""
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, r"G:\ClassTools\briefdesk\scripts")
FAILED = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else (" | " + str(detail)[:300])))
    if not cond:
        FAILED.append(name)


def main():
    with tempfile.TemporaryDirectory(prefix="v2e2e_") as d:
        tmp = Path(d)
        import build_notice_board as builder
        builder.OUT = tmp / "demo.html"
        builder.BOARD_DATA = tmp / "board-data.json"
        t0 = time.time()
        builder.main()
        took = time.time() - t0
        board = json.loads((tmp / "board-data.json").read_text(encoding="utf-8"))
        groups = board.get("groups") or []
        print("  real builder: groups=%d docs=%d took=%.1fs size=%.2fMB" % (
            len(groups), len(board.get("docs") or []), took,
            (tmp / "board-data.json").stat().st_size / 1048576))
        check("真实数据 builder 成功", (tmp / "demo.html").exists() and len(groups) > 20)
        check("真实数据无接龙卡", not any("接龙" in json.dumps(g, ensure_ascii=False) for g in groups))
        check("真实数据 build 耗时合理(<120s)", took < 120, took)
        # 微信媒体采集：当前班级群消息不可读 → 0 候选但不抛错；manifest 结构正常
        import wechat_media
        r = wechat_media.run(lookback_days=1)
        print("  wechat_media real:", r)
        check("微信媒体采集失败可降级（不抛错）", isinstance(r, dict) and "candidates" in r)
        st = wechat_media.stats()
        print("  wechat_media stats:", st)
        # ai_triage 采集计数（当前微信阻塞的取证）
        import ai_triage
        cutoff = time.time() - 30 * 3600
        qq = ai_triage.collect_qq(cutoff)
        wx = ai_triage.collect_wx(cutoff)
        print("  collect_qq=%d collect_wx=%d" % (len(qq), len(wx)))
        check("ai_triage 微信采集函数可运行", isinstance(wx, list))
        check("QQ 采集未回归（>0）", len(qq) > 0, len(qq))
    print("\n== %d FAILED ==" % len(FAILED) if FAILED else "\n== REAL PIPELINE SMOKE PASS ==")
    for f in FAILED:
        print(" -", f)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
