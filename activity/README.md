# activity —— 第二课堂本地助手

用抓包得到的 token + 逆向出的签名，直接调用学校「第二课堂」接口。
只在本机跑，给班级工具站的「活动」页提供数据；也可以直接命令行用。

> 仅本机、仅自己账号。token 会过期；接口/签名一旦改版就失效。

## 一次性准备

```powershell
python activity\agent.py import-token
```

它从 `pcap/captures/` 最新一次抓包里取 token、userId、classId，存到 `activity/token.json`（已 gitignore）。
前提是你用 pcap 抓过一次、并在小程序里进过活动列表页。

## 命令

```powershell
python activity\agent.py list                 # 活动列表
python activity\agent.py show <活动id>         # 详情 + 各角色名额
python activity\agent.py sign <活动id>         # dry-run，只打印请求
python activity\agent.py sign <活动id> --apply # 真的报名
python activity\agent.py cancel <活动id> --apply
python activity\agent.py serve                # 给网页用，127.0.0.1:8790
```

`list` 的 ID 就是 `show/sign` 要用的活动 id。

## 首次登录（每个同学一次，不经过任何服务器）

双击 **`activity\首次登录.cmd`**（等价于 `python activity\agent.py login`）：

1. 弹出一个专用浏览器窗口，打开学校活动网页
2. 点「统一身份认证」，用**学号+密码**登录（密码只输入到学校页面，助手不接触）
3. 登录成功后助手自动从页面 localStorage 读回 token，浏览器可以关掉
4. 之后日常只要双击 **`启动助手.cmd`**（= `serve`）

token 过期时（页面提示「未连接」），重新双击 `首次登录.cmd`；浏览器会保留登录状态，通常点一下就好。

> 没有 Python 的同学：后续可以打包成单个 exe，双击即用（见「分发」）。

## 本地服务（给工具站用）

`serve` 在 `127.0.0.1:8790` 提供：

| 接口 | 说明 |
|---|---|
| `GET /health` | 是否已导入 token |
| `GET /list?page=1&rows=20` | 活动列表 |
| `GET /detail/<id>` | 详情 + 角色名额 |
| `POST /sign/<id>` body `{"apply":false}` | 报名（默认 dry-run） |
| `POST /cancel/<id>` body `{"apply":false}` | 取消 |

只监听 127.0.0.1；CORS 允许 `http://121.196.47.2`、`http://127.0.0.1:8787` 等本机/站点来源。

> 站点以后上 HTTPS 后，网页不能直接调 `http://127.0.0.1`（混合内容），要走
> `deploy/local_channel.py` 的本机入口（`http://127.0.0.1:8787/`）打开站点。

## 签名（为什么能直接调）

2026-11-14 用抓包样本反推并 30/30 验证通过：

```
Authorization = base64( ts + ":" + nonce + ":" + md5(salt + 完整URL(不含query) + ts + nonce) + ":" + token )
salt = "rndAgtFzYJpyKlRY"
```

salt 写在 `config.json`（可选），学校改版时改这里，不用改代码：

```json
{ "salt": "rndAgtFzYJpyKlRY", "port": 8790 }
```

## 已知限制

- **token 会过期**：重新抓一次包，再 `import-token`；命令返回 401 就是过期了。
- 学校服务器 DH 只有 1024 位，代码里已把 OpenSSL 降到 `SECLEVEL=0`。
- 默认全部 dry-run，`--apply` 才真的提交。
- 这套签名是校方的防脚本机制，使用风险自担。

## 能跑在哪些端

| 端 | 支持 | 说明 |
|---|---|---|
| Windows 10/11 | ✅ 主推 | 双击 `首次登录.cmd` / `启动助手.cmd`；Edge 自带 |
| macOS | ⚠️ 需小改 | `python3` + Chrome/Edge；`find_edge()` 的路径要补 |
| Linux | ⚠️ 需小改 | 同上，有 Chrome 即可 |
| Android / iOS | ❌ | 跑不了本地 HTTP 服务 + 浏览器自动化，得写原生 App |
| 微信小程序 | ❌ | 读不到学校站点的 localStorage，也过不了跨域 |
| 纯网页 | ❌ | CORS + 拿不到 token |

工具站本身三端都能打开，但「活动」页只有在 **PC 上跑着助手** 时才有数据；
小程序/安卓打开会显示「未连接」。

## 分发

同学电脑要有 Python 3.8+，并装一次 `websocket-client`：

```powershell
python -m pip install websocket-client
```

不想让同学装 Python，就把 `activity/` 用 PyInstaller 打成单个 exe：

```powershell
pip install pyinstaller
pyinstaller --onefile --name 活动助手 activity\agent.py
```

（exe 版只需双击；浏览器登录逻辑不变。）
