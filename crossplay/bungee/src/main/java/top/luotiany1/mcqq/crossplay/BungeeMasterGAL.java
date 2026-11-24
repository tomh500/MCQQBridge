package top.luotiany1.mcqq.crossplay;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import net.md_5.bungee.api.CommandSender;
import net.md_5.bungee.api.chat.TextComponent;
import net.md_5.bungee.api.connection.ProxiedPlayer;
import net.md_5.bungee.api.connection.Server;
import net.md_5.bungee.api.event.PlayerDisconnectEvent;
import net.md_5.bungee.api.event.PluginMessageEvent;
import net.md_5.bungee.api.event.ServerSwitchEvent;
import net.md_5.bungee.api.plugin.Command;
import net.md_5.bungee.api.plugin.Listener;
import net.md_5.bungee.api.plugin.Plugin;
import net.md_5.bungee.event.EventHandler;
import org.geysermc.cumulus.form.SimpleForm;
import org.geysermc.cumulus.util.FormImage;
import org.geysermc.floodgate.api.FloodgateApi;

public final class BungeeMasterGAL extends Plugin implements Listener {
    private static final long PROBE_TIMEOUT = TimeUnit.SECONDS.toNanos(4);
    private final Map<UUID, PendingProbe> pending = new ConcurrentHashMap<>();
    private final Map<ProxiedPlayer, Server> galSessions = new ConcurrentHashMap<>();
    private final AtomicInteger sequence = new AtomicInteger();

    @Override
    public void onEnable() {
        getProxy().registerChannel(ProbeFrame.CLIENT_CHANNEL);
        getProxy().registerChannel(ProbeFrame.BACKEND_CHANNEL);
        getProxy().registerChannel(BedrockForm.CHANNEL);
        getProxy().registerChannel(GalPacket.CLIENT_CHANNEL);
        getProxy().registerChannel(GalPacket.BACKEND_CHANNEL);
        getProxy().getPluginManager().registerListener(this, this);
        getProxy().getScheduler().schedule(this, this::expireProbes, 1, 1, TimeUnit.SECONDS);
        getProxy().getPluginManager().registerCommand(this, new Command("crossplay") {
            @Override
            public void execute(CommandSender sender, String[] args) {
                if (sender instanceof ProxiedPlayer) {
                    openProbe((ProxiedPlayer) sender);
                }
            }
        });
    }

    @Override
    public void onDisable() {
        getProxy().getScheduler().cancel(this);
        pending.clear();
        galSessions.clear();
        getProxy().unregisterChannel(ProbeFrame.CLIENT_CHANNEL);
        getProxy().unregisterChannel(ProbeFrame.BACKEND_CHANNEL);
        getProxy().unregisterChannel(BedrockForm.CHANNEL);
        getProxy().unregisterChannel(GalPacket.CLIENT_CHANNEL);
        getProxy().unregisterChannel(GalPacket.BACKEND_CHANNEL);
    }

    @EventHandler
    public void onPluginMessage(PluginMessageEvent event) {
        String channel = event.getTag();
        if (GalPacket.CLIENT_CHANNEL.equals(channel) || GalPacket.BACKEND_CHANNEL.equals(channel)) {
            boolean intercepted = event.isCancelled();
            event.setCancelled(true);
            if (!intercepted) {
                relayGal(event);
            }
        } else if (ProbeFrame.CLIENT_CHANNEL.equals(channel)) {
            boolean intercepted = event.isCancelled();
            event.setCancelled(true);
            if (!intercepted && event.getSender() instanceof ProxiedPlayer) {
                ProxiedPlayer player = (ProxiedPlayer) event.getSender();
                ProbeFrame probe = ProbeFrame.decode(event.getData());
                if (probe != null && probe.kind == ProbeFrame.Kind.REQUEST
                        && !FloodgateApi.getInstance().isFloodgatePlayer(player.getUniqueId())) {
                    startProbe(player, player.getServer(), probe.id, false);
                }
            }
        } else if (ProbeFrame.BACKEND_CHANNEL.equals(channel)) {
            boolean intercepted = event.isCancelled();
            event.setCancelled(true);
            if (!intercepted && event.getSender() instanceof Server
                    && event.getReceiver() instanceof ProxiedPlayer) {
                completeProbe((ProxiedPlayer) event.getReceiver(), (Server) event.getSender(), event.getData());
            }
        } else if (BedrockForm.CHANNEL.equals(channel)) {
            boolean intercepted = event.isCancelled();
            event.setCancelled(true);
            if (!intercepted && event.getSender() instanceof Server
                    && event.getReceiver() instanceof ProxiedPlayer) {
                openBackendForm((ProxiedPlayer) event.getReceiver(), (Server) event.getSender(), event.getData());
            }
        }
    }

