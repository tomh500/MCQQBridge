package top.luotiany1.mcqq.images;

import java.io.*;
import java.lang.reflect.*;
import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import javax.imageio.ImageIO;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.loader.api.FabricLoader;

/** Universal Java 21 implementation with a generated per-version name bridge. */
public final class UniversalImages implements ClientModInitializer {
    private static final String MC="net.minecraft.client.Minecraft", COMPONENT="net.minecraft.network.chat.Component";
    private final LinkedHashMap<String,Preview> previews=new LinkedHashMap<>();
    private final ExecutorService workers=Executors.newFixedThreadPool(2,r -> { Thread t=new Thread(r,"MCQQ image download"); t.setDaemon(true); return t; });
    private final HttpClient http=HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).followRedirects(HttpClient.Redirect.NEVER).build();
    private Bridge bridge;
    private Object pipeline;
    private boolean renderError;
    private static final List<URI> MEDIA_BASES=new ArrayList<>();
    private static final int IMAGE_LINES=7;
    private static final String MARKER="mcqq-image:";
    private final Map<String,URI> imageMarkers=new LinkedHashMap<>();
    private static final class LinkSlot {
        final List<Object> children; final Object original,empty; boolean hidden;
        LinkSlot(List<Object> children,Object original,Object empty) { this.children=children; this.original=original; this.empty=empty; }
        void show(boolean show) { children.set(0,show ? original : empty); hidden=!show; }
    }
    private final Map<String,LinkSlot> labelSlots=new LinkedHashMap<>();
    private final Set<String> drawn=new HashSet<>();
    private boolean labelsDirty, labelHidingDisabled;
    private record Hit(int x,int y,int width,int height,URI uri) {}
    private final List<Hit> hits=new ArrayList<>();
    private URI enlarged;
    private ImageViewer viewer;
    private int viewerWidth,viewerHeight,mouseX,mouseY;
    static final class Preview {
        final String caption; final long created=System.currentTimeMillis();
        final List<Object> frames=new ArrayList<>(); final List<Integer> delays=new ArrayList<>();
        int width,height,originalWidth,originalHeight; boolean failed;
        Preview(String caption) { this.caption=caption; }
        Object frame(long time) {
            int total=delays.stream().mapToInt(Integer::intValue).sum(); long offset=Math.floorMod(time-created,Math.max(1,total));
            for(int i=0;i<delays.size();i++) { offset-=delays.get(i); if(offset<0)return frames.get(i); }
            return frames.getFirst();
        }
    }
    @Override public void onInitializeClient() {
        String version=FabricLoader.getInstance().getModContainer("minecraft").orElseThrow().getMetadata().getVersion().getFriendlyString();
        try {
            loadMediaConfig();
            bridge=new Bridge(version);
            // Resolve essential members before hooking events: a bad adapter cannot
            // break incoming chat or repeatedly throw on the render thread.
            bridge.type(COMPONENT); pipeline=bridge.pipeline();
            modifyGame();
            event("net.fabricmc.fabric.api.client.networking.v1.ClientPlayConnectionEvents","DISCONNECT",args -> bridge.execute(() -> {
                try { clear(); } catch(Exception error) { System.err.println("[MCQQ Images] Texture cleanup failed: "+error); }
            }));
            hud();
            screens();
            System.out.println("[MCQQ Images] Universal adapter loaded for "+version);
        } catch(Exception|LinkageError error) {
            System.err.println("[MCQQ Images] Cannot initialize "+version+"; original chat links remain usable."); error.printStackTrace();
        }
    }
    @FunctionalInterface interface Callback { void call(Object[] args) throws Exception; }
    static Object callback(Class<?> type,Callback body) {
        return Proxy.newProxyInstance(type.getClassLoader(),new Class<?>[]{type},(proxy,method,args)->{
            if(method.getDeclaringClass()==Object.class) return switch(method.getName()) {
                case "toString" -> "MCQQ callback"; case "hashCode" -> System.identityHashCode(proxy); case "equals" -> proxy==args[0]; default -> null;
            };
            try { body.call(args); } catch(Exception error) { System.err.println("[MCQQ Images] Event failed: "+error); }
            return null;
        });
    }
    static void event(String owner,String field,Callback body) throws Exception {
        Object event=Class.forName(owner).getField(field).get(null);
        Class<?> eventType=Class.forName("net.fabricmc.fabric.api.event.Event");
        Object invoker=eventType.getMethod("invoker").invoke(event);
        Class<?> callbackType=invoker.getClass().getInterfaces()[0];
        eventType.getMethod("register",Object.class).invoke(event,callback(callbackType,body));
    }
    private void modifyGame() throws Exception {
        Object event=Class.forName("net.fabricmc.fabric.api.client.message.v1.ClientReceiveMessageEvents").getField("MODIFY_GAME").get(null);
        Class<?> eventType=Class.forName("net.fabricmc.fabric.api.event.Event");
        Object invoker=eventType.getMethod("invoker").invoke(event);
        Class<?> callbackType=invoker.getClass().getInterfaces()[0];
        Object listener=Proxy.newProxyInstance(callbackType.getClassLoader(),new Class<?>[]{callbackType},(p,m,args)->{
            if(m.getDeclaringClass()==Object.class) return switch(m.getName()) {
                case "toString" -> "MCQQ chat modifier"; case "hashCode" -> System.identityHashCode(p); case "equals" -> p==args[0]; default -> null;
            };
            try { return Boolean.TRUE.equals(args[1]) ? args[0] : prepare(args[0]); }
            catch(Exception error) { System.err.println("[MCQQ Images] Message preparation failed: "+error); return args[0]; }
        });
        eventType.getMethod("register",Object.class).invoke(event,listener);
    }
    private Object prepare(Object message) throws Exception {
        List<URI> links=new ArrayList<>(); findLinks(message,links);
        if(links.isEmpty()) return message;
        Object cleaned=removeFaceMetadata(message);
        Object result=bridge.call(null,COMPONENT,"literal","");
        bridge.call(result,"net.minecraft.network.chat.MutableComponent","append",cleaned);
        List<Map.Entry<URI,LinkSlot>> slots=new ArrayList<>();
        collectSlots(result,slots);
        for(URI uri:links) {
            String marker=MARKER+UUID.randomUUID(); imageMarkers.put(marker,uri);
            for(var iterator=slots.iterator();iterator.hasNext();) {
                var slot=iterator.next(); if(slot.getKey().equals(uri)) { labelSlots.put(marker,slot.getValue()); iterator.remove(); break; }
            }
            while(imageMarkers.size()>1024) {
                String oldest=imageMarkers.keySet().iterator().next(); imageMarkers.remove(oldest);
                LinkSlot slot=labelSlots.remove(oldest); if(slot!=null && slot.hidden) { slot.show(true); labelsDirty=true; }
            }
            Object style=bridge.call(bridge.field(null,"net.minecraft.network.chat.Style","EMPTY"),"net.minecraft.network.chat.Style","withInsertion",marker);
            for(int i=0;i<IMAGE_LINES;i++) {
                Object part=bridge.call(null,COMPONENT,"literal","\n\u00a0");
                bridge.call(part,"net.minecraft.network.chat.MutableComponent","setStyle",style);
                bridge.call(result,"net.minecraft.network.chat.MutableComponent","append",part);
            }
        }
        return result;
    }
    @SuppressWarnings("unchecked")
    private void collectSlots(Object parent,List<Map.Entry<URI,LinkSlot>> slots) throws Exception {
        List<Object> siblings=(List<Object>)bridge.call(parent,COMPONENT,"getSiblings");
        for(int i=0;i<siblings.size();i++) {
            Object child=siblings.get(i), contents=bridge.call(child,COMPONENT,"getContents");
            String plain="net.minecraft.network.chat.contents.PlainTextContents";
            if(bridge.type(plain).isInstance(contents)) {
                String text=(String)bridge.call(contents,plain,"text");
                if((text.equals("[图片]") || text.equals("[表情包]")) && ((List<?>)bridge.call(child,COMPONENT,"getSiblings")).isEmpty()) {
                    List<URI> found=new ArrayList<>(); findLinks(child,found);
                    if(!found.isEmpty()) {
                        Object wrapper=bridge.call(null,COMPONENT,"literal","");
                        bridge.call(wrapper,"net.minecraft.network.chat.MutableComponent","append",child);
                        Object empty=bridge.call(null,COMPONENT,"literal","");
                        List<Object> children=(List<Object>)bridge.call(wrapper,COMPONENT,"getSiblings");
                        siblings.set(i,wrapper); slots.add(Map.entry(found.getFirst(),new LinkSlot(children,child,empty)));
                    }
                }
            }
            collectSlots(child,slots);
        }
    }
    private Object removeFaceMetadata(Object component) throws Exception {
        Object contents=bridge.call(component,COMPONENT,"getContents");
        Object copy;
        String plain="net.minecraft.network.chat.contents.PlainTextContents";
        if(bridge.type(plain).isInstance(contents)) {
            String text=(String)bridge.call(contents,plain,"text");
            String cleaned=text.replaceAll("(?i)<faceType\\s*=\\s*[^<>]*?faceId\\s*=\\s*[^<>]*?>","");
            copy=bridge.call(null,COMPONENT,"literal",cleaned);
            bridge.call(copy,"net.minecraft.network.chat.MutableComponent","setStyle",bridge.call(component,COMPONENT,"getStyle"));
        } else copy=bridge.call(component,COMPONENT,"plainCopy");
        for(Object child:(List<?>)bridge.call(component,COMPONENT,"getSiblings"))
            bridge.call(copy,"net.minecraft.network.chat.MutableComponent","append",removeFaceMetadata(child));
        return copy;
    }
    private void findLinks(Object component,List<URI> links) throws Exception {
        Object style=bridge.call(component,COMPONENT,"getStyle");
        Object click=bridge.call(style,"net.minecraft.network.chat.Style","getClickEvent");
        String label=bridge.text(component);
        if(click!=null && (label.contains("[图片]") || label.contains("[表情包]"))) {
            URI uri=null;
            if(bridge.version.equals("1.21.4")) {
                Object action=bridge.call(click,"net.minecraft.network.chat.ClickEvent","getAction");
                if(action==bridge.field(null,"net.minecraft.network.chat.ClickEvent$Action","OPEN_URL"))
                    uri=URI.create((String)bridge.call(click,"net.minecraft.network.chat.ClickEvent","getValue"));
            } else if(bridge.type("net.minecraft.network.chat.ClickEvent$OpenUrl").isInstance(click))
                uri=(URI)bridge.call(click,"net.minecraft.network.chat.ClickEvent$OpenUrl","uri");
            if(uri!=null && allowed(uri) && links.size()<8) links.add(uri);
        }
        for(Object child:(List<?>)bridge.call(component,COMPONENT,"getSiblings")) findLinks(child,links);
    }
    private void hud() throws Exception {
        try {
            Class<?> registry=Class.forName("net.fabricmc.fabric.api.client.rendering.v1.hud.HudElementRegistry");
            Object chat=Class.forName("net.fabricmc.fabric.api.client.rendering.v1.hud.VanillaHudElements").getField("CHAT").get(null);
            for(Method method:registry.getMethods()) if(method.getName().equals("attachElementAfter") && method.getParameterCount()==3) {
                method.invoke(null,chat,bridge.id("chat_images"),callback(method.getParameterTypes()[2],args -> { if(!chatFocused()) render(args[0]); })); return;
            }
            throw new NoSuchMethodException("HudElementRegistry.attachElementAfter");
        } catch(ClassNotFoundException absent) {
            event("net.fabricmc.fabric.api.client.rendering.v1.HudRenderCallback","EVENT",args -> { if(!chatFocused()) render(args[0]); });
        }
    }
    private boolean chatFocused() throws Exception {
        Object screen=bridge.screen(); return screen!=null && bridge.type("net.minecraft.client.gui.screens.ChatScreen").isInstance(screen);
    }
    private void screens() throws Exception {
        event("net.fabricmc.fabric.api.client.screen.v1.ScreenEvents","AFTER_INIT",args -> {
            Object screen=args[1];
            if(!bridge.type("net.minecraft.client.gui.screens.ChatScreen").isInstance(screen))return;
            enlarged=null; viewer=null; hits.clear();
            try { registerMouse(screen); }
            catch(Exception error) { System.err.println("[MCQQ Images] Image click integration unavailable: "+error); }
            Class<?> owner=Class.forName("net.fabricmc.fabric.api.client.screen.v1.ScreenEvents");
            String name=bridge.modern ? "afterExtract" : "afterRender";
            for(Method method:owner.getMethods()) if(method.getName().equals(name) && method.getParameterCount()==1) {
                Object event=method.invoke(null,screen); Class<?> eventType=Class.forName("net.fabricmc.fabric.api.event.Event");
                Object invoker=eventType.getMethod("invoker").invoke(event); Class<?> type=invoker.getClass().getInterfaces()[0];
                eventType.getMethod("register",Object.class).invoke(event,callback(type,renderArgs -> {
                    mouseX=((Number)renderArgs[2]).intValue(); mouseY=((Number)renderArgs[3]).intValue(); render(renderArgs[1]);
                })); return;
            }
        });
    }
    private void registerMouse(Object screen) throws Exception {
        Class<?> owner=Class.forName("net.fabricmc.fabric.api.client.screen.v1.ScreenMouseEvents");
        Method factory=Arrays.stream(owner.getMethods()).filter(m -> m.getName().equals("allowMouseClick") && m.getParameterCount()==1).findFirst().orElseThrow();
        Object event=factory.invoke(null,screen); Class<?> eventType=Class.forName("net.fabricmc.fabric.api.event.Event");
        Object invoker=eventType.getMethod("invoker").invoke(event); Class<?> type=invoker.getClass().getInterfaces()[0];
        Object listener=Proxy.newProxyInstance(type.getClassLoader(),new Class<?>[]{type},(p,m,args)-> {
            if(m.getDeclaringClass()==Object.class) return switch(m.getName()) {
                case "toString" -> "MCQQ image click"; case "hashCode" -> System.identityHashCode(p); case "equals" -> p==args[0]; default -> null;
            };
            try {
                double x,y; int button;
                if(args.length>=4) { x=((Number)args[1]).doubleValue(); y=((Number)args[2]).doubleValue(); button=((Number)args[3]).intValue(); }
                else {
                    Object click=args[1];
                    x=((Number)bridge.call(click,"net.minecraft.client.input.MouseButtonEvent","x")).doubleValue();
                    y=((Number)bridge.call(click,"net.minecraft.client.input.MouseButtonEvent","y")).doubleValue();
                    button=((Number)bridge.call(click,"net.minecraft.client.input.MouseButtonEvent","button")).intValue();
                }
                if(button!=0)return true;
                if(enlarged!=null) {
                    if(viewer!=null && !viewer.press(x,y,button,viewerWidth,viewerHeight)) { enlarged=null; viewer=null; }
                    return false;
                }
                for(Hit hit:hits) if(x>=hit.x && x<hit.x+hit.width && y>=hit.y && y<hit.y+hit.height) {
                    Preview image=previews.get(hit.uri.toString());
                    if(image!=null && image.originalWidth>0 && !image.failed) {
                        enlarged=hit.uri; viewer=new ImageViewer(image.originalWidth,image.originalHeight,new ImageViewer.Rect(hit.x,hit.y,hit.width,hit.height),System.currentTimeMillis());
                    }
                    return false;
                }
            } catch(Exception error) { System.err.println("[MCQQ Images] Image click unavailable: "+error); }
            return true;
        });
        eventType.getMethod("register",Object.class).invoke(event,listener);
        registerViewerEvent(owner,screen,"allowMouseRelease",args -> { if(viewer==null)return true; viewer.release(); return false; });
        registerViewerEvent(owner,screen,"allowMouseScroll",args -> {
            if(viewer==null)return true;
            viewer.scroll(((Number)args[1]).doubleValue(),((Number)args[2]).doubleValue(),((Number)args[4]).doubleValue(),viewerWidth,viewerHeight); return false;
        });
        Class<?> keyboard=Class.forName("net.fabricmc.fabric.api.client.screen.v1.ScreenKeyboardEvents");
        registerViewerEvent(keyboard,screen,"allowKeyPress",args -> {
            if(viewer==null)return true;
            int key=args.length>=4 ? ((Number)args[1]).intValue() : ((Number)bridge.call(args[1],"net.minecraft.client.input.KeyEvent","key")).intValue();
            if(key==256) { enlarged=null; viewer=null; return false; }
            return true;
        });
    }
    @FunctionalInterface interface AllowEvent { boolean allow(Object[] args) throws Exception; }
    private void registerViewerEvent(Class<?> owner,Object screen,String name,AllowEvent body) throws Exception {
        Method factory=Arrays.stream(owner.getMethods()).filter(m -> m.getName().equals(name) && m.getParameterCount()==1).findFirst().orElseThrow();
        Object event=factory.invoke(null,screen); Class<?> eventType=Class.forName("net.fabricmc.fabric.api.event.Event");
        Object invoker=eventType.getMethod("invoker").invoke(event); Class<?> type=invoker.getClass().getInterfaces()[0];
        Object listener=Proxy.newProxyInstance(type.getClassLoader(),new Class<?>[]{type},(p,m,args) -> {
            if(m.getDeclaringClass()==Object.class) return switch(m.getName()) {
                case "toString" -> "MCQQ viewer event"; case "hashCode" -> System.identityHashCode(p); case "equals" -> p==args[0]; default -> null;
            };
            try { return body.allow(args); } catch(Exception error) { System.err.println("[MCQQ Images] Viewer input failed: "+error); return true; }
        });
        eventType.getMethod("register",Object.class).invoke(event,listener);
    }
    private Preview preview(URI uri) throws Exception {
        String key=uri.toString(); Preview result=previews.get(key);
        if(result==null) {
            while(previews.size()>=6)evict(previews.keySet().iterator().next());
            result=new Preview(""); previews.put(key,result); Preview request=result;
            workers.execute(()->load(uri,request));
        }
        return result;
    }
    private static void loadMediaConfig() throws IOException {
        var path=FabricLoader.getInstance().getConfigDir().resolve("mcqq-images.properties");
        if(!java.nio.file.Files.exists(path)) java.nio.file.Files.writeString(path,"# Trusted media URL prefixes, comma-separated; each must end in /\ntrusted-media-bases=\n");
        Properties config=new Properties();
        try(var in=java.nio.file.Files.newBufferedReader(path)) { config.load(in); }
        MEDIA_BASES.clear();
        for(String raw:config.getProperty("trusted-media-bases","").split(",")) {
            if(raw.isBlank())continue;
            try {
                URI base=URI.create(raw.trim()).normalize();
                if(base.getHost()!=null && base.getUserInfo()==null && base.getQuery()==null && base.getFragment()==null
                    && ("http".equals(base.getScheme()) || "https".equals(base.getScheme())) && base.getPath().endsWith("/")) MEDIA_BASES.add(base);
            } catch(IllegalArgumentException ignored) { System.err.println("[MCQQ Images] Ignoring invalid media base URL"); }
        }
    }
    static boolean allowed(URI uri) {
        String host=uri.getHost(); if(host==null || uri.getUserInfo()!=null || uri.getFragment()!=null)return false;
        host=host.toLowerCase(Locale.ROOT);
        if(!"https".equals(uri.getScheme()) && !"http".equals(uri.getScheme()))return false;
        String rawPath=uri.getRawPath();
        if(rawPath==null || rawPath.toLowerCase(Locale.ROOT).matches(".*%(2e|2f|5c).*"))return false;
        for(URI base:MEDIA_BASES)
            if(host.equalsIgnoreCase(base.getHost()) && uri.getScheme().equals(base.getScheme()) && uri.getPort()==base.getPort()
                && uri.normalize().getPath().startsWith(base.getPath())) return true;
        if(uri.getPort()!=-1 && uri.getPort()!=80 && uri.getPort()!=443)return false;
        for(String domain:List.of("qq.com","qq.com.cn","qpic.cn","gtimg.cn","gtimg.com","idqqimg.com","qlogo.cn"))
            if(host.equals(domain) || host.endsWith('.'+domain))return true;
        return false;
    }
    private void load(URI uri,Preview preview) {
        try {
            byte[] data=null;
            for(int i=0;i<4;i++) {
                if(!allowed(uri))throw new IOException("Image host rejected");
                HttpResponse<InputStream> response=http.send(HttpRequest.newBuilder(uri).timeout(Duration.ofSeconds(10)).GET().build(),HttpResponse.BodyHandlers.ofInputStream());
                try(InputStream body=response.body()) {
                    if(response.statusCode()>=300 && response.statusCode()<400) { uri=uri.resolve(response.headers().firstValue("location").orElseThrow()); continue; }
                    if(response.statusCode()!=200)throw new IOException("Image unavailable");
                    data=body.readNBytes(8*1024*1024+1); if(data.length>8*1024*1024)throw new IOException("Image too large"); break;
                }
            }
            if(data==null)throw new IOException("Too many redirects");
            var decoded=ImageFrames.decode(data);
            // Encode bounded thumbnails off the render thread; NativeImage.read
            // handles each version's ARGB/ABGR representation without per-pixel reflection.
            List<byte[]> pngs=new ArrayList<>();
            for(var frame:decoded) { ByteArrayOutputStream output=new ByteArrayOutputStream(); ImageIO.write(frame.image(),"PNG",output); pngs.add(output.toByteArray()); }
            bridge.execute(()-> {
                if(!previews.containsValue(preview))return;
                try {
                    Object manager=bridge.call(bridge.client(),MC,"getTextureManager");
                    for(int i=0;i<decoded.size();i++) {
                        Object nativeImage=bridge.call(null,"com.mojang.blaze3d.platform.NativeImage","read",pngs.get(i));
                        Object texture=null;
                        try {
                            texture=bridge.texture(nativeImage);
                            Object id=bridge.id("image/"+UUID.randomUUID());
                            bridge.call(manager,"net.minecraft.client.renderer.texture.TextureManager","register",id,texture);
                            preview.frames.add(id); preview.delays.add(decoded.get(i).milliseconds());
                        } catch(Exception error) {
                            if(texture instanceof AutoCloseable close) close.close();
                            else if(nativeImage instanceof AutoCloseable close) close.close();
                            throw error;
                        }
                    }
                    preview.width=decoded.getFirst().image().getWidth(); preview.height=decoded.getFirst().image().getHeight();
                    preview.originalWidth=decoded.getFirst().originalWidth(); preview.originalHeight=decoded.getFirst().originalHeight();
                } catch(Exception error) { preview.failed=true; System.err.println("[MCQQ Images] Texture upload failed: "+error); }
            });
        } catch(Exception error) { try { bridge.execute(()->preview.failed=true); } catch(Exception ignored) {} }
    }
    private void render(Object graphics) throws Exception {
        if(renderError)return;
        try {
            hits.clear();
            if(bridge.field(bridge.client(),MC,"level")==null || bridge.hidden())return;
            Object options=bridge.field(bridge.client(),MC,"options");
            Object visibility=bridge.call(bridge.call(options,"net.minecraft.client.Options","chatVisibility"),"net.minecraft.client.OptionInstance","get");
            if(visibility instanceof Enum<?> value && value.name().equals("HIDDEN"))return;
            Object gui=bridge.field(bridge.client(),MC,"gui");
            String guiOwner="net.minecraft.client.gui.Gui";
            if(bridge.modern && !bridge.version.startsWith("26.1")) { gui=bridge.field(gui,guiOwner,"hud"); guiOwner="net.minecraft.client.gui.Hud"; }
            Object chat=bridge.call(gui,guiOwner,"getChat");
            String chatClass="net.minecraft.client.gui.components.ChatComponent";
            List<?> lines=(List<?>)bridge.privateField(chat,chatClass,"trimmedMessages");
            int scroll=(int)bridge.privateField(chat,chatClass,"chatScrollbarPos"), page=(int)bridge.call(chat,chatClass,"getLinesPerPage");
            double scale=(double)bridge.privateCall(chat,chatClass,"getScale");
            int lineHeight=(int)bridge.privateCall(chat,chatClass,"getLineHeight"), chatWidth=(int)bridge.privateCall(chat,chatClass,"getWidth");
            if(scale<=0 || lineHeight<=0)return;
            chatWidth=(int)Math.ceil(chatWidth/scale);
            String gc=bridge.graphicsClass(); int width=(int)bridge.call(graphics,gc,"guiWidth"), height=(int)bridge.call(graphics,gc,"guiHeight");
            int bottom=(int)Math.floor((height-40)/scale), top=bottom-page*lineHeight;
            int ticks=(int)bridge.call(gui,guiOwner,"getGuiTicks"); boolean focused=chatFocused();
            String lineClass=bridge.modern ? "net.minecraft.client.multiplayer.chat.GuiMessage$Line" : "net.minecraft.client.GuiMessage$Line";
            Map<String,Integer> first=new LinkedHashMap<>(); Map<String,Integer> age=new HashMap<>();
            Class<?> sinkType=bridge.type("net.minecraft.util.FormattedCharSink");
            for(int i=Math.max(0,scroll-IMAGE_LINES+1);i<Math.min(lines.size(),scroll+page);i++) {
                Object line=lines.get(i), sequence=bridge.call(line,lineClass,"content");
                final String[] found={null};
                Object sink=Proxy.newProxyInstance(sinkType.getClassLoader(),new Class<?>[]{sinkType},(p,m,args)->{
                    if(args!=null && args.length==3) {
                        String value=(String)bridge.call(args[1],"net.minecraft.network.chat.Style","getInsertion");
                        if(value!=null && value.startsWith(MARKER)) found[0]=value;
                    }
                    return true;
                });
                bridge.call(sequence,"net.minecraft.util.FormattedCharSequence","accept",sink);
                if(found[0]!=null && imageMarkers.containsKey(found[0])) {
                    first.putIfAbsent(found[0],i);
                    age.putIfAbsent(found[0],(int)bridge.call(line,lineClass,"addedTime"));
                }
            }
            bridge.call(graphics,gc,"enableScissor",0,Math.max(0,(int)Math.floor(top*scale)),Math.min(width,(int)Math.ceil((chatWidth+8)*scale)),Math.min(height,(int)Math.ceil(bottom*scale)));
            try {
                Object font=bridge.field(bridge.client(),MC,"font"); long now=System.currentTimeMillis();
                for(var entry:first.entrySet()) {
                    if(!focused && ticks-age.get(entry.getKey())>=200)continue;
                    int lower=entry.getValue()-scroll, y=bottom-(lower+IMAGE_LINES)*lineHeight, block=IMAGE_LINES*lineHeight;
                    if(y>=bottom || y+block<=top)continue;
                    Preview image=preview(imageMarkers.get(entry.getKey()));
                    int px=(int)Math.round(4*scale), py=(int)Math.round((y+2)*scale);
                    if(image.frames.isEmpty() || image.failed) { text(graphics,font,image.failed?"图片加载失败":"正在加载图片…",px,py,0xFFFFFFFF); continue; }
                    double factor=Math.min(Math.min(108,chatWidth-4)/(double)image.width,Math.min(block-4,(9*lineHeight-4)*3/4)/(double)image.height);
                    int w=Math.max(1,(int)Math.round(image.width*factor*scale)), h=Math.max(1,(int)Math.round(image.height*factor*scale));
                    bridge.call(graphics,gc,"blit",pipeline,image.frame(now),px,py,0f,0f,w,h,image.width,image.height,image.width,image.height);
                    drawn.add(imageMarkers.get(entry.getKey()).toString());
                    int hitTop=Math.max(py,(int)Math.floor(top*scale)), hitBottom=Math.min(py+h,(int)Math.ceil(bottom*scale));
                    if(focused && hitBottom>hitTop) hits.add(new Hit(px,hitTop,w,hitBottom-hitTop,imageMarkers.get(entry.getKey())));
                }
            } finally { bridge.call(graphics,gc,"disableScissor"); }
            syncLabels(chat,chatClass,scroll);
            if(focused && enlarged!=null) {
                Preview image=previews.get(enlarged.toString());
                if(image==null || image.failed || image.frames.isEmpty() || viewer==null) { enlarged=null; viewer=null; }
                else {
                    viewerWidth=width; viewerHeight=height; viewer.drag(mouseX,mouseY,width,height);
                    long now=System.currentTimeMillis(); int alpha=(int)(0xB0*viewer.progress(now));
                    bridge.call(graphics,gc,"fill",0,0,width,height,alpha<<24);
                    ImageViewer.Rect viewport=viewer.viewport(width,height), rect=viewer.animated(width,height,now);
                    boolean clipping=viewer.progress(now)>=1;
                    if(clipping) bridge.call(graphics,gc,"enableScissor",(int)Math.floor(viewport.x()),(int)Math.floor(viewport.y()),(int)Math.ceil(viewport.x()+viewport.width()),(int)Math.ceil(viewport.y()+viewport.height()));
                    try { bridge.call(graphics,gc,"blit",pipeline,image.frame(now),(int)Math.round(rect.x()),(int)Math.round(rect.y()),0f,0f,Math.max(1,(int)Math.round(rect.width())),Math.max(1,(int)Math.round(rect.height())),image.width,image.height,image.width,image.height); }
                    finally { if(clipping)bridge.call(graphics,gc,"disableScissor"); }
                }
            }
        } catch(Exception|LinkageError error) {
            renderError=true;
            try { restoreLabels(); Object chat=chat(); bridge.privateCall(chat,"net.minecraft.client.gui.components.ChatComponent","refreshTrimmedMessages"); }
            catch(Exception restoreError) { System.err.println("[MCQQ Images] Link restoration failed: "+restoreError); }
            clear(); System.err.println("[MCQQ Images] Chat rendering disabled; links remain usable: "+error);
        }
    }
    private Object chat() throws Exception {
        Object gui=bridge.field(bridge.client(),MC,"gui"); String owner="net.minecraft.client.gui.Gui";
        if(bridge.modern && !bridge.version.startsWith("26.1")) { gui=bridge.field(gui,owner,"hud"); owner="net.minecraft.client.gui.Hud"; }
        return bridge.call(gui,owner,"getChat");
    }
    private void restoreLabels() { for(LinkSlot slot:labelSlots.values()) if(slot.hidden)slot.show(true); drawn.clear(); }
    private void syncLabels(Object chat,String owner,int scroll) {
        if(labelHidingDisabled)return;
        boolean changed=labelsDirty; labelsDirty=false;
        try {
            for(var item:labelSlots.entrySet()) {
                URI uri=imageMarkers.get(item.getKey()); LinkSlot slot=item.getValue();
                Preview image=uri==null ? null : previews.get(uri.toString());
                boolean hide=image!=null && !image.failed && !image.frames.isEmpty() && drawn.contains(uri.toString());
                if(slot.hidden!=hide) { slot.show(!hide); changed=true; }
            }
            if(changed) { bridge.privateCall(chat,owner,"refreshTrimmedMessages"); bridge.privateSet(chat,owner,"chatScrollbarPos",scroll); }
        } catch(Exception error) {
            labelHidingDisabled=true; restoreLabels();
            try { bridge.privateCall(chat,owner,"refreshTrimmedMessages"); bridge.privateSet(chat,owner,"chatScrollbarPos",scroll); }
            catch(Exception ignored) { }
            System.err.println("[MCQQ Images] Link hiding disabled: "+error);
        }
    }
    private void text(Object graphics,Object font,String text,int x,int y,int color) throws Exception {
        bridge.call(graphics,bridge.graphicsClass(),bridge.modern?"text":"drawString",font,text,x,y,color);
    }
    private void evict(String key) throws Exception {
        Preview removed=previews.remove(key); if(removed==null)return;
        drawn.remove(key);
        Object manager=bridge.call(bridge.client(),MC,"getTextureManager");
        for(Object id:removed.frames)bridge.call(manager,"net.minecraft.client.renderer.texture.TextureManager","release",id);
    }
    private void clear() throws Exception { restoreLabels(); for(String key:List.copyOf(previews.keySet()))evict(key); imageMarkers.clear(); labelSlots.clear(); hits.clear(); enlarged=null; viewer=null; }
}
