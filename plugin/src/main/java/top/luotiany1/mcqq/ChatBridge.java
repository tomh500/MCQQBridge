package top.luotiany1.mcqq;

import com.google.gson.*;
import dev.aura.bungeechat.api.account.AccountManager;
import dev.aura.bungeechat.api.account.BungeeChatAccount;
import dev.aura.bungeechat.api.placeholder.BungeeChatContext;
import dev.aura.bungeechat.api.placeholder.PlaceHolder;
import dev.aura.bungeechat.api.placeholder.PlaceHolderManager;
import dev.aura.bungeechat.message.Format;
import dev.aura.bungeechat.message.MessagesService;
import net.md_5.bungee.api.connection.ProxiedPlayer;
import net.md_5.bungee.api.connection.Server;
import net.md_5.bungee.api.chat.TextComponent;
import net.md_5.bungee.api.chat.BaseComponent;
import net.md_5.bungee.api.chat.ClickEvent;
import net.md_5.bungee.api.chat.HoverEvent;
import net.md_5.bungee.api.event.PluginMessageEvent;
import net.md_5.bungee.api.plugin.Listener;
import net.md_5.bungee.config.Configuration;
import net.md_5.bungee.config.ConfigurationProvider;
import net.md_5.bungee.config.YamlConfiguration;
import net.md_5.bungee.event.EventHandler;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.*;
import java.util.concurrent.TimeUnit;

/** All bridge chat is rendered and routed at the proxy, never dispatched as a command. */
public final class ChatBridge implements Listener {
    static final String CHANNEL = "mcqq:chat";
    private final MCQQBridge plugin;
    private final Set<Long> delivered = new HashSet<>();
    private final Map<UUID, Long> cooldown = new HashMap<>();
    private final java.util.concurrent.ThreadPoolExecutor queue = new java.util.concurrent.ThreadPoolExecutor(1, 1, 0,
        TimeUnit.SECONDS, new java.util.concurrent.ArrayBlockingQueue<Runnable>(128));
    private volatile boolean busy;
    private final ThreadLocal<String> qqGroup = new ThreadLocal<>();
    private final ThreadLocal<String> qqRole = new ThreadLocal<>();
    private final ThreadLocal<String> qqTitle = new ThreadLocal<>();
    private final ThreadLocal<Boolean> saidSource = new ThreadLocal<>();
    private String lastTitleSnapshot;

    ChatBridge(MCQQBridge plugin) {
        this.plugin = plugin;
        plugin.getProxy().registerChannel(CHANNEL);
        plugin.getProxy().getPluginManager().registerListener(plugin, this);
        if (plugin.getProxy().getPluginManager().getPlugin("BungeeChat") != null) {
            PlaceHolderManager.registerPlaceholder(new PlaceHolder("mcqq_origin", context -> {
                if (qqRole.get() != null) return ChatFormat.qqPrefix(qqRole.get(), qqTitle.get(), qqGroup.get());
                return context.getSender().map(account -> ChatFormat.gamePrefix(account.getServerName(), ChatFormat.isBedrock(account.getUniqueId()), Boolean.TRUE.equals(saidSource.get()))).orElse("");
            }));
        }
        plugin.getProxy().getScheduler().schedule(plugin, this::poll, 1, 1, TimeUnit.SECONDS);
    }

    private List<String> servers() { return plugin.chatConfig().getStringList("chat-bridge.servers"); }
    private boolean enabled() {
        return plugin.chatConfig() != null && plugin.chatConfig().getBoolean("chat-bridge.enabled", false)
            && plugin.getProxy().getPluginManager().getPlugin("BungeeChat") != null;
    }
    private JsonObject call(String path, JsonObject data) throws Exception {
        Configuration config = plugin.chatConfig();
        HttpURLConnection c = (HttpURLConnection) new URL(config.getString("service-url").replaceAll("/+$", "") + "/v1/chat/" + path).openConnection();
        c.setConnectTimeout(2000); c.setReadTimeout(3000); c.setInstanceFollowRedirects(false);
        c.setRequestMethod("POST"); c.setDoOutput(true);
        c.setRequestProperty("Authorization", "Bearer " + config.getString("proxy-token"));
        c.setRequestProperty("Content-Type", "application/json");
        try {
            try (OutputStream out = c.getOutputStream()) { out.write(data.toString().getBytes(StandardCharsets.UTF_8)); }
            if (c.getResponseCode() != 200) throw new IOException("Chat API HTTP " + c.getResponseCode());
            try (Reader in = new InputStreamReader(c.getInputStream(), StandardCharsets.UTF_8)) {
                return new JsonParser().parse(in).getAsJsonObject();
            }
        } finally { c.disconnect(); }
    }

