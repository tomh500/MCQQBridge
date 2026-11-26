package top.luotiany1.mcqq.crossplay;

import io.netty.buffer.ByteBuf;
import io.netty.buffer.Unpooled;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.WeakHashMap;
import java.util.concurrent.TimeUnit;
import java.util.function.Consumer;
import net.minecraft.client.Minecraft;
import net.minecraft.client.network.NetHandlerPlayClient;
import net.minecraft.command.CommandBase;
import net.minecraft.command.ICommandSender;
import net.minecraft.network.NetworkManager;
import net.minecraft.network.PacketBuffer;
import net.minecraft.network.play.client.CPacketCustomPayload;
import net.minecraft.server.MinecraftServer;
import net.minecraft.util.text.TextComponentString;
import net.minecraftforge.client.ClientCommandHandler;
import net.minecraftforge.common.MinecraftForge;
import net.minecraftforge.fml.common.Mod;
import net.minecraftforge.fml.common.event.FMLInitializationEvent;
import net.minecraftforge.fml.common.eventhandler.SubscribeEvent;
import net.minecraftforge.fml.common.gameevent.TickEvent;
import net.minecraftforge.fml.common.network.FMLNetworkEvent;
import net.minecraftforge.fml.common.network.NetworkRegistry;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;

@Mod(modid = ForgeMaster.MOD_ID, name = "ForgeMaster", version = ForgeMaster.VERSION,
        acceptedMinecraftVersions = "[1.12.2]", clientSideOnly = true, acceptableRemoteVersions = "*")
public final class ForgeMaster {
    public static final String MOD_ID = "forgemaster";
    public static final String VERSION = "0.1.0";

    private static final Logger LOG = LogManager.getLogger("ForgeMaster");
    private static final byte[] EMPTY = new byte[0];
    private static final long HELLO_INTERVAL = TimeUnit.SECONDS.toNanos(2);
    private static final long PROBE_TIMEOUT = TimeUnit.SECONDS.toNanos(6);
    private static final GalEndpoint<Minecraft> GAL = new GalEndpoint<>(true,
            (client, bytes) -> send(client, GalPacket.CLIENT_CHANNEL, bytes),
            failure -> LOG.warn("MasterGAL handler failed", failure));
    private static final GalEventApi<Minecraft> EVENTS = new GalEventApi<>(GAL);
    private static final List<Consumer<Minecraft>> SESSION_CLOSED = new ArrayList<>();

    private final Map<NetworkManager, Set<String>> registrations = new WeakHashMap<>();
    private NetworkManager connection;
    private long lastHello;
    private int nextProbeId;
    private int pendingProbeId;
    private long probeDeadline;

    public static GalApi<Minecraft> api() {
        return GAL;
    }

    public static GalEventApi<Minecraft> events() {
        return EVENTS;
    }

    /** Called on the client thread after an active GAL session has been cleared. */
    public static void onSessionClosed(Consumer<Minecraft> listener) {
        SESSION_CLOSED.add(Objects.requireNonNull(listener));
    }

    @Mod.EventHandler
    public void init(FMLInitializationEvent event) {
        NetworkRegistry.INSTANCE.newEventDrivenChannel(GalPacket.CLIENT_CHANNEL).register(this);
        NetworkRegistry.INSTANCE.newEventDrivenChannel(ProbeFrame.CLIENT_CHANNEL).register(this);
        MinecraftForge.EVENT_BUS.register(this);

        GAL.onRequest("mastergal:client_info", (client, payload) -> "1.12.2".getBytes(StandardCharsets.UTF_8));
        GAL.onEvent("mastergal:notice", (client, payload) ->
                message(client, "收到 Spigot 事件，当前世界：" + new String(payload, StandardCharsets.UTF_8)));
        GAL.onEvent("mastergal:menu_open", (client, payload) -> {
            GalMenu.Frame frame = GalMenu.decode(payload);
            if (frame != null && frame.menu != null) {
                client.displayGuiScreen(new ForgeMasterMenu(frame.id, frame.menu));
            }
        });
        ClientCommandHandler.instance.registerCommand(new ClientCommand("crossplayprobe", this::probe));
        ClientCommandHandler.instance.registerCommand(new ClientCommand("crossplayevent", client -> {
            if (!GAL.sendEvent(client, "mastergal:client_event", EMPTY)) {
                message(client, "当前后端未启用 MasterGAL 事件。");
            }
        }));
    }

    @SubscribeEvent
    public void onRegistration(FMLNetworkEvent.CustomPacketRegistrationEvent<?> event) {
        if (!event.getSide().isClient()) {
            return;
        }
        boolean registered = "REGISTER".equals(event.getOperation());
        NetworkManager manager = event.getManager();
        Set<String> channels = event.getRegistrations();
        Minecraft client = Minecraft.getMinecraft();
        client.addScheduledTask(() -> {
            if (!manager.isChannelOpen()) {
                return;
            }
            Set<String> advertised = registrations.computeIfAbsent(manager, ignored -> new HashSet<>());
            if (registered) {
                advertised.addAll(channels);
            } else {
                advertised.removeAll(channels);
                if (manager == connection && channels.contains(GalPacket.CLIENT_CHANNEL)) {
                    closeSession(client);
                }
                if (manager == connection && channels.contains(ProbeFrame.CLIENT_CHANNEL)) {
                    pendingProbeId = 0;
                }
            }
        });
    }

