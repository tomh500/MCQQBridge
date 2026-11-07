import org.bukkit.Bukkit;
import org.bukkit.entity.Player;
import org.bukkit.event.player.PlayerCommandPreprocessEvent;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.configuration.file.YamlConfiguration;
import top.luotiany1.mcqq.SaidPlugin;
import top.luotiany1.mcqq.Storage;
import java.io.*;
import java.lang.reflect.Proxy;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;
public class BackendProbe extends JavaPlugin {
 @Override public void onEnable() {
  Bukkit.getScheduler().runTask(this, () -> {
   String result;
   try {
    SaidPlugin bridge=(SaidPlugin) Bukkit.getPluginManager().getPlugin("MCQQSpigot");
    if(bridge==null || !bridge.isEnabled())throw new AssertionError("Chat plugin disabled on storage failure");
    try {bridge.storage();throw new AssertionError("Unavailable storage not reported");}catch(IllegalStateException expected) { }
    AtomicReference<byte[]> sent=new AtomicReference<>();
    Player player=(Player)Proxy.newProxyInstance(Player.class.getClassLoader(),new Class<?>[]{Player.class},(proxy,method,args)->{
     switch(method.getName()) {
      case "hasPermission":return true;
      case "isOp":return true;
      case "getServer":return Bukkit.getServer();
      case "getName":return "RegressionProbe";
      case "getUniqueId":return UUID.fromString("12345678-1234-4234-8234-123456789abc");
      case "sendPluginMessage":sent.set((byte[])args[2]);return null;
      case "hashCode":return System.identityHashCode(proxy);
      case "equals":return proxy==args[0];
      case "toString":return "RegressionProbe";
     }
     if(method.getReturnType()==boolean.class)return false;
     if(method.getReturnType()==int.class)return 0;
     return null;
    });
    PlayerCommandPreprocessEvent event=new PlayerCommandPreprocessEvent(player,"/said hello  中文 /op test");
    Bukkit.getPluginManager().callEvent(event);
    if(!event.isCancelled() || sent.get()==null)throw new AssertionError("/said did not relay while storage unavailable");
    String text=new DataInputStream(new ByteArrayInputStream(sent.get())).readUTF();
    if(!text.equals("hello  中文 /op test"))throw new AssertionError("Raw command tail changed");
    YamlConfiguration cfg=YamlConfiguration.loadConfiguration(new File("test-mysql.yml"));
    try(Storage store=new Storage(new File("probe-storage"),cfg)) {
     String key="probe/"+UUID.randomUUID();
     try {
      store.put(key,"旧版Spigot MySQL").get();
      if(!"旧版Spigot MySQL".equals(store.get(key).get()))throw new AssertionError("MySQL roundtrip failed");
     }finally {store.put(key,null).get();}
     java.lang.reflect.Field field=Storage.class.getDeclaredField("sql");field.setAccessible(true);
     if(!field.get(store).getClass().getName().startsWith("top.luotiany1.mcqq.libs.mysql."))throw new AssertionError("MySQL driver not isolated");
    }
    result="PASS: Spigot 1.12 /said survives storage failure; preserves raw text; isolated MySQL driver read/write/delete";
   }catch(Throwable e){e.printStackTrace();result="FAIL: "+e.getClass().getSimpleName()+": "+e.getMessage();}
   try {java.nio.file.Files.write(new File("backend-probe-result.txt").toPath(),result.getBytes(java.nio.charset.StandardCharsets.UTF_8));}catch(Exception e){e.printStackTrace();}
   Bukkit.shutdown();
  });
 }
}
