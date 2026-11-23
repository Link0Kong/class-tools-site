# 班级工具站 · 网页端

> 一个班一个静态站：抽签、课表、通知、电费、投票……单文件零依赖，双击就能用。

[![version](https://img.shields.io/badge/version-2.0.0-4E9082)](CHANGELOG.md)
[![license](https://img.shields.io/badge/license-MIT-B98F63)](LICENSE)
[![platform](https://img.shields.io/badge/platform-Web-6E8CA8)](https://developer.mozilla.org/zh-CN/docs/Web)
[![CloudBase](https://img.shields.io/badge/CloudBase-PostgreSQL-4E9082)](https://cloud.tencent.com/product/tcb)

---

## 简介

班级工具站是给一个真实班级用的日常工具集合：一份 `tools/index.html`（原生 HTML/CSS/JS，无构建链、无静态资源目录、无第三方 CDN），打开即用。

- **单文件零依赖**：全部样式、脚本、模板内联在一个 HTML 里，双击本地文件即可运行。
- **多端数据契约**：网页端与安卓、小程序、鸿蒙、Windows 端共用同一套云端表结构与同步契约（用户数据按 section 合并，跨端互通）。
- **离线可用**：身份与数据先落本机缓存；网络不可用时照常打开，恢复后自动补发。

## 功能

| 模块 | 说明 |
| --- | --- |
| 工作台 | 顶部工具条（3~5 格）+「全部」页；工具顺序、卡片顺序可拖动自定义 |
| 抽签 | 按范围/个数/可重复/排除序号抽签，支持名单对应与结果重排 |
| 分组 | 用抽签序号或粘贴名单分组，可「打乱成员再分组」 |
| 课表 | 周次切换、周/日视图、今日与下一节、课程详情、导出图片 |
| 作业 | 发布、截止倒计时、完成勾选、附件、跨设备同步 |
| 通知 | 通知卡片、附件、长期安排、已处理状态、管理员编辑/隐藏 |
| 体测 | 按性别/年级算分与等级，历史记录随账号同步 |
| 名单 | 班委、团员、全班三份名单，去标识展示 |
| 点名 | 到课/请假记录与名单点名 |
| 电费 | 宿舍剩余电量、趋势、同类比较与低电提醒 |
| 水量 | 4/6 人间水表抄录与水费计算 |
| 投票 | 限时/长时投票，单选多选、匿名、可见范围、一人一票 |
| 演示 | PPT 上传、兼容版/PDF 下载、在线预览与视频单独下载 |
| 文件传输 | 手机与大屏之间互传文件、文字与遥控指令 |
| 校园地图 | 2.5D 校园地图，与课表教室联动导航 |
| 统计 | 访问次数、设备与版本分布（仅管理员） |
| 诊断 | 服务健康与设备诊断、异常上报（全员可见） |

导出图片统一走 `exportCard()`：图内含参数配置区、斜向水印、生成时间与唯一编号。

## 在线体验与下载

- 在线体验：<https://tool.furina.fun/>（2026-11-23 网站 ICP 备案通过，备案号 闽ICP备2026042939号-2；Caddy 自动 HTTPS，部署与运维见 [deploy/ECS_DEPLOY.md](deploy/ECS_DEPLOY.md)）
- 下载与版本说明：[Releases](https://github.com/Link0Kong/class-tools-site/releases) · [CHANGELOG.md](CHANGELOG.md)

## 本地打开 / 自部署

**只看界面（无班级数据）**：双击 `tools/index.html`。页面会停在身份页；没有可用的数据接口时，云端功能不可用，但界面与本地计算类工具可正常浏览。

**接上自己的云端数据**：

1. 准备一个 CloudBase（PostgreSQL + PostgREST）项目，建好站点用到的表与 RLS 策略（迁移脚本见 `deploy/cloudbase/`）。
2. 修改 `tools/index.html` 顶部附近的 `var CB="..."`（PostgREST 基址）与 `var CBK="..."`（可公开的 anon/publishable key）两个常量，换成你自己的项目。
3. 把页面放到任意静态托管（OSS、对象存储、Nginx 均可），或继续本地双击使用。
4. 班级名单与身份：登录用「学号 + 姓名」经云端核验，名单由数据库维护，不写进前端。

> `CB` / `CBK` 只是前端可见的公开标识，真正的权限由服务端 RLS 与身份 token 决定；不要把任何私钥、服务端密钥写进页面。

## 项目结构

```text
tools/         单文件网页应用（index.html）、课表快照（tt.json）、前端自检脚本（tests/）
deploy/        云端迁移 SQL、部署与运维脚本
legal/         隐私政策与用户协议（各端）
power/         宿舍电费采集工具（Python）
jwxt/          教务课表同步工具（Python）
ppt/           PPT 转换与演示工具链
vote/          投票功能契约与迁移
attachments/   通知附件服务契约
drop/          大屏互联（文件传输）服务
briefdesk/     班级通知整理与卡片生成
docs/          跨端设计与迁移说明
```

## 技术栈

- **前端**：原生 HTML/CSS/JS（ES5 语法为主），零构建链、零外部请求。
- **数据**：CloudBase PostgreSQL + PostgREST；身份 token + 行级安全（RLS）。
- **脚本**：Python 3（部署、迁移、采集、转换），Windows 与 Linux 均可运行。
- **托管**：任意静态托管即可；附件与大文件可另配对象存储。

## 相关仓库

| 端 | 仓库 |
| --- | --- |
| 网页端（本仓） | <https://github.com/Link0Kong/class-tools-site> |
| 安卓端 | <https://github.com/Link0Kong/class-tools-android> |
| 小程序端 | <https://github.com/Link0Kong/class-tools-mp> |
| 鸿蒙端 | <https://github.com/Link0Kong/class-tools-harmony> |
| Windows 端 | <https://github.com/Link0Kong/class-tools-windows> |

各端共享同一套云端表与同步契约；网页端的数据契约说明见 `tools/tests/` 下的 `_stage_sync_contract.md`、`_water_contract.md` 等文件。

## 文档

- 网页端功能与实现说明：[tools/README.md](tools/README.md)
- 隐私政策与用户协议（各端）：[legal/README.md](legal/README.md)
- 服务器部署与反向代理：[deploy/ECS_DEPLOY.md](deploy/ECS_DEPLOY.md)
- 版本变更记录：[CHANGELOG.md](CHANGELOG.md)
- 贡献指南：[CONTRIBUTING.md](CONTRIBUTING.md) · 安全策略：[SECURITY.md](SECURITY.md) · 行为准则：[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

## 隐私与数据

- **身份核验**：进入站点需输入「学号 + 姓名」，由云端名单核验后下发 token；名单与 token 由服务端维护，不写死在页面里。
- **行级安全**：所有班级数据（作业、通知、名单、体测、投票、统计等）都经 RLS 校验 token；前端隐藏不能代替权限。
- **不导出敏感个人信息**：导出图片与分享内容不包含手机号、学号、宿舍号；投票结果不返回投票人学号，匿名投票不返回投票人。
- **本机缓存**：身份与业务数据缓存在浏览器 `localStorage`，用于离线与加速；可随时清除，不会上传到第三方。
- **最小采集**：诊断页只采集设备类型、屏幕、网络等最小字段，异常上报做脱敏与限频。

## 免责声明

- 本项目是**班级自用的非官方工具**，与所在学校、学院及任何第三方平台均无隶属或合作关系，也不代表其立场。
- 站内数据由使用者自行维护；第三方服务（如教务系统、缴费平台、云服务商）的使用须遵守其服务条款。
- 使用者应自行确认所在场景下的合规要求（个人信息保护、数据留存、内容发布等），并自行承担相应责任。
- 软件按「现状」提供，不附带任何明示或暗示的担保。

## 许可证

本项目采用 [MIT License](LICENSE)。第三方依赖与其素材遵循各自的许可证（详见对应目录中的 LICENSE / NOTICE）。
