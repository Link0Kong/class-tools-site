# 通知附件外置 · 运维 README

> 一句话：通知附件从 CloudBase 数据库里的 base64 搬到 ECS 私有目录，用签名 URL 下发；
> 契约/字段/安全见 [CONTRACT.md](CONTRACT.md)。本文件只讲「怎么部署、怎么开、怎么回滚」。

## 1. 部署（一次性，已完成 2026-11-10）

前置：`deploy/ecs_site.py` 已能通过云助手操作 ECS（见 [../deploy/ECS_DEPLOY.md](../deploy/ECS_DEPLOY.md)）。

```powershell
cd %USERPROFILE%\.openclaw\workspace\web

# 1) 部署附件服务（写代码到 /opt/class-tools/att-code，systemd class-tools-att，本机自测上传/下载）
python deploy\ecs_attachments.py deploy

# 2) 让 Caddy 增加 /att/* 反代（同时刷新静态站；幂等）
python deploy\ecs_site.py apply

# 3) 健康检查（经 Caddy）
curl.exe https://tool.furina.fun/att/healthz
```

状态（2026-11-10 18:5x 实测）：
- `class-tools-att.service` active；`/att/healthz` → `{"ok":true,"attachments":N,"auth":true}`；
- 上传→签名 GET→sha 校验通过；篡改签名 403；`Cache-Control: public, max-age=31536000, immutable`；
- ECS 上附件目录 `/opt/class-tools/attachments/`，代码 `/opt/class-tools/att-code/`，备份 `/opt/class-tools/backup/<时间戳>/`。

## 2. 开启外置（**备案已通过（2026-11-23）；等四端新版发布后再开启**）

> 域名/HTTPS 已就绪（`https://tool.furina.fun/att/...` 可用），但**已发布的旧版小程序/安卓不认识 URL 形态附件**（旧版只读 data URI）。
> 因此仍需等小程序/安卓/鸿蒙/Windows 新版发布后，四端一起开启；在那之前保持默认关闭。

```powershell
# 本机环境变量（给 C:\briefdesk\scripts\sync_notices_cloud.py 用；计划任务进程需要能读到）
setx NOTICE_ATTACH_EXTERNALIZE 1
setx ATT_BASE_URL https://tool.furina.fun

# 手动跑一次同步（会把 95 条 auto 通知整体重写，自动回填存量 41 个附件）
C:\briefdesk\venv\Scripts\python.exe C:\briefdesk\scripts\sync_notices_cloud.py
```

观察点：
- 脚本输出 `notice attachments externalized: files=.. uploaded=.. replaced=.. failed=0`；
- CloudBase `notices.body` 里不再有 `data:...;base64,`（只剩签名 URL）；
- 网页/小程序/安卓三端附件可打开（图片直显、PDF/Word 下载/预览）。

回滚：取消环境变量（`setx NOTICE_ATTACH_EXTERNALIZE 0`）后跑一次同步 → 下次重建又写回 data URI；
或按 CONTRACT §5 用旧版客户端。ECS 服务可 `systemctl stop class-tools-att`（附件 URL 会 403，但旧 data URI 仍可读）。

## 3. 测试/自检

```powershell
python attachments\tests\test_attachments.py            # 算法+替换逻辑（23/23）
cd tools; python tests\v2_attach_url_check.py           # 网页渲染 URL/data URI（9/9）
cd tools; python tests\v2_notice_data_check.py         # 通知数据回归（27/27）
```

## 4. 排障

| 现象 | 排查 |
|---|---|
| `/att/healthz` 502 | `systemctl status class-tools-att`、`journalctl -u class-tools-att -n 50`；Caddyfile 是否有 `/att/*` |
| 上传 403 | 本机 `cloud.env` 的 `CLOUD_SYNC_TOKEN` 与 ECS `/etc/briefdesk-board.env` 的 `SYNC_TOKEN` 不一致 |
| 附件 403 | URL 过期（>180 天）或签名被改；重跑一次通知同步重新签名 |
| 附件 404 | ECS 目录文件被清；重跑开启外置的同步会重新上传（内容寻址，可重建） |
| 图片裂 | Caddy route 未 reload；或三端把 `http`/`https` 判断写死（应只认 `^https?://`） |
| 安卓/小程序打不开文件 | 小程序需在微信后台配 `downloadFile` 合法域名；安卓检查网络权限与下载大小限制 |
