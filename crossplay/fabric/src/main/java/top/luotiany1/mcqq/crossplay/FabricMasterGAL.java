package top.luotiany1.mcqq.crossplay;

import com.mojang.brigadier.builder.LiteralArgumentBuilder;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Map;
import java.util.function.BiConsumer;
import java.util.concurrent.TimeUnit;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.command.v2.ClientCommandRegistrationCallback;
import net.fabricmc.fabric.api.client.command.v2.FabricClientCommandSource;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.networking.v1.ClientConfigurationNetworking;
import net.fabricmc.fabric.api.client.networking.v1.ClientPlayConnectionEvents;
import net.fabricmc.fabric.api.client.networking.v1.ClientPlayNetworking;
import net.fabricmc.fabric.api.networking.v1.PayloadTypeRegistry;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.network.FriendlyByteBuf;
import net.minecraft.network.RegistryFriendlyByteBuf;
import net.minecraft.network.chat.Component;
import net.minecraft.network.codec.StreamCodec;
import net.minecraft.network.protocol.common.custom.CustomPacketPayload;
import net.minecraft.resources.Identifier;
import org.slf4j.LoggerFactory;

public final class FabricMasterGAL implements ClientModInitializer {
    private static final byte[] RESET = GalPacket.reset();
    private static final long TIMEOUT = TimeUnit.SECONDS.toNanos(6);
    private static final GalEndpoint<Minecraft> GAL = new GalEndpoint<>(true,
            (client, bytes) -> ClientPlayNetworking.send(new GalPayload(bytes)),
            failure -> LoggerFactory.getLogger("FabricMasterGAL")
                    .warn("MasterGAL handler failed: {}", failure.getClass().getSimpleName()));
    private static final GalEventApi<Minecraft> EVENTS = new GalEventApi<>(GAL);
    private int nextId;
    private long nextHello;
    private PendingProbe pending;

    public static GalApi<Minecraft> api() {
        return GAL;
    }

    public static void listenForEvent(String namespace, String system, String event,
                                      BiConsumer<Minecraft, Map<String, Object>> handler) {
        EVENTS.listenForEvent(namespace, system, event, handler);
    }

    public static boolean notifyToServer(String namespace, String system, String event, Map<String, Object> data) {
        return EVENTS.notifyPeer(Minecraft.getInstance(), namespace, system, event, data);
    }

