# 教务课表同步工具链（jwxt/）

把学校**新教务系统**的个人课表抓下来，写成班级工具站同源可读的 `../tools/tt.json`；
也可以一键生成 `https://tool.furina.fun/#tt=...` 发布链接，或用浏览器书签手动同步。

> **本目录只是工具链，不参与网站构建**。网站本体仍是单文件 `tools/index.html`，零依赖。
> 红线：凭据文件、cookie 缓存、账号密码一律不外传、不进 Git、不上传任何网盘。

---

## 0. 链路图（2026-11-03 起，学校已切统一身份认证）

```
统一身份认证 authserver (https://authserver.fjtcm.edu.cn)
   │  ① 纯 requests：GET 登录页取 execution/pwdEncryptSalt
   │     POST 表单（密码 AES-CBC-Pkcs7 加密；无验证码时）
   ▼
门户 e.fjtcm.edu.cn（拿到 WISCPSID 等门户 cookie）
   │  ② headless Edge（--remote-debugging-port + 临时 profile）
   │     注入门户 cookie → 打开门户 → 在 SPA iframe 里点「新教务系统」
   ▼
新教务系统 http://210.34.74.77/jsxsd/（SSO 下发 bzb_jsxsd 等 cookie，缓存 6 小时）
   │  ③ requests 用 cookie：
   │     GET /jsxsd/framework/xsMainV.jsp        → 验证登录
   │     GET /jsxsd/xskb/xskb_list.do?viweType=0 → table.qz-weeklyTable 周表
   ▼
解析 → ../tools/tt.json（站点 fetch 读取）/ #tt= 发布链接 / 可选 --deploy 上传
```

要点：
- **密码是「学校统一身份认证密码」**，不是旧教务系统直登密码（旧 `LoginToXk` 直登已不可用，仅留 `--direct` 调试）。
- cookie 缓存文件 `jwxsd_cookies.json`（含时间戳、6 小时过期）只在本机，已 gitignore；过期或失效会自动重新 SSO。
- **同一账号并发登录会互踢**（教务系统提示「您的账号在其它地方登录」）：
  计划任务、手动同步、`--check` 不要同时跑；被踢后重跑一次即可。
- 统一认证若出现**验证码**（`checkNeedCaptcha.htl` 返回 `isNeed:true`），自动模式会明确报错，
  此时用 `--manual` 人工登录（见 §5）。

---

## 1. 文件清单

| 文件 | 作用 |
|------|------|
| `jwxt.py` | 核心模块：统一认证 AES 登录、门户→教务 SSO（headless Edge CDP）、cookie 缓存、课表抓取、qz-weeklyTable/kbcontent 解析、DPAPI 凭据、发布链接、人工辅助模式 |
| `sync.py` | 命令行入口：`--save-creds` / `--check` / 日常同步 / `--publish-link` / `--copy` / `--deploy` / `--manual` / `--refresh-sso` |
| `bookmarklet.html` | 本地打开的说明页，内含 `javascript:` 书签（新旧两种课表表格都支持，纯前端） |
| `install_task.ps1` | 注册/卸载 Windows 计划任务（`pythonw.exe`，无控制台窗口，免提权） |
| `tests/test_parse.py` | 解析器单元测试 + 「有课表课程」列表交叉校验（不联网）：`python tests/test_parse.py` |
| `tests/fixtures/qz_weekly_real.html` | **真实新版课表页裁剪**（去 tooltip，保留 qz-weeklyTable 结构） |
| `tests/fixtures/list_view_rows.json` | 真实「有课表课程」列表（viweType=1，显式「周X第a-b节」），用于交叉校验 day 映射 |
| `tests/fixtures/fixture_*.html` | 旧版表格样本（单双周 / 同格多课 / 教室含括号 / rowspan / 朴素表格） |
| `requirements.txt` | 依赖：`requests` + `pycryptodome`（或 cryptography） |
| `creds.dpapi` | ⚠️ 运行时生成：DPAPI 加密凭据（**已 gitignore，禁止上传**） |
| `jwxsd_cookies.json` | ⚠️ 运行时生成：教务系统 cookie 缓存（**已 gitignore，禁止上传**） |
| `_last_timetable.html` | 运行时生成：最近一次抓到的课表 HTML（**已 gitignore**，排查解析问题时给维护者看） |
| `logs/sync-YYYYMMDD.log` | 运行时生成：每日日志（**已 gitignore**） |

