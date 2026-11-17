# MCQQBridge 2.0

QQ 官方机器人与 Minecraft 群服互通框架。Java 包与构建 Group ID 为 `top.luotiany1`。

## 组件和要求

- `mcqq`：Python 3.11+、官方 QQ Bot SDK、aiohttp；提供绑定、身份关联、消息队列和媒体服务。
- `plugin`：BungeeCord 代理插件 MCQQBridge；聊天需要 BungeeChat，基岩关联需要 Floodgate。
- `spigot`：Spigot 1.12.2+ 子服插件 MCQQSpigot；保留 `/said`，支持按群注册命令，提供异步存取接口。
- `fabric`：可选图片客户端，[通用 Fabric 源码与构建说明](fabric/universal/README.md)；26.2、26.3 为重点支持版本，旧版为 legacy support。Forge 和 NeoForge 原生支持正在开发。

首次使用复制 `settings.example.json` 为 `settings.json`，填写自己的 QQ app_id、app_secret 和两个不同的随机服务 token（各至少32字符），安装 requirements.txt 后分别运行 `python -m mcqq.service` 与 `python -m mcqq.bot`。配置路径可由 `MCQQ_SETTINGS` 指定，相对路径以配置文件目录为基准。代理的 service-url 和 proxy-token 必须匹配；远程 API 使用 HTTPS 或 SSH 隧道。不要公开凭据、数据库和签名私钥。

公开模板没有任何服主凭据、固定群号或默认互通子服。机器人需要自行申请官方消息权限和主动推送额度。

## 运行拓扑

本仓库是源码、构建与发布框架，不绑定任何特定服务器、域名、群或 SSH 身份。生产环境可全部运行在一台 Linux 主机，也可将 Python 服务与 Minecraft 代理分开部署：

```text
QQ 开放平台 / QQ 群
          │ WebSocket（官方 Bot SDK）
          ▼
    mcqq.bot（机器人进程）
          │ HTTP + bot_token
          ▼
 mcqq.service（本地 API，默认 127.0.0.1:18765）
          │ HTTP + proxy_token
          ▼
 BungeeCord + MCQQBridge
          │ 插件消息 / 群聊队列
          ├── Spigot/Paper 子服 A
          └── Spigot/Paper 子服 B …
```

`settings.json` 只供 Python API 与机器人使用；BungeeCord 的 `plugins/MCQQBridge/config.yml` 需要使用相同的 `service-url` 和 `proxy-token`。每个子服安装 MCQQSpigot 后可用 `/said`（或 `group-commands` 中配置的别名）发送消息。不要把运行配置、SQLite 数据库、日志、备份、SSH 私钥或任何群 openid 提交到仓库。

### 推荐启动顺序

1. 从 `settings.example.json` 生成仅属于自己的 `settings.json`，填入 QQ 开放平台凭据与两枚不同的随机 token。
2. 启动 `python -m mcqq.service`，并确认 `http://127.0.0.1:18765/healthz` 返回成功。
3. 启动 `python -m mcqq.bot`，确认机器人在 QQ 平台上线。
4. 配置并启动子服，再启动 BungeeCord；BungeeCord 加载 MCQQBridge 后开始轮询聊天队列。

生产环境建议为 API 和 bot 分别创建服务管理器单元（如 systemd），让 bot 依赖 API；Minecraft 代理应在 API 健康检查成功后才启动。示例配置的群列表、互通子服列表与白名单功能默认关闭，需由服主按自己的实际环境显式开启。

## 功能开关

代理 `config.yml` 的 `enabled` 是旧版兼容的群白名单开关，默认 false；推荐使用 `features.whitelist: true/false` 覆盖它。关闭白名单后，QQ聊天功能仍可独立开启。`chat-bridge.enabled` 控制代理聊天，`chat-bridge.servers` 列出允许互通的真实子服名称。开启白名单要求代理正版验证。配置错误时保持拒绝新登录的策略。控制台 `/mcqq reload`（兼容 `/qqwl reload`）重载代理配置。

子服 `features.chat` 控制发送功能。机器人 `features.private_ai` 默认 false；启用后额外配置私有 Afterglow 文件。`launcher_groups` 默认空，只有显式映射的群允许引导器验证。

## 多群路由和名称

`allowed_groups` 列出授权 group_openid，机器人 `/本群ID` 可获取；数字QQ群号不能用于消息路由。`chat_bridge.inbound_groups` 指定接收到游戏的群，必须属于 allowed_groups；空数组禁止接收，省略兼容旧行为。`chat_bridge.group_aliases` 为 group_openid 到显示别名的映射。