    private static String literal(String text) {
        return text.replace('\u00a7', '?').replaceAll("[\\p{Cc}\\p{Cf}]", " ");
    }

    private Optional<String> render(String uuid, String name, String text, boolean qq) {
        return render(uuid, name, text, qq, "member");
    }

    private Optional<String> render(String uuid, String name, String text, boolean qq, String role) {
        return render(uuid, name, text, qq, role, "");
    }

    private String titleFor(String memberOpenid) {
        Configuration config = plugin.chatConfig();
        if (config == null || memberOpenid.isEmpty()) return "";
        String direct = config.getString("chat-bridge.qq-titles." + memberOpenid, "");
        if (!ChatFormat.plain(direct).trim().isEmpty()) return direct;
        Configuration aliases = config.getSection("chat-bridge.qq-identities");
        for (String qq : new TreeSet<>(aliases.getKeys())) {
            if (memberOpenid.equals(aliases.getString(qq, ""))) {
                String title = config.getString("chat-bridge.qq-titles." + qq, "");
                if (!ChatFormat.plain(title).trim().isEmpty()) return title;
            }
        }
        return "";
    }

    private Optional<String> render(String uuid, String name, String text, boolean qq, String role, String memberOpenid) {
        return render(uuid, name, text, qq, role, memberOpenid, null);
    }

    private Optional<String> render(String uuid, String name, String text, boolean qq, String role, String memberOpenid, String selfTitle) {
        String title = qq ? (selfTitle == null ? titleFor(memberOpenid) : selfTitle) : "";
        Optional<BungeeChatAccount> account = uuid.isEmpty() ? Optional.empty() : AccountManager.getAccount(UUID.fromString(uuid));
        if (account.isPresent()) {
            BungeeChatContext context = new BungeeChatContext(account.get(), text);
            try {
                if (qq) { qqRole.set(role); qqTitle.set(title); }
                else saidSource.set(true);
                if (qq && (text.trim().isEmpty() || text.equals("[表情包：暂无图片链接]"))) {
                    if (account.get().isMuted()) return Optional.empty();
                    return Optional.of(Format.GLOBAL_CHAT.get(context));
                }
                return MessagesService.preProcessMessage(context, Format.GLOBAL_CHAT);
            } finally { qqRole.remove(); qqTitle.remove(); saidSource.remove(); }
        }
        return Optional.of((qq ? ChatFormat.qqPrefix(role, title, qqGroup.get()) + " " : "") + "\u00a7f" + literal(name) + "\u00a77: \u00a7f" + literal(text));
    }

    private void broadcast(String text) {
        // BungeeChat's multicast sender, with an explicit server predicate: no global leakage.
        MessagesService.sendToMatchingPlayers(text, MessagesService.getServerPredicate(servers()));
    }

    private BaseComponent mediaMessage(String text, JsonArray attachments) {
        TextComponent root = new TextComponent("");
        for (BaseComponent part : TextComponent.fromLegacyText(text)) root.addExtra(part);
        for (JsonElement value : attachments) {
            JsonObject item = value.getAsJsonObject();
            boolean sticker = item.get("kind").getAsString().equals("sticker");
            String url = item.get("url").getAsString();
            TextComponent label = new TextComponent(" " + (sticker ? "[表情包]" : "[图片]"));
            label.setColor(net.md_5.bungee.api.ChatColor.AQUA);
            try {
                java.net.URI uri = java.net.URI.create(url);
                if (uri.getHost() != null && (uri.getScheme().equals("https") || uri.getScheme().equals("http"))) {
                    label.setUnderlined(true);
                    label.setClickEvent(new ClickEvent(ClickEvent.Action.OPEN_URL, url));
                    label.setHoverEvent(new HoverEvent(HoverEvent.Action.SHOW_TEXT, new BaseComponent[]{new TextComponent("点击打开" + (sticker ? "表情包" : "图片"))}));
                }
            } catch (IllegalArgumentException ignored) { }
            if (label.getClickEvent() == null) label.setText(" " + (sticker ? "[表情包暂不可用]" : "[图片暂不可用]"));
            root.addExtra(label);
        }
        return root;
    }

    private void broadcastMedia(String text, JsonArray attachments) {
        if (attachments.size() == 0) { broadcast(text); return; }
        BaseComponent message = mediaMessage(text, attachments);
        for (ProxiedPlayer player : plugin.getProxy().getPlayers()) {
            if (player.getServer() != null && servers().contains(player.getServer().getInfo().getName())) player.sendMessage(message);
        }
    }