    @Override
    public void onInitializeClient() {
        PayloadTypeRegistry.clientboundPlay().register(Payload.TYPE, Payload.CODEC);
        PayloadTypeRegistry.serverboundPlay().register(Payload.TYPE, Payload.CODEC);
        PayloadTypeRegistry.clientboundPlay().register(GalPayload.TYPE, GalPayload.CODEC);
        PayloadTypeRegistry.serverboundPlay().register(GalPayload.TYPE, GalPayload.CODEC);
        PayloadTypeRegistry.clientboundConfiguration().register(GalPayload.TYPE, GalPayload.CODEC);
        ClientPlayNetworking.registerGlobalReceiver(Payload.TYPE, (payload, context) -> receive(payload));
        ClientPlayNetworking.registerGlobalReceiver(GalPayload.TYPE, (payload, context) -> {
            if (Arrays.equals(payload.bytes(), RESET)) {
                resetSession(context.client());
            } else {
                GAL.receive(context.client(), payload.bytes());
            }
        });
        ClientConfigurationNetworking.registerGlobalReceiver(GalPayload.TYPE, (payload, context) -> {
            if (Arrays.equals(payload.bytes(), RESET)) {
                context.client().execute(() -> resetSession(context.client()));
            }
        });
        GAL.onRequest("mastergal:client_info", (client, payload) -> FabricLoader.getInstance()
                .getModContainer("minecraft").orElseThrow().getMetadata().getVersion()
                .getFriendlyString().getBytes(StandardCharsets.UTF_8));
        GAL.onEvent("mastergal:notice", (client, payload) -> {
            if (client.player != null) {
                client.player.sendSystemMessage(Component.literal(
                        "收到 Spigot 事件，当前世界：" + new String(payload, StandardCharsets.UTF_8)));
            }
        });
        GAL.onEvent("mastergal:menu_open", this::openMenu);
        ClientCommandRegistrationCallback.EVENT.register((dispatcher, registryAccess) -> {
            dispatcher.register(LiteralArgumentBuilder.<FabricClientCommandSource>literal("crossplayprobe")
                    .executes(context -> sendProbe(context.getSource())));
            dispatcher.register(LiteralArgumentBuilder.<FabricClientCommandSource>literal("crossplayevent")
                    .executes(context -> sendEvent(context.getSource())));
        });
        ClientPlayConnectionEvents.JOIN.register((handler, sender, client) -> resetSession(client));
        ClientPlayConnectionEvents.DISCONNECT.register((handler, client) -> resetSession(client));
        ClientTickEvents.END_CLIENT_TICK.register(client -> {
            long now = System.nanoTime();
            if (client.player != null && client.getConnection() != null && !GAL.isReady(client)
                    && (nextHello == 0 || now - nextHello >= 0) && ClientPlayNetworking.canSend(GalPayload.TYPE)) {
                nextHello = now + TimeUnit.SECONDS.toNanos(2);
                GAL.begin(client);
            }
            GAL.expire();
            if (pending != null && now - pending.deadline() >= 0) {
                pending.source().sendError(Component.literal("跨端通信请求超时。"));
                pending = null;
            }
        });
    }

    private void resetSession(Minecraft client) {
        pending = null;
        nextHello = 0;
        GAL.close(client);
        if (client.gui.screen() instanceof GalMenuScreen) {
            client.setScreenAndShow(null);
        }
    }

    private void openMenu(Minecraft client, byte[] bytes) {
        GalMenu.Frame frame = GalMenu.decode(bytes);
        if (frame == null || frame.menu == null) {
            return;
        }
        client.setScreenAndShow(new GalMenuScreen(client, frame.id, frame.menu));
    }

    private int sendEvent(FabricClientCommandSource source) {
        if (!GAL.sendEvent(Minecraft.getInstance(), "mastergal:client_event", new byte[0])) {
            source.sendError(Component.literal("当前后端未启用 MasterGAL 事件。"));
            return 0;
        }
        return 1;
    }

    private int sendProbe(FabricClientCommandSource source) {
        Minecraft client = Minecraft.getInstance();
        if (GAL.canRequest(client, "mastergal:world")) {
            GAL.request(client, "mastergal:world", new byte[0]).whenComplete((world, failure) -> {
                if (failure == null) {
                    source.sendFeedback(Component.literal("当前世界：" + new String(world, StandardCharsets.UTF_8)));
                } else {
                    source.sendError(Component.literal("当前后端暂未响应。"));
                }
            });
            return 1;
        }
        if (!ClientPlayNetworking.canSend(Payload.TYPE)) {
            source.sendError(Component.literal("当前服务器未启用跨端通信。"));
            return 0;
        }
        if (pending != null) {
            source.sendError(Component.literal("正在等待上一条跨端通信请求。"));
            return 0;
        }
        int id = ++nextId;
        pending = new PendingProbe(id, System.nanoTime() + TIMEOUT, source);
        ClientPlayNetworking.send(new Payload(ProbeFrame.request(id)));
        return 1;
    }

    private void receive(Payload payload) {
        ProbeFrame response = ProbeFrame.decode(payload.bytes());
        if (pending == null || response == null || response.id != pending.id()
                || response.kind == ProbeFrame.Kind.REQUEST) {
            return;
        }
        FabricClientCommandSource source = pending.source();
        pending = null;
        if (response.kind == ProbeFrame.Kind.SUCCESS) {
            source.sendFeedback(Component.literal("当前世界：" + response.world));
        } else {
            source.sendError(Component.literal("当前后端暂未响应。"));
        }
    }