`chat_bridge.outbound_groups` 独立指定接收游戏消息的群，也必须是 `allowed_groups` 的子集；空数组禁止发送，省略则兼容旧行为，发往所有授权群。定向群命令同样受此列表限制；不在列表中的目标会被拒绝。修改机器人配置后需重启 API 和 Bot。

群标签优先采用别名，再尝试官方群信息接口获取群名；无接口权限时降级显示 group_openid。名称缓存一小时，失败缓存五分钟。名称不决定授权范围，未列入接收范围的群不会转发。

`/said 内容` 向出站列表中的群发送，并在允许的游戏子服广播。子服配置 `group-commands: {friends: "OPENID_A"}` 后，`/friends 内容` 只发送到目标群，同时在游戏内广播；重启生效。命令不能覆盖已有命令，权限为 mcqq.said。目标群需在授权及出站列表中。重复空格和标点保留，命令文本不会作为服务端命令执行。

子服控制台也可使用 `/said 内容` 和 `group-commands` 中的自定义命令，以 Console 身份向游戏和 QQ 发言。需在子服 `remote` 配置本地 API 地址、与代理相同的 `proxy-token`、代理中的真实 `server-name`。机器人 `/跨群信息` 查询可用目标及 group_openid；`/跨群信息 [群名/别名] 内容` 定向发送，单词别名可省略方括号；`/跨群信息 ALL 内容` 广播到所有允许出站的群，包含来源群。机器人发送格式为 `【跨群信息｜来源群】发送者：内容`。

`/发命令 lobby|survival|proxy|ALL /指令 参数` 以已绑定玩家身份执行；子服离线时使用受限模拟 Player，proxy 仅支持在线玩家。`/大发命令 lobby|survival|proxy|ALL /指令 参数` 以目标进程 Console 身份执行，不要求绑定游戏账号。目标由 `chat_bridge.command_targets` 显式开放，`ALL` 对列表中每个目标各执行一次。`bot_roles.owners` 填 QQ 官方 member_openid；只有主人和管理可用 `/大发命令`，管理只能指定单个子服，proxy 与 ALL 仅限主人。主人用 `/设bot管理 @成员` 和 `/取缔bot管理 @成员` 即时调整管理名单；名单存于机器人数据库，不需重启。API 服务端核验身份和权限并记录审计；子服需启用 `remote.poll-commands`。远程配置含密钥，勿提交仓库。

`/状态情报` 显示机器人所在主机的操作系统版本、内核、开机运行天数/小时和物理内存已用量、总量及比例。该命令只读，并受 `chat_bridge.command_groups` 群白名单限制。

## 配置与数据存取

子服 `SaidPlugin.storage()` 暴露统一异步 `get(key)` / `put(key,value)` 接口，null 表示删除，返回 CompletableFuture。键允许字母数字、下划线、冒号、斜线和连字符，最大190字符。数据库调用在独立线程执行；调用方应将 Bukkit 操作调回主线程。

`storage.type` 可选 yaml（默认）、sql、mongodb。SQL URL 留空使用本地 SQLite；也可填写 jdbc:mysql://host/database 或 jdbc:postgresql://host/database，用户名和密码单独配置。MongoDB 填写 storage.mongodb.uri 和 database。SQL 使用 mcqq_settings 表，MongoDB 使用 settings 集合，YAML 使用插件目录 data.yml。切换后端不会自动搬迁已有数据。机器人绑定与队列仍由机器人 SQLite 管理，代理玩家聊天偏好保存在代理目录；Spigot 数据接口不替代这些数据源。

默认配置从 JAR 生成至用户插件目录，不覆盖已存在配置；词库首次复制至代理数据目录，服主可修改，并通过重载生效。word-filter.enabled 控制过滤，red/yellow 提供额外正则。修改后应自行验证规则性能。

修改 `mcqq/commands.py` 的 `COMMANDS` 后，发布时还必须在云端机器人运行目录执行 `.venv/bin/python sync_commands.py`，将命令同步到 QQ 官方 `/` 面板。脚本会回读并核对名称与描述；仅更新 Python 文件或重启 Bot 不会更新面板。

