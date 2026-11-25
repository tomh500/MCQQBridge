package top.luotiany1.mcqq.crossplay;

import java.util.Arrays;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import java.util.function.IntConsumer;
import java.util.function.BiConsumer;
import org.bukkit.Bukkit;
import org.bukkit.Location;
import org.bukkit.World;
import org.bukkit.command.Command;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.inventory.InventoryOpenEvent;
import org.bukkit.event.player.PlayerChangedWorldEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.plugin.messaging.Messenger;
import org.bukkit.scheduler.BukkitTask;

public final class SpigotMasterGAL extends JavaPlugin implements Listener {
    private final GalEndpoint<Player> gal = new GalEndpoint<>(false,
            (player, bytes) -> player.sendPluginMessage(this, GalPacket.BACKEND_CHANNEL, bytes),
            failure -> getLogger().warning("MasterGAL handler failed: " + failure.getClass().getSimpleName()));
    private final GalEventApi<Player> events = new GalEventApi<>(gal);
    private final Set<UUID> bedrockPlayers = new HashSet<>();
    private final Map<UUID, PendingForm> forms = new HashMap<>();
    private final Map<UUID, PendingMenu> menus = new HashMap<>();
    private int nextFormId;
    private int nextMenuId;

    @Override
    public void onEnable() {
        Messenger messenger = getServer().getMessenger();
        messenger.registerOutgoingPluginChannel(this, ProbeFrame.BACKEND_CHANNEL);
        messenger.registerIncomingPluginChannel(this, ProbeFrame.BACKEND_CHANNEL, this::probe);
        messenger.registerOutgoingPluginChannel(this, BedrockForm.CHANNEL);
        messenger.registerIncomingPluginChannel(this, BedrockForm.CHANNEL, this::formResponse);
        messenger.registerOutgoingPluginChannel(this, GalPacket.BACKEND_CHANNEL);
        messenger.registerIncomingPluginChannel(this, GalPacket.BACKEND_CHANNEL,
                (channel, player, bytes) -> gal.receive(player, bytes));
        gal.onRequest("mastergal:world", (player, payload) ->
                player.getWorld().getName().getBytes(StandardCharsets.UTF_8));
        gal.onEvent("mastergal:client_event", (player, payload) ->
                gal.sendEvent(player, "mastergal:notice", player.getWorld().getName().getBytes(StandardCharsets.UTF_8)));
        gal.onEvent("mastergal:menu_result", this::menuResponse);
        getServer().getPluginManager().registerEvents(this, this);
        getServer().getScheduler().runTaskTimer(this, gal::expire, 20, 20);
    }

    @Override
    public void onDisable() {
        bedrockPlayers.clear();
        forms.values().forEach(pending -> pending.timeout.cancel());
        forms.clear();
        menus.values().forEach(pending -> pending.timeout.cancel());
        menus.clear();
        getServer().getOnlinePlayers().forEach(gal::close);
    }

    public GalApi<Player> api() {
        return gal;
    }

    public void listenForEvent(String namespace, String system, String event,
                               BiConsumer<Player, Map<String, Object>> handler) {
        events.listenForEvent(namespace, system, event, handler);
    }

    public boolean notifyToClient(Player player, String namespace, String system, String event,
                                  Map<String, Object> data) {
        return events.notifyPeer(player, namespace, system, event, data);
    }

    public int notifyToMultiClients(List<Player> players, String namespace, String system, String event,
                                    Map<String, Object> data) {
        int sent = 0;
        for (Player player : new LinkedHashSet<>(players)) {
            if (notifyToClient(player, namespace, system, event, data)) {
                sent++;
            }
        }
        return sent;
    }

    public int notifyToClientsNearby(Player except, Location origin, double distance, String namespace,
                                     String system, String event, Map<String, Object> data) {
        World world = Objects.requireNonNull(origin.getWorld());
        if (!Double.isFinite(distance) || distance < 0) {
            throw new IllegalArgumentException("Distance must be finite and nonnegative");
        }
        int sent = 0;
        double radiusSquared = distance * distance;
        for (Player player : world.getPlayers()) {
            if (!player.equals(except) && player.getLocation().distanceSquared(origin) <= radiusSquared
                    && notifyToClient(player, namespace, system, event, data)) {
                sent++;
            }
        }
        return sent;
    }

