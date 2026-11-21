# 完美校园宿舍电量查询 / 低电提醒（FJTCM 定制，Windows）

**福建中医药大学（schoolcode=769）**学生宿舍剩余电量查询工具。主链路走完美校园「缴费 →
用电支出（预付费）」背后的**云支付网关**，**免登录**：只要学校编码 + 学号 + 房间号，
不需要完美校园账号密码、不需要短信验证、不需要 deviceId。

功能：

- 查当前剩余电量（单间 / 班级全部房间批量查）；
- 每小时采样写本地 SQLite 台账，周一 00:05 推上周用电周报；
- 剩余电量低于阈值时按 3 小时节流推送提醒（充值后自动重新武装）；
- 生成班级站用的 `snapshot.json` + **单文件 HTML 看板**（双击即看，零外部请求）；
- 可选 5 种推送渠道：PushPlus / 企业微信群机器人 / Server酱 / 通用 webhook / QQ邮箱 SMTP；
- `doctor` 自检；`--fixture` 离线演示/测试；Windows 计划任务一键安装（pythonw 隐藏黑框）。

> ⚠️ **非官方接口**，靠逆向 App/H5 得到，学校或厂商随时可能改协议。只用于查**本校、自己班**的
> 房间，别做批量探测。详见文末「风险与合规」。

---

## 0. 目录与前置条件

```
src\
├─ run.bat / run.ps1          Windows 启动器（UTF-8 控制台）
├─ install_task.ps1           注册/删除计划任务（schtasks + pythonw）
├─ electricity_monitor.py     主程序（query/snapshot/dashboard/sample/report/doctor…）
├─ cloudpay.py                免登录网关客户端（主后端）
├─ wanxiao_login.py           完美校园账密登录（备用后端，默认关闭，vendor 自 MIT 项目）
├─ push.py                    5 种推送渠道适配器
├─ dashboard.py               snapshot -> 单文件 HTML 看板
├─ util.py                    UTF-8/日志/掩码/文件锁/权限/配置校验
├─ config.example.json        配置模板（复制成 config.json 再填）
├─ tests\selftest.py          统计/推送逻辑自检（离线）
├─ tests\smoke.py             全链路离线测试（fixture，不联网）
├─ tests\fixtures\class_rooms.fixture.json   17 个房间的离线 fixture（无姓名）
├─ logs\                      计划任务日志（自动创建）
├─ snapshot.json              snapshot 命令输出（gitignore）
└─ dashboard.html             dashboard 命令输出（gitignore）
```

前置：Windows 10/11 + **Python 3.8+**（本机 3.12 已装）。
主链路只用 Python 标准库；只有启用「账密 fallback」才需要 `cryptography`：

```bat
cd %USERPROFILE%\.openclaw\workspace\perfect-campus-power\src
pip install -r requirements.txt
copy config.example.json config.json
```

`config.json` 里有学号/房间，已列入 `.gitignore`，**不要提交仓库、不要发群里**。

---

## 1. 五步上手（免登录，5 分钟）

### 第 1 步：填 `config.json`

编辑 `src\config.json`，**只需要改这几处**（`schoolcode=769`、`payproid=2122` 已预置）：

| 字段 | 填什么 | 说明 |
| --- | --- | --- |
| `idserial` | 你的学号 | 完美校园绑定的学号（校园卡号=学号），纯数字 |
| `rooms[]` | 班级房间清单 | 每项 `{"label": "13号楼301", "roomverify": "1-13---301"}`；`label`/`building` 会按规范名自动统一 |
| `default_room` | 默认房间 | 写规范名或 `roomverify`（旧 label 也兼容），`query`/`now`/`sample`/`report` 默认查它 |

> **宿舍名统一规范**：`{楼号}号楼{座}{房间号}` —— `13号楼301`、`16号楼301`、
> `23号楼A座301`、`23号楼B座402`。
> 本工具会从 `roomverify` 自动派生规范名（label/building/room 三处统一），
> config 里即使写了旧名字（如 `23A-301`），输出也一律用规范名，`doctor` 会提示你同步配置；
> 班级站与本机工具因此始终是同一套名字。

