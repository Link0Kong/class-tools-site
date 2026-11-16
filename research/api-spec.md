# 完美校园（新开普 17wanxiao）电费 / 智能水电 接口协议解析

> 分析员：api-analyst（Agent Team）｜日期：2026-11-05（Asia/Shanghai）｜
> 目标用户：福建中医药大学（FJTCM）2026 级本科生
> 本文所有结论都带**置信度**标注，请勿把「推测」当「实测」使用。

## 置信度标签

| 标签 | 含义 |
| --- | --- |
| **实测** | 本轮由我直接发出 HTTP 请求 / 直接阅读可执行源码后验证（2026-11-05） |
| **多源一致** | ≥2 个相互独立的来源（或 ≥2 个独立开源实现）说法一致 |
| **单源** | 只有 1 个来源或 1 个开源实现，未见交叉验证 |
| **推测** | 由间接证据推理，没有直接证据 |

> 说明：本轮探活上限 5 次 HTTP 请求，我全部用在「空参/假参」上，未登录、未提交任何真实个人信息。探活原始响应见 §9。

---

## 0. 结论速览（先看这段）

1. **完美校园的宿舍水电查询有 3 代产品线并存**（不是「两代」）：
   - **老 H5 引擎 SWAEServlet**（`xqh5.17wanxiao.com`，POST）——**无账号鉴权**，只要「学校编码 + 学号」即可查绑定房间、余额/电量/日/月用电。2024-09 仍可用，2026-11-05 我复测**接口存活**。【实测 + 多源一致】
   - **加密版 SWAEEncryptServlet**（同域名，POST）——同一后端，但请求/响应体用 **AES-128-ECB** 加密（密钥由请求自带的 `timestamp`+`randomStr` 现场推导），**仍然不需要账号登录**，只是混淆。【多源一致（2 个独立实现）】
   - **App / CloudPayment 引擎**（`h5cloud.17wanxiao.com:18443/CloudPayment/`，GET）——**需要完美校园 App 登录态**（token/握手 session），走 `pay.do → SESSION → 5 步链` 才能查 `getRoomState`。这是「缴费 → 用电支出」页面用的接口。【多源一致 + 实测（2019 老域名存活）】
   - 另外还有 **2022 年微信端「新接口」**（微信 code → openid+token → session 的路子）【单源，正文未给出域名，见 §3.2】。
2. **福建中医药大学（schoolId=769）大概率没有接入完美校园「智能水电」**：
   - 学校官方（现代教育技术中心，2021-07 官微 + 2022-08 信息化 FAQ）明确：**查电费用「今日校园」→ 公共服务 →「购电查询」**，填楼栋号+房间号即可看「用电总量 / 购电总量 / 可用电量」。【多源一致（学校官方 2 篇）】
   - 完美校园在福中医的公开用途是**校园卡充值**（2017 年龙支付充值、2018 年校园卡充值须知）。【多源一致（学校后勤 2 篇）】
   - 我用福中医学校编码 769 实测 SWAEServlet `getbindroom`：返回 `8099 调用接口失败,body格式错误`；用对照学校 759（桂电北海，开源项目验证可用）同假参返回 `{"result":"0","ver":2,"existflag":"0","message":"操作成功"}`。→ **推测：FJTCM 未开通/未适配完美校园智能水电**（详见 §7）。【实测 + 推测】
3. **如果「今日校园」那条路能抓出后端接口，很可能才是 FJTCM 的正解**；完美校园这条路对 FJTCM 只能作为「先试一下」的备选。建议 Lead 让用户做一次「今日校园 购电查询」页面的抓包（用户自己操作，不需要给我们账号）。

---

## 1. 域名 / 产品线总览

| # | 产品线 | 域名 | 路径 | 鉴权 | 现状/证据 |
| --- | --- | --- | --- | --- | --- |
| A | 老 H5 水电引擎（明文） | `xqh5.17wanxiao.com` | `/smartWaterAndElectricityService/SWAEServlet` | **无**（学校编码+学号+房间凭证） | 2026-11-05 实测存活；2024-09 博主实测可用 |
| A2 | 老 H5 水电引擎（加密版） | `xqh5.17wanxiao.com` | `/smartWaterAndElectricityService/SWAEEncryptServlet` | 无登录，但请求/响应 AES-128-ECB 加密 | 2 个独立开源实现（2025） |
| A3 | 现代会话入口 | `xqh5.17wanxiao.com` | `/smartWaterAndElectricityService/loginCheck` | 依赖「落地页 params」（来源：学校 SSO / 公众号 / 小程序） | 1 个开源实现（2025-2026） |
| B | App 缴费引擎 CloudPayment | `h5cloud.17wanxiao.com:18443`（旧 `:8080`） | `/CloudPayment/...` | **需要 App 登录 token + SESSION Cookie** | ≥4 个独立实现；2019 老接口记录 |
| C | 充值下单网关 | `xqh5.17wanxiao.com` + `cloudpaygateway.59wanmei.com:8087` | `/smartWaterAndElectricityService/goPay`、`/paygateway/smallpaygateway/trade` | 免登录即可生成支付链接（含实名校验） | 1~2 个实现（2025） |
| D | 完美校园 App 账号体系 | `app.17wanxiao.com/campus/cam_iface46/` | `exchangeSecretkey.action`、`loginnew.action`、`gainMatrixCaptcha543.action` 等 | RSA 换密钥 + 3DES 加密 + deviceId 风控 | ≥3 个独立实现（2021-2026） |
| D2 | 完美校园开放平台 OAuth | `api.17wanxiao.com/api/...`、`open.17wanxiao.com` | `/api/authorize`、`/api/1/*` | OAuth access_token | 单源（搜索引擎摘要）；官方文档站现已 404，未能全文核实 |
| E | 一卡通 / 校园卡 | `server.17wanxiao.com/YKT_Interface/xyk`、`xqh5.17wanxiao.com/keychain/Api`、`ecard.v.<学校>.edu.cn` | 各校不同 | token / CAS | 多源但偏「校园卡」，与电费无直接关系，本文不展开 |

**相关但非电费**：`cloudpaygateway.59wanmei.com`（59wanmei = 完美校园支付网关）、`payicons.59wanmei.com`（缴费项目图标 CDN）、`100campus.com`（完美校园公司域名，本轮未发现可用的电费 API 文档）。

---

## 2. 端点清单与参数

### 2.1 【A】`SWAEServlet` —— 查询类主力（无鉴权）

```
POST https://xqh5.17wanxiao.com/smartWaterAndElectricityService/SWAEServlet
Content-Type: application/x-www-form-urlencoded
```

字段可以**放 POST 表单体**，也可以**拼在 URL query 上**（两种写法在真实实现里都出现过，服务端都认）。【多源一致】

| 参数 | 必填 | 位置 | 说明 | 置信度 |
| --- | --- | --- | --- | --- |
| `param` | ✅ | body 或 query | JSON 字符串，形如 `{"cmd":"getbindroom","account":"学号"}`，`cmd` 与 `method` 必须一致 | 多源一致 |
| `customercode` | ✅ | body 或 query | **学校编码**（= school_id，见 §6.1；FJTCM=769） | 多源一致 + 实测 |
| `method` | ✅ | body 或 query | 与 `param.cmd` 相同的接口名 | 多源一致 |
| `command` | 视接口 | body 或 query | 后端服务类名，**因学校而异**：`JBSWaterElecService` / `OWNWaterElecService`；也可从 `loginCheck` 动态取 | 多源一致（两种值都出现过） |

> ⚠️ 未登录时该接口**只校验「学校编码 + 学号」**，因此它对任意房间的余额存在越权读取面。只查自己账号，不要批量探测。

