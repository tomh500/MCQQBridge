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
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.client.gui.components.ChatComponent;
import net.minecraft.client.gui.screens.ChatScreen;
import net.minecraft.client.multiplayer.chat.GuiMessage;
import net.minecraft.client.renderer.texture.DynamicTexture;
import net.minecraft.network.chat.ClickEvent;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.Identifier;

public final class ChatImageCore {
    private static final int MAX_BYTES = 8 * 1024 * 1024;
    private static final String[] QQ_HOSTS = {"qq.com", "qq.com.cn", "qpic.cn", "gtimg.cn", "gtimg.com", "idqqimg.com", "qlogo.cn"};
    private static final java.util.List<URI> MEDIA_BASES = new java.util.ArrayList<>();
    public static final ChatImageCore INSTANCE = new ChatImageCore();
    private static void loadMediaConfig() {
        java.nio.file.Path file = Minecraft.getInstance().gameDirectory.toPath().resolve("config").resolve("mcqq-images.properties");
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
    private static final class LinkSlot {
        final List<Component> children; final Component original; boolean hidden;
        LinkSlot(List<Component> children,Component original) { this.children=children; this.original=original; }
        void show(boolean show) { children.set(0,show ? original : Component.empty()); hidden=!show; }
    }
    private record ImageMessage(List<URI> images, List<LinkSlot> slots) {}
    // Components change when a fallback is hidden, so equality/hash-based maps
    // would lose their entries while the message is still displayed.
    private final Map<Component, ImageMessage> chatImages = new java.util.IdentityHashMap<>();
    private boolean labelsDirty;
    private final java.util.Set<String> drawn=new java.util.HashSet<>();
    private boolean labelHidingDisabled;
    private java.lang.reflect.Field chatLines, chatScroll;
    private final Minecraft client = Minecraft.getInstance();
    private final Map<String, Preview> previews = new LinkedHashMap<>();
    private record Hit(int x,int y,int width,int height,URI uri) {}
    private final List<Hit> hits=new ArrayList<>();
    private URI enlarged;
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
    private ChatImageCore() {
        loadMediaConfig();
        try {
            chatLines=ChatComponent.class.getDeclaredField("trimmedMessages");
            chatScroll=ChatComponent.class.getDeclaredField("chatScrollbarPos");
            chatLines.setAccessible(true); chatScroll.setAccessible(true);
        } catch (ReflectiveOperationException error) {
            System.err.println("[MCQQ Images] Chat integration unavailable: "+error);
        }
    }
    public Component prepare(Component message) {
        if(chatLines==null) return message;
        List<URI> links=new ArrayList<>(); findLinks(message,links);
        if(links.isEmpty())return message;
        var result=Component.empty().append(removeFaceMetadata(message));
        var candidates=new ArrayList<Map.Entry<URI,LinkSlot>>(); collectSlots(result,candidates);
        var slots=new ArrayList<LinkSlot>();
        for(URI uri:links) {
            LinkSlot slot=null;
            for(var iterator=candidates.iterator();iterator.hasNext();) {
                var item=iterator.next(); if(item.getKey().equals(uri)) { slot=item.getValue(); iterator.remove(); break; }
            }
            slots.add(slot);
        }
        for(int i=0;i<IMAGE_LINES*links.size();i++)result.append("\n\u00a0");
        if(chatImages.size()>=256) {
            var iterator=chatImages.values().iterator(); ImageMessage old=iterator.next(); iterator.remove();
            for(LinkSlot slot:old.slots()) if(slot!=null && slot.hidden) { slot.show(true); labelsDirty=true; }
        }
        chatImages.put(result,new ImageMessage(List.copyOf(links),slots));
        return result;
    }
    private void collectSlots(Component parent,List<Map.Entry<URI,LinkSlot>> result) {
        List<Component> siblings=parent.getSiblings();
        for(int i=0;i<siblings.size();i++) {
            Component child=siblings.get(i);
            if(child.getContents() instanceof net.minecraft.network.chat.contents.PlainTextContents literal
                && (literal.text().equals("[图片]") || literal.text().equals("[表情包]")) && child.getSiblings().isEmpty()) {
                var found=new ArrayList<URI>(); findLinks(child,found);
                if(!found.isEmpty()) {
                    var wrapper=Component.empty().append(child); siblings.set(i,wrapper);
                    result.add(Map.entry(found.getFirst(),new LinkSlot(wrapper.getSiblings(),child)));
                }
            }
            collectSlots(child,result);
        }
    }
    private net.minecraft.network.chat.MutableComponent removeFaceMetadata(Component component) {
        net.minecraft.network.chat.MutableComponent copy;
        if (component.getContents() instanceof net.minecraft.network.chat.contents.PlainTextContents literal) {
            String text=literal.text().replaceAll("(?i)<faceType\\s*=\\s*[^<>]*?faceId\\s*=\\s*[^<>]*?>", "");
            copy=Component.literal(text).setStyle(component.getStyle());
        } else copy=component.plainCopy();
        for (Component child:component.getSiblings()) copy.append(removeFaceMetadata(child));
        return copy;
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
    public void render(GuiGraphicsExtractor graphics) {
        hits.clear();
        if (chatLines==null || client.level==null || client.gui.hud.isHidden() || client.options.chatVisibility().get()==net.minecraft.world.entity.player.ChatVisiblity.HIDDEN) return;
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
                    GuiMessage message=item.getKey(); ImageMessage info=chatImages.get(message.content());
                    if (info==null || (!focused && client.gui.hud.getGuiTicks()-message.addedTime()>=200)) continue;
                    List<URI> images=info.images();
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
                        drawImage(graphics,image.frame(now),0,y+2,w,h,image.width,image.height);
                        drawn.add(images.get(i).toString());
                        int px=(int)Math.round(4*scale), py=(int)Math.round((y+2)*scale);
                        int hitTop=Math.max(py,(int)Math.floor(top*scale)), hitBottom=Math.min((int)Math.ceil((y+2+h)*scale),(int)Math.ceil(bottom*scale));
                        if(focused && hitBottom>hitTop) hits.add(new Hit(px,hitTop,(int)Math.ceil(w*scale),hitBottom-hitTop,images.get(i)));
                    }
                }
            } finally { graphics.pose().popMatrix(); graphics.disableScissor(); }
            syncLabels(chat,scroll);
        } catch (Exception | LinkageError error) {
            restoreLabels(); labelHidingDisabled=true;
            try { client.gui.hud.getChat().rescaleChat(); } catch(Exception ignored) { }
            System.err.println("[MCQQ Images] Cannot render chat images: "+error);
        }
    }
    private void restoreLabels() {
        for(ImageMessage message:chatImages.values()) for(LinkSlot slot:message.slots()) if(slot!=null && slot.hidden)slot.show(true);
        drawn.clear();
    }
    private void syncLabels(ChatComponent chat,int scroll) {
        if(labelHidingDisabled)return;
        boolean changed=labelsDirty; labelsDirty=false;
        try {
            for(ImageMessage message:chatImages.values()) for(int i=0;i<message.images().size();i++) {
                LinkSlot slot=message.slots().get(i); if(slot==null)continue;
                String key=message.images().get(i).toString(); Preview image=previews.get(key);
                boolean hide=image!=null && !image.failed && !image.frames.isEmpty() && drawn.contains(key);
                if(slot.hidden!=hide) { slot.show(!hide); changed=true; }
            }
            if(changed) { chat.rescaleChat(); chatScroll.setInt(chat,scroll); }
        } catch(Exception error) {
            labelHidingDisabled=true; restoreLabels();
            try { chat.rescaleChat(); chatScroll.setInt(chat,scroll); } catch(Exception ignored) { }
            System.err.println("[MCQQ Images] Link hiding disabled: "+error);
        }
    }
    public boolean click(double x,double y,int button) {
        if(button!=0)return false;
        if(enlarged!=null) { enlarged=null; return true; }
        for(Hit hit:hits) if(x>=hit.x && x<hit.x+hit.width && y>=hit.y && y<hit.y+hit.height) { enlarged=hit.uri; return true; }
        return false;
    }
    public void closeViewer() { enlarged=null; hits.clear(); }
    public void renderViewer(GuiGraphicsExtractor graphics) {
        if(enlarged==null)return;
        Preview image=previews.get(enlarged.toString());
        if(image==null || image.failed || image.frames.isEmpty()) { enlarged=null; return; }
        try {
            int width=graphics.guiWidth(), height=graphics.guiHeight();
            graphics.fill(0,0,width,height,0xC0000000);
            double factor=Math.min((width-32.0)/image.width,(height-32.0)/image.height);
            int w=Math.max(1,(int)Math.round(image.width*factor)), h=Math.max(1,(int)Math.round(image.height*factor));
            drawImage(graphics,image.frame(System.currentTimeMillis()),(width-w)/2,(height-h)/2,w,h,image.width,image.height);
        } catch(ReflectiveOperationException error) { enlarged=null; System.err.println("[MCQQ Images] Image viewer unavailable: "+error); }
    }
    // The RenderPipeline class moved packages between 26.2 and 26.3. Resolve
    // the pipeline and blit overload once so one binary works with both.
    private java.lang.reflect.Method blitMethod;
    private Object texturedPipeline;
    private void drawImage(GuiGraphicsExtractor graphics, Identifier texture, int x, int y, int w, int h, int textureWidth, int textureHeight) throws ReflectiveOperationException {
        if (blitMethod==null) {
            texturedPipeline=Class.forName("net.minecraft.client.renderer.RenderPipelines").getField("GUI_TEXTURED").get(null);
            for (var method:GuiGraphicsExtractor.class.getMethods()) {
                var types=method.getParameterTypes();
                if (method.getName().equals("blit") && types.length==12 && types[0].isInstance(texturedPipeline) && types[1]==Identifier.class) {
                    blitMethod=method; break;
                }
            }
            if (blitMethod==null) throw new NoSuchMethodException("Compatible GUI textured blit");
        }
        blitMethod.invoke(graphics,texturedPipeline,texture,x,y,0f,0f,w,h,textureWidth,textureHeight,textureWidth,textureHeight);
    }
    private void evict(String key) {
        Preview removed=previews.remove(key);
        drawn.remove(key);
        if (removed!=null) for (Identifier frame : removed.frames) client.getTextureManager().release(frame);
    }
    public void clear() { closeViewer(); restoreLabels(); for (String key : List.copyOf(previews.keySet())) evict(key); chatImages.clear(); }
}