    private void relayGal(PluginMessageEvent event) {
        GalPacket frame = GalPacket.decode(event.getData());
        if (frame == null || frame.kind == GalPacket.Kind.RESET) {
            return;
        }
        if (GalPacket.CLIENT_CHANNEL.equals(event.getTag()) && event.getSender() instanceof ProxiedPlayer
                && frame.kind != GalPacket.Kind.WELCOME) {
            ProxiedPlayer player = (ProxiedPlayer) event.getSender();
            Server current = player.getServer();
            if (current == null || FloodgateApi.getInstance().isFloodgatePlayer(player.getUniqueId())) {
                return;
            }
            if (frame.kind == GalPacket.Kind.HELLO) {
                galSessions.put(player, current);
            }
            if (galSessions.get(player) == current) {
                current.sendData(GalPacket.BACKEND_CHANNEL, event.getData());
            }
        } else if (GalPacket.BACKEND_CHANNEL.equals(event.getTag()) && event.getSender() instanceof Server
                && event.getReceiver() instanceof ProxiedPlayer && frame.kind != GalPacket.Kind.HELLO) {
            ProxiedPlayer player = (ProxiedPlayer) event.getReceiver();
            if (player.getServer() == event.getSender() && galSessions.get(player) == event.getSender()) {
                player.sendData(GalPacket.CLIENT_CHANNEL, event.getData());
            }
        }
    }

    private void openBackendForm(ProxiedPlayer player, Server server, byte[] bytes) {
        if (player.getServer() != server) {
            return;
        }
        BedrockForm.Frame request = BedrockForm.decode(bytes);
        if (request == null || request.form == null) {
            return;
        }
        FloodgateApi floodgate = FloodgateApi.getInstance();
        UUID uuid = player.getUniqueId();
        if (!floodgate.isFloodgatePlayer(uuid)) {
            replyForm(player, server, request.id, BedrockForm.UNAVAILABLE);
            return;
        }
        BedrockForm descriptor = request.form;
        SimpleForm.Builder form = SimpleForm.builder().title(descriptor.title).content(descriptor.content);
        for (BedrockForm.Button button : descriptor.buttons) {
            if (button.texture.isEmpty()) {
                form.button(button.label);
            } else {
                form.button(button.label, FormImage.Type.PATH, button.texture);
            }
        }
        boolean sent = floodgate.sendForm(uuid, form.validResultHandler(response -> {
            int index = response.clickedButtonId();
            replyForm(player, server, request.id,
                    index >= 0 && index < descriptor.buttons.size() ? index : BedrockForm.CLOSED);
        }).closedOrInvalidResultHandler(() -> replyForm(player, server, request.id, BedrockForm.CLOSED)));
        if (!sent) {
            replyForm(player, server, request.id, BedrockForm.UNAVAILABLE);
        }
    }

    private void replyForm(ProxiedPlayer player, Server server, int id, int index) {
        if (player.isConnected() && player.getServer() == server) {
            server.sendData(BedrockForm.CHANNEL, BedrockForm.encodeResult(id, index));
        }
    }

