# MasterGAL 跨端通信

MasterGAL 从 MCQQBridge 独立构建。Spigot 插件与 Fabric Mod 可以注册各自接收的事件和请求、查询对端能力，并双向收发。兼容客户端可接收服务端驱动的 Fabric 自定义菜单；基岩玩家通过代理上的 Floodgate 表单接入。菜单只传回按钮编号，商品操作始终由服务端插件执行。

## 开发者文档

- [SpigotMaster-GAL](docs/SpigotMaster-GAL.md)
- [BungeeMaster-GAL](docs/BungeeMaster-GAL.md)
- [FabricMaster-GAL](docs/FabricMaster-GAL.md)
- [BedrockPack](docs/BedrockPack.md)

## 与当前拓扑的对应关系

| 位置 | 组件 | 用途 |
| --- | --- | --- |
| Java 客户端 | FabricMasterGAL | 协商能力，与 Spigot 交换事件和请求 |
| BungeeCord | BungeeMasterGAL | 路由 Fabric 请求与 Spigot 回包，使用 Floodgate 识别基岩玩家并映射表单 |
| Spigot | SpigotMasterGAL | 读取当前玩家所在世界，提供后端表单接口 |
| Geyser-BungeeCord | MasterGAL.mcpack | 玩家连接时下载，提供基岩表单按钮图标 |

可选 `MasterGALMenus` 插件接入 BedWars1058 的常规商店和 ChestCommands 菜单。BedWars 的快捷购买按钮调用 BedWars1058 原有购买执行路径；ChestCommands 按钮调用原图标的 `onClick`，保留它自己的权限、价格、物品要求及命令处理。关闭表单或不支持 MasterGAL 的 Java 客户端回到原始库存菜单。

Java 入口使用 TCP 25565，基岩入口使用 UDP 19132。BungeeCord 默认进 `lobby`。三个后端是 `lobby`（Spigot 1.12.2，25500）、`survival`（Spigot 26.2，25501）和 `bw`（Spigot 1.12.2，25502）。后端均监听本机回环地址。Geyser 和 Floodgate 在代理层，当前的 `send-floodgate-data: false` 可以继续使用。基岩身份和表单回调留在代理处理。

## Fabric 版本线

- **26.3 及以上**是官方客户端线，跟随 Minecraft Java 最新正式版。首个构建目标为 26.3。26.3 使用 SDL3，当前命令入口直接使用 Brigadier 与 Fabric API，将来如有自定义输入由各客户端目标选用对应 API。
- **26.2 及以下**保留为旧版线。首个构建目标为 26.2。26.1.x 和 1.21.x 需分别落实目标 API、映射和进服验证后再列为支持版本。

客户端包按实际编译的游戏版本锁定。新正式版发布后，新增客户端目标并核验 BungeeCord 的入口协议，以及 ViaVersion 在每个实际后端上的翻译链路。现有 Spigot 核心可按服务器自己的计划升级。0.2.0 通用消息通过 `mcqq:gal` 和 `mcqq:galbus` 沿玩家连接收发。0.3.0 菜单能力复用通用事件转发，代理无需改动。旧版世界查询保留 `mcqq:crossplay` 和 `mcqq:crossbus`。

## 构建与安装

从本目录使用 JDK 25、Gradle 9 和 Python 3 构建。服务端插件编译为 Java 8 字节码。

```powershell
pwsh -File ./build-server.ps1 -SpigotJar /path/to/spigot-1.12.2.jar -BungeeJar /path/to/BungeeCord.jar -FloodgateJar /path/to/floodgate-bungee.jar
gradle -p fabric -PminecraftTarget=26.3 build
gradle -p fabric -PminecraftTarget=26.2 build
python bedrock/build-pack.py
```

将路径替换为实际依赖文件的位置。Spigot 1.12.2 可用 Spigot BuildTools 构建。代理依赖使用 BungeeCord 和 Floodgate 的 BungeeCord 发行包。可通过 `-BedWarsJar` 传入兼容的 BedWars1058 21.11.2 JAR 来构建菜单适配器。已有开发服务器目录时可用 `-ServerRoot` 指定根目录。

- `build/BungeeMasterGAL-0.2.0.jar` 放到 `proxy/plugins/`。
- `build/SpigotMasterGAL-0.3.0.jar` 放到需要接入的 Spigot 后端的 `plugins/`。
- 当本地 BedWars1058 21.11.2 构建依赖存在时，脚本也生成 `build/MasterGALMenus-0.3.0.jar`。它是可选适配器，不属于 MasterGAL 核心。
- `fabric/build/<版本>/libs/FabricMasterGAL-0.3.0+<版本>.jar` 与对应的 Fabric API 一起放到客户端 `mods/`。
- `build/MasterGAL.mcpack` 放到 `proxy/plugins/Geyser-BungeeCord/packs/`。Geyser 会在基岩玩家连接时下发，更新资源包内容时提升清单版本。

## Spigot 与 Fabric 扩展 API

