# 班级工具站 · 五端隐私政策 / 用户协议

> 版本 **V1.0** · 生效 **2026-11-17** · 运营者 **陈子麒（个人开发者）**
> 本目录是**独立静态法律文档站**：10 个自包含 HTML 页面 + 文档中心 + `manifest.json` + 生成/校验脚本。
> 页面零外部字体、零统计脚本、零广告、零 CDN；可直接双击打开，也可部署到 `https://tool.furina.fun/legal/`。

---

## 1. 文件与地址

| 端 | 隐私政策 | 用户协议 | 适用环境 | 当前版本 |
|---|---|---|---|---|
| 网页端 | `web/privacy.html` | `web/terms.html` | 浏览器（手机/平板/桌面） | 站点 2.0.0 |
| 安卓端 | `android/privacy.html` | `android/terms.html` | Android 原生 App | 1.0.0-beta3 / vc86 |
| 电脑端 | `windows/privacy.html` | `windows/terms.html` | Windows 10/11 x64 原生 | 0.1.0 |
| 鸿蒙端 | `harmony/privacy.html` | `harmony/terms.html` | HarmonyOS 手机/平板/2in1/手表 | 1.0.6 / M79 |
| 微信小程序端 | `mp/privacy.html` | `mp/terms.html` | 微信小程序 | 2.0.0 / v25 |

统一入口：`index.html`；机器可读清单：`manifest.json`。

正式地址（域名恢复后）：

```text
https://tool.furina.fun/legal/
https://tool.furina.fun/legal/web/privacy.html
https://tool.furina.fun/legal/android/terms.html
...
```

> **已部署（2026-11-17 22:27）**：ECS `https://tool.furina.fun/legal/`、OSS `https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/legal/index.html` 均为 HTTP 200；当前域名未恢复，页面内相对链接可直接在 IP 下使用。域名恢复后按 §3 复跑并切换正式域名。
> 小程序备案号：`闽ICP备2026042939号`。网站/APP 备案号以工信部系统公示为准，页脚已留说明，取得后替换。

---

## 2. 本地预览与校验

直接双击 `index.html` 即可（所有 CSS/JS 内联）。建议用本地静态服务器模拟正式路径：

```powershell
cd %USERPROFILE%\.openclaw\workspace\web\legal
python -m http.server 8787
# 浏览器打开 http://127.0.0.1:8787/
```

校验（标准库 + lxml；不依赖 npm）：

```powershell
cd %USERPROFILE%\.openclaw\workspace\web\legal\_src
python build.py            # 重新生成 10 页 + index + manifest
python validate.py         # HTML/锚点/相对链接/无外部自动加载/无真实学号手机号
python preview_check.py    # 需先启动 Edge headless CDP（见脚本头注释）
```

`preview_check.py` 已实测：11 页 × 7 个宽度（360/390/430/768/960/1280/1440）无横向溢出、无外部请求、无 JS 报错；打印隐藏导航；深色模式背景正确。

---

## 3. 部署（已执行一次；域名恢复后复跑）

### 3.0 当前已部署状态（2026-11-17 22:27）

```text
ECS 入口：      https://tool.furina.fun/legal/
OSS 入口：      https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/legal/index.html
ECS 目录：      /var/www/tool/legal（12 个公开文件）
manifest：      debugBaseUrl = https://tool.furina.fun/legal/
                baseUrl      = https://tool.furina.fun/legal/
```

复跑命令：

```powershell
cd %USERPROFILE%\.openclaw\workspace\web
python deploy\sync_legal.py            # OSS + ECS，自动跳过 README/_src
python deploy\sync_legal.py --oss-only # 只更新 OSS
python deploy\sync_legal.py --ecs-only # ECS 从 OSS 重新拉取（重试）
```

`deploy/sync_legal.py` 只发布 `index.html`、`manifest.json` 和 5 个端目录下的 `*.html`，共 12 个文件；`README.md`、`_src/` 属于内部维护资料，不会出现在公网。

