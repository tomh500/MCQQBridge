# MCQQBridge 2.0

QQ 官方机器人与 Minecraft 群服互通框架。Java 包与构建 Group ID 为 `top.luotiany1`。

## 组件和要求

- `mcqq`：Python 3.11+、官方 QQ Bot SDK、aiohttp；提供绑定、身份关联、消息队列和媒体服务。
- `plugin`：BungeeCord 代理插件 MCQQBridge；聊天需要 BungeeChat，基岩关联需要 Floodgate。
- `spigot`：Spigot 1.12.2+ 子服插件 MCQQSpigot；保留 `/said`，支持按群注册命令，提供异步存取接口。
- `fabric`：可选图片客户端，[通用 Fabric 源码与构建说明](fabric/universal/README.md)；26.2、26.3 为重点支持版本，旧版为 legacy support。Forge 和 NeoForge 原生支持正在开发。

首次使用复制 `settings.example.json` 为 `settings.json`，填写自己的 QQ app_id、app_secret 和两个不同的随机服务 token（各至少32字符），安装 requirements.txt 后分别运行 `python -m mcqq.service` 与 `python -m mcqq.bot`。配置路径可由 `MCQQ_SETTINGS` 指定，相对路径以配置文件目录为基准。代理的 service-url 和 proxy-token 必须匹配；远程 API 使用 HTTPS 或 SSH 隧道。不要公开凭据、数据库和签名私钥。

公开模板没有任何服主凭据、固定群号或默认互通子服。机器人需要自行申请官方消息权限和主动推送额度。

## 功能开关

代理 `config.yml` 的 `enabled` 是旧版兼容的群白名单开关，默认 false；推荐使用 `features.whitelist: true/false` 覆盖它。关闭白名单后，QQ聊天功能仍可独立开启。`chat-bridge.enabled` 控制代理聊天，`chat-bridge.servers` 列出允许互通的真实子服名称。开启白名单要求代理正版验证。配置错误时保持拒绝新登录的策略。控制台 `/mcqq reload`（兼容 `/qqwl reload`）重载代理配置。

子服 `features.chat` 控制发送功能。机器人 `features.private_ai` 默认 false；启用后额外配置私有 Afterglow 文件。`launcher_groups` 默认空，只有显式映射的群允许引导器验证。

## 多群路由和名称

`allowed_groups` 列出授权 group_openid，机器人 `/本群ID` 可获取；数字QQ群号不能用于消息路由。`chat_bridge.inbound_groups` 指定接收到游戏的群，必须属于 allowed_groups；空数组禁止接收，省略兼容旧行为。`chat_bridge.group_aliases` 为 group_openid 到显示别名的映射。

群标签优先采用别名，再尝试官方群信息接口获取群名；无接口权限时降级显示 group_openid。名称缓存一小时，失败缓存五分钟。名称不决定授权范围，未列入接收范围的群不会转发。

`/said 内容` 向所有授权群发送，并在允许的游戏子服广播。子服配置 `group-commands: {friends: "OPENID_A"}` 后，`/friends 内容` 只发送到目标群，同时在游戏内广播；重启生效。命令不能覆盖已有命令，权限为 mcqq.said。目标群仍需在机器人授权列表中。重复空格和标点保留，命令文本不会作为服务端命令执行。

## 配置与数据存取

子服 `SaidPlugin.storage()` 暴露统一异步 `get(key)` / `put(key,value)` 接口，null 表示删除，返回 CompletableFuture。键允许字母数字、下划线、冒号、斜线和连字符，最大190字符。数据库调用在独立线程执行；调用方应将 Bukkit 操作调回主线程。

`storage.type` 可选 yaml（默认）、sql、mongodb。SQL URL 留空使用本地 SQLite；也可填写 jdbc:mysql://host/database 或 jdbc:postgresql://host/database，用户名和密码单独配置。MongoDB 填写 storage.mongodb.uri 和 database。SQL 使用 mcqq_settings 表，MongoDB 使用 settings 集合，YAML 使用插件目录 data.yml。切换后端不会自动搬迁已有数据。机器人绑定与队列仍由机器人 SQLite 管理，代理玩家聊天偏好保存在代理目录；Spigot 数据接口不替代这些数据源。

默认配置从 JAR 生成至用户插件目录，不覆盖已存在配置；词库首次复制至代理数据目录，服主可修改，并通过重载生效。word-filter.enabled 控制过滤，red/yellow 提供额外正则。修改后应自行验证规则性能。

## 构建与升级

代理运行 plugin/build.ps1；子服使用 Maven 3.9+ 执行 `mvn -f spigot/pom.xml package`，数据库驱动随子服 JAR 打包。源码构建需要服务器根目录 core 下的 BungeeCord.jar、spigot-1.12.2.jar 和 proxy 下的 BungeeChat JAR；Maven 可用 `-Dmcserver.root=绝对路径` 指定服务器根目录。输出分别为 mcqq-bridge-2.0.0.jar、mcqq-spigot-2.0.0.jar。

升级先备份并正常停止服务器，删除旧 qq-whitelist 和 mcqq-said JAR，放入新 JAR。代理首次启动自动复制 QQWhitelist 数据目录到 MCQQBridge；旧目录保留备份。子服旧 MCQQSaid 配置需要复制到 MCQQSpigot。切勿同时加载新旧插件。保留机器人 settings.json、bridge.json、数据库和服务器上的签名密钥。

本项目提供源码和构建包；对外发布前应遵循所含第三方库和词库的许可。测试命令：`python -m unittest discover -s tests`，代理真实启动测试为 `python tests/proxy_smoke.py`。

## 独立 Python 发布包

安装 `pip install mcqq_bridge-2.0.0-py3-none-any.whl`（将来发布到包索引后可按包名安装）。在任意用户工作目录运行 `mcqq init --config ./settings.json` 生成空凭据模板，填好配置后分别运行 `mcqq api --config ./settings.json` 和 `mcqq bot --config ./settings.json`。也支持 `python -m mcqq`。安装包只包含 mcqq 库、配置模板和元数据；不包含部署脚本、私有配置、数据库、日志或签名密钥。库可通过 `mcqq.service.create_app(config)` 嵌入 aiohttp 服务。

## License

项目原创代码采用 Apache License 2.0。第三方依赖遵循各自许可。公开源码不分发网易敏感词数据集，过滤功能默认关闭；如自行启用，需将适配格式的 G79SensitiveWords.json 和 X19SensitiveWords.json 放入代理数据目录并遵守数据集许可。Minecraft、BungeeChat 和 Floodgate 需要服主单独安装。
