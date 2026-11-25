# BungeeMaster-GAL 开发者文档

## 适用版本

本文对应 **BungeeMasterGAL 0.3.1**，目标平台为 **BungeeCord**。发行 JAR 使用 Java 8 字节码，代理进程须满足其 BungeeCord、Floodgate 和 Geyser 构建各自的 Java 下限。本地测试使用 Java 25、支持 Minecraft Java 26.2 和 26.3 协议的 BungeeCord、**Floodgate 2.2.5-SNAPSHOT（b141-81b65cc）** 和 **Geyser-BungeeCord 2.12.1-b1281**。这是已核对的部署组合，以上构建号不代表最低版本要求。测试后端为 Spigot 1.12.2、26.2。其他代理实现需单独适配。

把 `BungeeMasterGAL-0.3.1.jar` 和 Floodgate 的 BungeeCord 版安装到代理的 `plugins/`。插件硬依赖 Floodgate。基岩入口另需 Geyser-BungeeCord，将 Geyser 的 Java 端鉴权模式设为 `floodgate`，后端安装 [SpigotMasterGAL](SpigotMaster-GAL.md)。现有 Geyser 构建的配置项为 `java.auth-type`。MasterGAL 在代理查询基岩身份和发送表单，因此可以保持代理 Floodgate 的 `send-floodgate-data: false`。代理在初次连接和切换后端后向当前后端发送已确认的表单能力，配套的 SpigotMasterGAL 0.4.0 使用该能力路由按钮菜单。

## 扩展点与 API 边界

BungeeMasterGAL 负责会话路由。业务事件、请求处理器和结果回调在 [Spigot API](SpigotMaster-GAL.md) 与 [Fabric API](FabricMaster-GAL.md) 上注册。代理组件没有对外的业务注册方法或会话监听 SDK。代理插件若依赖它的加载顺序，可以在自己的 `bungee.yml` 中声明 `depends: [BungeeMasterGAL]`。需要在代理直接制作独立的基岩界面时，可以依赖 `floodgate`，使用 Floodgate 的公开 API。

| 入口或回调 | 挂载位置和行为 |
| --- | --- |
| `PluginMessageEvent` | BungeeMasterGAL 消费自己登记的通道，检查发出方向和当前后端连接，再转发或处理。其他代理插件应为自己的消息使用独立通道 |
| `ServerSwitchEvent` | 清除旧后端会话，向已协商的 Fabric 客户端发 RESET。新后端经过能力交换后才收到业务消息 |
| `PlayerDisconnectEvent` | 清理该玩家的路由和挂起诊断请求 |
| Floodgate 表单有效回调 | 读取 `clickedButtonId()`，有效索引回到发起表单的 Spigot 会话 |
| Floodgate 表单关闭或无效回调 | 把 `BedrockForm.CLOSED` 传回发起方；无法交付时回传 `BedrockForm.UNAVAILABLE` |

代理上的独立表单使用 `FloodgateApi.getInstance().isFloodgatePlayer(uuid)` 识别玩家，使用 `sendForm(uuid, builder)` 投递。Cumulus 的 `validResultHandler(...)` 接收有效响应，`closedOrInvalidResultHandler(...)` 接收关闭或无效结果。代理直接发出的表单，其回调也由代理插件直接处理。需要 Spigot 校验购买等业务时，由 Spigot 调用 `showBedrockForm(...)`，MasterGAL 会将结果送回对应后端。[Floodgate 表单 API](https://geysermc.org/wiki/geyser/forms/)

## 消息通道与会话

| 通道 | 链路 | 用途 |
| --- | --- | --- |
| `mcqq:gal` | Fabric ↔ BungeeCord | MasterGAL 0.2.0 的通用能力交换、事件、请求和结果 |
| `mcqq:galbus` | BungeeCord ↔ 当前 Spigot | 与 Fabric 侧相同的通用帧，沿该玩家当前的后端连接收发 |
| `mcqq:galform` | Spigot ↔ BungeeCord | 发送表单描述、回传按钮索引或失败状态 |
| `mcqq:crossplay`、`mcqq:crossbus` | 对应的客户端和后端旧通道 | 保留世界查询诊断路径 |

Fabric 发 HELLO 公布可接收的动作，代理将其转发给当前后端。Spigot 发 WELCOME 公布自己的接收能力。之后，同一玩家当前连接上的事件、请求和响应才能通过。代理不会将旧后端的回包发给已经切服的玩家。Java 客户端无法借由后端专用通道进入该后端的请求处理器。业务授权、数据格式、幂等性和限流仍由实际处理动作的业务插件负责。

### 调试协议帧

通用帧当前协议版本为 1。帧依次包含 1 字节版本、1 字节类型、4 字节大端请求 ID、1 字节动作名长度、ASCII 动作名和正文。类型依次为 `HELLO (0)`、`WELCOME (1)`、`RESET (2)`、`EVENT (3)`、`REQUEST (4)`、`RESPONSE (5)`、`ERROR (6)`。HELLO 和 WELCOME 正文先写 1 字节能力数，再重复写能力标志、1 字节名称长度和动作名。能力标志为 1 表示可接收事件，2 表示可接收请求，3 表示都支持。请求和响应使用相同的非零 ID 及动作名，事件 ID 为 0。该格式适合排查日志或协议抓包，业务插件采用两端公开回调以减少对代理内部格式的依赖。[GalPacket.java](../common/src/main/java/top/luotiany1/mcqq/crossplay/GalPacket.java)

## 验收与排查

- 确认代理启动日志中 Geyser、Floodgate 和 BungeeMasterGAL 已加载。只用 Java 端进行开发时，BungeeMasterGAL 依然要求代理安装 Floodgate。
- 用 Fabric 的 `/crossplayevent` 与后端的 `/mastergalclient` 验证双向事件和请求。换服时分别确认新旧后端是否安装对应业务插件，并在新后端等待重新协商。
- 基岩玩家执行 `/crossplay` 会打开世界查询表单。用 `/mastergalform` 验证 Spigot 到代理再到客户端的表单路径及回调。分别检查资源包读取、传输连接和游戏内的表单点击。基岩 26.60 起需要 NetherNet，Geyser 的基岩监听地址应按 NetherNet 网络要求配置。 [Geyser NetherNet 排查](https://geysermc.org/blog/preparing-for-nethernet/)
- 只在部分后端失败时，检查当前路由、ViaVersion/ViaBackwards 的版本链和目标后端注册的能力。资源包放置位置及图标路径见 [BedrockPack](BedrockPack.md)。