群聊 AI 使用 `group_ai_config` 指向权限受限的 `group-ai.yml`（参考 `group-ai.example.yml`），并可通过 `group_ai_word_filter` 指向代理的 `config.yml` 与现有词库。仅 QQ 官方的「@机器人」事件且正文不以 `/` 开头时触发模型；全量群讯息里 @ 其他成员不会触发。`/历史讯息向量化` 仅 Bot 主人及管理可用，压缩时区分群与发言人的官方身份，并按群友昵称检索个人记忆。同名昵称不互认。每群只保留最近 300 条讯息；图片暂存总量上限 200 MiB，满额清空；摘要记忆每群最多 100 条。模型调用可沿用 Afterglow 的 OpenAI 相容端点，但群聊历史与私聊会话独立。输出超过五行时先发送预览；管理可按按钮或发送 `/展开 TOKEN` 查看全文，暂存 30 分钟。

`/今日老婆` 使用 MySQL 保存每日结果与一次换取状态，MongoDB 保存可筛选角色目录。首次抽取附「换老婆」和「就这个了」按钮；每天最多换一次，确认后不能再换，重复点击只取回同一位。按钮不可用时可输入 `/换老婆`。主人可用 `/今日老婆 重置` 清除当天所有人的抽取与换取次数；旧按钮随抽取代号失效。既有资料库需执行 `deploy/daily_waifu_swap_20261117.sql` 升级资料表。Redis 仅存短期回覆快取，过期自动清除；每日结果始终读 MySQL，确保重置或换取后不返回旧资料。资料库专用帐号应由部署者建立，凭据保存在不纳入 Git 的 `.private-daily-waifu.json`。原有绑定、队列和权限仍在 SQLite，避免迁移线上资料。

角色目录来自 Bangumi 的动画角色与作品资料，使用 `deploy/build_waifu_catalog.py` 重新生成；卡片使用单条 QQ Markdown 消息承载头像、角色、作品及按钮，需要机器人具备相应 Markdown 权限。MongoDB 目录中的新角色须与内置目录对应；MongoDB 不可用时使用内置目录。旧版 AniList 抽取记录与新目录不兼容，切换前应备份并清理今日老婆记录。

在可访问 Bangumi 图片的机器上运行 `python deploy/fetch_waifu_portraits.py <目录>`，将图片放到机器人数据库所在目录的 `waifu-portraits` 子目录。机器人按需将图片上传到 QQ 官方素材库，并复用同内容素材；素材库权限或配额不可用时卡片会省略图片，其他内容仍保持一条消息。

## 构建与升级

代理运行 plugin/build.ps1；子服使用 Maven 3.9+ 执行 `mvn -f spigot/pom.xml package`，数据库驱动随子服 JAR 打包。源码构建需要服务器根目录 core 下的 BungeeCord.jar、spigot-1.12.2.jar 和 proxy 下的 BungeeChat JAR；Maven 可用 `-Dmcserver.root=绝对路径` 指定服务器根目录。输出分别为 mcqq-bridge-2.0.0.jar、mcqq-spigot-2.0.0.jar。

升级先备份并正常停止服务器，删除旧 qq-whitelist 和 mcqq-said JAR，放入新 JAR。代理首次启动自动复制 QQWhitelist 数据目录到 MCQQBridge；旧目录保留备份。子服旧 MCQQSaid 配置需要复制到 MCQQSpigot。切勿同时加载新旧插件。保留机器人 settings.json、bridge.json、数据库和服务器上的签名密钥。

本项目提供源码和构建包；对外发布前应遵循所含第三方库和词库的许可。测试命令：`python -m unittest discover -s tests`，代理真实启动测试为 `python tests/proxy_smoke.py`。

## 独立 Python 发布包

安装 `pip install mcqq_bridge-2.0.0-py3-none-any.whl`（将来发布到包索引后可按包名安装）。在任意用户工作目录运行 `mcqq init --config ./settings.json` 生成空凭据模板，填好配置后分别运行 `mcqq api --config ./settings.json` 和 `mcqq bot --config ./settings.json`。也支持 `python -m mcqq`。安装包只包含 mcqq 库、配置模板和元数据；不包含部署脚本、私有配置、数据库、日志或签名密钥。库可通过 `mcqq.service.create_app(config)` 嵌入 aiohttp 服务。

## License

项目原创代码采用 Apache License 2.0。第三方依赖遵循各自许可。公开源码不分发网易敏感词数据集，过滤功能默认关闭；如自行启用，需将适配格式的 G79SensitiveWords.json 和 X19SensitiveWords.json 放入代理数据目录并遵守数据集许可。Minecraft、BungeeChat 和 Floodgate 需要服主单独安装。
