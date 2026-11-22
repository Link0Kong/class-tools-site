# 通知管理（管理员）契约 · 2026-11-22

网页「通知」页右上角「管理」入口 → `#s-ntadmin` 页（`TOOLS` 中 `admin:true`，服务端数据也仅管理员可读）。
三块能力：① QQ/微信群聊采集开关 ② 每个群的通知可见人群 ③ 还需获取的文件清单。

## 1. 可见性 / 权限

| 层 | 规则 |
|---|---|
| 页面 | `TOOLS` 项 `admin:true`；`gotoTab` 用 `toolShown()` 拦截；非管理员不渲染「管理」入口、不发任何配置请求 |
| 云端 | 配置/状态全部存 `public.site_config`（现有 RLS：`sc_read/sc_insert/sc_update = auth_admin()`）；非管理员读到的永远是 `[]` |
| 通知 | `public.notices.audience` 由采集端按下发配置写入；RLS `nt_read` 决定谁能看见 |

## 2. 云端行（`public.site_config`）

| id | 写者 | 内容 |
|---|---|---|
| `notice_groups` | 网页管理员 | 采集/可见人群配置（唯一真源） |
| `notice_status` | 本机 `notice_admin.py` | 应用状态 + 待获取文件快照（网页只读） |
| `notice_request` | 网页管理员 | 请求本机重扫下载目录：`{scanAt:<ms>, by:<sid>}` |

所有行 `value` 为 JSON，`updated_at` 为 `timestamptz`。

### 2.1 `notice_groups`

```json
{
  "v": 1,
  "rev": 7,
  "updatedAt": "2026-11-22T16:30:00+08:00",
  "updatedBy": "2026xxxxxx",
  "groups": [
    {
      "platform": "qq",
      "gid": "1101960522",
      "name": "2026级信息管理与信息系统",
      "capture": {"ai": true, "file": true, "image": true, "doc": true},
      "audience": {"type": "all", "seats": [], "set": ""},
      "added": false
    },
    {
      "platform": "wx",
      "gid": "56720123123@chatroom",
      "name": "26信管班群",
      "capture": {"ai": true, "file": false, "image": false, "doc": false},
      "audience": {"type": "custom", "seats": [1, 8, 12], "set": ""}
    }
  ]
}
```

- `platform`: `qq` / `wx`；`gid`: QQ 群号 / 微信 talker（`xxx@chatroom`、`filehelper`）；只按名字匹配时可为空串。
- `capture.ai`：QQ 文本消息 / 微信文本+附件；`file`：QQ 单文件通知；`image`：QQ 图片 OCR；`doc`：腾讯文档/合并记录。
- `audience.type`：`all` | `committee` | `league` | `admin` | `custom`（座号）| `set`（沿用现有群成员名单，`set` 填 `volunteer/viewer/blood/review/dorm/redcross`）。
- 网页每次修改 `rev+1`、刷新 `updatedAt`、写 `updatedBy`。
- **未知群**（不在配置里）仍按原有关键词规则处理，避免新群静默漏采；已知群完全以配置为准。

### 2.2 `notice_status`

```json
{
  "agentAt": "2026-11-22T16:35:10+08:00",
  "configRev": 7,
  "configUpdatedAt": "2026-11-22T16:30:00+08:00",
  "appliedAt": "2026-11-22T16:31:02+08:00",
  "pendingCount": 10,
  "pending": [
    {"name":"民族器乐大赛招募志愿者名单.xlsx","group":"2026级信息管理与信息系统聊天群",
     "platform":"qq","noticeId":"g_ait_...","title":"民族器乐大赛志愿者入选名单公示",
     "time":"11-19 14:06","from":"08曹明星","source":"QQ 群 · ..."}
  ],
  "boardAt": "2026-11-22T16:30:40+08:00",
  "scanAt": 1763xxxxxxx
}
```

- `pending` = `board-data.json` 中 `items[].kind=="file"` 且无 `url`（非 `lazy`）的条目，按 (群, 文件名) 去重、按时间倒序，最多 500 条。
- 网页只读；「刷新」重读本行，「重新扫描」写 `notice_request` 后重读（最多等一轮看门狗 ≈5 分钟）。

