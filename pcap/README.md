# pcap —— 本机抓包工具（微信小程序接口分析）

一个只在本机跑的 HTTPS 中间人代理：手机/电脑把 HTTP 代理指过来、装一次它生成的 CA，
之后小程序里的每个请求都会被抓下来——列表、详情、报名、鉴权头，全都能看到、能导出、能重放。

**用途**：先搞清楚学校那个活动小程序的接口长什么样，再决定「抢活动」能做到哪一步。
**不联网上传任何东西**，不碰班级数据，只写本机 `pcap/captures/`。

---

## 0. 准备（一次性）

- Windows + Python 3.8+（本机 3.12）
- `pip install cryptography`
- 手机和电脑连**同一个 Wi-Fi**

```powershell
cd C:\Users\Ko_Li\.openclaw\workspace\web
python pcap\pcap.py run
```

启动后会打印类似：

```
抓包已启动  pcap.py v1.0.0
  本机        http://127.0.0.1:8080/
  局域网      10.198.142.192:8080    ← 手机 Wi-Fi 代理填这个
  证书页      http://pcap.local:8080/
  输出        ...\pcap\captures\20261114-211507
```

（也可以双击 `pcap\pcap.cmd`，等价于 `run`。）

---

## 1. 手机接上代理

### iPhone（推荐，成功率最高）

1. 设置 → Wi-Fi → 当前网络右边的 ⓘ → 配置代理 → **手动**
   服务器填电脑的局域网 IP（如 `10.198.142.192`），端口 `8080`，存储。
2. Safari 打开 `http://pcap.local:8080/ca.crt` → 允许下载 → 设置里点「已下载描述文件」→ 安装。
3. **关键一步**：设置 → 通用 → 关于本机 → **证书信任设置** → 找到 `pcap local CA` → 打开完全信任。
4. 打开微信 → 进那个活动小程序 → 正常点几下。

### 安卓

1. Wi-Fi 高级设置 → 代理 → 手动，同上。
2. 浏览器打开 `http://pcap.local:8080/ca.crt` 下载 → 设置 → 安全 → 加密与凭据 → 安装证书 → **CA 证书**。
3. ⚠️ Android 7 以上很多 App 不信任「用户证书」，微信大概率抓不到（控制台会提示 TLS 握手失败）。
   优先用 iPhone；安卓需要 root 把证书装进系统区，成本高，不推荐。

### PC 微信小程序（可以，但比手机多两步）

