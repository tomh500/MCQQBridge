import top.luotiany1.mcqq.Storage;
import org.bukkit.configuration.file.YamlConfiguration;
import java.io.File;
public class StorageProbe {
 public static void main(String[] args) throws Exception {
  for(String type:new String[]{"yaml","sql"}) {
   File dir=new File(args[0], type); YamlConfiguration cfg=new YamlConfiguration();cfg.set("storage.type",type);cfg.set("storage.sql.table","custom_settings");
   try(Storage store=new Storage(dir,cfg)) {
    store.put("player/test","中文 & symbols").get();
    if(!"中文 & symbols".equals(store.get("player/test").get())) throw new AssertionError(type);
   }
   try(Storage store=new Storage(dir,cfg)) {
    if(!"中文 & symbols".equals(store.get("player/test").get())) throw new AssertionError("restart "+type);
    store.put("player/test",null).get();if(store.get("player/test").get()!=null) throw new AssertionError("delete");
   }
  }
  YamlConfiguration invalid=new YamlConfiguration();invalid.set("storage.type","sql");invalid.set("storage.sql.table","unsafe;DROP_TABLE");
  try { new Storage(new File(args[0],"invalid"),invalid); throw new AssertionError("unsafe table accepted"); }
  catch(IllegalArgumentException expected) { }
  System.out.println("PASS YAML/SQLite create, Unicode roundtrip, restart persistence, delete");
 }
}