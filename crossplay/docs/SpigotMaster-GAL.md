# SpigotMaster-GAL 开发者文档

## 适用版本

本文对应 **SpigotMasterGAL 0.3.0**。后端已用 Spigot **1.12.2** 和 **26.2** 完成 Java 协议往返测试。JAR 使用 Java 8 字节码，运行时仍须符合所选 Spigot 核心的要求，测试中分别使用了 Java 8 和 Java 25。Fabric 端已有 **26.2、26.3** 两个构建，接入旧后端时仍需能转换对应 Minecraft 协议的 Via 组件。Bedrock 表单经 BungeeMasterGAL **0.2.0**、Geyser 和 Floodgate 转接，实机按钮验收仍待完成。0.3.0 新增菜单消息，复用 0.2.0 通用信道，代理不需要升级。

## 安装与编译依赖

将 `SpigotMasterGAL-0.3.0.jar` 放入每个需要接入的后端 `plugins/`。业务插件编译时依赖发行 JAR，运行时由 Bukkit 加载已安装的插件，避免把 MasterGAL 打进业务插件 JAR。

```groovy
dependencies {
    compileOnly files('libs/SpigotMasterGAL-0.3.0.jar')
}
```

在业务插件的 `plugin.yml` 声明 `depend: [SpigotMasterGAL]`。Gradle 片段只配置 MasterGAL，项目原有的 Spigot API 依赖仍用于编译 Bukkit 类型。如果同一业务 JAR 要覆盖 1.12.2，业务代码和依赖也需要兼容 Java 8 与该版本 Bukkit。

## Java API

`top.luotiany1.mcqq.crossplay.SpigotMasterGAL#api()` 返回 `GalApi<Player>`。从业务插件的 `onEnable()` 注册能力。调用、注册和业务处理都应在 Bukkit 主线程上完成。

| 方法 | 行为 |
| --- | --- |
| `onEvent(String, BiConsumer<Player, byte[]>)` | 注册单向事件。回调获得当前连接对应的 Bukkit 玩家及数据 |
| `onRequest(String, BiFunction<Player, byte[], byte[]>)` | 注册同步请求。返回字节数组作为回包，空数组表示成功且正文为空，返回 `null` 表示拒绝。处理器异常也会产生失败回包 |
| `onReady(Consumer<Player>)` | 新会话完成能力交换时回调。通常会在首次接入和切到本后端后各触发一次 |
| `canSendEvent(Player, String)`、`canRequest(Player, String)` | 检查该玩家当前会话是否公布了对应接收能力 |
| `sendEvent(Player, String, byte[])` | 对端公布对应能力时发出事件。返回 `false` 表示当前会话无法发出，`true` 只表示已提交传输 |
| `request(Player, String, byte[])` | 返回 `CompletableFuture<byte[]>`。对端拒绝、能力不可用、传输失败、待处理数达到上限、超时或会话结束时以异常完成 |

服务端额外提供 `showMenu(Player, GalMenu, IntConsumer)`：1 至 16 个有标签按钮，结果回调与表单一样从 0 开始，另有 `GalMenu.CLOSED` 和 `GalMenu.UNAVAILABLE`。最新版 FabricMasterGAL 通过可选能力 `mastergal:menu_open` 显示 Minecraft 原生 Screen，再以 `mastergal:menu_result` 回传按钮序号。旧版客户端没有该能力时此方法会尝试 Floodgate 表单；Java 旧客户端最终得到 `UNAVAILABLE`，调用方应打开原版库存菜单。此方法及新动作是新增兼容项，不改变 0.2.0 的既有 GalApi 签名或数据包编码。表单和自定义 Screen 都只传递按钮选择，不授予客户端修改服务器状态的权限。

使用自己的命名空间，例如 `examplegal:catalog`。动作名最长 80 个 ASCII 字符，完整格式为 `[a-z0-9_.-]+:[a-z0-9_./-]+`。每个端点最多 64 个不同动作名。同名动作可以分别注册事件和请求，同类处理器重复注册会抛出异常。0.3.0 暂无公开注销或向现有会话主动刷新能力的接口，建议在初始化阶段完成注册。

每条消息的业务正文最多 8 KiB，每个会话最多 32 个待完成请求。请求时限为 5 秒，由服务端定时检查，因此失败回调可稍晚执行。需要正文为空时传 `new byte[0]`。使用 `whenComplete` 等非阻塞回调，避免在游戏线程上调用 `get()` 或 `join()`。请求处理器适合快速操作。耗时业务可以先回任务编号，异步处理后再通过事件发送结果，发消息及修改 Bukkit 状态前切回主线程。

