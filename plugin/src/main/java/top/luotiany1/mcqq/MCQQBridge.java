package top.luotiany1.mcqq;

import net.md_5.bungee.api.CommandSender;
import net.md_5.bungee.api.chat.TextComponent;
import net.md_5.bungee.api.connection.ProxiedPlayer;
import net.md_5.bungee.api.event.LoginEvent;
import net.md_5.bungee.api.plugin.Command;
import net.md_5.bungee.api.plugin.Listener;
import net.md_5.bungee.api.plugin.Plugin;
import net.md_5.bungee.config.Configuration;
import net.md_5.bungee.config.ConfigurationProvider;
import net.md_5.bungee.config.YamlConfiguration;
import net.md_5.bungee.event.EventHandler;
import net.md_5.bungee.event.EventPriority;

import java.io.File;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.UUID;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/** Proxy-wide whitelist. No command dispatch, console injection, or name-based trust. */
public final class MCQQBridge extends Plugin implements Listener {
    private volatile Configuration config;
    private volatile boolean configured;
    private volatile boolean enabled;
    private ChatBridge chat;
    private ChatPreferences chatPreferences;
    private WordFilter wordFilter;
    WordFilter wordFilter() { return wordFilter; }
    Configuration chatConfig() { return configured ? config : null; }
    private final ThreadPoolExecutor workers = new ThreadPoolExecutor(4, 4, 0,
        TimeUnit.SECONDS, new ArrayBlockingQueue<Runnable>(128));

    @Override public void onEnable() {
        File legacy = new File(getDataFolder().getParentFile(), "QQWhitelist");
        if (!getDataFolder().exists() && legacy.isDirectory()) {
            try (java.util.stream.Stream<java.nio.file.Path> paths = Files.walk(legacy.toPath())) {
                for (java.nio.file.Path source : (Iterable<java.nio.file.Path>) paths::iterator) {
                    java.nio.file.Path target = getDataFolder().toPath().resolve(legacy.toPath().relativize(source));
                    if (Files.isDirectory(source)) Files.createDirectories(target);
                    else Files.copy(source, target);
                }
            } catch (Exception e) { throw new IllegalStateException("Legacy configuration migration failed", e); }
        }
        getProxy().getPluginManager().registerListener(this, this);
        getProxy().getPluginManager().registerCommand(this, new Command("mcqq", null, "qqwl") {
            @Override public void execute(CommandSender sender, String[] args) {
                if (sender != getProxy().getConsole()) {
                    sender.sendMessage(new TextComponent("只能从代理控制台管理白名单。"));
                    return;
                }
                if (args.length == 1 && args[0].equalsIgnoreCase("reload")) { loadConfig(); if (wordFilter != null) wordFilter.reload(); }
                sender.sendMessage(new TextComponent("MCQQBridge enabled=" + enabled + ", configured=" + configured));
            }
        });
        getProxy().getPluginManager().registerCommand(this, new Command("qqverify") {
            @Override public void execute(CommandSender sender, String[] args) {
                if (!(sender instanceof ProxiedPlayer) || args.length != 1 || !args[0].matches("[A-Fa-f0-9]{12}")) {
                    sender.sendMessage(new TextComponent("请在绑定的 Java 正版账号内输入 /qqverify 关联码。"));
                    return;
                }
                final ProxiedPlayer player = (ProxiedPlayer) sender;
                final String code = args[0];
                try {
                    workers.execute(() -> {
                        try {
                            UUID incoming = player.getUniqueId();
                            if (!configured || !getProxy().getConfig().isOnlineMode() || incoming.getMostSignificantBits() == 0 ||
                                !accountId(incoming).equals(incoming)) throw new IllegalStateException("Java identity required");
                            HttpURLConnection connection = (HttpURLConnection) new URL(config.getString("service-url").replaceAll("/+$", "") + "/v1/verify").openConnection();
                            connection.setConnectTimeout(2000);
                            connection.setReadTimeout(3000);
                            connection.setInstanceFollowRedirects(false);
                            connection.setRequestMethod("POST");
                            connection.setDoOutput(true);
                            connection.setRequestProperty("Content-Type", "application/json");
                            connection.setRequestProperty("Authorization", "Bearer " + config.getString("proxy-token"));
                            try {
                                String payload = "{\"code\":\"" + code + "\",\"uuid\":\"" + incoming + "\",\"java_authenticated\":true}";
                                try (OutputStream stream = connection.getOutputStream()) { stream.write(payload.getBytes(StandardCharsets.UTF_8)); }
                                if (connection.getResponseCode() != 200) throw new IllegalStateException("Verification failed");
                                player.sendMessage(new TextComponent("关联成功！基岩账号重新登录后将共用此 Java 账号的数据。"));
                            } finally { connection.disconnect(); }
                        } catch (Exception e) {
                            player.sendMessage(new TextComponent("验证失败：请确认使用原 Java 正版账号、关联码有效，且绑定服务可用。"));
                        }
                    });
                } catch (java.util.concurrent.RejectedExecutionException e) {
                    player.sendMessage(new TextComponent("服务繁忙，请稍后重试。"));
                }
            }
        });
        loadConfig();
        wordFilter = new WordFilter(this);
        chat = new ChatBridge(this);
        chatPreferences = new ChatPreferences(this);
        getProxy().getScheduler().schedule(this, this::recheck, 5, 5, TimeUnit.SECONDS);
    }