现成的班级 17 间房清单（规范名 + roomverify，**不含姓名**）可以直接复制：
`tests\fixtures\class_rooms.fixture.json` 里的 `_rooms` 数组。

配置片段示例：

```json
"idserial": "你的学号",
"rooms": [
  {"label": "13号楼301", "roomverify": "1-13---301"},
  {"label": "16号楼301", "roomverify": "1-16---301"},
  {"label": "23号楼A座301", "roomverify": "4-23A---301"},
  {"label": "23号楼B座402", "roomverify": "4-23B---402"}
],
"default_room": "13号楼301"
```

填完先跑一次自检（会告诉你还缺什么）：

```bat
run.bat doctor
```

> 权限收紧：`run.bat secure` 会把 `config.json` / `wanxiao_state.json` / 台账 / 日志的权限
> 收到只剩当前用户可访问（Windows 用 `icacls`）。

### 第 2 步：确认缴费项目 `payproid`

```bat
run.bat projects
```

FJTCM 正常输出（2026-11-05 实测）：

```
schoolcode = 769；idserial = 已配置（11 位学号，不显示）
   * payproid=2122   name=旗山用电支出  businesstype=2  上街校区缴电费
     payproid=3518   name=屏山用电支出  businesstype=2  屏山教职工生活区缴电费
     payproid=4498   name=屏山学生用电  businesstype=2  学生购电
```

住旗山校区的把 `payproid` 填 `2122`（默认就是）。

### 第 3 步：确认 `roomverify`（清单已给可跳过）

如果不知道房间的 roomverify，用房间树命令查（**逐层剪枝，别全量拉**）：

```bat
run.bat rooms --building 13 --room 301
```

输出形如：

```
  旗山校区学生公寓 / 13号楼 / 虚拟楼层 / 301  ->  1-13---301
```

FJTCM 实测要点（2026-11-05）：

- roomverify 格式 = `areaid-楼栋---房间`：`1-13---301`、`4-23B---402`；
- **13号楼、16号楼用 areaid=1**（`1-13---301` / `1-16---301`），规范名 `13号楼301` / `16号楼301`；
- **23号楼 A/B 只在 areaid=4**（`4-23A---301` / `4-23B---402`），规范名 `23号楼A座301` / `23号楼B座402`；
- areaid=4 里也有 13/16 号楼，但只有 6 个房间（不是宿舍楼），别选错；
- 每栋楼 `optype=3` 只返回一个虚拟楼层 `id=-1`，`optype=4` 返回的 `id` 就是 roomverify，不要自己拼。

### 第 4 步：验证能读数

```bat
run.bat doctor              :: 全部检查项（网络只做 TCP 连通，不发任何个人信息）
run.bat query               :: 查默认房间
run.bat now                 :: 同上，now 的别名
```

正常输出：

```
payproid = 2122；房间 1 个；串行查询，每请求间隔 1.1 秒（预计 0 秒）
  [1/1] 13号楼301        78.97 度

房间              roomverify            剩余 单位  状态
--------------------------------------------------------------------------
13号楼301         1-13---301          78.97 度   正常
```

批量查班级全部房间（串行、每请求间隔 1.1 秒，17 间约 20 秒）：

```bat
run.bat query --all
run.bat query --all --json-out query.json
```

### 第 5 步：装计划任务（每小时采样 + 周一 00:05 周报）

```powershell
cd %USERPROFILE%\.openclaw\workspace\perfect-campus-power\src
powershell -NoProfile -ExecutionPolicy Bypass -File install_task.ps1
```

装完会看到：

```
[ OK ] created: PerfectCampusPower_Hourly
[ OK ] created: PerfectCampusPower_Weekly
[ OK ] hourly action verified (pythonw + sample + log)
```

注册的两条任务（动作都用 `pythonw.exe`，**不会每小时闪黑框**）：

