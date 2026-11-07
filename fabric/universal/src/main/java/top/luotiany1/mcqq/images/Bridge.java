package top.luotiany1.mcqq.images;

import java.io.InputStream;
import java.lang.reflect.*;
import java.util.*;
import net.fabricmc.loader.api.FabricLoader;

/** Minecraft references are names, so the Java 21 entrypoint is safe on every target. */
final class Bridge {
    final String version;
    final boolean modern;
    private final Properties names = new Properties();
    private final Map<String, Class<?>> classes = new HashMap<>();
    private final Map<String, Method> methods = new HashMap<>();
    private final Map<String, Field> fields = new HashMap<>();

    Bridge(String version) throws Exception {
        this.version=version; modern=version.startsWith("26.");
        try (InputStream input=Bridge.class.getResourceAsStream("/bindings/"+version+".properties")) {
            if (input==null) throw new IllegalArgumentException("Unsupported Minecraft: "+version);
            names.load(input);
        }
    }
    Class<?> type(String name) throws Exception {
        Class<?> result=classes.get(name);
        if (result==null) {
            String runtime=names.getProperty("c|"+name,name);
            if (!modern) runtime=FabricLoader.getInstance().getMappingResolver().mapClassName("intermediary",runtime);
            result=Class.forName(runtime); classes.put(name,result);
        }
        return result;
    }
    Object field(Object target, String owner, String name) throws Exception {
        String key=owner+"|"+name;
        Field field=fields.get(key);
        if (field==null) {
            field=type(owner).getField(names.getProperty("f|"+owner+"|"+name,name)); fields.put(key,field);
        }
        return field.get(target);
    }
    Object privateField(Object target,String owner,String name) throws Exception {
        Field field=type(owner).getDeclaredField(names.getProperty("f|"+owner+"|"+name,name));
        field.setAccessible(true); return field.get(target);
    }
    void privateSet(Object target,String owner,String name,Object value) throws Exception {
        Field field=type(owner).getDeclaredField(names.getProperty("f|"+owner+"|"+name,name));
        field.setAccessible(true); field.set(target,value);
    }
    Object privateCall(Object target,String owner,String name) throws Exception {
        Set<String> candidates=new HashSet<>(Arrays.asList(names.getProperty("m|"+owner+"|"+name,name).split(",")));
        for(Method method:type(owner).getDeclaredMethods()) if(candidates.contains(method.getName()) && method.getParameterCount()==0) {
            method.setAccessible(true); return method.invoke(target);
        }
        throw new NoSuchMethodException(owner+"|"+name);
    }
    Object call(Object target, String owner, String name, Object... args) throws Exception {
        StringBuilder key=new StringBuilder(owner+"|"+name);
        for (Object arg:args) key.append('|').append(arg==null ? "null" : arg.getClass().getName());
        Method selected=methods.get(key.toString());
        if (selected==null) {
            Set<String> candidates=new HashSet<>(Arrays.asList(names.getProperty("m|"+owner+"|"+name,name).split(",")));
            for (Method method:type(owner).getMethods()) {
                if (candidates.contains(method.getName()) && compatible(method.getParameterTypes(),args)) {
                    selected=method; break;
                }
            }
            if (selected==null) throw new NoSuchMethodException(key.toString());
            methods.put(key.toString(),selected);
        }
        return selected.invoke(target,args);
    }
    Object create(String owner,Object... args) throws Exception {
        for (Constructor<?> constructor:type(owner).getConstructors())
            if (compatible(constructor.getParameterTypes(),args)) return constructor.newInstance(args);
        throw new NoSuchMethodException("Constructor "+owner);
    }
    static boolean compatible(Class<?>[] types,Object[] args) {
        if (types.length!=args.length) return false;
        for (int i=0;i<types.length;i++) {
            Class<?> type=types[i];
            if (type.isPrimitive()) type=Map.of(int.class,Integer.class,boolean.class,Boolean.class,
                float.class,Float.class,double.class,Double.class,long.class,Long.class,
                byte.class,Byte.class,short.class,Short.class,char.class,Character.class).get(type);
            if (args[i]==null ? types[i].isPrimitive() : !type.isInstance(args[i])) return false;
        }
        return true;
    }
    String idClass() { return version.equals("1.21.4") || version.equals("1.21.5") || version.equals("1.21.6")
        || version.equals("1.21.7") || version.equals("1.21.8") || version.equals("1.21.9") || version.equals("1.21.10")
        ? "net.minecraft.resources.ResourceLocation" : "net.minecraft.resources.Identifier"; }
    Object id(String path) throws Exception { return call(null,idClass(),"fromNamespaceAndPath","mcqq_images",path); }
    Object client() throws Exception { return call(null,"net.minecraft.client.Minecraft","getInstance"); }
    void execute(Runnable runnable) throws Exception {
        call(client(),"net.minecraft.util.thread.BlockableEventLoop","execute",runnable);
    }
    String text(Object component) throws Exception { return (String)call(component,"net.minecraft.network.chat.Component","getString"); }
    Object texture(Object image) throws Exception {
        return version.equals("1.21.4") ? create("net.minecraft.client.renderer.texture.DynamicTexture",image)
            : create("net.minecraft.client.renderer.texture.DynamicTexture",(java.util.function.Supplier<String>)()->"QQ chat image",image);
    }
    String graphicsClass() { return modern
        ? "net.minecraft.client.gui.GuiGraphicsExtractor" : "net.minecraft.client.gui.GuiGraphics"; }
    boolean oldBlit() { return version.equals("1.21.4") || version.equals("1.21.5"); }
    Object pipeline() throws Exception {
        if (oldBlit()) return (java.util.function.Function<Object,Object>)id -> {
            try { return call(null,"net.minecraft.client.renderer.RenderType","guiTextured",id); }
            catch(Exception error) { throw new IllegalStateException(error); }
        };
        return field(null,"net.minecraft.client.renderer.RenderPipelines","GUI_TEXTURED");
    }
    Object screen() throws Exception {
        Object minecraft=client();
        return modern && !version.startsWith("26.1")
            ? call(field(minecraft,"net.minecraft.client.Minecraft","gui"),"net.minecraft.client.gui.Gui","screen")
            : field(minecraft,"net.minecraft.client.Minecraft","screen");
    }
    boolean hidden() throws Exception {
        Object minecraft=client();
        if (modern && !version.startsWith("26.1")) {
            Object gui=field(minecraft,"net.minecraft.client.Minecraft","gui");
            return (boolean)call(field(gui,"net.minecraft.client.gui.Gui","hud"),"net.minecraft.client.gui.Hud","isHidden");
        }
        return (boolean)field(field(minecraft,"net.minecraft.client.Minecraft","options"),"net.minecraft.client.Options","hideGui");
    }
}