    @SubscribeEvent
    public void onPayload(FMLNetworkEvent.ClientCustomPacketEvent event) {
        String channel = event.getPacket().channel();
        int limit = GalPacket.CLIENT_CHANNEL.equals(channel) ? GalPacket.MAX_FRAME : ProbeFrame.MAX_BYTES;
        ByteBuf buffer = event.getPacket().payload();
        if (buffer.readableBytes() > limit) {
            return;
        }
        byte[] bytes = new byte[buffer.readableBytes()];
        buffer.getBytes(buffer.readerIndex(), bytes);
        NetworkManager manager = event.getManager();
        Minecraft client = Minecraft.getMinecraft();
        client.addScheduledTask(() -> {
            if (manager != connection || manager != managerOf(client)) {
                return;
            }
            if (GalPacket.CLIENT_CHANNEL.equals(channel)) {
                GalPacket packet = GalPacket.decode(bytes);
                if (packet != null && packet.kind == GalPacket.Kind.RESET) {
                    closeSession(client);
                } else if (advertised(GalPacket.CLIENT_CHANNEL)) {
                    GAL.receive(client, bytes);
                }
            } else {
                receiveProbe(client, bytes);
            }
        });
    }

    @SubscribeEvent
    public void onDisconnect(FMLNetworkEvent.ClientDisconnectionFromServerEvent event) {
        NetworkManager manager = event.getManager();
        Minecraft client = Minecraft.getMinecraft();
        client.addScheduledTask(() -> {
            registrations.remove(manager);
            if (manager == connection) {
                connection = null;
                closeSession(client);
            }
        });
    }

    @SubscribeEvent
    public void onTick(TickEvent.ClientTickEvent event) {
        if (event.phase != TickEvent.Phase.END) {
            return;
        }
        Minecraft client = Minecraft.getMinecraft();
        NetworkManager active = managerOf(client);
        if (active != connection) {
            connection = active;
            closeSession(client);
        }
        long now = System.nanoTime();
        if (active != null && !GAL.isReady(client) && advertised(GalPacket.CLIENT_CHANNEL)
                && (lastHello == 0 || now - lastHello >= HELLO_INTERVAL)) {
            lastHello = now;
            GAL.begin(client);
        }
        GAL.expire();
        if (pendingProbeId != 0 && now - probeDeadline >= 0) {
            pendingProbeId = 0;
            message(client, "跨端通信请求超时。");
        }
    }

    private void closeSession(Minecraft client) {
        lastHello = 0;
        pendingProbeId = 0;
        boolean ready = GAL.isReady(client);
        GAL.close(client);
        if (client.currentScreen instanceof ForgeMasterMenu) {
            client.displayGuiScreen(null);
        }
        if (ready) {
            for (Consumer<Minecraft> listener : new ArrayList<>(SESSION_CLOSED)) {
                try {
                    listener.accept(client);
                } catch (RuntimeException failure) {
                    LOG.warn("MasterGAL session listener failed", failure);
                }
            }
        }
    }

    private boolean advertised(String channel) {
        Set<String> channels = registrations.get(connection);
        return channels != null && channels.contains(channel);
    }

    private void probe(Minecraft client) {
        if (GAL.canRequest(client, "mastergal:world")) {
            GAL.request(client, "mastergal:world", EMPTY).whenComplete((world, failure) -> {
                if (failure == null) {
                    message(client, "当前世界：" + new String(world, StandardCharsets.UTF_8));
                } else {
                    message(client, "当前后端暂未响应。");
                }
            });
            return;
        }
        if (!advertised(ProbeFrame.CLIENT_CHANNEL)) {
            message(client, "当前服务器未启用跨端通信。");
            return;
        }
        if (pendingProbeId != 0) {
            message(client, "正在等待上一条跨端通信请求。");
            return;
        }
        if (++nextProbeId == 0) {
            ++nextProbeId;
        }
        pendingProbeId = nextProbeId;
        probeDeadline = System.nanoTime() + PROBE_TIMEOUT;
        send(client, ProbeFrame.CLIENT_CHANNEL, ProbeFrame.request(pendingProbeId));
    }

    private void receiveProbe(Minecraft client, byte[] bytes) {
        ProbeFrame response = ProbeFrame.decode(bytes);
        if (pendingProbeId == 0 || response == null || response.id != pendingProbeId
                || response.kind == ProbeFrame.Kind.REQUEST) {
            return;
        }
        pendingProbeId = 0;
        message(client, response.kind == ProbeFrame.Kind.SUCCESS
                ? "当前世界：" + response.world : "当前后端暂未响应。");
    }

    private static NetworkManager managerOf(Minecraft client) {
        NetHandlerPlayClient handler = client.getConnection();
        if (handler == null || !handler.getNetworkManager().isChannelOpen()) {
            return null;
        }
        return handler.getNetworkManager();
    }

    private static void send(Minecraft client, String channel, byte[] bytes) {
        NetHandlerPlayClient handler = client.getConnection();
        if (handler != null) {
            handler.sendPacket(new CPacketCustomPayload(channel, new PacketBuffer(Unpooled.wrappedBuffer(bytes))));
        }
    }

    private static void message(Minecraft client, String message) {
        if (client.player != null) {
            client.player.sendMessage(new TextComponentString(message));
        }
    }

    private static final class ClientCommand extends CommandBase {
        private final String name;
        private final Consumer<Minecraft> action;

        ClientCommand(String name, Consumer<Minecraft> action) {
            this.name = name;
            this.action = action;
        }

        @Override
        public String getName() {
            return name;
        }

        @Override
        public String getUsage(ICommandSender sender) {
            return "/" + name;
        }

        @Override
        public int getRequiredPermissionLevel() {
            return 0;
        }

        @Override
        public void execute(MinecraftServer server, ICommandSender sender, String[] args) {
            action.accept(Minecraft.getMinecraft());
        }
    }
}
