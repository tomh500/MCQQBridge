# ForgeMaster 接入契约

- Minecraft 1.12.2，Forge 14.23.5.2860，Java 8。模组 ID 为 `forgemaster`，显示名为 `ForgeMaster`，版本为 `0.1.0`。依赖模组应声明 `required-after:forgemaster@[0.1.0,)`，客户端初始化时注册处理器。
- 入口为 `top.luotiany1.mcqq.crossplay.ForgeMaster`。静态方法 `api()` 返回 `GalApi<net.minecraft.client.Minecraft>`，`events()` 返回 `GalEventApi<Minecraft>`。二者使用现有 MasterGAL 的接口、动作名和编码。需要关闭语音流、清除图片或取消尚未交付的异步结果时，注册 `ForgeMaster.onSessionClosed(Consumer<Minecraft>)`。
- 接口仅在客户端使用。在 Forge 客户端的 FML 初始化阶段注册 `onEvent`、`onRequest`、`onReady` 或结构化事件监听器。收包回调、换服回调、请求超时均在客户端游戏线程执行。后台线程访问 Minecraft 或调用 API 前，用 `Minecraft.addScheduledTask` 调度回游戏线程。
- 客户端通道为 `mcqq:gal`，兼容探针为 `mcqq:crossplay`。代理仍通过 `mcqq:galbus` 和 `mcqq:crossbus` 与 Spigot 通信。Forge 1.12.2 使用原样字符串通道和 GAL v1 帧。收到通道声明后才发 HELLO，收到 WELCOME 后才能发送对端公布的业务动作。Bungee RESET、通道撤销或断线会撤销旧能力并终止旧会话请求。在新会话中通过 `api().onReady(...)` 重新同步状态。
- 自定义动作名采用现有 `命名空间:动作` 语法，最长 80 个 ASCII 字符。每端最多 64 个动作、每会话最多 32 个挂起请求、单帧业务正文不超过 8192 字节。保留 GalVoice 现有动作。图片描述或图片数据分片由图片 Mod 的配对服务端定义。新功能通过事件能力广告和 `canSendEvent`、`canRequest` 控制。
- 构建依赖路径锁定为 `crossplay/forge/build/libs/ForgeMaster-0.1.0-dev.jar`（MCP 名开发包）。部署到 Minecraft 的路径为 `crossplay/forge/build/libs/ForgeMaster-0.1.0.jar`（SRG 重映射）。ForgeGradle 3 项目可用 `compileOnly files('path/to/ForgeMaster-0.1.0-dev.jar')` 和 `runtimeOnly files('path/to/ForgeMaster-0.1.0-dev.jar')`。发行时单独安装 ForgeMaster。

## 本地构建

将 `JAVA_HOME` 指向 Java 8 JDK。从检出根目录运行 `crossplay\forge\gradlew.bat -p crossplay/forge build`。项目锁定 Gradle 4.9、ForgeGradle 3.0.197 和 MCP `snapshot_20171003-1.12`。首次构建需要访问 Forge Maven、Maven Central 和 Mojang 的依赖服务。

`/crossplayprobe` 优先通过 GAL 查询当前世界。旧代理仍可通过 `mcqq:crossplay` 提供查询。`/crossplayevent` 验证通用单向事件及服务端返回的通知。Spigot 的 `/mastergalclient` 主动请求客户端版本。

## 本地验收

发行 JAR 在真实 Forge 14.23.5.2860 客户端中加载。回环测试使用 BungeeMasterGAL 0.3.1 与两个 Spigot 1.12.2 后端（SpigotMasterGAL 0.4.0），覆盖首次能力协商、双向请求、双向二进制和结构化事件、换服后旧请求取消及重新协商，以及服务端菜单选择回传。单独用 BungeeMasterGAL 0.1.0 验证了 `/crossplayprobe` 回退到旧查询通道。

本次本地验收产物的 SHA-256

| 文件 | SHA-256 |
| --- | --- |
| `ForgeMaster-0.1.0-dev.jar` | `70e0cbeaa3595a16f0c604af97d01dd7cac37bdfd6eabd7843f313a3c86eeb4f` |
| `ForgeMaster-0.1.0.jar` | `87c0aa62355f104b92c72025679a7a16e00c3e685dfa44ff656790969d9c7035` |