    private void openProbe(ProxiedPlayer player) {
        UUID uuid = player.getUniqueId();
        FloodgateApi floodgate = FloodgateApi.getInstance();
        if (!floodgate.isFloodgatePlayer(uuid)) {
            player.sendMessage(new TextComponent("请在 Fabric 客户端使用 /crossplayprobe。"));
            return;
        }
        Server server = player.getServer();
        boolean sent = floodgate.sendForm(uuid, SimpleForm.builder()
                .title("跨端通信")
                .content("查询当前 Spigot 后端的世界。")
                .button("查询", FormImage.Type.PATH, "textures/ui/mastergal/probe.png")
                .validResultHandler(response -> {
                    if (response.clickedButtonId() == 0 && player.getServer() == server) {
                        startProbe(player, server, 0, true);
                    }
                }));
        if (!sent) {
            player.sendMessage(new TextComponent("跨端通信表单暂时无法打开。"));
        }
    }

    private void startProbe(ProxiedPlayer player, Server server, int clientId, boolean bedrock) {
        if (server == null || !player.isConnected() || player.getServer() != server) {
            return;
        }
        UUID uuid = player.getUniqueId();
        PendingProbe probe = new PendingProbe(player, server, sequence.incrementAndGet(), clientId, bedrock);
        if (pending.putIfAbsent(uuid, probe) != null) {
            return;
        }
        server.sendData(ProbeFrame.BACKEND_CHANNEL, ProbeFrame.request(probe.backendId));
    }

    private void expireProbes() {
        long now = System.nanoTime();
        pending.forEach((uuid, probe) -> {
            if (now - probe.startedAt >= PROBE_TIMEOUT && pending.remove(uuid, probe)) {
                reply(probe, null);
            }
        });
    }

    private void completeProbe(ProxiedPlayer player, Server server, byte[] bytes) {
        UUID uuid = player.getUniqueId();
        PendingProbe probe = pending.get(uuid);
        if (probe == null || probe.player != player || probe.server != server) {
            return;
        }
        ProbeFrame response = ProbeFrame.decode(bytes);
        if (response == null || response.id != probe.backendId || response.kind == ProbeFrame.Kind.REQUEST) {
            return;
        }
        if (pending.remove(uuid, probe)) {
            reply(probe, response.kind == ProbeFrame.Kind.SUCCESS ? response.world : null);
        }
    }

    private void reply(PendingProbe probe, String world) {
        if (!probe.player.isConnected() || probe.player.getServer() != probe.server) {
            return;
        }
        if (probe.bedrock) {
            FloodgateApi.getInstance().sendForm(probe.player.getUniqueId(), SimpleForm.builder()
                    .title("跨端通信")
                    .content(world == null ? "当前后端暂未响应。" : "当前世界：" + world)
                    .button("关闭"));
        } else {
            byte[] response = world == null
                    ? ProbeFrame.unavailable(probe.clientId)
                    : ProbeFrame.success(probe.clientId, world);
            probe.player.sendData(ProbeFrame.CLIENT_CHANNEL, response);
        }
    }

    @EventHandler
    public void onSwitch(ServerSwitchEvent event) {
        ProxiedPlayer player = event.getPlayer();
        Server previous = galSessions.get(player);
        if (previous != null && previous != player.getServer() && galSessions.remove(player, previous)) {
            player.sendData(GalPacket.CLIENT_CHANNEL, GalPacket.reset());
        }
        pending.computeIfPresent(player.getUniqueId(), (uuid, probe) ->
                probe.player == player && probe.server != player.getServer() ? null : probe);
    }

    @EventHandler
    public void onDisconnect(PlayerDisconnectEvent event) {
        ProxiedPlayer player = event.getPlayer();
        galSessions.remove(player);
        pending.computeIfPresent(player.getUniqueId(), (uuid, probe) -> probe.player == player ? null : probe);
    }

    private static final class PendingProbe {
        final ProxiedPlayer player;
        final Server server;
        final int backendId;
        final int clientId;
        final boolean bedrock;
        final long startedAt = System.nanoTime();

        PendingProbe(ProxiedPlayer player, Server server, int backendId, int clientId, boolean bedrock) {
            this.player = player;
            this.server = server;
            this.backendId = backendId;
            this.clientId = clientId;
            this.bedrock = bedrock;
        }
    }
}
