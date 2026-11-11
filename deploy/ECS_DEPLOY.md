# ECS 备案落点部署（阿里云 class_tool / 121.196.47.2）

> 2026-11-10 建立。用途：ICP 备案通过后，`tool.furina.fun` 要从香港 OSS 切到内地 ECS；
> 本文件记录 ECS 端部署通道、当前状态、HTTPS 启用步骤与回滚方式。
> 相关：`deploy/ecs_site.py`（部署脚本）、`AGENTS.md` §0（部署授权 / 双远端同步）、`SYNC.md`。

## 1. 为什么用「云助手」而不是 SSH

- ECS 安全组 22 端口**只放行家庭固定 IP**（`110.88.108.89/32`），本机当前出口 IP 不在白名单，SSH 连不上；
- 实例云助手 Agent 在线（`CloudAssistantStatus=true`，版本 2.2.4），可通过阿里云 OpenAPI `RunCommand` 执行 shell，无需密钥登录；
- 脚本复用 `deploy/sync_tools.py::load_creds()` 的 AK/SK（**只在本机读取，不打印、不进远端命令**）。

## 2. 当前状态（2026-11-10 18:29 实测）

| 项 | 值 |
|---|---|
| 实例 | `class_tool` / `i-bp1ibr9hs7ewepmm1ugw`，杭州 2C2G，Ubuntu，到期 2027-11-03 |
| 站点目录 | `/var/www/tool`：`index.html` = **802,355 B / sha256 `e40571d3…`**（= OSS 线上最新版，2026-11-10 18:51），另有 `tt.json`、`assets/qr_tools.png`、`favicon.ico`、`apple-touch-icon.png`、`robots.txt` |
| Web 服务器 | Caddy **2.6.2**，仅 `:80`（HTTP），配置 `/etc/caddy/Caddyfile` |
| 压缩 | `encode zstd gzip`；`index.html` 传输 **260,997 B**（未压缩 802,355） |
| 缓存头 | `index.html` / `tt.json` / `/board` → `Cache-Control: no-cache`；`/assets/*` 与图标 → `public, max-age=604800` |
| 原有服务（未改） | `/api/*` → uvicorn `127.0.0.1:8090`（briefdesk-board）；`/board*` → `/opt/briefdesk/data/board.html` |
| 通知附件服务（迁移第 2 步） | `/att/*` → `127.0.0.1:8091`（`class-tools-att.service`，systemd，代码 `/opt/class-tools/att-code/`，数据 `/opt/class-tools/attachments/`；签名 URL 契约见 `attachments/CONTRACT.md`） |
| 同源 API 代理（第 3 步就绪，前端已切） | `/v1/rdb/rest/*` → `https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com`（`header_up Host` 已设为网关域名；实测 401/OpenAPI 200/RLS `[]` 正常）。网页 `var CB` 在 `tool.furina.fun` / `121.196.47.2` 下运行时改走同源（字面量保留给本机脚本解析） |
| HTTPS 就绪配置 | `/etc/caddy/Caddyfile.https.ready` 已生成并通过 `caddy validate`（含 `tool.furina.fun` 站点块 + 自动 Let's Encrypt），**尚未启用**（DNS 停用中，无法签发） |
| 备份 | 每次 apply 前备份到 `/var/www/tool_backup/<时间戳>/`（旧 `index.html` + 旧 `Caddyfile`） |
| 实测 | `curl http://121.196.47.2/` = 800,243 B 且与本地 sha 一致；`/board` 8,555,473 B、`/api/status` 200、`/tt.json` 7,463 B |

## 3. 用法（在 `web` 目录下执行，用带 `aliyunsdkcore` 的 Python，例如系统 `python`）

```powershell
python deploy\ecs_site.py probe            # 只读：磁盘 / Caddy 版本 / Caddyfile / 站点文件 / 本机 HTTP / gzip
python deploy\ecs_site.py apply            # 从 OSS 拉最新静态站 → /var/www/tool；写入 HTTP Caddy 配置并 reload
python deploy\ecs_site.py verify           # 本机校验 ECS 字节（sha、gzip、/board、/api/status、/tt.json）
python deploy\ecs_site.py apply --dry-run  # 只打印将要执行的远端脚本
```

- `apply` 流程：备份 → 从 OSS 公开地址下载（`https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com`）→ 原子替换 → 写 `Caddyfile.new` + `Caddyfile.https.ready` → `caddy validate` 两个文件 → 替换并 `systemctl reload caddy` → 本机 `verify`。
- 站点内容以 **OSS 为唯一真源**：先 `python deploy/sync_tools.py` 上传 OSS，再 `ecs_site.py apply` 同步 ECS（两步都成功才算上线）。

