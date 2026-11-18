# -*- coding: utf-8 -*-
"""离线自检：ecs_site 生产 API 路由两种模式的生成结果（不联网、不改 ECS）。

运行：python deploy\\migration\\selftest_cutover_config.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(WEB, "deploy"))
import ecs_site  # noqa: E402

PASS = []


def check(name, cond, detail=""):
    PASS.append((name, bool(cond)))
    print(("[PASS] " if cond else "[FAIL] ") + name + ((" | " + detail) if detail else ""))


def gen(mode):
    os.environ["CLASS_API_MODE"] = mode
    return ecs_site._caddy_https()


def main():
    # selfhosted：生产路由 2 处（domain + :80）都指向本地 PostgREST，不再出现 CloudBase 网关
    sh = gen("selfhosted")
    check("S1 selfhosted 生成 2 处 handle_path /v1/rdb/rest/*", sh.count("handle_path /v1/rdb/rest/*") == 2)
    check("S2 selfhosted 不再引用 CloudBase 网关", "tcloudbasegateway" not in sh)
    check("S3 selfhosted 剥 Authorization", sh.count("header_up -Authorization") >= 2)
    check("S4 staging 路由两种模式都保留", sh.count("rest-next") == 2)
    check("S5 本地 PostgREST upstream 出现", "reverse_proxy 127.0.0.1:3000" in sh)

    # cloudbase：默认模式保持原样（生产仍反代 CloudBase，:80 与域名块各 1 次）
    cb = gen("cloudbase")
    check("C1 cloudbase 生产 handle 2 处", cb.count("handle /v1/rdb/rest/*") == 2)
    check("C2 cloudbase 引用网关", cb.count("tcloudbasegateway.com") >= 2)
    check("C3 cloudbase 不出现本地生产路由", "handle_path /v1/rdb/rest/*" not in cb)
    check("C4 cloudbase 仍保留 -Origin 修复", cb.count("header_up -Origin") == 2)
    check("C5 staging 路由保留", cb.count("rest-next") == 2)

    # 非法模式拒绝
    try:
        gen("bogus")
        check("I1 非法模式拒绝", False)
    except SystemExit:
        check("I1 非法模式拒绝", True)
    finally:
        os.environ.pop("CLASS_API_MODE", None)

    ok = all(x[1] for x in PASS)
    print("=" * 52)
    print("selftest_cutover_config: %d 项，PASS %d，FAIL %d"
          % (len(PASS), sum(1 for _n, v in PASS if v), sum(1 for _n, v in PASS if not v)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