**能抓**，只是要额外做两件事：把 CA 装进 Windows 根证书 + 用 Proxifier 按进程转发。
PC 微信 4.x 的小程序跑在 `WeChatAppEx.exe`（`xwechat\XPlugin\Plugins\RadiumWMPF\` 下），
**不读系统代理**，所以在 Windows 设置里填代理对它没用。

```powershell
python pcap\pcap.py trust     # 1. 把 CA 装进「当前用户 → 受信任的根证书颁发机构」
python pcap\pcap.py pc        # 2. 打印本机步骤（自动找到 WeChatAppEx.exe 的真实路径）
python pcap\pcap.py run       # 3. 起抓包，记下端口
```

4. Proxifier（官方试用 30 天）→ `Profile → Proxy Servers` → 添加 `127.0.0.1:8080`，
   协议选 **HTTPS**。Proxifier 里的 HTTPS 指「支持 CONNECT 的 HTTP 代理」（官方叫
   CONNECT proxy / SSL proxy），正是我们这种；`HTTP` 选项只处理 80 端口明文，还要在
   `Profile → Advanced → HTTP Proxy Servers` 额外开启，别选。
5. `Profile → Proxification Rules` → 新增一条：
   - Applications：粘贴第 2 步打印的 `WeChatAppEx.exe` 完整路径
   - Action：选第 4 步那个代理
   - **这条规则必须排在 `Default` 之上**，否则不生效
6. 完全退出微信（右下角托盘 → 退出），重新打开 → 进活动小程序 → `python pcap\pcap.py list`。

几个实测要点：

- 微信主程序 `Weixin.exe` 没有流量是**正常**的，小程序请求全由 `WeChatAppEx.exe` 发出。
- Proxifier 的 `Default` 规则建议设成 **Direct**，只留 `WeChatAppEx.exe` 这一条走代理；
  否则浏览器、其它软件也会被塞进抓包，既吵又会拖慢上网。
- **不要把 Windows 系统代理改成 8080**：那会让浏览器/所有程序都进代理，而且 `--upstream-proxy auto`
  检测到端口相同会主动放弃链式转发。系统代理保持原样（如有 Clash 就还是它自己的端口）即可。
- Proxifier 提示「connection loop」时，按提示关掉 loop detection 即可。
- 装的是**系统级根证书**，比手机装描述文件更「重」，不用了请 `python pcap\pcap.py trust --remove`。
- 备选：本来就用 Clash 的话，可以用 TUN 模式 + 进程规则把 `WeChatAppEx.exe` 转进来，省掉 Proxifier。
- 如果 Proxifier 配好后 `list` 仍然空、控制台却出现 `TLS 握手失败`，说明这个版本做了证书校验，回手机。

> 优先顺序：**iPhone > PC 微信 > 安卓**。

---

## 2. 抓活动的正确姿势

先别急着点「报名」——按这个顺序抓，噪音最少：

1. **先进活动列表页**，上下滑两下。→ 抓到列表接口（通常是 `GET .../activity/list?page=1&status=...`）。
2. **点进一个活动详情**。→ 抓到详情接口（带活动 id）。
3. **报名那一步**：想看请求结构又不想真占名额，挑一个**已满员/已结束**的活动点报名，
   提交会失败，但请求原样被记录下来。真报名请留到工具做好之后。
4. 回电脑上看：

```powershell
python pcap\pcap.py list          # 所有请求，找学校那个域名
python pcap\pcap.py show 12       # 看第 12 条的完整请求/响应（token 自动打码）
```

5. 知道域名后，下次只抓它，干净很多：

```powershell
python pcap\pcap.py run --only "*.fjtcm.edu.cn,*.xxx.com"
```

### 抓包时注意

- 尽量别在抓包期间刷朋友圈/视频号（默认已排除微信 CDN 噪音，但仍会多）。
- 小程序页面如果一直转圈，说明证书没被信任，回第 1 步检查「完全信任」。
- 抓完记得：**关代理、删证书**（见 §6）。

---

## 3. 常用命令

| 命令 | 作用 |
|---|---|
| `python pcap\pcap.py run` | 启动抓包（默认 `0.0.0.0:8080`） |
| `... run --port 8081` | 换端口 |
| `... run --only "*.fjtcm.edu.cn"` | 只抓指定域名（逗号分隔，支持 `*`） |
| `... run --upstream-proxy off` | 上游直连（默认 `auto`：自动用 Windows 系统代理） |
| `... run --upstream-proxy http://127.0.0.1:7890` | 指定上游代理（本机有 Clash/V2Ray 时用） |
| `... run --keep-wechat` | 不过滤微信/系统噪音域名 |
| `... run --save-images` | 连图片响应体一起存（默认只存头，省空间） |
| `python pcap\pcap.py list` | 列出本次抓到的请求 |
| `... list -s 20261114-211507` | 看指定会话 |
| `python pcap\pcap.py show 12` | 看第 12 条：请求头/请求体/响应头/响应体（敏感值打码） |
| `... show 12 --raw` | 附原始 base64（想看二进制时） |
| `python pcap\pcap.py har -o 活动.har` | 导出 HAR（**默认脱敏**，可直接发人） |
| `python pcap\pcap.py replay 12` | 重放第 12 条（GET 直接发；POST/PUT 要加 `--send`） |
| `... replay 12 --repeat 3` | 连发 3 次，看耗时稳定性 |
| `python pcap\pcap.py ca` | 看 CA 路径、指纹、有效期 |
| `python pcap\pcap.py ca --regen` | 重新生成 CA（旧证书全部失效，手机要重装） |
| `python pcap\pcap.py trust` | 把 CA 装进 Windows 当前用户根证书（PC 微信/浏览器用） |
| `... trust --remove` | 从 Windows 根证书里卸载 |
| `python pcap\pcap.py pc` | 打印 PC 微信步骤，自动找 `WeChatAppEx.exe` |

退出：`Ctrl+C`，会打印本次共抓了多少条。

---

## 4. 抓完给我什么

最省事：导出一份 HAR 发我。

```powershell
python pcap\pcap.py har -o 活动接口.har
```

HAR 里 `Authorization` / `Cookie` / token 字段已经替换成 `***REDACTED***`，
**可以直接贴给我**，我需要的是：接口地址、方法、参数结构、响应 schema。

如果只想贴几条，`show 12 --full` 的输出也行。

---

## 5. 目录与产物