环境：Windows 10/11 + Python 3.8+ + Edge/Chrome（自动发现）。

```powershell
cd C:\Users\Ko_Li\.openclaw\workspace\web\jwxt
pip install -r requirements.txt
```

---

## 2. 第一次使用：保存统一认证凭据

```powershell
cd C:\Users\Ko_Li\.openclaw\workspace\web\jwxt
python sync.py --save-creds --account 3260707024
```

- 会提示两次隐藏输入（getpass）：**统一认证密码** + 确认；密码不显示、不落日志、不写明文。
- 用 Windows **DPAPI**（`CryptProtectData`）加密写入 `creds.dpapi`：只有当前 Windows 用户能解开，
  换用户/换机器失效，重新 `--save-creds` 即可。
- 预期输出：

```
提示：这里要输入的是**学校统一身份认证（authserver）密码**，不是旧教务系统直登密码。
统一认证密码（输入不回显）：
再输一次确认：
OK 凭据已加密保存：C:\...\web\jwxt\creds.dpapi
   （Windows DPAPI，仅当前 Windows 用户可解密；不要上传网盘/不要进 Git）
   下一步：python sync.py --check
```

> `--save-creds` 故意**不**顺手试登录，避免密码手滑造成无谓的失败计数；保存后用 `--check` 验证。

---

## 3. 验证链路

```powershell
python sync.py --check               # 用 cookie 缓存（有就快路径）
python sync.py --check --refresh-sso # 强制完整走：统一认证 → 门户 → 教务系统
```

成功输出：

```
OK 统一认证 SSO 登录成功：account=32******24，教务系统可访问（xsMainV.jsp 正常）
```

失败退出码 `2`，并打印原因（密码错误 / 需要验证码 / 门户改版 / 教务系统维护等）。

---

## 4. 日常同步

```powershell
python sync.py                                        # SSO -> 抓课表 -> 写 ../tools/tt.json
python sync.py --publish-link                         # 额外打印 #tt= 发布链接
python sync.py --publish-link --copy                  # 并复制到剪贴板
python sync.py --term 2026-2027-1 --term-start 2026-08-31
python sync.py --deploy                               # 写完调用 deploy/sync_tools.py 上传 tt.json
python sync.py --refresh-sso                          # 忽略 cookie 缓存，强制重新 SSO
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--term` | `2026-2027-1` | 学期，`YYYY-YYYY-1|2` |
| `--term-start` | 见下 | 第 1 周周一的日期 `YYYY-MM-DD`（当前学期应传 `2026-08-31`，即教务系统第 1 周周一；11/2–11/8 = 第 10 周） |
| `--out` | `../tools/tt.json` | 输出路径 |
| `--publish-link` | 关 | 打印 `https://tool.furina.fun/#tt=<base64url({c,t})>`（不带 meta） |
| `--copy` | 关 | 复制发布链接到剪贴板（Windows ctypes，无外部进程） |
| `--deploy` | 关 | `subprocess` 调 `python ../deploy/sync_tools.py tt.json`（部署凭据由该脚本自己读） |
| `--direct` | 关 | 旧版 jsxsd 直登（仅调试，学校已切统一认证，通常不可用） |
| `--refresh-sso` | 关 | 忽略 cookie 缓存强制重新 SSO |
| `--day-order` | `column` | 周表星期映射：`column`=按数据列位置（col1=周一，**正确**）；`header`=按 th 文本（仅调试） |
| `--quiet` / `--verbose` | 关 | 只写日志 / 输出 DEBUG |