#### 2.1.1 `getbindroom` —— 查「学号绑定的所有房间」

请求示例（可直接抄）：

```bash
curl -s 'https://xqh5.17wanxiao.com/smartWaterAndElectricityService/SWAEServlet' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -H 'X-Requested-With: com.newcapec.mobile.ncp' \
  -H 'Origin: https://xqh5.17wanxiao.com' \
  -H 'Referer: https://xqh5.17wanxiao.com/userwaterelecmini/index.html' \
  --data-urlencode 'param={"cmd":"getbindroom","account":"<学号>"}' \
  --data-urlencode 'customercode=<学校编码>' \
  --data-urlencode 'method=getbindroom'
```

响应（真实字段样例，来自 Apifox 共享文档，2024-09 抓包）：

```json
{
  "code_": 0,
  "sign": "EB29AE29889FC4FE",
  "result_": "true",
  "body": "{\"result\":\"0\",\"ver\":2,\"existflag\":\"2\",\"message\":\"操作成功\",\"roomlist\":[{\"roomfullname\":\"南珠校区_2#公寓_6层_24603\",\"detaillist\":[{\"use\":\"10066.2\",\"odd\":\"196.86\",\"businesstype\":\"0\",\"status\":\"1\"}],\"roomverify\":\"99-5--20-24603\"}]}",
  "message_": "获取成功！"
}
```

字段说明见 §4.2。注意：`body` 是**字符串**，需要二次 `json.loads`。【实测 + 多源一致】

#### 2.1.2 `h5_getstuindexpage` —— 查单个房间详细水电（首页数据）

```bash
curl -s 'https://xqh5.17wanxiao.com/smartWaterAndElectricityService/SWAEServlet' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -H 'X-Requested-With: com.newcapec.mobile.ncp' \
  -H 'Origin: https://xqh5.17wanxiao.com' \
  -H 'Referer: https://xqh5.17wanxiao.com/userwaterelecmini/index.html' \
  --data-urlencode 'param={"cmd":"h5_getstuindexpage","roomverify":"<上一步的 roomverify>","account":"<学号>","timestamp":"20261105223000000"}' \
  --data-urlencode 'customercode=<学校编码>' \
  --data-urlencode 'method=h5_getstuindexpage' \
  --data-urlencode 'command=<JBSWaterElecService 或 OWNWaterElecService>'
```

- `timestamp` 格式为 `yyyyMMddHHmmss` + `000`（18 位），**可选**（有的实现不传也能过）。【多源一致】
- `roomverify` 传空串 `""` 时，部分学校会返回当前账号的默认房间首页（JustaSage 项目即如此）。【单源】
- `command` 在该接口上必带（Apifox 与 doupoa 都带 `JBSWaterElecService`）；也有项目用 `OWNWaterElecService` 成功。学校相关，两个都试。【多源一致】

真实响应 `body`（Apifox 样例，节选，完整见来源）：

```json
{
  "isshowsubsidy": "0",
  "modlist": [{
    "mac": 78063,
    "blunum": "078063",
    "accode": 51101,
    "odd": 232.7,
    "todayuse": 14.8,
    "devicename": "电控",
    "bussnesstype": 0,
    "status": 1,
    "isshowpay": 1,
    "sumbuy": 484.6,
    "sumsub": 17994.57,
    "totalamount": 0,
    "weekuselist": [
      {"date":"09-04","daydate":"09-04","use":38,"dayuse":38,"weekday":"星期三",
       "formatweek":{"year":124,"month":8,"date":4,"time":1725379200000,"timezoneoffset":-480}}
    ],
    "monthuselist": [{"monthuse": 0, "yearmonth": "2022.01"}, {"monthuse": 138.9, "yearmonth": "2022.03"}],
    "todolist": [], "modstatus": []
  }],
  "roomfullname": "西区12栋-12619",
  "roomnum": "12619",
  "roomverify": "101-16--204-12619",
  "message": "操作成功",
  "result": "0",
  "subornot": "0,0,0,1,1,0",
  "isexpplan": "1"
}
```

#### 2.1.3 `gettimeusedetail` —— 区间（日）用量

| param 字段 | 说明 |
| --- | --- |
| `cmd` / `method` | `gettimeusedetail` |
| `roomverify` | 房间凭证 |
| `businesstype` | 业务类型，取 `getbindroom.detaillist[].businesstype`（0=电，1=冷水，2=热水） |
| `startdate` / `enddate` | `YYYY-MM-DD` |

响应 `body`：`sumuse`（区间合计用量，字符串）、`dayuselist[]`（`date` / `use` / `firstcolldate` / `lastcolldate`）。【单源：Jursin/wanxiao-electric-apis README】

#### 2.1.4 `getusedetail` —— 月度用量

| param 字段 | 说明 |
| --- | --- |
| `cmd` / `method` | `getusedetail` |
| `roomverify` | 房间凭证 |
| `businesstype` | 同上 |
| `yearmonth` | `YYYY-MM` |

响应 `body`：`monthuse`（当月总量）、`dayuselist[]`（`daydate` / `dayuse`）。【单源：同上】

> **「充值记录」没有找到公开可用的接口**。完美校园 App 的 UI 路径明确存在（智能水电 → 右上角「…」→ 充值记录），但没有任何公开源码/文章给出对应 HTTP 接口。【多源一致（UI 存在）+ 推测（接口未知）】
> 想拿充值记录只有三条路：① 抓包自己 App 的「充值记录」页；② 走 CloudPayment 的账单接口族（`bill/*`，需登录态）；③ 学校侧平台（FJTCM 用今日校园，见 §7）。

### 2.2 【A2】`SWAEEncryptServlet` —— 加密版（仍是「学校编码+学号」即可）

```
POST https://xqh5.17wanxiao.com/smartWaterAndElectricityService/SWAEEncryptServlet
Content-Type: application/x-www-form-urlencoded
```

表单字段：

| 字段 | 说明 |
| --- | --- |
| `encryptData` | 密文：对「内层表单串」做 **AES-128-ECB（PKCS7）+ base64** |
| `timestamp` | 13 位毫秒时间戳（明文） |
| `randomStr` | 10 位随机串（大写字母+数字，明文） |
| `method` | 明文接口名（如 `getbindroom`），与内层 `method` 一致 |

**密钥推导**（2 个独立实现交叉验证一致）【多源一致】：

```
key16 = ( int(timestamp) 为奇数 ? timestamp 前 6 位 : timestamp 后 6 位 ) + randomStr
```

内层明文是一个 JSON 串（把外层表单字段序列化）：

```json
{"param":"{\"cmd\":\"getbindroom\",\"account\":\"<学号>\",\"timestamp\":\"<13位毫秒>\"}","customercode":"<学校编码>","method":"getbindroom","command":"<服务类名>"}
```

响应有两种形态：① 明文信封（同 SWAEServlet）；② 加密信封 `{encryptData, timestamp, randomStr}` → 用同样的 key 规则解密。【多源一致】

Python 解密示例（只需 `pycryptodome`）：

```python
import base64, json
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

def campus_key(ts: str, random_str: str) -> bytes:
    head = ts[:6] if int(ts) % 2 else ts[-6:]
    return (head + random_str).encode()

def decrypt_payload(body: str) -> dict:
    form = dict(x.split("=", 1) for x in body.strip().split("&"))
    raw = base64.b64decode(form["encryptData"])
    plain = unpad(AES.new(campus_key(form["timestamp"], form["randomStr"]), AES.MODE_ECB).decrypt(raw), 16)
    return json.loads(plain)
```

