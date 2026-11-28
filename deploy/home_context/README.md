# Android 工作台内容服务

`home_context_app.py` 提供 Android 工作台使用的天气和公开文案。任务 AI 服务现有路由和请求方式沿用原有契约。

## 本地联调

从工作区根目录启动本机 HTTP 服务。`--state-dir` 指向存放本地文案批次的目录。可先使用空目录验收离线降级。

```powershell
python -B web/deploy/home_context_app.py serve --state-dir android-class-tools/artifacts/home-context/published-review --regions android-class-tools/app/src/main/assets/home_regions.tsv
adb -s <emulator> reverse tcp:8097 tcp:8097
```

调试包使用 Gradle 属性 `ct.homeContextBaseUrl=http://127.0.0.1:8097`。Android 正式包和鸿蒙默认访问 `https://tool.furina.fun`。Android 可用同一 Gradle 属性覆盖地址。

天气服务从 `CT_QWEATHER_API_HOST` 读取和风分配的主机名，密钥由系统凭据 `qweather-api-key` 或本机进程环境 `CT_QWEATHER_API_KEY` 提供。文案生成使用系统凭据 `deepseek-api-key` 或 `DEEPSEEK_API_KEY`。已有任务 AI 的 systemd 凭据可按同一方式装载。运行时只记录批次成功、已有当日尝试或失败。用已配置的凭据执行一次本地生成：

```powershell
python -B web/deploy/home_context_app.py generate --state-dir android-class-tools/artifacts/home-context/published-review
```

次日之前相同状态目录只接受一次生成尝试。两个公开主题各检索一次、各读取最多一篇来源文章，再分别调用 JSON 生成和文本审核。模型只接收公开素材及待审核文案。失败保留上次有效批次，最长使用 72 小时。

## 卡片热更

Android 与鸿蒙共用正式域名的 `GET /home-context/content/v1`。同一接口每天自动更新联网文案，并返回独立配置的 `englishTypography`。英文始终在上方，`large` 是默认大字号，`extraLarge` 使用更大的主句字号，中文译文保持在下方。支持配置的客户端在工作台可见且开启联网内容时最多每 15 分钟拉取一次，同一文案批次可收到字号调整。无有效缓存时使用客户端默认字号。

修改字号只更新 ECS 状态目录中的 `presentation.json`，每日文案生成保留此文件，无需重新打包、重启服务或重新配置客户端。在 web 仓运行以下命令切到更大字号，切回时将最后一个参数改为 `large`。命令回读正式 HTTPS 接口，回读失败时恢复原文件。

~~~powershell
python -B deploy/ecs_home_context.py --english-typography extraLarge
~~~

## 接口和部署模板

- `GET /home-context/content/v1` 返回 `generatedAt`、`expiresAt`、`entries`。条目包含稳定 ID、主题、语气、正文和可信来源。
- `GET /home-context/weather/v1?region=minhou` 读取指定地区的和风实时天气。地区 ID 使用 Android 内置地名表，`minhou` 固定查询北纬 26.15°、东经 119.15°。响应包含地区、有效时间、现象、温度、可用日出日落与归因。来源缺失或失效返回 503。
- ECS 服务监听 127.0.0.1:8097。Caddy 仅转发这两条只读路径。systemd 按北京时间 06:00 触发 `class-tools-home-context-daily.service`。`qweather-api-key` 由服务器的系统凭据目录提供，天气未配置时继续提供有效文案。

在 web 仓执行 `python -B deploy/ecs_home_context.py --check-bundle` 核对部署包。经授权启用或更新时运行 `python -B deploy/ecs_home_context.py`。可以用 `--reviewed-batch` 上传仍有效的复核批次作为首批内容。脚本复用 ECS 云助手和现有服务端凭据，备份同源路由和涉及的文件，校验配置及 HTTPS 后再启用定时任务。失败时恢复备份。

[DeepSeek 搜索与读取](https://api-docs.deepseek.com/guides/search/) · [DeepSeek 内容审核](https://api-docs.deepseek.com/guides/safety/) · [和风实时天气](https://dev.qweather.com/docs/api/weather/weather-current/)