## 示例插件

以下示例与 [Fabric 示例](FabricMaster-GAL.md#示例-mod) 配对。Fabric 查询目录并接收通知，Spigot 也会主动查询 Fabric 模组状态。

```yaml
name: ExampleGalCatalog
version: 1.0.0
main: top.luotiany1.examplegal.ExampleGalCatalog
depend: [SpigotMasterGAL]
commands:
  galcatalog:
    description: 打开基岩版示例目录
```

```java
package top.luotiany1.examplegal;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import org.bukkit.command.Command;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Player;
import org.bukkit.plugin.java.JavaPlugin;
import top.luotiany1.mcqq.crossplay.BedrockForm;
import top.luotiany1.mcqq.crossplay.GalApi;
import top.luotiany1.mcqq.crossplay.SpigotMasterGAL;

public final class ExampleGalCatalog extends JavaPlugin {
    private static final byte[] EMPTY = new byte[0];
    private SpigotMasterGAL bridge;

    @Override
    public void onEnable() {
        bridge = (SpigotMasterGAL) getServer().getPluginManager().getPlugin("SpigotMasterGAL");
        GalApi<Player> api = bridge.api();
        api.onRequest("examplegal:catalog", (player, payload) -> {
            if (payload.length != 0) {
                return null;
            }
            return "羊毛\n玻璃".getBytes(StandardCharsets.UTF_8);
        });
        api.onReady(player -> {
            api.sendEvent(player, "examplegal:notice", "目录可用".getBytes(StandardCharsets.UTF_8));
            if (api.canRequest(player, "examplegal:client_status")) {
                api.request(player, "examplegal:client_status", EMPTY).whenComplete((bytes, failure) -> {
                    if (failure == null) {
                        getLogger().info(player.getName() + " 客户端状态 "
                                + new String(bytes, StandardCharsets.UTF_8));
                    }
                });
            }
        });
    }

    @Override
    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (!(sender instanceof Player)) {
            return false;
        }
        Player player = (Player) sender;
        BedrockForm form = new BedrockForm("示例目录", "选择要查看的材料", Arrays.asList(
                new BedrockForm.Button("羊毛", "textures/ui/mastergal/probe.png"),
                new BedrockForm.Button("玻璃")));
        if (!bridge.showBedrockForm(player, form, index -> {
            if (index >= 0) {
                player.sendMessage("已选择 " + form.buttons.get(index).label);
            } else if (index == BedrockForm.UNAVAILABLE) {
                player.sendMessage("当前无法显示基岩版目录");
            }
        })) {
            player.sendMessage("当前连接无法发出新表单");
        }
        return true;
    }
}
```

## 基岩表单与回调

`boolean showBedrockForm(Player, BedrockForm, IntConsumer)` 需要在 Bukkit 主线程调用。表单有标题、正文和 1 至 16 个按钮。标题和按钮标题最多 128 个 Java 字符单位，正文最多 2048。可选图标路径最多 149 个字符，使用资源包中的 `textures/…`，目录及文件名仅使用小写 ASCII 字母、数字、下划线、连字符，可带 `.png` 后缀。填写图标时应同时交付资源包。

| 结果 | 含义 |
| --- | --- |
| 方法返回 `false` | 表单未发出，例如玩家离线、通道不可用或已有待处理表单。此时不会调用回调 |
| 方法返回 `true` | 已尝试向代理发出。代理仍需识别基岩会话并交付表单 |
| 回调值 `0` 至按钮数减一 | 玩家选择了对应位置的按钮。顺序与构造表单时传入的列表一致 |
| `BedrockForm.CLOSED`（`-1`） | 玩家关闭，或代理收到无效选择 |
| `BedrockForm.UNAVAILABLE`（`-2`） | 代理无法投递，玩家是 Java 版，或 1200 服务器 tick 后仍无结果 |

玩家离开当前后端或插件停用时，挂起表单会被清理，业务代码不能依赖必有回调。商店可在回调里根据原菜单映射找商品，并用当前价格、余额、库存、权限重新校验后再提交购买。按钮索引和客户端数据只表示玩家的操作意图。

用 `/mastergalclient` 验证 Spigot 向 Fabric 主动发请求，用 `/mastergalform` 验证 Spigot 发出的基岩表单。相关文档可参阅 [代理路由](BungeeMaster-GAL.md)、[Fabric 开发接入](FabricMaster-GAL.md) 和 [资源包制作](BedrockPack.md)。接口定义见 [GalApi.java](../common/src/main/java/top/luotiany1/mcqq/crossplay/GalApi.java)。