### 3.1 OSS

只上传公开的 12 个文件到 Bucket `tool-furina-fun` 的 `legal/` 前缀（`deploy/sync_legal.py` 已自动过滤 `README.md`/`_src/`），保持目录结构。所有 HTML 使用 `Content-Type: text/html; charset=utf-8`，`Cache-Control: no-cache`（法律文本需要及时更新；也可 `max-age=300`）。

可复用 `deploy/sync_tools.py` 的凭据读取方式（`ALIYUN_AK_ID` / `ALIYUN_AK_SECRET` 或 `deploy/creds.env`，**不要打印/提交凭据**）：

```python
# 示例：在 web 目录运行；bucket 用与 deploy/sync_tools.py 相同的方式初始化
# （凭据从环境变量或 deploy/creds.env 读取，禁止写入/提交本文件）
from pathlib import Path
import oss2

bucket = oss2.Bucket(
    oss2.Auth(ak, sk),  # 由部署脚本/环境变量提供，不在文档中展开
    "https://oss-cn-hongkong.aliyuncs.com",
    "tool-furina-fun",
)
root = Path("legal")
for p in root.rglob("*"):
    if p.is_file():
        key = p.as_posix()  # legal/web/privacy.html
        ctype = "text/html; charset=utf-8" if p.suffix == ".html" else "application/json; charset=utf-8"
        bucket.put_object_from_file(
            key, str(p),
            headers={"Content-Type": ctype, "Cache-Control": "no-cache"},
        )
```

### 3.2 ECS

ECS 站点根是 `/var/www/tool`。把同样的 `legal/` 树放到 `/var/www/tool/legal/`，Caddy 的 `file_server` 会直接提供 `/legal/*`。可用阿里云云助手（`deploy/ecs_site.py` 的通道）从 OSS 逐文件 `curl` 到 `/var/www/tool/legal/`；注意先 `mkdir -p`，再校验 `index.html` / `manifest.json` 的 sha256。

### 3.3 缓存与回滚

- 建议 `Cache-Control: no-cache` 或 `max-age=300`；`manifest.json` 必须短缓存，便于端内检查版本。
- 回滚：保留上一版 `legal/` 目录（或 Git 历史），整目录替换即可；不要只回滚单个页面，避免隐私政策/用户协议版本不一致。
- 每次更新同时改：`_src/common.py` 的 `VERSION/EFFECTIVE/LAST_UPDATED`、`_src/*` 文案、重新 `build.py`，并更新 `manifest.json`（脚本自动生成）。

---

## 4. 各端如何“统一调取”

推荐所有端只认 `manifest.json` 的 `documents.<端>.privacy/terms`，不要在各端硬编码十份文案；域名变更时只改 `baseUrl`。

### 4.1 网页端

身份页在收集学号/姓名**之前**放勾选框 + 两个链接；页脚/设置也放入口：

```html
<label>
  <input type="checkbox" id="legalAgree">
  我已阅读并同意
  <a href="/legal/web/terms.html" target="_blank" rel="noopener">《用户协议》</a>
  和
  <a href="/legal/web/privacy.html" target="_blank" rel="noopener">《隐私政策》</a>
</label>
```

未勾选时禁止提交身份；协议更新后应重新取得同意（不要只靠“继续使用”）。

### 4.2 安卓端

```kotlin
val url = "https://tool.furina.fun/legal/android/privacy.html"
startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
```

或在 App 内 WebView 打开（不要注入 JS、不要拦截页面内的外链到站外）；身份页勾选后再允许提交。端内 `PrivacyTexts.kt` 的旧草稿应改为“打开在线正式文本”，或至少同步为同版本。

### 4.3 鸿蒙端

```ts
// 使用系统浏览器
import { common } from '@kit.AbilityKit';
const ctx = getContext(this) as common.UIAbilityContext;
ctx.startAbility({ action: 'ohos.want.action.viewData', uri: 'https://tool.furina.fun/legal/harmony/privacy.html' });
```

