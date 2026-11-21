# deploy/functions —— CloudBase 云函数的 ECS 替代（P3）

## 这是什么

班级工具站的三个定时任务原本跑在 CloudBase 云函数上（2026-12-10 环境到期）：

| 云函数 | 时间表 | 作用 | 写库 |
|---|---|---|---|
| `power_sync` | 每小时 :01 | 完美校园网关 → `public.power` + `power_history` | 是 |
| `xgj_sync` | 每 2 小时 :20 | 班级小管家英语作业 → `public.homework`（`auto_hw_xgj_en_*`） | 是 |
| `health_probe` | 每 5 分钟 | 依赖服务健康巡检 → `public.service_health`（cloud 8 行） | 是 |

本目录把这三个函数**源码**（不含密钥）留在仓库里，供 `deploy/ecs_cron.py` 部署到 ECS
`/opt/class-tools/jobs/`，用 systemd timer 替代 CloudBase 定时触发器。

## 文件

```
deploy/functions/
  jobs_runner.py                  ECS 侧任务分发（读 jobs.env → 调各 job 的 main_handler → 写心跳）
  cloud_backend.py                = C:\briefdesk\scripts\cloud_backend.py（同源；ECS 上靠 jobs.env 解析后端）
  jobs.env.example                /etc/class-tools/jobs.env 键名模板（真值由 ecs_cron.py 生成本地 600 文件）
  power_sync/index.py             = C:\briefdesk\cloudbase\functions\power_sync\index.py
  power_sync/sync_power_cloud.py  = C:\briefdesk\scripts\sync_power_cloud.py（同源）
  xgj_sync/index.py               = C:\briefdesk\cloudbase\functions\xgj_sync\index.py
  xgj_sync/xgj_homework.py        = C:\briefdesk\scripts\xgj_homework.py（同源）
  health_probe/index.py           = C:\briefdesk\cloudbase\functions\health_probe\index.py
  health_probe/health_beat.py     = C:\briefdesk\cloudbase\functions\health_probe\health_beat.py
                                    ⚠️ P4 起含「PG 监控并入 cloudbase 行」，**不再等于**
                                    C:\briefdesk\scripts\health_beat.py（本机 watchdog 版保持 P3 行为）
  tests/test_health_pg_monitor.py P4 PG 监控并入逻辑离线单测（19 项；不上传 ECS）
```

**同源规则**：`index.py` / `health_beat.py` / `sync_power_cloud.py` / `xjg_homework.py`
的真源在 `C:\briefdesk\cloudbase\functions\`（index.py）与 `C:\briefdesk\scripts\`；
普通变更改真源后重新复制到本目录（`cloudbase/deploy.py` 部署 CloudBase 时也会刷新云函数目录里的副本）。
**唯一例外（P4）**：`health_probe/health_beat.py` 的 PG 监控并入逻辑只服务 ECS/自建后端，
按 task-12 要求只落在 `deploy/functions/` 与 `C:\briefdesk\cloudbase\functions\health_probe\` 两份副本，
本机 `scripts/health_beat.py`（watchdog 本机 10 行）**有意不改**；其余文件仍按同源规则维护。

三个 `index.py` 完全复用原 CloudBase 云函数实现（不改成 ECS 专用代码）：
`jobs_runner.py` 只负责「换后端地址、调 handler、写心跳、记退出码」。

## 部署 / 启用 / 回滚

唯一入口 `deploy/ecs_cron.py`（云助手 RunCommand，无需 SSH；系统 python 需 aliyunsdkcore）：

```powershell
cd %USERPROFILE%\.openclaw\workspace\web
python deploy\ecs_cron.py install --dry-run          # 只打印计划（所有值脱敏）
python deploy\ecs_cron.py install                    # 安装；默认 staging 后端，timer 全部禁用
python deploy\ecs_cron.py status                     # 只读：timer/心跳/env 键名
python deploy\ecs_cron.py smoke --job health_probe   # 手动跑一轮（timer 仍禁用；仅 staging）
python deploy\ecs_cron.py enable --confirm           # 切流后启用三个 timer
python deploy\ecs_cron.py disable                    # 停用（文件保留）
python deploy\ecs_cron.py uninstall [--purge]        # 删 unit；--purge 连 env/代码/心跳一起删
```

时间表（systemd timer）：`power-sync` `*-*-* *:01:00`、`xgj-sync` `*-*-* 00/2:20:00`、
`health-probe` `*-*-* *:00/5:00`，均带 `Persistent=true`（主机短暂离线后补跑一轮）。

**默认禁用**：`install` 只写文件 + `systemctl disable --now`，不会产生任何写库；
切流（P4）后再 `enable --confirm`，回滚用 `disable`。

## 环境变量（值全部由 ecs_cron.py 从本机读取后写入 600 的 /etc/class-tools/jobs.env）

只列键名（**任何文档/日志都不写值**）：

- 目标后端：`CB_BASE` / `CB_KEY`（`index.py` 包装层读）、`CLASS_CB_BASE` / `CLASS_CB_KEY`（`scripts/cloud_backend.py` 同源脚本读）；
- 管理员：`CLASS_ADMIN_SID` / `CLASS_ADMIN_NAME`（`rpc/class_verify` 换 token）、可选 `CLASS_TOKEN`；
- 学工记：`XGJ_TOKEN` / `XGJ_MEMBER_ID` / `XGJ_EXP` / `XGJ_EXP_TEXT` / `XGJ_CID`；
- 心跳：`CLASS_JOB_HEARTBEAT=1`、`CLASS_JOBS_STATE=/var/lib/class-tools/jobs/state`、`CLASS_HEALTH_RUNNER=ecs-timer`；
- PG 监控（P4）：`CLASS_PG_MONITOR=/var/lib/class-tools/pg-monitor.json` —— 自建后端模式下
  `health_probe` 把 round-3 PG 监控并入既有 `cloudbase` 行（detail 追加 PG 指标、`meta.pg` 完整字段），
  文件缺失/损坏/`ts`>30 分钟时该行降级 warn；**不新增行（18 行契约不变）**；CloudBase 模式不读文件、行为不变。

## 心跳契约（health_beat.py 读）

`jobs_runner.py` 每次运行后原子写 `/var/lib/class-tools/jobs/state/<row_id>.json`（600）：

```json
{"row":"cloud_power_sync","job":"power_sync","runner":"ecs-timer","at_ms":1794980178216,
 "ok":true,"rc":0,"ms":1234,"host":"class_tool","version":"2026-11-18.p3",
 "backend":"staging","rows":17,"patched":17,"posted":0,"summary":"…"}
```

`health_beat.py` 在 `CLASS_JOB_HEARTBEAT=1` 时把它合并进诊断行：
`cloud_power_sync` / `cloud_xgj_sync` 的 `meta.job`，上一轮失败且数据行仍 ok 时降级 `warn`
（detail 追加「（ECS 定时任务上轮失败）」）；`cloud_health_probe.meta.runner=ecs-timer`。
**关闭开关 / 删掉心跳目录 = 回到原「按数据年龄判定」行为**（CloudBase 云函数路径完全不变）。

## 安全

- 真实凭据只在 `ecs_cron.py` 进程内读取 → 云助手 base64 命令 → ECS 本地 `600 root:root` 文件；
  本目录 / 日志 / git **都不含任何凭据**；
- `--dry-run` 打印的 env 内容全部 `***` 脱敏；
- 目标后端默认 staging；`--backend live` 必须显式 `--allow-live`（切流前 `/v1/rdb/rest/*`
  仍反代 CloudBase，误用会把定时任务写进 CloudBase）。