    private void syncTitles(JsonArray snapshot) throws IOException {
        String revision = snapshot.toString();
        if (revision.equals(lastTitleSnapshot)) return;
        Configuration yaml = new Configuration();
        yaml.set("managed-by", "QQBot /设置头衔 and /清除头衔");
        for (JsonElement element : snapshot) {
            JsonObject item = element.getAsJsonObject();
            yaml.set("groups." + item.get("group").getAsString() + "." + item.get("member").getAsString(), item.get("title").getAsString());
        }
        File target = new File(plugin.getDataFolder(), "qq-titles.yml");
        File temporary = new File(plugin.getDataFolder(), "qq-titles.yml.new");
        ConfigurationProvider.getProvider(YamlConfiguration.class).save(yaml, temporary);
        Files.move(temporary.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING);
        lastTitleSnapshot = revision;
    }

    private void poll() {
        if (!enabled() || busy) return;
        busy = true;
        try {
            JsonObject batch = call("to-game", new JsonObject());
            if (batch.has("title_snapshot")) syncTitles(batch.getAsJsonArray("title_snapshot"));
            for (JsonElement element : batch.getAsJsonArray("messages")) {
                JsonObject item = element.getAsJsonObject(); long id = item.get("id").getAsLong();
                if (!delivered.contains(id)) {
                    qqGroup.set(item.has("group_name") ? item.get("group_name").getAsString() : "群内");
                    Optional<String> message;
                    try { message = render(item.get("uuid").getAsString(), item.get("name").getAsString(), literal(item.get("text").getAsString()), true,
                        item.has("role") ? item.get("role").getAsString() : "member",
                        item.has("qq_id") ? item.get("qq_id").getAsString() : "",
                        item.has("title") && !item.get("title").isJsonNull() ? item.get("title").getAsString() : null); } finally { qqGroup.remove(); }
                    message.ifPresent(text -> broadcastMedia(text, item.has("media") ? item.getAsJsonArray("media") : new JsonArray()));
                    delivered.add(id);
                }
                JsonObject ack = new JsonObject(); JsonArray ids = new JsonArray(); ids.add(id); ack.add("ids", ids);
                call("ack-game", ack);
            }
            if (delivered.size() > 4096) delivered.clear();
        } catch (Exception e) {
            // The whitelist has separate workers; chat failures cannot block login verification.
            plugin.getLogger().fine("Chat poll unavailable: " + e.getClass().getSimpleName());
        } finally { busy = false; }
    }

    @EventHandler public void said(PluginMessageEvent event) {
        if (!event.getTag().equals(CHANNEL)) return;
        event.setCancelled(true);
        if (!enabled() || !(event.getSender() instanceof Server) || !(event.getReceiver() instanceof ProxiedPlayer)) return;
        Server server = (Server) event.getSender(); ProxiedPlayer player = (ProxiedPlayer) event.getReceiver();
        // Accept server-origin data only; a client cannot impersonate another player or server.
        if (player.getServer() != server || !servers().contains(server.getInfo().getName())) return;
        try {
            DataInputStream in = new DataInputStream(new ByteArrayInputStream(event.getData()));
            String text = in.readUTF();
            String target = in.available() > 0 ? in.readUTF() : "";
            if (in.available() != 0 || target.length() > 128 || text.trim().isEmpty() || text.length() > 2000) return;
            synchronized (cooldown) {
                long now = System.currentTimeMillis();
                if (now - cooldown.getOrDefault(player.getUniqueId(), 0L) < 1500) {
                    player.sendMessage(new TextComponent("发送太快，请稍后再试。")); return;
                }
                if (cooldown.size() > 4096) cooldown.clear();
                cooldown.put(player.getUniqueId(), now);
            }
            final String content = plugin.wordFilter().filter(player, text);
            if (content == null) return;
            queue.execute(() -> {
                try {
                    Optional<String> rendered = render(player.getUniqueId().toString(), player.getName(), content, false);
                    if (!rendered.isPresent()) return;
                    broadcast(rendered.get());
                    JsonObject data = new JsonObject();
                    data.addProperty("uuid", player.getUniqueId().toString()); data.addProperty("name", player.getName());
                    data.addProperty("text", content); data.addProperty("group", target); data.addProperty("server", server.getInfo().getName());
                    data.addProperty("event_id", UUID.randomUUID().toString()); call("from-game", data);
                } catch (Exception e) {
                    player.sendMessage(new TextComponent("群消息提交失败，请稍后重试；游戏内可能已显示。"));
                }
            });
        } catch (java.util.concurrent.RejectedExecutionException e) {
            player.sendMessage(new TextComponent("聊天服务繁忙，请稍后重试。"));
        } catch (IOException ignored) { }
    }

    void close() { queue.shutdownNow(); plugin.getProxy().unregisterChannel(CHANNEL); }
}