> 注意：PHP 实现写作 `((int)$stamp % 8) % 2 ? 前6位 : 后6位`，Python 实现写作 `int(ts) % 2`，两者对 10 进制时间戳等价。

### 2.3 【A3】`loginCheck` —— 现代「带身份」入口（小程序/公众号/SSO 落地页）

```
POST https://xqh5.17wanxiao.com/smartWaterAndElectricityService/loginCheck
Content-Type: application/x-www-form-urlencoded

data=<落地页 URL fragment 里的 params 原文>
```

落地页长这样（由学校统一身份认证 / 公众号 / 小程序授权后跳转）：

```
https://xqh5.17wanxiao.com/userwaterelecmini/index.html#/?params=<一串带身份信息的参数>
```

响应：`{"resultdata": "<base64>"}`，`resultdata` 用 **AES-128-ECB / PKCS7，密钥固定 `1234567812345678`** 解密，得到

```json
{"body": "{\"result\":\"0\",\"data\":{\"customerCode\":\"...\",\"command\":\"...\",\"outid\":\"<学号>\",\"userid\":\"...\"}}"}
```

拿到 `customerCode / command / outid` 后再调 §2.1 的 `SWAEServlet`。【单源：JustaSage/ZCST_FEE_Bot，2025-2026】
SSO 链路本身（CAS REST：TGT → ST → hub → 17wanxiao 授权链接）也是该项目实现。【单源】

> 这条线的意义：**「新接口加身份验证」的本质是「入口参数由 SSO/微信授权生成」**，不是给 API 加了账号密码鉴权。参数一旦拿到，后续调用仍然是同一个 SWAEServlet。

### 2.4 【B】CloudPayment（App「缴费 → 用电支出」引擎，需要登录态）

```
基址：https://h5cloud.17wanxiao.com:18443/CloudPayment/    （2019 年为 :8080）
```

5 步链（全部 GET）：【多源一致】

| 步 | 请求 | 作用 |
| --- | --- | --- |
| 1 | `user/pay.do?versionnum=…&customerId=<学校编码>&systemType=Android&UAinfo=wanxiao&versioncode=…&token=<握手 session>` | 302 跳转并下发 HttpOnly `SESSION` Cookie（必须用 CookieJar 接住这一跳） |
| 2 | `bill/type.do` | 缴费分类 |
| 3 | `bill/querySelfPayList.do` | 返回 `payprolist`（含「用电支出 / 购冷水支出」等项目）。**列表为空 = token 无效**（服务端不报错） |
| 4 | `bill/selectPayProject.do?txcode=elecdetails&interurl=elecdetails&payProId=…&amtflag=0&payamt=100&payproname=<urlencode>…` | 建立会话上下文，同时这条 URL 要作为后续 Referer |
| 5 | `user/getRoomState.do?payProId=…&schoolcode=…&businesstype=2&roomverify=<校区-楼栋--楼层-房间>` | **查剩余量** |

`getRoomState.do` 真实响应（多源样例）：

```json
{"returncode":"100","returnmsg":"SUCCESS","quantity":"324.82","quantityunit":"度","canbuy":"true","description":"412"}
```

字段：`quantity`=剩余量，`quantityunit`=单位（电「度」/水「吨」），`canbuy`=是否可购，`description`=房间号/描述（有的学校还有 `custparams` 扩展）。【多源一致】

**三个隐蔽要求**（否则一律返回「系统繁忙」，极具误导性）【多源一致 + 单源细节】：

1. **Referer 参与鉴权**：服务端从 Referer 的 `payProId` 反查房间序列号 `idserial`。缺第 4 步或 Referer 不对 → `RspBaseVO [code=ERROR, msg=系统繁忙，请稍后重试]`（HTTP 200）。
2. **Cookie 必须用真正的 CookieJar**：`pay.do` 是 302 响应**那一跳**下发 SESSION 的，手工解析最终响应会丢。
3. **token 无效不报错**：会发匿名 SESSION，返回 200 HTML，`querySelfPayList` 的 `payprolist` 为 `null`。唯一可靠探针 = 「缴费项目列表非空」。
4. 请求头需带：`X-Requested-With: XMLHttpRequest`、`Accept: application/json, text/javascript, */*; q=0.01`、App 内嵌 WebView 的 UA、上述 Referer。

房间树枚举（同族接口，逐层下钻）：

```
GET /CloudPayment/user/getRoom.do?payProId=…&schoolcode=…&businesstype=2
    &optype=1|2|3|4&areaid=&buildid=&unitid=&levelid=
```

- `optype=1` 校区；`2` 楼栋；`3` 单元/楼层；`4` 房间。【多源一致】
- **坑**：`optype=4` 返回的 `id` **已经是拼好的 roomverify**（形如 `101-07--112-308`），不要再自己拼。【单源（但被 2019 CSDN 与 2024 项目同时印证）】
- 2019 年该接口完全无鉴权（只需 `payProId` + `schoolcode` + `businesstype`），现在已需要 token+SESSION。【多源一致】

### 2.5 【C】goPay / 支付网关（充值下单）

```
POST https://xqh5.17wanxiao.com/smartWaterAndElectricityService/goPay
Content-Type: application/x-www-form-urlencoded

param={"cmd":"getPayInfo", "thirdsource":"T002", "token":"", "wxToken":"",
       "idserial":"<学号>", "username":"<urlencode 姓名>", "txcode":"51101", "acccode":"51101",
       "payamt":"<金额，单位：分>", "schoolcode":"<学校编码>", "customerName":"<urlencode 学校名>",
       "returnurl":"https://xqh5.17wanxiao.com/userwaterelecmini/index.html#/pages/index/index",
       "payaccnum":"<roomverify>", "payaccname":"<urlencode 房间名>",
       "paychannel":"13", "journo":"T002<时间戳><6位随机>", "checkIdentity":"1",
       "customizedPay":"<学校编码>", "customJson":"{...}"}
customercode=<学校编码>
method=getPayInfo
command=JBSWaterElecService
```

响应 `body` → `{"result":0,"data":{"url":"…","jsonData":"…","sign":"…"}}`，拼成
`<url>?jsonData=<encode>&sign=<encode>` 即支付页（支付宝 WAP / 云缴费）。【单源：stmtc233/WanXiao-Elec-TgBot】

配套实名校验（免登录）：

```
POST https://cloudpaygateway.59wanmei.com:8087/paygateway/smallpaygateway/trade
Content-Type: application/json;charset=UTF-8

{"timestamp":"YYYY-MM-DD HH:MM:SS","method":"smallProgramUserAuth",
 "bizcontent":"{\"token\":\"\",\"idserial\":\"<学号>\",\"schoolcode\":\"<学校编码>\"}",
 "sourceId":2}
→ {"returncode":"SUCCESS","businessData":{"username":"<姓名>","orgname":"<学校名>","orgcode":"...","idserial":"..."}}
```

> ⚠️ 充值涉及**真实支付**与**支付密码**，不属于本次「查询 + 提醒」范围。不建议在自动化脚本里实现充值。
> ⚠️ `smallProgramUserAuth` 能凭「学号+学校编码」免登录返回**真实姓名**，属敏感越权面，切勿批量试。

### 2.6 【D】App 账号登录协议（CloudPayment 的 token 来源）

基址：`https://app.17wanxiao.com/campus`【多源一致 + 实测（源码级）】

1. **换密钥** `POST /cam_iface46/exchangeSecretkey.action`
   - 客户端自生成 RSA-1024 密钥对，把公钥（SPKI DER base64，每 64 字符换行）以 `{"key": "..."}` POST 上去；
   - 用私钥（PKCS#1 v1.5）解密响应 → `{ session, key(32 hex) }`，`appKey = key[:24]`。
