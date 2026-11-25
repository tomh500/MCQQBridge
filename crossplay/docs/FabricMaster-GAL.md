# FabricMaster-GAL 开发者文档

参阅 [SpigotMaster 事件迁移矩阵](EventCompatibility.md) 了解三段地址和结构化事件入口。

## 适用版本

| 维护线 | 0.3.1 构建包 | 构建时采用的 Fabric API |
| --- | --- | --- |
| 26.3 | `FabricMasterGAL-0.3.1+26.3.jar`，仅匹配 Minecraft 26.3 | `0.165.0+26.3` |
| 26.2 | `FabricMasterGAL-0.3.1+26.2.jar`，仅匹配 Minecraft 26.2 | `0.161.0+26.2` |

两包均为纯客户端 Mod，模组 ID 为 `fabricmastergal`，要求 **Java 25** 和 **Fabric Loader 0.19.5 或更新版本**。运行时需要 Fabric API 的 Networking、Client Command 和 Lifecycle Events 模块，安装表中对应 Minecraft 版本的完整 Fabric API 即可。Mod 元数据声明本目标构建和验证过的三个模块版本下限。前表是已构建的目标，26.2 之前和 26.3 之后的其他游戏版本需要单独适配与构建。

0.3.1 在 JDK 25、Gradle 9.6.1 和 Loom 1.17.21 构建两个目标。较早版本曾经用协议客户端验证 Bungee 至 Spigot **1.12.2、26.2** 的往返，26.3 协议也验证了换服重新协商。0.3.1 的真实客户端界面与控制操作仍待验收。命令和网络 API 在两套游戏版本间共用。输入集成另按游戏版本选择对应 API，Minecraft 26.3 起使用 SDL3。[Mojang 26.3 更新说明](https://www.minecraft.net/en-us/article/minecraft-java-edition-26-3)

从 0.3.0 起，客户端也支持 MasterGAL 服务端菜单动作：服务器最多传 16 个按钮，Mod 绘制为原生 Screen，再只回传按钮序号。界面允许在游戏窗口本地绘制，服务端仍需把选择映射到自己的权限、价格、库存与对局校验。客户端处理 Screen 的绘制、输入、关闭和会话清理。BedWars1058 与 ChestCommands 的 Java 入口继续使用插件库存。该动作继续复用 BungeeMasterGAL 0.2.0 引入的通用事件转发。

## 把 MasterGAL 加入你的 Mod

1. 在客户端 `mods/` 安装与游戏版本匹配的 FabricMasterGAL JAR 和 Fabric API。
2. 把同一个 MasterGAL JAR 加入开发项目的 Gradle 依赖。使用面向 Minecraft 26.x 的 Fabric Loom 项目时，可以用 `implementation files(...)`。把 MasterGAL 作为外部依赖发给用户，避免用 `include` 或 Shadow 将它装入你的 Mod。
3. 你的 `fabric.mod.json` 声明 `"environment": "client"`，注册你的 `client` 入口，并加入 `"fabricmastergal": ">=0.2.0"` 到 `depends`。服务端的对应业务插件通过 [SpigotMaster-GAL](SpigotMaster-GAL.md) 接入。

```groovy
dependencies {
implementation files('libs/FabricMasterGAL-0.3.1+26.3.jar')
}
```

## 客户端 API 与回调

`top.luotiany1.mcqq.crossplay.FabricMasterGAL.api()` 返回 `GalApi<Minecraft>`。这里的 `Minecraft` 是当前客户端实例，当前后端由 MasterGAL 会话确定。请在 `ClientModInitializer#onInitializeClient()` 注册动作，在客户端游戏线程调用接口。

| 方法 | 用法 |
| --- | --- |
| `onEvent(String, BiConsumer<Minecraft, byte[]>)` | 接收 Spigot 发送的单向通知，可以更新当前客户端控件或状态 |
| `onRequest(String, BiFunction<Minecraft, byte[], byte[]>)` | 处理 Spigot 主动发出的请求。立即返回字节数组，空数组表示成功且无正文，`null` 表示拒绝 |
| `onReady(Consumer<Minecraft>)` | 在新会话交换能力后初始化界面或请求快照。每次重连和换服按新会话处理，可重复执行 |
| `canSendEvent(Minecraft, String)`、`canRequest(Minecraft, String)` | 检查当前后端是否公布对应能力，用于控制按钮或提示 |
| `sendEvent(Minecraft, String, byte[])` | 发送动作。返回 `true` 表示提交传输，`false` 表示没有公布对应能力 |
| `request(Minecraft, String, byte[])` | 异步获得回包。用 `whenComplete` 处理失败；不要在客户端线程上阻塞等待 |

动作名最长 80 个 ASCII 字符，使用 `命名空间:动作`，格式为 `[a-z0-9_.-]+:[a-z0-9_./-]+`。每端最多 64 个不同动作名，单条正文最多 8 KiB，每个会话最多 32 个待完成请求。超时阈值为 5 秒，实际由游戏 tick 检查。断开和换服会使旧请求异常结束；需要显示的界面状态应随连接失效清理，并在新会话准备好后重新请求。客户端处理器或完成回调应尽快返回。如果在其他线程对 Future 注册异步后续操作，访问游戏对象前用 `client.execute(...)` 切回客户端线程。

## 示例 Mod

以下代码与 [Spigot 示例](SpigotMaster-GAL.md#示例插件) 配对。将 `top.luotiany1.examplegal.ExampleGalClient` 写入你的 `fabric.mod.json` 的 `entrypoints.client`。

```java
package top.luotiany1.examplegal;

import java.nio.charset.StandardCharsets;
import net.fabricmc.api.ClientModInitializer;
import net.minecraft.client.Minecraft;
import net.minecraft.network.chat.Component;
import top.luotiany1.mcqq.crossplay.FabricMasterGAL;
import top.luotiany1.mcqq.crossplay.GalApi;

public final class ExampleGalClient implements ClientModInitializer {
    @Override
    public void onInitializeClient() {
        GalApi<Minecraft> api = FabricMasterGAL.api();
        api.onEvent("examplegal:notice", (client, payload) ->
                message(client, new String(payload, StandardCharsets.UTF_8)));
        api.onRequest("examplegal:client_status", (client, payload) ->
                payload.length == 0 ? "ready".getBytes(StandardCharsets.UTF_8) : null);
        api.onReady(client -> {
            if (api.canRequest(client, "examplegal:catalog")) {
                api.request(client, "examplegal:catalog", new byte[0]).whenComplete((data, failure) -> {
                    if (failure != null) {
                        message(client, "目录暂不可用");
                    } else {
                        String catalog = new String(data, StandardCharsets.UTF_8);
                        message(client, "可查看 " + catalog.replace('\n', '、'));
                    }
                });
            }
        });
    }

    private static void message(Minecraft client, String text) {
        if (client.player != null) {
            client.player.sendSystemMessage(Component.literal(text));
        }
    }
}
```

## 验收与排查

- `/crossplayevent` 会发出客户端事件，并展示 Spigot 返回的事件。它能验证通用事件通道。
- `/mastergalclient` 由 Spigot 主动请求 Fabric 返回游戏版本，用于验证反向请求及回包。
- `/crossplayprobe` 查询当前世界。它在通用请求可用时优先使用通用 API，必要时使用旧版探测通道。因此，单独此命令成功不足以验证业务能力已经交换。
- 业务按钮不可用时，先检查正确的客户端构建，再检查 Mod 是否在初始化阶段注册了动作、玩家当前后端是否安装对应业务插件，以及动作名和方向是否相同。换服后重新等待 `onReady`。

API 定义可参阅 [GalApi.java](../common/src/main/java/top/luotiany1/mcqq/crossplay/GalApi.java)，代理的通道和会话约束见 [BungeeMaster-GAL](BungeeMaster-GAL.md)。
