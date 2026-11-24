# MCQQBridge 2.0

QQ 官方机器人与 Minecraft 群服互通框架。Java 包与构建 Group ID 为 `top.luotiany1`。

## 组件和要求

- `mcqq`：Python 3.11+、官方 QQ Bot SDK、aiohttp；提供绑定、身份关联、消息队列和媒体服务。
- `plugin`：BungeeCord 代理插件 MCQQBridge；聊天需要 BungeeChat，基岩关联需要 Floodgate。
- `spigot`：Spigot 1.12.2+ 子服插件 MCQQSpigot；保留 `/said`，支持按群注册命令，提供异步存取接口。
- `fabric`：可选图片客户端，[通用 Fabric 源码与构建说明](fabric/universal/README.md)；26.2、26.3 为重点支持版本，旧版为 legacy support。Forge 和 NeoForge 原生支持正在开发。
- [`crossplay`](crossplay/README.md)：MasterGAL 跨端套件，可独立构建和安装。包含 BungeeCord 路由、Spigot 插件、Fabric 客户端、菜单适配器和 Bedrock 资源包。

## 源码目录

| 目录 | 内容 |
| --- | --- |
| `mcqq/`、`tests/` | QQ 机器人、HTTP API 及 Python 测试 |
| `plugin/`、`spigot/` | QQ 桥的 BungeeCord 和 Spigot 插件 |
| `fabric/`、`multiloader/` | QQ 桥客户端及各加载器的构建工程 |
| `floodgate/` | Floodgate 账号关联集成 |
| `crossplay/common/` | MasterGAL 共享协议、能力协商和协议测试 |
| `crossplay/{bungee,spigot,fabric,menus,bedrock}/` | MasterGAL 各平台入口 |
| `docs/`、`deploy/` | 运维说明与部署脚本 |

## QQ 桥快速启动

首次使用复制 `settings.example.yml` 为 `settings.yml`，填写自己的 QQ app_id、app_secret 和两个不同的随机服务 token（各至少32字符），安装 requirements.txt 后分别运行 `python -m mcqq.service` 与 `python -m mcqq.bot`。配置路径可由 `MCQQ_SETTINGS` 指定，相对路径以配置文件目录为基准。已有 JSON 仍受支持；未指定路径时优先读取 YAML。纯数字的 AppID、QQ 群号和其他标识请加引号，以免 YAML 将它们解析为数字。代理的 service-url 和 proxy-token 必须匹配；不要公开凭据、数据库和签名私钥。

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

`settings.yml` 只供 Python API 与机器人使用；BungeeCord 的 `plugins/MCQQBridge/config.yml` 需要使用相同的 `service-url` 和 `proxy-token`。每个子服安装 MCQQSpigot 后可用 `/said`（或 `group-commands` 中配置的别名）发送消息。不要把运行配置、SQLite 数据库、日志、备份、SSH 私钥或任何群 openid 提交到仓库。

### 推荐启动顺序

1. 从 `settings.example.yml` 生成仅属于自己的 `settings.yml`，填入 QQ 开放平台凭据与两枚不同的随机 token。
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

子服控制台也可使用 `/said 内容` 和 `group-commands` 中的自定义命令，以 Console 身份向游戏和 QQ 发言。需在子服 `remote` 配置本地 API 地址、与代理相同的 `proxy-token`、代理中的真实 `server-name`。

BedWars1058 子服可以在 MCQQSpigot 启用 `features.bedwars-lobby-chat`。同时把该子服加入代理的 `chat-bridge.servers` 和 `chat-bridge.bedwars-lobby-servers`，并将它排除在 BungeeChat 自身的跨服聊天名单之外。QQ 消息只显示给未进入竞技场的玩家。大厅普通聊天发往出站群，`/said` 和群命令也只允许大厅玩家使用。竞技场内的队伍聊天和喊话由 BedWars1058 处理。