| 任务名 | 触发 | 动作 | 日志 |
| --- | --- | --- | --- |
| `PerfectCampusPower_Hourly` | 每小时 | `electricity_monitor.py sample --log logs\monitor.log` | `logs\monitor.log` |
| `PerfectCampusPower_Weekly` | 周一 00:05 | `electricity_monitor.py report --log logs\report.log` | `logs\report.log` |

自测一条推送（可选，先配好推送渠道）：

```bat
run.bat test
```

管理任务：

```bat
:: 看状态 / 看详细配置
powershell -NoProfile -ExecutionPolicy Bypass -File install_task.ps1 -Status
schtasks /Query /TN "PerfectCampusPower_Hourly" /V /FO LIST

:: 立即跑一次（验证任务动作对不对）
schtasks /Run /TN "PerfectCampusPower_Hourly"

:: 删除任务（两条一起删）
powershell -NoProfile -ExecutionPolicy Bypass -File install_task.ps1 -Remove

:: 只看命令不安装
powershell -NoProfile -ExecutionPolicy Bypass -File install_task.ps1 -DryRun
```

**频率红线：每小时 1 次，别调更密。** 站点前面有 WAF，短时间请求过密会返回 HTTP 405 / `code_:9004`。

---

## 2. 常用命令

`run.bat <命令> [参数]` 是统一入口（`run.ps1` 等价，`python electricity_monitor.py <命令>` 也行）。

| 命令 | 作用 |
| --- | --- |
| `doctor` | 自检：Python/依赖/配置/台账/网络；**不登录、不发个人信息** |
| `projects` | 列出本校缴费项目，用来填 `payproid` |
| `rooms --building 13 --room 301` | 房间树下钻找 `roomverify`（支持 `--campus/--building/--room/--floor/--payproid`） |
| `query` | 查默认房间剩余量（表格） |
| `query --all` | 串行查 `rooms[]` 全部房间；`--json-out <file>` 落 JSON |
| `snapshot` | 批量查全部房间 → 班级站用的精简 `snapshot.json` |
| `dashboard` | `snapshot.json` → 单文件 HTML 看板 `dashboard.html` |
| `now` / `state` | 只查一次剩余量（不写库、不推送） |
| `sample` | 采一次入库 + 低电检查（计划任务用） |
| `report` | 推送上周汇总；`--dry` 只打印、`--force` 样本不足也推 |
| `status` | 台账概览：样本数、最新读数、上次推送、后端/配置/推送状态 |
| `test` | 读一次 + 推一条部署确认消息；`--dry` 只预览 |
| `watch`（`run` 是别名） | 常驻循环，不装计划任务时用 |
| `secure` | 收紧 `config.json` / state / 台账 / 日志 的权限 |
| `install` | 打印 Windows 计划任务命令（等价于 install_task.ps1 的手动版） |

通用参数：

- `--dry`：只读、只打印，不写库、不推送（`sample --dry` 仍会读一次云端，但不会写库/推送）；
- `--config <路径>`：指定别的 config.json；
- `--backend cloudpay|wanxiao`：临时切后端（默认 cloudpay 免登录）；
- `--fixture <json>`：用本地假数据代替真实网关（**离线演示/测试，绝不联网**）；
- `--log <文件>`：输出同时落日志（计划任务用）。

---

## 3. 班级看板（snapshot + dashboard）

```bat
run.bat snapshot
run.bat dashboard
```

- `snapshot` 串行查 `rooms[]` 全部房间（每请求间隔 1.1s，17 间约 20 秒），生成 `snapshot.json`；
- `dashboard` 读 `snapshot.json`，生成单文件 `dashboard.html`——**双击用浏览器打开**即可，
  下拉选房间看剩余电量、低电标红、可勾选「只看低电」；
- 房间名统一为规范名 `{楼号}号楼{座}{房间号}`，看板**按楼栋分组、按楼号/房间号自然排序**：
  `13号楼 → 16号楼 → 23号楼A座 → 23号楼B座`；
