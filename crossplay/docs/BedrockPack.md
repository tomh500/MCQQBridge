# BedrockPack 开发者文档

## 适用版本

| 项目 | 当前版本 |
| --- | --- |
| 资源包文件及显示名 | `MasterGAL.mcpack`，游戏内为 `MasterGAL` |
| 资源包版本 | `0.1.0` |
| 清单格式与最低引擎声明 | `format_version: 2`，`min_engine_version: [1, 21, 0]` |
| 表单桥接组件 | SpigotMasterGAL **0.4.0** 和 BungeeMasterGAL **0.3.0** |
| 已核对的代理组合 | Geyser-BungeeCord **2.12.1-b1281** 和 Floodgate **2.2.5-SNAPSHOT（b141-81b65cc）** |

最低引擎声明约束资源包本身。能否加入服务器，还取决于运行中的 Geyser 构建支持哪些 Bedrock 协议。当前资源包已通过该 Geyser 版本的包读取检查，真实客户端的下载、显示和表单点击仍需验收。

## 资源包与表单的职责

BedrockPack 的开发接口是资源包清单和包内素材路径。表单由服务端生成，点击通过 Floodgate 和 BungeeMasterGAL 回到当前 Spigot 后端。为商店增加一个按钮时，资源包提供图标，业务插件决定展示哪些商品以及玩家点击后执行什么操作。需要运行行为包脚本时，使用支持该脚本的基岩服务端环境。Geyser 的资源包分发可与服务端表单配合使用。[Geyser 资源包与行为包支持](https://geysermc.org/wiki/geyser/packs/)

Geyser 可把 Java 原版库存菜单转换为 Bedrock 容器界面，原插件仍收到正常服务端点击。需要独立表单时，Floodgate 的 SimpleForm 提供标题、正文、按钮和可选路径/URL 图片；它不是任意布局画布，按钮点击只能回传选择编号。服务器资源包可下发图片并调整 Bedrock UI 的外观，但不能给 Geyser 代理添加行为包脚本，也不能为表单按钮编写客户端业务代码。[Floodgate 表单类型与图片](https://geysermc.org/wiki/geyser/forms/) [Geyser 资源包和 Add-on 支持范围](https://geysermc.org/wiki/geyser/packs/)

MasterGAL 的 `GalMenu.Button(label, texture)` 会把纹理路径传给 Bedrock 表单；将 PNG 放到资源包对应路径后，必须提升资源包清单版本，确保 Bedrock 客户端重新加载新内容。Java Fabric 自定义交互由客户端 Mod 的 Screen 绘制，不能通过 Bedrock 资源包文件替代。

## 包结构、构建与更新

```text
MasterGAL.mcpack
├── manifest.json
└── textures/
    └── ui/
        └── mastergal/
            └── probe.png
```

`manifest.json` 应位于 ZIP 根目录。模块类型为 `resources`，清单头和资源模块各有自己的 UUID。更新同一个包时保留 UUID，递增头部及模块版本。发布由你维护的独立附加资源包时使用新的 UUID，并采用自己的纹理子目录，避免覆盖内置图标。

在 `crossplay` 目录运行以下命令可构建内置包，依赖 Python 3。

```powershell
python bedrock/build-pack.py
```

脚本将现有 [manifest.json](../bedrock/manifest.json) 与生成的 `probe.png` 写入 `build/MasterGAL.mcpack`。它只打包内置图标。为同一个包增加素材时，在 [build-pack.py](../bedrock/build-pack.py) 中把新 PNG 以对应的归档路径加入 ZIP。制作独立资源包时，可在自己的打包目录中同时放置 `manifest.json` 和 `textures/`，再将两者作为根条目打包为 `.mcpack`。

安装到 `proxy/plugins/Geyser-BungeeCord/packs/`。重启代理或按 Geyser 的方式重载，再从基岩客户端重新连接。Geyser 在连接时提供资源包。代理换到其他 Spigot 后端时，客户端仍使用此次连接已加载的资源包。[Geyser 本地资源包部署](https://geysermc.org/wiki/geyser/packs/)

## 从 Spigot 引用素材和接收点击

以下片段可放在 Bukkit 主线程上的命令或交互处理器里。`bridge` 是已加载的 `SpigotMasterGAL`，`player` 是当前 Bukkit 玩家。示例使用内置素材，可在自有资源包装好后，将路径换成 `textures/ui/your_pack/shop.png`。

```java
BedrockForm form = new BedrockForm("商店", "选择一个分类", Arrays.asList(
        new BedrockForm.Button("材料", "textures/ui/mastergal/probe.png"),
        new BedrockForm.Button("退出")));

boolean accepted = bridge.showBedrockForm(player, form, result -> {
    if (result == 0) {
        player.sendMessage("你选择了材料分类");
    } else if (result == BedrockForm.UNAVAILABLE) {
        player.sendMessage("表单暂时无法使用");
    }
});
```

使用 `top.luotiany1.mcqq.crossplay.BedrockForm` 和 `java.util.Arrays`。按钮只有文案和可选纹理，1 至 16 个按钮按列表顺序排列。纹理路径只使用允许的小写字母、数字、下划线、连字符和目录分隔符，文件名可带 `.png` 后缀。保持路径大小写与包内条目一致。

`accepted` 为 `false` 时表单未发送且不会进入回调。回调以 0 为第一个按钮，`CLOSED (-1)` 代表关闭或无效选择，`UNAVAILABLE (-2)` 代表投递失败或超时。换服或退出导致原后端清理表单时，回调可能不执行。消费者应在业务侧校验选择，再修改游戏状态。完整签名、字符限制和回调时序见 [SpigotMaster-GAL](SpigotMaster-GAL.md#基岩表单与回调)。

## 游戏内验收

1. 使用基岩客户端连接 Geyser，确认已接收并启用对应包版本。
2. 执行后端命令 `/mastergalform`。第一项使用 `probe.png`，第二项仅显示文字。
3. 分别测试点击、关闭和换服。点击时聊天栏应显示 Spigot 收到的按钮编号，诊断命令显示从 1 开始的编号，业务回调仍从 0 开始。

如果按钮能点但图标缺失，先核对清单更新版本、包是否已下发以及 ZIP 内路径。若表单本身打不开，查看 [BungeeMaster-GAL](BungeeMaster-GAL.md#验收与排查) 的 Geyser、Floodgate 及后端通道检查。