**学期起始日 `t` 取值顺序**：`--term-start` → 已存在 `tt.json` 的 `t` → 按学期推断
（秋季=9 月 1 日起第一个周一；春季=次年 2 月 17 日起第一个周一），推断时会打印提示。
推断值仅图省事，**每学期开学建议手动传一次 `--term-start`**。

**输出结构**（站点同源 `fetch('tt.json')` 直接读）：

```json
{
  "c": [
    {"name":"高等数学","teacher":"龚志伟","room":"自强楼(教室01104)",
     "day":0,"start":1,"end":3,"weeks":"2-3","parity":"all"}
  ],
  "t": "2026-08-31",
  "meta": {"fetchedAt": 1793718652812, "term": "2026-2027-1", "source": "jwxt", "count": 32}
}
```

- `day`：0=周一 … 6=周日；`start/end`：第 1–12 节（超出截断）。
- `weeks`：**英文逗号/短横线**，例如 `2-4,6,9-18`；单双周一律展开成具体周次。
- `parity`：固定 `"all"`。

**发布链接**：`https://tool.furina.fun/#tt=<base64url(UTF-8 JSON {c,t})>`，
即 `+`→`-`、`/`→`_`、去掉 `=`，等价 JS `btoa(unescape(encodeURIComponent(json)))`。链接里**不含 meta**。

> 部署注意：`deploy/sync_tools.py` 已支持「存在 `tools/tt.json` 就一起上传」（Cache-Control: no-cache）。
> 手动部署：`cd ../deploy; python sync_tools.py tt.json`。

---

## 5. 人工辅助模式（`--manual`）

适合：统一认证出现验证码 / SPA 改动 / 自动 SSO 失败时。

```powershell
python sync.py --manual                 # 弹出可见 Edge，自己登录，之后自动接管
python sync.py --manual --check         # 只验证手动登录是否成功
python sync.py --manual --publish-link  # 抓完顺便出发布链接
```

流程：可见 Edge 打开统一认证登录页 → **你自己登录**（脚本不读密码）→ 检测到门户后自动点「新教务系统」→
取 cookie 缓存 → 关闭浏览器/清理临时 profile → 之后同自动模式。

---

## 6. 定时自动同步（计划任务）

先确认 `--save-creds` + `--check` 通过，然后（**无需管理员权限**）：

```powershell
cd C:\Users\Ko_Li\.openclaw\workspace\web\jwxt
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_task.ps1
```

默认注册：任务名 `JwxtTimetableSync`，**每天 07:00**；动作是
`pythonw.exe sync.py --out "..\tools\tt.json" --deploy`（`pythonw.exe` = 无控制台，不会闪黑框），
工作目录 `web\jwxt`，日志由 `sync.py` 自己写 `logs\sync-YYYYMMDD.log`。

注意点：
- **同账号不要并发**：计划任务 07:00 跑的时候别手动再跑，否则会互踢；`MultipleInstancesPolicy=IgnoreNew` 已避免任务自身重叠。
- 任务用 `InteractiveToken`：**只有该 Windows 用户登录时才会跑**；错过时间会补跑一次（`StartWhenAvailable`）。
- SSO 第二步需要本机 Edge（headless 启动，不弹窗）；如果 Edge 被卸载/策略禁用，任务会 exit 3，请改用 `--manual` 或重装 Edge。
- 任务动作里**不带任何密码**：凭据只从 `creds.dpapi` 解。

常用变体：

```powershell
.\install_task.ps1 -OnLogon                 # 额外加「登录后 3 分钟」触发器
.\install_task.ps1 -At 08:30 -Term 2026-2027-1 -TermStart 2026-08-31
.\install_task.ps1 -PublishLink             # 动作里加 --publish-link
.\install_task.ps1 -NoDeploy                # 只写本地 tt.json，不上传
.\install_task.ps1 -Show                    # 查看任务详情
.\install_task.ps1 -Run                     # 立刻跑一次（看 logs\sync-*.log）
.\install_task.ps1 -Remove                  # 卸载
```

