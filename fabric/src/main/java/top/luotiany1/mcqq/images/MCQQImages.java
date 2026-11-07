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
import net.minecraft.client.renderer.RenderPipelines;
import net.minecraft.client.renderer.texture.DynamicTexture;
import net.minecraft.network.chat.ClickEvent;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.Identifier;

public final class MCQQImages implements ClientModInitializer {
    private static final int MAX_BYTES = 8 * 1024 * 1024;
    private static final String[] QQ_HOSTS = {"qq.com", "qq.com.cn", "qpic.cn", "gtimg.cn", "gtimg.com", "idqqimg.com", "qlogo.cn"};
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
        ClientReceiveMessageEvents.GAME.register((message, overlay) -> {
            if (!overlay && message.getString().contains("[群内]")) inspect(message, message.getString());
        });
        HudElementRegistry.attachElementBefore(VanillaHudElements.CHAT, Identifier.fromNamespaceAndPath("mcqq_images", "previews"), (graphics, delta) -> render(graphics));
        ClientPlayConnectionEvents.DISCONNECT.register((handler, minecraft) -> clear());
    }
    private void inspect(Component component, String caption) {
        var click = component.getStyle().getClickEvent();
        if (click instanceof ClickEvent.OpenUrl link && (component.getString().contains("[图片]") || component.getString().contains("[表情包]"))) {
            URI uri = link.uri();
            if (allowed(uri) && !previews.containsKey(uri.toString())) {
                while (previews.size() >= 6) evict(previews.keySet().iterator().next());
                Preview preview = new Preview(caption.length()>45 ? caption.substring(0,45) : caption);
                previews.put(uri.toString(), preview);
                workers.execute(() -> load(uri, preview));
            }
        }
        for (Component child : component.getSiblings()) inspect(child, caption);
    }
    static boolean allowed(URI uri) {
        String host = uri.getHost();
        if (host == null || uri.getUserInfo() != null) return false;
        host = host.toLowerCase(java.util.Locale.ROOT);
        if (host.equals("lemoe.luotiany1.top") && uri.getPath().startsWith("/mcqq-media/") &&
            ((uri.getScheme().equals("http") && uri.getPort()==18766) || uri.getScheme().equals("https"))) return true;
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
                        NativeImage pixels=new NativeImage(image.getWidth(),image.getHeight(),false);
                        for (int y=0;y<image.getHeight();y++) for (int x=0;x<image.getWidth();x++) pixels.setPixel(x,y,image.getRGB(x,y));
                        Identifier id=Identifier.fromNamespaceAndPath("mcqq_images", "image/"+java.util.UUID.randomUUID()+"/"+index++);
                        client.getTextureManager().register(id,new DynamicTexture(() -> "QQ chat image",pixels));
                        preview.frames.add(id); preview.delays.add(frame.milliseconds());
                        preview.width=image.getWidth(); preview.height=image.getHeight();
                    }
                } catch (Exception failure) { preview.failed=true; }
            });
        } catch (Exception failure) { client.execute(() -> preview.failed=true); }
    }
    private void render(GuiGraphicsExtractor graphics) {
        if (client.level==null || client.gui.hud.isHidden()) return;
        long now=System.currentTimeMillis();
        var expired=previews.entrySet().stream().filter(e -> now-e.getValue().created>=3_600_000).map(Map.Entry::getKey).toList();
        for (String key : expired) evict(key);
        int y=24, shown=0, boxWidth=Math.min(170,graphics.guiWidth()/3), x=graphics.guiWidth()-boxWidth-8;
        var entries=new ArrayList<>(previews.values());
        java.util.Collections.reverse(entries);
        for (Preview preview : entries) {
            if (shown>=3 || y+35>=graphics.guiHeight()) break;
            if (now-preview.created>30_000 && client.gui.screen()==null) continue;
            int w=boxWidth-8, h=preview.height==0 ? 25 : Math.max(1,Math.min(95,(int)(w*(double)preview.height/preview.width)));
            w=preview.width==0 ? w : Math.max(1,Math.min(w,(int)(h*(double)preview.width/preview.height)));
            graphics.fill(x-3,y-3,x+boxWidth+3,y+h+17,0xBB101820);
            graphics.text(client.font,client.font.plainSubstrByWidth(preview.caption,boxWidth-4),x,y,0xFFFFFFFF);
            if (!preview.frames.isEmpty() && !preview.failed) {
                graphics.blit(RenderPipelines.GUI_TEXTURED,preview.frame(now),x,y+12,0f,0f,w,h,preview.width,preview.height,preview.width,preview.height);
            } else graphics.text(client.font,preview.failed ? "图片不可用，点击聊天链接打开" : "正在加载图片…",x,y+14,0xFFAAAAAA);
            y+=h+24; shown++;
        }
    }
    private void evict(String key) {
        Preview removed=previews.remove(key);
        if (removed!=null) for (Identifier frame : removed.frames) client.getTextureManager().release(frame);
    }
    private void clear() { for (String key : List.copyOf(previews.keySet())) evict(key); }
}