- 页面纯内联 CSS/JS：**零外部请求、零 CDN、零字体外链**，断网也能看。

`snapshot.json` 字段（给班级站用）：

```json
{
  "generated_at": "2026-11-05T22:41:51+08:00",
  "timezone": "Asia/Shanghai",
  "schoolcode": "769",
  "payproid": "2122",
  "payproname": "旗山用电支出",
  "low_threshold": 30.0,
  "rooms": [
    {
      "label": "13号楼301",
      "building": "13号楼",
      "room": "301",
      "roomverify": "1-13---301",
      "quantity": 78.97,
      "unit": "度",
      "low": false
    },
    {
      "label": "23号楼B座402",
      "building": "23号楼B座",
      "room": "402",
      "roomverify": "4-23B---402",
      "quantity": 148.83,
      "unit": "度",
      "low": false
    }
  ]
}
```

- `label` / `building` / `room` 均由 `roomverify` 按规范名派生，班级站可直接用；
- `low` = `quantity < low_threshold`（默认 30 度，可用 `snapshot --low-threshold 20` 或 config
  的 `snapshot_low_threshold` 改）；
- **不含任何姓名/学号/手机号**：`occupant`（同宿舍同学）只存在本机 `config.json`，
  任何命令输出、snapshot、dashboard 都不会带它；
- 个别房间查询失败不会中断整批：失败项会出现在 `errors` 数组（`label/roomverify/error`），
  `rooms` 里只放成功的数据。

---

## 4. 推送（可选，5 选 N）

不配推送时**只写日志、不报错**，采集/台账照常。配几个发几个；`push.channels` 留空 = 自动检测已填好的渠道。

| 渠道 | config 位置 | 怎么拿 |
| --- | --- | --- |
| PushPlus | `push.pushplus.token` | <https://www.pushplus.plus> 登录后复制 token（微信推送，最省事） |
| 企业微信群机器人 | `push.wecom.webhook` | 企业微信群 → 群设置 → 群机器人 → 添加 → 复制 Webhook（含 `key=`） |
| Server酱 | `push.serverchan.sendkey` | <https://sct.ftqq.com> 登录后复制 SendKey（微信推送） |
| 通用 webhook | `push.webhook.url` | 任意能收 JSON POST 的地址；`format` 可 `json`/`form`，`headers` 可自定义 |
| QQ邮箱 SMTP | `push.email.*` | QQ邮箱 → 设置 → 账户 → 开启 SMTP → 生成**授权码**（不是登录密码），QQ邮箱 App 会弹通知 |

示例（只配企业微信）：

```json
"push": {
  "channels": ["wecom"],
  "wecom": { "webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key" }
}
```

示例（QQ邮箱，收件人和发件人同一个 QQ 邮箱）：

```json
"push": {
  "channels": ["email"],
  "email": {
    "smtp_host": "smtp.qq.com", "smtp_port": 465, "ssl": true,
    "user": "你的QQ邮箱@qq.com",
    "password": "QQ邮箱授权码",
    "to": ["你的QQ邮箱@qq.com"],
    "from_name": "电费监控"
  }
}
```

配好后验证：`run.bat test`（会真发一条）。某个渠道失败只影响它自己，不会中断采集。

---

## 5. Windows 计划任务细节

`install_task.ps1` 参数：

| 参数 | 作用 |
| --- | --- |
| （无） | 安装两条任务（优先 `pythonw.exe`） |
| `-PythonExe <路径>` | 指定 python.exe（默认取 PATH 里第一个） |
| `-NoPythonw` | 用 `python.exe`（会有黑框，一般不用） |
| `-Status` | 查看任务当前状态 |
| `-Remove` | 删除两条任务 |
| `-DryRun` | 只打印将执行的 schtasks 命令，不安装 |

为什么用 `pythonw.exe`：它是 GUI 子系统，计划任务运行时**不会弹控制台窗口**；
`pythonw` 没有 stdout，所以必须用 `--log` 把输出落盘（`logs\monitor.log` / `logs\report.log`，
每行带时间戳）。

