package top.luotiany1.mcqq;

import java.io.File;
import java.sql.*;
import java.util.concurrent.*;
import org.bukkit.configuration.file.YamlConfiguration;
import org.bukkit.plugin.java.JavaPlugin;
import com.mongodb.client.*;
import com.mongodb.client.model.ReplaceOptions;
import org.bson.Document;

/** Asynchronous namespaced key/value repository. No database work on the tick thread. */
public final class Storage implements AutoCloseable {
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private Connection sql;
    private MongoClient mongo;
    private MongoCollection<Document> collection;
    private YamlConfiguration yaml;
    private File file;
    private String table;
    public Storage(JavaPlugin plugin) throws Exception { this(plugin.getDataFolder(), plugin.getConfig()); }
    public Storage(File directory, org.bukkit.configuration.file.FileConfiguration config) throws Exception {
        directory.mkdirs();
        String type = config.getString("storage.type", "yaml");
        if (type.equals("yaml")) {
            file = new File(directory, "data.yml"); yaml = YamlConfiguration.loadConfiguration(file);
        } else if (type.equals("mongodb")) {
            mongo = MongoClients.create(config.getString("storage.mongodb.uri"));
            collection = mongo.getDatabase(config.getString("storage.mongodb.database", "mcqq")) .getCollection("settings");
        } else if (type.equals("sql")) {
            table = config.getString("storage.sql.table", "mcqq_settings");
            if (!table.matches("[A-Za-z_][A-Za-z0-9_]{0,62}")) throw new IllegalArgumentException("Invalid storage.sql.table");
            String url = config.getString("storage.sql.url", "");
            if (url.isEmpty()) url = "jdbc:sqlite:" + new File(directory, "data.db").getAbsolutePath();
            java.util.Properties credentials = new java.util.Properties();
            credentials.setProperty("user", config.getString("storage.sql.username", ""));
            credentials.setProperty("password", config.getString("storage.sql.password", ""));
            // Legacy Spigot registers an obsolete MySQL driver globally. Select our bundled driver explicitly.
            if (url.startsWith("jdbc:mysql:")) sql = new com.mysql.cj.jdbc.Driver().connect(url, credentials);
            else sql = DriverManager.getConnection(url, credentials);
            try (Statement statement = sql.createStatement()) { statement.executeUpdate("CREATE TABLE IF NOT EXISTS " + table + " (setting_key VARCHAR(190) PRIMARY KEY, setting_value TEXT NOT NULL)"); }
            // Detect incompatible pre-existing tables before enabling the plugin.
            try (Statement statement = sql.createStatement(); ResultSet ignored = statement.executeQuery("SELECT setting_key,setting_value FROM " + table + " WHERE 1=0")) { }
            catch (SQLException e) { sql.close(); throw new SQLException("Incompatible storage table; choose a dedicated storage.sql.table", e); }
        } else throw new IllegalArgumentException("Unknown storage.type");
    }
    private static void key(String key) { if (!key.matches("[a-zA-Z0-9_:/-]{1,190}")) throw new IllegalArgumentException("Invalid storage key"); }
    public CompletableFuture<String> get(String key) {
        key(key); return CompletableFuture.supplyAsync(() -> {
            try {
                if (yaml != null) return yaml.getString(key);
                if (collection != null) { Document value=collection.find(new Document("_id", key)).first(); return value == null ? null : value.getString("value"); }
                try (PreparedStatement statement=sql.prepareStatement("SELECT setting_value FROM " + table + " WHERE setting_key=?")) {
                    statement.setString(1,key); try (ResultSet result=statement.executeQuery()) { return result.next() ? result.getString(1) : null; }
                }
            } catch (Exception e) { throw new CompletionException(e); }
        }, worker);
    }
    public CompletableFuture<Void> put(String key, String value) {
        key(key); if (value != null && value.length() > 65536) throw new IllegalArgumentException("Value too large");
        return CompletableFuture.runAsync(() -> {
            try {
                if (yaml != null) { yaml.set(key,value); File temp=new File(file.getPath()+".new"); yaml.save(temp); java.nio.file.Files.move(temp.toPath(),file.toPath(),java.nio.file.StandardCopyOption.REPLACE_EXISTING); return; }
                if (collection != null) { if(value==null) collection.deleteOne(new Document("_id",key)); else collection.replaceOne(new Document("_id",key),new Document("_id",key).append("value",value),new ReplaceOptions().upsert(true)); return; }
                sql.setAutoCommit(false);
                try {
                    try(PreparedStatement statement=sql.prepareStatement("DELETE FROM " + table + " WHERE setting_key=?")) { statement.setString(1,key); statement.executeUpdate(); }
                    if(value!=null) try(PreparedStatement statement=sql.prepareStatement("INSERT INTO " + table + "(setting_key,setting_value) VALUES(?,?)")) { statement.setString(1,key);statement.setString(2,value);statement.executeUpdate(); }
                    sql.commit();
                } catch(Exception e) { sql.rollback(); throw e; } finally { sql.setAutoCommit(true); }
            } catch(Exception e) { throw new CompletionException(e); }
        },worker);
    }
    public void close() throws Exception {
        worker.shutdown(); if(!worker.awaitTermination(10,TimeUnit.SECONDS)) worker.shutdownNow();
        if(sql!=null) sql.close(); if(mongo!=null) mongo.close();
    }
}
