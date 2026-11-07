# MC QQ Images (Fabric 26.2)

The maintained universal version now lives in the separate public repository [tomh500/mcqq-images](https://github.com/tomh500/mcqq-images), covering Minecraft 1.21.4 through 26.3 in one JAR. Use that repository's releases and build instructions. This directory retains the original 26.2-specific implementation for reference.

Install `mcqq-images-1.0.0+26.2.jar` from `qqbot/dist` in the Minecraft 26.2 client's `mods` directory, alongside Fabric Loader 0.19.3+ and Fabric API for **26.2**. Restart the game. The proxy/server does not load this client-only JAR.

QQ image and sticker links are recognized from the chat component's `open_url` click action. The right-hand HUD shows up to three recent previews for 30 seconds; opening chat shows cached previews again. Clicking the original `[图片]` / `[表情包]` still opens the source URL. Plain clients retain clickable links without installing this mod.

PNG/JPEG and GIF frames are decoded in background threads. Animated GIFs preserve per-frame timing and disposal; previews are scaled to at most 512 pixels, at most48 frames and8 megapixels total. At most6 images remain in memory; textures expire after one hour and are released on disconnect. Unsupported image formats (including WebP without an ImageIO reader) leave the original clickable link usable. The decoder rejects oversized downloads and dimensions. Downloads only use QQ image hosts and this server's expiring media endpoint; redirects are checked as well.

This binary targets the Minecraft **26.2** rendering API used by the provided client screenshot. Minecraft26.1/26.3 are not declared compatible without a separate build and runtime check. Other mods that suppress Fabric's incoming-message or HUD events may affect previews; normal clickable links continue to work.

Build with Java25 / Gradle9.6.1 and the included Fabric Loom project, or run `../.venv/Scripts/python build.py` from this directory. The Python build uses the official unobfuscated26.2 client and checksummed Fabric API dependencies, then tests PNG colors, animated GIF frames/timing and oversized-image rejection. GUI rendering is compiled against the26.2 API; an actual player client is still required for visual acceptance.

自建图片服务需在 config/mcqq-images.properties 的 trusted-media-bases 填入以 / 结尾的受信任 URL 前缀，多项用逗号分隔。默认仅信任 QQ 图片域名。
