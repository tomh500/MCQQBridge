package top.luotiany1.mcqq;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.bukkit.Bukkit;
import org.bukkit.OfflinePlayer;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Player;
import org.bukkit.permissions.Permission;
import org.bukkit.permissions.PermissionDefault;

import java.io.InputStreamReader;
import java.io.OutputStream;
import java.lang.reflect.Proxy;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/** Backend-side transport: HTTP works even when no player is connected. */
final class RemoteBridge {
    private final SaidPlugin plugin;
    RemoteBridge(SaidPlugin plugin) { this.plugin = plugin; }

    boolean configured() {
        return !plugin.getConfig().getString("remote.service-url", "").isEmpty()
            && plugin.getConfig().getString("remote.proxy-token", "").length() >= 32
            && !plugin.getConfig().getString("remote.server-name", "").isEmpty();
    }

    private JsonObject call(String path, JsonObject body) throws Exception {
        URL url = new URL(plugin.getConfig().getString("remote.service-url").replaceAll("/+$", "") + path);
        if (!url.getProtocol().equals("http") && !url.getProtocol().equals("https")) throw new IllegalArgumentException("service-url");
        if (url.getProtocol().equals("http") && !url.getHost().equals("127.0.0.1") && !url.getHost().equals("localhost")) throw new IllegalArgumentException("HTTPS required for remote API");
        HttpURLConnection c = (HttpURLConnection) url.openConnection();
        c.setConnectTimeout(2000); c.setReadTimeout(3000); c.setInstanceFollowRedirects(false);
        c.setRequestMethod("POST"); c.setDoOutput(true);
        c.setRequestProperty("Authorization", "Bearer " + plugin.getConfig().getString("remote.proxy-token"));
        c.setRequestProperty("Content-Type", "application/json");
        try {
            try (OutputStream out = c.getOutputStream()) { out.write(body.toString().getBytes(StandardCharsets.UTF_8)); }
            if (c.getResponseCode() != 200) throw new IllegalStateException("API HTTP " + c.getResponseCode());
            try (InputStreamReader in = new InputStreamReader(c.getInputStream(), StandardCharsets.UTF_8)) {
                return new JsonParser().parse(in).getAsJsonObject();
            }
        } finally { c.disconnect(); }
    }

    void start() {
        if (!configured() || !plugin.getConfig().getBoolean("remote.poll-commands", false)) return;
        Bukkit.getScheduler().runTaskTimerAsynchronously(plugin, () -> {
            try {
                JsonObject request = new JsonObject(); request.addProperty("server", plugin.getConfig().getString("remote.server-name"));
                JsonArray commands = call("/v1/command/poll", request).getAsJsonArray("commands");
                for (JsonElement element : commands) {
                    JsonObject item = element.getAsJsonObject();
                    Bukkit.getScheduler().runTask(plugin, () -> execute(item));
                }
            } catch (Exception e) { plugin.getLogger().fine("Remote command poll failed: " + e.getClass().getSimpleName()); }
        }, 20L, 20L);
    }

    void sendConsole(String text, String group, CommandSender sender) {
        if (!configured()) { sender.sendMessage("请先配置 remote.service-url、proxy-token 和 server-name。"); return; }
        Bukkit.getScheduler().runTaskAsynchronously(plugin, () -> {
            try {
                JsonObject body = new JsonObject();
                body.addProperty("source", "console"); body.addProperty("server", plugin.getConfig().getString("remote.server-name"));
                body.addProperty("text", text); body.addProperty("group", group); body.addProperty("event_id", UUID.randomUUID().toString());
                call("/v1/chat/from-game", body);
                sender.sendMessage("已从控制台发送群消息。");
            } catch (Exception e) { sender.sendMessage("群消息发送失败：" + e.getClass().getSimpleName()); }
        });
    }

    private void execute(JsonObject item) {
        String result;
        List<String> messages = new ArrayList<>();
        try {
            String command = item.get("command").getAsString().substring(1);
            boolean console = item.get("mode").getAsString().equals("console");
            Player online = null;
            CommandSender sender;
            if (console) sender = Bukkit.getConsoleSender();
            else {
                UUID uuid = UUID.fromString(item.get("game_uuid").getAsString());
                String name = item.get("game_name").getAsString();
                online = Bukkit.getPlayer(uuid);
                sender = online != null ? online : offlineSender(uuid, name, messages);
            }
            boolean accepted = Bukkit.dispatchCommand(sender, command);
            result = (accepted ? "已执行" : "指令未被接受") + (console ? "（Console 身份）" : online == null ? "（离线模拟身份）" : "（在线玩家身份）")
                + (messages.isEmpty() ? "。" : "：" + String.join(" | ", messages));
        } catch (Throwable e) {
            result = "指令执行失败：" + e.getClass().getSimpleName() + (e.getMessage() == null ? "" : " " + e.getMessage());
        }
        final String reply = result.length() > 1900 ? result.substring(0, 1900) : result;
        Bukkit.getScheduler().runTaskAsynchronously(plugin, () -> {
            try {
                JsonObject body = new JsonObject(); body.addProperty("server", plugin.getConfig().getString("remote.server-name"));
                body.addProperty("event", item.get("event").getAsString()); body.addProperty("result", reply);
                call("/v1/command/complete", body);
            } catch (Exception e) { plugin.getLogger().warning("Command result delivery failed: " + e.getClass().getSimpleName()); }
        });
    }

    private CommandSender offlineSender(UUID uuid, String name, List<String> messages) {
        OfflinePlayer offline = Bukkit.getOfflinePlayer(uuid);
        return (Player) Proxy.newProxyInstance(Player.class.getClassLoader(), new Class<?>[]{Player.class}, (proxy, method, args) -> {
            switch (method.getName()) {
                case "getName": return name;
                case "getUniqueId": return uuid;
                case "isOnline": return false;
                case "isOp": return offline.isOp();
                case "getServer": return Bukkit.getServer();
                case "sendMessage":
                    if (args != null && args.length > 0) {
                        if (args[0] instanceof String[]) for (String line : (String[]) args[0]) messages.add(line);
                        else messages.add(String.valueOf(args[0]));
                    }
                    return null;
                case "hasPermission":
                    String node = args[0] instanceof Permission ? ((Permission) args[0]).getName() : String.valueOf(args[0]);
                    Permission permission = Bukkit.getPluginManager().getPermission(node);
                    PermissionDefault level = permission == null ? Permission.DEFAULT_PERMISSION : permission.getDefault();
                    return level.getValue(offline.isOp());
                case "isPermissionSet": return false;
                case "toString": return "OfflinePlayerCommandSender(" + name + ")";
                case "hashCode": return uuid.hashCode();
                case "equals": return proxy == args[0];
                default: throw new UnsupportedOperationException("离线玩家不支持 " + method.getName());
            }
        });
    }
}
