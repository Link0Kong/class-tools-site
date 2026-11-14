# 教务卡片页 v1（安卓）实现规格 · 2026-11-14

> 用户需求：「把教务系统点开后也展示和班级工具站的卡片一样展开，只调用官方各个工具的网页接口」。
> 已确认口径：**只做安卓 App**；卡片直接展示官方接口数据（用户明确接受「需授权真实账号做接口勘察」）。

## 0. 授权与安全口径（重要）

- 2026-11-14 用户点选「卡片直接展示官方接口数据（脆弱，需授权）」= **授权本次一次性接口勘察**。
- 勘察已完成（Lead，2026-11-14 13:0x）：复用本机 DPAPI 凭据 + 既有 `jwxt.sso_login_http` 生产链路登录本人账号，
  **仅记录 URL/参数/JSON 字段名/表头**；原始页面只落盘 `%TEMP%\jw_probe\`（未入仓、未进对话正文）。
  勘察脚本 `jwxt/_dev_probe_pages*.py` 已被 `jwxt/.gitignore` 的 `_dev_*` 忽略。
- App 实现红线：**不在任何地方保存/上传/打印教务密码或 cookie 明文**；卡片数据只在内存展示；
  App 不代用户做写操作（选课/退课/评教等只在官方页面内由用户操作）。

## 1. 登录态（复用现有实现）

- 现有 `JwEntryScreen` 的自动登录流程保持：WebView 打开 `http://210.34.74.77/sso.jsp` → authserver 登录页注入
  `#username`/`#password` → 点 `#login_submit` → 回到 `210.34.74.77` 视为成功（验证码/失败回退人工，沿用 v4.46.1）。
- 登录成功后：`CookieManager.getInstance().getCookie("http://210.34.74.77")` 取会话 cookie，交给数据层做官方 JSON 请求。
- 若请求返回 HTML/登录页/非 JSON → 视为会话失效：重试自动登录 1 次；仍失败显示「登录失效，请重试」+ 手动入口。

## 2. 官方数据接口（2026-11-14 实测，本人账号）

统一：GET，`pageNum`/`pageSize` 分页（layui qzTable 口径）；响应 JSON：
`{msg, code, data:[...], count}`（`code` 可能是 0 或 "0"；行字段见下）。

| 卡片 | 接口 | 参数（默认） | 行字段（官方） |
|---|---|---|---|
| 成绩 | `/jsxsd/kscj/cjcx_list` | `pageNum=1&pageSize=5&kksj=&kcxz=&kcsx=&kcmc=&xsfs=all&sfxsbcxq=1` | `xnxqid`(开课学期) `kch`(课程编号) `kc_mc`(课程名称) `ksdw`(开课单位) `zcjstr`(成绩) `cjbs` `xf`(学分) `zxs`(总学时) `jd`(绩点) `bcxq`(补重学期) `ksfs` `ksxz` `kcsx` `kcxzmc` `txklb` |
| 考试 | `/jsxsd/xsks/xsksap_list` | `pageNum=1&pageSize=5&xnxqid=&xqlb=` | `xqmc`(校区) `ksxq`(考试校区) `kssj`(考试时间) `js_mc`(教室) `kch` `kskcmc`(课程名称) `jsxm`(授课教师) `zwh`(座位号) `zkzh`(准考证号) `ksccmc`(考试场次) `bzywmc`(备注) |
| 选课 | `/jsxsd/xsxk/xklc_list_data` | `pageNum=1&pageSize=10` | `xqmc`(学年学期) `xklc_mc`(选课轮次) `xksj`(选课时间) |
| 公告 | `/jsxsd/ggly/ysgg_query?type=list` | `pageNum=1&pageSize=5` | `title`(标题) `gglbname`(公告类别) `cjr`(创建人) |

请求头（必须，实测有效）：`Cookie: <WebView 同域 cookie>`、`User-Agent: <WebView settings.userAgentString>`、
`Referer: ` 对应官方页面、`X-Requested-With: XMLHttpRequest`、`Accept: application/json, text/javascript, */*`。
（`Referer`：成绩 `http://210.34.74.77/jsxsd/kscj/cjcx_frm`；考试 `…/jsxsd/xsks/xsksap_query`；
选课 `…/jsxsd/xsxk/xklc_list`；公告 `…/jsxsd/ggly/ysgg_query`。）

**当前实测态（如实）**：本账号 2026 级大一第一学期（数据为空，count 全 0）：成绩/考试/选课/公告均 `data:[]`，
说明接口可用但暂无数据。**流行（有数据）渲染未用真实数据验证过**——按上述字段名 + 合成夹具实现，
真机/有数据后如字段不符，卡片显示空态或失败态（不崩溃），并在文档记录。

## 3. 官方工具入口（实测自官方「快捷菜单」`kjcdShow`，直接打开官方页面）