    private synchronized void loadConfig() {
        configured = false;
        enabled = true; // Malformed configuration must never silently open the server.
        try {
            getDataFolder().mkdirs();
            File file = new File(getDataFolder(), "config.yml");
            if (!file.exists()) {
                try (InputStream input = getResourceAsStream("config.yml")) {
                    Files.copy(input, file.toPath(), StandardCopyOption.REPLACE_EXISTING);
                }
            }
            Configuration loaded = ConfigurationProvider.getProvider(YamlConfiguration.class).load(file);
            boolean requested = loaded.getBoolean("features.whitelist", loaded.getBoolean("enabled", false));
            String token = loaded.getString("proxy-token", "");
            URL url = new URL(loaded.getString("service-url", "") + "/v1/authorize");
            if (!url.getProtocol().equals("http") && !url.getProtocol().equals("https")) throw new IllegalArgumentException("URL protocol");
            // Unencrypted transport is allowed only over a local connection or SSH tunnel.
            if (url.getProtocol().equals("http") && !url.getHost().equals("127.0.0.1") && !url.getHost().equals("localhost"))
                throw new IllegalArgumentException("Remote service requires HTTPS");
            if (requested && (token.length() < 32 || token.startsWith("CHANGE_ME")))
                throw new IllegalArgumentException("Set proxy-token before enabling");
            if (requested && !getProxy().getConfig().isOnlineMode())
                throw new IllegalArgumentException("BungeeCord online_mode must be true");
            config = loaded;
            enabled = requested;
            configured = true;
            getLogger().info("QQ whitelist enabled=" + enabled);
        } catch (Exception e) {
            getLogger().severe("Invalid whitelist configuration; new logins will be denied: " + e.getClass().getSimpleName());
        }
    }

    /** Floodgate linked players are checked by their Xbox XUID, not their linked Java UUID. */
    private UUID accountId(UUID incoming) throws Exception {
        if (getProxy().getPluginManager().getPlugin("floodgate") != null) {
            Class<?> apiType = Class.forName("org.geysermc.floodgate.api.FloodgateApi");
            Object api = apiType.getMethod("getInstance").invoke(null);
            boolean bedrock = (Boolean) apiType.getMethod("isFloodgatePlayer", UUID.class).invoke(api, incoming);
            if (bedrock) {
                Object player = apiType.getMethod("getPlayer", UUID.class).invoke(api, incoming);
                Class<?> playerType = Class.forName("org.geysermc.floodgate.api.player.FloodgatePlayer");
                String xuid = (String) playerType.getMethod("getXuid").invoke(player);
                return new UUID(0, Long.parseUnsignedLong(xuid));
            }
        }
        if (incoming == null || incoming.getMostSignificantBits() == 0)
            throw new IllegalArgumentException("Missing authenticated identity");
        return incoming;
    }

    private boolean authorized(UUID incoming) throws Exception {
        if (!configured) throw new IllegalStateException("Not configured");
        Configuration current = config;
        UUID account = accountId(incoming);
        URL url = new URL(current.getString("service-url").replaceAll("/+$", "") + "/v1/authorize?uuid=" + account + "&session_uuid=" + incoming);
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        connection.setConnectTimeout(Math.max(100, current.getInt("connect-timeout-ms", 2000)));
        connection.setReadTimeout(Math.max(100, current.getInt("read-timeout-ms", 3000)));
        connection.setInstanceFollowRedirects(false);
        connection.setRequestProperty("Authorization", "Bearer " + current.getString("proxy-token"));
        try {
            if (connection.getResponseCode() != 200) throw new IllegalStateException("Whitelist API unavailable");
            try (InputStream stream = connection.getInputStream()) {
                byte[] bytes = new byte[6];
                int length = 0, count;
                while (length < bytes.length && (count = stream.read(bytes, length, bytes.length - length)) != -1) length += count;
                String result = new String(bytes, 0, length, StandardCharsets.UTF_8);
                if (result.equals("allow")) return true;
                if (result.equals("deny")) return false;
                throw new IllegalStateException("Invalid whitelist response");
            }
        } finally { connection.disconnect(); }
    }

    private String message(boolean failure) {
        if (config == null) return "白名单服务配置错误，请联系服主。";
        return config.getString(failure ? "unavailable-message" : "denied-message");
    }

    @EventHandler(priority = EventPriority.HIGHEST)
    public void login(final LoginEvent event) {
        if (!enabled || event.isCancelled()) return;
        event.registerIntent(this);
        try {
            workers.execute(() -> {
                try {
                    if (!authorized(event.getConnection().getUniqueId())) {
                        event.setCancelled(true);
                        event.setCancelReason(message(false));
                    }
                } catch (Exception e) {
                    event.setCancelled(true);
                    event.setCancelReason(message(true));
                } finally { event.completeIntent(this); }
            });
        } catch (java.util.concurrent.RejectedExecutionException e) {
            event.setCancelled(true);
            event.setCancelReason(message(true));
            event.completeIntent(this);
        }
    }

    private void recheck() {
        if (!enabled || !configured) return;
        for (final ProxiedPlayer player : new ArrayList<>(getProxy().getPlayers())) {
            try {
                workers.execute(() -> {
                    try {
                        if (enabled && !authorized(player.getUniqueId()) && player.isConnected())
                            player.disconnect(new TextComponent(message(false)));
                    } catch (Exception ignored) {
                        // An outage denies new logins, but does not mass-kick established sessions.
                    }
                });
            } catch (java.util.concurrent.RejectedExecutionException ignored) { break; }
        }
    }

    @Override public void onDisable() {
        if (chatPreferences != null) chatPreferences.close();
        if (chat != null) chat.close();
        getProxy().getScheduler().cancel(this);
        // Gracefully finish pending LoginEvent intents.
        workers.shutdown();
    }
}