    private record PendingProbe(int id, long deadline, FabricClientCommandSource source) {}

    private static final class GalMenuScreen extends Screen {
        private final Minecraft client;
        private final int menuId;
        private final GalMenu menu;
        private boolean replied;

        GalMenuScreen(Minecraft client, int menuId, GalMenu menu) {
            super(Component.literal(menu.title));
            this.client = client;
            this.menuId = menuId;
            this.menu = menu;
        }

        @Override
        protected void init() {
            int columns = 4;
            int gap = 6;
            int buttonWidth = Math.min(160, Math.max(72, (this.width - 32 - gap * (columns - 1)) / columns));
            int buttonHeight = 30;
            int totalWidth = columns * buttonWidth + (columns - 1) * gap;
            int left = (this.width - totalWidth) / 2;
            int top = Math.max(76, (this.height - 4 * buttonHeight - 3 * gap) / 2);
            for (int index = 0; index < menu.buttons.size(); index++) {
                final int selected = index;
                int x = left + (index % columns) * (buttonWidth + gap);
                int y = top + (index / columns) * (buttonHeight + gap);
                this.addRenderableWidget(Button.builder(Component.literal(menu.buttons.get(index).label),
                                button -> choose(selected))
                        .bounds(x, y, buttonWidth, buttonHeight).build());
            }
        }

        @Override
        public void extractRenderState(GuiGraphicsExtractor graphics, int mouseX, int mouseY, float delta) {
            this.extractBackground(graphics, mouseX, mouseY, delta);
            super.extractRenderState(graphics, mouseX, mouseY, delta);
            graphics.centeredText(this.font, this.title, this.width / 2, 28, 0xFFFFFF);
            graphics.centeredText(this.font, Component.literal(menu.content), this.width / 2, 48, 0xC8C8C8);
        }

        @Override
        public void onClose() {
            choose(GalMenu.CLOSED);
        }

        @Override
        public void removed() {
            reply(GalMenu.CLOSED);
            super.removed();
        }

        private void choose(int result) {
            reply(result);
            client.setScreenAndShow(null);
        }

        private void reply(int result) {
            if (!replied) {
                replied = true;
                if (client.getConnection() != null) {
                    GAL.sendEvent(client, "mastergal:menu_result", GalMenu.encodeResult(menuId, result));
                }
            }
        }
    }

    private static byte[] readPayload(FriendlyByteBuf buffer, int maximum) {
        if (buffer.readableBytes() > maximum) {
            buffer.skipBytes(buffer.readableBytes());
            return new byte[0];
        }
        byte[] bytes = new byte[buffer.readableBytes()];
        buffer.readBytes(bytes);
        return bytes;
    }

    private record GalPayload(byte[] bytes) implements CustomPacketPayload {
        static final Type<GalPayload> TYPE = new Type<>(Identifier.parse(GalPacket.CLIENT_CHANNEL));
        static final StreamCodec<FriendlyByteBuf, GalPayload> CODEC =
                StreamCodec.of((buffer, payload) -> buffer.writeBytes(payload.bytes()),
                        buffer -> new GalPayload(readPayload(buffer, GalPacket.MAX_FRAME)));

        @Override
        public Type<GalPayload> type() {
            return TYPE;
        }
    }

    private record Payload(byte[] bytes) implements CustomPacketPayload {
        static final Type<Payload> TYPE = new Type<>(Identifier.parse(ProbeFrame.CLIENT_CHANNEL));
        static final StreamCodec<RegistryFriendlyByteBuf, Payload> CODEC =
                StreamCodec.of((buffer, payload) -> buffer.writeBytes(payload.bytes()),
                        buffer -> new Payload(readPayload(buffer, ProbeFrame.MAX_BYTES)));

        @Override
        public Type<Payload> type() {
            return TYPE;
        }
    }
}
