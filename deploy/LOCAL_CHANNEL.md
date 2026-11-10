# 本地临时通道（域名暂停期间在本机正常使用网站）

> 用途：`furina.fun` 的 DNS 全部暂停（备案期间）时，`https://tool.furina.fun` 公网不可解析，
> 但网站本体（OSS）与云端数据（CloudBase）都在。直接用 OSS 默认域名打开网页会被浏览器 CORS 拦截
> （页面 Origin 不在 CloudBase 网关白名单里 → 身份校验/数据接口失败，登录不了）。
> 本工具提供一个**只在本机**的临时入口，让网站完整可用（登录、作业、通知、课表、电费、PPT 演示……全部功能）。

## 启动（两种方式，等价）

**方式 A（推荐，双击）**：双击 `deploy/local_channel.cmd`（或桌面快捷方式「班级工具站_本地临时通道」）→
浏览器自动打开 `http://127.0.0.1:8787/`。

**方式 B（命令行）**：

```powershell
cd C:\Users\Ko_Li\.openclaw\workspace\web
python deploy\local_channel.py --open          # 或 --port 8899
```

- 打开后用**自己的学号 + 姓名**登录即可（与本机浏览器无关，身份照旧走云端校验）。
- 停止：在通道窗口按 `Ctrl+C` 或直接关闭该窗口。**关闭窗口后网页就不能再取数据了**（页面本身还能开）。
- 域名恢复解析后就不需要它了，直接访问 `https://tool.furina.fun/`。

## 原理（为什么不用改配置）

1. 由本脚本在内存里把 `tools/index.html` 的 CloudBase 基址
   `https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/` 替换成同源 `/__cb/`；
2. 浏览器所有班级数据请求走 `http://127.0.0.1:8787/__cb/...`（同源，**没有任何 CORS**）；
3. 本脚本在服务端把请求原样转发到 CloudBase，并带上 `Origin: https://tool.furina.fun`
   （网关白名单内的来源）→ 云端按现有 RLS 正常鉴权；
4. OSS 上的 PPT 图片/视频仍由浏览器直连（`<img>/<video>` 不需要 CORS）。

即：**不改线上页面、不改 CloudBase 网关配置、不需要恢复 DNS、不涉及证书**，只在本机多一个进程。

## 安全边界

- 默认**只监听 `127.0.0.1`**，只有本机能访问；不要随意 `--host 0.0.0.0`（那会暴露给同一局域网）。
- 不保存、不打印任何 token / 密钥；身份 token 仍是浏览器 `localStorage` 里的原有机制。
- 不改 `tools/index.html` 原文件（只在响应时内存替换）；不写云端任何配置。
- 页面仍是 `http://127.0.0.1`（浏览器把 localhost/127.0.0.1 视为安全上下文，全屏/剪贴板等能力正常）。

## 自检（改动本工具后跑）

```powershell
cd C:\Users\Ko_Li\.openclaw\workspace\web
python deploy\local_channel_selftest.py
```

用**测试身份**（学号 3260799999 / 姓名 测试账号）在 headless Edge 里走真实登录：身份页 → 输入 → 进入 →
通过通道拉取云端数据 → 「演示」工具加载 → 断言 0 console/network 错误；输出 `RESULT: PASS` 即正常。
截图在 `deploy/_shots_local_channel/`（过程文件，可删）。

## 常见问题

| 现象 | 处理 |
|---|---|
| 端口被占用 | `python deploy\local_channel.py --port 8899 --open` |
| 页面能开但数据一直转圈 | 看通道窗口是否有「代理失败」日志；确认本机能访问 CloudBase 网关 |
| 登录提示身份不符 | 学号/姓名按班级名单原样填（与域名无关） |
| 想换回真实域名 | 关掉通道，DNS 恢复后直接访问 `https://tool.furina.fun/` |