- `/跨群信息` 查询目标群和 group_openid。`/跨群信息 [群名/别名] 内容` 定向发送，单词别名或 ID 可省略方括号。
- `/跨群信息 ALL 内容` 广播到允许出站的其他群。省略目标时也按 ALL 发送，并在回执中提示如何指定目标。
- 在 QQ 中引用回复 Bot 转发的跨群消息，可把回复直接发回原来源群。
- `/跨群信息 临时全量模式 一群,二群,MC群` 在接下来 2 小时内自动转发当前发言者的消息，目标以英文逗号分隔，支持别名和 ID。省略范围时为 ALL，自动跳过发言所在群。重复执行会替换范围，并从执行时起重新计时 2 小时。自动转发仅在失败时回报。
- `/跨群信息 结束全量模式` 立即关闭自己的全量模式。Bot 重启会清除临时模式及跨群消息的引用索引。
- Bot 主人和管理员可用 `/跨群信息 临时全量模式 一群,二群 !@成员` 为指定群友开启。英文感叹号后使用 QQ 的 @ 功能选择一名成员，省略群范围时为 ALL。用 `/跨群信息 结束全量模式 @成员` 可关闭该成员的模式。

`/发命令 lobby|survival|proxy|ALL /指令 参数` 以已绑定玩家身份执行；子服离线时使用受限模拟 Player，proxy 仅支持在线玩家。`/大发命令 lobby|survival|proxy|ALL /指令 参数` 以目标进程 Console 身份执行，不要求绑定游戏账号。目标由 `chat_bridge.command_targets` 显式开放，`ALL` 对列表中每个目标各执行一次。`bot_roles.owners` 填 QQ 官方 member_openid；只有主人和管理可用 `/大发命令`，管理只能指定单个子服，proxy 与 ALL 仅限主人。主人用 `/设bot管理 @成员` 和 `/取缔bot管理 @成员` 即时调整管理名单；名单存于机器人数据库，不需重启。API 服务端核验身份和权限并记录审计；子服需启用 `remote.poll-commands`。远程配置含密钥，勿提交仓库。

`/伺服器情报` 显示机器人所在主机的系统、内核、运行时间、内存和 CPU 占用率，以及主目录所在硬碟的剩余空间。SMP 在线人数默认来自 `survival` 或 `smp` 子服的状态快照。Bot 与 Java 版 SMP 位于同一台机器时，可为 Bot 设置环境变量 `MCQQ_SMP_STATUS_PORT` 为 SMP 的游戏端口，直接读取该本机端口的服务器状态。`/服状态 系统` 和 `/状态情报` 也可查看同一份情报。命令受 `chat_bridge.command_groups` 群白名单限制。

## 配置与数据存取

子服 `SaidPlugin.storage()` 暴露统一异步 `get(key)` / `put(key,value)` 接口，null 表示删除，返回 CompletableFuture。键允许字母数字、下划线、冒号、斜线和连字符，最大190字符。数据库调用在独立线程执行；调用方应将 Bukkit 操作调回主线程。

`storage.type` 可选 yaml（默认）、sql、mongodb。SQL URL 留空使用本地 SQLite；也可填写 jdbc:mysql://host/database 或 jdbc:postgresql://host/database，用户名和密码单独配置。MongoDB 填写 storage.mongodb.uri 和 database。SQL 使用 mcqq_settings 表，MongoDB 使用 settings 集合，YAML 使用插件目录 data.yml。切换后端不会自动搬迁已有数据。机器人绑定与队列仍由机器人 SQLite 管理，代理玩家聊天偏好保存在代理目录；Spigot 数据接口不替代这些数据源。

默认配置从 JAR 生成至用户插件目录，不覆盖已存在配置；词库首次复制至代理数据目录，服主可修改，并通过重载生效。word-filter.enabled 控制过滤，red/yellow 提供额外正则。修改后应自行验证规则性能。

QQ 面板将入服账户与头衔分别收在 `/SMP账号` 和 `/SMP头衔`。群情报与系统状态使用独立入口 `/群讯息情报统计`、`/群友情报` 和 `/伺服器情报`。`/群情报 今日` 和 `/群情报 成员 @群友` 是标准分组写法。简写 `/群情报` 或 `/群情报 @群友` 也可执行，并会附标准用法提示。`/大发命令`、`/设bot管理`、`/取消bot管理` 和 `/取缔bot管理` 通过手动输入使用。