## 4. HTTPS 启用（ICP 备案通过、`tool` 解析恢复之后）

前提：`tool.furina.fun` 的 A 记录已指向 `121.196.47.2`（备案落点），公网可解析。

```powershell
python deploy\ecs_site.py apply --https
```

- 会把 `/etc/caddy/Caddyfile.https.ready` 的内容装为正式 `Caddyfile`：`tool.furina.fun` 走 443 + Caddy 自动 Let's Encrypt（HTTP-01），80 自动跳 443；另保留 IP 直连 `:80` 入口。
- 首次签发需几十秒；验证：
  ```powershell
  curl.exe -I https://tool.furina.fun/          # 200 + 证书
  curl.exe -I http://tool.furina.fun/           # 301/308 → https
  ```
- 若签发失败（DNS 未生效 / 80 被拦），Caddy 会继续重试；可 `systemctl status caddy`、`journalctl -u caddy -n 50` 查看。

## 5. 回滚

```bash
# ECS 上
BK=/var/www/tool_backup/<最近时间戳>
cp -a $BK/index.html.old /var/www/tool/index.html
cp -a $BK/Caddyfile.old /etc/caddy/Caddyfile
systemctl reload caddy
```

或重新 `apply` 一次（会用 OSS 当前版本覆盖）。改动前后都可用 `ecs_site.py verify` 比对 sha。

## 6. 已知未完成（迁移第 2/3 步）

1. **通知附件外置（第 2 步）**：ECS 服务 + 网页端 + **小程序/安卓源码**均已完成（mp `unit 305/0`、安卓 `testDebugUnitTest 934/0`），但本机管线**默认关闭**（`NOTICE_ATTACH_EXTERNALIZE` 未开）。
   因为 `tool.furina.fun` 尚未备案解析，现在开会让已发布的旧版小程序/安卓遇到 http/IP URL；等备案通过 + 三端新版发布后按
   `attachments/README.md` §2 一次性开启（存量 41 个附件自动回填）。
2. **前端同源切换（第 3 步）**：已完成并随 2026-11-10 的 `index.html`（802,355 B）部署；逻辑是运行时按 `location.hostname`
   决定 `CB = location.origin + "/v1/rdb/rest/"`（仅 `tool.furina.fun` / `121.196.47.2`），其它来源仍走 CloudBase 网关。
3. **PPT 媒体仍在 OSS 香港**（`ppt/a/…`），跨境访问慢；后续可加 ECS 反代 + 磁盘缓存（媒体不可变，适合长缓存）。

## 8. PPT 文件本地缓存（下载加速，2026-11-11）

> 背景：兼容包 `compat.pptx` 约 37MB 在 OSS **香港**，本机→OSS 单连接实测 ~74KB/s（要 8 分钟）；
> ECS 杭州→OSS 单连接约 0.6–2.5MB/s；用户→ECS 约 4.7MB/s。方案：ECS 本地磁盘缓存 PPT 文件，
> Caddy 以 `/pptfiles/*` 暴露；转换机上传完成后调用预热，用户下载走 ECS。

### 8.1 组件

| 项 | 值 |
|---|---|
| 服务 | `class-tools-pptfiles.service`（systemd，User=www-data，Restart=always） |
| 代码 | `/opt/class-tools/pptfiles/app.py`（来源 `deploy/pptfiles_app.py`，Python 标准库） |
| 监听 | `127.0.0.1:8092`（仅本机；公网只能经 Caddy） |
| 缓存目录 | `/opt/class-tools/pptfiles/ppt/...`（www-data 可写） |
| 缓存上限 | `PPTFILES_MAX_BYTES` 默认 **5GiB**，超出按 mtime 删最旧（`.part` 不计数） |
| Caddy 路由 | `/pptfiles/*` → `uri strip_prefix /pptfiles` → `reverse_proxy 127.0.0.1:8092`（HTTP、HTTPS-ready 域名块、IP:80 块三处配置一致） |
| 部署脚本 | `python deploy\ecs_pptfiles.py deploy|probe|verify`（云助手；代码 >16KB 自动分片上传，单条命令 <16KB 限制） |

### 8.2 接口