注意：

- 本机 `schtasks /Create` **免提权可用**；PowerShell 的 `Register-ScheduledTask` 可能被拒，
  所以脚本用 `schtasks.exe`。
- 任务用固定参数、绝对路径，不受"当前目录"影响。
- 想改触发时间：删除后重装，或 `schtasks /Change /TN "PerfectCampusPower_Hourly" /ST ...`
  不适用于 HOURLY，建议后面直接改脚本里的 `$HourlyArgs`。
- 电脑睡眠/关机时任务会错过，属正常；台账按实际采样点算差值，不会算错。

---

## 6. 免登录数据源与协议要点（2026-11-05 实测）

网关（云支付）：

```
POST https://cloudpaygateway.59wanmei.com:8087/paygateway/smallpaygateway/trade
Content-Type: application/json
Origin: https://cloudpaygateway.59wanmei.com:8087
Referer: https://cloudpaygateway.59wanmei.com:8087/pay/index.html

{"method":"<method>","bizcontent":"<JSON 字符串>",
 "timestamp":"YYYY-MM-DD HH:MM:SS","sourceId":2}
```

| 用途 | method | bizcontent（实测） |
| --- | --- | --- |
| 缴费项目 | `smallProgramPayPro` | `{"schoolcode":"769","idserial":"<学号>","channelno":"30"}` |
| 房间树 | `samllProgramGetRoom`（**拼写就是 samll**） | `{"schoolno":"769","optype":1-4,"payproid":"2122","areaid":"0","buildid":"0","unitid":"0","levelid":"0","businesstype":"2","idserial":"<学号>"}` |
| 剩余电量 | `samllProgramGetRoomState` | `{"payproid":"2122","schoolcode":"769","roomverify":"4-23B---402","businesstype":"2"}` |

查电量响应（businessData）：

```json
{"description":"剩余电量","quantity":"148.83","quantityunit":"度"}
```

要点：

- **免登录**：只需 schoolcode + 学号 + payproid + roomverify，无 token/密码/短信；
- 房间树 `optype=1 校区 / 2 楼栋 / 3 楼层 / 4 房间`；FJTCM 每栋楼只返回一个虚拟楼层 `id=-1`，
  `optype=4` 的 `id` 直接就是 roomverify；
- 批量查询串行执行、每请求间隔默认 1.1 秒（`request_interval` 可调，但**别小于 1 秒**）；
- 遇超时 / 网络错 / 5xx / 405 / 「频繁请求」「9004」会自动按 **3s → 6s → 12s** 退避重试最多 3 次；
  仍失败会提示「可能被 WAF 限流：等几分钟再试」，**不会死循环**；
- 老接口 `xqh5.17wanxiao.com/.../SWAEServlet` 对 769 返回 `code_:8099 调用接口失败,body格式错误`
  （学校水电不挂老引擎），所以本项目不走它。

---

## 7. 备用后端：完美校园账密登录 + CloudPayment（可选，默认关闭）

默认**不需要**这一节。只有以下情况才启用：云支付网关接口失效、或你想换用 CloudPayment 的
缴费项目视图。代价：需要完美校园 App 的**手机号 + 密码**，首次在新设备登录要收**一次**短信验证码。

启用方式（`config.json`）：

```json
"backend": "wanxiao",
"phone": "你的完美校园登录手机号",
"password": "你的完美校园登录密码",
```

或者只做兜底（cloudpay 失败时才试）：

```json
"wanxiao_fallback": true,
"phone": "...", "password": "..."
```

首次绑定受信设备（**只需一次**，之后永久免短信）：

```bat
run.bat login            :: 先试纯账密；若提示「新设备」→
run.bat sms-send         :: 发短信验证码
run.bat sms-code 123456  :: 提交验证码（把本机 deviceId 绑成受信设备）
run.bat login            :: 复查：应该直接成功且不再要验证码
run.bat wx-status        :: 看登录状态（token/deviceId 全部掩码）
```

