package top.luotiany1.mcqq;

import io.netty.channel.Channel;
import io.netty.channel.ChannelHandlerContext;
import io.netty.channel.ChannelOutboundHandlerAdapter;
import io.netty.channel.ChannelPromise;
import io.netty.util.ReferenceCountUtil;
import java.io.File;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.IntSupplier;
import java.util.function.Supplier;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import net.md_5.bungee.UserConnection;
import net.md_5.bungee.api.ChatColor;
import net.md_5.bungee.api.CommandSender;
import net.md_5.bungee.api.chat.TextComponent;
import net.md_5.bungee.api.connection.ProxiedPlayer;
import net.md_5.bungee.api.event.PostLoginEvent;
import net.md_5.bungee.api.plugin.Command;
import net.md_5.bungee.api.plugin.Listener;
import net.md_5.bungee.config.Configuration;
import net.md_5.bungee.config.ConfigurationProvider;
import net.md_5.bungee.config.YamlConfiguration;
import net.md_5.bungee.event.EventHandler;
import net.md_5.bungee.protocol.packet.Chat;
import net.md_5.bungee.protocol.packet.SystemChat;
import net.md_5.bungee.chat.ComponentSerializer;

/** Filter formatted public chat at the outgoing packet boundary, preserving BungeeChat routing. */
public final class ChatPreferences implements Listener {
    private static final String HANDLER = "mcqq-chat-preferences";
    private static final String[] NAMES = {"接收全量信息", "仅接收游戏内信息", "仅接收当前子服信息", "屏蔽一切聊天信息"};
    private static final Pattern GAME = Pattern.compile("^\\[([^\\]]+)\\]\\[(?:java|bedrock)\\]");
    private final MCQQBridge plugin;
    private final ConcurrentHashMap<UUID,Integer> modes = new ConcurrentHashMap<>();

    ChatPreferences(MCQQBridge plugin) {
        this.plugin = plugin;
        File file = new File(plugin.getDataFolder(), "chat-preferences.yml");
        try {
            if (file.isFile()) {
                Configuration data = ConfigurationProvider.getProvider(YamlConfiguration.class).load(file);
                for (String key : data.getKeys()) {
                    int value = data.getInt(key, 0);
                    if (value >= 0 && value < 4) modes.put(UUID.fromString(key), value);
                }
            }
        } catch (Exception error) { plugin.getLogger().warning("Unable to read chat preferences: " + error.getClass().getSimpleName()); }
        plugin.getProxy().getPluginManager().registerListener(plugin, this);
        plugin.getProxy().getPluginManager().registerCommand(plugin, new Command("ignoremsg") {
            @Override public void execute(CommandSender sender, String[] args) {
                if (!(sender instanceof ProxiedPlayer)) { sender.sendMessage(new TextComponent("请在游戏内使用 /ignoremsg。")); return; }
                if (args.length != 0) { sender.sendMessage(new TextComponent("直接输入 /ignoremsg，按顺序切换接收状态。")); return; }
                UUID id = ((ProxiedPlayer)sender).getUniqueId();
                int next = (modes.getOrDefault(id,0)+1)%4;
                int previous = modes.getOrDefault(id,0);
                modes.put(id,next);
                try { save(); }
                catch (Exception error) {
                    modes.put(id,previous);
                    sender.sendMessage(new TextComponent("状态保存失败，请稍后重试。")); return;
                }
                sender.sendMessage(new TextComponent("聊天接收状态：" + NAMES[next] + "（再次 /ignoremsg 切换）"));
            }
        });
        for (ProxiedPlayer player : plugin.getProxy().getPlayers()) attach(player);
    }
    private synchronized void save() throws Exception {
        Configuration data = new Configuration();
        for (UUID id : modes.keySet()) if (modes.get(id) != 0) data.set(id.toString(),modes.get(id));
        File temporary = new File(plugin.getDataFolder(), "chat-preferences.yml.new");
        ConfigurationProvider.getProvider(YamlConfiguration.class).save(data,temporary);
        Files.move(temporary.toPath(),new File(plugin.getDataFolder(),"chat-preferences.yml").toPath(),StandardCopyOption.REPLACE_EXISTING);
    }
    public static boolean allows(int mode, String text, String currentServer) {
        if (mode == 0) return true;
        String plain = ChatColor.stripColor(text);
        if (ChatFormat.isQQ(plain)) return false;
        Matcher match = GAME.matcher(plain);
        if (!match.find()) return true; // Command replies, login notices and action bars remain visible.
        return mode == 1 || (mode == 2 && match.group(1).equals(currentServer));
    }
    public static final class PacketGate extends ChannelOutboundHandlerAdapter {
        private final IntSupplier mode; private final Supplier<String> current;
        public PacketGate(IntSupplier mode, Supplier<String> current) { this.mode=mode; this.current=current; }
        @Override public void write(ChannelHandlerContext context, Object packet, ChannelPromise promise) throws Exception {
            String text = null;
            if (mode.getAsInt() != 0) {
                if (packet instanceof SystemChat) {
                    SystemChat chat = (SystemChat)packet;
                    if (chat.getPosition() != 2) text=chat.getMessage().toPlainText();
                } else if (packet instanceof Chat) {
                    Chat chat=(Chat)packet;
                    if (chat.getPosition() != 2) text=TextComponent.toPlainText(ComponentSerializer.parse(chat.getMessage()));
                }
            }
            if (text != null && !allows(mode.getAsInt(),text,current.get())) {
                ReferenceCountUtil.release(packet); promise.setSuccess(); return;
            }
            context.write(packet,promise);
        }
    }
    private void attach(ProxiedPlayer player) {
        if (!(player instanceof UserConnection)) return;
        Channel channel = ((UserConnection)player).getCh().getHandle();
        channel.eventLoop().execute(() -> {
            if (channel.pipeline().get(HANDLER)==null) channel.pipeline().addLast(HANDLER,new PacketGate(
                () -> modes.getOrDefault(player.getUniqueId(),0),
                () -> player.getServer()==null ? "" : player.getServer().getInfo().getName()));
        });
    }
    @EventHandler public void login(PostLoginEvent event) { attach(event.getPlayer()); }
    void close() {
        for (ProxiedPlayer player : plugin.getProxy().getPlayers()) if (player instanceof UserConnection) {
            Channel channel=((UserConnection)player).getCh().getHandle();
            channel.eventLoop().execute(() -> { if (channel.pipeline().get(HANDLER)!=null) channel.pipeline().remove(HANDLER); });
        }
    }
}