```
pcap/
  pcap.py           工具本体（单文件，除 cryptography 外全标准库）
  pcap.cmd          双击启动
  README.md         本文件
  requirements.txt  依赖
  tests/selftest.py 自检（33 项，全本地，不联网）
  ca/               ⚠️ CA 私钥 + 站点证书，gitignore
  captures/         ⚠️ 抓包内容（含 token），gitignore
```

- `ca/ca.key`：CA 私钥。拿到它就能伪造任意 HTTPS 站点，**绝不外传**。
- `captures/<时间>/NNNN.json`：每条请求一个文件，`index.jsonl` 是索引。
- 存的是**原始**请求（含 token），`show` 和 `har` 才打码——所以抓包目录本身要当敏感文件对待。

---

## 6. 隐私与清理

- 只在本机和**可信 Wi-Fi** 用；代理是明文中间人，同一网络里别人也可能连上来。
- 用完：手机里关掉 Wi-Fi 代理 → 删除描述文件/证书 → `Ctrl+C` 停掉代理。
- PC 端用完：`python pcap\pcap.py trust --remove`，并在 Proxifier 里停用那条规则。
- 想清空抓包：直接删 `pcap/captures/`。
- 这些目录已进 `.gitignore`，不会被 `sync-repos.cmd` 提交。

---

## 7. 排错

| 现象 | 处理 |
|---|---|
| `? 连接 ... 收到 TLS 握手` | 有客户端对代理本身做了 TLS。本代理是明文 HTTP 代理：检查代理软件里「对代理使用 SSL/TLS」这类选项，关掉 |
| `? 连接 ... 连上就断开` | 一般是 Proxifier 的连通性探测；如果只有这种，说明规则没把 `WeChatAppEx.exe` 的流量导进来 |
| `! TLS 失败 <IP>:443` | 看后面的 `SNI=`：图片/CDN 域名可以忽略；如果是学校接口域名，说明客户端不信任本机 CA 或做了证书固定 → 彻底退出微信（任务管理器确认没有 `WeChatAppEx`）再开；仍失败就换 iPhone |
| `502 [upstream: TimeoutError]` | 本机走了 Clash/V2Ray 之类的系统代理，直连连不上。默认 `--upstream-proxy auto` 会自动用系统代理；如果系统代理被关过，手动加 `--upstream-proxy http://127.0.0.1:18081` |
| 手机连不上（浏览器打不开 `pcap.local`） | 同一 Wi-Fi？Windows 防火墙是否拦了 Python（控制面板 → 防火墙 → 允许应用）；换 `--bind 0.0.0.0`；用 `IP:端口` 而不是域名 |
| `Connection refused` | 代理没启动 / 端口写错 / 端口被占用（启动日志会提示换 `--port`） |
| 浏览器提示证书不受信任 | iOS 没开「完全信任」；或证书没装成功（重下 `ca.crt`） |
| 小程序白屏、一直转圈 | 证书没信任；或该小程序做了证书固定（pinning）——控制台会出现 `TLS 握手失败`，换 iPhone / PC 微信试 |
| 列表里没有活动接口 | 小程序可能用了 WebSocket 或本地缓存；杀掉小程序重进、多滑两下再抓 |
| PC 微信抓不到 | 小程序请求由 `WeChatAppEx.exe` 发出（不是 `Weixin.exe`），且不走系统代理：装 `trust` + Proxifier 规则指到它，规则要在 `Default` 之上，改完完全退出微信再开 |
| 用 curl 测试报 `schannel: revocation status is unknown` | Windows curl 的特性，加 `--ssl-no-revoke`（不影响手机） |
| 抓到一堆 `*.qpic.cn` / `*.gtimg.com` | 默认已排除；若还多，用 `--only` 限定学校域名 |

---

## 8. 自检

改完本工具跑一次（不联网、只用 127.0.0.1 的假源站）：

```powershell
python pcap\tests\selftest.py
```

覆盖：CONNECT/TLS、keep-alive、GET/POST、gzip、chunked、明文 HTTP、CA 下载页、
落盘、`show` 打码、HAR 脱敏、`replay`（GET 放行 / POST 未加 `--send` 拒绝）、
链式上游代理（`--upstream-proxy` 经二级代理转发并落盘）。

期望输出 `RESULT: PASS  37/37`。

---

## 9. 边界（先说明）

- 只抓**你自己的**账号流量，只用于看清接口结构。
- `replay` 非 GET 默认不发送，就是怕误把报名提交出去。
- 不提供绕过验证码/风控/证书固定的功能。
- 接口随时可能改版，抓到的结构只代表当时。
