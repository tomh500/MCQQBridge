# SpigotMaster-GAL 事件迁移

这组 Java API 对齐网易 SpigotMaster 开发文档中的定向事件调用方式。对照使用工作区的《SpigotMasterAPI 文档》和《Spigot 服与客户端 Python 通信》，在线参考为社区保留的文档镜像。网易官方开发文档站此次未能访问。网易正式版用户协议第 4–5 条说明其软件、手册和素材的许可范围。本实现依据可公开查看的接口行为设计，使用项目自己的代码、名字编码和 GAL 数据格式，所有 JAR 仅编译本项目源码。 [通信文档镜像](https://mcwiki.easecation.net/mcguide/27-%E6%89%8B%E6%9C%BA%E7%BD%91%E7%BB%9C%E6%B8%B8%E6%88%8F/%E8%AF%BE%E7%A8%8B10%EF%BC%9A%E4%BD%BF%E7%94%A8Spigot%E5%BC%80%E6%9C%8D/21-Spigot%E6%9C%8D%E4%B8%8E%E5%AE%A2%E6%88%B7%E7%AB%AFpython%E9%80%9A%E4%BF%A1%E5%8E%9F%E7%90%86%E7%AE%80%E4%BB%8B.html) · [网易官方用户协议](https://protocol.unisdk.netease.com/release/latest_v15.html)

| 网易开发文档的接口或模型 | 本项目入口与迁移方式 |
| --- | --- |
| Spigot `listenForEvent(namespace, system, event, handler)` | 同名方法，使用 `BiConsumer<Player, Map<String, Object>>`。服务端以当前连接传入的 `Player` 为准 |
| Spigot `notifyToClient` | 同名定向事件。返回 `boolean` 表示是否提交给声明了相应事件的连接 |
| Spigot `notifyToMultiClients`、`notifyToClientsNearby` | 同名方法，返回成功提交的玩家数。附近发送限制在所给位置的世界，可排除一名玩家 |
| Python `ListenForEvent`、`NotifyToServer` | Fabric Java 调用 `FabricMasterGAL.listenForEvent`、`FabricMasterGAL.notifyToServer`，发送时显式写出命名空间和来源系统 |
| Python 事件字典与 Java Map | 双方 Java 使用 `Map<String, Object>`，支持字符串键、嵌套 Map/List、null、Boolean、Integer、Long、Double、String 和无符号 64 位 BigInteger；Byte 和 Short 解码为 Integer，Float 解码为 Double |
| 请求、回包和失败 | 需要应答时用现有 `GalApi.onRequest/request`；事件发送结果仅表示已提交 |
| 中国版客户端、Python 运行时和 PyRpc 包 | 本项目使用 Fabric Java、GAL 能力协商及 `mcqq:gal`/`mcqq:galbus` 信道。迁移需要在两端改用本项目 API，线协议互通未验证 |
| 自定义实体、UI 渲染与原生客户端事件 | 每个功能按目标 Minecraft 的 API 单独实现；实体标识由业务协议定义，服务端重新授权 |
| Forge 与 NeoForge | 可选 Beta 候选。当前无构建产物或验收结果。Fabric 26.2 与 26.3 是本次完成构建的客户端目标 |

事件地址由命名空间、来源系统和事件名组成，区分大小写。三段使用字母、数字、下划线、点或连字符，总长度在 GAL 转义后不得超过 80 字符。在插件或 Mod 初始化时注册同一事件的一个监听器；连接就绪后发送，随服务器切换重新协商。事件消息最多 8 KiB，每个集合最多 256 项，集合嵌套有深度限制。端点拒绝无效载荷，仍由业务插件验证字段、玩家权限和游戏状态。

示例给 Fabric 目录控件发送一条服务端计算的状态。服务端插件依赖 Bukkit 加载名 `SpigotMasterGAL`，Fabric Mod 依赖 `fabricmastergal`。

```java
// Spigot 插件初始化，bridge 是 SpigotMasterGAL 实例。
bridge.listenForEvent("example", "CatalogClient", "StatusRequested", (player, ignored) -> {
    java.util.Map<String, Object> state = java.util.Collections.singletonMap(
            "canBrowse", player.hasPermission("example.catalog"));
    bridge.notifyToClient(player, "example", "CatalogServer", "StatusUpdated", state);
});
```

```java
// Fabric Mod 初始化。
FabricMasterGAL.listenForEvent("example", "CatalogServer", "StatusUpdated", (client, state) -> {
    if (client.player != null) {
        client.player.sendSystemMessage(net.minecraft.network.chat.Component.literal(
                Boolean.TRUE.equals(state.get("canBrowse")) ? "可浏览目录" : "无浏览权限"));
    }
});
FabricMasterGAL.api().onReady(client -> FabricMasterGAL.notifyToServer(
        "example", "CatalogClient", "StatusRequested", java.util.Collections.emptyMap()));
```

本地测试用两个 GAL 端点验证能力协商、结构化事件双向收发、整数精度、无效载荷拒绝及切服后失效。真实 Fabric 客户端接入代理和业务界面仍需验收。