```text
GET/HEAD  /pptfiles/ppt/<path>        仅允许 ppt/ 前缀；命中缓存直接下发
                                      头：Content-Type / Content-Length / Accept-Ranges: bytes
                                          Cache-Control: public,max-age=31536000,immutable / ETag
                                      Range: bytes=… → 206 + Content-Range（未缓存时先完整落盘再 206）
                                      未缓存 GET：边下边发（同时写 .part），完成后原子 rename；同 path 串行加锁
GET       /pptfiles/__warm/ppt/<path> 后台预热（已缓存 200 JSON；正在预热/已启动 202 JSON）
GET/HEAD  /pptfiles/__health          200 JSON：{ok, files, bytes, warming, root, max_bytes, uptime_s, version}
```

- 防穿越：仅 `ppt/` 前缀、拒绝 `..`/反斜杠/NUL，实测 `/pptfiles/ppt/../etc/passwd` → **400**；
- 上游：`https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/<path>`（公共读，无凭据）；
- 日志：`journalctl -u class-tools-pptfiles -f`（每个请求一行 + 预热/淘汰/cache 写入）。

### 8.3 部署与验证（web 目录，系统 python）

```powershell
python deploy\ecs_pptfiles.py deploy            # 分片上传 app.py + unit + 缓存目录 + 重启 + 本机健康检查
python deploy\ecs_pptfiles.py probe             # 服务状态/缓存文件/磁盘/journal/Caddy 路由
python deploy\ecs_pptfiles.py verify --path ppt/a/<deckId>/<buildId>/compat.pptx --timeout 25
                                                # 公网：health / HEAD / 预热 / Range(206) / 下载测速
python deploy\ecs_site.py apply                 # 同时更新 Caddy 配置（含 /pptfiles 路由）并再次安装本服务
python deploy\ecs_site.py verify                # 末尾含 pptfiles health 检查
```

**手动预热 / 清理缓存**：

```bash
# 预热（转换机在上传后会自动调用；也可手动）：
curl -sS http://121.196.47.2/pptfiles/__warm/ppt/a/<deckId>/<buildId>/compat.pptx
curl -sS http://121.196.47.2/pptfiles/__warm/ppt/a/<deckId>/<buildId>/preview.pdf
curl -sS http://121.196.47.2/pptfiles/__warm/ppt/a/<deckId>/<buildId>/original.pptx

# 查看缓存占用：
curl -sS http://121.196.47.2/pptfiles/__health
du -sh /opt/class-tools/pptfiles/ppt

# 清理全部缓存（不影响 OSS 原件；下次请求自动回源）：
systemctl stop class-tools-pptfiles && rm -rf /opt/class-tools/pptfiles/ppt/* && systemctl start class-tools-pptfiles
# 清理某个 deck：
rm -rf /opt/class-tools/pptfiles/ppt/a/<deckId>/
```

### 8.4 实测（2026-11-11 12:44–12:50）

- `/__health`：`{"ok": true, "files": 5, "bytes": 78245019, "warming": 0, "max_bytes": 5368709120}`（缓存 ~74.6MB）；
- **HEAD** `compat.pptx` → **200**，`Content-Length: 39063744`，`Content-Type: application/vnd.openxmlformats-officedocument.presentationml.presentation`，`Accept-Ranges: bytes`，`Cache-Control: public, max-age=31536000, immutable`；
- **GET** 200；**Range** `bytes=100-199` → **206**，`Content-Range: bytes 100-199/39063744`；
- **预热 39MB compat**：首次 `/__warm/` 后台回源耗时 **约 74s**（当时 ECS→OSS ≈0.53MB/s）；
- **本机下载（预热后，37.25MB）**：`curl --max-time 25` → **4.41s / 8.44MB/s**；完整 GET 4.07s / 9.14MB/s；
- **首次未缓存直下（38MB original.pptx，边下边发）**：14.88s / **2.56MB/s**（本次 ECS→OSS 达标）；缓存后二次下载 2.50s / **15.2MB/s**；
- 磁盘：ECS `/` 40G，已用 7.3G，可用 31G；缓存目录 `75M`（上限 5GiB 自动淘汰）。

### 8.5 回滚

```bash
systemctl disable --now class-tools-pptfiles     # 停服务（Caddy /pptfiles/* 会 502；客户端应回退 OSS 直链）
rm -rf /opt/class-tools/pptfiles /etc/systemd/system/class-tools-pptfiles.service
# Caddy 路由回滚：把 deploy/ecs_site.py 里的 pptfiles handle 去掉后重新 apply
```
## 7. 安全与边界

- `ecs_site.py` 不含任何密钥；远端命令只做文件下载/替换/Caddy reload，不含凭据；云助手执行记录留在阿里云账号内。
- 不要在前端/仓库中出现 OSS 写凭据；ECS 只读 OSS 公开对象。
- 备案期 `tool.furina.fun` 仍不可解析；ECS 的 IP 入口仅用于本机验证，不对外宣传。