2. **密码登录** `POST /cam_iface46/loginnew.action`
   - 密码：**逐字符** 3DES-CBC 加密（key=appKey 24 字符，IV=`66666666`，PKCS#5/PKCS#7，base64）→ 得到 `password` 数组；
   - 业务体：`3DES-CBC(JSON)` → base64 → 外层信封 `{"session": sid, "data": "<b64>"}`，`Content-Type: application/text`；
   - 请求头 `campusSign = sha256(请求体原文).hexdigest()`；
   - 参数：`appCode=M002, deviceId, netWork=wifi, qudao=guanwang, requestMethod=cam_iface46/loginnew.action, shebeixinghao, systemType, telephoneInfo, telephoneModel, type=1, userName=<手机号>, wanxiaoVersion, yunyingshang=07`。
3. **新设备风控**：未绑定的 `deviceId` 调 `loginnew.action` 会返回
   `code_=5 您正在新设备上使用完美校园，请使用验证码进行验证登录`（该校验在密码校验**之前**，不消耗密码错误次数）。【多源一致】
4. **绑定受信设备（短信）**：
   - 发码 `POST /cam_iface46/gainMatrixCaptcha543.action`（**必须带 `543` 后缀**，否则发的不是同一条链路，提交必失败）；
   - 提交 `POST /cam_iface46/registerUsersByTelAndLoginNew.action`（`type=2` + `sms`），成功后本机 deviceId 成为受信设备；验证码与那次握手的 session 绑定，必须复用同一 session；每日额度约 100 次。
5. **token 到底是什么**：CloudPayment 认的 token = **本次登录握手信封里的 `session`（UUID）**，不是响应体里的 `user.token`（后者是账号级固定值，拿去 SSO 会被拒）。【单源但证据强：抓包铁证】
6. **有效期/刷新**：没有公开的官方 TTL。项目实践：每次任务开头重新登录一次即可；deviceId 绑定后可长期无人值守自动续。【单源（实践结论）】
7. **响应错误码**：`code_=0` 成功；`code_=4` 该手机号未注册完美校园；`code_=5` 新设备验证 / 密码错误（`密码错误,您还有N次机会!`）；`code_=6` 短信验证码错误；`800114003` 短信验证码错误（543 后缀坑）。【多源一致】

> 完美校园「只允许一个设备登录」：脚本用固定 deviceId 登录后，手机 App 再登录可能使旧 deviceId 失效。【多源一致】

---

## 3. 世代差异与鉴权全景

### 3.1 四代对比

| | 老 H5（A） | 加密版（A2） | 微信端「新接口」（2022） | App/CloudPayment（B/D） |
| --- | --- | --- | --- | --- |
| 时间 | 2019–2024+ | 2024–2026 | 2022 起 | 2019–2026 |
| 域名 | xqh5 | xqh5 | 正文未给（图片中）；落地页同 xqh5 | h5cloud / app.17wanxiao.com |
| 需要登录？ | ❌ | ❌ | ✅（微信 code/openid） | ✅（App 账号 + deviceId） |
| 密码加密 | 不涉及 | 不涉及 | 不涉及 | RSA-1024 换密钥 + 3DES-CBC（逐字符密码）+ sha256 campusSign |
| 验证码/滑块 | 无 | 无 | 微信 OAuth/实名 | 新设备**短信验证码**（无图形滑块）；绑定后免验证 |
| token | 无 | 无 | WX code→openid+token→session；`session` 放请求头，`SERVERID` 每次请求更新，Referer 必带 | 握手 session（UUID）+ CloudPayment SESSION Cookie |
| 能查什么 | 绑定房间/余额/电量/日/月用电 | 同 A | 电量数据 | 缴费项目 + 剩余量（quantity） |
| 备注 | 本文主力，FJTCM 试过不通 | A 的加密壳，密钥可自算 | 伪造 session 返 200+假 session；正确需 302 | 最容易踩 Referer/Cookie 坑 |

### 3.2 2022「微信端新接口」的原始描述（单源）

出处：doupoa《完美校园电费查询新接口请求原理解析》（2022-06-08，CSDN 同步）。原文流程：

1. 用户使用 WX 浏览器获取用户 code；
2. 利用 code 获取 openid 及 token（token 实质为 uuid，生成算法未知）；
3. 用 openid+token 请求跳转链接，**302 跳转**的 Location 里带 openid+token；
4. 用正确的 session 请求电量数据：**所有请求头必须包含该 session；与其相存在的是 SERVERID（每次请求后更新）；Referer 也必须包含**；
5. 未按上述步骤、用正确 openid+token 访问会返回**假 session + HTTP 200**；正确访问应 302 跳转到用户页面。

→ 结论：这条线把「微信用户身份」作为凭据，**纯脚本很难拿到 code/openid**，因此不如 A/A2/B 实用。【单源；域名未验证】

### 3.3 「有没有验证码 / 滑块」

- 电费查询类接口（A/A2）：**没有**验证码。【多源一致】
- App 登录：**新设备短信验证码**（不是图形验证码/滑块）。【多源一致】
- 微信端新接口：微信 OAuth（扫码/授权），无图形验证码。【单源】

---

## 4. 响应结构与字段表

### 4.1 外层信封（SWAEServlet / SWAEEncryptServlet 解密后）

```json
{"code_":0, "sign":"F70D1065FD5742EA", "result_":"true", "body":"<JSON 字符串>", "message_":"获取成功！"}
```

| 字段 | 类型 | 含义 | 置信度 |
| --- | --- | --- | --- |
| `code_` | int | 0=成功；非 0 看 `message_` | 多源一致 |
| `sign` | string | 16 位十六进制；**同 customercode 的请求 sign 相同**（实测：769 两次不同请求 sign 都是 `40AFD174B2BEB3AC`） | 实测 |
| `result_` | string | `"true"`=成功；否则 `message_` 为错误信息 | 多源一致 |
| `body` | string | **二次 JSON 字符串**，需 `json.loads` 两次 | 实测 + 多源一致 |
| `message_` | string | 外层提示，成功恒为「获取成功！」 | 实测 |

> `sign` 的用途未公开，**不是**客户端签名校验（服务端不校验请求签名）。不要依赖它做鉴权。【推测】

### 4.2 `getbindroom` 的 body

| 字段 | 类型 | 含义 | 置信度 |
| --- | --- | --- | --- |
| `result` | string | `"0"`=成功 | 多源一致 |
| `ver` | int | 版本号（样例 2） | 单源 |
| `existflag` | string | `"0"`=该学号未绑定任何房间；`"1"`=**单房间**（房间字段直接平铺在 body 上，无 `roomlist`）；`"2"`=多房间（`roomlist` 数组） | 多源一致 |
| `message` | string | 「操作成功」 | 多源一致 |
| `roomfullname` | string | 房间全路径（`校区_楼栋_层_房间号` 或 `校区楼栋-房间号`，**格式因校而异**） | 多源一致 |
| `roomverify` | string | **房间凭证**，后续所有接口必传；格式 `{area}-{building}--{level}-{room}`（中间 `--` 表示 unit 为空） | 多源一致 |
| `detaillist[]` | array | 该房间的表计列表（一个房间可能有电表/冷水表/热水表多个） | 多源一致 |
| `detaillist[].businesstype` | string | 业务类型：`0`=电、`1`=冷水、`2`=热水（JustaSage 映射）；CloudPayment 的 `getRoomState` 用 `businesstype=2` 表示电类缴费项目（**两套语义，别混**） | 多源一致（但两套语义需注意） |
| `detaillist[].use` | string | **累计已用量**（度） | 多源一致 |
| `detaillist[].odd` | string | **剩余量**（度）——低电提醒就看它 | 多源一致 + 实测 |
| `detaillist[].status` | string | `"1"`=一般送电，否则一般断电（zuwei522 的映射） | 单源 |
| `roomlist[]` | array | 多房间时的列表，元素结构同上（`roomfullname` / `roomverify` / `detaillist`） | 多源一致 |