修改 `mcqq/commands.py` 的 `COMMANDS` 后，发布时还必须在云端机器人运行目录执行 `.venv/bin/python sync_commands.py`，将命令同步到 QQ 官方 `/` 面板。脚本会回读并核对名称与描述；仅更新 Python 文件或重启 Bot 不会更新面板。

群聊 AI 通过 `group_ai_config` 读取权限受限的 `group-ai.yml`（参考 `group-ai.example.yml`），并可通过 `group_ai_word_filter` 使用代理词库。群内 @ 机器人且正文不以 `/` 开头时触发群聊模型，同时支持 QQ 的专用 @ 事件和全量群消息。Bot 主人或管理可用 `/历史讯息向量化` 分批压缩本群尚未清理的全部缓存，按官方群和成员标识保存可检索的向量记忆。同名昵称不会关联到同一人。群聊原始记录按北京时间保留，图片暂存上限为单张 8 MiB、总量 200 MiB。摘要记忆长期保存。群与私聊使用独立会话，长回复必要时分条发送。

全量群消息模式下，将 `group_ai_mention_openid` 设置为 QQ 全量事件中 @ 机器人标记里的 32 位 OpenID。

**群讯息日报。** 系统于北京时间 23:55 预分析，当天最后五分钟的消息会一起纳入零点日报。星图只发一张，突出前三名和前 12 名的精确发言数，其他发言者合计列出。六个四小时段显示主要话题。头像优先使用 QQ 提供的地址，Redis 启用时复用最近成功的头像，其他情况显示昵称首字。零点生成后清理原始记录和临时图片，有效话题以群级向量摘要保存。发送失败的图片保留重试，零点后五分钟内可以补做漏掉的绘制。

**群友情报。** `/群友情报 @群友` 属于娱乐功能组并全天开放。提交后先回复排队确认，再发一张观察图。当天全部缓存用于查找目标发言、提及和相关上下文，同时加入该成员的持久记忆。图片展示核心标签、发言习惯、常聊话题、可核实的重复用语、带发言依据的长处与沟通摩擦、MBTI 趣味推测和情报总结。模型不可用时图上只展示本地统计。命令接受 QQ 的正式 @ 标记。

普通成员按群与成员计费，默认滚动一分钟 1 次、五小时 15 次、七天 80 次。额度不足会在排队前回覆各窗口的剩余比例与北京时间。Bot 主人及管理员默认不限额，可用 `/群友情报 重置` 清空本群的次数记录。使用 `settings.yml` 的 `plugins.member_intel` 调整开关、排队提示、限额、豁免角色和画像快取时间。群聊模型的术语偏好由 `group-ai.yml` 中的 `output_language` 指定。

**群聊情报存储拓扑。** 在 `settings.yml` 的 `group_ai_storage` 独立选择五项，默认整套群聊情报可离线使用 SQLite 与进程内快取。

| 选项 | 可选后端 | 数据 |
| --- | --- | --- |
| `history` | `sqlite` / `mysql` / `mongodb` | 原始讯息、成员资料、附件。MySQL 将附件内容保存在数据库，SQLite 和 MongoDB 模式将暂存附件保存在本机。 |
| `memory` | `sqlite` / `mysql` | 长期保留的群摘要和成员向量记忆。 |
| `reports` | `sqlite` / `mysql` | 日报日历、待投递图像、已归档日期。 |
| `quota` | `sqlite` / `mysql` | 需要原子更新的滚动配额和管理员重置。 |
| `cache` | `local` / `mysql` / `redis` | 可重建的头像、日报分析和画像结果。Redis 提供共享 TTL，MySQL 提供单库部署的 TTL 快取，`local` 不需要额外服务。 |

纯 MySQL 示例，适用 MySQL 8.0.19 及以上版本。

```yaml
group_ai_storage:
  history: mysql
  memory: mysql
  reports: mysql
  quota: mysql
  cache: mysql
  credentials_file: .private-group-ai.yml
```

混合模式可仅把上述 `history` 改为 `mongodb`、`cache` 改为 `redis`，其余继续使用 MySQL。凭据 YAML 可分别提供 `mysql`（主机、库、账号等）、`mongodb`（URI、库、集合前缀）、`redis`（URL、键前缀）。如果已经配置了这些连接，也可以用 `credentials_from: daily_waifu`。限额始终先核验，读取快取不会跳过配额。