或用 `Web({ src: url, controller: ... })` 打开；需 `ohos.permission.INTERNET`。身份页/“我的”增加两个入口，并在首次收集前取得同意。

### 4.4 电脑端（Windows）

```csharp
await Windows.System.Launcher.LaunchUriAsync(
    new Uri("https://tool.furina.fun/legal/windows/privacy.html"));
```

首次登录前展示同意勾选；设置页保留两个入口。

### 4.5 微信小程序端

小程序不能直接打开任意网页；两种方式：

1. **`web-view`**：把 `https://tool.furina.fun` 加入微信后台「业务域名」，页面内用 `<web-view src="https://tool.furina.fun/legal/mp/privacy.html">`；需要企业/个人主体支持，且页面不能有诱导分享/支付。
2. **复制链接/客服消息**：`wx.setClipboardData` 复制正式地址，提示用户在浏览器打开；同时用 `wx.openPrivacyContract` 打开微信平台侧的《小程序隐私保护指引》。

微信后台的「用户隐私保护指引」必须与代码实际接口一致（相册/相机、选中的文件、保存到相册、剪贴板、订阅消息等）；代码侧接入 `wx.requirePrivacyAuthorize` / `wx.onNeedPrivacyAuthorization`。

---

## 5. 版本与更新规则

1. 任何实质性修改（处理目的、字段、第三方、跨境、保存期限、用户权利、免责/争议解决）都必须升版本号 + 改生效日期，并在班级群/端内提示。
2. 重大变更（敏感信息、跨境、第三方共享、权利限制）必须**重新取得单独同意**，不能只以“继续使用”视为同意。
3. 端内离线副本/缓存要与 `manifest.json` 的 `version` 对齐；发现版本不一致时，优先展示在线正式文本，离线时提示“以在线版本为准”。
4. 旧版本保留在 Git 历史/归档目录，便于审计；不要删除历史版本页面后只留新版本。

---

## 6. 发布前必须完成的配套项（截至 2026-11-17 源码核对）

> 这 10 份文本是“可发布的文本层”。但**文本不能替代端内同意流程与后端保留期清理**。以下项目前尚未全部落地，正式上架/域名恢复前请逐项完成；否则文本与实现不一致，仍可能被审核/监管认定为未有效告知或未行使删除权。

| # | 配套项 | 现状/风险 | 涉及端 | 发布前动作 |
|---|---|---|---|---|
| 1 | 身份页同意门禁 | 网页身份页目前未看到“已阅读并同意”勾选与两协议链接 | 网页 | 在收集学号/姓名前加勾选 + 链接；未勾选禁止提交 |
| 2 | 端内旧隐私文本 | 安卓 `PrivacyTexts.kt` 仍是 2026-11-08 草稿；鸿蒙/Windows 无正式入口 | 安卓/鸿蒙/Windows | 改为打开在线正式文本，或同步为同版本；保留“我的/设置”入口 |
| 3 | 敏感信息单独同意 | 体测健康数据、教务密码、OPPO/华为账号标识、特定身份尚无统一单独同意弹窗 | 全部端 | 首次使用对应功能前单独告知 + 勾选；拒绝仅影响该功能 |
| 4 | PPT 跨境单独同意 | PPT 上传至香港 OSS，但未见上传前单独同意/告知 | 网页/安卓/鸿蒙/小程序/Windows | 上传前弹窗告知香港存储、公共读、风险；不同意禁止上传 |
| 5 | 微信隐私指引/授权 | 小程序后台隐私指引与代码接口是否逐项一致、是否接 `requirePrivacyAuthorize` 需复核 | 小程序 | 按相册/相机/文件/保存相册/剪贴板/订阅消息逐项声明；真机回归 |
| 6 | 保留期清理 | visits 90 天、feedback 1 年、notice 6 个月、PPT 软删 90 天、投票软删 30 天等目前主要靠人工/未实现定时清理 | 云端 | 加定时清理任务或管理员月度清理；保留清理记录 |
| 7 | 物理删除/注销 | 端内“清除云端”是覆盖/置否/归档；物理删除靠邮件人工 | 全部端 | 建立邮箱工单/台账，15 个工作日内处理；保留操作记录 |
| 8 | HTTPS | OPPO 账号服务/文件传输调试入口仍有 HTTP IP；正式发布不能明文 | 安卓/网页/小程序/Windows | 域名恢复后全部切 HTTPS；关闭 HTTP 明文入口 |
| 9 | OSS 公共读 | PPT Bucket 公共读，链接持有者可访问 | 全部端 | 优先改私有 Bucket + 短签名 URL；短期至少在页内显著警示 |
| 10 | 通知第三方个人信息 | 历史通知可能含发送人姓名/手机号/OCR 名单；需持续脱敏 | 全部端 | 上传前正则脱敏（手机号/身份证/学号）；提供当事人删除通道；群公告告知 |
| 11 | 应用商店隐私表单 | Android Data Safety、华为 AppGallery 隐私声明、微信隐私指引需与文本一致 | 安卓/鸿蒙/小程序 | 按本套文本逐项填写；保留截图/回执 |
| 12 | 备案号 | 网站 ICP/APP 备案号尚未在页脚展示（小程序备案号已有） | 网页/安卓/鸿蒙/Windows | 取得后替换页脚“以工信部系统公示为准”文案 |
| 13 | 法律复核 | 本文本为工程侧起草，不是律师意见 | 全部 | 上架/公开发布前请律师按实际功能复核，尤其是跨境、敏感信息、未成年人、免责条款 |

