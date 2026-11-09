# CloudBase 后端（云端作业板）

> 目标：**任何人可发布作业，发布后所有设备看到同一份数据。**
> 方案：CloudBase **PostgreSQL + PostgREST HTTP 接口**，前端只用原生 `fetch()`，
> **不引入 SDK、不引入构建链、不加任何 `<script src>`**。

## 目录

| 文件 | 说明 |
|------|------|
| `cloudbaserc.json` | 环境 ID / 地域（无密钥） |
| `schema.sql` | 建表 + RLS + 权限（幂等） |
| `publish_key.txt` | 前端用的 **Publishable Key**（设计上就是公开的，见下） |
| `README.md` | 本文件：一次性配置 + 运维 + 排查 |

## 已配置的云端资源（一次性，已完成）

| 项目 | 值 |
|------|-----|
| 环境 envId | `tool-d4gosudok46e0e081` |
| 地域 | `ap-shanghai`（上海） |
| 套餐 | 个人版 |
| 数据库 | PostgreSQL（该环境**未开通文档型数据库**，别用 `db.collection()`） |
| 表 | `public.homework` |
| 接口根 | `https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/homework` |
| 鉴权 | `Authorization: Bearer <publish_key>`（角色 `anon`） |
| 安全来源(CORS) | `tool.furina.fun` |

## 一次性配置（重来一遍时的命令）

```powershell
# 0) 登录（设备码流程，无浏览器环境也能用）
tcb login                     # 打开输出链接 → 输入用户码 → 授权

# 1) 建表 + RLS（schema.sql 里的语句逐条执行）
tcb db execute -e tool-d4gosudok46e0e081 --sql "create table if not exists public.homework (...)"
tcb db execute -e tool-d4gosudok46e0e081 --sql "alter table public.homework enable row level security"
tcb db execute -e tool-d4gosudok46e0e081 --sql "grant usage on schema public to anon"
tcb db execute -e tool-d4gosudok46e0e081 --sql "grant select, insert, update on public.homework to anon"
tcb db execute -e tool-d4gosudok46e0e081 --sql "create policy hw_read   on public.homework for select to anon using (true)"
tcb db execute -e tool-d4gosudok46e0e081 --sql "create policy hw_insert on public.homework for insert to anon with check (true)"
tcb db execute -e tool-d4gosudok46e0e081 --sql "create policy hw_update on public.homework for update to anon using (true) with check (true)"

# 2) 生成前端发布密钥（--type publish_key）
tcb env apikey create hw-publish -e tool-d4gosudok46e0e081 --type publish_key --json   # 取 data.ApiKey

# 3) 放通站点跨域（**不加 https:// 前缀**，写裸域名）
tcb cors add tool.furina.fun -e tool-d4gosudok46e0e081

# 4) 自测
curl "https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/homework?select=*&order=ts.asc" -H "Authorization: Bearer <KEY>"
```

## 运维手册

```powershell
# 看全部数据
tcb db execute -e tool-d4gosudok46e0e081 --sql "select id,subject,due,done,archived from public.homework order by ts"

# 删一条（管理员 CLI 有权限，anon 没有）
tcb db execute -e tool-d4gosudok46e0e081 --sql "delete from public.homework where id='xxx'"

# 清空测试数据
tcb db execute -e tool-d4gosudok46e0e081 --sql "delete from public.homework"

# 换密钥（旧的记得 tcb env apikey delete <KeyId>）
tcb env apikey create hw-publish-v2 -e tool-d4gosudok46e0e081 --type publish_key --json

# 看跨域白名单
tcb cors list -e tool-d4gosudok46e0e081
```

## 踩坑记录（真的踩过）

1. **这个环境没有文档型数据库**。`@cloudbase/node-sdk` 的 `db.collection()` 会报
   `the reource is not found`；`tcb db nosql execute` 报「当前环境未开通文档型数据库」。
   本环境是 **PostgreSQL (PostgREST)**，所以走 HTTP 接口。
2. **CLI 的 `--httpFn` 是 Web 函数**（要 `scf_bootstrap`），且 HTTP 网关路由的上游类型得是
   `WEB_SCF`；事件型函数配 `SCF`。两者混用报 `FUNCTIONS_PARAM_INVALID`。
   → 最终**没用云函数**，直接 PostgREST，少一层。
3. **`tcb routes add` 不能给默认域名加路由**（`is a system internal domain`）。
4. **CLI 的登录态是按当前目录分项目存的**：在 A 目录 `tcb login`，到 B 目录会报
   `No valid identity found`。就在同一目录里操作，或统一从 `workspace` 根跑 + `-e`。
5. **PowerShell 传 `--data '{...json...}'` 会被吃引号** → 用 Python `subprocess` 以参数数组调用
   `node .../@cloudbase/cli/bin/tcb`，绕开引号地狱。
6. **安全来源要写裸域名**（`tool.furina.fun`），写 `https://tool.furina.fun` 会被当成不匹配；
   加完之后**有几十秒~几分钟生效延迟**，别急着判定失败。
7. **Publishable Key 是公开凭据**（角色 `anon`，权限只由 RLS 决定），放进前端 HTML 是它的设计用途；
   但 **`--type api_key` 的是服务端密钥，绝不能进前端**。