| 名称 | 官方路径 |
|---|---|
| 学期理论课表 | `/jsxsd/xskb/xskb_list.do` |
| 课程成绩查询 | `/jsxsd/kscj/cjcx_frm` |
| 学生选课中心 | `/jsxsd/xsxk/xklc_list` |
| 考试安排查询 | `/jsxsd/xsks/xsksap_query` |
| 培养方案明细 | `/jsxsd/pyfa/topyfamx` |
| 已收公告 | `/jsxsd/ggly/ysgg_query` |
| 缓考申请 | `/jsxsd/kscj/hksq_query` |
| 社会考试报名 | `/jsxsd/xsdjks/xsdjks_list` |

入口卡点击 = 在 App 内置 WebView（沿用自动登录后的同一 WebView）打开对应官方页面；返回回到卡片页。
写操作（选课/报名/缓考/评教等）**只在官方页面内**由用户完成，App 不调用任何写接口。

## 4. UI（App 内「教务」工具页 = 卡片页）

```
顶栏：‹ 教务   [刷新]  [清除登录]
状态条：已自动登录 · 数据更新 HH:mm | 未登录/登录失效/加载失败（可点重试）
「数据」2 列卡片：
  成绩卡  已出成绩 N 门；最近 3 条：课程名 · 成绩（学期/绩点小字）→ 点开官方成绩页
  考试卡  下一场：时间 · 课程 · 教室 · 座位（或「暂无考试安排」）→ 点开官方考试页
  选课卡  当前轮次：学年学期 · 轮次 · 选课时间（或「暂无可选轮次」）→ 点开官方选课页
  公告卡  最近 2–3 条标题（类别小字）→ 点开官方公告页
「官方工具」2 列入口卡：上表 8 项（短名 + 官方页面）
底部：打开完整教务官网
```
- 卡片视觉沿用 App 现有卡片 token（CtShapeTokens/Expressive），圆角、两列、点按 ≥48dp；加载态用骨架/「—」；
  每张数据卡独立失败态（显示「获取失败 · 重试」+ 打开官网），不互相影响。
- 点数据卡 = 打开对应官方页面（成绩→`cjcx_frm`、考试→`xsksap_query`、选课→`xklc_list`、公告→`ysgg_query`）。
- 返回键：WebView 模式 → 回卡片页；卡片页 → 退出工具页。
- 「刷新」重新拉 4 个接口；「清除登录」= 清密码（JwCredentialStore）+ Cookie + WebStorage + 缓存，回一次性密码输入。

## 5. 实现拆分（文件所有权）

**新增（本任务独占，不与并行会话冲突）**
- `data/jw/JwApiModels.kt`：`JwApiEnvelope`（msg/code/data/count 宽松解析）+ 4 类行模型（字段名见 §2）。
- `data/jw/JwApiClient.kt`：URL/参数构造 + Cookie/UA/Referer 头 + HttpURLConnection/OkHttp 请求 + 超时 + JSON 解析；
  纯逻辑（URL 构造、JSON→模型、失败态判定）必须可 JVM 单测。
- `data/jw/JwCardsRepository.kt`：并行拉 4 接口（coroutine），单卡失败隔离，会话失效识别；状态流（Loading/Ready/Error）。
- `ui/screens/jw/JwCardModels.kt` / `JwCardsSection.kt`（Compose 卡片组件）。
- `app/src/test/.../features/jw/JwApiClientTest.kt`、`JwCardsRepositoryTest.kt`（合成 JSON 夹具，**不得使用真实个人数据**）。
**改造（属于 our jw 既有文件）**
- `ui/screens/jw/JwEntryScreen.kt`：改为「卡片页 + 全屏 WebView 切换」；保留 v4.46.1 自动登录/验证码回退/清除登录。
**共享文件（等并行会话静默后精确补 hunk）**
- `build.gradle.kts`：versionName 4.48.0 / versionCode 66（若并行会话已占用则顺延并报告）。
- `ui/screens/guide/GuideContent.kt` + `UserGuideContentTest.kt`：jx 卡文案改为「卡片页：成绩/考试/选课/公告 + 官方工具入口」。
- `data/tool/ToolCatalog.kt`：subtitle 改「卡片速览 · 自动登录」（features 同步）。
- `docs/CHANGELOG.md`：v4.48.0 条目（含实测口径与已知限制）。

## 6. 协调与验收

- 仓库有并行会话（2026-11-14 13:04 刚提交 v4.47.1、13:09 又有改动）→ 新增文件先写；共享文件先落 pending patch、
  监控静默 ≥3 分钟且 `compileDebugKotlin` 通过后再精确 edit（沿用 2026-11-13 口径）。
- 验收：`:app:testDebugUnitTest --no-daemon` 全绿（新增用例覆盖 JSON 解析/URL/头/失败态）；
  `:app:assembleRelease --no-build-cache --no-daemon` 产出 `artifacts/classtools-4.48.0-release-signed.apk`（记录大小/SHA-256）。
- **禁止用真实教务账号跑自动化测试**；真机/模拟器无法验证真实数据时如实说明。
- 回滚：删除新增 jw 卡片文件 + 恢复 JwEntryScreen v4.46.1 版本 + 版本号回退；APK 回退上一版 4.47.1 产物。
