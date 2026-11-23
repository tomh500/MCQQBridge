package top.luotiany1.mcqq;

import org.bukkit.Bukkit;
import org.bukkit.command.Command;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.player.AsyncPlayerChatEvent;
import org.bukkit.event.player.PlayerCommandPreprocessEvent;
import org.bukkit.plugin.java.JavaPlugin;
import java.io.*;
import java.util.HashSet;
import java.util.HashMap;
import java.util.Map;
import java.util.Locale;
import org.bukkit.command.CommandMap;
import org.bukkit.configuration.ConfigurationSection;

/** Captures the raw command tail so repeated spaces and punctuation survive. */
public final class SaidPlugin extends JavaPlugin implements Listener {
    private Storage storage;
    private RemoteBridge remote;
    private BedWarsLobbyChat bedWarsLobby;
    public Storage storage() { if(storage==null) throw new IllegalStateException("Storage is unavailable"); return storage; }
    @Override public void onDisable() { if(storage!=null) try { storage.close(); } catch(Exception e) { getLogger().warning("Storage shutdown failed"); } }
    private final Map<String, String> destinations = new HashMap<>();
    @Override public void onEnable() {
        File legacyConfig = new File(getDataFolder().getParentFile(), "MCQQSaid/config.yml");
        File currentConfig = new File(getDataFolder(), "config.yml");
        if (!currentConfig.exists() && legacyConfig.isFile()) try {
            getDataFolder().mkdirs(); java.nio.file.Files.copy(legacyConfig.toPath(), currentConfig.toPath());
        } catch(IOException e) { throw new IllegalStateException("Legacy configuration migration failed", e); }
        saveDefaultConfig();
        remote = new RemoteBridge(this);
        remote.start();
        try { storage = new Storage(this); } catch(Exception e) { getLogger().severe("Storage initialization failed: " + e.getClass().getSimpleName() + "; chat remains enabled. Check database settings."); }
        if (!getConfig().getBoolean("features.chat", true)) return;
        ConfigurationSection commands = getConfig().getConfigurationSection("group-commands");
        if (commands != null) for (String name : commands.getKeys(false)) {
            String key = name.toLowerCase(Locale.ROOT);
            String group = commands.getString(name, "").trim();
            if (!key.matches("[a-z0-9_-]+") || key.equals("said") || group.isEmpty() || group.length() > 128) {
                getLogger().warning("Invalid group command: " + name); continue;
            }
            try {
                CommandMap map = (CommandMap) getServer().getClass().getMethod("getCommandMap").invoke(getServer());
                if (map.getCommand(key) != null) { getLogger().warning("Command already registered: " + key); continue; }
                final String destination = group;
                Command command = new Command(key) {
                    @Override public boolean execute(CommandSender sender, String label, String[] args) {
                        said(sender, String.join(" ", args), destination);
                        return true;
                    }
                };
                if (map.register("mcqqsaid", command)) destinations.put(key, group);
            } catch (ReflectiveOperationException ex) { getLogger().warning("Unable to register " + key + ": " + ex); }
        }
        getServer().getMessenger().registerOutgoingPluginChannel(this, "mcqq:chat");
        if (getConfig().getBoolean("features.bedwars-lobby-chat")) {
            bedWarsLobby = new BedWarsLobbyChat(this);
        }
        getServer().getPluginManager().registerEvents(this, this);
    }
    private void said(CommandSender sender, String text, String group) {
        if (!getConfig().getBoolean("features.chat", true)) { sender.sendMessage("群服聊天功能未启用。"); return; }
        if (!sender.hasPermission("mcqq.said")) { sender.sendMessage("你没有使用 /said 的权限。"); return; }
        if (text.trim().isEmpty()) { sender.sendMessage("用法：/said 文本"); return; }
        if (text.length() > 2000 || text.chars().anyMatch(c -> c < 32 && c != 9)) {
            sender.sendMessage("文本过长或包含控制字符（最多 2000 字符）。"); return;
        }
        if (!(sender instanceof Player)) { remote.sendConsole(text, group, sender); return; }
        Player player = (Player) sender;
        if (bedWarsLobby != null && !bedWarsLobby.isInLobby(player)) {
            player.sendMessage("请回到起床战争大厅后再发送群消息。");
            return;
        }
        // Run normal backend chat moderation, but let the proxy own delivery and formatting.
        // Never player.chat(text): leading '/' must remain text rather than execute commands.
        AsyncPlayerChatEvent chat = new AsyncPlayerChatEvent(false, player, text, new HashSet<>(Bukkit.getOnlinePlayers()));
        Bukkit.getPluginManager().callEvent(chat);
        if (chat.isCancelled()) return;
        if (chat.getMessage().length() > 2000) { player.sendMessage("处理后的聊天文本过长。"); return; }
        sendChat(player, chat.getMessage(), group, "mcqq:chat");
    }
    void sendChat(Player player, String text, String group, String channel) {
        try {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            DataOutputStream out = new DataOutputStream(bytes); out.writeUTF(text); if (!group.isEmpty()) out.writeUTF(group);
            player.sendPluginMessage(this, channel, bytes.toByteArray());
        } catch (IOException e) { player.sendMessage("聊天发送失败。"); }
    }
    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = true)
    public void command(PlayerCommandPreprocessEvent event) {
        String raw = event.getMessage(); int boundary = raw.indexOf(' ');
        String label = boundary < 0 ? raw : raw.substring(0, boundary);
        String key = label.substring(1).toLowerCase(Locale.ROOT);
        if (key.startsWith("mcqqsaid:")) key = key.substring("mcqqsaid:".length());
        if (!key.equals("said") && !destinations.containsKey(key)) return;
        event.setCancelled(true);
        said(event.getPlayer(), boundary < 0 ? "" : raw.substring(boundary + 1), destinations.getOrDefault(key, ""));
    }
    @Override public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        said(sender, String.join(" ", args), "");
        return true;
    }
}
