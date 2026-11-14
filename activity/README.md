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