    /**
     * Open a server-authored menu on a compatible Fabric client or through Floodgate for Bedrock.
     * Older Java clients return false so the caller can keep using its native inventory menu.
     */
    public boolean showMenu(Player player, GalMenu menu, IntConsumer onResult) {
        if (!Bukkit.isPrimaryThread()) {
            throw new IllegalStateException("Use the Spigot server thread to open a menu");
        }
        Objects.requireNonNull(menu);
        Objects.requireNonNull(onResult);
        if (!isEnabled() || !player.isOnline()) {
            return false;
        }
        UUID uuid = player.getUniqueId();
        if (menus.containsKey(uuid)) {
            return false;
        }
        if (gal.canSendEvent(player, "mastergal:menu_open")) {
            int id = ++nextMenuId;
            BukkitTask timeout = getServer().getScheduler().runTaskLater(this, () ->
                    finishMenu(uuid, id, GalMenu.UNAVAILABLE), 1200L);
            menus.put(uuid, new PendingMenu(id, menu.buttons.size(), onResult, timeout));
            if (gal.sendEvent(player, "mastergal:menu_open", menu.encodeOpen(id))) {
                return true;
            }
            menus.remove(uuid);
            timeout.cancel();
            return false;
        }
        return showBedrockMenu(player, menu, onResult);
    }

    /** Whether the current backend connection was identified as Bedrock by the proxy. */
    public boolean supportsBedrockForms(Player player) {
        return isEnabled() && player.isOnline() && bedrockPlayers.contains(player.getUniqueId());
    }

    /** Render a button menu only for Bedrock. Java players can continue into the native inventory. */
    public boolean showBedrockMenu(Player player, GalMenu menu, IntConsumer onResult) {
        List<BedrockForm.Button> buttons = new java.util.ArrayList<>();
        for (GalMenu.Button button : menu.buttons) {
            buttons.add(new BedrockForm.Button(button.label, button.texture));
        }
        return showBedrockForm(player, new BedrockForm(menu.title, menu.content, buttons), onResult);
    }

    private void probe(String channel, Player player, byte[] bytes) {
        ProbeFrame request = ProbeFrame.decode(bytes);
        if (request == null || request.kind != ProbeFrame.Kind.REQUEST) {
            return;
        }
        player.sendPluginMessage(this, channel, ProbeFrame.success(request.id, player.getWorld().getName()));
    }

    /**
     * Send a Bedrock form on the server thread. The callback receives a zero-based button index,
     * CLOSED, or UNAVAILABLE. Returns false if the request was not dispatched.
     */
    public boolean showBedrockForm(Player player, BedrockForm form, IntConsumer onResult) {
        if (!Bukkit.isPrimaryThread()) {
            throw new IllegalStateException("Use the Spigot server thread to open a form");
        }
        Objects.requireNonNull(onResult);
        UUID uuid = player.getUniqueId();
        if (!supportsBedrockForms(player) || forms.containsKey(uuid)) {
            return false;
        }
        int id = ++nextFormId;
        byte[] bytes = form.encodeOpen(id);
        BukkitTask timeout = getServer().getScheduler().runTaskLater(this, () -> {
            PendingForm pending = forms.remove(uuid);
            if (pending != null) {
                pending.onResult.accept(BedrockForm.UNAVAILABLE);
            }
        }, 1200L);
        forms.put(uuid, new PendingForm(id, form.buttons.size(), onResult, timeout));
        try {
            player.sendPluginMessage(this, BedrockForm.CHANNEL, bytes);
        } catch (RuntimeException sendFailure) {
            forms.remove(uuid);
            timeout.cancel();
            throw sendFailure;
        }
        return true;
    }