---

## 7. 书签方式（浏览器里手动同步，备用）

打开 `bookmarklet.html`（双击即可，零依赖零外部请求）：

1. 把「📅 同步课表到工具站」拖到书签栏；
2. 在教务系统打开「个人课表信息」页（新版 qz-weeklyTable 或旧版 #kbtable 都行）；
3. 点书签 → 填「学期第 1 周周一日期」→ 自动跳到 `https://tool.furina.fun/#tt=...`。

页面里有「本地自检解析器」按钮（内置新旧两种示例表格）。新版表格按**数据列位置**映射星期
（col1=周一…col7=周日，已用「有课表课程」列表交叉核对；页面 th 文本顺序是服务器模板 bug）。

---

## 8. 退出码与排查

| 退出码 | 含义 |
|--------|------|
| `0` | 成功 |
| `2` | 登录失败（统一认证密码错 / 需要验证码 / 账号锁定 / 门户或 SSO 失败 / 网络不通） |
| `3` | 抓取、解析或上传失败（登录成功但拿不到/解析不了课表、deploy 失败） |

日志：`logs\sync-YYYYMMDD.log`（控制台同时输出；计划任务下只有文件日志）。日志里账号只显示
`32******24` 掩码，**不会出现密码**，也不会出现 cookie 值（只出现 cookie 名）。

| 现象 / 日志 | 处理 |
|-------------|------|
| `没有可用密码：请先运行 python sync.py --save-creds` | 先 `--save-creds` |
| `统一认证登录失败（账号或密码错误…）` | 密码错/账号错：重新 `--save-creds`（注意是**统一认证密码**） |
| `统一认证要求输入验证码` | 用 `python sync.py --manual` 手动登录 |
| `门户里没找到「新教务系统」入口` | 门户改版/登录态无效：先 `--check --refresh-sso`；仍失败用 `--manual`，并把日志发维护者 |
| `教务系统 cookie 缓存已失效，重新走统一认证` | 正常：自动重登；若反复出现，检查账号是否被其它地方登录（互踢） |
| `您的账号在其它地方登录` | 同账号并发：停掉其它同步/手动任务，重跑一次 |
| `课表页返回登录页：登录状态已失效` | cookie 失效：`--refresh-sso` 重跑 |
| `未找到课表页` / `找到 qz-weeklyTable 但未解析出课程` | 教务系统改版：把 `_last_timetable.html` 发给维护者，补 fixture/改解析器 |
| `部署脚本执行成功，但输出里没有 tt.json 的上传记录` | `deploy/sync_tools.py` 未支持 tt.json（现已支持，若再出现让部署脚本负责人看） |
| 计划任务 `Last Result: 2` | 登录失败（多半是没保存凭据/密码改过），跑一次 `python sync.py --check` 看文案 |

> `_last_timetable.html` 是调试用（课表原样 HTML，无密码），已 gitignore；排查完可删除。

---

## 9. 安全与红线

- `creds.dpapi`、`jwxsd_cookies.json`、`logs/`、`_last_timetable.html`、`__pycache__/` 均已写进 `.gitignore`。
- **禁止**把 `creds.dpapi`、`jwxsd_cookies.json`、日志、含学号截图发群里/上传网盘/提交 Git。
- 本工具不会把课表/账号上传到除 `tool.furina.fun`（发布链接/tt.json）以外的任何地方；
  `--deploy` 只调用项目自己的 `deploy/sync_tools.py`（阿里云密钥由它自己读，本工具不接触）。
- 发布链接/tt.json 里含课表内容（课程/教室/教师），发班级群前请自行确认可公开。