| 操作 | 用途 |
| --- | --- |
| `onEvent` 与 `sendEvent` | 单向通知，例如客户端 UI 操作、服务端状态变更 |
| `onRequest` 与 `request` | 带响应的调用，使用请求 ID 匹配回包 |
| `onReady`、`canRequest`、`canSendEvent` | 在连接建立时协商两端注册的能力 |

Spigot 插件在 `plugin.yml` 声明依赖 `SpigotMasterGAL`，使用 `SpigotMasterGAL#api()` 取得带当前 `Player` 的接口。Fabric Mod 依赖 `fabricmastergal`，通过 `FabricMasterGAL.api()` 取得带当前 `Minecraft` 的接口。双方在初始化时用自己的命名空间注册，例如 `myshop:catalog`。应用层自行定义消息内容和版本，由 Spigot 根据当前玩家校验业务动作。

`SpigotMasterGAL#showMenu(Player, GalMenu, IntConsumer)` 是可选的服务端菜单入口。0.3.0 菜单能力使用既有 `GalApi` 事件信道协商，添加的动作名是 `mastergal:menu_open` 与 `mastergal:menu_result`，不会改变 `GalApi` 方法或现有数据包格式。FabricMasterGAL 0.3.0 显示带 1 至 16 个按钮的自定义 Screen；旧客户端不公布该动作，适配器保留原版库存菜单。Floodgate 玩家走现有表单映射，按钮最多 16 个。业务插件必须把回调当作操作意图，并重新查询当前状态和权限。

事件和请求处理在对应端的游戏线程。单条数据最多 8 KiB，待处理请求最多 32 个，超时或换服会结束原会话的待处理请求。在 Fabric 客户端可用 `/crossplayprobe` 测试客户端请求，`/crossplayevent` 测试双向事件，`/mastergalclient` 测试 Spigot 主动向客户端请求版本。

Carpet 类服务端功能、自定义方块和实体可以把状态与交互定义为协议消息，服务端行为由 Spigot 插件实现，Fabric Mod 实现客户端输入与渲染。局内语音可通过此 API 协商能力和会话，实时音频需要单独的传输通道。

## 基岩版表单和商店接口

基岩玩家可用代理命令 `/crossplay` 查询当前 Spigot 世界，也可用后端命令 `/mastergalform` 验证带资源包图标的表单。后者在玩家点击后由 Spigot 告知按钮编号。

商店插件可依赖 `SpigotMasterGAL`，在主线程调用 `showBedrockForm(Player, BedrockForm, IntConsumer)`。`BedrockForm` 接收标题、正文和最多 16 个按钮，按钮可引用 Bedrock 资源包内的纹理路径。回调索引从 0 开始，也可能返回 `BedrockForm.CLOSED` 或 `BedrockForm.UNAVAILABLE`。返回 `false` 表示当前请求未发出。会话断开后表单作废；购买逻辑可在回调中使用原有商店的购买校验和扣款接口。

`MasterGALMenus` 会在 `ShopOpenEvent` 处把 BedWars1058 21.11.2 的快捷购买和商品类别呈现为表单或 Fabric Screen。选中商品后，它重新确认玩家仍处于可购买的对局，然后调用 BedWars1058 的 `CategoryContent.execute`；该插件继续检查货币、价格、队伍状态和 `ShopBuyEvent`，再扣款并更新物品。编辑快捷购买仍使用 BedWars 原版库存界面。其他 BedWars 界面（包括队伍升级箱）由 Geyser 原样翻译原版库存交互；它们未被自定义表单替代。

对于 ChestCommands，适配器只拦截其自有菜单 holder，按钮最终调用该菜单的原始 `Icon.onClick`。菜单条件、权限、花费和动作解析都留在 ChestCommands。若新版本改变该可选反射入口，原版菜单不受影响，日志会记录并可移除可选适配器。

Geyser 可以分发资源包，资源包向表单提供素材。Geyser 当前不运行行为包或 Add-on 脚本。其他资源包可提供纹理供服务器表单引用，运行脚本并直接与外部服务通信则需要独立的基岩服务端环境。参见 [Geyser 资源包](https://geysermc.org/wiki/geyser/packs/)、[Floodgate 表单](https://geysermc.org/wiki/geyser/forms/)和 [Bedrock 网络脚本 API](https://learn.microsoft.com/en-us/minecraft/creator/scriptapi/minecraft/server-net/minecraft-server-net?view=minecraft-bedrock-experimental)。

## 网易实现的参考范围

`SpigotMaster-GAL/decompiled/` 是本地 CFR 输出，包含两个 JAR 内的依赖。BungeeMaster 的插件入口负责 Master 控制连接，SpigotMaster 的 `wy:pyrpc` 用 MessagePack 和三段事件名分派到处理器，`geyser:msg` 负责另一组有编号的消息。网易 `PyRpcDemo` 用 `extraClientApi` 绑定 Python 客户端事件。MasterGAL 借鉴分层、事件分派和定向回包的思路，源码与线协议独立。
