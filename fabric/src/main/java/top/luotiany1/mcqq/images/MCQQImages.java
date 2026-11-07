package top.luotiany1.mcqq.images;

import com.mojang.blaze3d.platform.NativeImage;
import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Executors;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.message.v1.ClientReceiveMessageEvents;
import net.fabricmc.fabric.api.client.networking.v1.ClientPlayConnectionEvents;
import net.fabricmc.fabric.api.client.rendering.v1.hud.HudElementRegistry;
import net.fabricmc.fabric.api.client.rendering.v1.hud.VanillaHudElements;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.client.gui.components.ChatComponent;
import net.minecraft.client.gui.screens.ChatScreen;
import net.minecraft.client.multiplayer.chat.GuiMessage;
import net.fabricmc.fabric.api.client.screen.v1.ScreenEvents;
import net.minecraft.client.renderer.RenderPipelines;
import net.minecraft.client.renderer.texture.DynamicTexture;
import net.minecraft.network.chat.ClickEvent;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.Identifier;

public final class MCQQImages implements ClientModInitializer {
    private static final int MAX_BYTES = 8 * 1024 * 1024;
    private static final String[] QQ_HOSTS = {"qq.com", "qq.com.cn", "qpic.cn", "gtimg.cn", "gtimg.com", "idqqimg.com", "qlogo.cn"};
    private static final java.util.List<URI> MEDIA_BASES = new java.util.ArrayList<>();
    private static void loadMediaConfig() {
        java.nio.file.Path file = net.fabricmc.loader.api.FabricLoader.getInstance().getConfigDir().resolve("mcqq-images.properties");
        java.util.Properties config = new java.util.Properties();
        try {
            if (!java.nio.file.Files.exists(file)) java.nio.file.Files.writeString(file, "# Comma-separated trusted media base URLs, for example https://images.example.com/mcqq-media/\ntrusted-media-bases=\n");
            try (var in=java.nio.file.Files.newBufferedReader(file)) { config.load(in); }
            for(String value:config.getProperty("trusted-media-bases", "").split(",")) {
                if(value.isBlank()) continue;
                URI uri=URI.create(value.trim());
                if(uri.getHost()!=null && uri.getUserInfo()==null && uri.getQuery()==null && uri.getFragment()==null && ("https".equals(uri.getScheme()) || "http".equals(uri.getScheme())) && uri.getPath().endsWith("/")) MEDIA_BASES.add(uri.normalize());
            }
        } catch(Exception ignored) { }
    }
    private static final int IMAGE_LINES = 7;
    private final Map<Component, List<URI>> chatImages = new java.util.WeakHashMap<>();
    private java.lang.reflect.Field chatLines, chatScroll;
    private final Minecraft client = Minecraft.getInstance();
    private final Map<String, Preview> previews = new LinkedHashMap<>();
    private final java.util.concurrent.ExecutorService workers = Executors.newFixedThreadPool(2, runnable -> {
        Thread thread = new Thread(runnable, "MCQQ image download"); thread.setDaemon(true); return thread;
    });
    private final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).followRedirects(HttpClient.Redirect.NEVER).build();
    private static final class Preview {
        final String caption; final long created = System.currentTimeMillis();
        final List<Identifier> frames = new ArrayList<>(); final List<Integer> delays = new ArrayList<>();
        int width, height; boolean failed;
        Preview(String caption) { this.caption = caption; }
        Identifier frame(long time) {
            long duration = delays.stream().mapToInt(Integer::intValue).sum();
            long offset = Math.floorMod(time-created, Math.max(1,duration));
            for (int i=0;i<delays.size();i++) { offset -= delays.get(i); if (offset < 0) return frames.get(i); }
            return frames.getFirst();
        }
    }
    @Override public void onInitializeClient() {
        loadMediaConfig();
        try {
            chatLines = ChatComponent.class.getDeclaredField("trimmedMessages");
            chatScroll = ChatComponent.class.getDeclaredField("chatScrollbarPos");
            chatLines.setAccessible(true); chatScroll.setAccessible(true);
        } catch (ReflectiveOperationException error) {
            System.err.println("[MCQQ Images] Chat integration unavailable: " + error);
            return;
        }
        ClientReceiveMessageEvents.MODIFY_GAME.register((message, overlay) -> {
            if (overlay) return message;
            List<URI> links = new ArrayList<>();
            findLinks(message, links);
            if (links.isEmpty()) return message;
            var result = message.copy();
            // Native chat wrapping and scrolling own these placeholder lines.
            for (int i=0; i<IMAGE_LINES*links.size(); i++) result.append("\n ");
            chatImages.put(result, List.copyOf(links));
            return result;
        });
        HudElementRegistry.attachElementAfter(VanillaHudElements.CHAT, Identifier.fromNamespaceAndPath("mcqq_images", "chat_images"), (graphics, delta) -> {
            if (!(client.gui.screen() instanceof ChatScreen)) render(graphics);
        });
        ScreenEvents.AFTER_INIT.register((minecraft, screen, width, height) -> {
            if (screen instanceof ChatScreen) ScreenEvents.afterExtract(screen).register((s, graphics, mouseX, mouseY, delta) -> render(graphics));
        });
        ClientPlayConnectionEvents.DISCONNECT.register((handler, minecraft) -> client.execute(() -> { clear(); chatImages.clear(); }));
    }
    private void findLinks(Component component, List<URI> links) {
        var click = component.getStyle().getClickEvent();
        if (click instanceof ClickEvent.OpenUrl link && (component.getString().contains("[图片]") || component.getString().contains("[表情包]"))
            && allowed(link.uri()) && links.size() < 8) links.add(link.uri());
        for (Component child : component.getSiblings()) findLinks(child, links);
    }
    private Preview preview(URI uri) {
        String key=uri.toString();
        Preview result=previews.get(key);
        if (result==null) {
            while (previews.size()>=6) evict(previews.keySet().iterator().next());
            result=new Preview(""); previews.put(key,result);
            Preview requested=result; workers.execute(() -> load(uri,requested));
        }
        return result;
    }
    static boolean allowed(URI uri) {
        String host = uri.getHost();
        if (host == null || uri.getUserInfo() != null || uri.getFragment() != null) return false;
        if (!"https".equals(uri.getScheme()) && !"http".equals(uri.getScheme())) return false;
        String rawPath=uri.getRawPath();
        if(rawPath==null || rawPath.toLowerCase(java.util.Locale.ROOT).matches(".*%(2e|2f|5c).*"))return false;
        host = host.toLowerCase(java.util.Locale.ROOT);
        for(URI base: MEDIA_BASES) if(host.equalsIgnoreCase(base.getHost()) && uri.getScheme().equals(base.getScheme()) && uri.getPort()==base.getPort() && uri.normalize().getPath().startsWith(base.getPath())) return true;
        if (!uri.getScheme().equals("https") && !uri.getScheme().equals("http")) return false;
        if (uri.getPort()!=-1 && uri.getPort()!=443 && uri.getPort()!=80) return false;
        for (String domain : QQ_HOSTS) if (host.equals(domain) || host.endsWith("."+domain)) return true;
        return false;
    }
    private void load(URI uri, Preview preview) {
        try {
            byte[] data = null;
            for (int redirects=0;redirects<4;redirects++) {
                if (!allowed(uri)) throw new java.io.IOException("Untrusted media redirect");
                var request = HttpRequest.newBuilder(uri).timeout(Duration.ofSeconds(10)).GET().build();
                var response = http.send(request, HttpResponse.BodyHandlers.ofInputStream());
                try (InputStream body = response.body()) {
                    if (response.statusCode()>=300 && response.statusCode()<400) {
                        uri=uri.resolve(response.headers().firstValue("location").orElseThrow()); continue;
                    }
                    if (response.statusCode()!=200) throw new java.io.IOException("Image unavailable");
                    data=body.readNBytes(MAX_BYTES+1);
                    if (data.length>MAX_BYTES) throw new java.io.IOException("Image too large");
                    break;
                }
            }
            if (data==null) throw new java.io.IOException("Too many redirects");
            var decoded=ImageFrames.decode(data);
            client.execute(() -> {
                if (!previews.containsValue(preview)) return;
                try {
                    int index=0;
                    for (var frame : decoded) {
                        var image=frame.image();
                        java.io.ByteArrayOutputStream png=new java.io.ByteArrayOutputStream();
                        javax.imageio.ImageIO.write(image,"PNG",png);
                        NativeImage pixels=NativeImage.read(png.toByteArray());
                        Identifier id=Identifier.fromNamespaceAndPath("mcqq_images", "image/"+java.util.UUID.randomUUID()+"/"+index++);
                        client.getTextureManager().register(id,new DynamicTexture(() -> "QQ chat image",pixels));
                        preview.frames.add(id); preview.delays.add(frame.milliseconds());
                        preview.width=image.getWidth(); preview.height=image.getHeight();
                    }
                } catch (Exception failure) { preview.failed=true; }
            });
        } catch (Exception failure) { client.execute(() -> preview.failed=true); }
    }
    @SuppressWarnings("unchecked")
    private void render(GuiGraphicsExtractor graphics) {
        if (client.level==null || client.gui.hud.isHidden() || client.options.chatVisibility().get()==net.minecraft.world.entity.player.ChatVisiblity.HIDDEN) return;
        try {
            ChatComponent chat=client.gui.hud.getChat();
            List<GuiMessage.Line> lines=(List<GuiMessage.Line>)chatLines.get(chat);
            int scroll=chatScroll.getInt(chat), page=chat.getLinesPerPage();
            boolean focused=chat.isChatFocused();
            float scale=client.options.chatScale().get().floatValue();
            int lineHeight=(int)(client.font.lineHeight*(client.options.chatLineSpacing().get()+1.0));
            int bottom=(int)Math.floor((graphics.guiHeight()-40)/scale);
            int chatWidth=(int)Math.floor(ChatComponent.getWidth(client.options.chatWidth().get())/scale);
            int top=bottom-page*lineHeight;
            if (lineHeight<=0 || scale<=0) return;
            java.util.IdentityHashMap<GuiMessage, Integer> first=new java.util.IdentityHashMap<>();
            for (int i=0;i<lines.size();i++) first.putIfAbsent(lines.get(i).parent(),i);
            graphics.enableScissor(0, Math.max(0,(int)Math.floor(top*scale)), Math.min(graphics.guiWidth(),(int)Math.ceil((chatWidth+8)*scale)), Math.min(graphics.guiHeight(),(int)Math.ceil(bottom*scale)));
            graphics.pose().pushMatrix(); graphics.pose().scale(scale,scale); graphics.pose().translate(4,0);
            try {
                long now=System.currentTimeMillis();
                for (var item:first.entrySet()) {
                    GuiMessage message=item.getKey(); List<URI> images=chatImages.get(message.content());
                    if (images==null || (!focused && client.gui.hud.getGuiTicks()-message.addedTime()>=200)) continue;
                    int base=item.getValue()-scroll;
                    for (int i=0;i<images.size();i++) {
                        int lower=base+(images.size()-1-i)*IMAGE_LINES;
                        int y=bottom-(lower+IMAGE_LINES)*lineHeight;
                        int blockHeight=IMAGE_LINES*lineHeight;
                        if (y>=bottom || y+blockHeight<=top) continue;
                        Preview image=preview(images.get(i));
                        if (image.frames.isEmpty() || image.failed) {
                            graphics.text(client.font,image.failed?"图片加载失败，点击链接打开":"正在加载图片…",0,y+2,0xFFFFFFFF);
                            continue;
                        }
                        int maxWidth=Math.max(1, Math.min(108,chatWidth-4)), maxHeight=Math.max(1,Math.min(blockHeight-4,(9*lineHeight-4)*3/4));
                        double factor=Math.min(maxWidth/(double)image.width,maxHeight/(double)image.height);
                        int w=Math.max(1,(int)(image.width*factor)), h=Math.max(1,(int)(image.height*factor));
                        graphics.blit(RenderPipelines.GUI_TEXTURED,image.frame(now),0,y+2,0f,0f,w,h,image.width,image.height,image.width,image.height);
                    }
                }
            } finally { graphics.pose().popMatrix(); graphics.disableScissor(); }
        } catch (ReflectiveOperationException error) {
            System.err.println("[MCQQ Images] Cannot render chat images: "+error);
        }
    }
    private void evict(String key) {
        Preview removed=previews.remove(key);
        if (removed!=null) for (Identifier frame : removed.frames) client.getTextureManager().release(frame);
    }
    private void clear() { for (String key : List.copyOf(previews.keySet())) evict(key); }
}
