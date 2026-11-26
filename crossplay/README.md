# SpigotMaster-GAL、BungeeMaster-GAL 与 FabricMaster-GAL

三个 Minecraft 组件可从 MCQQBridge 分别构建，与 C++ `luo-master` 独立。Spigot 插件与 Fabric Mod 可以注册各自接收的事件和请求、查询对端能力，并双向收发。兼容客户端可接收服务端驱动的 Fabric 自定义菜单；基岩玩家通过代理上的 Floodgate 表单接入。菜单只传回按钮编号，商品操作始终由服务端插件执行。

## 开发者文档

- [SpigotMaster-GAL](docs/SpigotMaster-GAL.md)
- [BungeeMaster-GAL](docs/BungeeMaster-GAL.md)
- [FabricMaster-GAL](docs/FabricMaster-GAL.md)
- [BedrockPack](docs/BedrockPack.md)
- [界面映射与验收](docs/MenuMapping.md)
- [SpigotMaster 事件迁移矩阵](docs/EventCompatibility.md)

## 与当前拓扑的对应关系

| 位置 | 组件 | 用途 |
| --- | --- | --- |
| Java 客户端 | FabricMaster-GAL | 协商能力，与 Spigot 交换事件和请求 |
| BungeeCord | BungeeMaster-GAL | 路由 Fabric 请求与 Spigot 回包，使用 Floodgate 识别基岩玩家并映射表单 |
| Spigot | SpigotMaster-GAL | 读取当前玩家所在世界，提供后端表单接口 |
| Geyser-BungeeCord | MasterGAL.mcpack | 玩家连接时下载，提供基岩表单按钮图标 |

可选的 `MasterGALMenus` 将通过代理确认身份的基岩玩家引导到 BedWars1058 的快捷购买、商品类别和 GadgetsMenu 主菜单表单。GadgetsMenu 的各分类、购买和神秘箱继续使用原生库存。管理员可按文件启用已审计的 ChestCommands 按钮菜单。Java 客户端（包括 Fabric）继续使用这些插件的库存菜单。业务插件仍可用 `showMenu` 提供专门设计的 Fabric Screen。