在选定的 MySQL 数据库中，先用管理账号执行启用角色所需的建表脚本。`deploy/group_ai_full_mysql.sql` 包含历史、成员资料、附件、日报和 TTL 快取表；`deploy/group_ai_memory.sql` 创建向量记忆表；`deploy/group_command_quota.sql` 创建限额表。给运行账号授予所用表的 SELECT、INSERT、UPDATE 和必要的 DELETE 即可。Redis 账号需要对所选键前缀执行 GET 和 SETEX。

升级既有 MySQL 日报表时，若 `mcqq_group_ai_daily` 尚无 `cutoff` 列，请先用管理账号执行 `ALTER TABLE mcqq_group_ai_daily ADD COLUMN cutoff DOUBLE NULL`，以便继续使用原有运行账号权限。

从 SQLite 切换时先备份配置和数据库，停机器人后以目标配置运行 `python -m mcqq.migrate_group_storage`，查看逐项回读结果后再启动。可用 `--only history|memory|reports|quota` 分阶段切换。快取会自动重建，迁移不清除 SQLite 源记录。既有 SQLite 图片缓存仅导入仍可读取的文件。

**编写插件。** 在 `mcqq/plugins` 配对提交 Python 处理器和同名 `.yml` 清单，并在注册表显式注册。YAML 的 `command` 声明 `name`、`category`、`schedule` 与参数类型 `mention` 或 `text`，`skill` 保存分析提示。异步处理器接收群上下文和该 YAML 配置，成功时可返回 PNG 字节。示例见 `member_intel.py` 与 `member_intel.yml`。

自动日报默认只发给别名为「一群」的唯一授权群。可用 `daily_report_groups` 显式指定授权群的 `group_openid`，空数组关闭排程。用 `daily_report_time` 指定北京时间发送时间（默认 `"00:00"`）。设为 `"23:50"` 时，每期统计前一天 23:50 起、当日 23:50 前的消息。所有授权群的 Bot 主人或管理员均可发送 `/群讯息情报统计`，图上会注明「手动触发」和从当日 00:00 到命令触发时刻的区间。统计所覆盖的消息取决于该群启用的 QQ 全量群消息权限。图像通过 QQ Markdown 图片素材接口发送，定时投递还需要当前机器人在群中拥有主动发送权限。Ubuntu 需安装中文字体（例如 `fonts-noto-cjk`），也可配置 `daily_report_font`。

`/今日老婆` 使用 MySQL 保存每日结果与一次换取状态，MongoDB 保存可筛选角色目录。未更换或确认时，抽取和重复查询均附「换老婆」和「就这个了」按钮；点击换老婆会发送 `/换老婆`，每天最多换一次，确认后不能再换，重复点击只取回同一位。按钮不可用时可输入 `/换老婆`。`/今日老婆 许愿 角色名` 消耗 16 积分并使用当天的更换机会，可以在首次抽取前使用。主人可用 `/今日老婆 重置` 清除当天所有人的抽取与换取次数；旧按钮随抽取代号失效。既有资料库需执行 `deploy/daily_waifu_swap_20261117.sql` 升级资料表。Redis 仅存短期回覆快取，过期自动清除；每日结果始终读 MySQL，确保重置或换取后不返回旧资料。资料库专用帐号应由部署者建立，凭据保存在不纳入 Git 的 `.private-daily-waifu.json`。原有绑定、队列和权限仍在 SQLite，避免迁移线上资料。

角色目录来自 Bangumi 的动画角色与作品资料，使用 `deploy/build_waifu_catalog.py` 重新生成；卡片使用单条 QQ Markdown 消息承载头像、角色、作品及按钮，需要机器人具备相应 Markdown 权限。MongoDB 目录中的新角色须与内置目录对应；MongoDB 不可用时使用内置目录。旧版 AniList 抽取记录与新目录不兼容，切换前应备份并清理今日老婆记录。

在可访问 Bangumi 图片的机器上运行 `python deploy/fetch_waifu_portraits.py <目录>`，将图片放到机器人数据库所在目录的 `waifu-portraits` 子目录。机器人按需将图片上传到 QQ 官方素材库，并复用同内容素材；素材库权限或配额不可用时卡片会省略图片，其他内容仍保持一条消息。

