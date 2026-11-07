import top.luotiany1.mcqq.Storage;
import org.bukkit.configuration.file.YamlConfiguration;
import java.io.File;
public class MySQLProbe {
 public static void main(String[] args) throws Exception {
  YamlConfiguration config=YamlConfiguration.loadConfiguration(new File(args[0]));
  String key="probe/"+java.util.UUID.randomUUID();
  try(Storage store=new Storage(new File(args[1]),config)) {
   try {
    store.put(key,"中文 English MySQL").get(15,java.util.concurrent.TimeUnit.SECONDS);
    if(!"中文 English MySQL".equals(store.get(key).get(15,java.util.concurrent.TimeUnit.SECONDS))) throw new AssertionError("MySQL roundtrip");
   } finally { store.put(key,null).get(15,java.util.concurrent.TimeUnit.SECONDS); }
   if(store.get(key).get(15,java.util.concurrent.TimeUnit.SECONDS)!=null)throw new AssertionError("MySQL delete");
  }
  System.out.println("PASS MySQL custom table, Unicode read/write and probe cleanup");
 }
}