---

## 10. 解析规则（改解析器必读）

### 新版 `table.qz-weeklyTable`（现行）

1. **找表**：`<table class="qz-weeklyTable">`（正则，不依赖 DOM）。
2. **列→星期**：按 rowspan/colspan 还原二维网格后，**body 第 1~7 个数据列 = day0..day6（周一..周日）**。
   ⚠️ 页面 thead 的 th 文本顺序是 `周次,星期日,星期一,…,星期六`（服务器模板 bug），
   但数据列实际周一起；已用「有课表课程」列表（viweType=1）逐条交叉核对（见测试）。
   th 文本只写日志/自检；`--day-order header` 仅作调试用。
3. **节次/周次**：全部从 `li.courselists-item` 的 `.qz-hasCourse-abbrinfo`
   （`老师:…;时间:2-3周[1-3节];地点:…`）取；支持 `[1-3节]`、`[8-9节]`、`[2-5节]`、`[1、2节]` 等写法。
   行首节次标签（`一（1-2节）`）只在 abbrinfo 缺节次时兜底。
4. **同格多课**：一个 td 里多个 `li.courselists-item` 分别解析；`.qz-tooltip` 是重复信息，忽略。
5. **合并**：同 `name+teacher+room+day+start+end` 的多个周段合并为一条，`weeks` 求并集后压缩
   （`2,3`→`2-3`；`2-4,6,9-18`），47 条 li → 约 32 条。
6. `parity` 固定 `"all"`；跨第 12 节的截断到 12。

### 旧版 `#kbtable` / `div.kbcontent`（兜底，保留兼容）

按表头/列位置映射星期，单元格内 `font[title]` 取教师/周次/教室，`<br>`/`<hr>` 分块 —— 见 `_parse_table_fragment()`。

### 自检

```powershell
python tests/test_parse.py      # 期望 13/13 passed
```

测试覆盖：真实 qz 页 fixture（32 条 / day 分布 / 高数周一 1-3 节 / rowspan / 多课同格）、
「有课表课程」列表交叉校验（day/节次/周次集合必须完全一致）、旧版 3 个 fixture、纯函数、发布链接往返。

---

## 11. 当前状态

- ✅ 统一认证 SSO 全链路真机跑通（`--check --refresh-sso` 通过）
- ✅ 真实课表页抓取 + qz-weeklyTable 解析（32 条，已与 viweType=1 列表交叉校验）
- ✅ `tools/tt.json` 真实数据已生成（bootstrap 备份 `tools/tt.json.bak-20261103`）
- ⚠️ 统一认证若弹出验证码需 `--manual`；学期/起始日变化需更新 `--term/--term-start`
- ⚠️ 同账号并发会互踢；计划任务与手动同步不要同时跑

---

## 12. 课表快照云端发布（2026-11-07，DNS 暂停改造）

- `sync.py` 写盘成功后自动调用 `tt_cloud.publish(out)`，把 `tools/tt.json` 原对象 upsert 到 CloudBase
  `public.site_assets` 行 `id='tt'`（供小程序/网页在 `tool.furina.fun` 域名暂停后读取）。
- **失败只记 `jwxt.log` WARNING，不影响 `sync.py` 退出码与 `--deploy` 的 OSS 上传**；管理员 token 从
  `C:\briefdesk\secrets\class-token.json` 读取（过期自动 `rpc/class_verify` 刷新，不打印）。
- 手动回填/验证：`python tt_cloud.py --tt ..\tools\tt.json`（`--dry-run` 只打印 meta 不联网）。
- 云端读取方：小程序 `utils/cloud.js → ttFetch`（`s`优先 `site_assets`，失败回退旧 `ttUrl`）；网页 `ttSyncPull` 同源优先、失败回退 `site_assets`。
  契约见 `web/tools/tests/dns_pause_tt_health_spec.md`；`sync.py --help` 的 `--deploy` 说明不变。