群级功能时间可在 `feature_policy.groups` 中按官方 group_openid 和功能组配置，例如 `{"GROUP_A":{"entertainment":{"schedule":"china_school_hours","closed_dates":["06-04"]},"llm":{"schedule":"always","closed_dates":["06-04"]}}}`。`entertainment` 默认包含 `/今日老婆`、`/换老婆` 及对应按钮；可通过 `feature_policy.categories` 增加其他功能组、命令名和按钮前缀。未配置的群或功能组不受限制。时间采用 Asia/Shanghai，区间为 00:00–07:00、14:00–17:00，结束时刻不包含在内；工作日分别使用每群每分钟 10 次和 3 次的滑动限流，超限静默。周末、国务院放假日期及指定寒暑假仅在上述时段开放，指定年度关闭日期全天生效。LLM 关闭日期直接返回维护提示，不请求模型。

代码内置已核对的 2026、2027 年国务院放假日期；后续年份公布后应在 `feature_policy.holiday_ranges` 增加年份及 `[["MM-DD","MM-DD"], ...]` 放假区间。未知年份为避免漏掉节假日，工作日暂按受限日期处理并记录警告；补充官方日历并重启 Bot 后恢复准确规则。`closed_dates` 每年重复，格式为 `MM-DD`。

自定义功能的群级规则可用 `schedule: "daily_windows"` 和 `windows: [["18:30","20:15"]]` 指定每日开放区间，可选 `limit_per_minute`；跨午夜窗口拆成两段。`china_school_hours` 也可通过 `windows`、`limit_in_windows`、`limit_outside_windows` 覆盖默认时段和限额。

## 构建与升级

从仓库根目录运行 `pwsh -File plugin/build.ps1 -BungeeJar /path/to/BungeeCord.jar -ChatJar /path/to/BungeeChat.jar` 构建代理插件。子服使用 Maven 3.9+，执行 `mvn -f spigot/pom.xml "-Dmcserver.root=/path/to/server-root" package`。该目录的 `core/` 中需要 `spigot-1.12.2.jar`，数据库驱动随子服 JAR 打包。构建产物分别位于 `plugin/target/` 和 `spigot/target/`。

升级先备份并正常停止服务器，删除旧 qq-whitelist 和 mcqq-said JAR，放入新 JAR。代理首次启动自动复制 QQWhitelist 数据目录到 MCQQBridge；旧目录保留备份。子服旧 MCQQSaid 配置需要复制到 MCQQSpigot。切勿同时加载新旧插件。保留机器人 settings.json、bridge.json、数据库和服务器上的签名密钥。

安装 `requirements.txt` 后，在仓库根目录运行 `python -m unittest discover -s tests`。涉及 MySQL 的用例需要显式配置一次性测试数据库。

## 独立 Python 发布包

安装 `pip install mcqq_bridge-2.0.0-py3-none-any.whl`（将来发布到包索引后可按包名安装）。在任意用户工作目录运行 `mcqq init --config ./settings.yml` 生成空凭据模板，填好配置后分别运行 `mcqq api --config ./settings.yml` 和 `mcqq bot --config ./settings.yml`。也支持 `python -m mcqq`。安装包只包含 mcqq 库、配置模板和元数据；不包含部署脚本、私有配置、数据库、日志或签名密钥。库可通过 `mcqq.service.create_app(config)` 嵌入 aiohttp 服务。

可把 `scheduled_panel_groups` 设为需要独立面板的授权群 openid 数组，并定期运行 `python sync_group_panel.py`：脚本查询并按需更新 QQ 指定群面板，无需重启 Bot。需先确认 QQ 对指定群面板与已有全群面板的显示优先级，以及平台的实际审核和缓存行为；未验证前不要移除现有面板。被限制时的命令回复仍会显示下次开放时间。

## License

项目原创代码采用 Apache License 2.0。第三方依赖遵循各自许可。公开源码不分发网易敏感词数据集，过滤功能默认关闭；如自行启用，需将适配格式的 G79SensitiveWords.json 和 X19SensitiveWords.json 放入代理数据目录并遵守数据集许可。Minecraft、BungeeChat 和 Floodgate 需要服主单独安装。