### 4.3 `h5_getstuindexpage` 的 body

| 字段 | 类型 | 含义 | 置信度 |
| --- | --- | --- | --- |
| `modlist[]` | array | 表计列表（电表/水表） | 多源一致 |
| `modlist[].odd` | number | **剩余量**（预付费电表=度） | 多源一致 |
| `modlist[].todayuse` | number | 今日用量（度） | 多源一致 |
| `modlist[].devicename` | string | 表具名称，如「电控」 | 多源一致 |
| `modlist[].mac` | number | 表具编号（如 78063） | 多源一致 |
| `modlist[].blunum` | string | 蓝牙编号（`078063`，补零） | 单源 |
| `modlist[].accode` | number | 缴费项目代码（样例 51101 = 电费） | 多源一致 |
| `modlist[].price` | number | **电价（元/度）** | 单源（Jursin README） |
| `modlist[].bussnesstype` | number | 业务类型（注意拼写少一个 i；0=电） | 多源一致 |
| `modlist[].status` | number | 1=送电/0=断电 | 单源 |
| `modlist[].isshowpay` | number | 是否显示充值按钮 | 单源 |
| `modlist[].sumbuy` | number | 累计购电量（度）——**推测** | 推测 |
| `modlist[].sumsub` | number | 累计补贴量/补贴额——**推测**（样例 17994.57，与 `isshowsubsidy` 配合） | 推测 |
| `modlist[].totalamount` | number | 总金额（样例 0，含义未确认） | 推测 |
| `modlist[].weekuselist[]` | array | **近 7 天每日用量**：`date`/`daydate`=`MM-DD`，`weekday`=中文星期，`use`/`dayuse`=当日用量（度），`formatweek.time`=当日 0 点 epoch ms，`timezoneoffset=-480`（东八区） | 多源一致 |
| `modlist[].monthuselist[]` | array | 历史月度：`yearmonth`=`"YYYY.MM"`，`monthuse`=当月用量（度） | 多源一致 |
| `roomfullname` / `roomnum` / `roomverify` | string | 房间信息（`roomnum` 是纯房间号） | 多源一致 |
| `result` | string | `"0"`=成功 | 多源一致 |
| `message` | string | 「操作成功」 | 多源一致 |
| `subornot` / `isexpplan` / `isshowsubsidy` | string | 补贴/套餐开关，含义未完全确认 | 推测 |

### 4.4 单位与坑（重要）

| 项 | 结论 | 置信度 |
| --- | --- | --- |
| `odd` | 预付费电表：**度（kWh）**；金额表（费控）可能是**元**——未在公开来源见到「元」的案例，但 `quantityunit` 字段的存在说明单位是服务端配置的 | 度=多源一致；元=推测 |
| `use`（getbindroom） | 累计**已用**电量（度），不是账户余额 | 多源一致 |
| `quantity`（CloudPayment） | 剩余量，单位看同响应 `quantityunit`（电=度，水=吨） | 多源一致 |
| 余额「元 vs 分」 | 完美校园电费体系是**预付费电量制**（剩余多少度），不直接返回「元」。`price` 给元/度，可自己换算：金额 ≈ 剩余度数 × price | 多源一致 |
| 充值金额 `payamt` | **单位是分**（`int(round(元*100))`） | 多源一致 |
| `businesstype` | getbindroom 里 0=电、1=冷水、2=热水；CloudPayment 里 `businesstype=2` 是「电类缴费项目」的固定值 —— **两套语义** | 多源一致 |
| 负数 | 未观察到负值；`odd < 0` 是否代表欠费**未确认** | 推测 |
| 时间格式 | `timestamp`=`yyyyMMddHHmmss`(+`000`)；`weekuselist.date`=`MM-DD`（无年份，跨年需注意）；`formatweek.time`=epoch ms；`monthuselist.yearmonth`=`YYYY.MM`；`getusedetail.yearmonth`=`YYYY-MM`；`gettimeusedetail`=`YYYY-MM-DD` | 多源一致 |
| 时区 | `timezoneoffset: -480` = UTC+8 | 多源一致 |

---

## 5. 失败形态 / 错误码

### 5.1 SWAEServlet / SWAEEncryptServlet

| 场景 | HTTP | 响应长相 | 判定/处置 | 置信度 |
| --- | --- | --- | --- | --- |
| 正常 | 200 | `result_="true"`, `body` 里 `result:"0"` | OK | 实测 |
| **参数格式错误**（空 account / 非法 roomverify 等） | 200 | 外层 `result_="true"` 但 `body` 是错误包：`{"_message":"调用接口失败","code_":8099,"result_":false,"exception_":"调用接口失败,body格式错误","body":"","message_":"调用接口失败"}` | 检查 account 是否为空、roomverify 格式 | **实测**（FJTCM 769 空参 / 假参） |
| **学校未开通/未适配**（推测） | 200 | 同上 8099（对照学校同假参返回 `existflag:"0"` 正常包） | 换产品线 | **实测 + 推测** |
| 学号未绑定房间 | 200 | `body` 里 `{"result":"0","ver":2,"existflag":"0","message":"操作成功"}`（无 roomlist） | 去 App 里绑定房间，或换学号 | 实测（759 对照）+ 多源一致 |
| 业务失败 | 200 | `body.result != "0"`，看 `body.message` | 打印原始包 | 多源一致 |
| 外层失败 | 200 | `result_ != "true"`，看 `message_` | 打印原始包 | 多源一致 |
| 频率限制/风控 | 200 | 响应文本含「频繁」（有项目据此 `sleep 60` 重试） | 降频（≥3–5 秒/次）、退避重试 | 单源（lswlc33 项目） |
| 网络/证书错误 | — | 连接失败 | 检查网络；接口域名是 https | 常识 |

### 5.2 CloudPayment

| 场景 | 响应 | 判定 | 置信度 |
| --- | --- | --- | --- |
| 缺 Referer / 缺第 4 步上下文 / 无效 token | 200，`RspBaseVO [code=ERROR, msg=系统繁忙，请稍后重试]` | 与真·系统繁忙**完全一样**，只能靠重试/重登录区分 | 多源一致 |
| token 无效 | 200 HTML，`payprolist` 为 `null` | 唯一可靠探针 = 缴费项目列表非空 | 单源（证据强） |
| 成功 | `{"returncode":"100","returnmsg":"SUCCESS","quantity":"…","quantityunit":"度","canbuy":"true"}` | OK | 多源一致 |

### 5.3 App 登录

| `code_` | message | 含义 |
| --- | --- | --- |
| 0 | 登录成功 | OK |
| 4 | 该手机号未注册完美校园 | 账号不存在/未注册 |
| 5 | 您正在新设备上使用完美校园，请使用验证码进行验证登录 | 需短信绑定 deviceId |
| 5 | 密码错误,您还有N次机会! | 密码错（**与上同码，不能只看码**） |
| 6 / 800114003 | 短信验证码错误 | 验证码错 / 没带 543 后缀 |

【多源一致】

---

## 6. 如何拿到 schoolId / 楼栋 / 房间

### 6.1 学校编码（customercode / school_id）