    private void formResponse(String channel, Player player, byte[] bytes) {
        UUID uuid = player.getUniqueId();
        if (Arrays.equals(bytes, BedrockForm.AVAILABLE)) {
            bedrockPlayers.add(uuid);
            return;
        }
        PendingForm pending = forms.get(uuid);
        if (pending == null) {
            return;
        }
        BedrockForm.Frame response = BedrockForm.decode(bytes);
        if (response != null && response.form == null && response.id == pending.id
                && response.index < pending.buttonCount) {
            finishForm(uuid, response.index);
        }
    }

    private void menuResponse(Player player, byte[] bytes) {
        UUID uuid = player.getUniqueId();
        PendingMenu pending = menus.get(uuid);
        GalMenu.Frame response = GalMenu.decode(bytes);
        if (pending != null && response != null && response.menu == null
                && response.id == pending.id && response.index >= GalMenu.CLOSED
                && response.index < pending.buttonCount) {
            finishMenu(uuid, response.id, response.index);
        }
    }

    private void finishMenu(UUID uuid, int id, int result) {
        PendingMenu pending = menus.get(uuid);
        if (pending != null && pending.id == id && menus.remove(uuid, pending)) {
            pending.timeout.cancel();
            pending.onResult.accept(result);
        }
    }

    private void finishForm(UUID uuid, int result) {
        PendingForm pending = forms.remove(uuid);
        if (pending != null) {
            pending.timeout.cancel();
            pending.onResult.accept(result);
        }
    }

    @EventHandler
    public void onPlayerQuit(PlayerQuitEvent event) {
        Player player = event.getPlayer();
        gal.close(player);
        bedrockPlayers.remove(player.getUniqueId());
        discardMenus(player.getUniqueId());
    }

    @EventHandler
    public void onWorldChange(PlayerChangedWorldEvent event) {
        discardMenus(event.getPlayer().getUniqueId());
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onInventoryOpen(InventoryOpenEvent event) {
        discardMenus(event.getPlayer().getUniqueId());
    }

    private void discardMenus(UUID uuid) {
        PendingForm pending = forms.remove(uuid);
        if (pending != null) {
            pending.timeout.cancel();
        }
        PendingMenu menu = menus.remove(uuid);
        if (menu != null) {
            menu.timeout.cancel();
        }
    }

    @Override
    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (!(sender instanceof Player)) {
            return false;
        }
        Player player = (Player) sender;
        if (command.getName().equals("mastergalclient")) {
            gal.request(player, "mastergal:client_info", new byte[0]).whenComplete((version, failure) -> {
                if (player.isOnline()) {
                    player.sendMessage(failure == null
                            ? "Fabric 响应版本：" + new String(version, StandardCharsets.UTF_8)
                            : "当前连接未返回 Fabric 客户端版本。");
                }
            });
            return true;
        }
        BedrockForm form = new BedrockForm("MasterGAL", "测试服务端表单回调和资源包图标。",
                Arrays.asList(new BedrockForm.Button("确认", "textures/ui/mastergal/probe.png"),
                        new BedrockForm.Button("返回")));
        boolean sent = showBedrockForm(player, form, result -> {
            if (result >= 0) {
                sender.sendMessage("SpigotMasterGAL 收到按钮 " + (result + 1));
            } else if (result == BedrockForm.UNAVAILABLE) {
                sender.sendMessage("基岩版表单暂不可用。");
            }
        });
        if (!sent) {
            sender.sendMessage("当前连接无法打开新表单。");
        }
        return true;
    }

    private static final class PendingForm {
        final int id;
        final int buttonCount;
        final IntConsumer onResult;
        final BukkitTask timeout;

        PendingForm(int id, int buttonCount, IntConsumer onResult, BukkitTask timeout) {
            this.id = id;
            this.buttonCount = buttonCount;
            this.onResult = onResult;
            this.timeout = timeout;
        }
    }

    private static final class PendingMenu {
        final int id;
        final int buttonCount;
        final IntConsumer onResult;
        final BukkitTask timeout;

        PendingMenu(int id, int buttonCount, IntConsumer onResult, BukkitTask timeout) {
            this.id = id;
            this.buttonCount = buttonCount;
            this.onResult = onResult;
            this.timeout = timeout;
        }
    }
}
