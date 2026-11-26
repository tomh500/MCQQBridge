# MCQQ Images for Forge 1.12.2

这是 Java 8 客户端模组，适配 Minecraft 1.12.2 和 Forge 14.23.5.2860。把构建的 `mcqq-images-forge112-1.0.0.jar` 放进该实例的 `mods/`。服务端继续使用能够发送 QQ 图片链接的 MCQQBridge 代理插件。

模组读取聊天组件中包含 `OPEN_URL` 的 `[图片]` 或 `[表情包]` 标签。不需要 ForgeMaster，也没有新增插件消息通道。服务器原有的 QQ 群路由和玩家可见范围照常生效。图片预览随聊天记录滚动，打开聊天后点击预览可以放大，按 Esc 或再次点击关闭。原聊天链接保留，可用 Minecraft 的链接确认界面打开。

首次启动会创建 `config/mcqq-images.properties`。默认允许 QQ 图片域名。如果运营者设置了公开媒体地址（即 MCQQBridge 的 `media.public_base_url`），在客户端配置中加入对应前缀。可以配置多个，以逗号分隔，每个都要以 `/` 结尾。

```properties
enabled=true
trusted-media-bases=https://images.example.com/mcqq-media/
```

仅配置玩家可访问的媒体前缀。修改配置后重启客户端。设置 `enabled=false`，或关闭 Minecraft 的聊天链接选项，即可停用预览。预览支持 PNG、JPEG 和 GIF，限制 8 MiB、单边 8192 像素和总计 16777216 个源像素，GIF 最多 48 帧。下载和解码在后台完成，纹理在客户端游戏线程维护。其他格式仍可通过原聊天链接打开。

## 构建与验证

使用 Java 8 JDK，先将 `JAVA_HOME` 指向它。进入本目录执行以下命令。Linux/macOS 用 `./gradlew` 替代 `.\gradlew.bat`。

```powershell
.\gradlew.bat clean build previewProbe
```

可安装的重映射 JAR 位于 `build/libs/mcqq-images-forge112-1.0.0.jar`。独立的 `previewProbe` 使用本机 HTTP 服务检验下载边界、重定向、PNG 和 GIF 解码。

隔离客户端验证可在 Minecraft 1.12.2 服务端发送 `tellraw <player> {"text":"QQ","extra":[{"text":" [图片]","clickEvent":{"action":"open_url","value":"https://images.example.com/mcqq-media/example.png"}}]}`。把 URL 换成客户端信任且可访问的 PNG。聊天应保留原标签并出现预览。打开聊天后可尝试点击预览、关闭、滚动和切换世界。