- **权威原始来源**：`https://open.17wanxiao.com/kdword_fl02.html`（新开普开放平台「学校编码」表，2025-06 更新）。该页现已 404，但被多处镜像：
  - Apifox 共享文档镜像：`https://s.apifox.cn/ad1e6ba6-6cd2-4b6e-88b2-a1ca1577e14c/doc-5123374`（含完整表，Ctrl+F 可搜）【多源一致】
  - GitHub `zuwei522/perfect-campus_electricity-alert/school-list.md`（同名表）【多源一致】
  - GitHub `stmtc233/WanXiao-Elec-TgBot/schools/schools.csv`（**2903 条**，含 >4 位编码，如 1769、2001769；机器可读最佳）【单源】
  - GitHub `DragonYH/astrbot_plugin_wanxiao_electricity/school_codes.json`（377 条精选）【单源】
- **福建中医药大学 = `769`**（多源一致：Apifox 表、school-list.md、schools.csv、school_codes.json 四处一致）
- 同城参考：福州大学 763、福建师范大学 766、福建医科大学 767、福建师范大学协和学院 771、福建农林大学（未在表内确认）
- 编码段不连续、可大于 4 位（有 1005/1506/2439/1769/2001769 等），**枚举很危险**（有项目做「搜校」扫描，默认 6 req/s、全量约 35 分钟，并明确说明会被风控）。不建议枚举。【多源一致】

### 6.2 楼栋 / 房间（roomverify）

优先级从高到低：

1. **`getbindroom` 直接返回**（推荐）：只要学号在完美校园「智能水电」里绑定过房间，就能拿到 `roomverify`。【多源一致 + 实测】
2. **CloudPayment `getRoom.do` 逐层枚举**：`optype=1` 校区 → `2` 楼栋 → `3` 单元/楼层 → `4` 房间；`optype=4` 返回的 `id` 就是 roomverify。【多源一致】
3. **App 内绑定流程**（用户手动）：完美校园 App → 首页「智能水电」→ 右上角「…」→「我的房间」→ 选择校区/楼栋/单元/楼层/房间 → 绑定；然后首页就能看到剩余电量、今日用电、使用趋势、充值记录。【多源一致（内蒙古师大后勤通知、搜狐 2024 文章等）】
4. **从 App 抓包反推**：打开「智能水电」时的 `AloneEntrance` 请求，其响应头 `Location` 里带 `customerid`（即学校编码）；或者解 `SWAEEncryptServlet` 请求体（见 §2.2）得到 customercode/account。【单源】
5. **H5 URL**：`https://xqh5.17wanxiao.com/userwaterelecmini/index.html#/?params=…` 的 `params` 里含身份信息（经 `loginCheck` 解出）。【单源】

**roomverify 格式**：`{area}-{building}--{level}-{room}`（中间的 `--` 是「unit 为空」留下的分隔符）。真实样例：
`99-5--20-24603`、`101-16--204-12619`、`101-07--112-308`、`4-246-254--2204`、`1-6--56-6415`、`99-12--33-404`。【多源一致】

> 注意：不同学校/不同代接口的 roomverify 语义一致，但 **`command` 不同**（`JBSWaterElecService` / `OWNWaterElecService` / 从 loginCheck 动态取）。如果一个 command 报错，换另一个再试。【多源一致】

### 6.3 判断「我们学校走哪条产品线」

jialiangh 项目给出的判据（实用）：

1. 先问老引擎 `getbindroom`：
   - 正常返回 `existflag:"0"`/房间列表 → 学校走 **A/A2**，直接用 SWAEServlet。
   - 返回 8099/异常且对照学校正常 → 学校可能不在 A 线，转 CloudPayment（B）或学校自建平台。
2. CloudPayment 能查到「用电支出」缴费项目 → 学校走 **B**，需要有 App 登录态。
3. 学校用「今日校园」等第三方门户 → 可能两条都不走（FJTCM 就是这种情况，见 §7）。

---

## 7. 福建中医药大学（FJTCM）专项

### 7.1 公开信息时间线

| 时间 | 内容 | 来源 |
| --- | --- | --- |
| 2017-06 | 学生服务中心门口有**自助查询电费机**：输入楼号/楼层/房间号查购电记录、用电记录；交电费仍在宿舍楼一楼 | 搜狐 2017 |
| 2017-09 | 新生用**完美校园 App** 绑定校园卡（卡号=学号）、充值（龙支付） | 福中医/乐活杏苑公众号 |
| 2018-09 | 校园卡充值「以圈存机或完美校园 App 充值为主」，绑定需姓名+学工号+消费密码 | 福中医后勤处 |
| 2021-07 | **今日校园新增「购电查询」服务**：今日校园 → 公共服务 → 购电查询 → 填楼栋号+房间号 → 查「用电总量 / 购电总量 / 可用电量」（旗山校区） | 福中医党委宣传部公众号 |
| 2022-08 | 信息化 FAQ：「如何查询水电余额？打开今日校园 → 公共服务 → 购电查询，填楼栋号及房间号」 | 福中医现代教育技术中心 |
| 2025-09 | 学生公寓水电费计取说明：电费 0.58 元/度、水费 3.03 元/吨（**该篇微信正文被风控拦截，仅取到搜索摘要，未全文核实**） | 微信文章（摘要） |

**结论**：福中医的电费查询公开入口是 **今日校园「购电查询」**，不是完美校园「智能水电」；完美校园在福中医的角色是**校园卡**。【多源一致】

### 7.2 我的实测（2026-11-05）

探活记录见 §9。核心结果：

| 请求 | 学校编码 | 参数 | 响应 `body` |
| --- | --- | --- | --- |
| `getbindroom` | **769（FJTCM）** | `account=""`（空参） | `{"_message":"调用接口失败","code_":8099,"result_":false,"exception_":"调用接口失败,body格式错误","body":"","message_":"调用接口失败"}` |
| `h5_getstuindexpage` | 769 | 假 roomverify + 假学号 | 同上 8099 |
| `getbindroom` | **759（桂电北海，开源项目实测可用）** | 假学号 `0000000` | `{"result":"0","ver":2,"existflag":"0","message":"操作成功"}` ← 正常业务包 |
| `getbindroom` | 769 | 假学号 `0000000` | 8099（与空参同） |

**解读**：对照学校用假学号会正常进入业务层并返回「未绑定」（existflag 0），而 769 连业务层都没进（8099 body 格式错误）→ **769 侧的水电接口配置与标准实现不同/未开通**，不是「学号不存在」的问题。【实测 + 推测】

### 7.3 给 FJTCM 的可行路线（按性价比排序）

| 级别 | 路线 | 可行性 | 需要用户做什么 |
| --- | --- | --- | --- |
| **A（最可能成功）** | 抓「今日校园 → 公共服务 → 购电查询」的包，逆出学校自己的电费接口，再包一层脚本 + 低电提醒 | 高（这是学校当前官方入口） | 手机连代理（Fiddler/Reqable/Stream）抓一次查询请求；把抓到的请求（脱敏）发我们 |
| **B（先花 10 分钟验证）** | 完美校园 App 里看有没有「智能水电」入口；有就绑定房间后抓包，再套本文 A/A2 接口 | 中低（学校可能没开） | 登录完美校园 → 全部应用 → 找「智能水电」→ 看能否绑定宿舍房间 |
| **C（兜底）** | 手动查：今日校园购电查询页面，人工看剩余电量；或宿舍楼一楼/自助机 | 高但原始 | 无 |
| D | 完美校园 CloudPayment（App「缴费 → 用电支出」） | 低（福中医的缴费项目大概率没有「用电支出」） | App 里看「缴费」页是否有用电支出项目 |

> 如果用户抓到了「今日校园 购电查询」的请求，**请新开一个任务重新做协议解析**（它很可能不是新开普体系，参数模型完全不同）。本文的 A/A2 接口只能作为「完美校园路线」的参考实现。