## 3. 本机应用（`G:\ClassTools\briefdesk\scripts`）

- `notice_admin.py`：拉 `notice_groups` → 归一化 → 原子写 `data/notice-group-config.json`；处理 `notice_request`；发布 `notice_status`。
  - 看门狗每轮（5 分钟）隐藏启动一次；`sync_notices_cloud.py` 每次同步前也会轻量应用一次配置。
  - 云端无 `notice_groups` 行时用本机现状播种（见 §4），只写一次，绝不覆盖管理员配置。
  - 单实例锁 `data/notice-admin.lock`（>180s 视为陈旧）。
- `notice_groups.py`：所有管线脚本共享的只读视图；配置缺失/异常时返回 `None`，调用方回落到原有关键词规则。
- 可见人群写入：`sync_notices_cloud.audience_of()` 先查配置，再回落到原有规则。

## 4. 本机播种（首次）

以本机当前实际生效范围为准，保持改造前行为：

| 维度 | 来源 |
|---|---|
| QQ 群名/群号 | `data/monitored-groups.json` |
| QQ `ai` | `monitored-groups.json` 的 `ai` |
| QQ `file` | `qq_context.GROUPS`（8 群） |
| QQ `image` | `ocr_qq_images.OCR_GROUPS`（9 群） |
| QQ `doc` | `detect_docs.GROUPS`（11 群） |
| 微信 `ai` | `monitored-groups.json` 的 `ai` |
| 微信群 talker | `data/group-audience.json` 按群名匹配 |
| 可见人群 | `data/group-audience.json` 的「通知可见人群」→ audience 值 |
| 未收录群 | 全部 capture=false，audience=`admin` |

## 5. 可见人群取值（RLS）

| `audience` | 谁能看 |
|---|---|
| `all` | 已认证全班 |
| `committee` / `league` | 班委 / 团员（现有函数） |
| `admin` | 管理员 |
| `sid:<学号>` | 指定学号（沿用） |
| `set:<名称>` | `private.class_audience` 名单（沿用） |
| `seats:1,8,12` | 座号命中者；新增 `auth_seat()` + `notice_audience_visible()`，重建 `nt_read` |

迁移：`web/deploy/cloudbase/2026-11-22_notice_groups.sql`。回滚：重建旧 `nt_read`、删两个函数。
`seats:` 只存座号（不存/不显示学号），与投票「指定成员」口径一致。

## 6. 网页交互

- 列表：平台筛选（全部/QQ/微信）+ 搜索；行内主开关 = `capture.ai`；点行展开：四个能力开关（微信只显示「识别」，说明为文本+附件）、可见人群按钮、移除（仅 `added:true`）。
- 「可见人群」弹层：全体 / 班委 / 团员 / 仅管理员 / 指定成员（班级名单座号多选，至少 1 人）；已有 `set` 绑定的群另有「群成员（自动匹配）」。
- 保存：修改后 600ms 防抖 PATCH；`rev+1`；失败 toast + 保留本地待重试。
- 待获取文件：按平台筛选、显示群名/时间/所属通知、单项「复制文件名」、整表「复制清单」；状态卡显示本机应用时间与「配置待应用」。
- 无配置/无状态：显示「等待本机采集端同步」+「添加群聊」按钮，不阻塞页面。

## 7. 测试

- 网页：`web/tools/tests/v2_nt_admin_check.py`（headless Edge + mock fetch，不碰真实云端）：门禁、渲染、筛选、开关/人群保存、防抖、待获取、空态、360/390/430 无溢出、0 JS 报名、0 外部请求。
- 本机：`briefdesk/scripts/tests/test_notice_admin.py`（临时配置/board 夹具）：播种、归一化、可见性映射、待获取提取、配置缺失回落。
- 云端：`web/tools/tests/nt_admin_cloud_check.py`（临时 QA 9999 身份 + `rpc/notice_audience_visible`）：seats 命中/不命中、all/committee/sid，`finally` 删除临时身份；不写业务数据。