安全须知：

- `wanxiao_state.json` 里的 `deviceId` **等同于密码**（绑定凭证），换机器要一起带走，
  不要外传、不要提交仓库（已 gitignore，`run.bat secure` 会收紧权限）；
- 完美校园「只允许一个设备登录」：脚本登录后手机 App 重新登录可能让旧 deviceId 失效；
- token 过期不用管，脚本会自动重新账密登录；`token_max_age`（默认 5400 秒）控制缓存时长；
- 该链路需要 `cryptography`（`pip install -r requirements.txt`）。

---

## 8. 自检 / 测试 / 离线演示

```bat
:: 环境+配置+网络自检（不登录、不发个人信息；网络只做 TCP 连通）
run.bat doctor
run.bat doctor --no-net

:: 统计/推送逻辑自检（vendor 自上游项目，离线）
python tests\selftest.py

:: 全链路离线测试（fixture 假网关，不联网；约 190 项检查）
python tests\smoke.py
```

两者最后都应打印 `全部通过`。

**离线演示**（不联网、不需要学号）——用仓库里的 17 间房 fixture 直接看效果：

```bat
run.bat snapshot --fixture tests\fixtures\class_rooms.fixture.json --out demo_snapshot.json
run.bat dashboard --snapshot demo_snapshot.json --out demo_dashboard.html
```

> `--fixture` 只是本地 JSON 假数据，绝不发网络请求；fixture 里的房间读数来自 2026-11-05
> 实测快照，**已剔除同学姓名**。

---

## 9. 风险与合规（务必读完）

1. **非官方接口**：靠逆向 App/H5 得到，学校或厂商随时可能改协议/关入口，届时需要重新适配。
   出错先看 `logs\monitor.log` 与 `run.bat doctor`。
2. **频率限制**：默认每小时 1 次；批量查询串行 + ≥1 秒间隔。**不要把轮询调成秒级**，
   WAF 会返回 HTTP 405 / `code_:9004`，频繁触发可能短暂封 IP。
3. **只读、不碰钱**：本项目只查询剩余量，不实现充值/支付，不接触支付密码。
4. **隐私**：
   - `config.json`（学号/房间）、`snapshot.json`（班级房间电量）、`wanxiao_state.json`
     （fallback 的 token/deviceId）都只放本机，**不要发到公网/群里**；
   - `occupant`（同宿舍同学姓名）仅本机 config 里可选保存，**所有输出/快照/看板都不包含**；
   - 日志/终端输出对密码、token、deviceId、手机号、webhook key、邮箱授权码全部掩码；
   - 班级看板/班级站对外展示前，确认只展示房间号与电量，不带姓名。
5. **账号**：fallback 用你自己的完美校园账号；deviceId 当密码保管；"只允许单设备登录"可能互踢。
6. **TLS**：免登录网关走正常证书校验；fallback 的 CloudPayment 沿用上游实现关闭了证书校验
   （与 App 行为一致），仅用于校内服务查询，不要在不可信网络下使用。
7. **合规**：只查本校、自己班的房间，不做批量探测/撞库；发现接口鉴权缺陷应报告学校网络中心，
   而不是拿去验证别人能不能查。

---

## 10. 许可与来源

- 主链路（`cloudpay.py`、`push.py`、`dashboard.py`、`util.py`、Windows 脚本、`doctor`、
  `snapshot`、README 等）为本项目新增代码，MIT。
- `wanxiao_login.py`、`electricity_monitor.py` 的统计/台账部分、`tests/selftest.py` 等
  vendor 自 **jialiangh/campus-electricity-monitor**（MIT © 2026 jialiangh），
  已做 Windows 化 / 双后端 / 掩码 / 隐私裁剪等修改。
- 完整来源与改动清单见同目录 **`NOTICE`**；上游 MIT 全文见 **`LICENSE`**。

```
MIT License · Copyright (c) 2026 jialiangh（上游部分）
本目录新增文件同样以 MIT 许可发布。
```