---

## 8. 可直接照抄的代码

### 8.1 Python（零第三方依赖，urllib）

```python
# -*- coding: utf-8 -*-
"""完美校园智能水电查询：无鉴权版（SWAEServlet）
用法： python wx_elec.py <学校编码> <学号>
注意： 只查自己账号；请求间隔 >= 3 秒；接口随时可能变。
"""
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime

BASE = "https://xqh5.17wanxiao.com/smartWaterAndElectricityService/SWAEServlet"
HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "X-Requested-With": "com.newcapec.mobile.ncp",
    "Origin": "https://xqh5.17wanxiao.com",
    "Referer": "https://xqh5.17wanxiao.com/userwaterelecmini/index.html",
    "User-Agent": ("Mozilla/5.0 (Linux; Android 14; REP-AN00) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/127.0.6533.103 Mobile Safari/537.36 Wanxiao/5.8.6"),
}


def call(cmd: str, account: str, customercode: str, command: str = "JBSWaterElecService", **kw):
    """调 SWAEServlet；自动二次解析 body。"""
    param = {"cmd": cmd, "account": account,
             "timestamp": datetime.now().strftime("%Y%m%d%H%M%S") + "000", **kw}
    data = urllib.parse.urlencode({
        "param": json.dumps(param, ensure_ascii=False),
        "customercode": str(customercode),
        "method": cmd,
        "command": command,
    }).encode()
    req = urllib.request.Request(BASE, data=data, headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        outer = json.loads(r.read().decode("utf-8"))
    if outer.get("result_") != "true":
        raise RuntimeError(outer)
    body = json.loads(outer["body"])          # ← 关键：body 是字符串，要再 parse 一次
    return body


def list_rooms(account, customercode, command="JBSWaterElecService"):
    body = call("getbindroom", account, customercode, command)
    if str(body.get("existflag")) == "0":
        return []
    if str(body.get("existflag")) == "2" and body.get("roomlist"):
        return body["roomlist"]
    return [body]                              # existflag == "1" 时房间字段平铺


def room_detail(account, customercode, roomverify, command="JBSWaterElecService"):
    body = call("h5_getstuindexpage", account, customercode, command,
                roomverify=roomverify)
    mod = (body.get("modlist") or [{}])[0]
    return {
        "room": body.get("roomfullname"),
        "roomverify": body.get("roomverify"),
        "remain_kwh": mod.get("odd"),          # 剩余电量（度）
        "today_kwh": mod.get("todayuse"),      # 今日用电
        "price": mod.get("price"),             # 电价 元/度（部分学校有）
        "week": [(d.get("date"), d.get("dayuse")) for d in (mod.get("weekuselist") or [])],
        "month": [(m.get("yearmonth"), m.get("monthuse")) for m in (mod.get("monthuselist") or [])],
    }


def day_usage(account, customercode, roomverify, businesstype, start, end,
              command="JBSWaterElecService"):
    """区间日用量 start/end: 'YYYY-MM-DD'"""
    return call("gettimeusedetail", account, customercode, command,
                roomverify=roomverify, businesstype=str(businesstype),
                startdate=start, enddate=end)


if __name__ == "__main__":
    school, student = sys.argv[1], sys.argv[2]
    rooms = list_rooms(student, school)
    if not rooms:
        print("该学号未绑定房间（去完美校园 App『智能水电』里绑定）")
    for room in rooms:
        info = room_detail(student, school, room["roomverify"])
        print(json.dumps(info, ensure_ascii=False, indent=2))
```

### 8.2 curl 速查

```bash
# 1) 查绑定房间
curl -s 'https://xqh5.17wanxiao.com/smartWaterAndElectricityService/SWAEServlet' \
  --data-urlencode 'param={"cmd":"getbindroom","account":"<学号>"}' \
  --data-urlencode 'customercode=769' \
  --data-urlencode 'method=getbindroom'

# 2) 查单房间详情
curl -s 'https://xqh5.17wanxiao.com/smartWaterAndElectricityService/SWAEServlet' \
  --data-urlencode 'param={"cmd":"h5_getstuindexpage","roomverify":"<roomverify>","account":"<学号>","timestamp":"20261105223000000"}' \
  --data-urlencode 'customercode=769' \
  --data-urlencode 'method=h5_getstuindexpage' \
  --data-urlencode 'command=JBSWaterElecService'

# 3) 区间日用量
curl -s 'https://xqh5.17wanxiao.com/smartWaterAndElectricityService/SWAEServlet' \
  --data-urlencode 'param={"cmd":"gettimeusedetail","roomverify":"<roomverify>","account":"<学号>","businesstype":"0","startdate":"2026-11-01","enddate":"2026-11-05"}' \
  --data-urlencode 'customercode=769' \
  --data-urlencode 'method=gettimeusedetail' \
  --data-urlencode 'command=JBSWaterElecService'

# 4) 旧 CloudPayment 老接口（2019 无鉴权形态，仅作存活探测；现需 token）
curl -s 'http://h5cloud.17wanxiao.com:8080/CloudPayment/user/getRoom.do?payProId=1567&schoolcode=769&optype=1&areaid=0&buildid=0&unitid=0&levelid=0&businesstype=2'
```

### 8.3 低电提醒伪代码（给 task-3 参考）

```
每 N 小时（建议 >=3h，夜间不跑）:
  rooms = getbindroom()
  for r in rooms:
      d = h5_getstuindexpage(r.roomverify)
      if d.remain_kwh < THRESHOLD: 推送("剩余 {odd} 度，低于阈值")
  持久化 last_reading，用于算「日均用电」和「预计耗尽时间」
  失败退避：连续失败 3 次 → 暂停 1 小时；命中「频繁」→ sleep 60s 再试一次
```

---

## 9. 探活记录（2026-11-05，共 5 次请求）

规则：只发空参/假参、间隔 ≥4 秒、不携带任何真实个人信息、不尝试登录。

| # | 时间(约) | 请求 | 结果 |
| --- | --- | --- | --- |
| 1 | 22:20 | `POST SWAEServlet` `param={"cmd":"getbindroom","account":""}` `customercode=769` `method=getbindroom` | 200；`{"code_":0,"sign":"40AFD174B2BEB3AC","result_":"true","body":"{\"_message\":\"调用接口失败\",\"code_\":8099,...\"exception_\":\"调用接口失败,body格式错误\"...}","message_":"获取成功！"}` |
| 2 | 22:20 | `POST SWAEServlet` `param={"cmd":"h5_getstuindexpage","roomverify":"0-0-0--0","account":"0000000","timestamp":"20261105222053000"}` `customercode=769` `method=h5_getstuindexpage` `command=JBSWaterElecService` | 200；同上 8099 包 |
| 3 | 22:20 | `POST SWAEServlet` `param={"cmd":"getbindroom","account":"0000000"}` `customercode=759`（对照：桂电北海） | 200；`{"code_":0,"sign":"59FF0B794BC4331C","result_":"true","body":"{\"result\":\"0\",\"ver\":2,\"existflag\":\"0\",\"message\":\"操作成功\"}","message_":"获取成功！"}` |
| 4 | 22:21 | `POST SWAEServlet` `param={"cmd":"getbindroom","account":"0000000"}` `customercode=769` | 200；8099（与 #1 相同 sign `40AFD174B2BEB3AC`） |
| 5 | 22:21 | `GET http://h5cloud.17wanxiao.com:8080/CloudPayment/user/getRoom.do?...&schoolcode=769&optype=1...` | HTTP **200**（响应体为压缩字节，未解码）→ 仅证明旧域名仍存活；旧接口是否仍可用**未验证** |