典型拓扑在 BungeeCord 代理开放 Java TCP 25565。基岩 26.60 起使用 NetherNet。采用 Geyser 内置信令时，基岩端口通常同时使用 TCP 和 UDP，默认端口为 19132。为大厅、生存等后端分别配置代理路由，同机后端可监听回环地址。Geyser 和 Floodgate 安装在代理层处理基岩身份和表单回调，可使用 `send-floodgate-data: false`。 [Geyser NetherNet 配置](https://geysermc.org/wiki/geyser/setup/)

## Fabric 构建目标

26.3 和 26.2 分别构建，客户端 JAR 与实际编译的 Minecraft 版本精确匹配。新增目标需要核验 Fabric API、BungeeCord 入口协议和旧后端的 ViaVersion 翻译链路。FabricMasterGAL 仍通过 `mcqq:gal` 和 `mcqq:galbus` 协商和收发业务消息。旧版世界查询使用 `mcqq:crossplay` 和 `mcqq:crossbus`。

## 构建与安装

从本目录使用 JDK 25、Gradle 9.6.1 和 Python 3 构建。服务端插件编译为 Java 8 字节码。

```powershell
pwsh -File ./build-server.ps1 -Component SpigotMaster-GAL -SpigotJar /path/to/spigot-1.12.2.jar
pwsh -File ./build-server.ps1 -Component BungeeMaster-GAL -BungeeJar /path/to/BungeeCord.jar -FloodgateJar /path/to/floodgate-bungee.jar
pwsh -File ./build-server.ps1 -Component MasterGALMenus -SpigotJar /path/to/spigot-1.12.2.jar -BedWarsJar /path/to/bedwars.jar
gradle -p fabric -PminecraftTarget=26.3 build
gradle -p fabric -PminecraftTarget=26.2 build
python bedrock/build-pack.py
```

将路径替换为实际依赖文件的位置。Spigot 1.12.2 可用 Spigot BuildTools 构建。代理依赖使用 BungeeCord 和 Floodgate 的 BungeeCord 发行包。可通过 `-BedWarsJar` 传入兼容的 BedWars1058 21.11.2 JAR 来构建菜单适配器。已有开发服务器目录时可用 `-ServerRoot` 指定根目录。省略 `-Component` 时沿用原来的一次构建入口。Fabric 模块可从仓库根目录使用 `gradle -p crossplay/fabric` 调用。

源码和构建脚本保留在 `crossplay/`，现有 JAR 文件名、Bukkit/Bungee 加载名、Fabric 模组 ID、Java 包名、命令、协议通道和配置路径可继续使用。三个带连字符的名称用于文档、构建组件选项和产品展示。

- 表单部署使用配套的 BungeeMaster-GAL 0.3.1 与 SpigotMaster-GAL 0.4.0。
- `build/BungeeMasterGAL-0.3.1.jar` 放到 `proxy/plugins/`。
- `build/SpigotMasterGAL-0.4.0.jar` 放到需要接入的 Spigot 后端的 `plugins/`。
- 当本地 BedWars1058 21.11.2 构建依赖存在时，脚本也生成 `build/MasterGALMenus-0.4.0.jar`。它是可选适配器，不属于 MasterGAL 核心。
- `fabric/build/<版本>/libs/FabricMasterGAL-0.4.0+<版本>.jar` 与对应的 Fabric API 一起放到客户端 `mods/`。安装时替换旧版 FabricMasterGAL。
- 换服后，FabricMasterGAL 会在已完成过 GAL 握手的同一条代理连接上重新协商，GalVoice 0.2.0 可继续使用。第一人称剑格挡动作需要当前后端公布格挡能力并确认状态。
- `build/MasterGAL.mcpack` 放到 `proxy/plugins/Geyser-BungeeCord/packs/`。Geyser 会在基岩玩家连接时下发，更新资源包内容时提升清单版本。

## Spigot 与 Fabric 扩展 API

| 操作 | 用途 |
| --- | --- |
| `onEvent` 与 `sendEvent` | 单向通知，例如客户端 UI 操作、服务端状态变更 |
| `onRequest` 与 `request` | 带响应的调用，使用请求 ID 匹配回包 |
| `onReady`、`canRequest`、`canSendEvent` | 在连接建立时协商两端注册的能力 |

Spigot 插件在 `plugin.yml` 声明依赖 `SpigotMasterGAL`，使用 `SpigotMasterGAL#api()` 取得带当前 `Player` 的接口。Fabric Mod 依赖 `fabricmastergal`，通过 `FabricMasterGAL.api()` 取得带当前 `Minecraft` 的接口。双方在初始化时用自己的命名空间注册，例如 `myshop:catalog`。应用层自行定义消息内容和版本，由 Spigot 根据当前玩家校验业务动作。

`SpigotMasterGAL#showMenu(Player, GalMenu, IntConsumer)` 是可选的服务端菜单入口。0.3.0 菜单能力使用既有 `GalApi` 事件信道协商，添加的动作名是 `mastergal:menu_open` 与 `mastergal:menu_result`，不会改变 `GalApi` 方法或现有数据包格式。FabricMaster-GAL 0.3.0 起显示带 1 至 16 个按钮的自定义 Screen；旧客户端不公布该动作。Floodgate 玩家走表单映射，按钮最多 16 个。既有库存适配器使用仅基岩的 `showBedrockMenu`。业务插件必须把回调当作操作意图，并重新查询当前状态和权限。

事件和请求处理在对应端的游戏线程。单条数据最多 8 KiB，待处理请求最多 32 个，超时或换服会结束原会话的待处理请求。在 Fabric 客户端可用 `/crossplayprobe` 测试客户端请求，`/crossplayevent` 测试双向事件，`/mastergalclient` 测试 Spigot 主动向客户端请求版本。

Carpet 类服务端功能、自定义方块和实体可以把状态与交互定义为协议消息，服务端行为由 Spigot 插件实现，Fabric Mod 实现客户端输入与渲染。局内语音可通过此 API 协商能力和会话，实时音频需要单独的传输通道。

## 基岩版表单和商店接口

基岩玩家可用代理命令 `/crossplay` 查询当前 Spigot 世界，也可用后端命令 `/mastergalform` 验证带资源包图标的表单。后者在玩家点击后由 Spigot 告知按钮编号。

商店插件可依赖 `SpigotMasterGAL`，在主线程调用 `showBedrockForm(Player, BedrockForm, IntConsumer)`。`BedrockForm` 接收标题、正文和最多 16 个按钮，按钮可引用 Bedrock 资源包内的纹理路径。回调索引从 0 开始，也可能返回 `BedrockForm.CLOSED` 或 `BedrockForm.UNAVAILABLE`。返回 `false` 表示当前请求未发出。会话断开后表单作废；购买逻辑可在回调中使用原有商店的购买校验和扣款接口。

现有菜单的入口、保留的库存语义和真机验收步骤见 [界面映射与验收](docs/MenuMapping.md)。Geyser 可向表单提供资源包素材。参见 [Geyser 资源包](https://geysermc.org/wiki/geyser/packs/)和 [Floodgate 表单](https://geysermc.org/wiki/geyser/forms/)。