---

## 7. 文本结构（每页都有）

隐私政策：定义与范围、处理者、收集清单、目的与法律依据、敏感信息、本机存储/Cookie、委托/共享/公开、数据出境、保存期限、安全、权利、未成年人、更新、投诉；附件 A 个人信息处理清单、B 权限、C 第三方 SDK/服务、D 申请模板、E 版本记录。

用户协议：主体与接受、服务性质、资格与身份、账号/会话/设备、使用规范、用户内容与班级数据、隐私、第三方、知识产权、变更/中断/终止、免责与责任限制、违约、更新、法律适用/争议解决、其他；附件 A 禁止内容、B 本端特别条款、C 版本记录。

五端差异主要在：

- **网页端**：浏览器 localStorage/IndexedDB、无后台推送、大屏/互联、PPT 香港 OSS。
- **安卓端**：通知/日历/安装未知应用/WorkManager、OPPO 推送/账号、本机 Keystore 教务密码、APK 侧载更新。
- **电脑端**：Windows 单机、DPAPI、`%LOCALAPPDATA%\ClassTools`、Office COM、剪贴板/系统通知。
- **鸿蒙端**：华为账号/Push、手表、Asset Store、日历提醒、当前无独立数据与隐私页。
- **微信小程序端**：openid/订阅消息、微信隐私接口、微信云开发、保存相册/剪贴板/`downloadFile`。

---

## 8. 生成器说明

`_src/` 是唯一文案源，`*.html` 是生成产物；不要直接改 HTML（下次 `build.py` 会覆盖）。

```text
_src/common.py      模板、CSS、页头/页脚/目录/表格
_src/platforms.py   五端名称、版本、功能、权限、第三方、特别条款
_src/privacy.py     隐私政策正文
_src/terms.py       用户协议正文
_src/build.py       生成 10 页 + index + manifest
_src/validate.py    静态校验
_src/preview_check.py  Edge CDP 页面检查（可选）
```

文案中的日期、版本、运营者、邮箱集中在 `common.py`；改一处即可全站更新（生成后检查 `manifest.json`）。

---

## 9. 免责声明

本套文本由工程侧根据 2026-11-17 的源码/契约起草，**不构成正式法律意见**。正式上架、公开推广、跨境功能上线前，请让律师结合主体信息、实际数据流、云服务合同、应用商店规则复核；并确保端内实现与文本一致。