观察：
- 服务端对 `customercode` 不同会返回不同 `sign`（769→`40AFD174B2BEB3AC`，759→`59FF0B794BC4331C`），同一 school 不同请求 sign 相同 → sign 可能由学校编码派生，**不是**逐请求签名。【实测】
- 参数错误/学校配置缺失都被包成 HTTP 200 + 外层 `result_:"true"`，**只看 HTTP 状态码会误判为成功**。【实测】

---

## 10. 风险与合规提示

1. **只查自己账号**；不要替别人查、不要批量扫房间、不要扫学校编码（有项目因「搜校」被风控，且这属于越权探测）。
2. **接口随时会变**：2022 微信端改版、2024 加密版上线都说明这一点。脚本必须把「接口地址 / 命令名 / 字段名」放在适配层，失败时优雅降级。
3. **频率**：生产建议 ≥30–60 分钟一次；调试 ≥3–5 秒一次；命中「频繁」立刻退避。
4. **凭据安全**：App 登录的 `deviceId`、`session/token`、支付密码**绝不可**提交进 git / 发到群里；`config.json` 加 `.gitignore`。
5. **越权面已知**：老接口只凭「学校编码+学号」就能查任意绑定房间；`smallProgramUserAuth` 能凭「学号+学校编码」查出真实姓名。发现这类缺陷的正确做法是反馈给学校网络中心，而不是利用。
6. **充值**不要在自动脚本里做（涉及支付密码与真实资金）。

---

## 11. 来源清单

**必读（任务指定）**
- doupoa：《完美校园电费h5查询接口解析与应用》 https://doupoa.site/archives/510/完美校园电费h5查询接口解析与应用 （2024-09）
- doupoa：《完美校园电费查询新接口请求原理解析》 https://doupoa.site/archives/337 ｜CSDN 镜像 https://blog.csdn.net/doupoa/article/details/125192380 （2022-06）

**接口文档 / 参数表**
- Apifox 共享文档《完美校园智能水电API》：https://s.apifox.cn/ad1e6ba6-6cd2-4b6e-88b2-a1ca1577e14c/folder-41557094
  - 获取指定房间水电：https://s.apifox.cn/ad1e6ba6-6cd2-4b6e-88b2-a1ca1577e14c/api-213986424
  - 获取账号所绑定的所有房间：https://s.apifox.cn/ad1e6ba6-6cd2-4b6e-88b2-a1ca1577e14c/api-214004061
  - 学校代码表：https://s.apifox.cn/ad1e6ba6-6cd2-4b6e-88b2-a1ca1577e14c/doc-5123374
- 旧式接口链路（2019，湖南工业大学）：https://blog.csdn.net/weixin_43999566/article/details/101755168
- 全校电费采集（学校一卡通平台，非完美校园）：https://juejin.cn/post/7271103274064068665

**开源实现（本地已克隆到 `research/_raw/repos/`，可直接看源码）**
- `zuwei522/perfect-campus_electricity-alert` —— 低电提醒 Shell，`getbindroom` 最小实现 https://github.com/zuwei522/perfect-campus_electricity-alert
- `Jursin/wanxiao-electric-apis` —— 最全命令清单（getbindroom / h5_getstuindexpage / getusedetail / gettimeusedetail）+ SWAEEncryptServlet 解密 https://github.com/Jursin/wanxiao-electric-apis
- `jialiangh/campus-electricity-monitor` —— 两代接口对照 + CloudPayment 五步链 + App 登录/风控细节（`docs/接口说明.md` 强烈推荐）https://github.com/jialiangh/campus-electricity-monitor
- `stmtc233/WanXiao-Elec-TgBot` —— Go 版：goPay 充值 + 学校编码全表 + smallProgramUserAuth https://github.com/stmtc233/WanXiao-Elec-TgBot
- `JustaSage/ZCST_FEE_Bot` —— loginCheck + SSO 落地页 + AES(1234567812345678) 解密 https://github.com/JustaSage/ZCST_FEE_Bot
- `chuzong886/wanmeixiaoyuandianfeiyujin` —— SWAEEncryptServlet 加密实现（PHP）https://github.com/chuzong886/wanmeixiaoyuandianfeiyujin
- `ReaJason/17wanxiaoCheckin` / `yaochijuzi/17wanxiaoCheckin` —— App 登录协议（RSA/3DES/campusSign/543 验证码）https://github.com/ReaJason/17wanxiaoCheckin
- `Andtun02/school-charge-open`、`Zuizhuban/wanxiao-electricity-alert`、`DHKun/xzmu-electricity-monitor` —— CloudPayment 实现/踩坑 https://github.com/Andtun02/school-charge-open
- `Illustar0/ZZU.Py` —— 郑大版「一卡通/剩余电量/充值」客户端（CAS→tid→accessToken，45 分钟刷新，room 格式说明）https://github.com/Illustar0/ZZU.Py
- `suiren0219/astrbot_plugin_dorm_power` —— 搜校风控/限速实践 https://github.com/suiren0219/astrbot_plugin_dorm_power

**福建中医药大学**
- 福中医现代教育技术中心《信息化常见问题解答宣传册》（2022-08）https://metc.fjtcm.edu.cn/2022/0829/c1090a25617/page.htm
- 福中医党委宣传部《今日校园新增"购电查询"服务》（2021-07）https://mp.weixin.qq.com/s/bnEa7CE5U5UFVLW6B2Szxg
- 福中医后勤处《关于校园卡充值业务办理须知》（2018-09）https://hq.fjtcm.edu.cn/2018/0903/c1018a23505/page.htm
- 搜狐《【查电费？自己搞定！】自助查询电费机入驻福中医！》（2017-06）https://www.sohu.com/a/149810862_757850
- 福中医《信息化带你一键感知福中医》（2021-09，提到今日校园提供「购电查询、一卡通充值」）https://mp.weixin.qq.com/s/21KpR135a8Gizh0M1n1baQ
- 福中医《学生公寓水电费计取的情况说明》（2025-09，电 0.58 元/度、水 3.03 元/吨；仅取到搜索摘要，正文被风控拦截）http://mp.weixin.qq.com/s?__biz=MzkzOTM3ODkzMQ==&mid=2247485206&idx=1&sn=1afa5be36fbb198ca952282063d56af4
- 福中医《水电管理规定（修订）》（2024-10）https://hq.fjtcm.edu.cn/2024/1030/c1014a100184/page.htm

**绑定流程参考（其他学校官方通知）**
- 内蒙古师范大学后勤《关于盛乐专家公寓区联网水电系统开通缴费的通知》（2021-05，完美校园「智能水电」绑定/充值/消费记录）http://hqfw.imnu.edu.cn/info/1020/1392.htm
- 搜狐《完美校园可线上缴水电费、查明细，你知道吗？》（2024-09，绑定房间/使用趋势/充值记录 UI 路径）https://www.sohu.com/a/806886161_358114

---

## 12. 未解问题（留给后续任务）

1. **FJTCM「今日校园 购电查询」的后端接口**：域名/参数/鉴权全部未知。需要用户抓一次包（最优先）。
2. **充值记录**：完美校园没有公开接口；若必须做，需抓 App「充值记录」页。
3. **`odd` 在金额表学校的单位**：未找到公开案例。
4. **2022 微信端新接口的域名/参数**：原文章节只有流程描述，URL 在截图中不可得。
5. **schoolId=769 是否真的未开通**：只能确认「标准 SWAEServlet 口径返回 8099」；如果用户能在完美校园 App 里看到「智能水电」并成功绑定房间，则应重新测（用真实学号由用户自己测）。
